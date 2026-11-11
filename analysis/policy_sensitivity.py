#!/usr/bin/env python3
"""
Assessment-policy sensitivity analysis over the five signed bundles.

Everything here is recomputed from the telemetry samples INSIDE the signed
bundles (bundle["payload"]["observed"]["samples"]), so any verifier can
reproduce it without the printer and without trusting the stored assessment.
The signed/committed assessment values are not modified.

Three questions:
  1. Warm-up gating: how does the quality metric change if each heater is
     counted only after it first enters the tolerance band ("steady-state")?
  2. Tolerance band: does the honest-vs-anomaly separation depend on +/-8 C?
  3. Sampling interval: is the +15 C injection still visible if the 5 s
     trace is decimated to 10/20/30 s (all phase offsets)?

Usage:  python3 analysis/policy_sensitivity.py  [--json out.json]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = {  # run name -> signed bundle (Table II order)
    "f4u2": "signed_bundle.json",
    "cube_done": "bundle_cube_done.json",
    "cube_anomaly": "bundle_cube_anomaly.json",
    "cube_repeat": "bundle_cube_repeat.json",
    "bracket": "bundle_bracket_done.json",
}
HONEST = ["f4u2", "cube_done", "cube_repeat", "bracket"]
CHANNELS = (("nozzle_c", "expected_nozzle_c"), ("bed_c", "expected_bed_c"))


def load(run: str) -> dict:
    return json.loads((ROOT / RUNS[run]).read_text())["payload"]


def is_printing(s: dict) -> bool:
    return "printing" in (s.get("state") or "").lower()


def quality(payload: dict, tol: float = 8.0, gate: str = "steady",
            samples: list | None = None) -> tuple[int, int]:
    """Return (in-tolerance readings, counted readings).

    gate = "all"      every sample (policy used for f4u2 when it was signed)
           "printing" samples whose OctoPrint state is Printing (assess() in
                      attestation.py; used for the other four signed runs)
           "steady"   Printing samples from the first in-band reading of each
                      heater onward (excludes heat-up; later excursions count)
    """
    samples = payload["observed"]["samples"] if samples is None else samples
    design = payload["design"]
    hits = total = 0
    for actual, target in CHANNELS:
        exp = design[target]
        settled = gate != "steady"
        for s in samples:
            if gate in ("printing", "steady") and not is_printing(s):
                continue
            v = s.get(actual)
            if v is None:
                continue
            inb = abs(v - exp) <= tol
            if not settled:
                if not inb:
                    continue
                settled = True
            total += 1
            hits += inb
    return hits, total


def q(payload, **kw) -> float:
    h, t = quality(payload, **kw)
    return h / t if t else float("nan")


def injection_window(payload: dict) -> list[int]:
    """Indices of samples whose nozzle target was overridden (M104 S215)."""
    base = payload["design"]["expected_nozzle_c"]
    return [i for i, s in enumerate(payload["observed"]["samples"])
            if s.get("nozzle_target") not in (None, 0.0, base)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write results to this file")
    args = ap.parse_args()
    P = {r: load(r) for r in RUNS}
    out = {}

    # 1. gating ----------------------------------------------------------------
    print("1) Warm-up gating (tolerance +/-8 C)")
    print(f"   {'run':13} {'signed':>7} {'all':>12} {'printing':>12} {'steady':>12}")
    out["gating"] = {}
    for r, p in P.items():
        row = {g: quality(p, gate=g) for g in ("all", "printing", "steady")}
        out["gating"][r] = {"signed_quality": p["assessment"]["quality"],
                            **{g: {"hits": h, "total": t, "q": h / t}
                               for g, (h, t) in row.items()}}
        cells = " ".join(f"{h:>3}/{t:<3}={h/t:.3f}" for h, t in row.values())
        print(f"   {r:13} {p['assessment']['quality']:7.3f} {cells}")
    for g in ("printing", "steady"):
        d, a = q(P["cube_done"], gate=g), q(P["cube_anomaly"], gate=g)
        print(f"   controlled pair [{g}]: done {d:.3f} vs anomaly {a:.3f}"
              f" -> relative drop {(d - a) / d * 100:.1f}%")
        out["gating"][f"drop_{g}"] = (d - a) / d

    # 2. tolerance band ----------------------------------------------------------
    print("\n2) Tolerance-band sensitivity (steady-state gate)")
    out["tolerance"] = {}
    for tol in (4, 6, 8, 10, 12):
        hon = {r: q(P[r], tol=tol) for r in HONEST}
        an = q(P["cube_anomaly"], tol=tol)
        d = hon["cube_done"]
        out["tolerance"][tol] = {"honest": hon, "anomaly": an,
                                 "min_honest": min(hon.values()),
                                 "drop_vs_done": (d - an) / d}
        print(f"   +/-{tol:>2} C: honest min {min(hon.values()):.3f} "
              f"(" + ", ".join(f"{k} {v:.3f}" for k, v in hon.items()) + f")"
              f" | anomaly {an:.3f} | drop vs cube_done {(d - an) / d * 100:5.1f}%")

    # 3. sampling interval ---------------------------------------------------------
    print("\n3) Decimation of the 5 s trace (cube_anomaly, +/-8 C, steady gate)")
    pa = P["cube_anomaly"]
    S = pa["observed"]["samples"]
    inj = injection_window(pa)
    base = pa["design"]["expected_nozzle_c"]
    out["decimation"] = {}
    for k in (1, 2, 4, 6):
        res = []
        for phase in range(k):
            sub = S[phase::k]
            oob = sum(1 for i in range(phase, len(S), k)
                      if inj[0] <= i <= inj[-1] + 3 and S[i]["nozzle_c"] - base > 8)
            res.append({"phase": phase, "oob_injection_samples": oob,
                        "q_anomaly": q(pa, samples=sub),
                        "q_done": q(P["cube_done"],
                                    samples=P["cube_done"]["observed"]["samples"][phase::k])})
        worst = min(res, key=lambda x: x["oob_injection_samples"])
        out["decimation"][5 * k] = res
        print(f"   {5*k:>2} s: injection out-of-band samples (worst phase) "
              f"{worst['oob_injection_samples']:>2} | q anomaly "
              f"{min(x['q_anomaly'] for x in res):.3f}-{max(x['q_anomaly'] for x in res):.3f}"
              f" vs done {min(x['q_done'] for x in res):.3f}-{max(x['q_done'] for x in res):.3f}")

    # thermal slew (5 s resolution) ---------------------------------------------------
    sl = [(b["nozzle_c"] - a["nozzle_c"]) / (b["t"] - a["t"])
          for a, b in zip(S, S[1:]) if b["t"] > a["t"]]
    out["slew"] = {"max_heat_c_per_s": max(sl), "max_cool_c_per_s": min(sl),
                   "injection_samples": len(inj)}
    print(f"\n   nozzle slew at 5 s resolution: +{max(sl):.2f} / {min(sl):.2f} C/s;"
          f" override active for {len(inj)} samples")

    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=2))
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
