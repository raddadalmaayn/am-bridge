#!/usr/bin/env python3
"""
capture_poll.py -- Option A recorder for the provenance bridge experiment.

WHAT IT DOES
  During a print it polls OctoPrint's REST API (read-only) every few seconds,
  appends each sample to a durable JSONL log (survives a crash), and when the
  print ends it builds the `observed` block, signs it via attestation.py, and
  emits the one on-chain commitment (offChainDataHash) + the Fabric submit args.

WHY POLLING IS FINE FOR THE EXPERIMENT
  The ledger gets ONE record per build. This recorder produces exactly that.
  It is read-only (GET /api/printer, GET /api/job), so it never disturbs the
  shared printer or other users. Trust-wise it is weaker than the on-Pi plugin
  (Option B) because it signs what OctoPrint *reports* rather than capturing
  inside OctoPrint -- adequate to demonstrate the attestation + tamper pipeline,
  not the final trust claim.

LIVE USAGE (on a machine that can reach the printer)
  export OCTOPRINT_URL="http://<octoprint-host>:5000"
  export OCTOPRINT_API_KEY="<your own rotated app key>"
  python3 capture_poll.py --gcode f4u2.gcode --asset PART-f4u2-0001 \
                          --rated-actor operator-secnet
  # start the print in OctoPrint; the recorder stops itself when the job ends.

OFFLINE DRY-RUN (no printer, proves the pipeline)
  python3 capture_poll.py --simulate --gcode ender3/Ender3_Printer/f4u2.gcode
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import attestation as att   # the integrity core delivered earlier


def poll_once(base_url: str, api_key: str):
    """One read-only sample of printer + job state. Returns (sample, job)."""
    import requests
    h = {"X-Api-Key": api_key}
    pr = requests.get(f"{base_url}/api/printer", headers=h, timeout=5).json()
    jb = requests.get(f"{base_url}/api/job", headers=h, timeout=5).json()
    temps = pr.get("temperature", {})
    sample = {
        "t": int(time.time()),
        "nozzle_c": temps.get("tool0", {}).get("actual"),
        "nozzle_target": temps.get("tool0", {}).get("target"),
        "bed_c": temps.get("bed", {}).get("actual"),
        "bed_target": temps.get("bed", {}).get("target"),
        "state": pr.get("state", {}).get("text"),
    }
    return sample, jb


def capture_live(args, expected) -> dict:
    base = os.environ["OCTOPRINT_URL"].rstrip("/")
    key = os.environ["OCTOPRINT_API_KEY"]
    log = Path(args.log)
    samples, t0, seen_printing = [], time.time(), False
    print(f"[recorder] polling {base} every {args.interval}s -> {log}")
    while True:
        try:
            s, jb = poll_once(base, key)
        except Exception as e:           # noqa: BLE001 - keep recording resilient
            print(f"[recorder] poll error: {e}", file=sys.stderr)
            time.sleep(args.interval); continue

        with log.open("a") as fh:        # durable append per sample
            fh.write(json.dumps(s) + "\n")
        samples.append(s)

        state = (s["state"] or "").lower()
        completion = (jb.get("progress") or {}).get("completion")
        printing = "printing" in state or "pausing" in state or "paused" in state
        seen_printing = seen_printing or printing

        print(f"  t={s['t']} nozzle={s['nozzle_c']} bed={s['bed_c']} "
              f"state={s['state']} done={completion}")

        # Stop once a print we observed running has left the printing states.
        if seen_printing and not printing:
            done = completion is not None and completion >= 99.5
            outcome = "PrintDone" if done else "PrintCancelled"  # poller can't
            # distinguish cancel vs fail reliably -- the plugin (Option B) can.
            return assemble_observed(samples, t0, outcome, expected)
        time.sleep(args.interval)


def capture_simulated(expected) -> dict:
    """Synthesise a plausible thermal trace from the G-code envelope so the
    full pipeline is runnable with no printer. Tagged so it is never mistaken
    for real data."""
    noz, bed = expected["expected_nozzle_c"] or 200.0, expected["expected_bed_c"] or 50.0
    samples = []
    for i in range(0, 600, 30):                 # 10 min of 30s samples
        ramp = min(1.0, i / 120.0)              # ~2 min ramp to target
        samples.append({
            "t": 1000 + i,
            "nozzle_c": round(noz * ramp + math.sin(i) * 0.5, 1),
            "bed_c": round(bed * min(1.0, i / 90.0), 1),
            "state": "Printing",
        })
    return assemble_observed(samples, 0, "PrintCancelled", expected,
                             source="SIMULATED_NO_PRINTER", actual_time_s=600)


def assemble_observed(samples, t0, outcome, expected,
                      source="OCTOPRINT_POLL", actual_time_s=None) -> dict:
    if actual_time_s is None:
        actual_time_s = int(samples[-1]["t"] - samples[0]["t"]) if len(samples) > 1 else 0
    return {
        "outcome": outcome,
        "observed": {
            "source": source,
            "tolerance_c": 8.0,
            "actual_time_s": actual_time_s,
            "executed_gcode_sha256": expected["gcode_sha256"],
            "samples": samples,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gcode", default="ender3/Ender3_Printer/f4u2.gcode")
    ap.add_argument("--asset", default="PART-f4u2-0001")
    ap.add_argument("--rated-actor", default="operator-secnet")
    ap.add_argument("--dimension", default="quality")
    ap.add_argument("--interval", type=float, default=5.0)
    ap.add_argument("--run-name", default="run1",
                    help="names the output files: capture_<run>.jsonl / bundle_<run>.json")
    ap.add_argument("--log", default=None,
                    help="override the JSONL capture log path (default capture_<run>.jsonl)")
    ap.add_argument("--key", default="device_key.pem")
    ap.add_argument("--out", default=None,
                    help="override the signed bundle path (default bundle_<run>.json)")
    ap.add_argument("--simulate", action="store_true")
    args = ap.parse_args()

    # Per-run output filenames; --log / --out still override explicitly.
    if args.log is None:
        args.log = f"capture_{args.run_name}.jsonl"
    if args.out is None:
        args.out = f"bundle_{args.run_name}.json"

    expected = att.parse_gcode_envelope(args.gcode)
    cap = capture_simulated(expected) if args.simulate else capture_live(args, expected)

    key = att.DeviceKey.load_or_create(args.key)
    payload = att.build_payload(args.asset, expected, cap["observed"],
                                outcome=cap["outcome"],
                                started="(capture start)", ended="(capture end)")
    bundle = att.sign_bundle(payload, key)
    Path(args.out).write_text(json.dumps(bundle, indent=2))

    print("\n=== RESULT ===")
    print(f"run name          : {args.run_name}")
    print(f"outcome           : {cap['outcome']}")
    print(f"samples captured  : {len(cap['observed']['samples'])} "
          f"(source={cap['observed']['source']})")
    print(f"assessment        : {payload['assessment']}")
    print(f"offChainDataHash  : {att.off_chain_hash(bundle)}")
    print("\n=== OUTPUT FILES ===")
    print(f"  capture log    -> {args.log}")
    print(f"  signed bundle  -> {args.out}")
    print("\nFabric submit args (cloudnode, org MSP):")
    for k, v in att.chaincode_args(args.asset, bundle, args.rated_actor,
                                   args.dimension).items():
        print(f"  {k:18s}= {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
