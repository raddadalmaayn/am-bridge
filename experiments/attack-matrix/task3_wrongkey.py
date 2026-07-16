#!/usr/bin/env python3
"""Task 3 — wrong-key signature verification.

Verify bundle_cube_done.json against (1) a freshly generated WRONG Ed25519
public key -> must FAIL, and (2) the true device key embedded in the bundle
-> must PASS. No bytes of the bundle are modified.
"""
import json, sys, tempfile, os
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from attestation import verify_sig, canonical, DeviceKey

bundle = json.load(open(_ROOT / "bundle_cube_done.json"))
att = bundle["attestation"]
payload_bytes = canonical(bundle["payload"])
true_pub = att["pubkey"]
sig = att["signature"]

# Generate a second, unrelated keypair in a temp dir.
tmp = tempfile.mkdtemp(prefix="wrongkey_")
wrong_key = DeviceKey.load_or_create(os.path.join(tmp, "wrong_device_key.pem"))
wrong_pub = wrong_key.pubkey_hex

print("-"*70)
print("Task 3: wrong-key vs true-key signature verification (bundle unmodified)")
print("-"*70)
print(f"true device pubkey  : {true_pub}")
print(f"wrong device pubkey : {wrong_pub}  (fresh keypair in {tmp})")
print(f"device_id (bundle)  : {att['device_id']}")
print()

ok_wrong = verify_sig(wrong_pub, sig, payload_bytes)
print(f"[1] verify against WRONG key : {'PASS' if ok_wrong else 'FAIL'}  "
      f"-> expected FAIL  {'(OK)' if not ok_wrong else '(!! UNEXPECTED)'}")

ok_true = verify_sig(true_pub, sig, payload_bytes)
print(f"[2] verify against TRUE  key : {'PASS' if ok_true else 'FAIL'}  "
      f"-> expected PASS  {'(OK)' if ok_true else '(!! UNEXPECTED)'}")
print("-"*70)
assert not ok_wrong and ok_true, "Task 3 invariant violated"
print("RESULT: signature is valid ONLY under the true device key; an attacker")
print("without the Pi-resident private key cannot forge a passing attestation.")
