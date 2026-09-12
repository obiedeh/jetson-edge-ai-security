#!/usr/bin/env python3
"""Summarise repeated, alternated thread-pool runs as distributions, not point estimates.

Input: a directory of ``run<i>_<default|single>.json`` artifacts from
``run_benchmark.py`` (same device, same tier), plus optional ``cooldown.jsonl``
and ``system_snapshot_*.txt`` written by the orchestrator. Output: a JSON
summary with, per model at the chosen tier, the per-run values, median and
range for each configuration, the paired differences (default minus single
for consecutive pairs in run order), their median and range, and a verdict:
whether the two configurations' ranges overlap on board power.

    python deploy/thor/analyze_thread_repeats.py --dir reports/thor_threads_repeats --tier 1000
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path
from typing import Any

METRICS = {
    "vin_p50_mw": ("tegrastats", "rails_mw", "VIN", "p50"),
    "vin_peak_mw": ("tegrastats", "rails_mw", "VIN", "peak"),
    "cpu_rail_p50_mw": ("tegrastats", "rails_mw", "VDD_CPU_SOC_MSS", "p50"),
    "p95_ms": ("p95_ms",),
    "p50_ms": ("p50_ms",),
    "deadline_misses": ("deadline_misses",),
    "tj_peak_c": ("tegrastats", "temps_c", "tj", "peak"),
}


def _get(d: Any, path: tuple[str, ...]) -> Any:
    for k in path:
        if not isinstance(d, dict) or k not in d:
            return None
        d = d[k]
    return d


def _dist(values: list[float]) -> dict[str, Any]:
    clean = [v for v in values if v is not None]
    if not clean:
        return {"n": 0}
    return {
        "n": len(clean),
        "values": clean,
        "median": statistics.median(clean),
        "min": min(clean),
        "max": max(clean),
        "range": max(clean) - min(clean),
    }


def load_runs(directory: Path) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(directory.glob("run*_*.json"), key=lambda p: int(re.match(r"run(\d+)_", p.name).group(1))):
        m = re.match(r"run(\d+)_(default|single)\.json", path.name)
        if not m:
            continue
        data = json.loads(path.read_text())
        runs.append({"index": int(m.group(1)), "config": m.group(2), "path": path.name, "data": data})
    return runs


def summarize(runs: list[dict[str, Any]], tier: float) -> dict[str, Any]:
    if not runs:
        raise SystemExit("no run artifacts found")
    models = [m["model"] for m in runs[0]["data"]["models"]]
    out: dict[str, Any] = {
        "schema": "thread-repeats-v1",
        "tier_rps": tier,
        "run_order": [f"run{r['index']}_{r['config']}" for r in runs],
        "n_runs": {c: sum(1 for r in runs if r["config"] == c) for c in ("default", "single")},
        "duration_per_tier_s": runs[0]["data"].get("duration_per_tier_s"),
        "hardware": runs[0]["data"].get("hardware"),
        "session_options": {c: next(r["data"]["session_options"] for r in runs if r["config"] == c) for c in ("default", "single")},
        "idle_before_each_run_vin_p50_mw": {
            f"run{r['index']}_{r['config']}": _get(r["data"], ("idle_baseline", "before_load", "rails_mw", "VIN", "p50")) for r in runs
        },
        "models": {},
    }
    for model in models:
        per_cfg: dict[str, dict[str, list[float]]] = {"default": {k: [] for k in METRICS}, "single": {k: [] for k in METRICS}}
        per_run: list[dict[str, Any]] = []
        for r in runs:
            mrec = next(m for m in r["data"]["models"] if m["model"] == model)
            trec = next((t for t in mrec["tiers"] if t.get("target_rps") == tier), None)
            row = {"run": f"run{r['index']}_{r['config']}", "config": r["config"], "provider": mrec.get("provider")}
            for k, path in METRICS.items():
                v = _get(trec, path) if trec else None
                row[k] = v
                per_cfg[r["config"]][k].append(v)
            per_run.append(row)
        # consecutive default/single pairs in run order
        pairs = []
        seq = [row for row in per_run]
        for a, b in zip(seq, seq[1:], strict=False):
            if a["config"] == "default" and b["config"] == "single":
                pairs.append((a, b))
        deltas = {k: _dist([a[k] - b[k] for a, b in pairs if a[k] is not None and b[k] is not None]) for k in METRICS}
        d, s = _dist(per_cfg["default"]["vin_p50_mw"]), _dist(per_cfg["single"]["vin_p50_mw"])
        overlap = None
        if d.get("n") and s.get("n"):
            overlap = not (d["min"] > s["max"] or s["min"] > d["max"])
        out["models"][model] = {
            "per_run": per_run,
            "default": {k: _dist(v) for k, v in per_cfg["default"].items()},
            "single": {k: _dist(v) for k, v in per_cfg["single"].items()},
            "paired_delta_default_minus_single": deltas,
            "n_pairs": len(pairs),
            "vin_p50_ranges_overlap": overlap,
            "verdict": (
                "not assessable" if overlap is None else
                "ranges overlap: no power gap is claimed" if overlap else
                f"ranges separated: median gap {deltas['vin_p50_mw'].get('median')} mW, spread {deltas['vin_p50_mw'].get('min')} to {deltas['vin_p50_mw'].get('max')} mW over {len(pairs)} pairs"
            ),
        }
    return out


def attach_context(summary: dict[str, Any], directory: Path) -> None:
    cd = directory / "cooldown.jsonl"
    if cd.exists():
        recs = [json.loads(line) for line in cd.read_text().splitlines() if line.strip()]
        summary["cooldown"] = {
            "windows": len(recs),
            "settled_before_each_run": {r["tag"]: r["settled"] for r in recs if r.get("settled")},
            "unsettled_tags": sorted({r["tag"] for r in recs} - {r["tag"] for r in recs if r.get("settled")}),
            "last_window_per_tag": {r["tag"]: {k: r[k] for k in ("vin_p50_mw", "tj_max_c", "cpu_max_c", "settled")} for r in recs},
        }
    snaps = sorted(directory.glob("system_snapshot_*.txt"))
    if snaps:
        summary["other_processes_before_each_run"] = {
            p.stem.replace("system_snapshot_", ""): p.read_text().strip().splitlines()[-5:] for p in snaps
        }
    sess = directory / "session.txt"
    if sess.exists():
        summary["session"] = sess.read_text().strip().splitlines()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, required=True)
    ap.add_argument("--tier", type=float, default=1000.0)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()
    runs = load_runs(args.dir)
    summary = summarize(runs, args.tier)
    attach_context(summary, args.dir)
    out = args.output or args.dir / "summary.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    for model, m in summary["models"].items():
        d, s = m["default"]["vin_p50_mw"], m["single"]["vin_p50_mw"]
        print(f"{model}: default VIN p50 {d.get('values')} median {d.get('median')} | single {s.get('values')} median {s.get('median')} | {m['verdict']}")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
