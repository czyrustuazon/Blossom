# Crawl → per-topic RAG collections

Turns the rag-web-crawler output (`C:\Users\Zepse\Documents\rag-web-crawler\out`) into Chroma
collections per language (`crawl_code_<lang>`) and per topic (`crawl_3ds`, `crawl_gamedev`,
`crawl_re`, `crawl_security`, `crawl_ffmpeg`, `crawl_mslearn`, `crawl_shell`, `crawl_webfw`,
`crawl_misc`). ChatRouter searches only the collections a request points at
(`PythonScripts/CrawlTopics.py`).

| File | What it does |
|------|--------------|
| `cast_chunk.py` | cAST chunking (tree-sitter): oversized syntax nodes split into children, small siblings merged, 450 non-whitespace chars per chunk; headings for docs, blank lines as fallback |
| `tune_budget.py` | Measures how many stamped chunks fit the embedder's 256-token window at several budgets |
| `build_topic_corpus.py` | `scan` → `select` (prints counts per collection) → `split` → `import` (scratch Mind, or `--real-mind` into a staging store) → `promote` (moves staging to `Mind/assistant/crawl_chromadb`; restart the Assistant router) |

Work files live in `Mind/rag/topic_build/` (gitignored).

**Keep the crawl JSONL files** (compressed is fine) and the crawler's `data/` after importing.
The store holds a curated slice embedded with one model; the JSONL is the only full copy and the
only way to re-curate, re-chunk or re-embed (another embedder, LM Studio front ends, AnythingLLM)
without days of re-downloading. Full reasoning: the crawler's README, section
"Keep the output files".
