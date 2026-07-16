# Source this for peer CLI access (Org1 admin) — mirrors submit_provenance.sh
TEST_NETWORK=~/AM/fabric-samples/test-network
export PATH=~/AM/fabric-samples/bin:$PATH
export FABRIC_CFG_PATH=~/AM/fabric-samples/config/
export ORDERER_CA="${TEST_NETWORK}/organizations/ordererOrganizations/example.com/orderers/orderer.example.com/msp/tlscacerts/tlsca.example.com-cert.pem"
export ORG1_TLS_CA="${TEST_NETWORK}/organizations/peerOrganizations/org1.example.com/peers/peer0.org1.example.com/tls/ca.crt"
export ORG2_TLS_CA="${TEST_NETWORK}/organizations/peerOrganizations/org2.example.com/peers/peer0.org2.example.com/tls/ca.crt"
export CORE_PEER_TLS_ENABLED=true
export CORE_PEER_LOCALMSPID="Org1MSP"
export CORE_PEER_TLS_ROOTCERT_FILE="$ORG1_TLS_CA"
export CORE_PEER_MSPCONFIGPATH="${TEST_NETWORK}/organizations/peerOrganizations/org1.example.com/users/Admin@org1.example.com/msp"
export CORE_PEER_ADDRESS=localhost:7051
export INV="-o localhost:7050 --ordererTLSHostnameOverride orderer.example.com --tls --cafile $ORDERER_CA -C mychannel -n unified --peerAddresses localhost:7051 --tlsRootCertFiles $ORG1_TLS_CA --peerAddresses localhost:9051 --tlsRootCertFiles $ORG2_TLS_CA"
