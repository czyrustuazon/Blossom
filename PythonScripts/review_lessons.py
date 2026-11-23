"""
Review auto-learned coding lessons before they reach the Mind.

  python review_lessons.py                     # list pending lessons
  python review_lessons.py list --status all   # pending / approved / rejected / all
  python review_lessons.py show <id>           # full text of one lesson
  python review_lessons.py approve <id> [<id>…]
  python review_lessons.py reject <id> [<id>…] [--reason "why"]

Ids are the short ids from `list` (the "queued:" prefix is optional).
Uses BLOSSOM_MIND_ROOT when set, else the repo's Mind/ folder.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

import LessonQueue
from MindStores import SURFACE_ASSISTANT, surface_scope
from SemanticMemory import looks_like_broken_agent_output, looks_like_non_solution


def _warnings(text: str) -> list[str]:
    out = []
    if looks_like_broken_agent_output(text):
        out.append("agent-loop debris")
    if looks_like_non_solution(text):
        out.append("non-answer")
    return out


def _ask(text: str) -> str:
    m = re.search(r"User ask: (.*)", text)
    return (m.group(1) if m else text).strip()


def _answer(text: str) -> str:
    return text.split("Working solution", 1)[-1].split(":\n", 1)[-1].strip()


def cmd_list(status: str) -> int:
    entries = LessonQueue.list_entries(None if status == "all" else status)
    if not entries:
        print(f"No {status} lessons.  ({LessonQueue.db_file()})")
        return 0
    for e in entries:
        age_h = (time.time() - e["created"]) / 3600
        flags = []
        if e["metadata"].get("user_verified"):
            flags.append("USER-VERIFIED")
        flags += [w.upper() for w in _warnings(e["text"])]
        if e["status"] != "pending":
            flags.append(e["status"].upper())
        print(f"[{e['id']}] {age_h:5.1f}h ago  {e['metadata'].get('source', '?')}"
              + (f"  ({', '.join(flags)})" if flags else ""))
        print(f"    ask:    {_ask(e['text'])[:110]}")
        print(f"    answer: {_answer(e['text'])[:220].replace(chr(10), ' ⏎ ')}")
    print(f"\n{len(entries)} {status} lesson(s).  show <id> for full text; approve / reject <id>.")
    return 0


def cmd_show(qid: str) -> int:
    e = LessonQueue.get_entry(qid)
    if not e:
        print(f"No lesson {qid}.")
        return 1
    print(f"id {e['id']}  status {e['status']}  importance {e['importance']}  "
          f"metadata {e['metadata']}")
    warn = _warnings(e["text"])
    if warn:
        print(f"WARNING: looks like {', '.join(warn)}")
    print("-" * 70)
    print(e["text"])
    return 0


def cmd_approve(ids: list[str]) -> int:
    rc = 0
    with surface_scope(SURFACE_ASSISTANT):
        for qid in ids:
            mid = LessonQueue.approve(qid)
            if mid:
                print(f"approved {qid} -> memory {mid}")
            else:
                print(f"{qid}: not found or not pending")
                rc = 1
    return rc


def cmd_reject(ids: list[str], reason: str) -> int:
    rc = 0
    for qid in ids:
        if LessonQueue.reject(qid, reason):
            print(f"rejected {qid}")
        else:
            print(f"{qid}: not found or not pending")
            rc = 1
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    p_list = sub.add_parser("list")
    p_list.add_argument("--status", default="pending",
                        choices=["pending", "approved", "rejected", "all"])
    p_show = sub.add_parser("show")
    p_show.add_argument("id")
    p_app = sub.add_parser("approve")
    p_app.add_argument("ids", nargs="+")
    p_rej = sub.add_parser("reject")
    p_rej.add_argument("ids", nargs="+")
    p_rej.add_argument("--reason", default="")
    args = ap.parse_args(argv)

    if args.cmd in (None, "list"):
        return cmd_list(getattr(args, "status", "pending"))
    if args.cmd == "show":
        return cmd_show(args.id)
    if args.cmd == "approve":
        return cmd_approve(args.ids)
    return cmd_reject(args.ids, args.reason)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
