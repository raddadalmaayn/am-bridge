#!/usr/bin/env python3
"""
T1 attestation core for the physical-to-chain provenance bridge.

Scope of THIS module (the integrity layer only):
  - parse the *expected* envelope + content hash from a G-code file
  - assemble a deterministic, canonical telemetry "bundle" (expected vs observed)
  - sign the bundle with a Pi-resident Ed25519 *device* key
  - derive the offChainDataHash that gets committed on the Fabric ledger
  - verify a bundle two independent ways and demonstrate tamper-detection

What it deliberately does NOT do yet (next increments):
  - live OctoPrint capture (runs as an event hook/plugin ON THE PI)
  - Fabric gateway submission (cloudnode, under the org MSP)
  - on-chain signature verification / device registry (that is the T2 fork)

Trust model (T1): the device key lives on the box wired to the printer; the
bundle it signs is the unit of evidence. Anyone altering the stored bundle
breaks BOTH the ledger hash commitment and the device signature. T1 does NOT
defend against a party that controls the device key AND fabricates the
telemetry at source (garbage-in) -- that is the honest boundary, addressed
only by T3 (TEE / signed sensors / threshold attestation).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives import serialization


# ---------------------------------------------------------------------------
# Canonicalisation -- MUST match on the verifier side (incl. the Go chaincode)
# ---------------------------------------------------------------------------
def canonical(obj) -> bytes:
    """Deterministic JSON: sorted keys, no whitespace, UTF-8.

    The offChainDataHash committed on-chain is sha256 over this encoding, so any
    verifier (Python here, Go on the peer) recomputes the identical bytes.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# G-code: real content hash + the commanded/expected envelope from the header
# ---------------------------------------------------------------------------
def parse_gcode_envelope(path: str) -> dict:
    raw = Path(path).read_bytes()
    gcode_sha256 = sha256_hex(raw)
    text = raw.decode("utf-8", errors="replace")

    def find(pat, cast=str, default=None):
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        return cast(m.group(1)) if m else default

    # Commanded temperatures: M104/M109 = nozzle, M140/M190 = bed (first set).
    nozzle = find(r"^M10[49]\s+S(\d+(?:\.\d+)?)", float)
    bed = find(r"^M1[49]0\s+S(\d+(?:\.\d+)?)", float)

    return {
        "gcode_filename": Path(path).name,
        "gcode_sha256": gcode_sha256,
        "gcode_bytes": len(raw),
        "slicer": find(r"^;Generated with (.+?)\s*$"),
        "flavor": find(r"^;FLAVOR:(.+?)\s*$"),
        "target_machine": find(r"^;TARGET_MACHINE\.NAME:(.+?)\s*$"),
        "expected_nozzle_c": nozzle,
        "expected_bed_c": bed,
        "expected_layers": find(r"^;LAYER_COUNT:(\d+)", int),
        "expected_time_s": find(r"^;TIME:(\d+)", int),
        "filament_m": find(r"^;Filament used:\s*([\d.]+)m", float),
        "layer_height_mm": find(r"^;Layer height:\s*([\d.]+)", float),
    }


# ---------------------------------------------------------------------------
# Observed-vs-expected -> per-dimension reputation signal
# (placeholder policy -- to be justified empirically, integration-contract #3)
# ---------------------------------------------------------------------------
def assess(expected: dict, observed: dict) -> dict:
    """Map physical adherence to the [0,1] dimensions the chaincode consumes.

    quality    : fraction of nozzle+bed samples within tolerance of target
    delivery   : actual duration vs estimated (1.0 if <= estimate, decays after)
    compliance : 1.0 iff the executed G-code hash matches the certified design
    The aggregate ratingValue is the gate-relevant scalar for PRINT_JOB.
    """
    tol_c = observed.get("tolerance_c", 8.0)
    samples = observed.get("samples", [])

    def within(actual, target):
        return target is not None and actual is not None and abs(actual - target) <= tol_c

    def is_printing(s):
        # Thermal quality is only meaningful while the machine is actively
        # printing. Idle/room-temperature readings (state "Operational" or no
        # state) are excluded so they do not dilute at-target tracking.
        return "printing" in (s.get("state") or "").lower()

    printing_samples = [s for s in samples if is_printing(s)]

    hits = total = 0
    for s in printing_samples:
        for actual, target in (("nozzle_c", "expected_nozzle_c"),
                               ("bed_c", "expected_bed_c")):
            if s.get(actual) is not None:
                total += 1
                hits += 1 if within(s[actual], expected.get(target)) else 0
    quality = (hits / total) if total else 0.0

    est = expected.get("expected_time_s")
    act = observed.get("actual_time_s")
    if est and act:
        delivery = 1.0 if act <= est else max(0.0, 1.0 - (act - est) / est)
    else:
        delivery = 0.0

    compliance = 1.0 if observed.get("executed_gcode_sha256") == expected.get("gcode_sha256") else 0.0

    rating_value = round(0.6 * quality + 0.25 * compliance + 0.15 * delivery, 4)
    return {
        "quality": round(quality, 4),
        "delivery": round(delivery, 4),
        "compliance": round(compliance, 4),
        "thermal_samples_in_tol": hits,
        "thermal_samples_total": total,
        "thermal_samples_total_unfiltered": sum(
            1 for s in samples for a in ("nozzle_c", "bed_c") if s.get(a) is not None),
        "rating_value": rating_value,
    }


# ---------------------------------------------------------------------------
# Device key (Ed25519) -- lives on the Pi in the real deployment
# ---------------------------------------------------------------------------
class DeviceKey:
    def __init__(self, priv: Ed25519PrivateKey):
        self._priv = priv
        self.pub = priv.public_key()

    @classmethod
    def load_or_create(cls, path: str) -> "DeviceKey":
        p = Path(path)
        if p.exists():
            priv = serialization.load_pem_private_key(p.read_bytes(), password=None)
        else:
            priv = Ed25519PrivateKey.generate()
            p.write_bytes(priv.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption()))
        return cls(priv)

    @property
    def pubkey_hex(self) -> str:
        return self.pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw).hex()

    @property
    def device_id(self) -> str:
        # Mirrors the chaincode's short-hash identity style; T2 registry key.
        return "DEV:" + sha256_hex(bytes.fromhex(self.pubkey_hex))[:16]

    def sign_hex(self, data: bytes) -> str:
        return self._priv.sign(data).hex()


def verify_sig(pubkey_hex: str, signature_hex: str, data: bytes) -> bool:
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(pubkey_hex)).verify(
            bytes.fromhex(signature_hex), data)
        return True
    except (InvalidSignature, ValueError):
        return False


# ---------------------------------------------------------------------------
# Bundle assembly + signing + the on-chain commitment
# ---------------------------------------------------------------------------
def build_payload(asset_id: str, expected: dict, observed: dict,
                  outcome: str, started: str, ended: str) -> dict:
    return {
        "schema": "am-provenance/telemetry-bundle/v1",
        "assetId": asset_id,
        "eventType": "PRINT_JOB",
        "machine": expected.get("target_machine"),
        "design": {k: expected[k] for k in
                   ("gcode_filename", "gcode_sha256", "gcode_bytes",
                    "slicer", "flavor", "expected_nozzle_c", "expected_bed_c",
                    "expected_layers", "expected_time_s", "filament_m")},
        "observed": observed,
        "assessment": assess(expected, observed),
        "outcome": outcome,
        "window": {"started": started, "ended": ended},
    }


def sign_bundle(payload: dict, key: DeviceKey) -> dict:
    sig = key.sign_hex(canonical(payload))   # device signs the payload only
    return {
        "payload": payload,
        "attestation": {
            "alg": "Ed25519",
            "signed_field": "payload",
            "device_id": key.device_id,
            "pubkey": key.pubkey_hex,
            "signature": sig,
        },
    }


def off_chain_hash(signed_bundle: dict) -> str:
    """The value committed on-chain as ProvenanceEvent.OffChainDataHash."""
    return sha256_hex(canonical(signed_bundle))


def verify_bundle(signed_bundle: dict, ledger_off_chain_hash: str | None = None,
                  registered_pubkey_hex: str | None = None):
    """Two independent checks; returns (ok, reasons)."""
    reasons = []
    att = signed_bundle["attestation"]

    if ledger_off_chain_hash is not None:
        recomputed = off_chain_hash(signed_bundle)
        if recomputed != ledger_off_chain_hash:
            reasons.append(f"LEDGER-HASH MISMATCH: stored evidence != on-chain commitment "
                           f"({recomputed[:12]}.. vs {ledger_off_chain_hash[:12]}..)")

    if not verify_sig(att["pubkey"], att["signature"], canonical(signed_bundle["payload"])):
        reasons.append("DEVICE SIGNATURE INVALID: payload not signed by claimed device key")

    if registered_pubkey_hex is not None and att["pubkey"] != registered_pubkey_hex:
        reasons.append("UNREGISTERED DEVICE: pubkey not in device registry (T2 check)")

    return (len(reasons) == 0, reasons)


def chaincode_args(asset_id: str, signed_bundle: dict, rated_actor: str,
                   dimension: str = "quality") -> dict:
    """The argument tuple for IntegrationContract:RecordProvenanceWithReputation."""
    payload = signed_bundle["payload"]
    return {
        "fn": "RecordProvenanceWithReputation",
        "assetID": asset_id,
        "eventType": "PRINT_JOB",
        "offChainDataHash": off_chain_hash(signed_bundle),
        "ratedActorID": rated_actor,
        "ratingValue": f'{payload["assessment"]["rating_value"]}',
        "dimension": dimension,
        "evidenceHash": sha256_hex(canonical(payload)),
    }


# ---------------------------------------------------------------------------
# Demo: real f4u2.gcode -> sign -> commitment -> verify -> tamper -> reject
# ---------------------------------------------------------------------------
def _demo(gcode_path: str):
    bar = "-" * 70
    expected = parse_gcode_envelope(gcode_path)
    print(bar); print("1) EXPECTED ENVELOPE (parsed from real G-code)"); print(bar)
    for k in ("gcode_filename", "gcode_sha256", "gcode_bytes", "slicer",
              "target_machine", "expected_nozzle_c", "expected_bed_c",
              "expected_layers", "expected_time_s", "filament_m"):
        print(f"  {k:20s}: {expected[k]}")

    # Observed telemetry: SYNTHETIC PLACEHOLDER. Live capture (OctoPrint event
    # hook on the Pi) replaces this with real client.printer() samples.
    observed = {
        "source": "SYNTHETIC_PLACEHOLDER",
        "tolerance_c": 8.0,
        "actual_time_s": 13980,
        "executed_gcode_sha256": expected["gcode_sha256"],
        "samples": [
            {"t": 0, "nozzle_c": 21.5, "bed_c": 21.6, "state": "Operational"},
            {"t": 120, "nozzle_c": 199.4, "bed_c": 50.2, "state": "Printing"},
            {"t": 1800, "nozzle_c": 201.1, "bed_c": 49.7, "state": "Printing"},
            {"t": 7200, "nozzle_c": 200.3, "bed_c": 50.0, "state": "Printing"},
            {"t": 13000, "nozzle_c": 198.9, "bed_c": 49.5, "state": "Printing"},
        ],
    }

    key = DeviceKey.load_or_create("device_key.pem")
    payload = build_payload("PART-f4u2-0001", expected, observed,
                            outcome="PrintDone",
                            started="2026-06-02T14:00:00Z",
                            ended="2026-06-02T17:53:00Z")
    bundle = sign_bundle(payload, key)
    och = off_chain_hash(bundle)

    print(); print(bar); print("2) ATTESTATION + ON-CHAIN COMMITMENT"); print(bar)
    print(f"  device_id            : {key.device_id}")
    print(f"  assessment           : {payload['assessment']}")
    print(f"  offChainDataHash     : {och}")
    print(); print("  -> Fabric submit args (cloudnode, under org MSP):")
    for k, v in chaincode_args("PART-f4u2-0001", bundle, rated_actor="operator-secnet").items():
        print(f"     {k:18s}= {v}")

    print(); print(bar); print("3) VERIFY (honest evidence)"); print(bar)
    ok, reasons = verify_bundle(bundle, ledger_off_chain_hash=och,
                                registered_pubkey_hex=key.pubkey_hex)
    print(f"  result: {'ACCEPT' if ok else 'REJECT'}  {reasons}")

    print(); print(bar); print("4) TAMPER (flip one observed nozzle sample)"); print(bar)
    bundle["payload"]["observed"]["samples"][0]["nozzle_c"] = 235.0  # overheat hidden
    ok, reasons = verify_bundle(bundle, ledger_off_chain_hash=och,
                                registered_pubkey_hex=key.pubkey_hex)
    print(f"  result: {'ACCEPT' if ok else 'REJECT'}")
    for r in reasons:
        print(f"    - {r}")
    print(bar)
    print("Tampering is caught twice over: the recomputed evidence hash no longer")
    print("matches the on-chain commitment, AND the device signature fails.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else \
        "ender3/Ender3_Printer/f4u2.gcode"
    _demo(path)
