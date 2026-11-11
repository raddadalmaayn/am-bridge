'use strict';
/*
 * Fleet experiment, step 2: N emulated printers commit concurrently.
 *
 * Reads the jobs written by make_fleet_bundles.py and, per scenario and fleet
 * size N, runs N concurrent closed-loop workers (one per printer). Each worker
 * commits its jobs back to back through the same atomic
 * IntegrationContract:RecordProvenanceWithReputation call the bridge uses,
 * retrying contention failures (MVCC_READ_CONFLICT at commit, or mismatched
 * endorsements when peers briefly hold different versions of a hot key) with
 * jittered exponential backoff, as a production bridge would.
 *
 *   independent : every printer rates its own operator (no shared state)
 *   shared      : all printers rate one print-farm operator (shared
 *                 REPUTATION:<operator>:quality key)
 *
 * Asset certification (CreateMaterialCertification) is done untimed first.
 * Usage: node fleet_submit.js jobs_RUN1.jsonl results_RUN1.json
 */
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const NM = process.env.FABRIC_NODE_MODULES ||
  path.join(process.env.HOME, 'AM', 'fabric-test-app', 'node_modules');
const { connect, signers } = require(path.join(NM, '@hyperledger', 'fabric-gateway'));
const grpc = require(path.join(NM, '@grpc', 'grpc-js'));

const TN = path.join(process.env.HOME, 'AM', 'fabric-samples', 'test-network');
const ORG1 = path.join(TN, 'organizations', 'peerOrganizations', 'org1.example.com');
const CHANNEL = 'mychannel', CHAINCODE = 'unified', MSP = 'Org1MSP';
const MVCC_READ_CONFLICT = 11;
const MAX_ATTEMPTS = 100;

const [, , jobsFile, outFile] = process.argv;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const pct = (a, p) => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(p * s.length))]; };
const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;

async function gateway() {
  const tls = fs.readFileSync(path.join(ORG1, 'peers', 'peer0.org1.example.com', 'tls', 'ca.crt'));
  const client = new grpc.Client('localhost:7051', grpc.credentials.createSsl(tls),
    { 'grpc.ssl_target_name_override': 'peer0.org1.example.com' });
  const msp = path.join(ORG1, 'users', 'Admin@org1.example.com', 'msp');
  const keyDir = path.join(msp, 'keystore');
  const cert = fs.readFileSync(path.join(msp, 'signcerts', fs.readdirSync(path.join(msp, 'signcerts'))[0]));
  // The keystore can hold stale keys; use the one matching the signing cert.
  const certPub = new crypto.X509Certificate(cert).publicKey.export({ type: 'spki', format: 'pem' });
  const key = fs.readdirSync(keyDir).map((f) => crypto.createPrivateKey(fs.readFileSync(path.join(keyDir, f))))
    .find((k) => crypto.createPublicKey(k).export({ type: 'spki', format: 'pem' }) === certPub);
  const gw = connect({
    client,
    identity: { mspId: MSP, credentials: cert },
    signer: signers.newPrivateKeySigner(key),
    endorseOptions: () => ({ deadline: Date.now() + 30000 }),
    submitOptions: () => ({ deadline: Date.now() + 30000 }),
    commitStatusOptions: () => ({ deadline: Date.now() + 120000 }),
  });
  return { gw, client, contract: gw.getNetwork(CHANNEL).getContract(CHAINCODE) };
}

// Submit once; returns { ok, code, ms }
async function submitOnce(contract, fn, args) {
  const t0 = performance.now();
  try {
    const tx = await contract.submitAsync(fn, { arguments: args });
    const st = await tx.getStatus();
    return { ok: st.successful, code: st.code, ms: performance.now() - t0 };
  } catch (e) {
    return { ok: false, code: e.code ?? -1, err: String(e.details?.[0]?.message || e.message).slice(0, 160), ms: performance.now() - t0 };
  }
}

async function pool(items, conc, fn) {
  let i = 0;
  await Promise.all(Array.from({ length: conc }, async () => { while (i < items.length) await fn(items[i++]); }));
}

async function main() {
  const jobs = fs.readFileSync(jobsFile, 'utf8').trim().split('\n').map(JSON.parse);
  const { gw, client, contract } = await gateway();
  const out = { started: new Date().toISOString(), batchTimeout: '50ms', levels: [] };
  try {
    // Stake for the submitting identity (idempotent top-up), untimed.
    const st = await submitOnce(contract, 'ReputationContract:AddStake', ['50000']);
    console.log('AddStake:', st.ok ? 'ok' : st);

    const groups = {};
    for (const j of jobs) (groups[`${j.scenario}|${j.n}`] ||= []).push(j);

    for (const [gk, gjobs] of Object.entries(groups)) {
      const [scenario, nStr] = gk.split('|'); const n = Number(nStr);
      // Untimed: certify every asset of this level (distinct keys, no contention).
      let certFail = 0;
      await pool(gjobs, 32, async (j) => {
        const r = await submitOnce(contract, 'ProvenanceContract:CreateMaterialCertification',
          [j.assetId, 'PLA', 'MAT-BATCH-FLEET', 'SupplierPLA', j.gcodeHash]);
        if (!r.ok) certFail++;
      });
      await sleep(500);

      // Timed: n closed-loop printers.
      const byDev = {};
      for (const j of gjobs) (byDev[j.device] ||= []).push(j);
      const rec = [];
      const t0 = performance.now();
      await Promise.all(Object.values(byDev).map(async (devJobs) => {
        for (const j of devJobs) {
          const js = performance.now(); let attempts = 0, mvcc = 0, mismatch = 0, last;
          const args = [j.assetId, 'PRINT_JOB', j.offChainDataHash, j.ratedActor, j.rating, 'quality', j.evidenceHash];
          while (attempts < MAX_ATTEMPTS) {
            attempts++;
            last = await submitOnce(contract, 'IntegrationContract:RecordProvenanceWithReputation', args);
            if (last.ok) break;
            // Retriable contention outcomes: commit-time MVCC conflict, or the two
            // endorsers reading different versions of the hot key (transient).
            if (last.code === MVCC_READ_CONFLICT) mvcc++;
            else if (/ProposalResponsePayloads do not match/.test(last.err || '')) mismatch++;
            else break;
            await sleep(Math.random() * Math.min(400, 25 * 2 ** Math.min(attempts, 4)));
          }
          rec.push({ device: j.device, ok: last.ok, code: last.code, err: last.err, attempts, mvcc, mismatch, latency_ms: performance.now() - js });
        }
      }));
      const wall = (performance.now() - t0) / 1000;
      const okRec = rec.filter((r) => r.ok);
      const attemptsTotal = rec.reduce((a, r) => a + r.attempts, 0);
      const level = {
        scenario, n, jobs: rec.length, committed: okRec.length, cert_failures: certFail,
        wall_s: +wall.toFixed(3), goodput_jobs_per_s: +(okRec.length / wall).toFixed(2),
        latency_ms: okRec.length ? { mean: +mean(okRec.map((r) => r.latency_ms)).toFixed(1), p50: +pct(okRec.map((r) => r.latency_ms), 0.5).toFixed(1), p95: +pct(okRec.map((r) => r.latency_ms), 0.95).toFixed(1) } : null,
        attempts_total: attemptsTotal,
        attempts_per_job: +(attemptsTotal / rec.length).toFixed(2),
        mvcc_conflicts: rec.reduce((a, r) => a + r.mvcc, 0),
        endorsement_mismatches: rec.reduce((a, r) => a + r.mismatch, 0),
        retry_fraction: +((attemptsTotal - rec.length) / attemptsTotal).toFixed(4),
        failures: rec.filter((r) => !r.ok).map((r) => ({ code: r.code, err: r.err })).slice(0, 5),
      };
      // Integrity check for the shared operator: every committed job must be counted once.
      if (scenario === 'shared') {
        const actor = gjobs[0].ratedActor;
        const q = await contract.evaluate('ReputationContract:GetReputation', { arguments: [actor, 'quality'] });
        const rep = JSON.parse(Buffer.from(q).toString());
        level.shared_operator = { actor, total_events: rep.totalEvents ?? rep.TotalEvents, alpha: rep.alpha ?? rep.Alpha, beta: rep.beta ?? rep.Beta };
      }
      out.levels.push(level);
      console.log(`${scenario.padEnd(11)} N=${String(n).padStart(2)} jobs=${level.jobs} ok=${level.committed} ` +
        `goodput=${level.goodput_jobs_per_s} job/s p50=${level.latency_ms?.p50}ms p95=${level.latency_ms?.p95}ms ` +
        `retry=${(level.retry_fraction * 100).toFixed(1)}% (mvcc ${level.mvcc_conflicts}, mismatch ${level.endorsement_mismatches}) att/job=${level.attempts_per_job}` + (level.shared_operator ? ` farmEvents=${level.shared_operator.total_events}` : ''));
      fs.writeFileSync(outFile, JSON.stringify(out, null, 2));
    }
  } finally {
    gw.close(); client.close();
  }
}
main().catch((e) => { console.error(e); process.exit(1); });
