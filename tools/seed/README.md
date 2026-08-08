# NLPP domain lesson seeds (P5)

**One-time apply (2026-08-02).** Four lessons are in Chroma `coding_lessons`; ChatRouter does not re-seed on boot.

Re-run only after wiping `Mind/chromadb/`:

```powershell
python tools/seed/seed_nlpp_lessons.py
```

Idempotent by `seed_id` in lesson metadata.
