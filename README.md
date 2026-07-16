# am-bridge

Physical-to-chain attestation bridge for additive manufacturing provenance.
During a print, a recorder polls the printer's OctoPrint API (read-only),
builds a canonical telemetry bundle that binds the certified design (G-code
SHA-256), the commanded process envelope, the observed telemetry, and the job
outcome into one unit, signs it with an Ed25519 device key, and anchors the
bundle hash on Hyperledger Fabric through a unified provenance + reputation
chaincode. The result is tamper-evident evidence that a specific physical
build matches the design that was certified on-chain.

**Trust ladder.** The design is organized as a four-tier trust ladder: T0
(naive self-reported submission), T1 (edge-signed telemetry bundles), T2
(on-chain device registry), and T3 (hardware root of trust), each stating
explicitly which attacks it defeats and which it does not. This repository
implements the T1 tier end-to-end on an unmodified consumer Ender-3 printer.

Author: Raddad Almaayn

## Quickstart

```bash
# 1. Record: poll the printer during a build (or --simulate without one)
export OCTOPRINT_URL="http://<octoprint-host>:5000"
export OCTOPRINT_API_KEY="<your app key>"
python3 capture_poll.py --gcode calibration_cube_20mm.gcode \
    --asset PART-CUBE-001 --rated-actor operator-secnet

# 2. Attest: the recorder signs the bundle via attestation.py on job end,
#    producing bundle_<run>.json (device key generated on first use)

# 3. Submit: anchor the bundle hash on Fabric and record the linked rating
./submit_provenance.sh bundle_cube_done.json

# Or run a full lab session end to end:
./run_experiment.sh cube_done calibration_cube_20mm.gcode PART-CUBE-001
```

## Layout

```
attestation.py              Ed25519 signing, canonical JSON, bundle verification
capture_poll.py             telemetry recorder (OctoPrint polling, JSONL log)
submit_provenance.sh        Fabric submission: certify, record, query trust report
run_experiment.sh           one-run orchestrator (record -> attest -> submit)
generate_cube_gcode.py      calibration cube G-code generator
generate_bracket_gcode.py   bracket G-code generator
benchmark_bridge.py         bundle latency / scaling benchmark
generate_figures.py         evaluation figures from bundles + captures
bundle_*.json               signed telemetry bundles (evaluation data)
capture_*.jsonl             raw telemetry logs (evaluation data)
experiments/attack-matrix/  attack experiments: replay, tamper, wrong key,
                            in-flight edit, build substitution (+ raw logs)
figures/                    generated evaluation figures
paper/                      LaTeX sources for the paper
```
