#!/usr/bin/env python3
"""
Fleet experiment, step 1: emulated printers attest real telemetry.

Each emulated printer (device) gets its own fresh Ed25519 key and attests jobs
built from the REAL captured traces of the four PLA-profile runs (cube_done,
cube_anomaly, cube_repeat, bracket), round-robin, under fresh asset IDs.
Only the device identity, asset ID and signature are new; design envelope,
telemetry samples and assessment are those of the real prints.

Output: one JSONL line per job with the chaincode arguments that
fleet_submit.js commits, plus the measured attestation time on this host.
Private keys are kept in memory only and discarded.

Usage: python3 make_fleet_bundles.py --tag RUN1 --out jobs_RUN1.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from attestation import (DeviceKey, build_payload, sign_bundle,  # noqa: E402
                         off_chain_hash, canonical, sha256_hex)
from cryptography.hazmat.primitives.asymmetric.ed25519 import \
    Ed25519PrivateKey  # noqa: E402

TRACES = ["bundle_cube_done.json", "bundle_cube_anomaly.json",
          "bundle_cube_repeat.json", "bundle_bracket_done.json"]
LEVELS = [1, 2, 4, 8, 16, 32, 64]          # concurrent printers
SCENARIOS = ["independent", "shared"]       # operator per printer vs one farm


def jobs_per_device(n: int) -> int:
    return max(4, 32 // n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    real = [json.loads((ROOT / t).read_text())["payload"] for t in TRACES]
    keys = [DeviceKey(Ed25519PrivateKey.generate()) for _ in range(max(LEVELS))]

    n_jobs = 0
    with open(args.out, "w") as f:
        for scen in SCENARIOS:
            for n in LEVELS:
                for d in range(n):
                    for j in range(jobs_per_device(n)):
                        src = real[(d + j) % len(real)]
                        asset = f"FLEET-{args.tag}-{scen[:3].upper()}-N{n}-D{d}-J{j}"
                        expected = {**src["design"],
                                    "target_machine": src.get("machine")}
                        t0 = time.perf_counter()
                        payload = build_payload(asset, expected, src["observed"],
                                                src["outcome"],
                                                src["window"]["started"],
                                                src["window"]["ended"])
                        bundle = sign_bundle(payload, keys[d])
                        och = off_chain_hash(bundle)
                        evid = sha256_hex(canonical(payload))
                        attest_ms = (time.perf_counter() - t0) * 1e3
                        actor = (f"FLEET-OP-{args.tag}-N{n}-D{d}" if scen == "independent"
                                 else f"FLEET-FARM-{args.tag}-N{n}")
                        f.write(json.dumps({
                            "scenario": scen, "n": n, "device": d, "job": j,
                            "device_id": keys[d].device_id,
                            "assetId": asset,
                            "gcodeHash": payload["design"]["gcode_sha256"],
                            "offChainDataHash": och,
                            "evidenceHash": evid,
                            "rating": f'{payload["assessment"]["rating_value"]}',
                            "ratedActor": actor,
                            "bundleBytes": len(canonical(bundle)),
                            "attest_ms": round(attest_ms, 4),
                        }) + "\n")
                        n_jobs += 1
    print(f"wrote {n_jobs} jobs for {max(LEVELS)} emulated devices -> {args.out}")


if __name__ == "__main__":
    main()
