#!/usr/bin/env python3
"""Task 5(d) — build & sign the design-substitution bundle (SIMULATED telemetry).

Scenario: asset PART-CUBE-SUBST-01 was certified on-chain against the ORIGINAL
cube design. The operator actually executed the MODIFIED cube G-code. The bundle
therefore carries the certified (original) design envelope but the executed hash
of what really ran (modified). assess() -> compliance = 0 -> Eq.2 vetoes the
0.25 compliance term: r = 0.6q + 0.15d.

Telemetry here is SIMULATED (no printer this run) and is tagged as such; the
substitution mechanic (executed != certified design) is real, not simulated.
"""
import json, math, sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
import attestation as att

BRIDGE = _ROOT
ORIG_GCODE = BRIDGE / "calibration_cube_20mm.gcode"           # certified design
MOD_GCODE  = BRIDGE / "experiments/attack-matrix/cube_substituted_20mm.gcode"
OUTDIR = BRIDGE / "experiments/attack-matrix"
ASSET = "PART-CUBE-SUBST-01"

expected = att.parse_gcode_envelope(str(ORIG_GCODE))          # certified/original
modified_hash = att.sha256_hex(MOD_GCODE.read_bytes())        # what actually ran

# Simulated-but-coherent thermal trace at the CERTIFIED targets (200/50):
# quality stays high so the veto is attributable purely to compliance.
noz = expected["expected_nozzle_c"] or 200.0
bed = expected["expected_bed_c"] or 50.0
samples = []
for i in range(0, 300, 15):                # ~5 min at 15s cadence (short run)
    ramp = min(1.0, i / 90.0)
    samples.append({
        "t": 1000 + i,
        "nozzle_c": round(noz + math.sin(i) * 0.6, 1) if ramp >= 1.0 else round(noz * ramp, 1),
        "bed_c": round(bed + math.cos(i) * 0.4, 1) if ramp >= 1.0 else round(bed * ramp, 1),
        "state": "Printing",
    })

# Durable capture log (new file; does not touch published captures)
cap_log = OUTDIR / "capture_cube_substituted.jsonl"
with cap_log.open("w") as fh:
    for s in samples:
        fh.write(json.dumps(s) + "\n")

observed = {
    "source": "SIMULATED_NO_PRINTER",
    "tolerance_c": 8.0,
    "actual_time_s": samples[-1]["t"] - samples[0]["t"],
    "executed_gcode_sha256": modified_hash,        # <-- the substitution: MODIFIED ran
    "samples": samples,
}

payload = att.build_payload(ASSET, expected, observed, outcome="PrintCancelled",
                            started="(sim start)", ended="(sim cancel)")
a = payload["assessment"]
q, c, d = a["quality"], a["compliance"], a["delivery"]
r_reported = a["rating_value"]                     # 0.6q + 0.25c + 0.15d
r_eq2_veto = round(0.6 * q + 0.15 * d, 4)          # compliance vetoed (c=0)

key = att.DeviceKey.load_or_create(str(BRIDGE / "device_key.pem"))
bundle = att.sign_bundle(payload, key)
och = att.off_chain_hash(bundle)
evh = att.sha256_hex(att.canonical(payload))

out_bundle = OUTDIR / "bundle_cube_substituted.json"
out_bundle.write_text(json.dumps(bundle, indent=2))

print("-"*70)
print("Task 5(d): design-substitution bundle assessment")
print("-"*70)
print(f"certified (original) design hash : {expected['gcode_sha256']}")
print(f"executed  (modified) gcode hash  : {modified_hash}")
print(f"executed == certified?           : {modified_hash == expected['gcode_sha256']}")
print()
print(f"q (quality)    = {q}")
print(f"c (compliance) = {c}")
print(f"d (delivery)   = {d}")
print(f"r  reported by assess() (0.6q+0.25c+0.15d) = {r_reported}")
print(f"r  Eq.2 veto            (0.6q+0.15d, c=0)  = {r_eq2_veto}")
print(f"   -> compliance=0 removes the 0.25 term; both equal {r_reported} since c=0")
print()
print(f"offChainDataHash = {och}")
print(f"evidenceHash     = {evh}")
print(f"ratingValue      = {r_reported}")
print()
print(f"capture log   -> {cap_log}")
print(f"signed bundle -> {out_bundle}")
# Emit the commit args for the shell step
print("COMMIT_ASSET=" + ASSET)
print("COMMIT_OCH=" + och)
print("COMMIT_EVH=" + evh)
print("COMMIT_RV=" + str(r_reported))
assert c == 0.0, "expected compliance veto"
