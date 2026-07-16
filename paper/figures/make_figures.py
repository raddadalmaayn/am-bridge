#!/usr/bin/env python3
"""Generate the paper's data figures from the REAL captured telemetry.

Inputs (real experiment artifacts, not simulated), all under ../../ :
  capture_cube_done.jsonl, capture_cube_anomaly.jsonl, ...   OctoPrint traces
  bundle_*.json, signed_bundle.json                          signed bundles
  benchmark_results.json                                     100-iter timings

Outputs (PDF, referenced from sections/*.tex):
  fig_thermal_trace.pdf     anomaly run: nozzle/bed vs time, 215C window marked
  fig_beta_posterior.pdf    reputation evolution: score + Wilson CI over 5 events
  fig_bridge_latency.pdf    measured per-stage bridge latency (mean, P95 cap)
  fig_bundle_scaling.pdf    canonical bundle size vs samples; constant on-chain
"""
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent

plt.rcParams.update({
    "font.size": 8,
    "axes.labelsize": 8,
    "axes.titlesize": 8,
    "legend.fontsize": 7,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "figure.dpi": 150,
    "pdf.fonttype": 42,
})

FIGW = 3.45  # IEEE single column width in inches


def _load_capture(name):
    return [json.loads(l) for l in (ROOT / name).open()]


def thermal_trace():
    """The thermal-anomaly run: a +15C setpoint override is injected mid-print
    and recovered, visible as a clean excursion outside the tolerance band."""
    samples = _load_capture("capture_cube_anomaly.jsonl")
    t0 = samples[0]["t"]
    t = [s["t"] - t0 for s in samples]
    noz = [s["nozzle_c"] for s in samples]
    bed = [s["bed_c"] for s in samples]

    print_start = next(s["t"] - t0 for s in samples if s["state"] == "Printing")
    # anomaly window: samples whose nozzle target was raised to 215
    anom = [s["t"] - t0 for s in samples if s.get("nozzle_target") == 215.0]
    a_lo, a_hi = (min(anom), max(anom)) if anom else (None, None)

    fig, ax = plt.subplots(figsize=(FIGW, 1.7))
    ax.plot(t, noz, label="Nozzle (actual)", color="#c0392b", lw=1.2)
    ax.plot(t, bed, label="Bed (actual)", color="#2471a3", lw=1.2)
    ax.axhline(200, color="#c0392b", ls=":", lw=0.8, alpha=0.6)
    ax.axhline(50, color="#2471a3", ls=":", lw=0.8, alpha=0.6)
    # tolerance band on the nozzle target
    ax.axhspan(192, 208, color="#c0392b", alpha=0.06)
    ax.text(5, 209, "200±8°C tolerance", color="#c0392b", fontsize=6)
    ax.text(5, 54, "target 50°C", color="#2471a3", fontsize=6)
    ax.axvline(print_start, color="k", ls="--", lw=0.8)
    ax.annotate("print start", xy=(print_start, 150), fontsize=6.5,
                xytext=(print_start + 20, 120),
                arrowprops=dict(arrowstyle="->", lw=0.6))
    if a_lo is not None:
        ax.axvspan(a_lo, a_hi, color="#e67e22", alpha=0.15)
        ax.annotate("M104 S215\ninjected (60 s)", xy=((a_lo + a_hi) / 2, 216),
                    fontsize=6.5, ha="center",
                    xytext=((a_lo + a_hi) / 2, 244),
                    arrowprops=dict(arrowstyle="->", lw=0.6))
    ax.set_xlabel("Time since capture start (s)")
    ax.set_ylabel("Temperature (°C)")
    ax.set_ylim(0, 260)
    ax.legend(loc="center right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "fig_thermal_trace.pdf")
    plt.close(fig)
    print(f"thermal trace (anomaly): {len(samples)} samples, "
          f"print_start=t+{print_start}s, anomaly t+{a_lo}..{a_hi}s")


def _wilson(alpha, beta, z=1.96):
    """Wilson 95% interval as the chaincode computes it: n = alpha+beta,
    phat = alpha/n."""
    n = alpha + beta
    p = alpha / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return center - half, center + half


def beta_posterior():
    """Measured on-chain reputation evolution for operator-secnet (quality)
    across the five committed events. beta stays 2.0 (every rating >= 0.5),
    so alpha = 2*score/(1-score) recovers the posterior at each event."""
    # measured scores read off the ledger after each submission
    events = ["f4u2", "cube_done", "cube_anom", "cube_rep", "bracket"]
    scores = [0.5394, 0.5969, 0.6371, 0.6799, 0.7120]
    beta = 2.0
    los, his = [], []
    for s in scores:
        a = beta * s / (1 - s)
        lo, hi = _wilson(a, beta)
        los.append(lo); his.append(hi)

    x = list(range(1, len(scores) + 1))
    fig, ax = plt.subplots(figsize=(FIGW, 1.7))
    ax.fill_between(x, los, his, color="#1e8449", alpha=0.12,
                    label="95% Wilson CI")
    ax.plot(x, scores, "-o", color="#1e8449", lw=1.3, ms=3.5,
            label="Posterior score")
    ax.axhline(0.5, color="#7f8c8d", ls="--", lw=0.8)
    ax.text(1.05, 0.51, "prior mean 0.5", color="#7f8c8d", fontsize=6)
    for xi, s in zip(x, scores):
        ax.annotate(f"{s:.3f}", (xi, s), fontsize=5.8,
                    textcoords="offset points", xytext=(0, 5), ha="center")
    ax.set_xlabel("Committed events (totalEvents)")
    ax.set_ylabel("Reputation score")
    ax.set_xticks(x)
    ax.set_xticklabels([f"{i}\n{n}" for i, n in zip(x, events)], fontsize=5.6)
    ax.set_ylim(0, 1)
    ax.legend(loc="lower right", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "fig_beta_posterior.pdf")
    plt.close(fig)
    print(f"reputation evolution: score {scores[0]:.3f}->{scores[-1]:.3f}, "
          f"CI width {his[0]-los[0]:.3f}->{his[-1]-los[-1]:.3f}")


def bridge_latency():
    """Measured per-stage bridge latency (mean bar, P95 cap), averaged over the
    four PLA-profile runs (cube x3 + bracket). The f4u2 bundle is excluded from
    the parse bar only because its 5 MB G-code makes parse unrepresentative; we
    note that scaling in the text."""
    bench = json.loads((ROOT / "benchmark_results.json").read_text())
    runs = {r["bundle"]: r["latency"] for r in bench["results"]}
    pla = ["bundle_cube_done.json", "bundle_cube_anomaly.json",
           "bundle_cube_repeat.json", "bundle_bracket_done.json"]
    stages = ["parse_gcode_envelope", "build_payload", "canonical",
              "ed25519_sign", "off_chain_hash", "verify_bundle"]
    labels = ["parse", "build", "canon", "sign", "hash", "verify"]

    means, p95s = [], []
    for st in stages:
        ms = [runs[b][st]["mean_ms"] for b in pla]
        ps = [runs[b][st]["p95_ms"] for b in pla]
        means.append(sum(ms) / len(ms))
        p95s.append(max(ps))

    total_mean = sum(means)
    fig, ax = plt.subplots(figsize=(FIGW, 1.7))
    xs = range(len(labels))
    err = [p - m for m, p in zip(means, p95s)]
    ax.bar(xs, means, color="#34495e", width=0.62,
           yerr=[[0] * len(means), err], capsize=2.5,
           error_kw=dict(lw=0.7), label="mean (cap = P95)")
    for xi, m in zip(xs, means):
        ax.annotate(f"{m:.2f}", (xi, m), fontsize=5.8,
                    textcoords="offset points", xytext=(0, 9), ha="center")
    ax.set_xticks(list(xs))
    ax.set_xticklabels(labels)
    ax.set_ylabel("Latency (ms)")
    ax.set_title(f"Full attest pipeline {total_mean:.2f} ms mean "
                 f"(100 iters x 4 runs)", fontsize=6.8)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "fig_bridge_latency.pdf")
    plt.close(fig)
    print(f"latency: stages {dict(zip(labels, [round(m,3) for m in means]))}, "
          f"total mean {total_mean:.3f} ms")


def bundle_scaling():
    """Canonical bundle size grows with sample count; the on-chain footprint is
    constant at 369 B regardless. Five real runs."""
    bench = json.loads((ROOT / "benchmark_results.json").read_text())
    pts = [(r["sizes"]["n_samples"], r["sizes"]["canonical_json_bytes"] / 1024.0,
            r["bundle"]) for r in bench["results"]]
    onchain_kb = bench["results"][0]["sizes"]["onchain_footprint_bytes"] / 1024.0

    fig, ax = plt.subplots(figsize=(FIGW, 1.7))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    ax.scatter(xs, ys, color="#8e44ad", s=22, zorder=3,
               label="Canonical bundle (off-chain)")
    # linear fit through the points to show ~linear growth
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / \
        sum((x - mx) ** 2 for x in xs)
    a = my - b * mx
    xr = [min(xs), max(xs)]
    ax.plot(xr, [a + b * x for x in xr], color="#8e44ad", ls="--", lw=0.8,
            alpha=0.6)
    ax.axhline(onchain_kb, color="#16a085", lw=1.4,
               label=f"On-chain footprint ({onchain_kb*1024:.0f} B, constant)")
    ax.set_xlabel("Telemetry samples in bundle")
    ax.set_ylabel("Size (kB)")
    ax.set_ylim(0, max(ys) * 1.15)
    ax.legend(loc="upper left", frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(HERE / "fig_bundle_scaling.pdf")
    plt.close(fig)
    print(f"scaling: {n} runs, canonical {min(ys):.1f}-{max(ys):.1f} kB, "
          f"on-chain constant {onchain_kb*1024:.0f} B")


if __name__ == "__main__":
    thermal_trace()
    beta_posterior()
    bridge_latency()
    bundle_scaling()
