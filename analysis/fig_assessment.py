#!/usr/bin/env python3
"""
Paper Fig. 3: per-run assessment, signed quality q next to the warm-up-excluded
quality q_ss, plus compliance c.

All values are computed from the five signed bundles: q and c are the signed,
committed assessment; q_ss re-scores the signed telemetry samples with the
steady-state gate of policy_sensitivity.py. Styling matches the paper's other
data figures (Liberation Serif, single IEEE column).

Usage: python3 analysis/fig_assessment.py [out.pdf]
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from policy_sensitivity import RUNS, load, quality  # noqa: E402

NAVY, LIGHT, GREEN, RED = "#21507f", "#9db9d8", "#3f8a4f", "#b03a2e"

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Liberation Serif", "Times New Roman", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8, "axes.labelsize": 8, "legend.fontsize": 7,
    "xtick.labelsize": 7, "ytick.labelsize": 7,
    "axes.linewidth": 0.6, "pdf.fonttype": 42,
    "xtick.direction": "in", "ytick.direction": "in",
})


def main(out: str):
    names = list(RUNS)
    q, qss, c = [], [], []
    for r in names:
        p = load(r)
        q.append(p["assessment"]["quality"])
        h, t = quality(p, gate="steady")
        qss.append(h / t)
        c.append(p["assessment"]["compliance"])

    fig, ax = plt.subplots(figsize=(3.45, 1.4))
    w = 0.26
    x = range(len(names))
    bars = [
        (-w, q, NAVY, None, r"quality $q$ (signed)"),
        (0.0, qss, LIGHT, "////", r"$q_\mathrm{ss}$ (warm-up excluded)"),
        (+w, c, GREEN, None, r"compliance $c$"),
    ]
    for dx, vals, col, hatch, lab in bars:
        ax.bar([i + dx for i in x], vals, width=w, color=col, label=lab,
               edgecolor="white" if hatch is None else NAVY, linewidth=0.4,
               hatch=hatch)
    for i in x:  # value labels on the two quality bars
        ax.text(i - w, q[i] + 0.02, f"{q[i]:.2f}", ha="center", va="bottom",
                fontsize=5.6, color=NAVY)
        ax.text(i, qss[i] + 0.02, f"{qss[i]:.2f}", ha="center", va="bottom",
                fontsize=5.6, color=NAVY)

    a, d = names.index("cube_anomaly"), names.index("cube_done")
    drop = (qss[d] - qss[a]) / qss[d] * 100
    ax.annotate("", xy=(a - 0.02, qss[a] + 0.10), xytext=(d + 0.06, qss[d] + 0.10),
                arrowprops=dict(arrowstyle="->", color=RED, lw=0.8))
    ax.text((a + d) / 2, qss[d] + 0.11, f"injection $-${drop:.1f}%", color=RED,
            fontsize=6, ha="center", va="bottom")

    ax.set_xticks(list(x))
    ax.set_xticklabels(names, family="Liberation Mono", fontsize=6.3,
                       rotation=12, ha="right", rotation_mode="anchor")
    ax.set_ylim(0, 1.42)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0])
    ax.set_ylabel("Score")
    ax.yaxis.grid(True, ls=":", lw=0.5, color="0.75")
    ax.set_axisbelow(True)
    ax.legend(loc="upper center", ncol=3, frameon=False, handlelength=1.2,
              columnspacing=0.8, borderaxespad=0.1, fontsize=6.3)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(pad=0.2)
    fig.savefig(out)
    plt.close(fig)
    print(f"wrote {out}: " + ", ".join(
        f"{n} q={a_:.3f} q_ss={b:.3f} c={c_:.1f}" for n, a_, b, c_ in zip(names, q, qss, c)))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "fig_assessment.pdf")
