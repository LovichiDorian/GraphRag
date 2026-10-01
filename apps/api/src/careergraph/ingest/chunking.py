"""Heading-aware Markdown chunking tuned for READMEs and CV sections."""

from __future__ import annotations

import re
from dataclasses import dataclass

_BADGE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|!\[[^\]]*\]\([^)]*\)")
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_HTML_TAG = re.compile(
    r"</?(?:img|p|div|br|a|picture|source|table|tr|td|th|sub|sup|details|summary|h\d)[^>]*>", re.I
)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BOX_DRAWING = re.compile(r"[─━│┃┌┐└┘├┤┬┴┼═║╔╗╚╝╠╣╦╩╬▼▲►◄→←↓↑]{2,}")


@dataclass(slots=True)
class TextChunk:
    title: str
    text: str
    ord: int


def clean_markdown(text: str) -> str:
    text = _HTML_COMMENT.sub("", text)
    text = _BADGE.sub("", text)
    text = _HTML_TAG.sub("", text)
    out: list[str] = []
    in_code = False
    code: list[str] = []
    for line in text.splitlines():
        if line.strip().startswith("```"):
            if in_code:
                # Keep short snippets (commands, tiny configs); drop long listings.
                if 0 < len(code) <= 8 and not any(_BOX_DRAWING.search(c) for c in code):
                    out.extend(["```", *code, "```"])
                code, in_code = [], False
            else:
                in_code = True
            continue
        if in_code:
            code.append(line)
            continue
        if _BOX_DRAWING.search(line):
            continue
        out.append(line.rstrip())
    cleaned = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def chunk_markdown(
    text: str, *, doc_title: str, max_chars: int = 1400, min_chars: int = 80
) -> list[TextChunk]:
    """Split on headings, then pack paragraphs up to ``max_chars``; titles carry the heading path."""
    text = clean_markdown(text)
    sections: list[tuple[str, list[str]]] = []
    path: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if any(p.strip() for p in current):
            sections.append((" › ".join(path) or doc_title, current.copy()))
        current.clear()

    for line in text.splitlines():
        if match := _HEADING.match(line):
            flush()
            level = len(match.group(1))
            title = re.sub(r"[*_`]|:[a-z_]+:", "", match.group(2)).strip()
            title = re.sub(r"^[^\w(]+", "", title).strip() or title
            path = [*path[: level - 1], title][:3]
            continue
        current.append(line)
    flush()

    chunks: list[TextChunk] = []
    for title, lines in sections:
        paragraphs = [p.strip() for p in "\n".join(lines).split("\n\n") if p.strip()]
        buffer = ""
        for paragraph in paragraphs:
            while len(paragraph) > max_chars:  # hard split pathological paragraphs
                cut = paragraph.rfind(" ", 0, max_chars)
                cut = cut if cut > max_chars // 2 else max_chars
                if buffer:
                    chunks.append(TextChunk(title, buffer, len(chunks)))
                    buffer = ""
                chunks.append(TextChunk(title, paragraph[:cut].strip(), len(chunks)))
                paragraph = paragraph[cut:].strip()
            if buffer and len(buffer) + len(paragraph) + 2 > max_chars:
                chunks.append(TextChunk(title, buffer, len(chunks)))
                buffer = ""
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
        if buffer:
            chunks.append(TextChunk(title, buffer, len(chunks)))

    # Merge tiny chunks into their predecessor from the same section.
    merged: list[TextChunk] = []
    for chunk in chunks:
        if merged and len(chunk.text) < min_chars and merged[-1].title == chunk.title:
            merged[-1].text = f"{merged[-1].text}\n\n{chunk.text}"
        elif len(chunk.text) >= min_chars or not merged:
            merged.append(chunk)
    for i, chunk in enumerate(merged):
        chunk.ord = i
    return [c for c in merged if len(c.text) >= 30]
