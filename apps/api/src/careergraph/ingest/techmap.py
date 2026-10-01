"""Canonical technology ontology used for entity resolution and manifest analysis.

Every technology has a canonical display name, a category and a domain (the CV
skill groups, plus "Mobile" for native mobile work found on GitHub). Aliases,
package names and file patterns all resolve to the canonical name, so "k8s",
a `kind: Deployment` manifest and "Kubernetes" become one Skill node.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass

import yaml

from careergraph.graph.snapshot import normalize_name


@dataclass(frozen=True, slots=True)
class Tech:
    name: str
    category: str
    domain: str


# (canonical name, category, domain, aliases)
# fmt: off
_TECH: list[tuple[str, str, str, tuple[str, ...]]] = [
    # ── languages
    ("Python", "language", "Languages", ("python3", "py")),
    ("TypeScript", "language", "Languages", ("ts",)),
    ("JavaScript", "language", "Languages", ("js", "ecmascript", "es6")),
    ("PHP", "language", "Languages", ()),
    ("SQL", "language", "Languages", ()),
    ("Kotlin", "language", "Languages", ()),
    ("Dart", "language", "Languages", ()),
    ("Java", "language", "Languages", ()),
    ("ActionScript", "language", "Languages", ("actionscript 3", "as3")),
    ("Go", "language", "Languages", ("golang",)),
    ("Rust", "language", "Languages", ()),
    ("C#", "language", "Languages", ("csharp", ".net c#")),
    ("C++", "language", "Languages", ("cpp",)),
    ("Swift", "language", "Languages", ()),
    ("Bash", "language", "Languages", ("shell", "shell scripting", "sh")),
    ("HTML & CSS", "language", "Frontend", ("html", "css", "html5", "css3", "scss", "sass")),
    # ── applied AI
    (
        "LLMs",
        "ai",
        "Applied AI",
        ("llm", "large language models", "large language model", "generative ai", "genai"),
    ),
    ("RAG", "ai", "Applied AI", ("retrieval augmented generation", "retrieval-augmented generation")),
    ("GraphRAG", "ai", "Applied AI", ("graph rag", "graph-based rag", "knowledge graph rag")),
    (
        "AI Agents",
        "ai",
        "Applied AI",
        ("ai agent", "agents", "agentic ai", "autonomous agents", "llm agents"),
    ),
    (
        "Multi-agent orchestration",
        "ai",
        "Applied AI",
        ("multi-agent", "multi agent orchestration", "multi-agent systems"),
    ),
    ("Embeddings", "ai", "Applied AI", ("text embeddings", "vector embeddings")),
    (
        "Vector search",
        "ai",
        "Applied AI",
        ("vector database", "semantic search", "vector retrieval", "vector index"),
    ),
    ("Prompt optimization", "ai", "Applied AI", ("prompt engineering", "prompt optimisation")),
    ("LangChain", "ai", "Applied AI", ("langchain-core", "langchain_core")),
    ("LangGraph", "ai", "Applied AI", ()),
    ("Gemini", "ai", "Applied AI", ("google gemini", "gemini api", "google genai", "google generative ai")),
    ("OpenAI API", "ai", "Applied AI", ("openai", "gpt", "chatgpt api", "gpt-4")),
    ("Mistral AI", "ai", "Applied AI", ("mistral",)),
    ("Anthropic Claude", "ai", "Applied AI", ("claude", "anthropic")),
    ("Knowledge graphs", "ai", "Applied AI", ("knowledge graph", "kg")),
    ("Model Context Protocol (MCP)", "ai", "Applied AI", ("mcp", "model context protocol")),
    ("Structured output", "ai", "Applied AI", ("json mode", "structured outputs")),
    ("LLM evaluation", "ai", "Applied AI", ("llm evals", "rag evaluation")),
    ("Machine learning", "ai", "Applied AI", ("ml",)),
    ("Vercel AI SDK", "library", "Applied AI", ("ai sdk", "ai-sdk")),
    ("Graph algorithms", "ai", "Applied AI", ("pagerank", "personalized pagerank", "louvain", "louvain algorithm", "community detection", "leiden")),
    # ── frontend
    ("React", "framework", "Frontend", ("reactjs", "react.js", "react 19", "react 18")),
    ("Angular", "framework", "Frontend", ("angularjs", "angular 17", "angular 18", "angular 19")),
    ("Next.js", "framework", "Frontend", ("nextjs", "next")),
    ("Vue.js", "framework", "Frontend", ("vue", "vuejs")),
    ("Vite", "tool", "Frontend", ("vitejs",)),
    ("Tailwind CSS", "library", "Frontend", ("tailwind", "tailwindcss")),
    ("shadcn/ui", "library", "Frontend", ("shadcn",)),
    ("Framer Motion", "library", "Frontend", ("motion", "framer-motion")),
    ("React Router", "library", "Frontend", ("react-router", "react-router-dom")),
    ("Leaflet", "library", "Frontend", ("react-leaflet", "leaflet.js")),
    ("OpenStreetMap", "platform", "Frontend", ("osm",)),
    ("Three.js", "library", "Frontend", ("threejs", "three")),
    ("i18next", "library", "Frontend", ("react-i18next",)),
    (
        "PWA",
        "concept",
        "Frontend",
        ("progressive web app", "progressive web apps", "pwas", "installable pwa"),
    ),
    ("Service Workers", "concept", "Frontend", ("service worker", "workbox")),
    ("IndexedDB", "database", "Frontend", ("idb",)),
    (
        "Offline-first",
        "concept",
        "Frontend",
        ("offline mode", "offline first", "offline-first architecture", "offline support"),
    ),
    ("Nx", "tool", "Frontend", ("nx monorepo", "nx workspace", "monorepo")),
    ("RxJS", "library", "Frontend", ()),
    ("Redux", "library", "Frontend", ("redux toolkit",)),
    ("TanStack Query", "library", "Frontend", ("react query", "react-query")),
    ("Server-Driven UI", "concept", "Frontend", ("sdui", "server driven ui")),
    ("Responsive design", "concept", "Frontend", ()),
    ("Lazy loading", "concept", "Frontend", ()),
    ("PostCSS", "tool", "Frontend", ()),
    ("UI design", "practice", "Frontend", ("ui", "ui/ux", "ux design", "web design", "ui/ux design")),
    # ── mobile
    ("React Native", "framework", "Mobile", ("react-native", "expo")),
    ("Flutter", "framework", "Mobile", ("provider",)),
    ("Jetpack Compose", "framework", "Mobile", ("compose", "androidx compose")),
    ("Android", "platform", "Mobile", ("android sdk",)),
    ("iOS", "platform", "Mobile", ()),
    ("Material Design", "library", "Mobile", ("material 3", "material3", "material design 3")),
    ("Retrofit", "library", "Mobile", ()),
    ("Kotlin Coroutines", "library", "Mobile", ("coroutines", "kotlinx-coroutines")),
    # ── backend & data
    ("FastAPI", "framework", "Backend & Data", ()),
    ("Node.js", "platform", "Backend & Data", ("node", "nodejs", "node js")),
    ("Express", "framework", "Backend & Data", ("express.js", "expressjs")),
    ("NestJS", "framework", "Backend & Data", ("nest", "nest.js")),
    ("Phalcon", "framework", "Backend & Data", ("phalcon php",)),
    ("Flask", "framework", "Backend & Data", ()),
    ("Django", "framework", "Backend & Data", ()),
    (
        "REST APIs",
        "concept",
        "Backend & Data",
        ("rest", "rest api", "restful api", "restful apis", "api rest"),
    ),
    ("GraphQL", "concept", "Backend & Data", ()),
    ("WebSockets", "concept", "Backend & Data", ("socket.io", "websocket")),
    ("PostgreSQL", "database", "Backend & Data", ("postgres", "psql", "pg")),
    ("MongoDB", "database", "Backend & Data", ("mongo", "mongoose")),
    ("MySQL", "database", "Backend & Data", ("mariadb",)),
    ("SQLite", "database", "Backend & Data", ()),
    ("Redis", "database", "Backend & Data", ("ioredis",)),
    ("Neo4j", "database", "Backend & Data", ("cypher",)),
    ("Firebase", "platform", "Backend & Data", ("firebase auth", "firebase authentication", "firebase storage", "firebase_core")),
    ("Cloud Firestore", "database", "Backend & Data", ("firestore",)),
    ("Prisma", "library", "Backend & Data", ("prisma orm",)),
    ("Pydantic", "library", "Backend & Data", ()),
    ("JWT authentication", "concept", "Backend & Data", ("jwt", "json web tokens")),
    ("OAuth", "concept", "Backend & Data", ("google sign-in", "oauth2")),
    ("Stripe", "platform", "Backend & Data", ("stripe payments",)),
    ("Web scraping", "concept", "Backend & Data", ("beautifulsoup", "beautifulsoup4", "scraping")),
    ("RSS", "concept", "Backend & Data", ("feedparser", "rss feeds")),
    ("Data modeling", "practice", "Backend & Data", ("data model", "database design")),
    ("Email automation", "concept", "Backend & Data", ("smtp", "email notifications")),
    # ── devops & cloud
    ("Docker", "devops", "DevOps & Cloud", ("dockerfile", "containers", "containerization", "containerized")),
    ("Docker Compose", "devops", "DevOps & Cloud", ("docker-compose", "compose file")),
    ("Kubernetes", "devops", "DevOps & Cloud", ("k8s", "kubernetes cluster")),
    ("k3s", "devops", "DevOps & Cloud", ("k3s cluster",)),
    ("Helm", "devops", "DevOps & Cloud", ("helm charts",)),
    ("Argo CD", "devops", "DevOps & Cloud", ("argocd", "argo-cd")),
    ("GitOps", "practice", "DevOps & Cloud", ()),
    (
        "CI/CD",
        "practice",
        "DevOps & Cloud",
        ("ci", "cd", "continuous integration", "continuous delivery", "ci pipelines"),
    ),
    ("GitHub Actions", "devops", "DevOps & Cloud", ("gh actions",)),
    ("Nginx", "devops", "DevOps & Cloud", ()),
    ("Traefik", "devops", "DevOps & Cloud", ()),
    ("cert-manager", "devops", "DevOps & Cloud", ("let's encrypt", "letsencrypt")),
    ("Linux", "platform", "DevOps & Cloud", ("ubuntu", "debian")),
    ("Cloud architecture", "practice", "DevOps & Cloud", ("cloud", "cloud infrastructure")),
    ("Oracle Cloud", "cloud", "DevOps & Cloud", ("oci", "oracle cloud infrastructure")),
    ("Vercel", "cloud", "DevOps & Cloud", ()),
    ("Netlify", "cloud", "DevOps & Cloud", ()),
    ("PM2", "devops", "DevOps & Cloud", ()),
    (
        "Cron jobs",
        "devops",
        "DevOps & Cloud",
        ("cronjob", "cronjobs", "kubernetes cronjob", "scheduled jobs"),
    ),
    ("Observability", "practice", "DevOps & Cloud", ("prometheus", "monitoring", "opentelemetry")),
    ("DNS & hosting", "practice", "DevOps & Cloud", ("dns", "hosting", "domain setup", "web hosting", "domain management")),
    ("Terraform", "devops", "DevOps & Cloud", ()),
    ("Webhooks", "concept", "DevOps & Cloud", ("webhook",)),
    # ── practices
    ("Design patterns", "practice", "Practices", ()),
    ("Git", "tool", "Practices", ()),
    ("Code review", "practice", "Practices", ("code reviews", "peer code reviews", "peer review")),
    ("Agile/Scrum", "practice", "Practices", ("agile", "scrum")),
    ("Technical audit", "practice", "Practices", ("technical audits", "audits")),
    ("Technical training", "practice", "Practices", ("training", "teaching")),
    ("Requirements gathering", "practice", "Practices", ("requirements analysis",)),
    ("Web development", "practice", "Practices", ("website development", "web dev")),
    ("Testing", "practice", "Practices", ("unit testing", "pytest", "jest", "vitest", "playwright")),
    ("MVVM", "concept", "Practices", ("model-view-viewmodel",)),
    ("Object-oriented programming", "practice", "Practices", ("oop", "object oriented programming")),
    ("Localization", "concept", "Practices", ("l10n", "i18n", "internationalization", "multilingual", "bilingual")),
    # ── domain knowledge
    ("IoT", "domain-knowledge", "Domain expertise", ("iot sensors", "internet of things", "field sensors", "sensors")),
    ("Satellite imagery", "domain-knowledge", "Domain expertise", ("remote sensing",)),
    ("Drone data", "domain-knowledge", "Domain expertise", ("drones", "uav data")),
    ("Sensor data fusion", "domain-knowledge", "Domain expertise", ("data fusion",)),
    ("Real-time monitoring", "domain-knowledge", "Domain expertise", ("realtime monitoring", "real-time data processing")),
    ("Alerting", "domain-knowledge", "Domain expertise", ("automated alerts", "alerts")),
    ("Game development", "domain-knowledge", "Domain expertise", ("shoot 'em up", "shmup", "2d game")),
    ("Geolocation", "domain-knowledge", "Domain expertise", ("gps", "maps", "location services")),
    ("Technology watch", "domain-knowledge", "Domain expertise", ("tech watch", "veille technologique")),
]

# fmt: on

# Too generic to be useful as graph nodes ("Software development", "Programming"…).
GENERIC_SKILLS = {
    "softwaredevelopment", "softwareengineering", "programming", "coding", "development", "fullstackdevelopment",
    "webapplications", "applicationdevelopment", "artificialintelligence", "ai", "technology", "computerscience",
    "problemsolving", "teamwork", "communication", "documentation", "frontend", "backend", "fullstack",
}  # fmt: skip

DOMAINS = [
    "Languages",
    "Applied AI",
    "Frontend",
    "Mobile",
    "Backend & Data",
    "DevOps & Cloud",
    "Practices",
    "Domain expertise",
]

_BY_KEY: dict[str, Tech] = {}
for _name, _category, _domain, _aliases in _TECH:
    _tech = Tech(_name, _category, _domain)
    for _label in (_name, *_aliases):
        _BY_KEY.setdefault(normalize_name(_label), _tech)

_VERSION_SUFFIX = re.compile(r"\s+v?\d+(\.\d+|\.x)*\+?$", re.IGNORECASE)


def canonical(name: str) -> Tech | None:
    """Resolve any alias ('k8s', 'React 19', 'Postgres') to its canonical technology."""
    cleaned = _VERSION_SUFFIX.sub("", name.strip())
    for candidate in (cleaned, name):
        if tech := _BY_KEY.get(normalize_name(candidate)):
            return tech
    return None


def all_aliases(tech_name: str) -> list[str]:
    for name, _, _, aliases in _TECH:
        if name == tech_name:
            return list(aliases)
    return []


# Using X demonstrates Y (e.g. calling the Gemini API is hands-on LLM work).
IMPLIES: dict[str, tuple[str, ...]] = {
    "LangGraph": ("AI Agents", "LLMs"),
    "LangChain": ("LLMs",),
    "Gemini": ("LLMs",),
    "OpenAI API": ("LLMs",),
    "Mistral AI": ("LLMs",),
    "Anthropic Claude": ("LLMs",),
    "Vercel AI SDK": ("LLMs",),
    "GraphRAG": ("RAG", "Knowledge graphs"),
    "Model Context Protocol (MCP)": ("AI Agents",),
    "k3s": ("Kubernetes",),
    "Argo CD": ("GitOps", "Kubernetes"),
    "Docker Compose": ("Docker",),
    "GitHub Actions": ("CI/CD",),
    "NestJS": ("Node.js",),
    "Express": ("Node.js",),
    "Next.js": ("React",),
    "React Native": ("React",),
    "Jetpack Compose": ("Android", "Kotlin"),
    "Flutter": ("Dart",),
    "Cloud Firestore": ("Firebase",),
    "Phalcon": ("PHP",),
    "Angular": ("TypeScript",),
}


# ── dependency manifests ─────────────────────────────────────────────────────
NPM: dict[str, str] = {
    "react": "React", "react-dom": "React", "next": "Next.js", "@angular/core": "Angular", "vue": "Vue.js",
    "vite": "Vite", "tailwindcss": "Tailwind CSS", "@tailwindcss/vite": "Tailwind CSS",
    "@tailwindcss/postcss": "Tailwind CSS", "framer-motion": "Framer Motion", "motion": "Framer Motion",
    "react-router": "React Router", "react-router-dom": "React Router", "leaflet": "Leaflet",
    "react-leaflet": "Leaflet", "idb": "IndexedDB", "dexie": "IndexedDB", "i18next": "i18next",
    "react-i18next": "i18next", "three": "Three.js", "@nestjs/core": "NestJS", "express": "Express",
    "prisma": "Prisma", "@prisma/client": "Prisma", "pg": "PostgreSQL", "mongoose": "MongoDB",
    "mongodb": "MongoDB", "mysql2": "MySQL", "redis": "Redis", "ioredis": "Redis", "openai": "OpenAI API",
    "@google/generative-ai": "Gemini", "@google/genai": "Gemini", "@mistralai/mistralai": "Mistral AI",
    "@anthropic-ai/sdk": "Anthropic Claude", "langchain": "LangChain", "@langchain/core": "LangChain",
    "@langchain/langgraph": "LangGraph", "stripe": "Stripe", "firebase": "Firebase", "socket.io": "WebSockets",
    "jsonwebtoken": "JWT authentication", "passport-jwt": "JWT authentication", "@nestjs/jwt": "JWT authentication",
    "typescript": "TypeScript", "react-native": "React Native", "expo": "React Native", "@nx/workspace": "Nx",
    "nx": "Nx", "rxjs": "RxJS", "@reduxjs/toolkit": "Redux", "@tanstack/react-query": "TanStack Query",
    "jest": "Testing", "vitest": "Testing", "@playwright/test": "Testing", "cypress": "Testing",
    "workbox-window": "Service Workers", "vite-plugin-pwa": "PWA", "pm2": "PM2", "neo4j-driver": "Neo4j",
    "node-cron": "Cron jobs", "nodemailer": "Email automation", "ai": "Vercel AI SDK", "@ai-sdk/react": "Vercel AI SDK",
}  # fmt: skip

PYPI: dict[str, str] = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "langchain": "LangChain",
    "langchain-core": "LangChain", "langgraph": "LangGraph", "langchain-google-genai": "Gemini",
    "google-genai": "Gemini", "google-generativeai": "Gemini", "langchain-mistralai": "Mistral AI",
    "mistralai": "Mistral AI", "openai": "OpenAI API", "anthropic": "Anthropic Claude", "pydantic": "Pydantic",
    "beautifulsoup4": "Web scraping", "feedparser": "RSS", "neo4j": "Neo4j", "psycopg": "PostgreSQL",
    "psycopg2": "PostgreSQL", "psycopg2-binary": "PostgreSQL", "asyncpg": "PostgreSQL", "pymongo": "MongoDB",
    "redis": "Redis", "pytest": "Testing", "prometheus-client": "Observability", "mcp": "Model Context Protocol (MCP)",
    "scikit-learn": "Machine learning", "torch": "Machine learning",
}  # fmt: skip

PUB: dict[str, str] = {
    "flutter": "Flutter", "firebase_core": "Firebase", "firebase_auth": "Firebase", "cloud_firestore": "Cloud Firestore",
    "firebase_storage": "Firebase", "google_sign_in": "OAuth", "provider": "Flutter", "http": "REST APIs",
    "intl": "Localization", "sqflite": "SQLite",
}  # fmt: skip

GRADLE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"compose", re.I), "Jetpack Compose"),
    (re.compile(r"retrofit", re.I), "Retrofit"),
    (re.compile(r"kotlinx[-.]coroutines", re.I), "Kotlin Coroutines"),
    (re.compile(r"material3|material-icons", re.I), "Material Design"),
    (re.compile(r"play-services-location", re.I), "Geolocation"),
    (re.compile(r"moshi|gson|kotlinx[-.]serialization", re.I), "REST APIs"),
    (re.compile(r"room-runtime|androidx\.room", re.I), "SQLite"),
    (re.compile(r"com\.android\.application|android\s*\{", re.I), "Android"),
    (re.compile(r"kotlin", re.I), "Kotlin"),
]

# (path regex, canonical tech) — presence of the file is the evidence.
FILE_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(^|/)Dockerfile(\.[\w-]+)?$"), "Docker"),
    (re.compile(r"(^|/)(docker-)?compose(\.[\w-]+)?\.ya?ml$"), "Docker Compose"),
    (re.compile(r"(^|/)\.github/workflows/[^/]+\.ya?ml$"), "GitHub Actions"),
    (re.compile(r"(^|/)\.gitlab-ci\.yml$"), "CI/CD"),
    (re.compile(r"(^|/)nginx[^/]*\.conf$"), "Nginx"),
    (re.compile(r"(^|/)ecosystem\.config\.[cm]?js$"), "PM2"),
    (re.compile(r"(^|/)vercel\.json$"), "Vercel"),
    (re.compile(r"(^|/)netlify\.toml$"), "Netlify"),
    (re.compile(r"(^|/)firebase\.json$"), "Firebase"),
    (re.compile(r"(^|/)Chart\.yaml$"), "Helm"),
    (re.compile(r"\.tf$"), "Terraform"),
    (re.compile(r"(^|/)schema\.prisma$"), "Prisma"),
    (re.compile(r"(^|/)vite\.config\.[cm]?[jt]s$"), "Vite"),
    (re.compile(r"(^|/)next\.config\.[cm]?[jt]s$"), "Next.js"),
    (re.compile(r"(^|/)tailwind\.config\.[cm]?[jt]s$"), "Tailwind CSS"),
    (re.compile(r"(^|/)angular\.json$"), "Angular"),
    (re.compile(r"(^|/)nx\.json$"), "Nx"),
    (re.compile(r"(^|/)tsconfig(\.[\w-]+)?\.json$"), "TypeScript"),
    (re.compile(r"(^|/)(sw|service-worker)\.[jt]s$"), "Service Workers"),
    (re.compile(r"(^|/)(manifest\.webmanifest|site\.webmanifest)$"), "PWA"),
    (re.compile(r"(^|/)pubspec\.yaml$"), "Flutter"),
    (re.compile(r"\.kts?$"), "Kotlin"),
    (re.compile(r"\.as$"), "ActionScript"),
    (re.compile(r"(^|/)(pytest\.ini|conftest\.py)$"), "Testing"),
    (re.compile(r"\.(spec|test)\.[jt]sx?$"), "Testing"),
]

K8S_KIND = re.compile(
    r"^kind:\s*(Deployment|StatefulSet|Service|Ingress|CronJob|Job|DaemonSet|ConfigMap|PersistentVolumeClaim)\s*$",
    re.M,
)
K8S_CONTENT_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"traefik", re.I), "Traefik"),
    (re.compile(r"cert-manager\.io", re.I), "cert-manager"),
    (re.compile(r"^kind:\s*CronJob", re.M), "Cron jobs"),
    (re.compile(r"k3s|local-path", re.I), "k3s"),
    (re.compile(r"argoproj\.io", re.I), "Argo CD"),
]


def _dep_name(spec: str) -> str:
    return re.split(r"[\s<>=!~\[;@]", spec.strip(), maxsplit=1)[0].lower()


def detect_from_manifest(path: str, content: str) -> set[str]:
    """Return canonical technologies evidenced by a dependency manifest or config file."""
    found: set[str] = set()
    base = path.rsplit("/", 1)[-1]
    try:
        if base == "package.json":
            data = json.loads(content)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            found.add("Node.js")
            for dep in deps:
                if tech := NPM.get(dep.lower()):
                    found.add(tech)
                elif dep.startswith("@langchain/"):
                    found.add("LangChain")
                elif dep.startswith("@nestjs/"):
                    found.add("NestJS")
                elif dep.startswith("@angular/"):
                    found.add("Angular")
                elif dep.startswith("@radix-ui/") and "shadcn" not in found:
                    found.add("shadcn/ui")
        elif re.fullmatch(r"requirements[\w.-]*\.txt", base):
            found.add("Python")
            for line in content.splitlines():
                line = line.split("#", 1)[0].strip()
                if line and (tech := PYPI.get(_dep_name(line))):
                    found.add(tech)
        elif base == "pyproject.toml":
            found.add("Python")
            data = tomllib.loads(content)
            py_deps: list[str] = list(data.get("project", {}).get("dependencies", []))
            py_deps += list(data.get("tool", {}).get("poetry", {}).get("dependencies", {}))
            for spec in py_deps:
                if tech := PYPI.get(_dep_name(spec)):
                    found.add(tech)
        elif base == "pubspec.yaml":
            found.update({"Flutter", "Dart"})
            data = yaml.safe_load(content) or {}
            for dep in data.get("dependencies") or {}:
                if tech := PUB.get(str(dep)):
                    found.add(tech)
        elif re.fullmatch(r"(build|settings)\.gradle(\.kts)?|libs\.versions\.toml", base):
            for pattern, tech in GRADLE_PATTERNS:
                if pattern.search(content):
                    found.add(tech)
        elif base == "composer.json":
            found.add("PHP")
            data = json.loads(content)
            if any("phalcon" in dep for dep in data.get("require", {})):
                found.add("Phalcon")
        elif base.endswith((".yaml", ".yml")) and K8S_KIND.search(content) and "apiVersion:" in content:
            found.add("Kubernetes")
            for pattern, tech in K8S_CONTENT_RULES:
                if pattern.search(content):
                    found.add(tech)
        elif base.startswith("Dockerfile"):
            found.add("Docker")
    except ValueError, yaml.YAMLError, tomllib.TOMLDecodeError:
        return found
    return found


def detect_from_paths(paths: list[str]) -> dict[str, str]:
    """Technologies evidenced by the mere presence of files → {tech: example path}."""
    found: dict[str, str] = {}
    for path in paths:
        for pattern, tech in FILE_RULES:
            if tech not in found and pattern.search(path):
                found[tech] = path
    return found


GITHUB_LANGUAGES: dict[str, str] = {
    "Python": "Python", "TypeScript": "TypeScript", "JavaScript": "JavaScript", "PHP": "PHP", "Kotlin": "Kotlin",
    "Dart": "Dart", "Java": "Java", "ActionScript": "ActionScript", "Go": "Go", "Rust": "Rust", "C#": "C#",
    "Vue": "Vue.js", "Shell": "Bash", "PLpgSQL": "SQL", "TSQL": "SQL",
}  # fmt: skip
GENERATED_LANGUAGES = {"C++", "CMake", "Swift", "Objective-C", "Ruby", "C"}
