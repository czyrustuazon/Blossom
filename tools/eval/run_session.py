"""
Multi-turn session tasks through the REAL Blossom Assistant extension: session memory across
auto compaction, /compact, and closing VS Code + reopening the chat from .blossom/chats.

A session task (corpora/session-memory) lists `steps` in task.json:
  {"send": "...", "newChat": true, "noEdits": true}   one chat turn ("$prompt" = task prompt)
  {"untilCompacted": ["...", ...], "noEdits": true}  send these one by one until auto
                                                      compaction has written a summary chapter
  {"compact": "focus"}                               /compact [focus], same path as typing it
  {"restart": true}                                  close the window, relaunch VS Code on the
                                                      same workspace, reopen the saved chat
`facts` are strings the early turns established; the run reports whether the summary, the
saved archive and the restored tab still hold them. The task's `checks` score the workspace
after the last step, like run_vscode.py (hidden acceptance copied in only for scoring).

Required for a pass: auto compaction fired, /compact folded turns, the restored tab matches
the saved archive, and every task check passes. A run is INVALID (not a pass or a fail) if a
noEdits turn changed files, since the last step could then pass without remembering anything.

  python run_session.py --task compaction-restore --runs 2 --out <dir>
  (router from --router-url or BLOSSOM_EVAL_CHAT_URL; never the real :8083 router)
"""
from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blossom_eval.corpus import load_corpus  # noqa: E402
from blossom_eval.scorers import run_check  # noqa: E402
from run_vscode import (  # noqa: E402
    Mcp,
    code_pids,
    find_window,
    kill_launch,
    parse_settings,
    prepare_workspace,
    wait_code_exit,
)

ARCHIVE_DIR = Path(".blossom") / "chats"


class Run:
    """One session run: the window, its MCP client, and everything recorded on the way."""

    def __init__(self, task, raw: dict, run_name: str, args):
        self.task, self.raw, self.args = task, raw, args
        self.ws = Path(args.ws_root) / f"{task.id}-{run_name}"
        self.out = Path(args.out) / run_name / task.id
        self.out.mkdir(parents=True, exist_ok=True)
        self.mcp: Mcp | None = None
        self.window = 0
        self.turn_no = 0
        self.steps: list[dict] = []
        self.invalid: list[str] = []

    def log(self, msg: str) -> None:
        print(f"  [{self.task.id}] {msg}", flush=True)

    # ---- window -------------------------------------------------------------------

    def launch(self) -> None:
        self.window += 1
        before = code_pids()
        started = time.time()
        subprocess.Popen(f'code --new-window "{self.ws}"', shell=True)
        try:
            url = find_window(self.ws, started)
        except Exception:  # noqa: BLE001 — hung launch: kill it and retry once
            self.log("window did not come up; killing that launch and retrying")
            kill_launch(self.ws)
            time.sleep(5)
            started = time.time()
            subprocess.Popen(f'code --new-window "{self.ws}"', shell=True)
            url = find_window(self.ws, started)
        self._pids = code_pids() - before
        self.mcp = Mcp(url)
        self.mcp.initialize()
        info = json.loads(self.mcp.call("blossom_info"))
        self.log(f"window {self.window} up: v{info['version']} backend={info.get('apiBaseUrl')}")
        if "8083" in str(info.get("apiBaseUrl")):
            self.mcp.call("blossom_close_window")
            raise RuntimeError("window is pointed at the real :8083 router; refusing to run")
        tools = {t["name"] for t in self.mcp._post(
            {"jsonrpc": "2.0", "id": 0, "method": "tools/list"}, 15)["result"]["tools"]}
        if "blossom_open_archive" not in tools:
            raise RuntimeError(f"extension v{info['version']} has no blossom_open_archive (need >= 0.1.91)")
        time.sleep(self.args.settle)

    def save_window_logs(self) -> None:
        assert self.mcp
        trace = self.mcp.call("blossom_trace", {"afterSeq": 0, "limit": 20000})
        (self.out / f"trace-w{self.window}.log").write_text(trace, encoding="utf-8")
        try:
            index = json.loads(self.mcp.call("blossom_rounds"))
            for row in index:
                text = self.mcp.call("blossom_rounds", {"seq": row["seq"]}, timeout=60)
                (self.out / f"w{self.window}-round-{row['seq']:03d}.md").write_text(text, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            self.log(f"rounds not saved: {exc}")

    def close(self) -> None:
        if not self.mcp:
            return
        try:
            self.save_window_logs()
            self.mcp.call("blossom_close_window")
        except Exception:  # noqa: BLE001 — window may already be gone
            pass
        self.mcp = None
        wait_code_exit(self._pids)

    # ---- session ------------------------------------------------------------------

    def state(self, wait: bool = True) -> dict:
        assert self.mcp
        return json.loads(self.mcp.call("blossom_session_state", {"waitCompaction": wait}, timeout=600))

    def project_changed(self) -> list[str]:
        """Project files that differ from the task's pristine copy."""
        src = self.task.project_path
        changed = []
        for f in src.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                rel = f.relative_to(src)
                dst = self.ws / rel
                if not dst.is_file() or not filecmp.cmp(f, dst, shallow=False):
                    changed.append(str(rel).replace("\\", "/"))
        return changed

    def turn(self, prompt: str, new_chat: bool, no_edits: bool = False) -> dict:
        assert self.mcp
        self.turn_no += 1
        self.mcp.call("blossom_send", {"prompt": prompt, "newChat": new_chat}, timeout=30)
        deadline = time.time() + self.args.timeout_min * 60
        answered: list[str] = []
        while True:
            s = json.loads(self.mcp.call("blossom_wait", {"timeoutSec": 240}, timeout=300))
            self.log(f"turn {self.turn_no}: {s['state']} {s['elapsedSec']}s rounds={s['rounds']} "
                     f"edits={len(s['editsApplied'])} last={s['lastStatus'][:60]!r}")
            if s["state"] == "finished":
                break
            for p in s.get("pending", []):
                decision = {"command": "run", "step": "continue", "ask": "skip"}[p["kind"]]
                if p["kind"] == "ask" and p["text"].startswith("That's the plan"):
                    # Approve on a real change; on a "don't edit" turn a user would cancel.
                    # (s1 on 2026-11-25 approved it and the decide turn wrote config.py.)
                    decision = "1" if no_edits else "0"
                self.mcp.call("blossom_respond", {"kind": p["kind"], "id": p["id"], "decision": decision})
                answered.append(f"{p['kind']} {p['id']} -> {decision}: {p['text'][:120]}")
            if time.time() > deadline:
                self.mcp.call("blossom_cancel")
                time.sleep(5)
                s = json.loads(self.mcp.call("blossom_status"))
                s["outcome"] = f"eval-timeout ({self.args.timeout_min} min)"
                break
        s["answered"] = answered
        return s

    def archive_on_disk(self, archive_id: str) -> dict | None:
        p = self.ws / ARCHIVE_DIR / f"{archive_id}.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def facts_in(self, text: str) -> dict[str, bool]:
        low = (text or "").lower()
        return {f: f.lower() in low for f in self.raw.get("facts", [])}

    def record(self, step_id: str, kind: str, **data) -> dict:
        row = {"step": step_id, "kind": kind, **data}
        self.steps.append(row)
        with open(self.out / "steps.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return row

    def send_step(self, step: dict, prompt: str) -> dict:
        s = self.turn(prompt, bool(step.get("newChat")), bool(step.get("noEdits")))
        st = self.state(wait=True)
        changed = self.project_changed() if step.get("noEdits") else []
        if changed:
            self.invalid.append(f"step {step['id']} turn {self.turn_no} edited {changed}")
        disk = self.archive_on_disk(st["archiveId"])
        return self.record(
            step["id"], "send", turn=self.turn_no, prompt=prompt[:300], outcome=s.get("outcome"),
            rounds=s.get("rounds"), elapsedSec=s.get("elapsedSec"), editsApplied=s.get("editsApplied"),
            changedFiles=changed, finalText=(s.get("finalText") or "")[:2000], answered=s["answered"],
            historyMessages=st["historyMessages"], packChars=st["packChars"],
            budgetChars=st["budgetChars"], chapters=st["chapters"], summaryChars=len(st["summary"]),
            summaryFacts=self.facts_in(st["summary"]),
            # 0.1.92+: real llama-server token totals and compaction count for the chat.
            stats={k: (st.get("stats") or {}).get(k) for k in
                   ("promptTokens", "completionTokens", "calls", "compactions")},
            # The archive is written when the turn ends; background compaction finishes later.
            archiveSummaryInSync=bool(disk) and (disk.get("historySummary") or "") == st["summary"],
        )

    # ---- main ---------------------------------------------------------------------

    def run(self) -> dict:
        prepare_workspace(self.task, self.ws, self.args.router_url, self.args.port,
                          {**self.raw.get("settings", {}), **parse_settings(self.args.set)})
        self.launch()
        live_before_close: dict = {}
        restored: dict = {}
        archived: dict | None = None
        final: dict = {}
        try:
            for step in self.raw["steps"]:
                sid = step.get("id", f"s{len(self.steps) + 1}")
                step = {**step, "id": sid}
                if "send" in step:
                    prompt = self.task.prompt if step["send"] == "$prompt" else step["send"]
                    row = self.send_step(step, prompt)
                    if step["send"] == "$prompt":
                        final = row
                elif "untilCompacted" in step:
                    fired = False
                    for i, prompt in enumerate(step["untilCompacted"], 1):
                        row = self.send_step({**step, "id": f"{sid}-{i}"}, prompt)
                        if row["chapters"] >= 1:
                            fired = True
                            break
                    self.record(sid, "untilCompacted", fired=fired, turnsSent=i)
                elif "compact" in step:
                    assert self.mcp
                    before = self.state(wait=True)
                    after = json.loads(self.mcp.call("blossom_compact", {"focus": step["compact"]}, timeout=900))
                    disk = self.archive_on_disk(after["archiveId"])
                    self.record(sid, "compact", historyBefore=before["historyMessages"],
                                historyAfter=after["historyMessages"], chaptersBefore=before["chapters"],
                                chaptersAfter=after["chapters"], packBefore=before["packChars"],
                                packAfter=after["packChars"], summaryFacts=self.facts_in(after["summary"]),
                                summary=after["summary"],
                                archiveSummaryInSync=bool(disk) and (disk.get("historySummary") or "") == after["summary"])
                elif step.get("restart"):
                    live_before_close = self.state(wait=True)
                    archive_id = live_before_close["archiveId"]
                    self.close()
                    archived = self.archive_on_disk(archive_id)
                    self.launch()
                    assert self.mcp
                    listed = json.loads(self.mcp.call("blossom_archives"))
                    restored = json.loads(self.mcp.call("blossom_open_archive", {"id": archive_id}, timeout=60))
                    self.record(sid, "restart", archiveId=archive_id,
                                archiveListed=any(e["id"] == archive_id for e in listed),
                                liveHistory=live_before_close["historyMessages"],
                                liveSummaryChars=len(live_before_close["summary"]),
                                archivedSummaryChars=len((archived or {}).get("historySummary") or ""),
                                restoredHistory=restored["historyMessages"],
                                restoredChapters=restored["chapters"],
                                restoredSummaryFacts=self.facts_in(restored["summary"]),
                                restoredLedger=restored["ledger"][:1500])
                else:
                    raise ValueError(f"unknown step {step}")
        finally:
            self.close()

        return self.score(live_before_close, archived, restored, final)

    def score(self, live: dict, archived: dict | None, restored: dict, final: dict) -> dict:
        by_kind = {r["kind"]: r for r in self.steps}
        compact = by_kind.get("compact", {})
        auto = by_kind.get("untilCompacted", {})
        # Auto compaction counts if any turn before /compact left a summary chapter, not only
        # inside the padding step (v93s1: it first fired on the turn after padding).
        before_compact = []
        for r in self.steps:
            if r["kind"] == "compact":
                break
            before_compact.append(r)
        session_checks = {
            "auto_compaction_fired": bool(auto.get("fired")) or any(
                r["kind"] == "send" and r.get("chapters", 0) >= 1 for r in before_compact),
            "compact_folded_turns": compact.get("historyAfter", 99) < compact.get("historyBefore", 0),
            "archive_saved": archived is not None,
            "restore_matches_live": bool(restored) and restored.get("summary") == live.get("summary")
            and restored.get("historyMessages") == live.get("historyMessages"),
        }
        if self.task.hidden_path and self.task.hidden_path.is_dir():
            shutil.copytree(self.task.hidden_path, self.ws / "_acceptance", dirs_exist_ok=True)
        results = [run_check(c, work_dir=self.ws, response_text=final.get("finalText") or "")
                   for c in self.task.checks]
        shutil.rmtree(self.ws / "_acceptance", ignore_errors=True)
        task_checks = {r.check_id: {"passed": r.passed, "detail": r.detail[-3000:]} for r in results}
        # Diagnostics: where a fact got lost, if it did. Not required for a pass.
        diagnostics = {
            "facts_in_summary_after_auto": next((r["summaryFacts"] for r in self.steps
                                                 if r["kind"] == "send" and r["chapters"] >= 1), None),
            "facts_in_summary_after_compact": compact.get("summaryFacts"),
            "facts_in_restored_summary": by_kind.get("restart", {}).get("restoredSummaryFacts"),
            "archive_lagged_after_auto_compaction": any(
                r["kind"] == "send" and r["chapters"] >= 1 and not r["archiveSummaryInSync"] for r in self.steps),
        }
        passed = all(session_checks.values()) and all(r.passed for r in results)
        verdict = "INVALID" if self.invalid else ("PASS" if passed else "FAIL")
        score = {"verdict": verdict, "passed": passed and not self.invalid, "invalid": self.invalid,
                 "session_checks": session_checks, "checks": task_checks, "diagnostics": diagnostics}
        (self.out / "score.json").write_text(json.dumps(score, indent=2), encoding="utf-8")
        return {"task": self.task.id, "verdict": verdict, "passed": score["passed"],
                "session_checks": session_checks,
                "task_checks": {k: v["passed"] for k, v in task_checks.items()},
                "diagnostics": diagnostics, "invalid": self.invalid, "turns": self.turn_no,
                "workspace": str(self.ws)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="session-memory")
    ap.add_argument("--task", action="append", help="task id (repeatable; default all)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ws-root", default=str(Path.home() / "Documents" / "blossom-eval-runs"))
    ap.add_argument("--router-url", default=os.getenv("BLOSSOM_EVAL_CHAT_URL", ""))
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--timeout-min", type=float, default=20, help="per turn")
    ap.add_argument("--settle", type=float, default=8)
    ap.add_argument("--name", default="s", help="run name prefix")
    ap.add_argument("--set", action="append", metavar="KEY=JSON", help="extra workspace setting (repeatable)")
    args = ap.parse_args()
    if not args.router_url or ":8083" in args.router_url:
        print("Set --router-url / BLOSSOM_EVAL_CHAT_URL to the isolated test router (not :8083).")
        return 2

    corpus_dir = Path(__file__).resolve().parent / "corpora" / args.corpus
    corpus = load_corpus(corpus_dir)
    tasks = [t for t in corpus.tasks if not args.task or t.id in args.task]
    Path(args.ws_root).mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(1, args.runs + 1):
        for task in tasks:
            raw = json.loads((task.task_dir / "task.json").read_text(encoding="utf-8"))
            name = f"{args.name}{i}"
            print(f"== {name} {task.id}", flush=True)
            try:
                row = Run(task, raw, name, args).run()
            except Exception as exc:  # noqa: BLE001 — record and move on
                row = {"task": task.id, "verdict": "ERROR", "passed": False, "error": f"driver error: {exc}"}
            row["run"] = name
            rows.append(row)
            print(f"  -> {row['verdict']} {json.dumps(row.get('session_checks'))} "
                  f"{json.dumps(row.get('task_checks'))}", flush=True)
            with open(Path(args.out) / "results.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    valid = [r for r in rows if r["verdict"] in {"PASS", "FAIL"}]
    print(f"\n{sum(r['passed'] for r in rows)}/{len(valid)} passed ({len(rows) - len(valid)} invalid/error)")
    return 0 if valid and all(r["passed"] for r in valid) else 1


if __name__ == "__main__":
    sys.exit(main())
