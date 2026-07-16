#!/usr/bin/env python3
"""
generate_figures.py -- publication-ready PDF figures from REAL bridge data.

Figures (IEEE two-column styling, vector PDF, serif/Times, 8-9pt):
  1. thermal_trace.pdf        -- nozzle/bed temperature trace from a capture log
  2. reputation_evolution.pdf -- Beta posterior narrowing across successive jobs
  3. assessment_comparison.pdf-- per-run quality/compliance/delivery/rating bars

Everything plotted comes from captured telemetry or signed bundles; no synthetic
numbers are introduced in this script.

Usage:
  python3 generate_figures.py --capture capture_log.jsonl --bundles signed_bundle.json
  python3 generate_figures.py --captures capture_*.jsonl --bundles bundle_*.json
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # headless: write files, never open a window
import matplotlib.pyplot as plt

FIG_DIR = Path("figures")
COL_1 = 3.5     # IEEE single-column width (inches)
COL_2 = 7.16    # IEEE double-column width (inches)


def ieee_style():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "legend.fontsize": 7,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "axes.linewidth": 0.6,
        "lines.linewidth": 1.0,
        "figure.dpi": 150,
        "savefig.dpi": 300,
        "pdf.fonttype": 42,   # embed TrueType so reviewers' viewers render text
    })


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------
def load_capture(path: str) -> list:
    rows = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def load_bundle(path: str) -> dict:
    return json.loads(Path(path).read_text())


def is_printing(state) -> bool:
    return "printing" in (state or "").lower()


# ---------------------------------------------------------------------------
# Figure 1 -- thermal trace
# ---------------------------------------------------------------------------
def fig_thermal_trace(capture_path: str, target_nozzle=200.0, target_bed=50.0):
    rows = load_capture(capture_path)
    if not rows:
        print(f"[fig1] no rows in {capture_path}; skipped")
        return
    t0 = rows[0]["t"]
    secs = [r["t"] - t0 for r in rows]
    nozzle = [r.get("nozzle_c") for r in rows]
    bed = [r.get("bed_c") for r in rows]

    printing_secs = [s for s, r in zip(secs, rows) if is_printing(r.get("state"))]
    p_start = printing_secs[0] if printing_secs else None
    p_end = printing_secs[-1] if printing_secs else None

    fig, ax = plt.subplots(figsize=(COL_1, 2.4))
    ax.plot(secs, nozzle, linestyle="-", color="black", label="Nozzle")
    ax.plot(secs, bed, linestyle="--", color="black", label="Bed")

    ax.axhline(target_nozzle, linestyle=":", color="0.45", linewidth=0.8)
    ax.axhline(target_bed, linestyle=":", color="0.45", linewidth=0.8)
    ax.text(secs[-1], target_nozzle + 3, f"target {target_nozzle:.0f}°C",
            ha="right", va="bottom", fontsize=6, color="0.3")
    ax.text(secs[-1], target_bed + 3, f"target {target_bed:.0f}°C",
            ha="right", va="bottom", fontsize=6, color="0.3")

    if p_start is not None:
        ax.axvline(p_start, linestyle="--", color="0.6", linewidth=0.8)
        ax.text(p_start, ax.get_ylim()[1], "print start", rotation=90,
                va="top", ha="right", fontsize=6, color="0.3")
    if p_end is not None and p_end != p_start:
        ax.axvline(p_end, linestyle="--", color="0.6", linewidth=0.8)
        ax.text(p_end, ax.get_ylim()[1], "print end", rotation=90,
                va="top", ha="right", fontsize=6, color="0.3")

    ax.set_xlabel("Time since first sample (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.legend(loc="center right", frameon=False)
    ax.margins(x=0.01)
    fig.tight_layout()
    out = FIG_DIR / "thermal_trace.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"[fig1] wrote {out}  ({len(rows)} samples)")


# ---------------------------------------------------------------------------
# Figure 2 -- reputation posterior evolution
# ---------------------------------------------------------------------------
def _beta_pdf(x, a, b):
    # Beta(a,b) density via log-gamma; avoids a scipy hard-dependency.
    if x <= 0 or x >= 1:
        return 0.0
    log_b = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    return math.exp((a - 1) * math.log(x) + (b - 1) * math.log(1 - x) - log_b)


def _wilson_ci(successes, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    phat = successes / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


def fig_reputation_evolution(bundle_paths: list, prior_a=2.0, prior_b=2.0):
    if not bundle_paths:
        print("[fig2] no bundles; skipped")
        return
    fig, ax = plt.subplots(figsize=(COL_1, 2.6))
    xs = [i / 400.0 for i in range(1, 400)]

    a, b = prior_a, prior_b
    cum_hits = cum_total = 0
    styles = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]

    # prior curve for reference
    ax.plot(xs, [_beta_pdf(x, a, b) for x in xs], color="0.7",
            linewidth=0.8, label=f"prior Beta({prior_a:.0f},{prior_b:.0f})")

    for i, bp in enumerate(bundle_paths):
        bundle = load_bundle(bp)
        asm = bundle["payload"]["assessment"]
        hits = int(asm.get("thermal_samples_in_tol", 0))
        total = int(asm.get("thermal_samples_total", 0))
        a += hits
        b += (total - hits)
        cum_hits += hits
        cum_total += total
        score = a / (a + b)
        lo, hi = _wilson_ci(cum_hits, cum_total)

        label = (f"after job {i+1}: score={score:.3f} "
                 f"CI[{lo:.2f},{hi:.2f}]")
        ax.plot(xs, [_beta_pdf(x, a, b) for x in xs], color="black",
                linestyle=styles[i % len(styles)], label=label)
        ax.axvline(score, color="0.5", linestyle=":", linewidth=0.5)

    ax.set_xlabel("Reputation score (Beta posterior support)")
    ax.set_ylabel("Posterior density")
    ax.legend(loc="upper left", frameon=False)
    ax.margins(x=0.01)
    fig.tight_layout()
    out = FIG_DIR / "reputation_evolution.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"[fig2] wrote {out}  ({len(bundle_paths)} bundles)")


# ---------------------------------------------------------------------------
# Figure 3 -- assessment comparison
# ---------------------------------------------------------------------------
def fig_assessment_comparison(bundle_paths: list):
    if not bundle_paths:
        print("[fig3] no bundles; skipped")
        return
    dims = ["quality", "compliance", "delivery", "rating_value"]
    hatches = ["", "//", "..", "xx"]
    grays = ["0.2", "0.45", "0.65", "0.85"]

    labels, series = [], {d: [] for d in dims}
    for bp in bundle_paths:
        asm = load_bundle(bp)["payload"]["assessment"]
        labels.append(Path(bp).stem.replace("bundle_", "").replace("signed_", ""))
        for d in dims:
            series[d].append(float(asm.get(d, 0.0)))

    n = len(labels)
    width = 0.8 / len(dims)
    xbase = list(range(n))

    fig, ax = plt.subplots(figsize=(COL_2 if n > 2 else COL_1, 2.6))
    for j, d in enumerate(dims):
        offs = [x + (j - (len(dims) - 1) / 2) * width for x in xbase]
        ax.bar(offs, series[d], width=width, label=d, color=grays[j],
               edgecolor="black", linewidth=0.5, hatch=hatches[j])

    ax.set_xticks(xbase)
    ax.set_xticklabels(labels, rotation=0)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Score [0,1]")
    ax.legend(loc="lower right", frameon=False, ncol=2)
    fig.tight_layout()
    out = FIG_DIR / "assessment_comparison.pdf"
    fig.savefig(out)
    plt.close(fig)
    print(f"[fig3] wrote {out}  ({n} runs)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capture", default=None, help="single capture log for Fig.1")
    ap.add_argument("--captures", nargs="*", default=None,
                    help="multiple capture logs (Fig.1 uses the first)")
    ap.add_argument("--bundles", nargs="*", default=[], help="signed bundle files")
    ap.add_argument("--target-nozzle", type=float, default=200.0)
    ap.add_argument("--target-bed", type=float, default=50.0)
    args = ap.parse_args()

    FIG_DIR.mkdir(exist_ok=True)
    ieee_style()

    capture = args.capture
    if capture is None and args.captures:
        capture = args.captures[0]

    if capture:
        fig_thermal_trace(capture, args.target_nozzle, args.target_bed)
    else:
        print("[fig1] no --capture/--captures given; skipped")

    fig_reputation_evolution(args.bundles)
    fig_assessment_comparison(args.bundles)

    print(f"\nFigures written to {FIG_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
