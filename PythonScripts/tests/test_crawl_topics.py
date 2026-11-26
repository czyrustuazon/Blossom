"""Per-topic crawl collections: import-side classification and query-side routing."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ChatRouter  # noqa: E402
import SemanticMemory  # noqa: E402
from CrawlTopics import (  # noqa: E402
    classify_doc_url,
    classify_github_row,
    route_collections,
)


def gh(language, path="src/x", repo="acme/x"):
    return {"language": language, "path": path, "repo": repo}


# --- import side --------------------------------------------------------------------


def test_github_rows_go_to_their_language_or_topic():
    assert classify_github_row(gh("python", "a.py"), "def f(): pass") == "crawl_code_python"
    assert classify_github_row(gh("kotlin", "a.kt"), "fun f() {}") is None
    assert classify_github_row(gh("c", "main.c"), "#include <3ds.h>\ngfxInitDefault();") == "crawl_3ds"
    assert classify_github_row(gh("c", "x.c", repo="devkitPro/libctru"), "int x;") == "crawl_3ds"
    assert classify_github_row(gh("csharp", "P.cs"), "class P : MonoBehaviour {}") == "crawl_gamedev"
    assert classify_github_row(gh("csharp", "P.cs"), "class P {}") == "crawl_code_csharp"
    assert classify_github_row(gh("cpp", "A.h"), "UCLASS()\nclass AFoo : public AActor") == "crawl_gamedev"
    assert classify_github_row(gh("python", "s.py"), "from pwn import *") == "crawl_re"
    assert classify_github_row(gh("", "boot.asm"), "mov eax, 1") == "crawl_re"
    assert classify_github_row(gh("", "Makefile"), "all:\n\tcc x.c") == "crawl_code_make"


def test_doc_urls_route_by_domain():
    assert classify_doc_url("https://ffmpeg.org/ffmpeg-filters.html")[0] == "crawl_ffmpeg"
    coll, extra = classify_doc_url("https://learn.microsoft.com/en-us/powershell/module/x")
    assert coll == "crawl_mslearn" and extra == {"product": "powershell"}
    assert classify_doc_url("https://cwe.mitre.org/data/definitions/79.html")[0] == "crawl_security"
    assert classify_doc_url("https://book.rada.re/x")[0] == "crawl_re"
    assert classify_doc_url("https://docs.python.org/3/")[0] == "crawl_misc"


# --- query side ---------------------------------------------------------------------


def test_python_refactor_never_reaches_ffmpeg_or_mslearn():
    routed = route_collections("rename calc_total to compute_order_total", ["shop/cart.py", "tests/test_cart.py"])
    assert routed == ["crawl_code_python", "crawl_misc"]


def test_topics_come_from_the_ask():
    assert "crawl_ffmpeg" in route_collections("use libavcodec to decode h264 frames", ["dec.c"])
    assert route_collections("use libavcodec to decode h264 frames", ["dec.c"])[0] == "crawl_code_c"
    assert "crawl_mslearn" in route_collections("write a PowerShell script with Get-ChildItem")
    assert "crawl_3ds" in route_collections("draw a sprite with citro2d", ["source/main.c"])
    assert "crawl_re" in route_collections("write a ghidra script to rename functions")


def test_attached_files_decide_languages_first():
    routed = route_collections("make it faster", ["a.rs", "b.go", "c.py"])
    assert routed[:2] == ["crawl_code_rust", "crawl_code_go"]
    assert len([c for c in routed if c.startswith("crawl_code_")]) == 2
    assert routed[-1] == "crawl_misc"


def test_crawl_block_routes_when_topic_collections_exist():
    queried: list[str] = []

    def fake_query(focus, collection, top_k):
        queried.append(collection)
        return [{"text": f"hit from {collection}", "distance": 0.2, "metadata": {"url": f"https://x/{collection}"}}]

    existing = frozenset({"crawl_code_python", "crawl_ffmpeg", "crawl_mslearn", "crawl_docs", "crawl_code"})
    with patch.object(ChatRouter, "existing_collections", lambda surface=None: existing), patch.object(
        ChatRouter, "query_memories", fake_query
    ):
        block, n = ChatRouter._crawl_reference_block("rename a function", ["pkg/a.py"])
    assert queried == ["crawl_code_python"]
    assert n == 1 and "crawl_code_python" in block


def test_crawl_block_keeps_the_legacy_pair_until_the_topic_import_ran():
    queried: list[str] = []

    def fake_query(focus, collection, top_k):
        queried.append(collection)
        return []

    with patch.object(ChatRouter, "existing_collections", lambda surface=None: frozenset({"crawl_docs", "crawl_code"})), patch.object(
        ChatRouter, "query_memories", fake_query
    ):
        ChatRouter._crawl_reference_block("rename a function", ["pkg/a.py"])
    assert queried == [ChatRouter.COLLECTION_CRAWL_DOCS, ChatRouter.COLLECTION_CRAWL_CODE]


def test_crawl_retrieval_off_queries_nothing(monkeypatch):
    # The crawl on/off A/B: "off" must also skip the legacy pair, which a router without
    # topic collections otherwise still queries.
    queried: list[str] = []

    def fake_query(focus, collection, top_k):
        queried.append(collection)
        return [{"text": "hit", "distance": 0.1, "metadata": {}}]

    monkeypatch.setenv("CRAWL_RETRIEVAL", "0")
    with patch.object(ChatRouter, "existing_collections", lambda surface=None: frozenset({"crawl_docs", "crawl_code_python"})), patch.object(
        ChatRouter, "query_memories", fake_query
    ):
        assert ChatRouter._crawl_reference_block("rename a struct field", ["src/item.c"]) == ("", 0)
    assert queried == []


def test_topic_collections_live_in_the_assistant_store():
    assert SemanticMemory.collection_home("crawl_code_rust") == SemanticMemory.SURFACE_ASSISTANT
    assert SemanticMemory.collection_home("crawl_ffmpeg") == SemanticMemory.SURFACE_ASSISTANT


def test_topic_crawl_collections_use_their_own_store(tmp_path, monkeypatch):
    monkeypatch.setenv("CRAWL_CHROMA_DIR", str(tmp_path / "crawl"))
    main = SemanticMemory.MindStores.chroma_dir(SemanticMemory.SURFACE_ASSISTANT)
    assert SemanticMemory._store_path("crawl_code_python", SemanticMemory.SURFACE_ASSISTANT) == tmp_path / "crawl"
    assert SemanticMemory._store_path("crawl_docs", SemanticMemory.SURFACE_ASSISTANT) == main
    assert SemanticMemory._store_path("coding_lessons", SemanticMemory.SURFACE_ASSISTANT) == main
