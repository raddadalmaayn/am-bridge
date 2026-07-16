#!/usr/bin/env python3
"""
benchmark_bridge.py -- latency + size measurement for the provenance bridge.

Measures the *off-chain* overhead the bridge adds on top of a print job:
parsing, payload assembly, canonicalisation, Ed25519 signing, hash derivation,
and full two-way verification. Also reports how a multi-megabyte print collapses
to a 32-byte on-chain commitment (the compression argument for the paper).

All timing imports come from attestation.py -- no logic is duplicated here.

Usage:
  python3 benchmark_bridge.py signed_bundle.json
  python3 benchmark_bridge.py bundle_run1.json bundle_run2.json bundle_run3.json
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import attestation as att

ITERS = 100
# On-chain chaincode record footprint (bytes). The committed ProvenanceEvent
# stores the 32-byte offChainDataHash plus the surrounding record fields
# (assetId, eventType, txID, timestamp, rated-actor link, evidence hash, ...).
ONCHAIN_RECORD_BYTES = 337


def _percentile(sorted_vals, pct):
    """Nearest-rank percentile on an already-sorted list (no numpy dep)."""
    if not sorted_vals:
        return 0.0
    k = max(0, min(len(sorted_vals) - 1,
                   int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _stats_ns(samples_ns):
    """Summarise nanosecond samples -> dict of milliseconds (and raw ns mean)."""
    s = sorted(samples_ns)
    to_ms = 1e-6
    return {
        "mean_ms": statistics.mean(s) * to_ms,
        "median_ms": statistics.median(s) * to_ms,
        "p95_ms": _percentile(s, 95) * to_ms,
        "p99_ms": _percentile(s, 99) * to_ms,
        "min_ms": s[0] * to_ms,
        "max_ms": s[-1] * to_ms,
        "mean_ns": statistics.mean(s),
        "n": len(s),
    }


def _bench(fn, iters=ITERS):
    """Time `fn` `iters` times with perf_counter_ns; return per-call ns samples."""
    samples = []
    for _ in range(iters):
        t0 = time.perf_counter_ns()
        fn()
        samples.append(time.perf_counter_ns() - t0)
    return samples


def benchmark_one(bundle_path: str) -> dict:
    bundle = json.loads(Path(bundle_path).read_text())
    payload = bundle["payload"]
    design = payload["design"]
    observed = payload["observed"]

    # Resolve the real G-code so envelope parsing is measured against actual I/O
    # if present; otherwise fall back to re-deriving from the design block.
    gcode_name = design.get("gcode_filename", "")
    gcode_candidates = [gcode_name, f"Ender3_Printer/{gcode_name}"]
    gcode_path = next((p for p in gcode_candidates if p and Path(p).exists()), None)

    key = att.DeviceKey.load_or_create("device_key.pem")
    och = att.off_chain_hash(bundle)

    timings = {}

    if gcode_path:
        timings["parse_gcode_envelope"] = _bench(
            lambda: att.parse_gcode_envelope(gcode_path))
        expected = att.parse_gcode_envelope(gcode_path)
    else:
        expected = dict(design)  # design block already holds the expected fields
        timings["parse_gcode_envelope"] = None

    timings["build_payload"] = _bench(
        lambda: att.build_payload(payload["assetId"], expected, observed,
                                  payload["outcome"], "s", "e"))
    timings["canonical"] = _bench(lambda: att.canonical(payload))
    timings["ed25519_sign"] = _bench(lambda: key.sign_hex(att.canonical(payload)))
    timings["off_chain_hash"] = _bench(lambda: att.off_chain_hash(bundle))
    timings["verify_bundle"] = _bench(
        lambda: att.verify_bundle(bundle, ledger_off_chain_hash=och,
                                  registered_pubkey_hex=bundle["attestation"]["pubkey"]))

    latency = {k: (_stats_ns(v) if v is not None else None)
               for k, v in timings.items()}

    # ---- sizes -----------------------------------------------------------
    raw_bytes = len(json.dumps(bundle, indent=2).encode("utf-8"))
    canonical_bytes = len(att.canonical(bundle))
    onchain_bytes = 32 + ONCHAIN_RECORD_BYTES  # 32-byte hash + record overhead
    gcode_bytes = design.get("gcode_bytes")
    n_samples = len(observed.get("samples", []))

    sizes = {
        "raw_json_bytes": raw_bytes,
        "canonical_json_bytes": canonical_bytes,
        "onchain_hash_bytes": 32,
        "onchain_record_bytes": ONCHAIN_RECORD_BYTES,
        "onchain_footprint_bytes": onchain_bytes,
        "gcode_bytes": gcode_bytes,
        "n_samples": n_samples,
        "compression_ratio_canonical_to_onchain": round(canonical_bytes / onchain_bytes, 2),
        "compression_ratio_gcode_to_onchain": (
            round(gcode_bytes / onchain_bytes, 2) if gcode_bytes else None),
    }

    return {"bundle": bundle_path, "latency": latency, "sizes": sizes}


def _fmt_row(label, st):
    if st is None:
        return f"  {label:24s}   (not measured -- G-code not present)"
    return (f"  {label:24s} {st['mean_ms']:9.4f} {st['median_ms']:9.4f} "
            f"{st['p95_ms']:9.4f} {st['p99_ms']:9.4f}")


def print_human(result):
    b = result["bundle"]
    bar = "-" * 78
    print(bar); print(f"LATENCY  ({ITERS} iters)  bundle = {b}"); print(bar)
    print(f"  {'stage':24s} {'mean':>9s} {'median':>9s} {'p95':>9s} {'p99':>9s}  (ms)")
    order = ["parse_gcode_envelope", "build_payload", "canonical",
             "ed25519_sign", "off_chain_hash", "verify_bundle"]
    for k in order:
        print(_fmt_row(k, result["latency"][k]))

    s = result["sizes"]
    print(); print(bar); print("SIZES"); print(bar)
    print(f"  raw JSON (indented)        : {s['raw_json_bytes']:>12,} B")
    print(f"  canonical JSON (committed) : {s['canonical_json_bytes']:>12,} B")
    print(f"  on-chain footprint         : {s['onchain_footprint_bytes']:>12,} B "
          f"(32-byte hash + {s['onchain_record_bytes']} B record)")
    if s["gcode_bytes"]:
        print(f"  source G-code              : {s['gcode_bytes']:>12,} B")
    print(f"  samples in bundle          : {s['n_samples']:>12,}")
    print(f"  compression canonical->chain: {s['compression_ratio_canonical_to_onchain']:>11}x")
    if s["compression_ratio_gcode_to_onchain"]:
        print(f"  compression  gcode  ->chain: {s['compression_ratio_gcode_to_onchain']:>11}x")
    print(bar)


def print_size_table(results):
    """Fig. 4b: on-chain footprint is flat regardless of sample count."""
    bar = "=" * 78
    print(); print(bar); print("SIZE vs SAMPLE COUNT  (Fig. 4b)"); print(bar)
    print(f"  {'bundle':28s} {'samples':>8s} {'canonical B':>12s} {'on-chain B':>11s} {'ratio':>8s}")
    for r in results:
        s = r["sizes"]
        name = Path(r["bundle"]).name
        print(f"  {name:28s} {s['n_samples']:>8d} {s['canonical_json_bytes']:>12,} "
              f"{s['onchain_footprint_bytes']:>11,} "
              f"{s['compression_ratio_canonical_to_onchain']:>7}x")
    print(bar)


def main() -> int:
    paths = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not paths:
        paths = ["signed_bundle.json"]

    results = []
    for p in paths:
        if not Path(p).exists():
            print(f"[skip] {p} not found", file=sys.stderr)
            continue
        results.append(benchmark_one(p))

    if not results:
        print("ERROR: no bundles to benchmark", file=sys.stderr)
        return 1

    for r in results:
        print_human(r)
        print()

    if len(results) > 1:
        print_size_table(results)

    out = {
        "iterations": ITERS,
        "onchain_record_bytes": ONCHAIN_RECORD_BYTES,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": results,
    }
    Path("benchmark_results.json").write_text(json.dumps(out, indent=2))
    print(f"\nMachine-readable results -> benchmark_results.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
