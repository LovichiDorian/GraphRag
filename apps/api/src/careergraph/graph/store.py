"""Async Neo4j access layer: schema, atomic graph replacement, search and guarded Cypher."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, LiteralString

import neo4j
import orjson
from neo4j import AsyncGraphDatabase, AsyncManagedTransaction, unit_of_work
from neo4j.graph import Node, Path, Relationship

from careergraph.graph.models import KnowledgeGraph
from careergraph.graph.schema import constraint_statements, index_statements
from careergraph.logs import get_logger
from careergraph.settings import Settings
from careergraph.text import STOPWORDS

log = get_logger(__name__)

_WRITE_BATCH = 500
_HIDDEN_PROPS = {"embedding", "aliases_text"}

# Defence in depth for LLM-generated Cypher: keyword denylist *and* a READ
# transaction (the server rejects any write with Neo.ClientError.Statement.AccessMode).
_FORBIDDEN_CYPHER = re.compile(
    r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH|CALL|ALTER|RENAME|GRANT|DENY|REVOKE|"
    r"TERMINATE|USE|FINISH|INSERT)\b|apoc\.|dbms\.|db\.",
    re.IGNORECASE,
)


class UnsafeCypherError(ValueError):
    pass


def _clean(value: Any) -> Any:
    """Convert driver graph types into JSON-friendly structures, dropping embeddings."""
    if isinstance(value, Node):
        props = {k: _clean(v) for k, v in value.items() if k not in _HIDDEN_PROPS}
        return {"labels": sorted(value.labels - {"Entity"}), **props}
    if isinstance(value, Relationship):
        return {"type": value.type, **{k: _clean(v) for k, v in value.items()}}
    if isinstance(value, Path):
        return {
            "nodes": [_clean(n) for n in value.nodes],
            "relationships": [_clean(r) for r in value.relationships],
        }
    if isinstance(value, list):
        if len(value) > 64 and all(isinstance(v, float) for v in value):
            return f"<vector[{len(value)}]>"
        return [_clean(v) for v in value]
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if k not in _HIDDEN_PROPS}
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return value


def validate_readonly_cypher(query: str) -> str:
    stripped = query.strip().rstrip(";").strip()
    if not stripped:
        raise UnsafeCypherError("Empty query")
    if ";" in stripped:
        raise UnsafeCypherError("Multiple statements are not allowed")
    # Ignore string literals when scanning for forbidden keywords.
    without_strings = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", stripped)
    if match := _FORBIDDEN_CYPHER.search(without_strings):
        raise UnsafeCypherError(f"Forbidden clause: {match.group(0)}")
    if not re.search(r"\bRETURN\b", without_strings, re.IGNORECASE):
        raise UnsafeCypherError("Query must RETURN something")
    return stripped


class Neo4jStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = settings.neo4j_database
        self.driver = AsyncGraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password.get_secret_value()),
            notifications_min_severity="OFF",
            max_connection_pool_size=20,
            connection_acquisition_timeout=10,
        )

    async def close(self) -> None:
        await self.driver.close()

    async def ping(self) -> bool:
        try:
            await self.driver.verify_connectivity()
        except Exception:  # noqa: BLE001 - health probe must never raise
            return False
        return True

    # ── generic helpers ───────────────────────────────────────────────────────
    async def read(self, query: LiteralString, **params: Any) -> list[dict[str, Any]]:
        records, _, _ = await self.driver.execute_query(
            query, params, database_=self.database, routing_=neo4j.RoutingControl.READ
        )
        return [record.data() for record in records]

    async def write(self, query: LiteralString, **params: Any) -> None:
        await self.driver.execute_query(query, params, database_=self.database)

    # ── schema ────────────────────────────────────────────────────────────────
    async def ensure_schema(self) -> None:
        for statement in [*constraint_statements(), *index_statements(self.settings.embedding_dim)]:
            await self.write(statement)
        await self.write("CALL db.awaitIndexes(120)")

    # ── ingestion: atomic replacement of the whole knowledge graph ────────────
    async def replace_graph(self, graph: KnowledgeGraph, version: str) -> None:
        entities_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for entity in graph.entities.values():
            props: dict[str, Any] = {
                **entity.props,
                "id": entity.id,
                "name": entity.name,
                "type": entity.type.value,
                "description": entity.description,
                "aliases": entity.aliases,
                "aliases_text": " | ".join(entity.aliases),
                "url": entity.url,
                "sources": entity.sources,
            }
            entities_by_type[entity.type.value].append(
                {"props": {k: v for k, v in props.items() if v is not None}, "embedding": entity.embedding}
            )
        relations_by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for relation in graph.relations:
            relations_by_type[relation.type.value].append(
                {"source": relation.source, "target": relation.target, "props": relation.props}
            )
        documents = [doc.model_dump() for doc in graph.documents]
        chunks = [chunk.model_dump() for chunk in graph.chunks]
        communities = [community.model_dump() for community in graph.communities]
        meta = {
            "version": version,
            "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "stats": orjson.dumps(graph.meta).decode(),
        }

        async def work(tx: AsyncManagedTransaction) -> None:
            await tx.run("MATCH (n) WHERE n:Entity OR n:Document OR n:Chunk OR n:Community DETACH DELETE n")
            for label, rows in entities_by_type.items():
                query = (
                    f"UNWIND $rows AS row CREATE (n:Entity:{label}) SET n = row.props "
                    "WITH n, row WHERE row.embedding IS NOT NULL "
                    "CALL db.create.setNodeVectorProperty(n, 'embedding', row.embedding)"
                )
                for batch in _batches(rows):
                    await tx.run(query, rows=batch)
            for rel_type, rows in relations_by_type.items():
                query = (
                    "UNWIND $rows AS row MATCH (a:Entity {id: row.source}), (b:Entity {id: row.target}) "
                    f"CREATE (a)-[r:{rel_type}]->(b) SET r = row.props"
                )
                for batch in _batches(rows):
                    await tx.run(query, rows=batch)
            for batch in _batches(documents):
                await tx.run(
                    "UNWIND $rows AS row CREATE (d:Document {id: row.id}) "
                    "SET d.title = row.title, d.kind = row.kind, d.source = row.source, d.url = row.url, "
                    "    d.updated_at = row.updated_at "
                    "WITH d, row UNWIND row.describes AS eid MATCH (e:Entity {id: eid}) CREATE (d)-[:DESCRIBES]->(e)",
                    rows=batch,
                )
            for batch in _batches(chunks):
                await tx.run(
                    "UNWIND $rows AS row MATCH (d:Document {id: row.doc_id}) "
                    "CREATE (c:Chunk {id: row.id}) SET c.title = row.title, c.text = row.text, c.ord = row.ord, "
                    "    c.doc_id = row.doc_id "
                    "CREATE (c)-[:PART_OF]->(d) "
                    "WITH c, row CALL (c, row) { WITH c, row WHERE row.embedding IS NOT NULL "
                    "  CALL db.create.setNodeVectorProperty(c, 'embedding', row.embedding) } "
                    "WITH c, row UNWIND row.mentions AS eid MATCH (e:Entity {id: eid}) CREATE (c)-[:MENTIONS]->(e)",
                    rows=batch,
                )
            for batch in _batches(communities):
                await tx.run(
                    "UNWIND $rows AS row CREATE (c:Community {id: row.id}) "
                    "SET c.title = row.title, c.summary = row.summary, c.key_entities = row.key_entities, "
                    "    c.size = size(row.members) "
                    "WITH c, row CALL (c, row) { WITH c, row WHERE row.embedding IS NOT NULL "
                    "  CALL db.create.setNodeVectorProperty(c, 'embedding', row.embedding) } "
                    "WITH c, row UNWIND row.members AS eid MATCH (e:Entity {id: eid}) "
                    "CREATE (e)-[:IN_COMMUNITY]->(c) SET e.community = c.id",
                    rows=batch,
                )
            await tx.run("MERGE (m:Meta {key: 'graph'}) SET m += $meta", meta=meta)

        async with self.driver.session(database=self.database) as session:
            await session.execute_write(work)
        log.info(
            "graph.replaced",
            version=version,
            entities=len(graph.entities),
            relations=len(graph.relations),
            chunks=len(graph.chunks),
            communities=len(graph.communities),
        )

    async def get_cached_answer(self, key: str) -> dict[str, Any] | None:
        rows = await self.read(
            "MATCH (a:CachedAnswer {key: $key}) RETURN a.revision AS revision, a.created AS created, a.events AS events",
            key=key,
        )
        return rows[0] if rows else None

    async def save_cached_answer(self, key: str, revision: str, events: str, created: float) -> None:
        await self.write(
            "MERGE (a:CachedAnswer {key: $key}) SET a.revision = $revision, a.events = $events, a.created = $created",
            key=key,
            revision=revision,
            events=events,
            created=created,
        )

    async def graph_meta(self) -> dict[str, Any] | None:
        rows = await self.read("MATCH (m:Meta {key: 'graph'}) RETURN m {.*} AS meta")
        if not rows:
            return None
        meta = dict(rows[0]["meta"])
        if isinstance(meta.get("stats"), str):
            meta["stats"] = orjson.loads(meta["stats"])
        return meta

    # ── retrieval primitives ──────────────────────────────────────────────────
    async def vector_search(self, index: str, embedding: Sequence[float], k: int) -> list[tuple[str, float]]:
        if index not in {"entity_embedding", "chunk_embedding", "community_embedding"}:
            raise ValueError(index)
        rows = await self.read(
            "CALL db.index.vector.queryNodes($index, $k, $embedding) YIELD node, score "
            "RETURN node.id AS id, score",
            index=index,
            k=k,
            embedding=list(embedding),
        )
        return [(row["id"], float(row["score"])) for row in rows]

    async def fulltext_search(self, index: str, text: str, k: int) -> list[tuple[str, float]]:
        if index not in {"entity_fulltext", "chunk_fulltext"}:
            raise ValueError(index)
        lucene = _lucene_query(text)
        if not lucene:
            return []
        rows = await self.read(
            "CALL db.index.fulltext.queryNodes($index, $q, {limit: $k}) YIELD node, score "
            "RETURN node.id AS id, score",
            index=index,
            q=lucene,
            k=k,
        )
        return [(row["id"], float(row["score"])) for row in rows]

    async def chunks_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        return await self.read(
            "UNWIND $ids AS cid MATCH (c:Chunk {id: cid})-[:PART_OF]->(d:Document) "
            "OPTIONAL MATCH (c)-[:MENTIONS]->(e:Entity) "
            "RETURN c.id AS id, c.title AS title, c.text AS text, d.id AS doc_id, d.title AS doc_title, "
            "       d.kind AS kind, d.url AS url, collect(e.id) AS mentions",
            ids=list(ids),
        )

    async def communities_by_ids(self, ids: Sequence[str]) -> list[dict[str, Any]]:
        return await self.read(
            "UNWIND $ids AS cid MATCH (c:Community {id: cid}) "
            "RETURN c.id AS id, c.title AS title, c.summary AS summary, c.key_entities AS key_entities",
            ids=list(ids),
        )

    async def all_communities(self) -> list[dict[str, Any]]:
        return await self.read(
            "MATCH (c:Community) RETURN c.id AS id, c.title AS title, c.summary AS summary, "
            "c.key_entities AS key_entities, c.size AS size ORDER BY c.size DESC"
        )

    async def entity_evidence(self, entity_id: str, limit: int = 6) -> list[dict[str, Any]]:
        return await self.read(
            "MATCH (c:Chunk)-[:MENTIONS]->(:Entity {id: $id}) MATCH (c)-[:PART_OF]->(d:Document) "
            "RETURN c.id AS id, c.title AS title, left(c.text, 600) AS text, d.title AS doc_title, "
            "       d.url AS url, d.kind AS kind ORDER BY d.kind = 'cv' DESC, c.ord LIMIT $limit",
            id=entity_id,
            limit=limit,
        )

    async def load_graph_rows(self) -> dict[str, list[dict[str, Any]]]:
        entities = await self.read("MATCH (n:Entity) RETURN n {.*, embedding: null, aliases_text: null} AS n")
        relations = await self.read(
            "MATCH (a:Entity)-[r]->(b:Entity) RETURN a.id AS source, b.id AS target, type(r) AS type, "
            "properties(r) AS props"
        )
        mentions = await self.read(
            "MATCH (c:Chunk)-[:MENTIONS]->(e:Entity) RETURN e.id AS entity, collect(c.id) AS chunks"
        )
        return {"entities": [row["n"] for row in entities], "relations": relations, "mentions": mentions}

    async def run_readonly_cypher(
        self, query: str, params: dict[str, Any] | None = None, *, limit: int = 50, timeout_s: float = 5.0
    ) -> list[dict[str, Any]]:
        safe = validate_readonly_cypher(query)

        @unit_of_work(timeout=timeout_s)
        async def work(tx: AsyncManagedTransaction) -> list[dict[str, Any]]:
            result = await tx.run(safe, params or {})
            records = await result.fetch(limit)
            return [_clean(record.data()) for record in records]

        async with self.driver.session(
            database=self.database, default_access_mode=neo4j.READ_ACCESS
        ) as session:
            return await session.execute_read(work)


def _batches(rows: list[dict[str, Any]], size: int = _WRITE_BATCH) -> list[list[dict[str, Any]]]:
    return [rows[i : i + size] for i in range(0, len(rows), size)] or []


_LUCENE_SPECIAL = re.compile(r'([+\-!(){}\[\]^"~*?:\\/]|&&|\|\|)')


def _lucene_query(text: str) -> str:
    """Turn free text into a forgiving Lucene query (escaped terms, light fuzziness)."""
    terms = []
    for raw in re.findall(r"[\w.+#-]+", text.lower()):
        if raw in STOPWORDS or len(raw) < 2:
            continue
        term = _LUCENE_SPECIAL.sub(r"\\\1", raw)
        terms.append(f"{term}~1" if len(raw) >= 6 and raw.isalpha() else term)
    return " OR ".join(terms[:24])
