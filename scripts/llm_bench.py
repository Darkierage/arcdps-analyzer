"""Benchmark LLM debrief configs (prompt variant x model x temperature) against the analysis.

Each debrief is scored automatically (see wvw_analyzer/llm/scoring.py): it should keep the
static analyzer's ranking, carry its fixes, invent nothing, and stay short. Optional reference
points (data/llm_bench/reference.yaml) add a "matches a commander's take" score.

Usage:
  uv run python scripts/llm_bench.py prepare [--fights 30]        # pick fights, cache inputs
  uv run python scripts/llm_bench.py run --variants v1_json,v2_text --temps 0.3 \\
      [--models Qwen3-4B-Q4_K_M.gguf] [--server PATH] [--ngl 99] [--threads 8] [--repeats 1]
  uv run python scripts/llm_bench.py report [results.jsonl ...]

Everything is written to data/llm_bench/ (git-ignored: it contains player names).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import socket
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean

import httpx
import yaml

from wvw_analyzer import paths, tools
from wvw_analyzer.analysis import Skipped, analyze_file
from wvw_analyzer.config import Settings
from wvw_analyzer.llm import prompts
from wvw_analyzer.llm.scoring import reference_similarity, score

BENCH = paths.data_dir() / "llm_bench"
FIGHTS = BENCH / "fights.json"
REFERENCE = BENCH / "reference.yaml"
CLAUDE_REF = BENCH / "claude_reference.yaml"


def claude_refs() -> dict[str, str]:
    if not CLAUDE_REF.exists():
        return {}
    return yaml.safe_load(CLAUDE_REF.read_text(encoding="utf-8")) or {}


# ---- prepare ------------------------------------------------------------------------------------
def prepare(n: int, seed: int) -> None:
    corpus = sorted((paths.data_dir() / "dev_corpus").glob("*.json.gz"))
    rows = []
    for f in corpus:
        try:
            a = analyze_file(f, Settings())
        except Skipped:
            continue
        players = [p["name"] for p in a.stats["players"]]
        rows.append({"id": a.summary["logId"], "summary": a.summary, "notes": a.notes,
                     "players": players})
    by_result = defaultdict(list)
    for r in rows:
        by_result[r["summary"]["result"]].append(r)
    rng = random.Random(seed)
    # Losses and even fights matter most for a debrief; fill the rest with wins and skirmishes.
    quota = {"loss": n * 2 // 5, "even": n // 10, "win": n * 2 // 5, "skirmish": n // 10}
    picked = []
    for res, k in quota.items():
        pool = by_result.get(res, [])
        picked += rng.sample(pool, min(k, len(pool)))
    rest = [r for r in rows if r not in picked]
    picked += rng.sample(rest, max(0, min(n - len(picked), len(rest))))
    picked.sort(key=lambda r: r["id"])
    BENCH.mkdir(parents=True, exist_ok=True)
    FIGHTS.write_text(json.dumps(picked, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = defaultdict(int)
    for r in picked:
        counts[r["summary"]["result"]] += 1
    print(f"{len(picked)} fights -> {FIGHTS} ({dict(counts)})")


# ---- llama-server -------------------------------------------------------------------------------
class Server:
    def __init__(self, binary: Path, model: Path, ngl: int, threads: int, ctx: int = 8192):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.cmd = [str(binary), "-m", str(model), "--host", "127.0.0.1", "--port",
                    str(self.port), "-ngl", str(ngl), "-t", str(threads), "-c", str(ctx),
                    "--no-webui"]
        self.proc: subprocess.Popen | None = None

    def __enter__(self) -> Server:
        self.proc = subprocess.Popen(self.cmd, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
        for _ in range(600):
            if self.proc.poll() is not None:
                raise RuntimeError(f"llama-server exited ({self.proc.returncode}): {self.cmd}")
            try:
                if httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=2).status_code == 200:
                    return self
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        raise RuntimeError("llama-server not ready")

    def __exit__(self, *exc) -> None:
        if self.proc:
            self.proc.terminate()
            self.proc.wait(timeout=20)

    def chat(self, msgs: list[dict], temperature: float, max_tokens: int, seed: int
             ) -> tuple[str, float, int]:
        t0 = time.perf_counter()
        r = httpx.post(f"http://127.0.0.1:{self.port}/v1/chat/completions", timeout=900, json={
            "messages": msgs, "temperature": temperature, "max_tokens": max_tokens,
            "seed": seed, "chat_template_kwargs": {"enable_thinking": False}})
        r.raise_for_status()
        d = r.json()
        text = d["choices"][0]["message"]["content"] or ""
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return text, time.perf_counter() - t0, int(d.get("usage", {}).get("completion_tokens", 0))


# ---- run ----------------------------------------------------------------------------------------
def run(args: argparse.Namespace) -> Path:
    fights = json.loads(FIGHTS.read_text(encoding="utf-8"))
    if args.limit:
        fights = fights[: args.limit]
    refs = yaml.safe_load(REFERENCE.read_text(encoding="utf-8")) if REFERENCE.exists() else {}
    refs = refs or {}
    binary = Path(args.server) if args.server else tools.llama_server_path()
    if not binary or not binary.exists():
        sys.exit("llama-server not found (scripts/setup_tools.py --llm, or --server PATH)")
    out = BENCH / f"results-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    variants = args.variants.split(",")
    temps = [float(t) for t in args.temps.split(",")]
    total = len(args.models.split(",")) * len(variants) * len(temps) * len(fights) * args.repeats
    done = 0
    with out.open("w", encoding="utf-8") as fh:
        for model_name in args.models.split(","):
            model = tools.model_path(model_name)
            if not model.exists():
                print(f"skip {model_name}: not downloaded")
                continue
            with Server(binary, model, args.ngl, args.threads) as srv:
                for variant in variants:
                    for temp in temps:
                        for rep in range(args.repeats):
                            for f in fights:
                                msgs, user = prompts.messages(variant, f["summary"], f["notes"])
                                text, secs, toks = srv.chat(msgs, temp, args.max_tokens,
                                                            seed=rep)
                                text = prompts.finalize(variant, f["summary"], text, f["notes"])
                                sc = score(text, user, f["summary"], f["notes"], f["players"],
                                           refs.get(f["id"]))
                                fh.write(json.dumps({
                                    "model": model_name, "variant": variant, "temp": temp,
                                    "rep": rep, "fight": f["id"],
                                    "result": f["summary"]["result"], "secs": round(secs, 2),
                                    "tokens": toks, "text": text, "score": sc.as_dict(),
                                }, ensure_ascii=False) + "\n")
                                fh.flush()
                                done += 1
                                print(f"[{done}/{total}] {model_name} {variant} t={temp} "
                                      f"{f['id']}: {sc.total:.0f} ({secs:.1f}s)", flush=True)
    print(f"results -> {out}")
    return out


# ---- report -------------------------------------------------------------------------------------
METRICS = ["similarity", "total", "top1_first", "top1_mentioned", "top_recall", "fix_coverage",
           "format_ok", "result_ok", "reference"]


def rescore(rows: list[dict]) -> None:
    """Recompute scores from the saved texts, so scorer changes apply without rerunning models."""
    fights = {f["id"]: f for f in json.loads(FIGHTS.read_text(encoding="utf-8"))}
    refs = {}
    cref = claude_refs()
    if REFERENCE.exists():
        refs = yaml.safe_load(REFERENCE.read_text(encoding="utf-8")) or {}
    for r in rows:
        f = fights.get(r["fight"])
        if not f or r["variant"] not in prompts.VARIANTS:
            continue
        _, user = prompts.messages(r["variant"], f["summary"], f["notes"])
        r["score"] = score(r["text"], user, f["summary"], f["notes"], f["players"],
                           refs.get(f["id"])).as_dict()
        ref = cref.get(f["id"])
        r["score"]["similarity"] = reference_similarity(r["text"], ref) if ref else None


def load_judgments() -> dict[tuple[str, str, str, float], float]:
    """(results file, variant, fight, temp) -> Claude's grade out of 10 (judgments-*.yaml)."""
    out: dict[tuple[str, str, str, float], float] = {}
    for f in sorted(BENCH.glob("judgments-*.yaml")):
        data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        results = data.pop("results", None)
        temp = float(data.pop("temp", 0.1))
        if not results:
            continue  # grades must say which run they belong to
        for variant, fights in data.items():
            for fight, g in (fights or {}).items():
                out[(results, variant, str(fight), temp)] = float(
                    sum(g.get(k, 0) for k in ("faith", "rank", "fixes", "tone")))
    return out


def sheet(file: Path, variants: list[str], temp: float, fights_filter: list[str] | None) -> Path:
    """Side-by-side judging sheet: input, Claude reference and each variant's output."""
    rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line]
    fights = {f["id"]: f for f in json.loads(FIGHTS.read_text(encoding="utf-8"))}
    cref = claude_refs()
    by = {(r["variant"], r["fight"]): r for r in rows if r["temp"] == temp and r["rep"] == 0}
    out = [f"# Judging sheet ({file.name}, temp {temp})", ""]
    for fid, f in fights.items():
        if fights_filter and fid not in fights_filter:
            continue
        out += [f"## {fid} ({f['summary']['result']})", "", "Problems in the analysis:"]
        out += [f"{i}. [{x['severity']}] {x['title']}" for i, x in
                enumerate(f["notes"]["issues"][:3], 1)] or ["(none)"]
        out += [f"+ {x['title']}" for x in f["notes"]["positives"]]
        out += ["", "**Claude reference**", "```", (cref.get(fid) or "(none)").strip(), "```"]
        for v in variants:
            r = by.get((v, fid))
            out += ["", f"**{v}**", "```", r["text"] if r else "(missing)", "```"]
        out.append("")
    path = BENCH / f"sheet-{file.stem}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def report(files: list[Path]) -> str:
    rows = []
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append({**json.loads(line), "file": f.name})
    rescore(rows)
    judged = load_judgments()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["model"], r["variant"], r["temp"])].append(r)
    header = ("| model | prompt | temp | n | judge /10 | vs Claude | score | #1 first | #1 named | "
              "top-3 recall | fixes | "
              "format | result | reference | went well | padded | invented nums | "
              "invented names | words | sec |")
    lines = [header, "|" + "---|" * 20]
    ranked = []
    for key, rs in groups.items():
        def m(metric: str, rs=rs) -> float | None:
            vals = [r["score"][metric] for r in rs if r["score"][metric] is not None]
            return mean(float(v) for v in vals) if vals else None

        inv_n = mean(len(r["score"]["invented_numbers"]) > 0 for r in rs)
        inv_p = mean(len(r["score"]["invented_names"]) > 0 for r in rs)
        ranked.append((m("total"), key, rs, m, inv_n, inv_p))
    ranked.sort(key=lambda x: -(x[0] or 0))
    for total, (model, variant, temp), rs, m, inv_n, inv_p in ranked:
        def pct(v):
            return "–" if v is None else f"{100 * v:.0f}%"
        jv = [judged[k] for r in rs
              if (k := (r["file"], variant, r["fight"], r["temp"])) in judged and r["rep"] == 0]
        jtxt = f"**{mean(jv):.1f}** ({len(jv)})" if jv else "–"
        sim = m("similarity")
        lines.append(
            f"| {model.replace('.gguf', '')} | {variant} | {temp} | {len(rs)} | {jtxt} | "
            f"{pct(sim)} | {total:.1f} | "
            f"{pct(m('top1_first'))} | {pct(m('top1_mentioned'))} | {pct(m('top_recall'))} | "
            f"{pct(m('fix_coverage'))} | {pct(m('format_ok'))} | {pct(m('result_ok'))} | "
            f"{pct(m('reference'))} | {pct(m('positives_ok'))} | {pct(m('padded'))} | "
            f"{pct(inv_n)} | {pct(inv_p)} | "
            f"{mean(r['score']['words'] for r in rs):.0f} | {mean(r['secs'] for r in rs):.1f} |")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--fights", type=int, default=30)
    p.add_argument("--seed", type=int, default=7)
    r = sub.add_parser("run")
    r.add_argument("--variants", default=",".join(prompts.VARIANTS))
    r.add_argument("--temps", default="0.3")
    r.add_argument("--models", default="Qwen3-4B-Q4_K_M.gguf")
    r.add_argument("--server")
    r.add_argument("--ngl", type=int, default=0)
    r.add_argument("--threads", type=int, default=8)
    r.add_argument("--repeats", type=int, default=1)
    r.add_argument("--max-tokens", type=int, default=450)
    r.add_argument("--limit", type=int, default=0)
    rp = sub.add_parser("report")
    rp.add_argument("files", nargs="*")
    sh = sub.add_parser("sheet")
    sh.add_argument("file")
    sh.add_argument("--variants", default="")
    sh.add_argument("--temp", type=float, default=0.1)
    sh.add_argument("--fights", default="")
    args = ap.parse_args()

    if args.cmd == "prepare":
        prepare(args.fights, args.seed)
    elif args.cmd == "run":
        out = run(args)
        print(report([out]))
    elif args.cmd == "sheet":
        f = Path(args.file)
        variants = args.variants.split(",") if args.variants else sorted(
            {json.loads(line)["variant"] for line in f.read_text(encoding="utf-8").splitlines()})
        print(sheet(f, variants, args.temp, args.fights.split(",") if args.fights else None))
    else:
        files = [Path(f) for f in args.files] or sorted(BENCH.glob("results-*.jsonl"))[-1:]
        print(report(files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
