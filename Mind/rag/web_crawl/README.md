# Web crawl snapshots

Live export of the first rag-web-crawler pass (finished 18 Oct 2026, compacted 7 Nov 2026). Embedded 7 Nov 2026 into the Assistant Chroma store (`Mind/assistant/chromadb`) as two collections, keyed by the crawl `id`:

| Collection | Rows |
|---|---|
| `crawl_docs` | 230,565 |
| `crawl_code` | 11,912 |

`tools/import_crawl_corpus.py` did the upsert with Chroma's default embedder. It is resumable via `import_progress.json`. On a coding turn, `ChatRouter._crawl_reference_block` adds up to 4 `crawl_docs` hits and 3 `crawl_code` hits to the coder prompt (same skip rules as coding lessons). Casual chat does not read them.

| File | Rows | What it is |
|---|---|---|
| `rag_docs.jsonl` | 230,565 | Documentation chunks. Load as its own collection. |
| `rag_code.jsonl` | 11,912 | Code samples that have a language tag. Load as a second collection. |

Both files are gitignored. They are copies of the snapshots on this machine at `Documents\rag-web-crawler\out\` and on mainserver at `/home/zepse/crawler/rag-web-crawler/out/`.

Each line is one JSON object: `id`, `kind` (`documentation` or `code_sample`), `action` (`upsert`), `text`, `metadata` (`url`, `title`, `section`, `breadcrumb`, and `language` on code rows). Import by `id`. Replace the collection when a later crawl is compacted; do not append.

How the log was replayed, which code rows were dropped, and the recrawl backlog are written up in `Documents\rag-web-crawler\docs\first-pass-corpus.md`.
