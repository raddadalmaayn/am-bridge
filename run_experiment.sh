#!/bin/bash
# run_experiment.sh -- one-run orchestrator for the physical-to-chain bridge.
#
# Usage:
#   ./run_experiment.sh <run_name> <gcode_file> <asset_id> [--skip-material-cert]
#
# Tomorrow's lab plan:
#   Run 1: ./run_experiment.sh cube_done calibration_cube_20mm.gcode PART-CUBE-001
#   Run 2: ./run_experiment.sh cube_anomaly calibration_cube_20mm.gcode PART-CUBE-002
#     (during print: send M104 S215 via OctoPrint terminal, wait 60s, send M104 S200)
#   Run 3: ./run_experiment.sh cube_repeat calibration_cube_20mm.gcode PART-CUBE-003
#   After all runs: python3 benchmark_bridge.py bundle_*.json
#   Generate figures: python3 generate_figures.py --bundles bundle_*.json --captures capture_*.jsonl

set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

RUN_NAME="$1"; GCODE="$2"; ASSET_ID="$3"; SKIP_FLAG="$4"

if [ -z "$RUN_NAME" ] || [ -z "$GCODE" ] || [ -z "$ASSET_ID" ]; then
  echo -e "${RED}Usage: ./run_experiment.sh <run_name> <gcode_file> <asset_id> [--skip-material-cert]${NC}"
  exit 1
fi

BUNDLE="bundle_${RUN_NAME}.json"
CAPTURE="capture_${RUN_NAME}.jsonl"

# 1) environment ------------------------------------------------------------
echo -e "${YELLOW}==> [1/7] Checking OctoPrint environment...${NC}"
if [ -z "$OCTOPRINT_URL" ] || [ -z "$OCTOPRINT_API_KEY" ]; then
  echo -e "${RED}ERROR: OCTOPRINT_URL and OCTOPRINT_API_KEY must be set.${NC}"
  echo "  export OCTOPRINT_URL=\"http://<octoprint-host>:5000\""
  echo "  export OCTOPRINT_API_KEY=\"<your rotated app key>\""
  exit 1
fi
echo -e "${GREEN}  OCTOPRINT_URL=${OCTOPRINT_URL}${NC}"

# 2) gcode + hash -----------------------------------------------------------
echo -e "\n${YELLOW}==> [2/7] Checking G-code file...${NC}"
if [ ! -f "$GCODE" ]; then
  echo -e "${RED}ERROR: gcode file '$GCODE' not found.${NC}"; exit 1
fi
GCODE_SHA=$(sha256sum "$GCODE" | awk '{print $1}')
echo -e "${GREEN}  $GCODE${NC}"
echo "  SHA-256: $GCODE_SHA"

# 3) capture ----------------------------------------------------------------
echo -e "\n${YELLOW}==> [3/7] Starting capture (run=${RUN_NAME})...${NC}"
echo "  Start the print in OctoPrint now; the recorder stops itself at job end."
python3 capture_poll.py --run-name "$RUN_NAME" --gcode "$GCODE" --asset "$ASSET_ID"

# 4) assessment summary -----------------------------------------------------
echo -e "\n${YELLOW}==> [4/7] Assessment summary${NC}"
if [ ! -f "$BUNDLE" ]; then
  echo -e "${RED}ERROR: expected bundle '$BUNDLE' was not produced.${NC}"; exit 1
fi
python3 -c "
import json
b=json.load(open('$BUNDLE'))
a=b['payload']['assessment']
print('  outcome   :', b['payload']['outcome'])
print('  quality   :', a.get('quality'))
print('  compliance:', a.get('compliance'))
print('  delivery  :', a.get('delivery'))
print('  rating    :', a.get('rating_value'))
print('  thermal samples (printing/total):',
      a.get('thermal_samples_total'), '/', a.get('thermal_samples_total_unfiltered'))
"

# 5) optional Fabric submission --------------------------------------------
echo -e "\n${YELLOW}==> [5/7] Submit to Fabric?${NC}"
read -r -p "  Submit bundle '$BUNDLE' to Fabric? (y/n) " ANS
if [ "$ANS" = "y" ] || [ "$ANS" = "Y" ]; then
  ./submit_provenance.sh "$BUNDLE" $SKIP_FLAG
else
  echo "  Skipped Fabric submission."
fi

# 6) independent verify -----------------------------------------------------
echo -e "\n${YELLOW}==> [6/7] Verifying bundle integrity...${NC}"
python3 -c "
import json, attestation as att
b=json.load(open('$BUNDLE'))
och=att.off_chain_hash(b)
ok,reasons=att.verify_bundle(b, ledger_off_chain_hash=och,
                             registered_pubkey_hex=b['attestation']['pubkey'])
print('  result:', 'ACCEPT' if ok else 'REJECT')
[print('   -', r) for r in reasons]
import sys; sys.exit(0 if ok else 1)
"

# 7) done -------------------------------------------------------------------
echo -e "\n${GREEN}==> [7/7] Run ${RUN_NAME} complete. Files: ${CAPTURE}, ${BUNDLE}${NC}"
