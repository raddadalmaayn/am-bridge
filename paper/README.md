# Paper: Closing the Physical-to-Chain Gap

IEEE two-column conference draft (IEEEtran, conference mode) for the
physical-to-chain provenance attestation work in `~/provenance-bridge/`.

## Compiling

### Overleaf (recommended)
1. Zip this `paper/` folder (everything: `main.tex`, `sections/`,
   `figures/`, `references.bib`).
2. Overleaf → New Project → Upload Project → select the zip.
3. Set the compiler to **pdfLaTeX** and the main document to `main.tex`.
4. Compile. Overleaf runs BibTeX automatically.

The `IEEEtran` class and all used packages (graphicx, amsmath, booktabs,
xcolor, tikz, listings, balance, hyperref) ship with TeX Live, so no extra
files are needed.

### Local
```bash
pdflatex main && bibtex main && pdflatex main && pdflatex main
# or, single command:
tectonic main.tex
```

This draft was compile-verified locally with `tectonic` (XeTeX-based engine);
warnings only, no errors. Current length: **7 pages** (last page ≈ half
references). The 6-page target needs roughly one more page of cuts; the
content is already trimmed tight, so if the venue does not allow an
overlength page, the candidates are: (a) convert Table I (tamper taxonomy)
to prose, (b) drop Listing 1 in favor of a sentence pointing to the repo,
(c) cut Section VII-B (path to T2/T3) to one paragraph. Do not cut the
trust-boundary discussion — it is the core claim.

## Figures

`figures/make_figures.py` regenerates the data figures **from the real
captured artifacts** (`../capture_log.jsonl`, `../signed_bundle.json`):

- `fig_thermal_trace.pdf` — real 115-sample thermal trace (print start /
  cancel marked)
- `fig_beta_posterior.pdf` — measured Beta(2,2) → Beta(2.40, 2.0) update
- `fig_latency_pending.pdf`, `fig_scaling_pending.pdf` — skeleton axes for
  the pending experiments (red TODO labels)

`figures/fig_pipeline.tex` is the TikZ architecture diagram, compiled inline.
The trust-tier ladder and tamper taxonomy are LaTeX tables in
`sections/threat_model.tex`.

```bash
cd figures && python3 make_figures.py   # requires matplotlib
```

## Honest-data policy

All numbers in Sections VI-A–VI-C (capture, reputation, tamper demo) are
measured from the real Ender-3 run: 115 samples, offChainDataHash
`9b739c98…`, rating 0.52, posterior Beta(2.40, 2.0), CI [0.184, 0.865].
Experiments not yet run are marked with red `\todo{PENDING: …}` macros
(defined in `main.tex`) — **do not replace these with invented numbers**.
Search for `TODO` in the PDF before submission.

Numbers cited from the companion unified-chaincode paper (337 B/event,
4.8 ms / 9.9 % atomic-bridge overhead, 53.6 ms mean atomic write,
280–304 TPS concurrent) are verified against that paper's evaluation
section. A previously quoted "471 TPS provenance-only" figure could **not**
be located in any results file or draft (the only `471` found is a failure
count in a geo-benchmark JSON) — it is deliberately not used; verify the
source before citing it.

Two measured details that differ slightly from earlier notes: the nozzle
ramp is ~96 s measured from when the nozzle target was set (heating is
sequential after the bed, ≈188 s from print start — not ~170 s), and the
capture interval is 5 s.

## Remaining placeholders before submission

- Author block in `main.tex` (names, affiliations, emails).
- `anonymous2026unified` in `references.bib` → replace with the published
  citation of the unified-chaincode paper.
- All `\todo{PENDING: …}` experiment results (Section VI-D).

## Alternative titles

1. *Closing the Physical-to-Chain Gap: Tamper-Evident Provenance
   Attestation for Additive Manufacturing Supply Chains* (current)
2. *Trust at the Last Mile: Device-Signed Telemetry Attestation for
   Blockchain Provenance in Additive Manufacturing*
3. *From Thermistor to Ledger: A Trust-Tier Analysis and Implementation of
   the Oracle Problem in Additive Manufacturing Provenance*
4. *Signed at the Source? Edge Attestation and Its Honest Limits for
   Blockchain-Based Additive Manufacturing Provenance*
