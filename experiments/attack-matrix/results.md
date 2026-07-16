# T1 Adversarial Attack-Matrix — Empirical Results

**Date:** 2026-07-07 (America/Denver)
**Operator:** lab workstation, Ender-3 testbed
**Network:** Hyperledger Fabric test-network (`~/AM/fabric-samples/test-network`),
2-org `mychannel`, unified three-contract chaincode deployed as CCAAS.
**Bridge:** `~/provenance-bridge/` (attestation.py canonical-bundle / Ed25519 / assess()).
**Constraints honored:** chaincode source unmodified; the five published
`capture_*.jsonl` / `bundle_*.json` and both `.gcode` design files verified
unchanged (SHA-256 unchanged post-run). All new artifacts under
`experiments/attack-matrix/`. Raw per-step logs in `raw/`.

> Task 5 was re-run **LIVE on 2026-07-07** with a real Ender-3 print of the
> modified cube (OctoPrint poll, 100 real telemetry samples, `source=OCTOPRINT_POLL`,
> outcome `PrintDone`). Tasks 1–4 are unchanged from the prior run. The
> substitution mechanic — executed hash ≠ certified design hash → `compliance = 0`
> — is now evidenced with real telemetry, not simulated.

---

## Summary table

| Attack | Mechanism exercised | Observed result | Detected / Rejected by |
|---|---|---|---|
| **Cross-asset replay** (reuse a valid bundle hash on a wrong-stage / uncertified asset) | On-chain lifecycle state machine | `RecordPrintJob` rejected on both a `PRINT_COMPLETE` asset and a nonexistent asset | Chaincode `ProvenanceContract.RecordPrintJob` stage guard (status 500) |
| **Cross-design evidence** (attach cube bundle to a bracket-certified asset) | Design-hash binding + off-chain `assess()` compliance | Binding mismatch; `compliance = 0`, rating drops to `0.6q+0.15d` | Gateway design-hash binding (bundle.design ≠ certified) + `assess()` |
| **Wrong-key attestation** (verify bundle under an attacker keypair) | Ed25519 signature verification | Wrong key → **FAIL**; true key → **PASS** | `attestation.verify_sig` (Ed25519 over canonical payload) |
| **In-flight modification** (flip 1 telemetry byte after signing) | Hash commitment + signature | REJECT twice: ledger-hash mismatch **and** signature invalid | `attestation.verify_bundle` (both checks fire) |
| **Live design substitution** (LIVE Ender-3 print of modified G-code vs certified design) | `assess()` compliance veto → Beta posterior | Real print (100 samples); `compliance = 0`, `r = 0.5005` committed (0.7505 if compliant); operator α-gain cut ~33% | Off-chain `assess()` Eq.2 veto, propagated on-chain via `RecordProvenanceWithReputation` |

---

## Task 1 — Commit latency (replaces the "tens of ms per atomic write [3]" citation)

End-to-end wall-clock latency of `IntegrationContract:RecordProvenanceWithReputation`,
measured client-side with `peer chaincode invoke --waitForEvent` (endorse →
order → commit-event), **20 sequential** commits, each on a distinct
pre-certified asset (varied asset ID so the state machine accepts each), real
`bundle_cube_done.json` off-chain/evidence hashes.

| Statistic | Value |
|---|---|
| n (successful / failed) | 20 / 0 |
| **mean** | **227.8 ms** |
| **median** | **223.0 ms** |
| **p95** | **260.7 ms** |
| min / max | 192 / 273 ms |

Raw: `raw/task1_latency_20260707-142748.csv` / `.log`.
Channel tuning in effect on this network: BatchTimeout 10 ms, preferred_max_bytes
2 MB, Raft tick 100 ms (per project config log). The measured ~0.2 s reflects a
full atomic provenance-**and**-reputation write under `--waitForEvent`, i.e. the
number the paper should cite for our own system rather than an external "[3]".

---

## Task 2 — Cross-asset / cross-design replay

### 2(a) Replay a valid bundle hash onto the wrong lifecycle stage
Verbatim rejections (`raw/task2a_replay.log`):

```
## PART-CUBE-001 (stage PRINT_COMPLETE):
Error: endorsement failure during invoke. response: status:500 message:"invalid lifecycle transition: RecordPrintJob requires stage MATERIAL_CERTIFIED, current stage is PRINT_COMPLETE"

## REPLAY-NOCERT-01 (never certified):
Error: endorsement failure during invoke. response: status:500 message:"asset REPLAY-NOCERT-01 does not exist"
```

**Honest caveat (`raw/task2a_integration_gap.log`):** the *integration convenience
path* `IntegrationContract:RecordProvenanceWithReputation` does **not** enforce
the lifecycle state machine — invoked with `eventType=PRINT_JOB` on a
never-certified asset `REPLAY-GAP-01`, it returned `rc=0` and created the asset
directly at `PRINT_COMPLETE`. The T1 replay defense holds on the dedicated
`ProvenanceContract.RecordPrintJob` path; it is **bypassed** on the integration
path. This is an implementation gap worth stating in the paper (and fixing:
mirror the stage guard into `RecordProvenanceWithReputation`).

### 2(b) Attach cube evidence to a bracket-certified asset
`XASSET-BRACKET-01` certified against the **bracket** design hash
`48f7790a…`; attacker attaches the cube bundle (design `dec2a69d…`).
Verbatim (`raw/task2b_binding.log`):

```
[CHECK A] design-hash binding (bundle.design vs on-chain certified):
    MISMATCH -> REJECT
    error: DESIGN-BINDING MISMATCH: bundle design dec2a69dc80d.. != certified 48f7790a773d.. for asset XASSET-BRACKET-01

[CHECK B] off-chain assess() compliance vs certified (bracket) design:
    executed(cube) == expected(bracket)? False
    q=0.7803  c=0.0  d=0.9299
    rating with compliance term      r = 0.6q+0.25c+0.15d = 0.6077
    Eq.2 veto (compliance=0)         r = 0.6q+0.15d       = 0.6077
```

Rejected by the design-hash binding (Check A); independently the compliance
dimension collapses to 0. **Note:** the binding is enforced at the gateway/
`assess()` layer — the chaincode does **not** compare PRINT_JOB evidence to the
certified design hash on-chain (grep of the Go source finds no design-hash
comparison in the write path). State this boundary precisely in the paper.

---

## Task 3 — Wrong-key attestation

`raw/task3_wrongkey.log` (bundle bytes unmodified):

```
true device pubkey  : 58363123af2b947b3434f11297e6e6a625b23db6dede431a317a581e52ef0b8c
wrong device pubkey : c644eefd1d1a1f8e8b72f3d72807e85213841e07410cf3ff8cbf9b3ddb4c6f0e
[1] verify against WRONG key : FAIL  -> expected FAIL  (OK)
[2] verify against TRUE  key : PASS  -> expected PASS  (OK)
```

Signature verifies **only** under the Pi-resident device key; an attacker
without the private key cannot forge a passing attestation.

---

## Task 4 — In-flight modification (post-signing)

One byte flipped in one telemetry sample after signing (`21.17 → 21.27`),
`raw/task4_inflight.log`:

```
on-chain committed hash        : 43dd3e476543d8bc936c280de42ae553e582c2135813b1fb0a1b39394404495b
recomputed hash (tampered)     : 0e61c69e97bbd55229bdf5f800673027cd812608e051aba2dd1b411893b46819
verify_bundle verdict : REJECT
   - LEDGER-HASH MISMATCH: stored evidence != on-chain commitment (0e61c69e97bb.. vs 43dd3e476543..)
   - DEVICE SIGNATURE INVALID: payload not signed by claimed device key
[Detection 1] ledger-hash mismatch : FIRED
[Detection 2] signature invalid    : FIRED
```

Both detections fire. Published `bundle_cube_done.json` untouched (worked on a
deep copy).

---

## Task 5 — Design substitution → compliance veto → reputation (LIVE PRINT)

**Live Ender-3 print, 2026-07-07.** Fresh asset `PART-CUBE-SUBST-LIVE-01`
certified on-chain against the **original** cube design (`dec2a69d…`,
`raw/task5_live_certify.log`). The operator physically printed the **modified**
cube (`cube_substituted_20mm.gcode`, layer height 0.2→0.25 → SHA `3a886e67…`,
temps unchanged at 200/50 so quality stays clean). The print ran to completion
(short 40-layer hollow cube, ~3 min at steady state), outcome `PrintDone`.

Telemetry captured live via OctoPrint poll (5 s interval,
`capture_cube_substituted_live.jsonl`): **100 real samples, 58 in the `Printing`
state**, `source=OCTOPRINT_POLL` (not simulated). Steady-state held nozzle
200.0 °C / bed 50.0 °C. Bundle `bundle_cube_substituted_live.json` built with
`expected = original certified design`, `observed.executed = modified hash`.

Assessment (`raw/task5_live_build.log`):

```
telemetry source : OCTOPRINT_POLL  (SIMULATED? False)
total / printing samples : 100 / 58   (thermal in-tol 87/116)
executed == certified? : False
q (quality)    = 0.75
c (compliance) = 0.0
d (delivery)   = 0.3366
r  reported by assess() (0.6q+0.25c+0.15d) = 0.5005
r  Eq.2 veto            (0.6q+0.15d, c=0)  = 0.5005
r  IF compliant         (0.6q+0.25+0.15d)  = 0.7505  (counterfactual)
```

`compliance = 0` removes the `0.25` term: `r = 0.6·0.75 + 0.15·0.3366 = 0.5005`
(a compliant print would have been `0.5005 + 0.25 = 0.7505`). Delivery is low
(0.3366) because `actual_time_s` counts the full 509 s capture window including
heat-up/idle against the original cube's slicer time estimate — this depresses
`d` but does not affect the compliance veto, which is the result of interest.

On-chain commit + posterior propagation (`raw/task5_live_commit.log`):

```
operator-secnet quality BEFORE : alpha=17.1991 beta=2 score=0.8958 events=27
RecordProvenanceWithReputation : rc=0
operator-secnet quality AFTER  : alpha=17.5918 beta=2 score=0.8979 events=28
linked rating on asset         : value=0.5005 weight=0.7673 raterId=org1admin
                                 ratingId RATING:a8ebd57c… txId 64550ab5…
asset final stage              : PRINT_COMPLETE
```

**Veto effect on the Beta posterior:** the committed rating is the vetoed
`0.5005`, not `0.7505`. Observed `Δα = 17.5918 − 17.1991 = 0.393` (this event's
weighted contribution `weight·value ≈ 0.7673·0.5005 = 0.384`, plus a small
decay adjustment over the 2445 s since the last update). A compliant print
(`r=0.7505`) would have contributed `0.7673·0.7505 = 0.576` to α — so the
compliance veto suppressed the operator's positive trust gain by **~33%** for
this event (the vetoed rating is `0.5005/0.7505 = 0.667×` a compliant one).
β is unchanged; this reputation model accumulates weighted-positive evidence
into α, so the veto manifests as a reduced positive contribution rather than an
absolute drop.

---

## Suggested LaTeX table (booktabs, single column) for the Tamper Detection subsection

```latex
\begin{table}[t]
\centering
\caption{Empirical T1 tamper-detection results on the Fabric + Ender-3 testbed.
Latency is the mean of 20 sequential atomic provenance+reputation commits
(\texttt{--waitForEvent}); median/p95 $=223/261$\,ms.}
\label{tab:t1-empirical}
\small
\setlength{\tabcolsep}{4pt}
\begin{tabular}{@{}p{1.55cm}p{2.2cm}p{3.4cm}@{}}
\toprule
\textbf{Attack} & \textbf{Mechanism} & \textbf{Result} \\
\midrule
Cross-asset replay & Lifecycle state machine & Rejected: ``requires stage MATERIAL\_CERTIFIED'' (HTTP 500) \\
Cross-design evidence & Design-hash binding + compliance & Binding mismatch; $c{=}0\Rightarrow r{=}0.6q{+}0.15d$ \\
Wrong-key attest. & Ed25519 verify & Wrong key FAIL / true key PASS \\
In-flight edit & Hash commit + signature & Rejected twice: hash mismatch \emph{and} bad signature \\
Design subst. (live) & Compliance veto $\rightarrow$ Beta & Real print; $c{=}0$, $r{=}0.5005$ ($0.7505$ if compliant); $\alpha$-gain $-33\%$ \\
\midrule
\multicolumn{3}{@{}l}{\textbf{Atomic commit latency:} mean $227.8$\,ms, p95 $260.7$\,ms ($n{=}20$)} \\
\bottomrule
\end{tabular}
\end{table}
```

---

## Claims in Table I that these experiments do NOT cover (state accurately)

1. **Sybil / collusion resistance** (CI-width + stake gates). Not exercised here;
   covered by the earlier `security_test.js` suite (PARTIAL results: stake cost +
   CI-width width limit impact, low meta-rep weight caps amplification). Cite that,
   not this matrix.
2. **On-chain design-hash binding.** Task 2(b) shows the substitution is caught,
   but by the *off-chain* `assess()`/gateway layer — the chaincode itself does
   **not** bind PRINT_JOB evidence to the certified design hash. Do not claim an
   on-chain design-integrity check.
3. **Lifecycle enforcement on the integration path.** Task 2(a) shows
   `RecordProvenanceWithReputation` bypasses the state machine. If Table I claims
   "all provenance writes are stage-guarded," qualify it: only the dedicated
   `RecordPrintJob` path is guarded in the current build.
4. **Garbage-in / source fabrication.** By design T1 does not defend against a
   party controlling the device key AND fabricating telemetry at source
   (attestation.py docstring, the honest T1 boundary — addressed only by T3).
5. **Multi-peer endorsement divergence / non-determinism.** Not tested here;
   covered by the geo-distributed benchmark (0.00% failure, separate results).
6. **Replay of a *stage-valid* bundle** (correct stage, duplicate evidence hash).
   Not tested — there is no on-chain nonce/duplicate-hash check; a bundle whose
   asset is correctly in `MATERIAL_CERTIFIED` would be accepted. Worth noting as
   a residual gap if Table I claims replay immunity generally.

---

## Artifact index

- `fabric_env.sh` — peer CLI env (Org1 admin).
- `task1_latency.sh` — latency harness → `raw/task1_latency_*.{csv,log}`.
- `task2b_binding.py` — cross-design binding demo → `raw/task2b_binding.log`.
- `task3_wrongkey.py` — wrong-key verify → `raw/task3_wrongkey.log`.
- `task4_inflight.py` — post-signing tamper → `raw/task4_inflight.log`.
- `generate_cube_substituted.py` — modified-cube generator (layer 0.2→0.25).
- `cube_substituted_20mm.gcode` — modified design, SHA `3a886e67…`.
- **LIVE Task 5 (2026-07-07):**
  - `task5_build_substitution_live.py` — live substitution bundle build → `raw/task5_live_build.log`.
  - `bundle_cube_substituted_live.json` / `capture_cube_substituted_live.jsonl` — signed bundle + REAL capture log (100 samples, `source=OCTOPRINT_POLL`).
  - `raw/task5_live_certify.log`, `raw/task5_live_commit.log`, `raw/task5_live_recorder.stdout` — certify / commit / recorder logs.
  - `_recorder_auto_bundle_live.json` — recorder's naive auto-bundle (design=original, executed=original → c=1); superseded by the authoritative live bundle, kept for audit.
- Superseded simulated run: `task5_build_substitution.py`, `bundle_cube_substituted.json`, `capture_cube_substituted.jsonl` (`raw/task5_build.log`, `raw/task5_certify.log`, `raw/task5_commit.log`).
- `generate_cube_substituted.py` / `cube_substituted_20mm.gcode` — modified design (layer 0.2→0.25, SHA `3a886e67…`).
- `raw/task0_network_up.log`, `raw/task2a_*.log` — remaining step logs.
