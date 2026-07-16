#!/bin/bash
set -e
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

TEST_NETWORK=~/AM/fabric-samples/test-network
CHAINCODE="unified"; CHANNEL="mychannel"

# ---- args: positional bundle file + optional --skip-material-cert ----------
BUNDLE_FILE="signed_bundle.json"
SKIP_MATERIAL_CERT=false
for arg in "$@"; do
  case "$arg" in
    --skip-material-cert) SKIP_MATERIAL_CERT=true ;;
    *) BUNDLE_FILE="$arg" ;;
  esac
done
STAKE_AMOUNT=50000

export PATH=~/AM/fabric-samples/bin:$PATH
export FABRIC_CFG_PATH=~/AM/fabric-samples/config/

ORDERER_CA="${TEST_NETWORK}/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
ORG1_TLS_CA="${TEST_NETWORK}/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
ORG2_TLS_CA="${TEST_NETWORK}/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"

export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID="Org1MSP"
export CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_TLS_CA"
export CORE_PEER_MSPCONFIGPATH="${TEST_NETWORK}/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
export CORE_PEER_ADDRESS=localhost:7051

INV="-o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile $ORDERER_CA -C $CHANNEL -n $CHAINCODE --peerAddresses localhost:7051 --tlsRootCertFiles $ORG1_TLS_CA --peerAddresses localhost:9051 --tlsRootCertFiles $ORG2_TLS_CA"

echo -e "${YELLOW}==> Reading ${BUNDLE_FILE}...${NC}"
[ ! -f "$BUNDLE_FILE" ] && echo "ERROR: ${BUNDLE_FILE} not found" && exit 1

eval "$(python3 -c "
import json, hashlib
bundle = json.loads(open('$BUNDLE_FILE').read())
p = bundle['payload']; a = p['assessment']
c = json.dumps(bundle, sort_keys=True, separators=(',',':')).encode()
pc = json.dumps(p, sort_keys=True, separators=(',',':')).encode()
print(f'ASSET_ID=\"{p[\"assetId\"]}\"')
print(f'OFF_CHAIN_HASH=\"{hashlib.sha256(c).hexdigest()}\"')
print(f'EVIDENCE_HASH=\"{hashlib.sha256(pc).hexdigest()}\"')
print(f'RATING_VALUE=\"{a[\"rating_value\"]}\"')
print(f'GCODE_HASH=\"{p[\"design\"][\"gcode_sha256\"]}\"')
print(f'OUTCOME=\"{p[\"outcome\"]}\"')
print(f'DEVICE_ID=\"{bundle[\"attestation\"][\"device_id\"]}\"')
")"

RATED_ACTOR="operator-secnet"; DIMENSION="quality"
echo "  Asset: ${ASSET_ID}  Hash: ${OFF_CHAIN_HASH}  Rating: ${RATING_VALUE}  Outcome: ${OUTCOME}"

echo -e "\n${YELLOW}==> Step 0: Add stake (${STAKE_AMOUNT} units, idempotent)...${NC}"
peer chaincode invoke $INV \
  -c "{\"function\":\"ReputationContract:AddStake\",\"Args\":[\"${STAKE_AMOUNT}\"]}"
echo -e "${GREEN}✅ Stake added (caller now above ${STAKE_AMOUNT} min)${NC}"; sleep 3

if [ "$SKIP_MATERIAL_CERT" = true ]; then
  echo -e "\n${YELLOW}==> Step 1: Material certification SKIPPED (--skip-material-cert)${NC}"
else
  echo -e "\n${YELLOW}==> Step 1: Material certification...${NC}"
  # Tolerate the "already exists" case so re-runs of the same asset don't abort.
  set +e
  CERT_OUT=$(peer chaincode invoke $INV \
    -c "{\"function\":\"ProvenanceContract:CreateMaterialCertification\",\"Args\":[\"${ASSET_ID}\",\"PLA\",\"MAT-BATCH-f4u2\",\"SupplierPLA\",\"${GCODE_HASH}\"]}" 2>&1)
  CERT_RC=$?
  set -e
  echo "$CERT_OUT"
  if [ $CERT_RC -ne 0 ]; then
    if echo "$CERT_OUT" | grep -qiE "already exists"; then
      echo -e "${YELLOW}⚠ Asset already certified — continuing (re-run of same asset)${NC}"
    else
      echo -e "ERROR: material certification failed"; exit 1
    fi
  else
    echo -e "${GREEN}✅ Material certification recorded${NC}"
  fi
  sleep 3
fi

echo -e "\n${YELLOW}==> Step 2: PRINT_JOB with real capture data...${NC}"
peer chaincode invoke $INV \
  -c "{\"function\":\"IntegrationContract:RecordProvenanceWithReputation\",\"Args\":[\"${ASSET_ID}\",\"PRINT_JOB\",\"${OFF_CHAIN_HASH}\",\"${RATED_ACTOR}\",\"${RATING_VALUE}\",\"${DIMENSION}\",\"${EVIDENCE_HASH}\"]}"
echo -e "${GREEN}✅ Print job + reputation recorded${NC}"; sleep 3

echo -e "\n${YELLOW}==> Step 3: Asset record${NC}"
peer chaincode query -C $CHANNEL -n $CHAINCODE \
  -c "{\"function\":\"ProvenanceContract:ReadAsset\",\"Args\":[\"${ASSET_ID}\"]}" | python3 -m json.tool

echo -e "\n${YELLOW}==> Step 4: Provenance history${NC}"
peer chaincode query -C $CHANNEL -n $CHAINCODE \
  -c "{\"function\":\"ProvenanceContract:GetAssetHistory\",\"Args\":[\"${ASSET_ID}\"]}" | python3 -m json.tool

echo -e "\n${YELLOW}==> Step 5: Linked ratings${NC}"
peer chaincode query -C $CHANNEL -n $CHAINCODE \
  -c "{\"function\":\"IntegrationContract:GetLinkedRatingsForAsset\",\"Args\":[\"${ASSET_ID}\"]}" | python3 -m json.tool

echo -e "\n${YELLOW}==> Step 6: Operator reputation${NC}"
peer chaincode query -C $CHANNEL -n $CHAINCODE \
  -c "{\"function\":\"ReputationContract:GetReputation\",\"Args\":[\"${RATED_ACTOR}\",\"${DIMENSION}\"]}" | python3 -m json.tool

echo -e "\n${YELLOW}==> Step 7: Part trust report${NC}"
peer chaincode query -C $CHANNEL -n $CHAINCODE \
  -c "{\"function\":\"IntegrationContract:GetPartTrustReport\",\"Args\":[\"${ASSET_ID}\"]}" | python3 -m json.tool

echo -e "\n${GREEN}====== Submission complete. offChainDataHash: ${OFF_CHAIN_HASH} ======${NC}"
