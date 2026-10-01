"""In-memory representation of the knowledge graph produced by the ingestion pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, PrivateAttr

from careergraph.graph.schema import NodeType, RelType

Scalar = str | int | float | bool | None
PropValue = Scalar | list[str] | list[int] | list[float]


class EntityNode(BaseModel):
    id: str
    type: NodeType
    name: str
    description: str = ""
    aliases: list[str] = Field(default_factory=list)
    url: str | None = None
    props: dict[str, PropValue] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None

    def embedding_text(self) -> str:
        parts = [f"{self.type.value}: {self.name}"]
        if self.aliases:
            parts.append(f"(also known as {', '.join(self.aliases[:6])})")
        if self.description:
            parts.append(f"— {self.description}")
        highlights = self.props.get("highlights")
        if isinstance(highlights, list):
            parts.append(" ".join(str(h) for h in highlights[:4]))
        return " ".join(parts)[:4000]


class Relation(BaseModel):
    source: str
    target: str
    type: RelType
    props: dict[str, PropValue] = Field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.source, self.type.value, self.target)


class DocumentNode(BaseModel):
    id: str
    title: str
    kind: str  # cv | readme | doc | note | manifest
    source: str
    url: str | None = None
    describes: list[str] = Field(default_factory=list)
    updated_at: str | None = None


class ChunkNode(BaseModel):
    id: str
    doc_id: str
    title: str
    text: str
    ord: int
    mentions: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None


class CommunityNode(BaseModel):
    id: str
    title: str
    summary: str
    members: list[str]
    key_entities: list[str] = Field(default_factory=list)
    embedding: list[float] | None = None


class KnowledgeGraph(BaseModel):
    entities: dict[str, EntityNode] = Field(default_factory=dict)
    relations: list[Relation] = Field(default_factory=list)
    documents: list[DocumentNode] = Field(default_factory=list)
    chunks: list[ChunkNode] = Field(default_factory=list)
    communities: list[CommunityNode] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)
    _relation_index: dict[tuple[str, str, str], Relation] = PrivateAttr(default_factory=dict)

    def add_entity(self, entity: EntityNode) -> EntityNode:
        """Insert or merge an entity (aliases, sources and missing fields are unioned)."""
        existing = self.entities.get(entity.id)
        if existing is None:
            self.entities[entity.id] = entity
            return entity
        existing.aliases = sorted({*existing.aliases, *entity.aliases} - {existing.name})
        existing.sources = sorted({*existing.sources, *entity.sources})
        if len(entity.description) > len(existing.description):
            existing.description = entity.description
        existing.url = existing.url or entity.url
        for key, value in entity.props.items():
            existing.props.setdefault(key, value)
        return existing

    def add_relation(self, source: str, rel: RelType, target: str, /, **props: PropValue) -> None:
        if source == target or source not in self.entities or target not in self.entities:
            return
        key = (source, rel.value, target)
        existing = self._relation_index.get(key)
        if existing is not None:
            for k, v in props.items():
                existing.props.setdefault(k, v)
            return
        relation = Relation(source=source, target=target, type=rel, props=dict(props))
        self._relation_index[key] = relation
        self.relations.append(relation)

    def has_relation(self, source: str, rel: RelType, target: str, /) -> bool:
        return (source, rel.value, target) in self._relation_index
