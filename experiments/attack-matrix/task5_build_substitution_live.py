#!/usr/bin/env python3
"""Task 5(d) LIVE — build & sign the design-substitution bundle from REAL telemetry.

Asset PART-CUBE-SUBST-LIVE-01 certified on-chain against the ORIGINAL cube design.
The operator physically printed the MODIFIED cube (real Ender-3 run, captured via
OctoPrint poll). The bundle carries the certified (original) design envelope but
the executed hash of what actually ran (modified). assess() -> compliance = 0 ->
Eq.2 vetoes the 0.25 compliance term: r = 0.6q + 0.15d.

Telemetry here is REAL (source=OCTOPRINT_POLL), NOT simulated.
"""
import json, sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import attestation as att

BRIDGE = _ROOT
ORIG_GCODE = BRIDGE / "calibration_cube_20mm.gcode"          # certified design
MOD_GCODE  = BRIDGE / "experiments/attack-matrix/cube_substituted_20mm.gcode"
JSONL = BRIDGE / "experiments/attack-matrix/capture_cube_substituted_live.jsonl"
OUTDIR = BRIDGE / "experiments/attack-matrix"
ASSET = "PART-CUBE-SUBST-LIVE-01"

expected = att.parse_gcode_envelope(str(ORIG_GCODE))         # certified/original
modified_hash = att.sha256_hex(MOD_GCODE.read_bytes())       # what actually ran

# Load the REAL captured samples (durable JSONL from the live OctoPrint poll).
samples = [json.loads(l) for l in JSONL.read_text().splitlines() if l.strip()]
printing = [s for s in samples if "printing" in (s.get("state") or "").lower()]
actual_time_s = int(samples[-1]["t"] - samples[0]["t"]) if len(samples) > 1 else 0

observed = {
    "source": "OCTOPRINT_POLL",          # REAL, not simulated
    "tolerance_c": 8.0,
    "actual_time_s": actual_time_s,
    "executed_gcode_sha256": modified_hash,   # <-- substitution: MODIFIED cube ran
    "samples": samples,
}

payload = att.build_payload(ASSET, expected, observed, outcome="PrintDone",
                            started="(live capture start)", ended="(live capture end)")
a = payload["assessment"]
q, c, d = a["quality"], a["compliance"], a["delivery"]
r_reported = a["rating_value"]                    # 0.6q + 0.25c + 0.15d  (c=0 here)
r_eq2_veto = round(0.6 * q + 0.15 * d, 4)         # compliance vetoed (c=0)
r_if_compliant = round(0.6 * q + 0.25 * 1.0 + 0.15 * d, 4)  # counterfactual c=1

key = att.DeviceKey.load_or_create(str(BRIDGE / "device_key.pem"))
bundle = att.sign_bundle(payload, key)
och = att.off_chain_hash(bundle)
evh = att.sha256_hex(att.canonical(payload))

out_bundle = OUTDIR / "bundle_cube_substituted_live.json"
out_bundle.write_text(json.dumps(bundle, indent=2))

print("-"*70)
print("Task 5(d) LIVE: design-substitution bundle from REAL telemetry")
print("-"*70)
print(f"telemetry source                 : {observed['source']}  (SIMULATED? {'SIMULAT' in observed['source']})")
print(f"total samples / printing-state    : {len(samples)} / {len(printing)}")
print(f"actual_time_s (capture window)   : {actual_time_s}")
print(f"certified (original) design hash : {expected['gcode_sha256']}")
print(f"executed  (modified) gcode hash  : {modified_hash}")
print(f"executed == certified?           : {modified_hash == expected['gcode_sha256']}")
print()
print(f"q (quality)    = {q}   (thermal in-tol {a['thermal_samples_in_tol']}/{a['thermal_samples_total']})")
print(f"c (compliance) = {c}")
print(f"d (delivery)   = {d}")
print(f"r  reported by assess() (0.6q+0.25c+0.15d) = {r_reported}")
print(f"r  Eq.2 veto            (0.6q+0.15d, c=0)  = {r_eq2_veto}")
print(f"r  IF compliant         (0.6q+0.25+0.15d)  = {r_if_compliant}  (counterfactual)")
print()
print(f"offChainDataHash = {och}")
print(f"evidenceHash     = {evh}")
print(f"ratingValue      = {r_reported}")
print()
print(f"signed bundle -> {out_bundle}")
print("COMMIT_ASSET=" + ASSET)
print("COMMIT_OCH=" + och)
print("COMMIT_EVH=" + evh)
print("COMMIT_RV=" + str(r_reported))
print("N_SAMPLES=" + str(len(samples)))
print("N_PRINTING=" + str(len(printing)))
print("R_IF_COMPLIANT=" + str(r_if_compliant))
assert c == 0.0, "expected compliance veto"
assert "SIMULAT" not in observed["source"], "must be real telemetry"
