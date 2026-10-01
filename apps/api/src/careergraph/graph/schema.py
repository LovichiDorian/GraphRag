"""Ontology of the career knowledge graph and the Neo4j schema that backs it."""

from __future__ import annotations

from enum import StrEnum


class NodeType(StrEnum):
    PERSON = "Person"
    ROLE = "Role"
    ORGANIZATION = "Organization"
    PROJECT = "Project"
    SKILL = "Skill"
    DOMAIN = "Domain"
    DEGREE = "Degree"
    LANGUAGE = "Language"
    AWARD = "Award"
    LOCATION = "Location"


class RelType(StrEnum):
    HELD_ROLE = "HELD_ROLE"  # Person → Role
    AT = "AT"  # Role|Degree → Organization
    BUILT = "BUILT"  # Person → Project
    DELIVERED = "DELIVERED"  # Role → Project (client work, work projects)
    USES = "USES"  # Project → Skill
    USED = "USED"  # Role → Skill
    HAS_SKILL = "HAS_SKILL"  # Person → Skill (derived, carries strength/evidence)
    IN_DOMAIN = "IN_DOMAIN"  # Skill → Domain
    RELATED_TO = "RELATED_TO"  # Skill ↔ Skill (LLM-extracted, e.g. LangGraph → LangChain)
    STUDIED = "STUDIED"  # Person → Degree
    SPEAKS = "SPEAKS"  # Person → Language
    WON = "WON"  # Person → Award
    AWARDED_FOR = "AWARDED_FOR"  # Award → Project
    AWARDED_BY = "AWARDED_BY"  # Award → Organization
    LOCATED_IN = "LOCATED_IN"  # Person|Organization|Role → Location


# Relationship types the LLM extractor is allowed to emit between skills/concepts.
EXTRACTABLE_RELATIONS = (RelType.RELATED_TO,)

# Weights used by Personalized PageRank. HAS_SKILL is excluded: the Person node
# links to everything, so propagating through it would wash out locality.
PPR_EDGE_WEIGHTS: dict[str, float] = {
    RelType.HELD_ROLE: 0.6,
    RelType.AT: 1.0,
    RelType.BUILT: 0.6,
    RelType.DELIVERED: 1.0,
    RelType.USES: 1.0,
    RelType.USED: 1.0,
    RelType.IN_DOMAIN: 0.35,
    RelType.RELATED_TO: 0.7,
    RelType.STUDIED: 0.6,
    RelType.SPEAKS: 0.3,
    RelType.WON: 0.6,
    RelType.AWARDED_FOR: 1.0,
    RelType.AWARDED_BY: 0.8,
    RelType.LOCATED_IN: 0.3,
}

# Node types left out of community detection (hubs / attributes).
COMMUNITY_EXCLUDED = {NodeType.PERSON, NodeType.DOMAIN, NodeType.LANGUAGE, NodeType.LOCATION}

SCHEMA_DESCRIPTION = """\
Node labels (every knowledge node also has the label :Entity and properties id, name, description):
  (:Person {name, headline, location, summary})
  (:Role {name, title, start, end, highlights})            // a position held, e.g. "Software Engineer (Apprenticeship) @ GoodBarber"
  (:Organization {name, description, url})
  (:Project {name, summary, url, repo_url, stars, primary_language, highlights, period, pushed_at, featured})
  (:Skill {name, category, evidence})                       // category: language|framework|library|database|ai|devops|cloud|tool|platform|concept|practice|domain-knowledge
  (:Domain {name})                                          // CV skill group, e.g. "Applied AI", "DevOps & Cloud"
  (:Degree {name, school, start, end, honors})
  (:Language {name, level})
  (:Award {name, year})
  (:Location {name})
  (:Document {id, title, kind, url}) and (:Chunk {id, text, title}) hold the raw evidence text.
  (:Community {id, title, summary}) are thematic clusters of the graph.
Relationships:
  (:Person)-[:HELD_ROLE]->(:Role)-[:AT]->(:Organization)
  (:Person)-[:BUILT]->(:Project), (:Role)-[:DELIVERED]->(:Project)
  (:Project)-[:USES]->(:Skill), (:Role)-[:USED]->(:Skill)
  (:Person)-[:HAS_SKILL {strength, evidence, last_used}]->(:Skill)
  (:Skill)-[:IN_DOMAIN]->(:Domain), (:Skill)-[:RELATED_TO]->(:Skill)
  (:Person)-[:STUDIED]->(:Degree)-[:AT]->(:Organization)
  (:Person)-[:SPEAKS]->(:Language), (:Person)-[:WON]->(:Award)-[:AWARDED_FOR]->(:Project)
  (:Person|Organization|Role)-[:LOCATED_IN]->(:Location)
  (:Chunk)-[:PART_OF]->(:Document), (:Chunk)-[:MENTIONS]->(:Entity), (:Document)-[:DESCRIBES]->(:Entity)
  (:Entity)-[:IN_COMMUNITY]->(:Community)
Dates are strings "YYYY" or "YYYY-MM"; an ongoing role has end = null."""


def constraint_statements() -> list[str]:
    return [
        "CREATE CONSTRAINT entity_id IF NOT EXISTS FOR (n:Entity) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (n:Document) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:Chunk) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (n:Community) REQUIRE n.id IS UNIQUE",
        "CREATE CONSTRAINT meta_key IF NOT EXISTS FOR (n:Meta) REQUIRE n.key IS UNIQUE",
        "CREATE CONSTRAINT cached_answer_key IF NOT EXISTS FOR (n:CachedAnswer) REQUIRE n.key IS UNIQUE",
    ]


def index_statements(dim: int) -> list[str]:
    def vector(name: str, label: str) -> str:
        return (
            f"CREATE VECTOR INDEX {name} IF NOT EXISTS FOR (n:{label}) ON n.embedding "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {dim}, `vector.similarity_function`: 'cosine'}}}}"
        )

    return [
        vector("entity_embedding", "Entity"),
        vector("chunk_embedding", "Chunk"),
        vector("community_embedding", "Community"),
        "CREATE FULLTEXT INDEX entity_fulltext IF NOT EXISTS FOR (n:Entity) ON EACH [n.name, n.aliases_text, n.description]",
        "CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS FOR (n:Chunk) ON EACH [n.text, n.title]",
    ]
