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

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24126908.svg)](https://doi.org/10.5281/zenodo.24126908)
Archived release used in the CCNC 2027 paper: `v1.0-ccnc2027`,
doi:[10.5281/zenodo.24126908](https://doi.org/10.5281/zenodo.24126908)
(all versions: doi:[10.5281/zenodo.24126907](https://doi.org/10.5281/zenodo.24126907)).

## Verify the published evidence (no printer, no ledger needed)

```bash
pip install cryptography
python3 verify.py --tamper --replay
```

For each signed bundle, `verify.py` checks the Ed25519 device signature, the
device identity, the on-chain commitment against the `offChainDataHash`
recorded at commit time (`commitments.json`), the design-file hash, and that
the signed assessment is reproduced from the signed telemetry samples. It
also checks that the asset ID signed inside each bundle matches the ledger
asset, and reports the warm-up-excluded quality used in the paper. `--tamper`
shows that editing one stored sample breaks both the commitment and the
signature; `--replay` shows that replaying an untouched bundle onto another
asset of the same design passes both, and is caught only by the asset-ID
check (the chaincode sees only the hash; see the paper, Sec. VI-D). The original testbed ledger is not distributed; the recorded
commitment values come from the commit logs in `experiments/` and the paper.
(`f4u2.gcode` is not part of the public tree, so its design-file check is
skipped.)

## Reproducing the paper's results

| Paper result | Script | Needs |
|---|---|---|
| Table II assessments, signatures, commitments | `verify.py` | nothing |
| Warm-up exclusion, tolerance sweep, 5-30 s decimation (Sec. VI-B) | `analysis/policy_sensitivity.py` | nothing |
| Fig. 3 (signed vs. warm-up-excluded quality per run) | `analysis/fig_assessment.py` | matplotlib |
| Attack matrix (Table III) | `experiments/attack-matrix/` | Fabric |
| Bridge latency (Sec. VI-E) | `benchmark_bridge.py`, `experiments/attack-matrix/task1_latency.sh` | Fabric for commit latency |
| Fleet concurrency (Sec. VI-F) | `experiments/fleet/` (see below) | Fabric |
| Live capture | `capture_poll.py`, `run_experiment.sh` | printer + OctoPrint |

**Fleet experiment.** Emulates 1-64 printers, each with its own Ed25519 key,
re-attesting the four real PLA traces under fresh asset IDs and committing
them concurrently through `IntegrationContract:RecordProvenanceWithReputation`,
either with one operator per printer or with one shared print-farm operator:

```bash
cd experiments/fleet
python3 make_fleet_bundles.py --tag MYRUN --out jobs_MYRUN.jsonl
node fleet_submit.js jobs_MYRUN.jsonl results_MYRUN.json   # needs @hyperledger/fabric-gateway
python3 summarize.py
```

Use a fresh `--tag` for every run: asset IDs must be new, since the chaincode
lifecycle guard rejects a second `PRINT_JOB` on the same asset.

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
verify.py                   one-command verification of all published bundles
commitments.json            on-chain commitments recorded at commit time
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
experiments/fleet/          emulated-fleet concurrency experiment (+ results)
analysis/                   assessment-policy sensitivity analysis
figures/                    generated evaluation figures
paper/                      paper PDF and figure scripts
```

## License and citation

Code and data are released under the MIT License (`LICENSE`). If you use
them, please cite the paper (`CITATION.cff`).
