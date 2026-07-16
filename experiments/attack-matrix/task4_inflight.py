#!/usr/bin/env python3
"""Task 4 — in-flight modification between attestation and gateway.

Copy an existing signed bundle, flip ONE byte in ONE telemetry sample AFTER the
device signed it, recompute the on-chain commitment hash, and show BOTH
detections fire:
  (1) recomputed offChainDataHash != the original on-chain commitment
  (2) Ed25519 signature invalid over the altered payload
The original published bundle file is never overwritten (we work on a copy).
"""
import json, copy, sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from attestation import off_chain_hash, verify_bundle, canonical

SRC = _ROOT / "bundle_cube_done.json"
orig = json.load(open(SRC))

# The commitment that WAS written on-chain when the honest bundle was submitted.
committed_hash = off_chain_hash(orig)

# Work on a deep copy — the published file is untouched.
tampered = copy.deepcopy(orig)
samples = tampered["payload"]["observed"]["samples"]
# pick first sample with a nozzle reading, flip one byte: 0.1 C nudge
idx = next(i for i, s in enumerate(samples) if s.get("nozzle_c") is not None)
before = samples[idx]["nozzle_c"]
samples[idx]["nozzle_c"] = round(before + 0.1, 4)   # single-byte-scale mutation
after = samples[idx]["nozzle_c"]

recomputed_hash = off_chain_hash(tampered)

print("-"*70)
print("Task 4: in-flight telemetry modification (post-signing)")
print("-"*70)
print(f"mutated sample[{idx}].nozzle_c : {before} -> {after}")
print(f"on-chain committed hash        : {committed_hash}")
print(f"recomputed hash (tampered)     : {recomputed_hash}")
print()

# Detection 1 + 2 via verify_bundle, passing the ORIGINAL on-chain commitment.
ok, reasons = verify_bundle(tampered, ledger_off_chain_hash=committed_hash,
                            registered_pubkey_hex=tampered["attestation"]["pubkey"])
print(f"verify_bundle verdict : {'ACCEPT' if ok else 'REJECT'}")
for r in reasons:
    print(f"   - {r}")
print()
hash_detected = recomputed_hash != committed_hash
sig_detected  = any("SIGNATURE INVALID" in r for r in reasons)
print(f"[Detection 1] ledger-hash mismatch : {'FIRED' if hash_detected else 'missed'}")
print(f"[Detection 2] signature invalid    : {'FIRED' if sig_detected else 'missed'}")
print("-"*70)
assert not ok and hash_detected and sig_detected, "Task 4 invariant violated"
print("RESULT: a single-byte post-signing edit is caught twice over — the")
print("evidence no longer hashes to the on-chain commitment AND the device")
print("signature no longer verifies over the altered payload.")
