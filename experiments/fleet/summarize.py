#!/usr/bin/env python3
"""Aggregate fleet results (results_*.json) across repetitions: mean and
min-max per scenario and fleet size. Writes summary.json and prints the
rows used in the paper's fleet table."""
import glob
import json
import statistics as st
from pathlib import Path

HERE = Path(__file__).resolve().parent
runs = [json.loads(Path(f).read_text()) for f in sorted(glob.glob(str(HERE / "results_F*.json")))]
rows = {}
for r in runs:
    for lv in r["levels"]:
        rows.setdefault((lv["scenario"], lv["n"]), []).append(lv)

summary = []
print(f"{len(runs)} repetitions")
print(f"{'scenario':12}{'N':>3} {'committed':>10} {'job/s mean (min-max)':>24} {'p50 ms':>8} {'p95 ms':>8} {'att/job':>8} {'farm ok':>8}")
for (scen, n), L in sorted(rows.items()):
    g = [x["goodput_jobs_per_s"] for x in L]
    p50 = st.mean(x["latency_ms"]["p50"] for x in L)
    p95 = st.mean(x["latency_ms"]["p95"] for x in L)
    att = st.mean(x["attempts_per_job"] for x in L)
    committed = sum(x["committed"] for x in L); jobs = sum(x["jobs"] for x in L)
    farm_ok = all(x["shared_operator"]["total_events"] == x["committed"] for x in L) if scen == "shared" else None
    summary.append({"scenario": scen, "n": n, "reps": len(L), "jobs": jobs, "committed": committed,
                    "goodput_mean": st.mean(g), "goodput_min": min(g), "goodput_max": max(g),
                    "p50_ms_mean": p50, "p95_ms_mean": p95, "attempts_per_job_mean": att,
                    "mvcc_conflicts": sum(x["mvcc_conflicts"] for x in L),
                    "endorsement_mismatches": sum(x["endorsement_mismatches"] for x in L),
                    "farm_counter_exact": farm_ok})
    print(f"{scen:12}{n:>3} {committed:>4}/{jobs:<5} {st.mean(g):>9.1f} ({min(g):.1f}-{max(g):.1f}) "
          f"{p50:>8.0f} {p95:>8.0f} {att:>8.2f} {str(farm_ok) if farm_ok is not None else '':>8}")
(HERE / "summary.json").write_text(json.dumps(summary, indent=2))
