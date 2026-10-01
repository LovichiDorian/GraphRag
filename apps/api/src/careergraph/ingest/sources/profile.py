"""profile.yaml (the CV, as structured data) → entities, relations and CV documents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from careergraph.graph.models import DocumentNode, EntityNode, KnowledgeGraph
from careergraph.graph.schema import NodeType, RelType
from careergraph.ingest.resolve import add_skill
from careergraph.text import slugify

CV_URL = "/dorian-lovichi-resume.pdf"


@dataclass(slots=True)
class SourceDoc:
    node: DocumentNode
    text: str
    subject: str | None = None  # entity the document is about (for LLM extraction)
    extract: bool = False


def load_profile(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "person" not in data:
        raise ValueError(f"{path} is not a valid profile (missing 'person')")
    return data


def _date(value: Any) -> str | None:
    return None if value in (None, "") else str(value)


def _period(start: Any, end: Any) -> str:
    start_s, end_s = _date(start), _date(end)
    return f"{start_s or '?'} – {end_s or 'present'}"


def _org(kg: KnowledgeGraph, name: str, *, description: str = "", url: str | None = None) -> str:
    oid = f"org:{slugify(name)}"
    kg.add_entity(
        EntityNode(
            id=oid,
            type=NodeType.ORGANIZATION,
            name=name,
            description=description,
            url=url,
            sources=["cv:summary"],
        )
    )
    return oid


def _location(kg: KnowledgeGraph, name: str) -> str:
    lid = f"loc:{slugify(name)}"
    kg.add_entity(EntityNode(id=lid, type=NodeType.LOCATION, name=name))
    return lid


def build_profile_graph(profile: dict[str, Any], kg: KnowledgeGraph) -> list[SourceDoc]:
    docs: list[SourceDoc] = []
    person = profile["person"]
    pid = f"person:{person['id']}"
    kg.add_entity(
        EntityNode(
            id=pid,
            type=NodeType.PERSON,
            name=person["name"],
            description=" ".join(str(person.get("summary", "")).split()),
            url=person.get("website"),
            props={
                key: person.get(key)
                for key in (
                    "headline",
                    "location",
                    "email",
                    "website",
                    "linkedin",
                    "github",
                    "work_authorization",
                )
                if person.get(key)
            },
            sources=["cv:summary"],
        )
    )
    if person.get("location"):
        kg.add_relation(pid, RelType.LOCATED_IN, _location(kg, person["location"]))

    # ── skills, grouped by CV domain
    skill_lines = []
    for group, names in (profile.get("skills") or {}).items():
        did = f"domain:{slugify(group)}"
        kg.add_entity(
            EntityNode(id=did, type=NodeType.DOMAIN, name=group, description=f"Skill domain: {group}")
        )
        for name in names:
            sid = add_skill(kg, str(name), source="cv:skills", domain=group)
            if sid:
                kg.entities[sid].props["listed_on_cv"] = True
                kg.add_relation(sid, RelType.IN_DOMAIN, did)
        skill_lines.append(f"- **{group}:** {', '.join(map(str, names))}")
    docs.append(
        SourceDoc(
            DocumentNode(
                id="cv:skills",
                title="CV — Technical skills",
                kind="cv",
                source="cv",
                url=CV_URL,
                describes=[pid],
            ),
            "# Technical skills\n\n" + "\n".join(skill_lines),
        )
    )

    # ── experience
    for exp in profile.get("experience") or []:
        oid = _org(
            kg,
            exp["organization"],
            description=exp.get("organization_description", ""),
            url=exp.get("organization_url"),
        )
        rid = f"role:{exp['id']}"
        highlights = [" ".join(h.split()) for h in exp.get("highlights") or []]
        period = _period(exp.get("start"), exp.get("end"))
        kg.add_entity(
            EntityNode(
                id=rid,
                type=NodeType.ROLE,
                name=f"{exp['title']} — {exp['organization']}",
                description=f"{exp['title']} at {exp['organization']} ({exp.get('location', '')}, {period}). "
                + (highlights[0] if highlights else ""),
                props={
                    "title": exp["title"],
                    "organization": exp["organization"],
                    "start": _date(exp.get("start")),
                    "end": _date(exp.get("end")),
                    "period": period,
                    "current": exp.get("end") in (None, ""),
                    "location": exp.get("location"),
                    "highlights": highlights,
                },
                sources=[f"cv:experience:{exp['id']}"],
            )
        )
        kg.add_relation(pid, RelType.HELD_ROLE, rid)
        kg.add_relation(rid, RelType.AT, oid)
        if exp.get("location"):
            lid = _location(kg, exp["location"])
            kg.add_relation(rid, RelType.LOCATED_IN, lid)
            kg.add_relation(oid, RelType.LOCATED_IN, lid)
        for name in exp.get("skills") or []:
            if sid := add_skill(kg, str(name), source=f"cv:experience:{exp['id']}"):
                kg.add_relation(rid, RelType.USED, sid, source="cv")
        text = (
            f"# {exp['title']} — {exp['organization']}\n\n"
            f"{exp.get('location', '')} · {period}\n\n"
            f"{exp.get('organization_description', '')}\n\n" + "\n".join(f"- {h}" for h in highlights)
        )
        docs.append(
            SourceDoc(
                DocumentNode(
                    id=f"cv:experience:{exp['id']}",
                    title=f"CV — {exp['title']}, {exp['organization']}",
                    kind="cv",
                    source="cv",
                    url=CV_URL,
                    describes=[rid, oid],
                ),
                text,
                subject=rid,
                extract=True,
            )
        )

    # ── projects
    for proj in profile.get("projects") or []:
        prid = f"project:{proj['id']}"
        highlights = [" ".join(h.split()) for h in proj.get("highlights") or []]
        kg.add_entity(
            EntityNode(
                id=prid,
                type=NodeType.PROJECT,
                name=proj["name"],
                description=" ".join(str(proj.get("summary", "")).split()),
                url=proj.get("url"),
                props={
                    "featured": bool(proj.get("featured")),
                    "period": _date(proj.get("period")),
                    "highlights": highlights,
                    "source": "cv",
                },
                sources=[f"cv:project:{proj['id']}"],
            )
        )
        if proj.get("role"):
            kg.add_relation(f"role:{proj['role']}", RelType.DELIVERED, prid)
        kg.add_relation(pid, RelType.BUILT, prid)
        for name in proj.get("skills") or []:
            if sid := add_skill(kg, str(name), source=f"cv:project:{proj['id']}"):
                kg.add_relation(prid, RelType.USES, sid, source="cv")
        text = f"# Project: {proj['name']}\n\n{proj.get('summary', '')}\n\n" + "\n".join(
            f"- {h}" for h in highlights
        )
        if proj.get("url"):
            text += f"\n\nLive: {proj['url']}"
        docs.append(
            SourceDoc(
                DocumentNode(
                    id=f"cv:project:{proj['id']}",
                    title=f"CV — Project: {proj['name']}",
                    kind="cv",
                    source="cv",
                    url=proj.get("url") or CV_URL,
                    describes=[prid],
                ),
                text,
                subject=prid,
                extract=True,
            )
        )

    # ── education
    edu_lines = []
    for edu in profile.get("education") or []:
        oid = _org(kg, edu["school"], description="University / school")
        deg_id = f"degree:{edu['id']}"
        period = _period(edu.get("start"), edu.get("end"))
        kg.add_entity(
            EntityNode(
                id=deg_id,
                type=NodeType.DEGREE,
                name=edu["degree"],
                description=f"{edu['degree']}, {edu['school']} ({period})"
                + (f", {edu['honors']}" if edu.get("honors") else "")
                + (f" — {edu['note']}" if edu.get("note") else ""),
                props={
                    "school": edu["school"],
                    "start": _date(edu.get("start")),
                    "end": _date(edu.get("end")),
                    "period": edu.get("note") or period,
                    "honors": edu.get("honors"),
                },
                sources=["cv:education"],
            )
        )
        kg.add_relation(pid, RelType.STUDIED, deg_id)
        kg.add_relation(deg_id, RelType.AT, oid)
        if edu.get("location"):
            kg.add_relation(oid, RelType.LOCATED_IN, _location(kg, edu["location"]))
        honors = f" — {edu['honors']}" if edu.get("honors") else ""
        edu_lines.append(f"- {edu['degree']}{honors} | {edu['school']} | {edu.get('note') or period}")
    docs.append(
        SourceDoc(
            DocumentNode(
                id="cv:education", title="CV — Education", kind="cv", source="cv", url=CV_URL, describes=[pid]
            ),
            "# Education\n\n" + "\n".join(edu_lines),
        )
    )

    # ── awards
    for award in profile.get("awards") or []:
        aid = f"award:{award['id']}"
        kg.add_entity(
            EntityNode(
                id=aid,
                type=NodeType.AWARD,
                name=award["name"],
                description=f"{award['name']} ({award.get('year', '')})",
                props={"year": award.get("year")},
                sources=["cv:summary"],
            )
        )
        kg.add_relation(pid, RelType.WON, aid)
        if award.get("project"):
            kg.add_relation(aid, RelType.AWARDED_FOR, f"project:{award['project']}")
        if award.get("organization"):
            kg.add_relation(aid, RelType.AWARDED_BY, _org(kg, award["organization"]))

    # ── spoken languages
    language_lines = []
    for lang in profile.get("languages") or []:
        lid = f"lang:{slugify(lang['name'])}"
        kg.add_entity(
            EntityNode(
                id=lid,
                type=NodeType.LANGUAGE,
                name=lang["name"],
                description=f"{lang['name']} — {lang.get('level', '')}",
                props={"level": lang.get("level")},
                sources=["cv:summary"],
            )
        )
        kg.add_relation(pid, RelType.SPEAKS, lid, level=lang.get("level"))
        language_lines.append(f"{lang['name']} ({lang.get('level', '')})")

    summary = " ".join(str(person.get("summary", "")).split())
    links = " · ".join(str(person[k]) for k in ("website", "linkedin", "github") if person.get(k))
    docs.insert(
        0,
        SourceDoc(
            DocumentNode(
                id="cv:summary", title="CV — Summary", kind="cv", source="cv", url=CV_URL, describes=[pid]
            ),
            f"# {person['name']}\n\n{person.get('headline', '')}\n\n"
            f"Location: {person.get('location', '')} · Email: {person.get('email', '')} · {links}\n\n"
            f"## Summary\n\n{summary}\n\n"
            f"## Languages\n\n{' | '.join(language_lines)}\n\n"
            f"## Work authorization\n\n{person.get('work_authorization', '')}\n\n"
            "## Awards\n\n" + "\n".join(f"- {a['name']}" for a in profile.get("awards") or []),
        ),
    )
    return docs


def load_notes(notes_dir: Path) -> list[SourceDoc]:
    """Free-form Markdown notes (data/notes/*.md) become extra evidence documents."""
    docs: list[SourceDoc] = []
    if not notes_dir.is_dir():
        return docs
    for path in sorted(notes_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8")
        title = next(
            (line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")), path.stem
        )
        docs.append(
            SourceDoc(
                DocumentNode(
                    id=f"note:{slugify(path.stem)}", title=f"Note — {title}", kind="note", source="notes"
                ),
                text,
            )
        )
    return docs
