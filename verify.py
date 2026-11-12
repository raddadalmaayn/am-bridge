#!/usr/bin/env python3
"""
Verify the published signed telemetry bundles end to end, offline.

For every bundle listed in commitments.json this checks:
  1. device signature  : Ed25519 over canon(payload) with the embedded key
  2. device identity   : device_id == "DEV:" + SHA-256(raw public key)[:16]
  3. commitment        : SHA-256(canon({payload, attestation})) equals the
                         offChainDataHash recorded at commit time (when logged)
  4. design binding    : SHA-256 of the G-code file (when present) equals the
                         certified design hash; compliance = executed == certified
  5. asset binding     : the asset ID signed inside the payload equals the
                         ledger asset the commitment was recorded against
  6. assessment        : the signed quality/rating are reproduced from the
                         signed telemetry samples (reports which policy matches)
and prints the steady-state (warm-up-excluded) quality used in the paper.

    python3 verify.py            # verify all bundles
    python3 verify.py --tamper   # also show that a one-sample edit is caught twice
    python3 verify.py --replay   # also show that a same-design replay is caught
                                 # only by the asset-binding check

Requires: Python 3.9+, `cryptography`.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "analysis"))
from attestation import (assess, canonical, off_chain_hash, sha256_hex,  # noqa: E402
                         verify_sig)
from policy_sensitivity import quality  # noqa: E402

OK, BAD, SKIP = "PASS", "FAIL", "n/a "


def check(path: str, recorded: str | None, ledger_asset: str) -> tuple[bool, list[str]]:
    b = json.loads((ROOT / path).read_text())
    p, att = b["payload"], b["attestation"]
    lines, ok = [], True

    def row(status, name, detail):
        nonlocal ok
        ok &= status != BAD
        lines.append(f"    [{status}] {name:17} {detail}")

    sig = verify_sig(att["pubkey"], att["signature"], canonical(p))
    row(OK if sig else BAD, "device signature", f"Ed25519, {att['device_id']}")

    did = "DEV:" + sha256_hex(bytes.fromhex(att["pubkey"]))[:16]
    row(OK if did == att["device_id"] else BAD, "device identity", did)

    och = off_chain_hash(b)
    if recorded:
        row(OK if och.startswith(recorded) else BAD, "ledger commitment",
            f"{och[:16]}... vs recorded {recorded[:16]}... ({len(recorded) * 4}-bit)")
    else:
        row(SKIP, "ledger commitment", f"{och[:16]}... (no recorded value in repo)")

    row(OK if p["assetId"] == ledger_asset else BAD, "asset binding",
        f"signed {p['assetId']} vs ledger {ledger_asset}")

    d = p["design"]
    gfile = next((c for c in (ROOT / d["gcode_filename"],
                              ROOT / Path(path).parent / d["gcode_filename"]) if c.exists()), None)
    if gfile:
        g = sha256_hex(gfile.read_bytes())
        row(OK if g == d["gcode_sha256"] else BAD, "design file hash", f"{d['gcode_filename']} {g[:16]}...")
    else:
        row(SKIP, "design file hash", f"{d['gcode_filename']} not in public tree")
    comp = p["observed"]["executed_gcode_sha256"] == d["gcode_sha256"]
    row(OK if comp == (p["assessment"]["compliance"] == 1.0) else BAD, "compliance",
        f"executed {'==' if comp else '!='} certified -> c={p['assessment']['compliance']}")

    signed_q = p["assessment"]["quality"]
    rec_q = round(assess(d, p["observed"])["quality"], 4)
    h, t = quality(p, gate="all")
    if abs(rec_q - signed_q) < 1e-4:
        row(OK, "assessment", f"q={signed_q} reproduced (Printing-state samples)")
    elif abs(round(h / t, 4) - signed_q) < 1e-4:
        row(OK, "assessment", f"q={signed_q} reproduced (all samples; earlier policy)")
    else:
        row(BAD, "assessment", f"signed q={signed_q} not reproduced (got {rec_q})")
    hs, ts = quality(p, gate="steady")
    lines.append(f"    [info] steady-state q     {hs}/{ts} = {hs / ts:.3f} (warm-up excluded)")
    return ok, lines


def tamper_demo(path: str, recorded: str):
    b = json.loads((ROOT / path).read_text())
    t = copy.deepcopy(b)
    t["payload"]["observed"]["samples"][60]["nozzle_c"] = 235.0
    hash_ok = off_chain_hash(t).startswith(recorded)
    sig_ok = verify_sig(t["attestation"]["pubkey"], t["attestation"]["signature"],
                        canonical(t["payload"]))
    print(f"\nTamper demo on {path}: sample 60 nozzle -> 235.0 C")
    print(f"    ledger commitment : {'still matches' if hash_ok else 'MISMATCH (detected)'}")
    print(f"    device signature  : {'still valid' if sig_ok else 'INVALID (detected)'}")
    return not hash_ok and not sig_ok


def replay_demo(path: str, other_asset: str):
    """Commit an unmodified valid bundle against another certified asset of
    the same design: hash and signature still verify, asset binding fails."""
    b = json.loads((ROOT / path).read_text())
    p, att = b["payload"], b["attestation"]
    sig_ok = verify_sig(att["pubkey"], att["signature"], canonical(p))
    print(f"\nReplay demo: {path} (signed for {p['assetId']}) committed against {other_asset}")
    print(f"    device signature  : {'valid' if sig_ok else 'INVALID'} (bundle untouched)")
    print(f"    ledger commitment : matches (the replayed hash is what was committed)")
    caught = p["assetId"] != other_asset
    print(f"    asset binding     : {'MISMATCH (detected)' if caught else 'match'}")
    return caught


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tamper", action="store_true")
    ap.add_argument("--replay", action="store_true")
    args = ap.parse_args()
    manifest = json.loads((ROOT / "commitments.json").read_text())
    all_ok = True
    for path, meta in manifest.items():
        if path.startswith("_"):
            continue
        ok, lines = check(path, meta["recorded_offChainDataHash"], meta["assetId"])
        all_ok &= ok
        print(f"{'VERIFIED' if ok else 'FAILED  '}  {path}  ({meta['assetId']})")
        print("\n".join(lines))
    if args.tamper:
        all_ok &= tamper_demo("bundle_cube_done.json",
                              manifest["bundle_cube_done.json"]["recorded_offChainDataHash"])
    if args.replay:
        all_ok &= replay_demo("bundle_cube_done.json",
                              manifest["bundle_cube_repeat.json"]["assetId"])
    print("\nALL CHECKS PASSED" if all_ok else "\nSOME CHECKS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
