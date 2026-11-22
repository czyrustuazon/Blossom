"""
Hidden acceptance for php-modernize: the site must run on PHP 8.3 and use the database safely.
Static checks only (no php on the eval host), via the lexer in _php_scan.py.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _php_scan import balance_errors, code_only, php_files, sql_literals, unsafe_sql  # noqa: E402

ROOT = Path(".")
FILES = php_files(ROOT)

# Removed in PHP 7.0 / 8.0 (mysql_* extension, POSIX regex, split, each, magic quotes, ...).
REMOVED = [
    (r"\bmysql_\w+\s*\(", "mysql_* (removed in PHP 7)"),
    (r"(?<![\w$>:\\])(?:eregi?|eregi?_replace|spliti?)\s*\(", "ereg/eregi/split (removed in PHP 7)"),
    (r"(?<![\w$>:\\])each\s*\(", "each() (removed in PHP 8)"),
    (r"\bcreate_function\s*\(", "create_function (removed in PHP 8)"),
    (r"\bget_magic_quotes_(?:gpc|runtime)\s*\(", "get_magic_quotes_* (removed in PHP 8)"),
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def test_pages_still_exist():
    names = {p.as_posix() for p in FILES}
    for page in ("login.php", "gallery.php", "user.php"):
        assert page in names, f"{page} is missing"


def test_syntax_is_balanced():
    bad = {p.as_posix(): balance_errors(_read(p)) for p in FILES}
    bad = {k: v for k, v in bad.items() if v}
    assert not bad, f"broken PHP structure: {bad}"


def test_no_functions_removed_from_php():
    hits = []
    for p in FILES:
        code = code_only(_read(p))
        for pattern, label in REMOVED:
            for m in re.finditer(pattern, code):
                hits.append(f"{p.as_posix()}: {m.group(0).strip()} — {label}")
    assert not hits, "still calls functions that no longer exist:\n" + "\n".join(hits)


def test_database_layer_is_pdo_or_mysqli():
    code = "\n".join(code_only(_read(p)) for p in FILES)
    assert re.search(r"new\s+\\?PDO\s*\(|new\s+\\?mysqli\s*\(|\bmysqli_connect\s*\(", code), (
        "no PDO / mysqli connection found"
    )


def test_no_variables_spliced_into_sql():
    problems = []
    for p in FILES:
        for prob in unsafe_sql(_read(p)):
            problems.append(f"{p.as_posix()}: {prob}")
    assert not problems, "SQL still built from variables (use placeholders):\n" + "\n".join(problems)


def test_queries_use_prepared_statements():
    code = "\n".join(code_only(_read(p)) for p in FILES)
    assert re.search(r"->\s*prepare\s*\(|\bmysqli_prepare\s*\(", code), "no prepared statements"
    for page in ("login.php", "user.php"):
        sql = sql_literals(_read(ROOT / page))
        if not sql:
            continue  # queries moved into helpers; the splice test above covers those
        assert any(re.search(r"\?|:\w+", s) for s in sql), f"{page}: SQL has no placeholders"


def test_helpers_kept():
    code = "\n".join(code_only(_read(p)) for p in FILES)
    for fn in ("redirect_to", "sanitize", "numbers_only", "valid_email", "tag_list",
               "get_username", "count_pictures", "html_head", "html_foot"):
        assert re.search(r"\bfunction\s+" + fn + r"\s*\(", code), f"helper {fn}() was removed or renamed"


def test_inputs_still_read():
    expect = {
        "login.php": ["login_name", "password", "confirm_user"],
        "gallery.php": ["page", "user"],
        "user.php": ["id", "email", "tags"],
    }
    for page, keys in expect.items():
        src = _read(ROOT / page)
        for key in keys:
            assert re.search(r"\$_(?:GET|POST|REQUEST)\s*\[\s*['\"]" + key + r"['\"]", src) or (
                re.search(r"filter_input\s*\([^)]*['\"]" + key + r"['\"]", src)
            ), f"{page} no longer reads input {key!r}"
