"""
Run eval tasks through the REAL Blossom Assistant extension (not the agent_loop.py replica).

Each run copies a task's project into a fresh folder, opens it in a new VS Code window with
the extension's debug MCP server on (blossom.debug.mcpServer) and the router pointed at the
isolated test router, sends the task prompt through the chat panel's own code path, waits
for the turn, saves the Blossom Trace, scores the workspace with the task's checks
(hidden acceptance copied in as _acceptance/ only for scoring), and closes the window.

  python run_vscode.py --task php-modernize --runs 3 --out <dir>
  (router URL from --router-url or BLOSSOM_EVAL_CHAT_URL; never the real :8083 router —
  it writes coding lessons into Blossom's real memory)

The workspace parent (--ws-root) must be trusted in VS Code once ("Trust the parent folder"),
or the extension is disabled in Restricted Mode.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from blossom_eval.corpus import load_corpus  # noqa: E402
from blossom_eval.scorers import run_check  # noqa: E402

DISCOVERY_DIR = Path.home() / ".blossom" / "mcp"


class Mcp:
    def __init__(self, url: str):
        self.url = url
        self._id = 0

    def _post(self, payload: dict, timeout: float) -> dict | None:
        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
        return json.loads(body) if body else None

    def initialize(self) -> dict:
        self._id += 1
        r = self._post({"jsonrpc": "2.0", "id": self._id, "method": "initialize",
                        "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "blossom-eval", "version": "1"}}}, 15)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, 15)
        return r["result"]

    def call(self, name: str, args: dict | None = None, timeout: float = 30) -> str:
        self._id += 1
        r = self._post({"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                        "params": {"name": name, "arguments": args or {}}}, timeout)
        if "error" in r:
            raise RuntimeError(f"{name}: {r['error']}")
        text = "".join(c.get("text", "") for c in r["result"].get("content", []))
        if r["result"].get("isError"):
            raise RuntimeError(f"{name}: {text}")
        return text


def find_window(ws: Path, since: float, timeout: float = 180) -> str:
    want = str(ws.resolve()).lower()
    deadline = time.time() + timeout
    while time.time() < deadline:
        for f in DISCOVERY_DIR.glob("*.json"):
            try:
                info = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            folders = [str(Path(p).resolve()).lower() for p in info.get("workspaceFolders", [])]
            if want in folders and f.stat().st_mtime >= since - 2:
                return info["url"]
        time.sleep(1)
    raise TimeoutError(f"no Blossom debug MCP server for {ws} after {timeout}s "
                       "(window not open, extension disabled in Restricted Mode, or old extension)")


def prepare_workspace(task, ws: Path, router_url: str, port: int, extra: dict | None = None) -> None:
    if ws.exists():
        shutil.rmtree(ws)
    shutil.copytree(task.project_path, ws)
    (ws / ".vscode").mkdir(exist_ok=True)
    (ws / ".vscode" / "settings.json").write_text(json.dumps({
        "blossom.debug.mcpServer": True,
        "blossom.debug.mcpPort": port,
        "blossom.api.baseUrl": router_url,
        "blossom.ollama.baseUrl": router_url,
        "blossom.commands.askBeforeRun": False,
        "blossom.edits.autoApply": True,
        **(extra or {}),
    }, indent=2), encoding="utf-8")


def parse_settings(pairs: list[str] | None) -> dict:
    """--set blossom.agent.leanPrompt=true → {"blossom.agent.leanPrompt": True} (JSON values)."""
    out: dict = {}
    for pair in pairs or []:
        key, _, raw = pair.partition("=")
        try:
            out[key.strip()] = json.loads(raw)
        except json.JSONDecodeError:
            out[key.strip()] = raw
    return out


def run_one(task, run_name: str, args) -> dict:
    ws = Path(args.ws_root) / f"{task.id}-{run_name}"
    out = Path(args.out) / run_name / task.id
    out.mkdir(parents=True, exist_ok=True)
    prepare_workspace(task, ws, args.router_url, args.port, parse_settings(args.set))

    started = time.time()
    subprocess.Popen(f'code --new-window "{ws}"', shell=True)
    url = find_window(ws, started)
    mcp = Mcp(url)
    mcp.initialize()
    info = json.loads(mcp.call("blossom_info"))
    print(f"  [{task.id}] window up: v{info['version']} backend={info.get('apiBaseUrl')}", flush=True)
    if "8083" in str(info.get("apiBaseUrl")):
        mcp.call("blossom_close_window")
        raise RuntimeError("window is pointed at the real :8083 router; refusing to run")

    time.sleep(args.settle)  # let repo knowledge index the project
    try:
        seq_before = max((r["seq"] for r in json.loads(mcp.call("blossom_rounds"))), default=0)
    except Exception:  # noqa: BLE001 — older extension
        seq_before = 0
    sent = json.loads(mcp.call("blossom_send", {"prompt": task.prompt, "newChat": True}, timeout=30))
    deadline = time.time() + args.timeout_min * 60
    summary: dict = {}
    answered: list[str] = []
    while True:
        summary = json.loads(mcp.call("blossom_wait", {"timeoutSec": 240}, timeout=300))
        print(f"  [{task.id}] {summary['state']} {summary['elapsedSec']}s rounds={summary['rounds']} "
              f"edits={len(summary['editsApplied'])} last={summary['lastStatus'][:70]!r}", flush=True)
        if summary["state"] == "finished":
            break
        for p in summary.get("pending", []):
            decision = {"command": "run", "step": "continue", "ask": "skip"}[p["kind"]]
            if p["kind"] == "ask" and p["text"].startswith("That's the plan"):
                decision = "0"  # plan card: Approve — implement the plan
            mcp.call("blossom_respond", {"kind": p["kind"], "id": p["id"], "decision": decision})
            answered.append(f"{p['kind']} {p['id']} -> {decision}: {p['text'][:120]}")
        if time.time() > deadline:
            mcp.call("blossom_cancel")
            time.sleep(5)
            summary = json.loads(mcp.call("blossom_status"))
            summary["outcome"] = f"eval-timeout ({args.timeout_min} min)"
            break

    trace = mcp.call("blossom_trace", {"afterSeq": max(0, summary.get("traceStartSeq", 1) - 1), "limit": 5000})
    (out / "trace.log").write_text(trace, encoding="utf-8")
    # Every round's full prompt + reasoning + reply (extension >= 0.1.75).
    try:
        index = json.loads(mcp.call("blossom_rounds", {"sinceSeq": seq_before}))
        for n, row in enumerate(index, 1):
            (out / f"round-{n:02d}.md").write_text(mcp.call("blossom_rounds", {"seq": row["seq"]}, timeout=60),
                                                  encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — older extension without blossom_rounds
        print(f"  [{task.id}] rounds not saved: {exc}", flush=True)
    (out / "summary.json").write_text(json.dumps({**summary, "answered": answered, "turn": sent}, indent=2),
                                      encoding="utf-8")
    try:
        mcp.call("blossom_close_window")
    except Exception:  # noqa: BLE001 — the window may already be gone
        pass

    # Score: hidden acceptance copied in only now.
    if task.hidden_path and task.hidden_path.is_dir():
        shutil.copytree(task.hidden_path, ws / "_acceptance", dirs_exist_ok=True)
    results = [run_check(c, work_dir=ws, response_text=summary.get("finalText") or "") for c in task.checks]
    passed = all(r.passed for r in results)
    detail = {r.check_id: {"passed": r.passed, "detail": r.detail[-3000:]} for r in results}
    (out / "score.json").write_text(json.dumps({"passed": passed, "checks": detail}, indent=2), encoding="utf-8")
    shutil.rmtree(ws / "_acceptance", ignore_errors=True)
    return {"task": task.id, "run": run_name, "settings": parse_settings(args.set),
            "passed": passed, "outcome": summary.get("outcome"),
            "rounds": summary.get("rounds"), "elapsedSec": summary.get("elapsedSec"),
            "editsApplied": summary.get("editsApplied"), "workspace": str(ws)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", default="project-refactor")
    ap.add_argument("--task", action="append", help="task id (repeatable; default all)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ws-root", default=str(Path.home() / "Documents" / "blossom-eval-runs"))
    ap.add_argument("--router-url", default=os.getenv("BLOSSOM_EVAL_CHAT_URL", ""))
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--timeout-min", type=float, default=30)
    ap.add_argument("--settle", type=float, default=8)
    ap.add_argument("--name", default="r", help="run name prefix")
    ap.add_argument("--set", action="append", metavar="KEY=JSON",
                    help="extra workspace setting for the eval window (repeatable), e.g. "
                         "blossom.agent.leanPrompt=true")
    args = ap.parse_args()
    if not args.router_url or ":8083" in args.router_url:
        print("Set --router-url / BLOSSOM_EVAL_CHAT_URL to the isolated test router (not :8083).")
        return 2

    corpus = load_corpus(Path(__file__).resolve().parent / "corpora" / args.corpus)
    tasks = [t for t in corpus.tasks if not args.task or t.id in args.task]
    Path(args.ws_root).mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(1, args.runs + 1):
        for task in tasks:
            name = f"{args.name}{i}"
            print(f"== {name} {task.id}", flush=True)
            try:
                row = run_one(task, name, args)
            except Exception as exc:  # noqa: BLE001 — record and move on
                row = {"task": task.id, "run": name, "passed": False, "outcome": f"driver error: {exc}"}
            rows.append(row)
            print(f"  -> {'PASS' if row['passed'] else 'FAIL'} {row.get('outcome')}", flush=True)
            with open(Path(args.out) / "results.jsonl", "a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
    n = sum(r["passed"] for r in rows)
    print(f"\n{n}/{len(rows)} passed")
    return 0 if n == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
