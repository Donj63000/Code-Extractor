from __future__ import annotations
import fnmatch
import json, logging, os, queue, re, shlex, subprocess, sys, threading, tkinter as tk
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Protocol, Sequence
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from datetime import datetime
import shutil

APP_NAME = "CodeViewer"
DEFAULT_OUT = "symfony_project.txt"
READ_CHUNK = 1 << 20
PREVIEW_MAX = 4 << 20
MAX_RECENTS = 10
CFG_PATH = Path.home() / ".concat_project.cfg"
IGNORED_DIRS = {".git", ".idea", ".vscode", "var", "node_modules", "build", "dist", "coverage", ".cache", ".venv", "venv"}
MIN_LEFT = 240
MIN_RIGHT = 360
_STALE_FILTER_VALUES = {
    "filtrer par chemin…",
    "filtrer…",
    "filtrer par chemin...",
    "filtrer...",
    "filtrer par chemin",
    "filtrer",
}

AI_RELEVANT_EXT = {
    ".py", ".pyi", ".pyw", ".rb", ".php", ".twig", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".kts", ".cs", ".go", ".rs", ".dart", ".scala", ".swift",
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".m", ".mm", ".sql",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro", ".cshtml", ".razor",
    ".yaml", ".yml", ".toml", ".ini", ".conf",
    ".proto", ".graphql", ".gql", ".gradle", ".groovy", ".md", ".rst", ".tex", ".txt", ".ps1", ".sh", ".bash", ".bat", ".cmd"
}
AI_IMPORTANT_FILENAMES = {
    "readme", "readme.md", "readme.txt", "readme.rst", "license", "license.txt", "copying", "changelog", "changelog.md",
    "contributing.md", "code_of_conduct.md", "security.md",
    "package.json", "composer.json",
    "requirements.txt", "requirements-dev.txt", "requirements.in", "pipfile", "pipfile.lock",
    "pyproject.toml", "setup.py", "setup.cfg", "tox.ini", "pytest.ini", "mypy.ini", "ruff.toml",
    ".flake8", ".pylintrc", ".editorconfig", ".gitignore", ".gitattributes",
    ".prettierrc", ".prettierrc.json", ".prettierrc.js", ".prettierrc.cjs", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json",
    ".stylelintrc", ".stylelintrc.json", ".babelrc", ".babelrc.json",
    "dockerfile", "docker-compose.yml", "docker-compose.yaml", "docker-compose.override.yml",
    "makefile", "cmakelists.txt", "build.gradle", "build.gradle.kts", "gradle.properties",
    "manage.py", "artisan", "console.php", "procfile",
    "tsconfig.json", "vite.config.ts", "vite.config.js", "webpack.config.js", "webpack.config.ts",
    "angular.json", "nx.json", "package.yaml", "manifest.json", "vercel.json", "netlify.toml",
    "cargo.toml", "go.mod", "go.sum", "go.work", "Gemfile",
    "pom.xml", "settings.gradle", "settings.gradle.kts", "appsettings.json", "appsettings.development.json", "appsettings.production.json", "global.json",
    ".env.example", ".env.sample", ".env.template", ".env.test", ".dockerignore", ".npmrc", ".yarnrc", ".yarnrc.yml",
    ".gitmodules", ".pre-commit-config.yaml", ".pre-commit-config.yml", ".tool-versions", "jenkinsfile", "azure-pipelines.yml", "azure-pipelines.yaml", "bitbucket-pipelines.yml",
    "package.bzl", "workspace", "mix.exs", "rebar.config", ".drone.yml", "directory.build.props", "directory.build.targets"
}
AI_IMPORTANT_FILENAMES = {name.lower() for name in AI_IMPORTANT_FILENAMES}

AI_IMPORTANT_SUFFIXES = (
    ".config.js", ".config.cjs", ".config.mjs", ".config.ts", ".config.json",
    ".rc", ".rc.js", ".rc.cjs", ".rc.json", ".rc.yaml", ".rc.yml",
    ".env.example", ".env.sample", ".env.template", ".env.test",
    ".gradle", ".gradle.kts", ".sln", ".csproj", ".props", ".targets"
)

AI_RELEVANT_DIRS = {
    "src", "app", "apps", "config", "configs", "tests", "test", "spec", "specs", "lib", "include", "public",
    "resources", "assets", "templates", "views", "server", "client", "scripts", "bin",
    "infra", "infrastructure", "deploy", "docker", ".github", ".gitlab", ".circleci", ".azure", ".pipelines",
    "backend", "frontend", "packages", "modules", ".vscode"
}

AI_IGNORE_FILENAMES = {
    ".env", ".env.local", ".env.production", ".env.development", ".env.test.local",
    ".ds_store", "thumbs.db", "desktop.ini"
}

AI_IGNORE_SUFFIXES = (".log", ".tmp", ".cache", ".bak", ".swp", ".old", ".orig")

AI_IGNORE_DIRS = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vscode", ".venv", "venv", "build", "dist", "coverage", ".cache", "node_modules"
}

# --- IA : paramètres avancés (peuvent être surchargés via variables d'environnement)
AI_MAX_BYTES = int(os.getenv("AI_MAX_BYTES", "1048576"))  # 1 MiB par défaut

# Fichiers générés/bruit à exclure systématiquement en mode IA
AI_MINIFIED_SUFFIXES = (".min.js", ".min.css", ".bundle.js", ".chunk.js")
AI_MAP_SUFFIXES = (".map",)

# Répertoires supplémentaires "bruit" (builds front, caches divers) — effectifs pour la pertinence IA
AI_IGNORE_DIRS |= {
    "public/build", "public/bundles", ".next", ".nuxt", ".output", ".parcel-cache",
    ".storybook-static", ".svelte-kit", ".vercel", ".netlify", "tmp", "temp"
}

# Répertoires à ignorer dans l'énumération brute (gains de perfs), si pertinent dans votre contexte
IGNORED_DIRS |= {
    "public/build", "public/bundles", ".next", ".nuxt", ".output", ".parcel-cache",
    ".storybook-static", ".svelte-kit", ".vercel", ".netlify", "tmp", "temp"
}

CLIPBOARD_MAX = int(os.getenv("CLIPBOARD_MAX", str(8 << 20)))  # 8 MiB par défaut

AI_REASON_LABELS = {
    "gitattributes": ".gitattributes",
    "size": "> AI_MAX_BYTES",
    "gitignore": ".gitignore",
    "sourcemap": "sourcemap",
    "minified": "minifie",
    "lockfile": "lockfile",
    "markdown": "markdown secondaire",
    "noise": "fichier bruit",
    "ignored_dir": "repertoire ignore",
    "non_relevant": "non pertinent",
}

SENSITIVE_FILENAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.test",
    ".env.example",
    ".env.sample",
    ".env.template",
    "id_rsa",
    "id_rsa.pub",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".pfx", ".p12", ".crt")
SENSITIVE_KEYWORDS = ("secret", "api_key", "apikey", "password", "credential", "token")

# --- Extraction ENV : patterns multi-langages
ENV_REGEXES = [
    # Symfony YAML / PHP
    re.compile(r'%env\((?P<name>[A-Z0-9_]{2,})\)%'),
    re.compile(r'env\((?P<name>[A-Z0-9_]{2,})\)'),

    # PHP
    re.compile(r'getenv\(\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\)'),
    re.compile(r'\$_ENV\[\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),
    re.compile(r'\$_SERVER\[\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),

    # JavaScript / Node / Vite
    re.compile(r'process\.env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)'),
    re.compile(r'process\.env\[\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),
    re.compile(r'import\.meta\.env\.(?P<name>[A-Za-z_][A-Za-z0-9_]*)'),

    # Python
    re.compile(r'os\.getenv\(\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\)'),
    re.compile(r'os\.environ\[\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),

    # Ruby
    re.compile(r'ENV\[\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\]'),

    # Java
    re.compile(r'System\.getenv\(\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\)'),

    # Go
    re.compile(r'os\.Getenv\(\s*[\'"](?P<name>[A-Za-z_][A-Za-z0-9_]*)[\'"]\s*\)'),

    # .env / shell lines / docker list items
    re.compile(r'^\s*(?:export\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*=', re.MULTILINE),
    re.compile(r'^\s*-\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)\s*[:=]', re.MULTILINE),

    # ${VAR} expansions (docker-compose, yaml, etc.)
    re.compile(r'\$\{\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)'),
]

ENV_CATEGORY_RULES = [
    ("database",   re.compile(r'^(DATABASE_URL|DB_|MYSQL_|POSTGRES_|PG_|REDIS_)')),
    ("mail",       re.compile(r'^(MAILER_DSN|MAIL_|SMTP_|SENDGRID_|POSTMARK_)')),
    ("mercure",    re.compile(r'^MERCURE_')),
    ("stripe",     re.compile(r'^STRIPE_')),
    ("runtime",    re.compile(r'^(APP_ENV|APP_SECRET|APP_DEBUG|APP_URL|APP_NAME|TRUSTED_)')),
    ("cache",      re.compile(r'^(CACHE_|REDIS_)')),
    ("queue",      re.compile(r'^(RABBITMQ_|KAFKA_|SQS_|QUEUE_)')),
    ("storage",    re.compile(r'^(AWS_|S3_|GCS_|AZURE_)')),
    ("monitoring", re.compile(r'^(SENTRY_|NEW_RELIC|DATADOG)')),
]

ENV_HINTS = {
    "DATABASE_URL": "ex: mysql://user:pass@localhost:3306/dbname",
    "MAILER_DSN": "ex: smtp://user:pass@localhost:1025",
    "MERCURE_URL": "ex: http://localhost/.well-known/mercure",
    "MERCURE_PUBLIC_URL": "ex: http://localhost/.well-known/mercure",
    "MERCURE_JWT_SECRET": "ex: change-me",
    "STRIPE_PUBLIC_KEY": "ex: pk_test_...",
    "STRIPE_SECRET_KEY": "ex: sk_test_...",
    "APP_SECRET": "ex: `openssl rand -hex 16`",
}

# Palette UI (dark / light)
PALETTES = {
    "dark": {
        "bg": "#05050F",
        "bg_alt": "#0B1020",
        "toolbar_bg": "#0B1020",
        "panel_bg": "#101733",
        "panel_border": "#1F2B55",
        "panel_border_dim": "#161E3A",
        "input_bg": "#151D3F",
        "row_odd": "#131C3C",
        "row_even": "#101733",
        "row_hover": "#1E2A54",
        "fg": "#E6ECFF",
        "fg_dim": "#8F9DC5",
        "accent": "#21F6FF",
        "accent_hover": "#4CD4FF",
        "accent_text": "#05050F",
        "button_hover": "#1C2B58",
        "sel_bg": "#28F5FF",
        "sel_fg": "#05060F",
        "pb_trough": "#0E152F",
        "pb_bar": "#56F4FF",
        "file_fg": "#EAF0FF",
        "code_bg": "#0B1124",
        "code_fg": "#E9EFFF",
        "border": "#1F2B55",
        "border_active": "#45E5FF",
        "badge_bg": "#17254A",
        "badge_fg": "#67E2FF",
        "badge_outline": "#233466",
        "chip_bg": "#151F3D",
        "chip_fg": "#9CB1EA",
        "chip_hover_bg": "#1D2B54",
        "chip_sel_bg": "#2B46A7",
        "chip_sel_fg": "#EAF0FF",
        "glow": "#21F6FF",
        "glow_soft": "#1A2F5C",
        "shadow": "#03040A",
        "scroll_bg": "#0F162F",
        "scroll_thumb": "#273660",
        "scroll_thumb_active": "#34A3FF",
    },
    "light": {
        "bg": "#F2F5FF",
        "bg_alt": "#FFFFFF",
        "toolbar_bg": "#E7ECFF",
        "panel_bg": "#FFFFFF",
        "panel_border": "#C7D4FF",
        "panel_border_dim": "#D8E2FF",
        "input_bg": "#F8FAFF",
        "row_odd": "#F2F7FF",
        "row_even": "#FFFFFF",
        "row_hover": "#E3ECFF",
        "fg": "#1B2442",
        "fg_dim": "#5C6A94",
        "accent": "#4268FF",
        "accent_hover": "#5F80FF",
        "accent_text": "#FFFFFF",
        "button_hover": "#D8E3FF",
        "sel_bg": "#5B7CFF",
        "sel_fg": "#FFFFFF",
        "pb_trough": "#D8E2FF",
        "pb_bar": "#4F76FF",
        "file_fg": "#22305A",
        "code_bg": "#FFFFFF",
        "code_fg": "#1B2442",
        "border": "#CBD6FF",
        "border_active": "#4268FF",
        "badge_bg": "#E8EDFF",
        "badge_fg": "#2E4CB3",
        "badge_outline": "#C5D2FF",
        "chip_bg": "#ECF1FF",
        "chip_fg": "#4A5D97",
        "chip_hover_bg": "#DAE4FF",
        "chip_sel_bg": "#4F76FF",
        "chip_sel_fg": "#FFFFFF",
        "glow": "#83A0FF",
        "glow_soft": "#E4EAFF",
        "shadow": "#CBD6FF",
        "scroll_bg": "#E2E8FF",
        "scroll_thumb": "#B8C5FF",
        "scroll_thumb_active": "#8DA3FF",
    },
}

# Commande Codex CLI (surchargable via variable d'environnement)
CODEX_CMD = os.getenv("CODEX_CMD", "codex")

LOGGER = logging.getLogger("concat_app")
if not LOGGER.handlers:
    handler = logging.FileHandler(Path.home() / ".concat_project.log", encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    LOGGER.addHandler(handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False

def _base_ext() -> set[str]:
    # Ensemble d'extensions par defaut (large couverture de langages)
    base = {
        # Web / scripts
        ".php", ".twig", ".html", ".htm", ".yaml", ".yml", ".json", ".js", ".mjs", ".cjs",
        ".ts", ".tsx", ".jsx", ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro",
        # Shell / batch / powershell
        ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1",
        # Python / Ruby / Perl / R / Julia
        ".py", ".pyw", ".pyi", ".rb", ".pl", ".pm", ".r", ".jl",
        # Java / Kotlin / Groovy
        ".java", ".kt", ".kts", ".groovy", ".gradle",
        # C / C++ / ObjC / Swift
        ".c", ".h", ".cpp", ".cxx", ".cc", ".hpp", ".hh", ".hxx", ".m", ".mm", ".swift",
        # C# / Go / Rust / Dart / Scala
        ".cs", ".go", ".rs", ".dart", ".scala",
        # Configs / data
        ".env", ".ini", ".conf", ".toml", ".xml", ".sql", ".md",
        # Proto/GraphQL
        ".proto", ".graphql", ".gql",
    }
    extra = os.getenv("CONCAT_EXT_EXTRA", "")
    base |= {("." + x if not x.startswith(".") else x).lower() for x in (s.strip() for s in extra.split(",")) if x}
    if not base:
        raise RuntimeError("no extension allowed")
    return base

ALLOWED_EXT: set[str] = _base_ext()

EXT_LANG = {
    ".php": "php",
    ".twig": "twig",
    ".html": "html",
    ".htm": "html",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".js": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".jsx": "jsx",
    ".css": "css",
    ".scss": "scss",
    ".sass": "sass",
    ".env": "dotenv",
    ".xml": "xml",
    ".ini": "ini",
    ".conf": "ini",
    ".sh": "bash",
    ".bash": "bash",
    ".zsh": "bash",
    ".bat": "bat",
    ".cmd": "bat",
    ".ps1": "powershell",
    ".py": "python",
    ".pyw": "python",
    ".pyi": "python",
    ".sql": "sql",
    ".md": "markdown",
    ".rb": "ruby",
    ".pl": "perl",
    ".pm": "perl",
    ".r": "r",
    ".jl": "julia",
    ".java": "java",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".groovy": "groovy",
    ".gradle": "groovy",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".m": "objectivec",
    ".mm": "objectivec",
    ".swift": "swift",
    ".cs": "csharp",
    ".go": "go",
    ".rs": "rust",
    ".dart": "dart",
    ".scala": "scala",
    ".toml": "toml",
    ".vue": "vue",
    ".svelte": "svelte",
    ".astro": "astro",
    ".proto": "protobuf",
    ".graphql": "graphql",
    ".gql": "graphql",
}

def _is_env_like(p: Path) -> bool:
    n = p.name.lower()
    return n == ".env" or n.startswith(".env.")

def _ext_key(p: Path) -> str:
    return ".env" if _is_env_like(p) else p.suffix.lower()

def _lang_for(p: Path) -> str:
    n = p.name.lower()
    if n == ".htaccess":
        return "apacheconf"
    if _is_env_like(p):
        return "dotenv"
    return EXT_LANG.get(p.suffix.lower(), "text")

def _chunks(p: Path) -> Iterable[str]:
    try:
        with p.open("r", encoding="utf-8", errors="strict") as f:
            while True:
                c = f.read(READ_CHUNK)
                if not c:
                    break
                yield c
            return
    except UnicodeDecodeError:
        pass
    for enc in ("utf-8-sig", "cp1252", "latin-1", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            with p.open("r", encoding=enc, errors="replace") as f:
                while True:
                    c = f.read(READ_CHUNK)
                    if not c:
                        break
                    yield c
            return
        except Exception:
            continue
    with p.open("rb") as f:
        while True:
            b = f.read(READ_CHUNK)
            if not b:
                break
            yield b.decode("utf-8", errors="replace")

def _read_preview(p: Path, limit: int = PREVIEW_MAX) -> str:
    acc = []
    total = 0
    for c in _chunks(p):
        acc.append(c)
        total += len(c)
        if total >= limit:
            break
    return "".join(acc)

def _is_allowed_file(p: Path) -> bool:
    if _is_env_like(p):
        return ".env" in ALLOWED_EXT
    return p.suffix.lower() in ALLOWED_EXT

def _normalize_vendor_mode(mode: str | None) -> str:
    return mode if mode in {"none", "symfony", "all"} else "none"

def _vendor_allows_file(rel_parts: Sequence[str], mode: str) -> bool:
    if not rel_parts or rel_parts[0] != "vendor":
        return True
    if mode == "none":
        return False
    if mode == "symfony":
        return len(rel_parts) > 1 and rel_parts[1] == "symfony"
    return True

def _is_sensitive_file(p: Path) -> bool:
    lower = p.name.lower()
    lower_path = str(p).lower()
    if lower in SENSITIVE_FILENAMES:
        return True
    if any(lower.endswith(sfx) for sfx in SENSITIVE_SUFFIXES):
        return True
    if any(keyword in lower or keyword in lower_path for keyword in SENSITIVE_KEYWORDS):
        return True
    return False

def _is_env_sample_file(fp: Path) -> bool:
    n = fp.name.lower()
    return n in {".env.example", ".env.sample", ".env.template"} or n.startswith(".env.test")

def _should_scan_for_env(fp: Path) -> bool:
    try:
        size = fp.stat().st_size
        if size > 2 * (1 << 20):
            return False
    except Exception:
        pass

    lower = fp.name.lower()
    if any(lower.endswith(sfx) for sfx in AI_MAP_SUFFIXES) or any(lower.endswith(sfx) for sfx in AI_MINIFIED_SUFFIXES):
        return False

    if _is_sensitive_file(fp) and not _is_env_sample_file(fp):
        return False
    return True

def _categorize_env(name: str) -> str:
    for cat, rx in ENV_CATEGORY_RULES:
        if rx.search(name):
            return cat
    return "other"

def _extract_env_variables(root: Path, files: Sequence[Path]) -> dict[str, set[str]]:
    """
    Retourne {VAR -> {liste de chemins où la variable a été vue}}.
    Ne remonte que des NOMS de variables (aucune valeur).
    """
    found: dict[str, set[str]] = defaultdict(set)
    for fp in files:
        try:
            if not fp.exists() or not fp.is_file() or not _should_scan_for_env(fp):
                continue
            rel = fp.relative_to(root).as_posix() if root else fp.as_posix()
        except Exception:
            rel = str(fp)
        try:
            for chunk in _chunks(fp):
                for rx in ENV_REGEXES:
                    for match in rx.finditer(chunk):
                        name = match.groupdict().get("name")
                        if not name or len(name) < 2:
                            continue
                        found[name].add(rel)
        except Exception:
            continue
    return found

def _render_env_template(vars_to_paths: dict[str, set[str]]) -> str:
    """
    Construit un .env.example trié par catégories, avec hints et références de fichiers.
    """
    cats: dict[str, list[tuple[str, list[str]]]] = defaultdict(list)
    for name, paths in vars_to_paths.items():
        cat = _categorize_env(name)
        cats[cat].append((name, sorted(paths, key=str.casefold)))

    order = [c for c, _ in ENV_CATEGORY_RULES] + ["other"]
    lines: list[str] = []
    lines.append("# Generated by CodeViewer — ENV template")
    lines.append("# Variables détectées automatiquement (noms uniquement, sans valeurs)")
    lines.append("")

    for cat in [c for c in order if c in cats]:
        sect = {
            "database": "Base de données",
            "mail": "Mail",
            "mercure": "Mercure",
            "stripe": "Stripe (paiement)",
            "runtime": "Runtime / App",
            "cache": "Cache",
            "queue": "Queue / Broker",
            "storage": "Stockage",
            "monitoring": "Monitoring",
            "other": "Autres",
        }.get(cat, cat.capitalize())
        lines.append(f"# --- {sect} ---")
        for name, paths in sorted(cats[cat], key=lambda t: t[0]):
            hint = ENV_HINTS.get(name)
            if hint:
                lines.append(f"# {hint}")
            if paths:
                shown = ", ".join(_shorten(p, 80) for p in paths[:4])
                more = f" (+{len(paths)-4} autres)" if len(paths) > 4 else ""
                lines.append(f"# vu dans: {shown}{more}")
            lines.append(f"{name}=")
            lines.append("")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"

def _env_extract_worker(root: Path, files: Sequence[Path], q: "queue.Queue", cancel: threading.Event | None = None):
    try:
        files = list(files) if files else _discover(root, "none")
        if cancel and cancel.is_set():
            q.put(("cancelled", "env"))
            return
        result = _extract_env_variables(root, files)
        text = _render_env_template(result)
        q.put(("done_env", result, text))
    except Exception as exc:
        LOGGER.exception("Echec extraction ENV", exc_info=exc)
        q.put(("error", str(exc)))

def _has_git(root: Path) -> bool:
    try:
        return (root / ".git").exists()
    except Exception:
        return False

def _git_tracked(root: Path) -> set[Path]:
    git = shutil.which("git")
    if not git or not _has_git(root):
        return set()
    try:
        cp = subprocess.run([git, "-C", str(root), "ls-files", "-z"], capture_output=True, check=True)
        out = cp.stdout.split(b"\x00")
        tracked: set[Path] = set()
        for b in out:
            if not b:
                continue
            try:
                rel = b.decode("utf-8", errors="replace")
            except Exception:
                continue
            p = (root / rel)
            if p.exists() and p.is_file():
                tracked.add(p.resolve())
        return tracked
    except Exception:
        return set()

def _load_gitattributes(root: Path) -> list[tuple[str, set[str]]]:
    rules: list[tuple[str, set[str]]] = []
    p = root / ".gitattributes"
    if not p.exists():
        return rules
    try:
        for raw in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if not parts:
                continue
            pattern = parts[0]
            flags = set(part.split("=", 1)[0] for part in parts[1:])
            rules.append((pattern, flags))
    except Exception:
        pass
    return rules

def _ai_filter_reason(fp: Path, root: Path | None) -> str | None:
    lower = fp.name.lower()
    suffix = fp.suffix.lower()

    # Bruit classique : minifiés, sourcemaps
    if any(lower.endswith(sfx) for sfx in AI_MAP_SUFFIXES) or any(lower.endswith(sfx) for sfx in AI_MINIFIED_SUFFIXES):
        return "sourcemap" if lower.endswith(".map") else "minified"

    # Fichiers à ignorer globalement (logs, backups, etc.)
    if lower in AI_IGNORE_FILENAMES or any(lower.endswith(sfx) for sfx in AI_IGNORE_SUFFIXES):
        return "noise"

    # Markdown : uniquement "importants" (README, LICENSE, CHANGELOG, etc.)
    if suffix == ".md" and lower not in AI_IMPORTANT_FILENAMES:
        return "markdown"

    # Lockfiles : ne pas inclure par défaut pour l'IA (trop volumineux / peu utiles)
    if suffix == ".lock":
        return "lockfile"

    # Important par nom/suffixe
    if lower in AI_IMPORTANT_FILENAMES:
        return None
    if any(lower.endswith(sfx) for sfx in AI_IMPORTANT_SUFFIXES):
        return None

    # Extensions de code
    if suffix in AI_RELEVANT_EXT:
        return None

    # Fichiers sans suffixe mais "importants"
    if suffix == "" and lower in {"makefile", "dockerfile", "procfile"}:
        return None

    # Pertinence par dossier
    try:
        parts = [part.lower() for part in fp.relative_to(root).parts[:-1]] if root else [part.lower() for part in fp.parts[:-1]]
    except Exception:
        parts = [part.lower() for part in fp.parts[:-1]]

    if any(part in AI_IGNORE_DIRS for part in parts):
        return "ignored_dir"

    if any(part in AI_RELEVANT_DIRS for part in parts):
        if suffix in AI_RELEVANT_EXT or lower in AI_IMPORTANT_FILENAMES or any(lower.endswith(sfx) for sfx in AI_IMPORTANT_SUFFIXES):
            return None

    return "non_relevant"

def _ai_is_relevant(fp: Path, root: Path | None) -> bool:
    return _ai_filter_reason(fp, root) is None

def _discover(root: Path, vendor_mode: str) -> list[Path]:
    vendor_mode = _normalize_vendor_mode(vendor_mode)
    files: list[Path] = []
    root_resolved = root.resolve()
    stack = [root_resolved]
    seen = set()
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_symlink():
                            continue
                        path_entry = Path(entry.path)
                        try:
                            rel_parts = path_entry.relative_to(root).parts
                        except Exception:
                            rel_parts = path_entry.parts
                        if entry.is_dir(follow_symlinks=False):
                            name = entry.name
                            if name in IGNORED_DIRS:
                                continue
                            if rel_parts and rel_parts[0] == "vendor":
                                if vendor_mode == "none":
                                    continue
                                if vendor_mode == "symfony":
                                    if len(rel_parts) == 1:
                                        sym = path_entry / "symfony"
                                        if sym.exists() and sym.is_dir():
                                            stack.append(sym)
                                        continue
                                    if len(rel_parts) >= 2 and rel_parts[1] != "symfony":
                                        continue
                            stack.append(path_entry)
                        elif entry.is_file(follow_symlinks=False):
                            if not _vendor_allows_file(rel_parts, vendor_mode):
                                continue
                            if not _is_allowed_file(path_entry):
                                continue
                            rp = path_entry.resolve()
                            if rp in seen:
                                continue
                            seen.add(rp)
                            files.append(path_entry)
                    except Exception:
                        continue
        except Exception:
            continue
    return sorted(files, key=lambda q: q.relative_to(root).as_posix().casefold())
def _human_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    idx = 0
    value = float(size)
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if value >= 100:
        return f"{int(value)} {units[idx]}"
    if value >= 10:
        return f"{value:.1f} {units[idx]}"
    return f"{value:.2f} {units[idx]}"

def _shorten(s: str, maxlen: int = 80) -> str:
    if len(s) <= maxlen:
        return s
    keep = maxlen - 3
    left = keep // 2
    right = keep - left
    return s[:left] + "..." + s[-right:]

class _Cfg:
    def __init__(
        self,
        win="1100x720",
        col=None,
        recent=None,
        ext_state=None,
        theme="dark",
        wrap=False,
        font_size=12,
        pane=520,
        sort_col="name",
        sort_rev=False,
        filter_text="",
        codex_cmd: str = "",
        sort_by_dir: bool = False,
        ai_filter: bool = False,
        include_vendor: bool = False,
        tracked_only: bool = False,
        respect_gitignore: bool = False,
        vendor_mode: str | None = None,
        safe_export_exclude_sensitive: bool = False,
    ):
        self.win_geom = win
        self.col_widths = col or {"name": 320, "size": 100, "rel": 600}
        self.recent_dirs = recent or []
        self.ext_enabled = ext_state or {}
        self.theme = theme
        self.preview_wrap = wrap
        self.preview_font_size = font_size
        self.pane_pos = pane
        self.sort_col = sort_col
        self.sort_rev = sort_rev
        self.filter_text = filter_text
        self.codex_cmd = codex_cmd
        self.sort_by_dir = sort_by_dir
        self.ai_filter = ai_filter
        self.include_vendor = include_vendor  # legacy toggle
        self.tracked_only = tracked_only
        self.respect_gitignore = respect_gitignore
        self.vendor_mode = vendor_mode or ("symfony" if include_vendor else "none")
        if self.vendor_mode not in {"none", "symfony", "all"}:
            self.vendor_mode = "none"
        self.safe_export_exclude_sensitive = safe_export_exclude_sensitive

    @classmethod
    def load(cls):
        try:
            raw = json.loads(CFG_PATH.read_text(encoding="utf-8"))
            win = raw.get("win_geom", "1100x720")
            col = raw.get("col_widths", {"name": 320, "size": 100, "rel": 600})
            recent = [p for p in raw.get("recent_dirs", []) if Path(p).exists()]
            ext_state = raw.get("ext_enabled", {})
            theme = raw.get("theme", "dark")
            wrap = raw.get("preview_wrap", False)
            font_size = int(raw.get("preview_font_size", 12))
            pane = int(raw.get("pane_pos", 520))
            sort_col = raw.get("sort_col", "name")
            sort_rev = bool(raw.get("sort_rev", False))
            filter_text = raw.get("filter_text", "")
            codex_cmd = raw.get("codex_cmd", "")
            sort_by_dir = bool(raw.get("sort_by_dir", False))
            ai_filter = bool(raw.get("ai_filter", False))
            include_vendor = bool(raw.get("include_vendor", False))
            tracked_only = bool(raw.get("tracked_only", False))
            respect_gitignore = bool(raw.get("respect_gitignore", False))
            vendor_mode = raw.get("vendor_mode")
            if not vendor_mode:
                vendor_mode = "symfony" if include_vendor else "none"
            safe_export_exclude_sensitive = bool(raw.get("safe_export_exclude_sensitive", False))
            return cls(
                win,
                col,
                recent,
                ext_state,
                theme,
                wrap,
                font_size,
                pane,
                sort_col,
                sort_rev,
                filter_text,
                codex_cmd,
                sort_by_dir,
                ai_filter,
                include_vendor,
                tracked_only,
                respect_gitignore,
                vendor_mode,
                safe_export_exclude_sensitive,
            )
        except Exception:
            return cls()

    def save(self):
        try:
            CFG_PATH.write_text(
                json.dumps(
                    {
                        "win_geom": self.win_geom,
                        "col_widths": self.col_widths,
                        "recent_dirs": self.recent_dirs,
                        "ext_enabled": self.ext_enabled,
                        "theme": self.theme,
                        "preview_wrap": self.preview_wrap,
                        "preview_font_size": self.preview_font_size,
                        "pane_pos": self.pane_pos,
                        "sort_col": self.sort_col,
                        "sort_rev": self.sort_rev,
                        "filter_text": self.filter_text,
                        "codex_cmd": self.codex_cmd,
                        "sort_by_dir": self.sort_by_dir,
                        "ai_filter": self.ai_filter,
                        "include_vendor": self.vendor_mode != "none",
                        "tracked_only": self.tracked_only,
                        "respect_gitignore": self.respect_gitignore,
                        "vendor_mode": self.vendor_mode,
                        "safe_export_exclude_sensitive": self.safe_export_exclude_sensitive,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

class _Worker(Protocol):
    def __call__(self, root: Path, files: Sequence[Path], *extra, q: "queue.Queue", cancel: threading.Event | None = None): ...

def _export(root: Path, files: Sequence[Path], out_: Path, q: "queue.Queue", cancel: threading.Event | None = None):
    try:
        if not files:
            q.put(("error", "Aucun fichier selectionne."))
            return
        out_.parent.mkdir(parents=True, exist_ok=True)
        files_sorted = sorted(files, key=lambda p: p.relative_to(root).as_posix().casefold())
        total = len(files_sorted)
        intro = _compose_structured_intro(root, files_sorted)
        with out_.open("w", encoding="utf-8", newline="\n") as out:
            out.write(intro + "\n")
            for i, fp in enumerate(files_sorted, 1):
                if cancel and cancel.is_set():
                    q.put(("cancelled", "export"))
                    return
                try:
                    rel = fp.relative_to(root)
                except Exception:
                    rel = fp
                lang = _lang_for(fp)
                out.write(f"### {i}/{total} - {rel}\n{'-'*80}\n")
                out.write(f"```{lang}\n")
                for c in _chunks(fp):
                    if cancel and cancel.is_set():
                        q.put(("cancelled", "export"))
                        return
                    out.write(c)
                out.write("\n```\n\n")
                q.put(("progress", i, total))
        q.put(("done_export", total, out_))
    except Exception as e:
        LOGGER.exception("Echec export", exc_info=e)
        q.put(("error", str(e)))

def _copy(root: Path, files: Sequence[Path], q: "queue.Queue", cancel: threading.Event | None = None):
    try:
        if not files:
            q.put(("error", "Aucun fichier selectionne."))
            return
        total = len(files)
        pieces: list[str] = []
        for i, fp in enumerate(files, 1):
            if cancel and cancel.is_set():
                q.put(("cancelled", "copy"))
                return
            rel = fp.relative_to(root)
            lang = _lang_for(fp)
            pieces.append(f"### File: {rel}\n{'-'*80}\n")
            pieces.append(f"```{lang}\n")
            for c in _chunks(fp):
                if cancel and cancel.is_set():
                    q.put(("cancelled", "copy"))
                    return
                pieces.append(c)
            pieces.append("\n```\n\n")
            q.put(("progress", i, total))
        payload = "".join(pieces)
        if len(payload.encode("utf-8", errors="ignore")) > CLIPBOARD_MAX:
            q.put(("too_large_for_clipboard", total, payload))
        else:
            q.put(("clip_ready", total, payload))
    except Exception as e:
        LOGGER.exception("Echec copie", exc_info=e)
        q.put(("error", str(e)))

def _build_tree_text(root: Path, files: Sequence[Path]) -> str:
    try:
        rels = [fp.relative_to(root).as_posix() for fp in files]
    except Exception:
        rels = [fp.as_posix() for fp in files]
    tree: dict[str, dict] = {}
    for s in rels:
        parts = [p for p in s.split('/') if p]
        d = tree
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                d.setdefault('__files__', []).append(part)
            else:
                d = d.setdefault(part, {})
    lines: list[str] = [f"{Path(root).name}/"]
    def rec(node: dict, prefix: str = "") -> None:
        dirs = sorted([k for k in node.keys() if k != '__files__'], key=lambda x: x.lower())
        files = sorted(node.get('__files__', []), key=lambda x: x.lower())
        entries = [(name + '/', node[name]) for name in dirs] + [(fname, None) for fname in files]
        for idx, (name, sub) in enumerate(entries):
            last = (idx == len(entries) - 1)
            connector = ('`-- ' if last else '|-- ')
            lines.append(prefix + connector + name)
            if sub is not None:
                ext = ('    ' if last else '|   ')
                rec(sub, prefix + ext)
    rec(tree, "")
    return "\n".join(lines)

def _compose_structured_intro(root: Path, files_sorted: Sequence[Path]) -> str:
    try:
        root_res = str(root.resolve())
    except Exception:
        root_res = str(root)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total = len(files_sorted)
    header: list[str] = []
    header.append(f"# Projet: {Path(root).name}")
    header.append(f"Racine: {root_res}")
    header.append(f"Date: {now}")
    header.append(f"Total fichiers: {total}")
    header.append("")
    header.append("## Table des fichiers")
    for fp in files_sorted:
        try:
            rel = fp.relative_to(root).as_posix()
        except Exception:
            rel = fp.as_posix()
        header.append(f"- {rel}")
    header.append("")
    header.append("## Arborescence")
    header.append("")
    header.append("```text")
    header.append(_build_tree_text(root, files_sorted))
    header.append("```")
    header.append("")
    header.append("## Contenu")
    header.append("")
    return "\n".join(header)

def _copy_structured(root: Path, files: Sequence[Path], q: "queue.Queue", cancel: threading.Event | None = None):
    try:
        files = list(files)
        if not files:
            q.put(("error", "Aucun fichier selectionne."))
            return
        files_sorted = sorted(files, key=lambda p: p.relative_to(root).as_posix().casefold())
        total = len(files_sorted)
        intro = _compose_structured_intro(root, files_sorted)
        pieces: list[str] = [intro, ""]
        for i, fp in enumerate(files_sorted, 1):
            if cancel and cancel.is_set():
                q.put(("cancelled", "copy"))
                return
            rel = fp.relative_to(root)
            lang = _lang_for(fp)
            pieces.append(f"### {i}/{total} - {rel}\n{'-'*80}\n")
            pieces.append(f"```{lang}\n")
            for c in _chunks(fp):
                if cancel and cancel.is_set():
                    q.put(("cancelled", "copy"))
                    return
                pieces.append(c)
            pieces.append("\n```\n")
            q.put(("progress", i, total))
        payload = "\n".join(pieces)
        if len(payload.encode("utf-8", errors="ignore")) > CLIPBOARD_MAX:
            q.put(("too_large_for_clipboard", total, payload))
        else:
            q.put(("clip_ready", total, payload))
    except Exception as e:
        LOGGER.exception("Echec copie structuree", exc_info=e)
        q.put(("error", str(e)))

class ConcatApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.cfg = _Cfg.load()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.project_dir: Path | None = Path(self.cfg.recent_dirs[0]).resolve() if self.cfg.recent_dirs and Path(self.cfg.recent_dirs[0]).exists() else None
        self._load_gitignore(self.project_dir)
        self.files_all: list[Path] = []
        self.sort_reverse = self.cfg.sort_rev
        self.sort_col = self.cfg.sort_col
        self.queue: "queue.Queue" = queue.Queue()
        self._size_cache: dict[str, int] = {}
        self.preview_path: Path | None = None
        self._hover_iid: str | None = None
        self._last_total = 0
        self._scan_thread: threading.Thread | None = None
        self.gitignore_rules: list[tuple[str, bool]] = []
        self.git_tracked: set[Path] = set()
        self.gitattributes_rules: list[tuple[str, set[str]]] = []
        self.cancel_event = threading.Event()
        self._filter_after_id: str | None = None
        self.filter_var = tk.StringVar(value=self.cfg.filter_text)
        self.ext_vars = {e: tk.BooleanVar(value=self.cfg.ext_enabled.get(e, True)) for e in sorted(ALLOWED_EXT)}
        if not any(v.get() for v in self.ext_vars.values()):
            for v in self.ext_vars.values():
                v.set(True)
        self.theme_var = tk.BooleanVar(value=(self.cfg.theme == "dark"))
        self.wrap_var = tk.BooleanVar(value=self.cfg.preview_wrap)
        self.font_size = tk.IntVar(value=self.cfg.preview_font_size)
        self.sort_by_dir_var = tk.BooleanVar(value=self.cfg.sort_by_dir)
        self.ai_filter_var = tk.BooleanVar(value=self.cfg.ai_filter)
        self.tracked_only_var = tk.BooleanVar(value=self.cfg.tracked_only)
        self.respect_gitignore_var = tk.BooleanVar(value=self.cfg.respect_gitignore)
        self.vendor_mode_var = tk.StringVar(value=self.cfg.vendor_mode)
        self.safe_export_exclude_sensitive_var = tk.BooleanVar(value=self.cfg.safe_export_exclude_sensitive)
        self._build_fonts()
        self._menubar()
        self._status()
        self._paned()
        self._apply_theme()
        self.title(APP_NAME)
        self.geometry(self.cfg.win_geom)
        self.minsize(920, 560)
        shortcuts = {
            "<Control-o>": self._choose,
            "<Control-s>": self._export_sel,
            "<Control-c>": self._copy_sel,
            "<Control-t>": self._open_terminal_codex,
            "<Control-a>": self._sel_all,
            "<Control-d>": self._clear,
            "<F5>": self._apply,
            "<Control-f>": lambda: (self.entry_filter.focus_set(), "break"),
            "<Control-r>": self._refresh,
            "<Control-plus>": lambda: self._font_step(1),
            "<Control-minus>": lambda: self._font_step(-1),
            "<Control-0>": self._font_reset,
        }
        for seq, cb in shortcuts.items():
            self.bind_all(seq, lambda _e, f=cb: f())
        self.bind_all("<F9>", lambda _e: self._toggle_theme(toggle=True))
        if self.project_dir:
            self._scan_async(self.project_dir)
        self.after(100, self._process)

    def _build_fonts(self):
        if sys.platform.startswith("win"):
            fam = "Consolas"
        elif sys.platform == "darwin":
            fam = "Menlo"
        else:
            fam = "DejaVu Sans Mono"
        self.mono = tkfont.Font(family=fam, size=self.font_size.get())
        self.heading_font = tkfont.Font(family=fam, size=max(13, self.font_size.get() + 1), weight="bold")
        self.small_font = tkfont.Font(family=fam, size=max(10, self.font_size.get() - 2))

    def _refresh_fonts(self):
        base = self.font_size.get()
        self.heading_font.configure(size=max(13, base + 1))
        self.small_font.configure(size=max(10, base - 2))

    def _apply_theme(self) -> None:
        palette_key = "dark" if self.theme_var.get() else "light"
        palette = PALETTES[palette_key].copy()
        self.colors = palette

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        bg = palette["bg"]
        fg = palette["fg"]
        panel_bg = palette.get("panel_bg", palette["bg_alt"])
        panel_border = palette.get("panel_border", palette["border"])
        panel_border_dim = palette.get("panel_border_dim", panel_border)
        accent = palette["accent"]
        accent_hover = palette["accent_hover"]

        style.configure(".", background=bg, foreground=fg, fieldbackground=bg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)

        style.configure("ToolbarCard.TFrame", background=panel_bg, borderwidth=1, relief="groove")
        style.configure("ToolbarPrimary.TFrame", background=panel_bg)
        style.configure("ToolbarSection.TFrame", background=panel_bg)
        style.configure("ToolbarStats.TFrame", background=panel_bg)
        style.configure("Card.TFrame", background=panel_bg)

        style.configure("ToolbarHeading.TLabel", background=panel_bg, foreground=palette["badge_fg"], font=self.heading_font)
        style.configure("ToolbarNote.TLabel", background=panel_bg, foreground=palette["fg_dim"], font=self.small_font)
        style.configure("ToolbarBadge.TLabel", background=palette["badge_bg"], foreground=palette["badge_fg"], font=self.small_font, padding=(14, 6))

        style.configure("PreviewHeader.TFrame", background=panel_bg)
        style.configure("PreviewHeading.TLabel", background=panel_bg, foreground=fg, font=self.heading_font)
        style.configure("PreviewPath.TLabel", background=panel_bg, foreground=palette["fg_dim"], font=self.small_font)
        style.configure("PreviewBadge.TLabel", background=palette["badge_bg"], foreground=palette["badge_fg"], font=self.small_font, padding=(12, 4))
        style.configure("PreviewCheck.TCheckbutton", background=panel_bg, foreground=fg)
        style.map("PreviewCheck.TCheckbutton", background=[("active", panel_bg)], foreground=[("disabled", palette["fg_dim"])])

        style.configure("Status.TFrame", background=panel_bg)
        style.configure("Status.Count.TLabel", background=panel_bg, foreground=fg, font=self.heading_font)
        style.configure("Status.Badge.TLabel", background=palette["badge_bg"], foreground=palette["badge_fg"], padding=(12, 6), font=self.small_font)
        style.configure("Status.Message.TLabel", background=panel_bg, foreground=palette["fg_dim"], font=self.small_font)

        style.configure("TSeparator", background=panel_bg, foreground=panel_border_dim)

        style.configure(
            "TEntry",
            fieldbackground=palette["input_bg"],
            foreground=fg,
            insertcolor=fg,
            bordercolor=panel_border,
            lightcolor=panel_border,
            darkcolor=panel_border,
        )
        style.map("TEntry", bordercolor=[("focus", palette["border_active"])])
        style.configure(
            "Filter.TEntry",
            fieldbackground=palette["input_bg"],
            foreground=fg,
            insertcolor=fg,
            bordercolor=panel_border,
            padding=(14, 9),
        )
        style.map("Filter.TEntry", bordercolor=[("focus", palette["border_active"])])

        style.configure("TCombobox", fieldbackground=palette["input_bg"], foreground=fg, bordercolor=panel_border)
        style.map("TCombobox", fieldbackground=[("readonly", palette["input_bg"])], foreground=[("readonly", fg)])

        style.layout(
            "Toggle.TCheckbutton",
            [
                (
                    "Checkbutton.padding",
                    {
                        "sticky": "nswe",
                        "children": [("Checkbutton.label", {"sticky": "nswe"})],
                    },
                )
            ],
        )
        style.configure(
            "Toggle.TCheckbutton",
            background=palette["chip_bg"],
            foreground=palette["chip_fg"],
            padding=(16, 7),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Toggle.TCheckbutton",
            background=[
                ("selected", palette["chip_sel_bg"]),
                ("pressed", palette["chip_sel_bg"]),
                ("active", palette["chip_hover_bg"]),
            ],
            foreground=[
                ("selected", palette["chip_sel_fg"]),
                ("pressed", palette["chip_sel_fg"]),
                ("active", palette["chip_sel_fg"]),
            ],
        )

        style.configure(
            "Toolbar.TButton",
            background=palette["chip_bg"],
            foreground=fg,
            padding=(16, 10),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Toolbar.TButton",
            background=[("active", palette["chip_hover_bg"]), ("pressed", palette["chip_sel_bg"])],
            foreground=[("disabled", palette["fg_dim"])],
        )

        style.configure(
            "Accent.TButton",
            background=accent,
            foreground=palette["accent_text"],
            padding=(18, 10),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Accent.TButton",
            background=[("active", accent_hover), ("pressed", accent_hover)],
            foreground=[("disabled", palette["fg_dim"])],
        )

        style.configure(
            "Neon.Horizontal.TProgressbar",
            background=palette["pb_bar"],
            troughcolor=palette["pb_trough"],
            thickness=8,
            borderwidth=0,
        )

        style.configure(
            "Vertical.TScrollbar",
            background=palette["scroll_thumb"],
            troughcolor=palette["scroll_bg"],
            borderwidth=0,
            arrowcolor=fg,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", palette["scroll_thumb_active"]), ("!active", palette["scroll_thumb"])],
            arrowcolor=[("disabled", palette["fg_dim"])],
        )
        style.configure(
            "Horizontal.TScrollbar",
            background=palette["scroll_thumb"],
            troughcolor=palette["scroll_bg"],
            borderwidth=0,
            arrowcolor=fg,
        )
        style.map(
            "Horizontal.TScrollbar",
            background=[("active", palette["scroll_thumb_active"]), ("!active", palette["scroll_thumb"])],
            arrowcolor=[("disabled", palette["fg_dim"])],
        )

        style.configure(
            "Neon.Treeview",
            background=panel_bg,
            fieldbackground=panel_bg,
            foreground=palette["file_fg"],
            rowheight=26,
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Neon.Treeview",
            background=[("selected", palette["sel_bg"])],
            foreground=[("selected", palette.get("sel_fg", palette["accent_text"]))],
        )
        style.configure(
            "Treeview.Heading",
            background=panel_bg,
            foreground=fg,
            padding=(14, 9),
            relief="flat",
            font=self.heading_font,
        )
        style.map(
            "Treeview.Heading",
            background=[("active", palette["chip_hover_bg"])],
            foreground=[("active", fg)],
        )

        style.configure("Heading.TLabel", background=panel_bg, foreground=fg, font=self.heading_font)
        style.configure("SmallNote.TLabel", background=panel_bg, foreground=palette["fg_dim"], font=self.small_font)

        self.configure(background=bg)
        if hasattr(self, "toolbar"):
            self.toolbar.configure(style="ToolbarCard.TFrame")
            if hasattr(self, "toolbar_heading"):
                self.toolbar_heading.configure(style="ToolbarHeading.TLabel")
            if hasattr(self, "toolbar_note"):
                self.toolbar_note.configure(style="ToolbarNote.TLabel")
            if hasattr(self, "toolbar_stats_frame"):
                self.toolbar_stats_frame.configure(style="ToolbarStats.TFrame")
            if hasattr(self, "toggles"):
                self.toggles.configure(style="ToolbarSection.TFrame")
        if hasattr(self, "status_bar"):
            self.status_bar.configure(style="Status.TFrame")
            if hasattr(self, "lbl_count"):
                self.lbl_count.configure(style="Status.Count.TLabel")
            if hasattr(self, "lbl_size"):
                self.lbl_size.configure(style="Status.Badge.TLabel")
            if hasattr(self, "lbl_msg"):
                self.lbl_msg.configure(style="Status.Message.TLabel")
        if hasattr(self, "tree"):
            self.tree.configure(style="Neon.Treeview")
            self.tree.tag_configure("odd", background=palette["row_odd"], foreground=palette["file_fg"])
            self.tree.tag_configure("even", background=palette["row_even"], foreground=palette["file_fg"])
            self.tree.tag_configure("hover", background=palette["row_hover"], foreground=palette["file_fg"])
        if hasattr(self, "txt"):
            self.txt.configure(background=palette["code_bg"], foreground=palette["code_fg"], insertbackground=palette["code_fg"])
        if hasattr(self, "entry_filter"):
            self._update_filter_placeholder_style()
        if hasattr(self, "progress"):
            self.progress.configure(style="Neon.Horizontal.TProgressbar")
        if hasattr(self, "preview_header"):
            self.preview_header.configure(style="PreviewHeader.TFrame")
        if hasattr(self, "preview_title"):
            self.preview_title.configure(style="PreviewHeading.TLabel")
        if hasattr(self, "lbl_preview"):
            self.lbl_preview.configure(style="PreviewPath.TLabel")
        if hasattr(self, "preview_meta"):
            self.preview_meta.configure(style="PreviewHeader.TFrame")
        if hasattr(self, "preview_size_badge"):
            self.preview_size_badge.configure(style="PreviewBadge.TLabel")
        if hasattr(self, "preview_mtime_badge"):
            self.preview_mtime_badge.configure(style="PreviewBadge.TLabel")
        if hasattr(self, "stat_total_label"):
            self.stat_total_label.configure(style="ToolbarBadge.TLabel")
        if hasattr(self, "stat_selection_label"):
            self.stat_selection_label.configure(style="ToolbarBadge.TLabel")
        if hasattr(self, "stat_filter_label"):
            self.stat_filter_label.configure(style="ToolbarBadge.TLabel")
        if hasattr(self, "toggle_sort"):
            self.toggle_sort.configure(style="Toggle.TCheckbutton")
        if hasattr(self, "toggle_ai"):
            self.toggle_ai.configure(style="Toggle.TCheckbutton")
        if hasattr(self, "toggle_vendor"):
            self.toggle_vendor.configure(style="Toggle.TCheckbutton")
        if hasattr(self, "toggle_tracked"):
            self.toggle_tracked.configure(style="Toggle.TCheckbutton")
        if hasattr(self, "toggle_gitignore"):
            self.toggle_gitignore.configure(style="Toggle.TCheckbutton")
        if hasattr(self, "toggle_safe_export"):
            self.toggle_safe_export.configure(style="Toggle.TCheckbutton")

    def _update_filter_placeholder_style(self) -> None:
        if not hasattr(self, 'entry_filter'):
            return
        palette = getattr(self, 'colors', {})
        fg = palette.get('fg', '#000000')
        field_bg = palette.get('input_bg', '#ffffff')
        style = ttk.Style(self)
        style.configure('Filter.TEntry', foreground=fg, fieldbackground=field_bg, insertcolor=palette.get('fg', '#000000'), bordercolor=palette.get('border', '#000000'), padding=(12, 8))

    def _menubar(self):
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Ouvrir...", accelerator="Ctrl+O", command=self._choose)
        file_menu.add_command(label="Actualiser", accelerator="Ctrl+R", command=self._refresh)
        file_menu.add_separator()
        file_menu.add_command(label="Exporter...", accelerator="Ctrl+S", command=self._export_sel)
        file_menu.add_command(label="Extraire variables d'environnement...", command=self._extract_env)
        file_menu.add_command(label="Copier le code", accelerator="Ctrl+C", command=self._copy_sel)
        file_menu.add_separator()
        file_menu.add_command(label="Quitter", command=self._close)
        menu.add_cascade(label="Fichier", menu=file_menu)

        edit_menu = tk.Menu(menu, tearoff=False)
        edit_menu.add_command(label="Selectionner tout", accelerator="Ctrl+A", command=self._sel_all)
        edit_menu.add_command(label="Deselectionner", accelerator="Ctrl+D", command=self._clear)
        edit_menu.add_command(label="Inverser la selection", command=self._invert)
        edit_menu.add_separator()
        edit_menu.add_command(label="Filtrer", accelerator="Ctrl+F", command=lambda: self.entry_filter.focus_set())
        menu.add_cascade(label="Edition", menu=edit_menu)

        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_checkbutton(label="Theme sombre", onvalue=True, offvalue=False, variable=self.theme_var, command=self._toggle_theme)
        view_menu.add_checkbutton(label="Retour a la ligne", variable=self.wrap_var, command=self._toggle_wrap)
        view_menu.add_separator()
        view_menu.add_command(label="Police +", accelerator="Ctrl++", command=lambda: self._font_step(1))
        view_menu.add_command(label="Police -", accelerator="Ctrl+-", command=lambda: self._font_step(-1))
        view_menu.add_command(label="Police par defaut", accelerator="Ctrl+0", command=self._font_reset)
        view_menu.add_separator()
        view_menu.add_command(label="Reinitialiser la disposition", command=self._reset_layout)
        view_menu.add_checkbutton(label="Trier par dossier", variable=self.sort_by_dir_var, command=self._resort)
        view_menu.add_checkbutton(label="Trier pour l'IA", variable=self.ai_filter_var, command=self._toggle_ai_filter)
        menu.add_cascade(label="Affichage", menu=view_menu)

        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(
            label="A propos",
            command=lambda: messagebox.showinfo(APP_NAME, "Visionneuse de code avec apercu integre"),
        )
        menu.add_cascade(label="Aide", menu=help_menu)
        self.config(menu=menu)

    def _status(self):
        bar = ttk.Frame(self, padding=(12, 8), style="Status.TFrame")
        bar.pack(fill="x", side="bottom")
        self.status_bar = bar
        bar.grid_columnconfigure(2, weight=1)
        self.lbl_count = ttk.Label(bar, text="Selection 0 / 0", style="Status.Count.TLabel")
        self.lbl_count.grid(row=0, column=0, sticky="w")
        self.lbl_size = ttk.Label(bar, text="Volume 0 B", style="Status.Badge.TLabel")
        self.lbl_size.grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.lbl_msg = ttk.Label(bar, text="Pret", style="Status.Message.TLabel")
        self.lbl_msg.grid(row=0, column=2, sticky="w")
        self.progress = ttk.Progressbar(bar, length=220, mode="determinate", style="Neon.Horizontal.TProgressbar")
        self.progress.grid(row=0, column=3, sticky="e", padx=(16, 0))

    def _toolbar(self, parent: ttk.Frame):
        card = ttk.Frame(parent, style="ToolbarCard.TFrame", padding=(20, 20, 20, 16))
        card.pack(fill="x", pady=(0, 20))
        self.toolbar = card
        card.grid_columnconfigure(0, weight=1)
        card.grid_columnconfigure(1, weight=1)

        def tip(widget: ttk.Widget, text: str) -> None:
            widget.bind("<Enter>", lambda _e: self.lbl_msg.config(text=text))
            widget.bind("<Leave>", lambda _e: self.lbl_msg.config(text="Pret"))

        self.toolbar_heading = ttk.Label(card, text="CodeViewer By Val BETA 1.0", style="ToolbarHeading.TLabel")
        self.toolbar_heading.grid(row=0, column=0, sticky="w")
        self.toolbar_note = ttk.Label(card, text="", style="ToolbarNote.TLabel")
        self.toolbar_note.grid(row=0, column=1, sticky="e")

        ttk.Separator(card).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 18))

        primary = ttk.Frame(card, style="ToolbarPrimary.TFrame")
        primary.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.btn_open = ttk.Button(primary, text="Ouvrir", command=self._choose, style="Accent.TButton")
        self.btn_open.pack(side="left", padx=(0, 12))
        tip(self.btn_open, "Choisir un dossier projet")

        self.combo_recent = ttk.Combobox(primary, state="readonly", values=self.cfg.recent_dirs, width=36)
        self.combo_recent.pack(side="left", padx=(0, 16))
        self.combo_recent.bind("<<ComboboxSelected>>", lambda _e: self._open(Path(self.combo_recent.get())))
        tip(self.combo_recent, "Historique des dossiers ouverts")

        self.btn_refresh = ttk.Button(primary, text="Actualiser", command=self._refresh, style="Toolbar.TButton")
        self.btn_refresh.pack(side="left", padx=(0, 12))
        tip(self.btn_refresh, "Rafraichir la liste de fichiers")

        self.btn_env = ttk.Button(primary, text="Env -> Template", command=self._extract_env, style="Accent.TButton")
        self.btn_env.pack(side="left", padx=(0, 12))
        tip(self.btn_env, "Generer un modele .env")

        self.btn_export = ttk.Button(primary, text="Exporter", command=self._export_sel, state="disabled", style="Accent.TButton")
        self.btn_export.pack(side="left", padx=(0, 12))
        tip(self.btn_export, "Exporter vers un fichier texte avec glow")

        self.btn_copy = ttk.Button(primary, text="Copier", command=self._copy_sel, state="disabled", style="Toolbar.TButton")
        self.btn_copy.pack(side="left", padx=(0, 12))
        tip(self.btn_copy, "Copier le texte concatene")

        self.btn_terminal = ttk.Button(primary, text="Terminal Codex", command=self._open_terminal_codex, style="Toolbar.TButton")
        self.btn_terminal.pack(side="left", padx=(0, 12))
        tip(self.btn_terminal, "Ouvrir un terminal - Ctrl+T")

        self.btn_langs = ttk.Button(primary, text="Extensions", command=self._open_langages_dialog, style="Toolbar.TButton")
        self.btn_langs.pack(side="left", padx=(0, 12))
        tip(self.btn_langs, "Choisir les extensions a inclure")

        self.btn_cancel = ttk.Button(primary, text="Arreter", command=self._cancel_ops, state="disabled", style="Toolbar.TButton")
        self.btn_cancel.pack(side="right")
        tip(self.btn_cancel, "Annuler l'operation en cours")

        filter_bar = ttk.Frame(card, style="ToolbarSection.TFrame")
        filter_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        filter_bar.grid_columnconfigure(1, weight=1)

        ttk.Label(filter_bar, text="Filtrer les chemins", style="ToolbarNote.TLabel").grid(row=0, column=0, sticky="w")

        self.entry_filter = ttk.Entry(filter_bar, textvariable=self.filter_var, style="Filter.TEntry")
        self.entry_filter.grid(row=0, column=1, sticky="ew", padx=(12, 12))
        self.entry_filter.bind("<KeyRelease>", self._on_filter_keystroke)
        self._update_filter_placeholder_style()

        filter_actions = ttk.Frame(filter_bar, style="ToolbarSection.TFrame")
        filter_actions.grid(row=0, column=2, sticky="e")

        btn_apply = ttk.Button(filter_actions, text="Appliquer", command=self._apply, style="Accent.TButton")
        btn_apply.pack(side="left")
        tip(btn_apply, "Appliquer le filtre en temps reel")

        btn_clear = ttk.Button(filter_actions, text="Effacer", command=self._clear_filter, style="Toolbar.TButton")
        btn_clear.pack(side="left", padx=(12, 0))
        tip(btn_clear, "Effacer le filtre et reinitialiser la liste")

        toggles = ttk.Frame(card, style="ToolbarSection.TFrame")
        toggles.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self.toggles = toggles

        self.toggle_sort = ttk.Checkbutton(
            toggles,
            text="Trier par dossiers",
            variable=self.sort_by_dir_var,
            command=self._resort,
            style="Toggle.TCheckbutton",
            takefocus=0,
        )
        self.toggle_sort.pack(side="left")
        tip(self.toggle_sort, "Regrouper les fichiers par dossier")

        self.toggle_ai = ttk.Checkbutton(
            toggles,
            text="Filtre IA",
            variable=self.ai_filter_var,
            command=self._toggle_ai_filter,
            style="Toggle.TCheckbutton",
            takefocus=0,
        )
        self.toggle_ai.pack(side="left", padx=(12, 0))
        tip(self.toggle_ai, "Prioriser les fichiers utiles a l'IA")

        self.toggle_tracked = ttk.Checkbutton(
            toggles,
            text="GitHub exact",
            variable=self.tracked_only_var,
            command=self._toggle_tracked_mode,
            style="Toggle.TCheckbutton",
            takefocus=0,
        )
        self.toggle_tracked.pack(side="left", padx=(12, 0))
        tip(self.toggle_tracked, "Limiter aux fichiers suivis par Git")

        self.toggle_gitignore = ttk.Checkbutton(
            toggles,
            text=".gitignore",
            variable=self.respect_gitignore_var,
            command=self._apply,
            style="Toggle.TCheckbutton",
            takefocus=0,
        )
        self.toggle_gitignore.pack(side="left", padx=(12, 0))
        tip(self.toggle_gitignore, "Respecter les regles .gitignore")

        vendor_frame = ttk.Frame(toggles, style="ToolbarSection.TFrame")
        vendor_frame.pack(side="left", padx=(16, 0))
        ttk.Label(vendor_frame, text="Vendor", style="ToolbarNote.TLabel").pack(side="left", padx=(0, 6))
        for label, value, tooltip in [
            ("Exclu", "none", "Exclure completement vendor"),
            ("Symfony", "symfony", "Limiter a vendor/symfony"),
            ("Tout", "all", "Inclure l'ensemble du vendor"),
        ]:
            rb = ttk.Radiobutton(
                vendor_frame,
                text=label,
                value=value,
                variable=self.vendor_mode_var,
                command=self._toggle_vendor_mode,
                takefocus=0,
            )
            rb.pack(side="left")
            tip(rb, tooltip)

        self.toggle_safe_export = ttk.Checkbutton(
            toggles,
            text="Export sûr",
            variable=self.safe_export_exclude_sensitive_var,
            command=self._toggle_safe_export_mode,
            style="Toggle.TCheckbutton",
            takefocus=0,
        )
        self.toggle_safe_export.pack(side="left", padx=(12, 0))
        tip(self.toggle_safe_export, "Exclure automatiquement les fichiers sensibles (.env, cles…)")

        self.toolbar_stats_frame = ttk.Frame(card, style="ToolbarStats.TFrame")
        self.toolbar_stats_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        self.stat_total_label = ttk.Label(self.toolbar_stats_frame, text="0 fichier(s)", style="ToolbarBadge.TLabel")
        self.stat_total_label.pack(side="left")
        tip(self.stat_total_label, "Nombre total de fichiers visibles")

        self.stat_selection_label = ttk.Label(self.toolbar_stats_frame, text="Selection 0", style="ToolbarBadge.TLabel")
        self.stat_selection_label.pack(side="left", padx=(12, 0))
        tip(self.stat_selection_label, "Elements selectionnes")

        self.stat_filter_label = ttk.Label(self.toolbar_stats_frame, text="Filtre Aucun", style="ToolbarBadge.TLabel")
        self.stat_filter_label.pack(side="left", padx=(12, 0))
        tip(self.stat_filter_label, "Etat du filtre et options actives")

        self._update_toolbar_note()
        self._update_toolbar_stats()

    def _update_toolbar_note(self):
        if not hasattr(self, "toolbar_note"):
            return
        suffix_parts: list[str] = []
        if getattr(self, "ai_filter_var", None) and self.ai_filter_var.get():
            suffix_parts.append("filtre IA actif")
        if getattr(self, "tracked_only_var", None) and self.tracked_only_var.get():
            suffix_parts.append("mode GitHub exact")
        vendor_mode = _normalize_vendor_mode(self.vendor_mode_var.get() if hasattr(self, "vendor_mode_var") else "none")
        if vendor_mode == "symfony":
            suffix_parts.append("vendor symfony")
        elif vendor_mode == "all":
            suffix_parts.append("vendor complet")
        suffix = f" - {' | '.join(suffix_parts)}" if suffix_parts else ""
        prefix = "CodeViewer"
        if self.project_dir:
            base = f"{prefix} - Dossier actif : {self.project_dir.name}"
        else:
            base = f"{prefix} - Ouvrez un dossier pour analyser ses sources."
        self.toolbar_note.config(text=base + suffix)

    def _update_toolbar_stats(self):
        if not hasattr(self, "stat_total_label"):
            return
        total = self._last_total
        if hasattr(self, "tree"):
            try:
                total = len(self.tree.get_children())
            except Exception:
                total = self._last_total
        selection = 0
        if hasattr(self, "tree"):
            selection = len(self.tree.selection())
        self.stat_total_label.config(text=f"{total} fichier(s)")
        self.stat_selection_label.config(text=f"Selection {selection}")
        filter_text = self.filter_var.get().strip()
        if filter_text:
            filter_label = f'Filtre "{_shorten(filter_text, 32)}"'
        else:
            filter_label = "Filtre Aucun"
        tags: list[str] = []
        if self.ai_filter_var.get():
            tags.append("IA")
        if self.sort_by_dir_var.get():
            tags.append("tri dossiers")
        if self.tracked_only_var.get():
            tags.append("git-tracked")
        if self.respect_gitignore_var.get():
            tags.append(".gitignore")
        vendor_mode = _normalize_vendor_mode(self.vendor_mode_var.get() if hasattr(self, "vendor_mode_var") else "none")
        vendor_tag = {
            "none": "vendor exclu",
            "symfony": "vendor symfony",
            "all": "vendor complet",
        }.get(vendor_mode, "vendor exclu")
        tags.append(vendor_tag)
        if self.safe_export_exclude_sensitive_var.get():
            tags.append("export sûr")
        if tags:
            filter_label += " [" + ", ".join(tags) + "]"
        self.stat_filter_label.config(text=filter_label)

    def _load_gitignore(self, root: Path | None) -> None:
        self.gitignore_rules = []
        self.gitattributes_rules = []
        if not root:
            return

        # .gitignore
        gitignore = root / ".gitignore"
        if gitignore.exists():
            try:
                raw_lines = gitignore.read_text(encoding="utf-8", errors="ignore").splitlines()
            except Exception:
                raw_lines = []
            rules: list[tuple[str, bool]] = []
            for raw in raw_lines:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                negate = line.startswith("!")
                if negate:
                    line = line[1:].strip()
                if not line:
                    continue
                rules.append((line, negate))
            self.gitignore_rules = rules

        # .gitattributes
        try:
            self.gitattributes_rules = _load_gitattributes(root)
        except Exception:
            self.gitattributes_rules = []

    @staticmethod
    def _gitignore_matches(pattern: str, rel_path: str, is_dir: bool) -> bool:
        dir_only = pattern.endswith("/")
        if dir_only:
            pattern = pattern.rstrip("/")
        anchored = pattern.startswith("/")
        if anchored:
            pattern_cmp = pattern.lstrip("/")
        else:
            pattern_cmp = pattern
        candidates = [rel_path]
        if not anchored and "/" in rel_path:
            parts = rel_path.split("/")
            candidates.extend("/".join(parts[i:]) for i in range(1, len(parts)))
        if dir_only:
            if any(c == pattern_cmp or c.startswith(pattern_cmp + "/") for c in candidates):
                return True
            return False
        for c in candidates:
            if fnmatch.fnmatch(c, pattern_cmp):
                return True
        if not anchored:
            name = rel_path.rsplit("/", 1)[-1]
            if fnmatch.fnmatch(name, pattern_cmp):
                return True
        return False

    def _is_gitignored(self, path: Path) -> bool:
        if not self.gitignore_rules or not self.project_dir:
            return False
        try:
            rel = path.relative_to(self.project_dir).as_posix()
        except Exception:
            rel = path.as_posix()
        ignored = False
        is_dir = path.is_dir()
        for pattern, negate in self.gitignore_rules:
            if self._gitignore_matches(pattern, rel, is_dir):
                ignored = not negate
        return ignored

    def _gitattributes_is_excluded(self, rel_path: str) -> bool:
        # Exclut si marqué généré/vendored/documentation/export-ignore
        for pat, flags in getattr(self, "gitattributes_rules", []):
            if self._gitignore_matches(pat, rel_path, False):
                if any(f in flags for f in ("linguist-generated", "linguist-vendored", "linguist-documentation", "export-ignore")):
                    return True
        return False

    def _toggle_ai_filter(self):
        state = self.ai_filter_var.get()
        self.cfg.ai_filter = state
        self._update_toolbar_note()
        if self.project_dir:
            self._scan_async(self.project_dir)
        else:
            self._apply()
        self.lbl_msg.config(text="Filtre IA actif." if state else "Filtre IA desactive.")
        self._update_toolbar_stats()

    def _toggle_tracked_mode(self):
        self.cfg.tracked_only = self.tracked_only_var.get()
        if self.project_dir:
            self._scan_async(self.project_dir)
        else:
            self._apply()
        self._update_toolbar_note()
        self._update_toolbar_stats()

    def _toggle_vendor_mode(self):
        val = self.vendor_mode_var.get()
        if val not in {"none", "symfony", "all"}:
            self.vendor_mode_var.set("none")
            val = "none"
        self.cfg.vendor_mode = _normalize_vendor_mode(val)
        self.cfg.include_vendor = self.cfg.vendor_mode != "none"
        if self.project_dir:
            self._scan_async(self.project_dir)
        else:
            self._apply()
        self._update_toolbar_note()
        self._update_toolbar_stats()

    def _toggle_safe_export_mode(self):
        self.cfg.safe_export_exclude_sensitive = self.safe_export_exclude_sensitive_var.get()
        self._update_toolbar_stats()

    def _clear_filter(self):
        self.filter_var.set("")
        self._cancel_filter_pending()
        if hasattr(self, "entry_filter"):
            self.entry_filter.focus_set()
        self._apply()
        self._update_toolbar_stats()

    def _on_filter_keystroke(self, *_):
        self._schedule_filter_update()

    def _schedule_filter_update(self):
        self._cancel_filter_pending()
        try:
            self._filter_after_id = self.after(250, self._apply)
        except Exception:
            self._apply()

    def _cancel_filter_pending(self):
        if self._filter_after_id:
            try:
                self.after_cancel(self._filter_after_id)
            except Exception:
                pass
            self._filter_after_id = None

    def _cancel_ops(self):
        if not hasattr(self, "btn_cancel") or self.btn_cancel["state"] == "disabled":
            return
        if not self.cancel_event.is_set():
            self.cancel_event.set()
            self.btn_cancel.config(state="disabled")
            self.lbl_msg.config(text="Annulation demandee...")
            self.progress.stop()
            self.progress.configure(mode="determinate")
            LOGGER.info("Annulation demandee par l'utilisateur")

    def _confirm_sensitive(self, files: Sequence[Path]) -> bool:
        if not files:
            return True
        try:
            rels = [
                (fp.relative_to(self.project_dir).as_posix() if self.project_dir else fp.as_posix())
                for fp in files
            ]
        except Exception:
            rels = [fp.as_posix() for fp in files]
        preview = "\n".join(f"- {path}" for path in rels[:5])
        if len(rels) > 5:
            preview += "\n..."
        return messagebox.askyesno(
            "Fichiers sensibles",
            "Certains fichiers semblent contenir des secrets:\n"
            f"{preview}\n\nPoursuivre tout de meme ?",
        )

    def _paned(self):
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True)
        self._toolbar(container)
        paned = ttk.PanedWindow(container, orient="horizontal")
        paned.pack(fill="both", expand=True)
        self.paned = paned

        left = ttk.Frame(paned, style="Card.TFrame", padding=(16, 16, 16, 16))
        right = ttk.Frame(paned, style="Card.TFrame", padding=(16, 16, 16, 16))
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        cols = ("name", "size", "rel")
        headings = {"name": "Nom", "size": "Taille", "rel": "Chemin relatif"}
        anchors = {"name": "w", "size": "e", "rel": "w"}
        widths = self.cfg.col_widths or {"name": 320, "size": 120, "rel": 540}

        left.grid_columnconfigure(0, weight=1)
        tree_header = ttk.Frame(left, style="Card.TFrame")
        tree_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Label(tree_header, text="Fichiers du projet", style="ToolbarHeading.TLabel").pack(side="left")

        self.tree = ttk.Treeview(left, columns=cols, show="headings", selectmode="extended", style="Neon.Treeview")
        for col in cols:
            self.tree.heading(col, text=headings[col], command=lambda c=col: self._sort(c))
            self.tree.column(col, width=widths.get(col, 200), anchor=anchors[col], stretch=(col != "size"))

        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(left, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=vsb.set, xscroll=hsb.set)
        self.tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")
        hsb.grid(row=2, column=0, sticky="ew")
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        self.tree.bind("<Double-1>", self._open_file)
        self.tree.bind("<Button-3>", self._popup)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", self._on_tree_leave)

        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Ouvrir", command=lambda: self._ctx("open"))
        self.menu.add_command(label="Afficher dans l'explorateur", command=lambda: self._ctx("reveal"))
        self.menu.add_command(label="Copier le chemin", command=lambda: self._ctx("copy"))
        self.menu.add_separator()
        self.menu.add_command(label="Basculer selection", command=lambda: self._ctx("toggle"))

        preview = ttk.Frame(right, style="Card.TFrame")
        preview.pack(fill="both", expand=True)
        preview_header = ttk.Frame(preview, style="PreviewHeader.TFrame", padding=(0, 0, 0, 12))
        preview_header.pack(fill="x")
        preview_header.columnconfigure(1, weight=1)
        self.preview_header = preview_header
        self.preview_title = ttk.Label(preview_header, text="Apercu", style="PreviewHeading.TLabel")
        self.preview_title.grid(row=0, column=0, sticky="w")
        wrap_chk = ttk.Checkbutton(preview_header, text="Retour ligne", variable=self.wrap_var, command=self._toggle_wrap)
        wrap_chk.grid(row=0, column=1, sticky="w", padx=(16, 0))
        wrap_chk.configure(style="PreviewCheck.TCheckbutton")
        btns = ttk.Frame(preview_header, style="PreviewHeader.TFrame")
        btns.grid(row=0, column=2, sticky="e")
        self.btn_copy_preview = ttk.Button(btns, text="Copier l'apercu", command=self._copy_preview, state="disabled", style="Accent.TButton")
        self.btn_copy_preview.grid(row=0, column=0, padx=(0, 6))
        self.btn_open_preview = ttk.Button(btns, text="Ouvrir", command=self._open_preview_file, state="disabled")
        self.btn_open_preview.grid(row=0, column=1, padx=(0, 6))
        self.btn_reveal_preview = ttk.Button(btns, text="Reveler", command=self._reveal_preview_file, state="disabled")
        self.btn_reveal_preview.grid(row=0, column=2)
        self.lbl_preview = ttk.Label(preview_header, text="Aucun fichier selectionne", style="PreviewPath.TLabel")
        self.lbl_preview.grid(row=1, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.preview_meta = ttk.Frame(preview_header, style="PreviewHeader.TFrame")
        self.preview_meta.grid(row=2, column=0, columnspan=3, sticky="w", pady=(10, 0))
        self.preview_size_badge = ttk.Label(self.preview_meta, text="Taille --", style="PreviewBadge.TLabel")
        self.preview_size_badge.pack(side="left")
        self.preview_mtime_badge = ttk.Label(self.preview_meta, text="Modifie --", style="PreviewBadge.TLabel")
        self.preview_mtime_badge.pack(side="left", padx=(12, 0))

        text_frame = ttk.Frame(preview, style="Card.TFrame")
        text_frame.pack(fill="both", expand=True)
        self.txt = tk.Text(
            text_frame,
            wrap="word" if self.wrap_var.get() else "none",
            font=self.mono,
            undo=False,
            height=20,
        )
        txt_vsb = ttk.Scrollbar(text_frame, orient="vertical", command=self.txt.yview)
        txt_hsb = ttk.Scrollbar(text_frame, orient="horizontal", command=self.txt.xview)
        self.txt.configure(yscrollcommand=txt_vsb.set, xscrollcommand=txt_hsb.set)
        self.txt.grid(row=0, column=0, sticky="nsew")
        txt_vsb.grid(row=0, column=1, sticky="ns")
        txt_hsb.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)
        self.txt.configure(state="disabled", padx=16, pady=14, spacing1=2, spacing3=4)

        try:
            self.paned.sashpos(0, self.cfg.pane_pos)
        except Exception:
            pass

        self._toggle_wrap()
        self._update_preview_meta(None, None)

    def _choose(self):
        start = (
            str(self.project_dir)
            if self.project_dir and self.project_dir.exists()
            else (self.cfg.recent_dirs[0] if self.cfg.recent_dirs else str(Path.home()))
        )
        old = os.getcwd()
        try:
            os.chdir(start)
        except Exception:
            pass
        try:
            selected = filedialog.askdirectory(parent=self, initialdir=start, title="Choisir le dossier projet")
        finally:
            try:
                os.chdir(old)
            except Exception:
                pass
        if selected:
            self._open(Path(selected))

    def _open(self, path: Path):
        if not path.exists():
            messagebox.showerror("Erreur", "Le dossier n'existe plus.")
            return
        self.project_dir = path.resolve()
        parts = [p for p in self.cfg.recent_dirs if Path(p).exists()]
        str_proj = str(self.project_dir)
        if str_proj in parts:
            parts.remove(str_proj)
        parts.insert(0, str_proj)
        self.cfg.recent_dirs = parts[:MAX_RECENTS]
        self.combo_recent["values"] = self.cfg.recent_dirs
        try:
            self.combo_recent.current(0)
        except Exception:
            pass
        self.title(f"{APP_NAME} - {self.project_dir.name}")
        self._load_gitignore(self.project_dir)
        self._update_toolbar_note()
        self.preview_path = None
        self._show_preview()
        self._update_toolbar_stats()
        self._scan_async(self.project_dir)

    def _scan_async(self, root: Path):
        if not root:
            return
        if self._scan_thread and self._scan_thread.is_alive():
            return

        ai_mode = bool(self.ai_filter_var.get()) if hasattr(self, "ai_filter_var") else False
        tracked_only = bool(self.tracked_only_var.get()) if hasattr(self, "tracked_only_var") else False
        vendor_mode = _normalize_vendor_mode(self.vendor_mode_var.get() if hasattr(self, "vendor_mode_var") else "none")
        if hasattr(self, "vendor_mode_var") and self.vendor_mode_var.get() != vendor_mode:
            self.vendor_mode_var.set(vendor_mode)

        self.cancel_event.clear()
        self.btn_cancel.config(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self.lbl_msg.config(text="Scan en cours...")
        self.tree.delete(*self.tree.get_children())
        self._clear_hover()
        self._last_total = 0
        self._update_toolbar_stats()

        try:
            file_fg = self.colors.get("file_fg", self.colors.get("fg", ""))
            odd_bg = self.colors.get("row_odd", self.colors.get("bg_alt", ""))
            even_bg = self.colors.get("row_even", self.colors.get("bg_alt", ""))
        except Exception:
            file_fg = ""
            odd_bg = even_bg = ""
        self.tree.tag_configure("odd", background=odd_bg, foreground=file_fg)
        self.tree.tag_configure("even", background=even_bg, foreground=file_fg)
        self._size_cache.clear()

        def worker():
            try:
                if self.cancel_event.is_set():
                    self.queue.put(("cancelled", "scan"))
                    return
                use_git_base = tracked_only or ai_mode
                tracked = _git_tracked(root) if use_git_base else set()
                if tracked:
                    files = []
                    for p in tracked:
                        if not p.exists() or not p.is_file():
                            continue
                        if not _is_allowed_file(p):
                            continue
                        try:
                            rel_parts = p.relative_to(root).parts
                        except Exception:
                            rel_parts = p.parts
                        if not _vendor_allows_file(rel_parts, vendor_mode):
                            continue
                        files.append(p)
                    def _rel_key(path: Path) -> str:
                        try:
                            return path.relative_to(root).as_posix().casefold()
                        except Exception:
                            return str(path).casefold()
                    files.sort(key=_rel_key)
                else:
                    files = _discover(root, vendor_mode)

                attrs = _load_gitattributes(root)
                if self.cancel_event.is_set():
                    self.queue.put(("cancelled", "scan"))
                    return
                self.queue.put(("scan_done", root, vendor_mode, ai_mode, tracked_only, files, tracked, attrs))
            except Exception as exc:
                LOGGER.exception("Echec scan", exc_info=exc)
                self.queue.put(("error", str(exc)))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()

    def _refresh(self):
        if not self.project_dir:
            return
        self._scan_async(self.project_dir)

    def _resort(self):
        self._apply()

    def _sort(self, col: str):
        if col not in {"name", "size", "rel"}:
            return
        if self.sort_col == col:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_col = col
            self.sort_reverse = False
        self._apply()

    def _update_headings(self):
        titles = {"name": "Nom", "size": "Taille", "rel": "Chemin relatif"}
        for col in ("name", "size", "rel"):
            title = titles[col]
            if col == self.sort_col:
                arrow = " v" if self.sort_reverse else " ^"
            else:
                arrow = ""
            self.tree.heading(col, text=title + arrow, command=lambda c=col: self._sort(c))

    def _apply(self, *_e):
        self._filter_after_id = None
        self._update_headings()
        if not self.project_dir:
            self.tree.delete(*self.tree.get_children())
            self._size_cache.clear()
            self._last_total = 0
            self._counter()
            return
        raw_pattern = self.filter_var.get()
        pattern = raw_pattern.strip().lower()
        normalized_pattern = pattern.replace("�", "").replace("…", "...")
        if (
            pattern in _STALE_FILTER_VALUES
            or (normalized_pattern.startswith("filtrer") and ("chemin" in normalized_pattern or normalized_pattern in {"filtrer", "filtrer..."}))
        ):
            pattern = ""
        active_exts = {ext for ext, var in self.ext_vars.items() if var.get()}
        if not active_exts:
            active_exts = set(ALLOWED_EXT)
        ai_mode = self.ai_filter_var.get()
        respect_gitignore = self.respect_gitignore_var.get()
        self.cfg.respect_gitignore = respect_gitignore
        ai_skipped = 0
        ai_reason_counts: Counter[str] = Counter()
        items: list[tuple[Path, Path, str, int]] = []
        for fp in self.files_all:
            try:
                suffix = _ext_key(fp)
            except Exception:
                suffix = fp.suffix.lower()
            if suffix not in active_exts:
                continue
            try:
                rel = fp.relative_to(self.project_dir)
                rel_posix = rel.as_posix()
            except Exception:
                rel = fp.name
                rel_posix = str(fp)
            if pattern and pattern not in rel_posix.lower():
                continue
            try:
                size_bytes = fp.stat().st_size
            except Exception:
                size_bytes = None
            if (ai_mode or respect_gitignore) and self._is_gitignored(fp):
                if ai_mode:
                    ai_skipped += 1
                    ai_reason_counts["gitignore"] += 1
                continue
            if ai_mode:
                # Exclusion .gitignore déjà couverte par _is_gitignored ; gitattributes et taille ici.
                if self.gitattributes_rules and self._gitattributes_is_excluded(rel_posix):
                    ai_skipped += 1
                    ai_reason_counts["gitattributes"] += 1
                    continue
                try:
                    if size_bytes is not None and size_bytes > AI_MAX_BYTES:
                        ai_skipped += 1
                        ai_reason_counts["size"] += 1
                        continue
                except Exception:
                    pass
                reason = _ai_filter_reason(fp, self.project_dir)
                if reason is not None:
                    ai_skipped += 1
                    ai_reason_counts[reason] += 1
                    continue
            size_value = size_bytes if size_bytes is not None else 0
            items.append((fp, rel, rel_posix, size_value))

        if self.sort_by_dir_var.get():
            items.sort(key=lambda it: (str(Path(it[2]).parent).lower(), it[0].name.lower()))
        else:
            if self.sort_col == "size":
                items.sort(key=lambda it: it[3])
            elif self.sort_col == "rel":
                items.sort(key=lambda it: it[2].lower())
            else:
                items.sort(key=lambda it: it[0].name.lower())
        if self.sort_reverse:
            items.reverse()

        selection = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        self._clear_hover()
        self._size_cache = {}
        for idx, (fp, _rel, rel_posix, size_bytes) in enumerate(items):
            iid = str(fp)
            self._size_cache[iid] = size_bytes
            display_size = _human_bytes(size_bytes)
            tags = ("odd",) if idx % 2 == 0 else ("even",)
            self.tree.insert("", "end", iid=iid, values=(fp.name, display_size, rel_posix), tags=tags)
        if selection:
            keep = [iid for iid in selection if iid in self.tree.get_children("")]
            if keep:
                self.tree.selection_set(keep)
        self._last_total = len(items)
        self._counter()
        self._show_preview()
        if ai_mode:
            reasons_text = ""
            if ai_reason_counts:
                top_reasons = ai_reason_counts.most_common(3)
                formatted = ", ".join(
                    f"{AI_REASON_LABELS.get(reason, reason)} ({count})" for reason, count in top_reasons
                )
                reasons_text = f" Motifs : {formatted}."
            if ai_skipped:
                self.lbl_msg.config(
                    text=f"{self._last_total} fichier(s) affiches. Filtre IA actif : {ai_skipped} ignores.{reasons_text}"
                )
            else:
                self.lbl_msg.config(
                    text=f"{self._last_total} fichier(s) affiches. Filtre IA actif.{reasons_text}"
                )
        else:
            self.lbl_msg.config(text=f"{self._last_total} fichier(s) affiches.")
        self._update_toolbar_stats()

    def _update_action_states(self):
        has_selection = bool(self.tree.selection())
        state = "normal" if has_selection else "disabled"
        self.btn_copy.config(state=state)
        self.btn_export.config(state=state)

    def _clear_hover(self):
        if not hasattr(self, "tree"):
            self._hover_iid = None
            return
        if self._hover_iid and self.tree.exists(self._hover_iid):
            tags = tuple(t for t in self.tree.item(self._hover_iid, "tags") if t != "hover")
            self.tree.item(self._hover_iid, tags=tags)
        self._hover_iid = None

    def _set_hover(self, iid: str | None):
        if not hasattr(self, "tree"):
            self._hover_iid = None
            return
        if iid == self._hover_iid:
            return
        if self._hover_iid and self.tree.exists(self._hover_iid):
            tags = tuple(t for t in self.tree.item(self._hover_iid, "tags") if t != "hover")
            self.tree.item(self._hover_iid, tags=tags)
        self._hover_iid = iid if iid and self.tree.exists(iid) else None
        if self._hover_iid:
            tags = tuple(t for t in self.tree.item(self._hover_iid, "tags") if t != "hover")
            self.tree.item(self._hover_iid, tags=tags + ("hover",))

    def _on_tree_motion(self, event: tk.Event):
        row = self.tree.identify_row(event.y)
        if not row:
            if self._hover_iid:
                self._clear_hover()
            return
        self._set_hover(row)

    def _on_tree_leave(self, _event: tk.Event):
        self._clear_hover()

    def _on_tree_select(self, _event=None):
        self._counter()
        self._show_preview()

    def _show_preview(self):
        sel = self.tree.selection()
        if not sel:
            self.preview_path = None
            self.lbl_preview.config(text="Aucun fichier selectionne")
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", "Selectionnez un fichier pour afficher l'apercu.")
            self.txt.configure(state="disabled")
            self._update_preview_buttons()
            self._update_preview_meta(None, None)
            return
        path = Path(sel[0])
        self.preview_path = path
        try:
            rel = path.relative_to(self.project_dir) if self.project_dir else path.name
        except Exception:
            rel = path.name
        self.lbl_preview.config(text=str(rel))
        size_bytes = self._size_cache.get(str(path))
        mtime = None
        try:
            stat = path.stat()
            mtime = stat.st_mtime
            if size_bytes is None:
                size_bytes = stat.st_size
        except Exception:
            if size_bytes is None:
                size_bytes = 0
        try:
            content = _read_preview(path)
        except Exception as exc:
            content = f"Erreur de lecture: {exc}"
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("1.0", content)
        self.txt.configure(state="disabled")
        self._update_preview_buttons()
        self._update_preview_meta(size_bytes, mtime)

    def _update_preview_buttons(self):
        state = "normal" if self.preview_path and self.preview_path.exists() else "disabled"
        self.btn_copy_preview.config(state=state)
        self.btn_open_preview.config(state=state)
        self.btn_reveal_preview.config(state=state)

    def _update_preview_meta(self, size_bytes: int | None, mtime: float | None):
        if not hasattr(self, "preview_size_badge"):
            return
        if size_bytes is None:
            self.preview_size_badge.config(text="Taille --")
        else:
            self.preview_size_badge.config(text=f"Taille {_human_bytes(size_bytes)}")
        if mtime is None:
            self.preview_mtime_badge.config(text="Modifie --")
        else:
            try:
                dt = datetime.fromtimestamp(mtime)
                self.preview_mtime_badge.config(text=f"Modifie {dt.strftime('%d/%m/%Y %H:%M')}")
            except Exception:
                self.preview_mtime_badge.config(text="Modifie --")

    def _copy_preview(self):
        if not self.preview_path:
            return
        content = self.txt.get("1.0", "end-1c")
        lang = _lang_for(self.preview_path)
        snippet = f"```{lang}\n{content}\n```\n"
        self.clipboard_clear()
        self.clipboard_append(snippet)
        self.lbl_msg.config(text="Apercu copie.")

    def _open_preview_file(self):
        if self.preview_path:
            self._open_file_fp(self.preview_path)

    def _reveal_preview_file(self):
        if self.preview_path:
            self._reveal(self.preview_path)

    def _open_selected(self):
        sel = self.tree.selection()
        if sel:
            self._open_file_fp(Path(sel[0]))

    def _reveal_selected(self):
        sel = self.tree.selection()
        if sel:
            self._reveal(Path(sel[0]))

    def _copy_path_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        path = Path(sel[0])
        self.clipboard_clear()
        self.clipboard_append(str(path))
        self.lbl_msg.config(text="Chemin copie.")

    def _popup(self, event: tk.Event):
        row = self.tree.identify_row(event.y)
        if row:
            self.tree.selection_set(row)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    def _ctx(self, action: str):
        if action == "open":
            self._open_selected()
        elif action == "reveal":
            self._reveal_selected()
        elif action == "copy":
            self._copy_path_selected()
        elif action == "toggle":
            self._invert()

    def _open_file(self, _event: tk.Event):
        self._open_selected()

    @staticmethod
    def _open_file_fp(fp: Path):
        try:
            target = str(fp.resolve())
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            messagebox.showerror("Erreur", "Impossible d'ouvrir le fichier.")

    @staticmethod
    def _reveal(fp: Path):
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", f"/select,{fp.resolve()}"])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(fp)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(["xdg-open", str(fp.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            messagebox.showerror("Erreur", "Impossible d'afficher le fichier.")

    def _sel_all(self):
        self.tree.selection_set(self.tree.get_children())
        self._counter()

    def _clear(self):
        self.tree.selection_remove(self.tree.selection())
        self._counter()

    def _invert(self):
        current = set(self.tree.selection())
        all_items = set(self.tree.get_children())
        new_sel = all_items - current
        self.tree.selection_set(list(new_sel))
        self._counter()

    def _toggle_wrap(self, *_e):
        if not hasattr(self, "txt"):
            return
        wrap = "word" if self.wrap_var.get() else "none"
        self.txt.configure(wrap=wrap)

    def _font_step(self, delta: int):
        new_size = max(6, min(48, self.font_size.get() + delta))
        self.font_size.set(new_size)
        self.mono.configure(size=new_size)
        self._refresh_fonts()
        self._apply_theme()
        if hasattr(self, "txt"):
            self.txt.configure(font=self.mono)

    def _font_reset(self):
        self.font_size.set(12)
        self.mono.configure(size=12)
        self._refresh_fonts()
        self._apply_theme()
        if hasattr(self, "txt"):
            self.txt.configure(font=self.mono)

    def _toggle_theme(self, toggle: bool = False):
        if toggle:
            self.theme_var.set(not self.theme_var.get())
        self._apply_theme()
        self._apply()

    def _open_langages_dialog(self):
        dlg = tk.Toplevel(self)
        dlg.title("Extensions")
        dlg.transient(self)
        dlg.grab_set()
        frame = ttk.Frame(dlg, padding=12)
        frame.pack(fill="both", expand=True)
        cols = 4
        for idx, ext in enumerate(sorted(self.ext_vars)):
            var = self.ext_vars[ext]
            chk = ttk.Checkbutton(frame, text=ext, variable=var, command=lambda e=ext: self._on_extension_change(e))
            chk.grid(row=idx // cols, column=idx % cols, sticky="w", padx=4, pady=2)
        btns = ttk.Frame(frame)
        row_btns = (len(self.ext_vars) // cols) + 1
        btns.grid(row=row_btns, column=0, columnspan=cols, pady=(12, 0), sticky="e")
        ttk.Button(btns, text="Tout", command=lambda: self._set_all_extensions(True)).pack(side="left", padx=4)
        ttk.Button(btns, text="Aucun", command=lambda: self._set_all_extensions(False)).pack(side="left", padx=4)
        ttk.Button(btns, text="Fermer", command=dlg.destroy).pack(side="left", padx=4)
        dlg.wait_window(dlg)

    def _set_all_extensions(self, value: bool):
        for var in self.ext_vars.values():
            var.set(value)
        if not value:
            first = next(iter(self.ext_vars.values()))
            first.set(True)
        self._apply()

    def _on_extension_change(self, ext: str | None = None):
        if not any(var.get() for var in self.ext_vars.values()):
            messagebox.showwarning("Extensions", "Au moins une extension doit rester active.")
            if ext and ext in self.ext_vars:
                self.ext_vars[ext].set(True)
            return
        self._apply()

    def _reset_layout(self):
        self.filter_var.set("")
        for var in self.ext_vars.values():
            var.set(True)
        self.sort_col = "name"
        self.sort_reverse = False
        self.sort_by_dir_var.set(False)
        rescan_needed = bool(self.project_dir)
        ai_active = self.ai_filter_var.get()
        self.ai_filter_var.set(False)
        self.tracked_only_var.set(False)
        self.respect_gitignore_var.set(False)
        self.vendor_mode_var.set("none")
        self.safe_export_exclude_sensitive_var.set(False)
        self.cfg.tracked_only = False
        self.cfg.respect_gitignore = False
        self.cfg.vendor_mode = "none"
        self.cfg.include_vendor = False
        self.cfg.safe_export_exclude_sensitive = False
        self.wrap_var.set(self.cfg.preview_wrap)
        self._toggle_wrap()
        self._font_reset()
        try:
            if hasattr(self, "paned"):
                self.paned.sashpos(0, self.cfg.pane_pos)
        except Exception:
            pass
        self.theme_var.set(True)
        self._toggle_theme()
        if ai_active:
            self._toggle_ai_filter()
        elif rescan_needed:
            self._scan_async(self.project_dir)
        else:
            self._apply()
        self._toggle_safe_export_mode()
        self._update_toolbar_stats()

    def _open_terminal_codex(self):
        cmd = (self.cfg.codex_cmd or CODEX_CMD).strip()
        if not cmd:
            messagebox.showerror("Terminal", "Commande Codex CLI introuvable. Configurez-la dans les parametres ou via la variable CODEX_CMD.")
            return

        target_dir = self.project_dir if self.project_dir else Path.home()
        target_dir = target_dir if isinstance(target_dir, Path) else Path(target_dir)
        if not target_dir.exists():
            target_dir = Path.home()
        cwd = str(target_dir)

        try:
            if sys.platform.startswith("win"):
                creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
                subprocess.Popen(["cmd.exe", "/K", cmd], cwd=cwd, creationflags=creationflags)
                return

            command_line = f"cd {shlex.quote(cwd)} && {cmd}"

            if sys.platform == "darwin":
                escaped_command = command_line.replace("\\", "\\\\").replace('"', '\\"')
                applescript = (
                    'tell application "Terminal"\n'
                    '    activate\n'
                    f'    do script "{escaped_command}"\n'
                    'end tell\n'
                )
                subprocess.Popen(["osascript", "-e", applescript])
                return

            term_env = os.environ.get("TERMINAL")
            if term_env:
                term_parts = shlex.split(term_env)
                subprocess.Popen([*term_parts, "-e", "bash", "-lc", command_line], cwd=cwd)
                return

            term_candidates = [
                ("x-terminal-emulator", ["-e", "bash", "-lc", command_line]),
                ("gnome-terminal", ["--", "bash", "-lc", command_line]),
                ("konsole", ["-e", "bash", "-lc", command_line]),
                ("xfce4-terminal", ["-e", "bash", "-lc", command_line]),
                ("kitty", ["-e", "bash", "-lc", command_line]),
                ("alacritty", ["-e", "bash", "-lc", command_line]),
                ("tilix", ["-e", "bash", "-lc", command_line]),
                ("terminator", ["-e", "bash", "-lc", command_line]),
                ("wezterm", ["start", "bash", "-lc", command_line]),
                ("xterm", ["-e", "bash", "-lc", command_line]),
            ]
            for term, args in term_candidates:
                path = shutil.which(term)
                if path:
                    subprocess.Popen([path, *args], cwd=cwd)
                    return

            messagebox.showerror("Erreur", "Aucun terminal compatible detecte. Definissez $TERMINAL ou installez un emulateur prenant en charge l'option -e.")
        except FileNotFoundError:
            messagebox.showerror("Erreur", f"Commande introuvable: {cmd}")
        except Exception as exc:
            messagebox.showerror("Erreur", f"Impossible de lancer le terminal: {exc}")

    def _run_worker(self, target, *args):
        threading.Thread(target=target, args=(*args, self.queue, self.cancel_event), daemon=True).start()

    def _copy_sel(self):
        if not self.project_dir:
            return
        sel = [Path(iid) for iid in self.tree.selection()]
        if not sel:
            messagebox.showinfo("Copie", "Selectionnez au moins un fichier.")
            return
        sensitive = [fp for fp in sel if _is_sensitive_file(fp)]
        note = ""
        if self.safe_export_exclude_sensitive_var.get():
            if sensitive:
                sel = [fp for fp in sel if fp not in sensitive]
                if not sel:
                    messagebox.showinfo("Copie", "Tous les fichiers selectionnes sont sensibles et ont ete exclus.")
                    return
                note = " (sensibles exclus)"
        elif sensitive and not self._confirm_sensitive(sensitive):
            self.lbl_msg.config(text="Copie annulee (fichiers sensibles).")
            return
        self.cancel_event.clear()
        self.btn_cancel.config(state="normal")
        self.progress.configure(mode="determinate", maximum=len(sel), value=0)
        self.lbl_msg.config(text=f"Copie en cours...{note}")
        self.btn_copy.config(state="disabled")
        self.btn_export.config(state="disabled")
        self._run_worker(_copy_structured, self.project_dir, sel)

    def _export_sel(self):
        if not self.project_dir:
            return
        sel = [Path(iid) for iid in self.tree.selection()]
        if not sel:
            messagebox.showinfo("Export", "Selectionnez au moins un fichier.")
            return
        out = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile=DEFAULT_OUT)
        if not out:
            return
        sensitive = [fp for fp in sel if _is_sensitive_file(fp)]
        note = ""
        if self.safe_export_exclude_sensitive_var.get():
            if sensitive:
                sel = [fp for fp in sel if fp not in sensitive]
                if not sel:
                    messagebox.showinfo("Export", "Tous les fichiers selectionnes sont sensibles et ont ete exclus.")
                    return
                note = " (sensibles exclus)"
        elif sensitive and not self._confirm_sensitive(sensitive):
            self.lbl_msg.config(text="Export annule (fichiers sensibles).")
            return
        out_path = Path(out)
        self.cancel_event.clear()
        self.btn_cancel.config(state="normal")
        self.progress.configure(mode="determinate", maximum=len(sel), value=0)
        self.lbl_msg.config(text=f"Export en cours...{note}")
        self.btn_copy.config(state="disabled")
        self.btn_export.config(state="disabled")
        self._run_worker(_export, self.project_dir, sel, out_path)

    def _extract_env(self):
        if not self.project_dir:
            messagebox.showinfo("Extraction ENV", "Ouvrez d'abord un dossier projet.")
            return
        self.cancel_event.clear()
        self.btn_cancel.config(state="normal")
        self.progress.configure(mode="indeterminate")
        self.progress.start(10)
        self.lbl_msg.config(text="Extraction des variables d'environnement...")
        files = self.files_all or []
        self._run_worker(_env_extract_worker, self.project_dir, files)

    def _process(self):
        try:
            while True:
                kind, *payload = self.queue.get_nowait()
                if kind == "scan_done":
                    root, vendor_mode_state, ai_mode_state, tracked_flag_state, files, git_tracked_set, gitattributes_rules = payload
                    if self.cancel_event.is_set():
                        self._scan_thread = None
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=0)
                        self.lbl_msg.config(text="Scan annule.")
                        self.btn_cancel.config(state="disabled")
                        self.cancel_event.clear()
                        continue
                    if self.project_dir and Path(root) != self.project_dir:
                        self._scan_thread = None
                        continue

                    current_vendor_state = _normalize_vendor_mode(self.vendor_mode_var.get()) if hasattr(self, "vendor_mode_var") else "none"
                    current_ai_mode = bool(self.ai_filter_var.get()) if hasattr(self, "ai_filter_var") else False
                    current_tracked_flag = bool(self.tracked_only_var.get()) if hasattr(self, "tracked_only_var") else False
                    if current_vendor_state != vendor_mode_state or current_ai_mode != ai_mode_state or current_tracked_flag != tracked_flag_state:
                        self._scan_thread = None
                        if self.project_dir:
                            self._scan_async(self.project_dir)
                        continue

                    self.files_all = files
                    self.git_tracked = set(git_tracked_set) if git_tracked_set else set()
                    self.gitattributes_rules = gitattributes_rules or []

                    self._scan_thread = None
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.lbl_msg.config(text=f"{len(files)} fichier(s) detectes.")
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    self._apply()
                elif kind == "done_env":
                    vars_to_paths, text = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()

                    total = len(vars_to_paths)
                    if total == 0:
                        messagebox.showinfo("Extraction ENV", "Aucune variable d'environnement detectee.")
                        self.lbl_msg.config(text="Aucune variable detectee.")
                        continue

                    out = filedialog.asksaveasfilename(
                        parent=self,
                        defaultextension=".example",
                        initialfile=".env.example",
                        title="Enregistrer le modele .env",
                    )
                    if out:
                        try:
                            Path(out).write_text(text, encoding="utf-8", newline="\n")
                            messagebox.showinfo("Succes", f"{total} variable(s) detectee(s).\nFichier ecrit : {out}")
                            self.lbl_msg.config(text="Modele .env ecrit.")
                        except Exception as exc:
                            LOGGER.exception("Echec ecriture .env", exc_info=exc)
                            messagebox.showerror("Erreur", f"Impossible d'ecrire le fichier : {exc}")
                            self.lbl_msg.config(text="Echec ecriture .env")
                    else:
                        self.clipboard_clear()
                        self.clipboard_append(text)
                        messagebox.showinfo(
                            "Copie",
                            f"{total} variable(s) detectee(s).\nModele copie dans le presse-papiers.",
                        )
                        self.lbl_msg.config(text="Modele .env copie.")
                elif kind == "progress":
                    i, total = payload
                    self.progress.configure(mode="determinate", maximum=total, value=i)
                elif kind == "clip_ready":
                    total, full_text = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.clipboard_clear()
                    self.clipboard_append(full_text)
                    self.lbl_msg.config(text=f"Copie terminee ({total} fichier(s)).")
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    messagebox.showinfo("Succes", "Texte copie dans le presse-papiers.")
                    self._counter()
                elif kind == "too_large_for_clipboard":
                    total, full_text = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    self.lbl_msg.config(text="Selection volumineuse.")
                    if messagebox.askyesno(
                        "Trop volumineux",
                        "La selection est trop volumineuse pour le presse-papiers.\nSouhaitez-vous exporter dans un fichier ?",
                    ):
                        out = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile=DEFAULT_OUT)
                        if out:
                            try:
                                Path(out).write_text(full_text, encoding="utf-8", newline="\n")
                                messagebox.showinfo("Succes", f"Selection exportee vers {out}")
                            except Exception as exc:
                                LOGGER.exception("Echec ecriture export volumineux", exc_info=exc)
                                messagebox.showerror("Erreur", f"Impossible d'ecrire le fichier : {exc}")
                    self._counter()
                elif kind == "done_export":
                    total, out_path = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.lbl_msg.config(text="Export termine.")
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    messagebox.showinfo("Succes", f"{total} fichier(s) exporte(s) dans\n{out_path}")
                    self._counter()
                elif kind == "cancelled":
                    op, = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    msg = {
                        "scan": "Scan annule.",
                        "copy": "Copie annulee.",
                        "export": "Export annule.",
                        "env": "Extraction ENV annulee.",
                    }.get(op, f"Operation {op} annulee.")
                    self.lbl_msg.config(text=msg)
                elif kind == "error":
                    msg, = payload
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.lbl_msg.config(text="Erreur")
                    self.btn_cancel.config(state="disabled")
                    self.cancel_event.clear()
                    messagebox.showerror("Erreur", msg)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._process)

    def _counter(self, *_e):
        total = len(self.tree.get_children())
        selected = self.tree.selection()
        nb = len(selected)
        size_bytes = sum(self._size_cache.get(iid, 0) for iid in selected)
        self.lbl_count.config(text=f"Selection {nb} / {total}")
        volume_text = _human_bytes(size_bytes) if nb else "0 B"
        self.lbl_size.config(text=f"Volume {volume_text}")
        self._update_action_states()
        self._update_preview_buttons()
        self._update_toolbar_stats()

    def _close(self):
        if hasattr(self, "paned"):
            try:
                self.cfg.pane_pos = self.paned.sashpos(0)
            except Exception:
                pass
        self.cfg.win_geom = self.geometry()
        self.cfg.col_widths = {col: self.tree.column(col)["width"] for col in self.tree["columns"]}
        self.cfg.ext_enabled = {ext: var.get() for ext, var in self.ext_vars.items()}
        self.cfg.filter_text = self.filter_var.get()
        self.cfg.theme = "dark" if self.theme_var.get() else "light"
        self.cfg.preview_wrap = self.wrap_var.get()
        self.cfg.preview_font_size = self.font_size.get()
        self.cfg.sort_col = self.sort_col
        self.cfg.sort_rev = self.sort_reverse
        self.cfg.sort_by_dir = self.sort_by_dir_var.get()
        self.cfg.ai_filter = self.ai_filter_var.get()
        self.cfg.tracked_only = self.tracked_only_var.get()
        self.cfg.respect_gitignore = self.respect_gitignore_var.get()
        vendor_mode = _normalize_vendor_mode(self.vendor_mode_var.get())
        self.cfg.vendor_mode = vendor_mode
        self.cfg.include_vendor = vendor_mode != "none"
        self.cfg.safe_export_exclude_sensitive = self.safe_export_exclude_sensitive_var.get()
        self.cfg.save()
        self.destroy()


if __name__ == "__main__":
    ConcatApp().mainloop()
