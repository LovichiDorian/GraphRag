"""GitHub repositories → evidence documents and dependency-verified skills.

Per repository we fetch metadata and language bytes from the REST API, then
download the tarball once and read, in-memory, the README, docs and every
dependency manifest / deployment file. Technologies found in manifests are
"verified" evidence (package.json says React, a `kind: Deployment` says
Kubernetes), stronger than claims in prose.
"""

from __future__ import annotations

import asyncio
import io
import json
import re
import subprocess
import tarfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from careergraph.ingest.techmap import (
    GENERATED_LANGUAGES,
    GITHUB_LANGUAGES,
    detect_from_manifest,
    detect_from_paths,
)
from careergraph.logs import get_logger
from careergraph.settings import Settings

log = get_logger(__name__)

API = "https://api.github.com"
MAX_TARBALL_BYTES = 60 * 1024 * 1024
MAX_TEXT_BYTES = 200_000
SKIP_DIRS = re.compile(
    r"(^|/)(node_modules|vendor|dist|build|\.git|\.next|\.dart_tool|\.gradle|__pycache__|\.venv|venv|coverage|Pods|"
    r"\.idea|\.vscode|out|target|bin|obj)(/|$)"
)
MANIFEST = re.compile(
    r"(^|/)(package\.json|requirements[\w.-]*\.txt|pyproject\.toml|pubspec\.yaml|composer\.json|"
    r"(build|settings)\.gradle(\.kts)?|libs\.versions\.toml|Dockerfile(\.[\w-]+)?|go\.mod|Cargo\.toml)$"
)
DEPLOY_YAML = re.compile(
    r"(^|/)(k8s|kubernetes|deploy|deployment|manifests|helm|charts|infra|\.github/workflows)/.*\.ya?ml$|(^|/)(docker-)?compose[\w.-]*\.ya?ml$"
)
DOC_MD = re.compile(r"^(README[\w.-]*\.md|docs?/[^/]+\.md|[A-Z][\w-]*\.md)$", re.I)
FLUTTER_PLATFORM = re.compile(r"^(android|ios|linux|macos|windows|web)/")
SOURCE_EXT = re.compile(r"\.(py|ts|tsx|js|jsx|kt|kts|dart|php|java|go|rs|as|vue|svelte|swift|cs)$")


@dataclass
class RepoFile:
    path: str
    text: str


@dataclass
class Repo:
    name: str
    full_name: str
    url: str
    description: str = ""
    homepage: str | None = None
    topics: list[str] = field(default_factory=list)
    stars: int = 0
    forks: int = 0
    private: bool = False
    fork: bool = False
    archived: bool = False
    language: str | None = None
    languages: dict[str, int] = field(default_factory=dict)
    created_at: str | None = None
    pushed_at: str | None = None
    default_branch: str = "main"
    readme: RepoFile | None = None
    docs: list[RepoFile] = field(default_factory=list)
    manifests: list[RepoFile] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)

    # ── derived evidence ──────────────────────────────────────────────────────
    @property
    def is_flutter(self) -> bool:
        return "pubspec.yaml" in self.paths

    def relevant_paths(self) -> list[str]:
        if self.is_flutter:
            return [p for p in self.paths if not FLUTTER_PLATFORM.match(p)]
        return self.paths

    def technologies(self) -> dict[str, str]:
        """Canonical technology → evidence (file path or 'GitHub languages')."""
        found: dict[str, str] = {}
        for file in self.manifests:
            if self.is_flutter and FLUTTER_PLATFORM.match(file.path):
                continue
            for tech in detect_from_manifest(file.path, file.text):
                found.setdefault(tech, file.path)
        for tech, path in detect_from_paths(self.relevant_paths()).items():
            found.setdefault(tech, path)
        for language in self.top_languages():
            if mapped := GITHUB_LANGUAGES.get(language):
                found.setdefault(mapped, "GitHub languages")
        return found

    def top_languages(self, min_share: float = 0.05) -> list[str]:
        languages = {
            lang: size
            for lang, size in self.languages.items()
            if not (self.is_flutter and lang in GENERATED_LANGUAGES | {"Kotlin", "Java"})
        }
        total = sum(languages.values()) or 1
        return [
            lang
            for lang, size in sorted(languages.items(), key=lambda kv: -kv[1])
            if size / total >= min_share
        ]

    def profile_text(self) -> str:
        """Synthetic evidence document: what the repository itself proves."""
        techs = self.technologies()
        lines = [f"# Repository {self.full_name}", ""]
        if self.description:
            lines += [self.description, ""]
        langs = self.top_languages()
        if langs:
            total = sum(self.languages.values()) or 1
            shares = ", ".join(f"{lang} {round(100 * self.languages[lang] / total)}%" for lang in langs)
            lines.append(f"Languages (by bytes of code): {shares}.")
        if techs:
            evidence = "; ".join(f"{tech} ({path})" for tech, path in sorted(techs.items()))
            lines.append(f"Technologies verified from the code and manifests: {evidence}.")
        if self.topics:
            lines.append(f"Topics: {', '.join(self.topics)}.")
        dates = []
        if self.created_at:
            dates.append(f"created {self.created_at[:10]}")
        if self.pushed_at:
            dates.append(f"last push {self.pushed_at[:10]}")
        if dates:
            lines.append(f"Activity: {', '.join(dates)}.")
        source_files = [p for p in self.relevant_paths() if SOURCE_EXT.search(p)]
        if source_files:
            lines.append(f"Source files: {len(source_files)} (e.g. {', '.join(source_files[:6])}).")
        return "\n".join(lines)


def _decode(data: bytes) -> str | None:
    if b"\x00" in data[:4096]:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1", errors="ignore")


def _collect(repo: Repo, path: str, read: Any) -> None:
    """Route a file of the repository into the right bucket (reads content lazily)."""
    if SKIP_DIRS.search(path):
        return
    repo.paths.append(path)
    is_readme = re.fullmatch(r"README(\.[\w-]+)?\.md", path, re.I) is not None
    wanted = is_readme or DOC_MD.match(path) or MANIFEST.search(path) or DEPLOY_YAML.search(path)
    if not wanted:
        return
    data = read()
    if data is None or len(data) > MAX_TEXT_BYTES:
        return
    text = _decode(data)
    if text is None:
        return
    file = RepoFile(path, text)
    if is_readme and (repo.readme is None or path.lower() == "readme.md"):
        if repo.readme is not None:
            repo.docs.append(repo.readme)
        repo.readme = file
    elif DOC_MD.match(path):
        repo.docs.append(file)
    else:
        repo.manifests.append(file)


def _read_tarball(repo: Repo, blob: bytes) -> None:
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as archive:
        for member in archive:
            if not member.isfile():
                continue
            # GitHub tarballs are prefixed with "<owner>-<repo>-<sha>/".
            path = member.name.split("/", 1)[1] if "/" in member.name else member.name

            def read(m: tarfile.TarInfo = member) -> bytes | None:
                handle = archive.extractfile(m)
                return handle.read() if handle else None

            _collect(repo, path, read)


class GitHubSource:
    def __init__(self, settings: Settings, user: str) -> None:
        self.settings = settings
        self.user = user
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "careergraph-ingest",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token.get_secret_value()}"
        self.client = httpx.AsyncClient(base_url=API, headers=headers, timeout=60, follow_redirects=True)

    async def close(self) -> None:
        await self.client.aclose()

    async def _get(self, url: str, **params: Any) -> Any:
        for attempt in range(4):
            response = await self.client.get(url, params=params or None)
            if response.status_code in (403, 429) and "rate limit" in response.text.lower():
                raise RuntimeError(
                    "GitHub API rate limit reached — set GITHUB_TOKEN for 5,000 requests/hour."
                )
            if response.status_code >= 500 and attempt < 3:
                await asyncio.sleep(2**attempt)
                continue
            response.raise_for_status()
            return response.json()
        raise RuntimeError(f"GitHub API failed for {url}")

    async def list_repos(self) -> list[dict[str, Any]]:
        if self.settings.github_token and self.settings.github_include_private:
            items = await self._get("/user/repos", per_page=100, affiliation="owner", sort="pushed")
        else:
            items = await self._get(f"/users/{self.user}/repos", per_page=100, type="owner", sort="pushed")
        return list(items)

    async def fetch(self, include: list[str], exclude: list[str]) -> list[Repo]:
        if self.settings.github_local_dir:
            return load_local_repos(self.settings.github_local_dir, include, exclude)
        raw = await self.list_repos()
        wanted = []
        for item in raw:
            name = item["name"]
            if include and name not in include:
                continue
            if name in exclude or (item.get("fork") and not self.settings.github_include_forks):
                continue
            if item.get("private") and not self.settings.github_include_private:
                continue
            wanted.append(item)
        semaphore = asyncio.Semaphore(4)

        async def one(item: dict[str, Any]) -> Repo | None:
            async with semaphore:
                try:
                    return await self._fetch_repo(item)
                except Exception as exc:  # noqa: BLE001 - one bad repo must not kill ingestion
                    log.warning("github.repo_failed", repo=item["name"], error=str(exc)[:200])
                    return None

        repos = [r for r in await asyncio.gather(*(one(i) for i in wanted)) if r is not None]
        log.info("github.fetched", user=self.user, repos=len(repos))
        return repos

    async def _fetch_repo(self, item: dict[str, Any]) -> Repo:
        repo = Repo(
            name=item["name"],
            full_name=item["full_name"],
            url=item["html_url"],
            description=item.get("description") or "",
            homepage=item.get("homepage") or None,
            topics=list(item.get("topics") or []),
            stars=int(item.get("stargazers_count") or 0),
            forks=int(item.get("forks_count") or 0),
            private=bool(item.get("private")),
            fork=bool(item.get("fork")),
            archived=bool(item.get("archived")),
            language=item.get("language"),
            created_at=item.get("created_at"),
            pushed_at=item.get("pushed_at"),
            default_branch=item.get("default_branch") or "main",
        )
        repo.languages = await self._get(f"/repos/{repo.full_name}/languages")
        response = await self.client.get(f"/repos/{repo.full_name}/tarball/{repo.default_branch}")
        response.raise_for_status()
        if len(response.content) <= MAX_TARBALL_BYTES:
            await asyncio.to_thread(_read_tarball, repo, response.content)
        return repo


def load_local_repos(root: Path, include: list[str], exclude: list[str]) -> list[Repo]:
    """Offline/dev mode: read repositories from local clones (optional ``_meta.json`` per repo)."""
    repos: list[Repo] = []
    for directory in sorted(p for p in root.iterdir() if p.is_dir()):
        name = directory.name
        if (include and name not in include) or name in exclude:
            continue
        meta: dict[str, Any] = {}
        meta_file = directory / "_meta.json"
        if meta_file.exists():
            meta = json.loads(meta_file.read_text())
        repo = Repo(
            name=name,
            full_name=meta.get("full_name", f"local/{name}"),
            url=meta.get("html_url", f"https://github.com/{meta.get('full_name', name)}"),
            description=meta.get("description") or "",
            homepage=meta.get("homepage"),
            topics=meta.get("topics") or [],
            stars=int(meta.get("stargazers_count") or 0),
            private=bool(meta.get("private")),
            created_at=meta.get("created_at"),
            pushed_at=meta.get("pushed_at") or _git_date(directory),
            default_branch=meta.get("default_branch", "main"),
        )
        languages: dict[str, int] = dict(meta.get("languages") or {})
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name == "_meta.json":
                continue
            rel = path.relative_to(directory).as_posix()
            _collect(repo, rel, lambda p=path: p.read_bytes() if p.stat().st_size <= MAX_TEXT_BYTES else None)
            if not meta.get("languages") and not SKIP_DIRS.search(rel) and (lang := _language_of(rel)):
                languages[lang] = languages.get(lang, 0) + path.stat().st_size
        repo.languages = languages
        repos.append(repo)
    return repos


_EXT_LANG = {
    ".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
    ".mjs": "JavaScript", ".kt": "Kotlin", ".kts": "Kotlin", ".dart": "Dart", ".php": "PHP", ".java": "Java",
    ".as": "ActionScript", ".go": "Go", ".rs": "Rust", ".cs": "C#", ".swift": "Swift", ".vue": "Vue",
    ".sh": "Shell", ".cpp": "C++", ".cc": "C++", ".h": "C", ".c": "C", ".html": "HTML", ".css": "CSS",
}  # fmt: skip


def _language_of(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return _EXT_LANG.get(suffix)


def _git_date(directory: Path) -> str | None:
    if not (directory / ".git").exists():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(directory), "log", "-1", "--format=%cI"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return out.stdout.strip() or None
