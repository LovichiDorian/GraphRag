"""Small text utilities shared by retrieval, planning and ingestion."""

from __future__ import annotations

import re
import unicodedata

STOPWORDS = frozenset(
    """
    a an and are as at be been but by can could did do does for from had has have he her his how i if in
    into is it its me my of on or our she should so than that the their them then there these they this
    to was we were what when where which who whom why will with would you your about any tell dorian
    lovichi his him does has experience
    le la les l de des du d et en est il elle un une quel quels quelle quelles sur avec pour dans par
    qu que qui quoi ou où son sa ses ce cette ces au aux a-t-il t-il est-ce
    """.split()
)


def slugify(text: str, max_len: int = 80) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    text = text.replace("++", "pp").replace("#", "sharp")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:max_len] or "item"


# Inline evidence citations written by the models: "[3]", "[2][5]", "[2, 16, 23]", "[4-6]".
CITATION = re.compile(r"\[(\d{1,3}(?:\s*[,;–-]\s*\d{1,3})*)\](?!\()")


def citation_refs(text: str) -> set[int]:
    """Source numbers cited in ``text``, expanding lists and short ranges."""
    refs: set[int] = set()
    for group in CITATION.findall(text):
        for piece in re.split(r"[,;]", group):
            bounds = [int(x) for x in re.split(r"[–-]", piece) if x.strip()]
            if len(bounds) == 2 and 0 < bounds[1] - bounds[0] <= 12:
                refs.update(range(bounds[0], bounds[1] + 1))
            else:
                refs.update(bounds)
    return refs


def truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
