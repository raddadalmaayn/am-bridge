#!/bin/bash
# Task 1 — end-to-end commit latency of RecordProvenanceWithReputation
# 20 sequential invokes with --waitForEvent (endorse -> order -> commit event).
set -e
DIR=~/provenance-bridge/experiments/attack-matrix
source "$DIR/fabric_env.sh"
export FABRIC_LOGGING_SPEC=error
cd ~/provenance-bridge

RUN_TAG=$(date +%Y%m%d-%H%M%S)
LOG="$DIR/raw/task1_latency_$RUN_TAG.log"
CSV="$DIR/raw/task1_latency_$RUN_TAG.csv"
N=20

# Real bundle hashes from bundle_cube_done.json (same derivation as submit_provenance.sh)
eval "$(python3 - <<'EOF'
import json, hashlib
b = json.load(open('bundle_cube_done.json'))
p = b['payload']
c  = json.dumps(b, sort_keys=True, separators=(',',':')).encode()
pc = json.dumps(p, sort_keys=True, separators=(',',':')).encode()
print(f'OFF_CHAIN_HASH="{hashlib.sha256(c).hexdigest()}"')
print(f'EVIDENCE_HASH="{hashlib.sha256(pc).hexdigest()}"')
print(f'RATING_VALUE="{p["assessment"]["rating_value"]}"')
print(f'GCODE_HASH="{p["design"]["gcode_sha256"]}"')
EOF
)"
echo "bundle=bundle_cube_done.json offChainHash=$OFF_CHAIN_HASH rating=$RATING_VALUE" | tee "$LOG"

echo "== Step 0: AddStake 50000 (idempotent) ==" | tee -a "$LOG"
peer chaincode invoke $INV --waitForEvent \
  -c '{"function":"ReputationContract:AddStake","Args":["50000"]}' >>"$LOG" 2>&1
echo "stake ok" | tee -a "$LOG"

echo "== Step 1: certify $N throwaway assets (setup, NOT timed) ==" | tee -a "$LOG"
for i in $(seq -w 1 $N); do
  A="LAT-$RUN_TAG-$i"
  peer chaincode invoke $INV --waitForEvent \
    -c "{\"function\":\"ProvenanceContract:CreateMaterialCertification\",\"Args\":[\"$A\",\"PLA\",\"MAT-BATCH-LAT\",\"SupplierPLA\",\"$GCODE_HASH\"]}" >>"$LOG" 2>&1
  echo "  certified $A"
done

echo "== Step 2: $N timed sequential RecordProvenanceWithReputation ==" | tee -a "$LOG"
echo "iter,asset,ms,rc" > "$CSV"
for i in $(seq -w 1 $N); do
  A="LAT-$RUN_TAG-$i"
  T0=$(date +%s%N)
  set +e
  OUT=$(peer chaincode invoke $INV --waitForEvent \
    -c "{\"function\":\"IntegrationContract:RecordProvenanceWithReputation\",\"Args\":[\"$A\",\"PRINT_JOB\",\"$OFF_CHAIN_HASH\",\"operator-secnet\",\"$RATING_VALUE\",\"quality\",\"$EVIDENCE_HASH\"]}" 2>&1)
  RC=$?
  set -e
  T1=$(date +%s%N)
  MS=$(( (T1 - T0) / 1000000 ))
  echo "$OUT" >> "$LOG"
  echo "$i,$A,$MS,$RC" | tee -a "$CSV"
done

echo "== Stats ==" | tee -a "$LOG"
python3 - "$CSV" <<'EOF' | tee -a "$LOG"
import csv, statistics, sys
rows = [r for r in csv.DictReader(open(sys.argv[1]))]
ok  = [int(r['ms']) for r in rows if r['rc'] == '0']
bad = [r for r in rows if r['rc'] != '0']
ms = sorted(ok)
def pctl(v, p):
    k = (len(v)-1) * p/100
    f, c = int(k), min(int(k)+1, len(v)-1)
    return v[f] + (v[c]-v[f]) * (k-f)
print(f"n={len(ok)} success, {len(bad)} failed")
print(f"mean   = {statistics.mean(ms):.1f} ms")
print(f"median = {statistics.median(ms):.1f} ms")
print(f"p95    = {pctl(ms,95):.1f} ms")
print(f"min/max= {ms[0]} / {ms[-1]} ms")
EOF
echo "CSV: $CSV"
echo "LOG: $LOG"
