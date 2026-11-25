"""Per-topic crawl collections: where a crawled row goes, and which collections a request searches.

One Chroma collection per language (crawl_code_<lang>) and per topic (crawl_3ds, crawl_gamedev,
crawl_re, crawl_security, crawl_ffmpeg, crawl_mslearn, crawl_shell, crawl_webfw). A request only
searches the collections its attached files and its words point at; unmatched topics are never
searched. That keeps ffmpeg / Microsoft Learn pages (most of the doc crawl) out of a Python
rename, and Chroma loads a collection's index into RAM only once it is queried, so only the
topics a session touches are resident.

Shared by tools/crawl/build_topic_corpus.py (import side) and ChatRouter (query side).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PREFIX = "crawl_"
CODE_PREFIX = "crawl_code_"
# Doc pages with no topic (language manuals: docs.python.org, sqlite.org, go.dev, …). Searched on
# every request with the distance cutoff, like the legacy crawl_docs was. Not named crawl_docs:
# that legacy collection still exists in the main store.
MISC_DOCS = "crawl_misc"

# Crawler language label → collection slug. Languages not listed are dropped (user's focus areas,
# 2026-11-24: web, low-level, game engines, reverse engineering, shell; no Kotlin/Swift/Scala/…).
CODE_LANGUAGES = {
    "javascript": "javascript", "js": "javascript", "jsx": "javascript",
    "typescript": "typescript", "ts": "typescript", "tsx": "typescript",
    "php": "php",
    "python": "python",
    "rust": "rust",
    "go": "go",
    "ruby": "ruby",
    "java": "java",
    "csharp": "csharp", "c#": "csharp",
    "sql": "sql",
    "bash": "bash", "shell": "bash", "sh": "bash", "zsh": "bash", "dockerfile": "bash",
    "c": "c",
    "cpp": "cpp", "c++": "cpp",
    "make": "make", "makefile": "make", "cmake": "make",
    "lua": "lua",
    "gdscript": "gdscript",
    "hlsl": "shader", "glsl": "shader", "shader": "shader", "wgsl": "shader",
    "gdshader": "shader", "shaderlab": "shader",
    "asm": "asm", "assembly": "asm", "nasm": "asm",
    "vue": "javascript", "svelte": "javascript",
}
DROP_LANGUAGES = {
    "kotlin", "swift", "scala", "elixir", "r", "dart", "haskell", "perl", "fsharp", "f#",
    "html", "css", "scss", "less", "objective-c", "objc", "clojure", "erlang", "julia", "ocaml",
}

EXT_LANGUAGE = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".php": "php", ".rs": "rust", ".go": "go", ".rb": "ruby",
    ".java": "java", ".cs": "csharp", ".sql": "sql", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp", ".hh": "cpp",
    ".mk": "make", ".cmake": "make", ".lua": "lua", ".gd": "gdscript", ".hlsl": "hlsl", ".fx": "hlsl",
    ".glsl": "glsl", ".vert": "glsl", ".frag": "glsl", ".comp": "glsl", ".gdshader": "shader",
    ".shader": "shader", ".s": "asm", ".asm": "asm", ".vue": "vue", ".svelte": "svelte",
    ".ps1": "powershell", ".psm1": "powershell",
}

# --- topic markers in code (GitHub rows) -----------------------------------------------
_3DS_RE = re.compile(
    r"\b(libctru|citro3d|citro2d|3dsx|devkitARM|devkitPro|Luma3DS|Rosalina|makerom|ctru[-_]rs|"
    r"C3D_\w+|C2D_\w+|gfxInitDefault|aptMainLoop|hidScanInput|svcSendSyncRequest)\b"
)
_3DS_REPOS = re.compile(
    r"^(devkitPro|LumaTeam|smealum|derrekr|rust3ds|fincs|citra-emu|PabloMK7|Steveice10|"
    r"profi200|Universal-Team|mtheall|xem)/",
    re.I,
)
_UNITY_RE = re.compile(r"\b(MonoBehaviour|UnityEngine|ScriptableObject|SerializeField|UnityEditor)\b")
_UNREAL_RE = re.compile(r"\b(UCLASS|UPROPERTY|UFUNCTION|GENERATED_BODY|USTRUCT)\s*\(")
_SHADER_RE = re.compile(r"\b(gl_FragColor|gl_Position|SV_Target|SV_Position|shader_type\s+(?:spatial|canvas_item))\b")
_RE_RE = re.compile(
    r"(\bghidra\b|\bidaapi\b|\bidautils\b|\bida_\w+|\bangr\b|from pwn import|\bpwntools\b|\bfrida\b|"
    r"Interceptor\.attach|\bcapstone\b|\bunicorn\b|\byara\b|\brizin\b|\bradare2\b|\br2pipe\b|"
    r"\bbinaryninja\b|\bkeystone\b)",
    re.I,
)

# --- doc domains -----------------------------------------------------------------------
_DOC_DOMAINS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(^|\.)ffmpeg\.org$|(^|\.)trac\.ffmpeg\.org$"), "crawl_ffmpeg"),
    (re.compile(r"(^|\.)learn\.microsoft\.com$|(^|\.)docs\.microsoft\.com$"), "crawl_mslearn"),
    (re.compile(r"(^|\.)3dbrew\.org$|(^|\.)devkitpro\.org$|libctru\.devkitpro\.org$"), "crawl_3ds"),
    (re.compile(r"(^|\.)(cwe|capec|cve|attack)\.mitre\.org$|(^|\.)owasp\.org$|(^|\.)openssf\.org$|"
                r"(^|\.)nvd\.nist\.gov$|cheatsheetseries\.owasp\.org$"), "crawl_security"),
    (re.compile(r"(^|\.)developer\.arm\.com$|arm\.jonpalmisc\.com$|(^|\.)rizin\.re$|book\.rada\.re$|"
                r"(^|\.)ghidra-sre\.org$|(^|\.)felixcloutier\.com$|(^|\.)capstone-engine\.org$|"
                r"(^|\.)unicorn-engine\.org$|docs\.angr\.io$|docs\.pwntools\.com$|(^|\.)frida\.re$|"
                r"yara\.readthedocs\.io$|(^|\.)6502\.org$|(^|\.)masswerk\.at$|(^|\.)z80\.info$|"
                r"(^|\.)nesdev\.org$|(^|\.)hex-rays\.com$"), "crawl_re"),
    (re.compile(r"docs\.godotengine\.org$|docs\.unity3d\.com$|dev\.epicgames\.com$|"
                r"(^|\.)thebookofshaders\.com$|registry\.khronos\.org$|(^|\.)khronos\.org$"), "crawl_gamedev"),
    (re.compile(r"(^|\.)git-scm\.com$|(^|\.)gnu\.org$|(^|\.)man7\.org$|(^|\.)tldr\.sh$|"
                r"(^|\.)shellcheck\.net$|wiki\.archlinux\.org$"), "crawl_shell"),
    (re.compile(r"(^|\.)react\.dev$|(^|\.)nextjs\.org$|(^|\.)vuejs\.org$|(^|\.)nuxt\.com$|"
                r"(^|\.)nodejs\.org$|(^|\.)expressjs\.com$|(^|\.)laravel\.com$|(^|\.)php\.net$|"
                r"developer\.mozilla\.org$"), "crawl_webfw"),
]
# learn.microsoft.com path → product tag (kept as metadata.product for filtering)
_MSLEARN_PRODUCT_RE = re.compile(r"^/[a-z]{2}-[a-z]{2}/([a-z0-9-]+)(?:/([a-z0-9-]+))?")

# --- query routing: words in the ask → topic collections -------------------------------
_QUERY_TOPICS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bffmpeg\b|\bffprobe\b|\blibav(?:codec|format|filter|util|device)\b|\bavcodec_|\bsws_scale\b", re.I),
     "crawl_ffmpeg"),
    (re.compile(r"\bpowershell\b|\bazure\b|\.ps1\b|\b(?:Get|Set|New|Remove|Invoke)-[A-Z][a-zA-Z]+|\bdotnet\b|"
                r"\bmsbuild\b|\bwin32\b|\bwinapi\b|\bwinrt\b|\bmsvc\b|\bnuget\b", re.I),
     "crawl_mslearn"),
    (re.compile(r"\blibctru\b|\bcitro[23]d\b|\b3dsx\b|\bdevkitpro\b|\bdevkitarm\b|\bluma3ds\b|\b3ds\b|"
                r"\bnintendo 3ds\b|\bmakerom\b|\bctru\b", re.I),
     "crawl_3ds"),
    (re.compile(r"\bunity\b|\bunreal\b|\bgodot\b|\bgdscript\b|\bshaders?\b|\bhlsl\b|\bglsl\b|"
                r"\bmonobehaviour\b|\bblueprints?\b|\bue5\b|\bue4\b", re.I),
     "crawl_gamedev"),
    (re.compile(r"\bghidra\b|\bida\b|\bangr\b|\bpwntools\b|\bfrida\b|\byara\b|\bdisassembl|\bdecompil|"
                r"\breverse[- ]engineer|\bassembly\b|\bx86(?:[-_]64)?\b|\baarch64\b|\barm64\b|\bthumb\b|"
                r"\b6502\b|\b65816\b|\bz80\b|\b68000\b|\b68k\b|\bmips\b|\brizin\b|\bradare2\b|\bcapstone\b",
                re.I),
     "crawl_re"),
    (re.compile(r"\bcwe-?\d*\b|\bcapec\b|\bowasp\b|\bxss\b|\bsql injection\b|\bcsrf\b|\bssrf\b|"
                r"\bvulnerab|\bsanitiz|\bexploit", re.I),
     "crawl_security"),
    (re.compile(r"\bgit\b|\bbash\b|\bshell script|\bmakefile\b|\blinux\b|\bcoreutils\b|\bsed\b|\bawk\b|"
                r"\bgrep\b|\bcron\b|\bsystemd\b|\bshellcheck\b", re.I),
     "crawl_shell"),
    (re.compile(r"\breact\b|\bnext\.?js\b|\bvue\b|\bnuxt\b|\bexpress(?:\.js)?\b|\blaravel\b|\bnode\.?js\b|"
                r"\bphp\b|\bjsx\b", re.I),
     "crawl_webfw"),
]
_QUERY_LANGUAGES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpython\b|\bpytest\b|\bpip\b|\bdjango\b|\bflask\b", re.I), "python"),
    (re.compile(r"\btypescript\b|\btsx?\b", re.I), "typescript"),
    (re.compile(r"\bjavascript\b|\bnode\.?js\b|\bnpm\b|\breact\b|\bvue\b|\bexpress\b", re.I), "javascript"),
    (re.compile(r"\bphp\b|\blaravel\b|\bcomposer\b", re.I), "php"),
    (re.compile(r"\brust\b|\bcargo\b", re.I), "rust"),
    (re.compile(r"\bgolang\b|\bgo (?:module|code|func)", re.I), "go"),
    (re.compile(r"\bruby\b|\brails\b", re.I), "ruby"),
    (re.compile(r"\bjava\b(?!script)", re.I), "java"),
    (re.compile(r"\bc#|\bcsharp\b|\.net\b|\bunity\b", re.I), "csharp"),
    (re.compile(r"\bsql\b|\bpostgres|\bmysql\b|\bsqlite\b", re.I), "sql"),
    (re.compile(r"\bbash\b|\bshell script", re.I), "bash"),
    (re.compile(r"\bc\+\+|\bcpp\b|\bunreal\b", re.I), "cpp"),
    (re.compile(r"\bin c\b|\bc code\b|\bc header|\bstruct\b.*\.h\b", re.I), "c"),
    (re.compile(r"\bmakefile\b|\bcmake\b", re.I), "make"),
    (re.compile(r"\blua\b", re.I), "lua"),
    (re.compile(r"\bgdscript\b|\bgodot\b", re.I), "gdscript"),
    (re.compile(r"\bhlsl\b|\bglsl\b|\bshaders?\b", re.I), "shader"),
    (re.compile(r"\bassembly\b|\basm\b|\bx86\b|\barm64\b|\b6502\b|\bz80\b", re.I), "asm"),
]


def code_collection(slug: str) -> str:
    return f"{CODE_PREFIX}{slug}"


def language_slug(language: str | None, path: str | None = None) -> str | None:
    """Collection slug for a crawler language label or file path; None = dropped language."""
    lang = (language or "").strip().lower()
    if not lang and path:
        lang = language_for_path(path) or ""
    if lang in DROP_LANGUAGES:
        return None
    return CODE_LANGUAGES.get(lang)


def language_for_path(path: str) -> str | None:
    name = (path or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in {"makefile", "gnumakefile"}:
        return "make"
    if name == "dockerfile":
        return "dockerfile"
    if name == "cmakelists.txt":
        return "cmake"
    if "." not in name:
        return None
    return EXT_LANGUAGE.get("." + name.rsplit(".", 1)[-1])


def classify_github_row(meta: dict, text: str) -> str | None:
    """Collection for one GitHub crawl row (code or README), or None to drop it."""
    repo = str(meta.get("repo") or "")
    path = str(meta.get("path") or "")
    language = str(meta.get("language") or "").lower() or (language_for_path(path) or "")
    if _3DS_REPOS.search(repo + "/") or _3DS_RE.search(text):
        return "crawl_3ds"
    if language in {"gdscript", "hlsl", "glsl", "shader", "gdshader", "shaderlab"} or path.lower().endswith((".gd", ".gdshader", ".shader", ".hlsl", ".glsl")):
        return "crawl_gamedev"
    if (language in {"csharp", "c#"} and _UNITY_RE.search(text)) or (
        language in {"cpp", "c++", "c"} and _UNREAL_RE.search(text)
    ) or _SHADER_RE.search(text):
        return "crawl_gamedev"
    if language in {"asm", "assembly", "nasm", "yara"} or path.lower().endswith((".yar", ".yara")) or _RE_RE.search(text):
        return "crawl_re"
    slug = language_slug(language, path)
    return code_collection(slug) if slug else None


def classify_doc_url(url: str) -> tuple[str, dict]:
    """Topic collection for a crawled web doc page (+ extra metadata such as the MS Learn product)."""
    parsed = urlparse(url or "")
    host = (parsed.hostname or "").lower()
    for pattern, collection in _DOC_DOMAINS:
        if pattern.search(host):
            extra: dict = {}
            if collection == "crawl_mslearn":
                m = _MSLEARN_PRODUCT_RE.match(parsed.path or "")
                if m:
                    extra["product"] = m.group(1)
            return collection, extra
    return MISC_DOCS, {}


def query_topics(text: str) -> list[str]:
    """Topic collections the ask's own words point at (order = pattern order)."""
    return [coll for pattern, coll in _QUERY_TOPICS if pattern.search(text or "")]


def query_languages(text: str, attached_paths: list[str] | tuple[str, ...] = ()) -> list[str]:
    """Language slugs from attached files first (strongest signal), then from the ask's words."""
    out: list[str] = []
    for path in attached_paths:
        slug = language_slug(None, path)
        if slug and slug not in out:
            out.append(slug)
    for pattern, slug in _QUERY_LANGUAGES:
        if slug not in out and pattern.search(text or ""):
            out.append(slug)
    return out


def route_collections(
    text: str, attached_paths: list[str] | tuple[str, ...] = (), max_languages: int = 2
) -> list[str]:
    """Collections to search for a request: code per language (attached files first), then topics."""
    langs = query_languages(text, attached_paths)[:max_languages]
    return [code_collection(s) for s in langs] + query_topics(text) + [MISC_DOCS]

TOPIC_COLLECTIONS = frozenset(
    {"crawl_3ds", "crawl_gamedev", "crawl_re", "crawl_security", "crawl_ffmpeg", "crawl_mslearn",
     "crawl_shell", "crawl_webfw", MISC_DOCS}
)
