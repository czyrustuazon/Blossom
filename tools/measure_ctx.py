"""
Measure coder llama-server VRAM and speed at different context sizes / KV cache types.

Usage: python tools/measure_ctx.py <ctx> <cache_type> [n_cpu_moe] [fill_tokens]
Runs llama-server on port 11500, reports GPU memory after load and after a long prompt.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXE = ROOT / "Brains" / "runtime" / "llama-server.exe"
MODEL = ROOT / "Brains" / "models" / "coding" / "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf"
PORT = 11500


def gpu_used_mib() -> int:
    out = subprocess.check_output(
        ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], text=True
    )
    return int(out.strip().splitlines()[0])


def post(path: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def healthy() -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    ctx = int(sys.argv[1])
    cache = sys.argv[2]
    n_cpu_moe = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    fill = int(sys.argv[4]) if len(sys.argv) > 4 else min(ctx - 2048, 100_000)
    base = gpu_used_mib()
    fit = os.getenv("MEASURE_FIT", "").strip()
    args = [
        str(EXE), "-m", str(MODEL), "--ctx-size", str(ctx),
        "--port", str(PORT), "--host", "127.0.0.1", "--jinja", "--flash-attn", "on",
        "-ctk", cache, "-ctv", cache, "-np", "1",
    ]
    if fit:
        # Let llama-server pick GPU layers / expert offload against free VRAM.
        args += ["--fit", "on", "--fit-target", fit]
    else:
        args += ["--n-gpu-layers", "999"]
    if n_cpu_moe:
        args += ["--n-cpu-moe", str(n_cpu_moe)]
    log = open(ROOT / "Mind" / f"measure-{ctx}-{cache}-{n_cpu_moe}.log", "w", encoding="utf-8")
    t0 = time.time()
    proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    result: dict = {"ctx": ctx, "cache": cache, "n_cpu_moe": n_cpu_moe, "baseline_mib": base}
    try:
        while not healthy():
            if proc.poll() is not None:
                result["error"] = f"exited {proc.returncode} during load"
                print(json.dumps(result))
                return
            if time.time() - t0 > 300:
                result["error"] = "load timeout"
                print(json.dumps(result))
                return
            time.sleep(1)
        result["load_s"] = round(time.time() - t0, 1)
        result["loaded_mib"] = gpu_used_mib() - base
        if result["loaded_mib"] + base > 23_000:
            # Near the 24 GB ceiling Windows spills to shared memory; keep the probe short.
            result["spill_risk"] = True
            fill = min(fill, 4000)
        # ~4 chars/token of varied filler so the tokenizer can't collapse it.
        words = [f"item{i} value{i % 97} note{i % 13}" for i in range(fill // 6)]
        prompt = " ".join(words)
        n_tok = len(post("/tokenize", {"content": prompt}, timeout=120)["tokens"])
        if n_tok > fill:
            prompt = prompt[: int(len(prompt) * fill / n_tok * 0.98)]
        t1 = time.time()
        r = post(
            "/completion",
            {"prompt": prompt + "\nSummarize the pattern in one sentence:", "n_predict": 64,
             "cache_prompt": False},
            timeout=1800,
        )
        timing = r.get("timings", {})
        result["prompt_tokens"] = timing.get("prompt_n")
        result["prompt_tok_s"] = round(timing.get("prompt_per_second", 0), 1)
        result["gen_tok_s"] = round(timing.get("predicted_per_second", 0), 1)
        result["request_s"] = round(time.time() - t1, 1)
        result["after_prompt_mib"] = gpu_used_mib() - base
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)[:300]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
