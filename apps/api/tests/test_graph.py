from careergraph.graph.models import EntityNode, KnowledgeGraph
from careergraph.graph.schema import NodeType, RelType
from careergraph.graph.snapshot import EdgeView, EntityView, GraphSnapshot, normalize_name
from careergraph.graph.store import UnsafeCypherError, validate_readonly_cypher
from careergraph.retrieval.hybrid import rrf
from careergraph.text import citation_refs


def _snapshot() -> GraphSnapshot:
    entities = [
        EntityView("person:d", "Person", "Dorian"),
        EntityView("role:gb", "Role", "Software Engineer — GoodBarber"),
        EntityView("org:gb", "Organization", "GoodBarber"),
        EntityView("project:a", "Project", "DL-Refine"),
        EntityView("project:b", "Project", "WantToGo"),
        EntityView("skill:k8s", "Skill", "Kubernetes", aliases=["k8s"]),
        EntityView("skill:react", "Skill", "React"),
        EntityView("skill:php", "Skill", "PHP"),
        EntityView("skill:llm", "Skill", "LLMs"),
    ]
    edges = [
        EdgeView("person:d", "role:gb", "HELD_ROLE"),
        EdgeView("role:gb", "org:gb", "AT"),
        EdgeView("role:gb", "skill:php", "USED"),
        EdgeView("person:d", "project:a", "BUILT"),
        EdgeView("person:d", "project:b", "BUILT"),
        EdgeView("project:a", "skill:k8s", "USES"),
        EdgeView("project:a", "skill:llm", "USES"),
        EdgeView("project:b", "skill:react", "USES"),
        EdgeView("project:b", "skill:k8s", "USES"),
        EdgeView("person:d", "skill:k8s", "HAS_SKILL"),
    ]
    return GraphSnapshot("v1", entities, edges)


def test_normalize_name_is_punctuation_and_case_insensitive() -> None:
    assert normalize_name("Node.js") == normalize_name("nodejs")
    assert normalize_name("CI/CD") == "cicd"
    assert normalize_name("C++") != normalize_name("C")


def test_lookup_handles_aliases_and_plurals() -> None:
    snapshot = _snapshot()
    assert snapshot.lookup("k8s") == "skill:k8s"
    assert snapshot.lookup("llm") == "skill:llm"
    assert snapshot.lookup("unknown tech") is None


def test_personalized_pagerank_prefers_multi_hop_neighbours() -> None:
    snapshot = _snapshot()
    ranks = snapshot.personalized_pagerank({"skill:llm": 1.0})
    # LLMs → DL-Refine → Kubernetes is reachable in two hops; React is three hops away.
    assert ranks["project:a"] > ranks["skill:k8s"] > ranks.get("skill:react", 0.0)
    # The Person hub is excluded from propagation.
    assert ranks.get("person:d", 0.0) == 0.0


def test_shortest_path_avoids_person_hub() -> None:
    snapshot = _snapshot()
    path = snapshot.shortest_path("skill:llm", "skill:react")
    assert path == ["skill:llm", "project:a", "skill:k8s", "project:b", "skill:react"]


def test_rrf_rewards_items_ranked_high_in_several_lists() -> None:
    fused = rrf([[("a", 0.9), ("b", 0.8)], [("b", 3.0), ("c", 2.0)]])
    assert max(fused, key=lambda k: fused[k]) == "b"


def test_readonly_cypher_guard() -> None:
    assert (
        validate_readonly_cypher("MATCH (s:Skill) RETURN s.name LIMIT 5;")
        == "MATCH (s:Skill) RETURN s.name LIMIT 5"
    )
    # keywords inside string literals are fine
    validate_readonly_cypher("MATCH (s:Skill {name: 'Data set CREATE'}) RETURN s.name")
    for query in (
        "MATCH (n) DETACH DELETE n RETURN 1",
        "CREATE (n:X) RETURN n",
        "MATCH (n) SET n.x = 1 RETURN n",
        "CALL db.labels() YIELD label RETURN label",
        "MATCH (n) RETURN n; MATCH (m) DELETE m",
        "LOAD CSV FROM 'http://x' AS row RETURN row",
        "MATCH (n) WITH n MERGE (m:Y) RETURN m",
    ):
        try:
            validate_readonly_cypher(query)
        except UnsafeCypherError:
            continue
        raise AssertionError(f"accepted unsafe query: {query}")


def test_knowledge_graph_dedups_relations_and_merges_entities() -> None:
    kg = KnowledgeGraph()
    kg.add_entity(EntityNode(id="skill:react", type=NodeType.SKILL, name="React", sources=["a"]))
    kg.add_entity(
        EntityNode(id="skill:react", type=NodeType.SKILL, name="React", aliases=["ReactJS"], sources=["b"])
    )
    kg.add_entity(EntityNode(id="project:x", type=NodeType.PROJECT, name="X"))
    kg.add_relation("project:x", RelType.USES, "skill:react", source="code")
    kg.add_relation("project:x", RelType.USES, "skill:react", source="llm", how="UI")
    assert kg.entities["skill:react"].sources == ["a", "b"]
    assert kg.entities["skill:react"].aliases == ["ReactJS"]
    assert len(kg.relations) == 1
    assert kg.relations[0].props == {"source": "code", "how": "UI"}


def test_citation_refs_accept_lists_and_ranges() -> None:
    text = "Shipped at GoodBarber [1][3], uses React [2, 16, 23] and Kubernetes [4-6]; see [docs](x) [7]"
    assert citation_refs(text) == {1, 2, 3, 4, 5, 6, 7, 16, 23}
    assert citation_refs("no citations, a markdown [link](https://x) or [9-200]") == {9, 200}
