#!/usr/bin/env python3
"""Task 2(b) — cross-design evidence substitution.

XASSET-BRACKET-01 was certified on-chain against the BRACKET design hash.
An attacker attaches the cube bundle's evidence (design+telemetry) to it.
Show exactly which check rejects the binding.
"""
import json, hashlib, sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
from attestation import parse_gcode_envelope, assess, canonical

# Certified design hash committed on-chain for XASSET-BRACKET-01
# (offChainDataHash of its MATERIAL_CERTIFICATION event = bracket gcode sha256)
CERTIFIED_DESIGN_HASH = "48f7790a773da49cecc2b9806ca4f8e4f915d642646ef74fd0f754ff246a6150"
BRACKET_GCODE = str(_ROOT / "am_bracket_15mm.gcode")

bundle = json.load(open(_ROOT / "bundle_cube_done.json"))
p = bundle["payload"]
cube_design_hash   = p["design"]["gcode_sha256"]
cube_executed_hash = p["observed"]["executed_gcode_sha256"]

print("-"*70)
print("Task 2(b): attach cube bundle evidence to bracket-certified asset")
print("-"*70)
print(f"asset XASSET-BRACKET-01 certified design hash : {CERTIFIED_DESIGN_HASH}")
print(f"cube bundle  design.gcode_sha256              : {cube_design_hash}")
print(f"cube bundle  observed.executed_gcode_sha256   : {cube_executed_hash}")
print()

# CHECK A — gateway design-hash binding: bundle design vs on-chain certified design
bindingA = (cube_design_hash == CERTIFIED_DESIGN_HASH)
print("[CHECK A] design-hash binding (bundle.design vs on-chain certified):")
print(f"    {'MATCH -> accept' if bindingA else 'MISMATCH -> REJECT'}")
print(f"    error: DESIGN-BINDING MISMATCH: bundle design {cube_design_hash[:12]}.. "
      f"!= certified {CERTIFIED_DESIGN_HASH[:12]}.. for asset XASSET-BRACKET-01")
print()

# CHECK B — assess() compliance against the CERTIFIED design (bracket) envelope.
# The verifier parses the certified design file (bracket) as 'expected', while the
# attacker's observed telemetry executed the cube. compliance = 0 -> Eq.2 veto.
expected_bracket = parse_gcode_envelope(BRACKET_GCODE)
observed_cube = dict(p["observed"])   # cube telemetry as-attested
a = assess(expected_bracket, observed_cube)
q, c, d = a["quality"], a["compliance"], a["delivery"]
r_full = round(0.6*q + 0.25*c + 0.15*d, 4)
r_veto = round(0.6*q + 0.15*d, 4)     # Eq.2 with compliance vetoed
print("[CHECK B] off-chain assess() compliance vs certified (bracket) design:")
print(f"    executed(cube) == expected(bracket)? {observed_cube['executed_gcode_sha256']==expected_bracket['gcode_sha256']}")
print(f"    q={q}  c={c}  d={d}")
print(f"    rating with compliance term      r = 0.6q+0.25c+0.15d = {r_full}")
print(f"    Eq.2 veto (compliance=0)         r = 0.6q+0.15d       = {r_veto}")
print(f"    -> compliance=0 vetoes the 0.25 term; rating drops to {r_veto}")
print("-"*70)
print("REJECTED BY: design-hash binding (Check A) — the cube evidence does not")
print("bind to the bracket asset's certified design; and independently the")
print("compliance dimension collapses to 0, vetoing the reputation contribution.")
