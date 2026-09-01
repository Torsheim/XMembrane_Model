# XMembrane Model

Physics-based modelling framework for electro-osmotic water removal from humid air.

This repository is a cleaned research implementation derived from the larger historical HeiQ_V2 development repository.

## Canonical model chain

```text
local membrane transport
        ↓
axial process integration
        ↓
coupled process/receiver integration
        ↓
material and operating-point optimisation
        ↓
bottleneck diagnostics and alternative receiver boundaries
```

See `docs/MODEL_CHAIN.md` for the numerical hierarchy, `docs/CLAIM_BOUNDARY.md` for interpretation limits, and `docs/PACKAGE_BOUNDARIES.md` for the boundary between native package code and retained reference implementations.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Tests

```bash
pytest -q
```

The test suite contains local-transport unit tests and golden regression checks against retained reference calculations.

## Current model closure and material handoff (2026-08-31)

The hash-frozen English V8.1 package is the controlled delivery. Its current
result and decision report governs wherever wording or status differs from a
supporting note:

- `deliverables/current/2026-08-31_v8_1/`
- `deliverables/current/2026-08-31_v8_1/reports/current_result/HeiQ_XMembrane_Current_Result_and_Decision_Report_2026-08-31_v8.pdf`

The model-closure report is supporting provenance, while the 1 September
test-cell note records the later minimum-area and ERV scale check. See
`reports/README.md` for the short report map and `docs/REPOSITORY_LAYOUT.md` for
the source-file naming policy.

The current decision is to stop broad unfocused modelling and move the existing
material search into availability/procurement enquiries plus controlled-flow
same-sample coupon qualification. Candidate ranking is not yet justified, and neither a selected module
architecture nor a net full-system energy saving has been demonstrated. Two
important interpretation rules are now frozen:

- current density and membrane area are reported design coordinates, not
  acceptance limits in the exploratory screen;
- a positive passive surface-gradient direction is not required for actively
  driven EO transport, but bulk-to-surface film losses remain an engineering
  diagnostic that the coupon experiment must measure.

Water diffusivity is therefore not a universal stand-alone procurement gate.
The passive transport identifiable by the model is the coupled chemical-water-
permeance bundle, proportional to
`D * (dCw/daw) / thickness` under the declared constitutive convention. The
post-ERV diffusivity replay is a controlled one-factor sensitivity study in
which sorption capacity, thickness, drag and conductivity were held fixed;
direct-ERV and post-ERV use may lead to different preferred property vectors.

Run the machine-readable closure checks with:

```bash
python3 -B scripts/run_direct_erv_gradient_closure_v1.py --overwrite
python3 -B scripts/run_project_closure_check_v1.py \
  --output-dir outputs/project_closure_check_v1 --overwrite
```

The final gradient/film and signed-polarity evidence is written to
`outputs/direct_erv_gradient_closure_v1`; the project-level readiness decision
is written to `outputs/project_closure_check_v1`.

Run the fail-closed final delivery check with live tests using:

```bash
python3 -B scripts/run_final_delivery_check_v1.py \
  --run-tests --overwrite
```

The result is written to `outputs/final_delivery_check_v1`. It reports model
delivery, release-snapshot readiness and next-phase empirical readiness as
three separate decisions. Open material/receiver/practical gates do not reopen
the completed model study; stale hashes, failed audits, missing runtime
dependencies, report damage or failed tests do block delivery.

## Earlier integrated decision package (2026-08-26; retained for provenance)

The current conclusion is assembled from named audited outputs rather than from chat
text or a single historical sweep:

```bash
PYTHONPATH=src python3 scripts/run_system_energy_closure_study.py \
  --source-root . \
  --output-dir outputs/system_energy_closure_study

python3 scripts/make_integrated_evidence_register_v1.py
```

No current-density acceptance cap is applied by default. The integrated register is
written to `outputs/integrated_evidence_v1`, and the complete LaTeX/PDF report is under
`reports/trond_full_report_v1`. `material_data_requirements.csv` is the working template
for supplier and literature scouting. Full-system savings remain unavailable while receiver
regeneration and heat rejection are unresolved.

### Reproducible membrane operating-region study

The dense direct-EO and post-ERV parameter maps, inverse-design sensitivity,
censor-aware area analysis and detailed-HVAC replay are orchestrated by:

```bash
python3 -B scripts/run_membrane_operating_region_study_v1.py
```

The declared axes and interpretation policy are in
`config/membrane_operating_region_study_v1.json`; audited results are written to
`outputs/membrane_operating_region_study_v1`. Direct EO and EO after ERV retain
separate reference systems and water duties. Current density is a sampled control
coordinate, not a 21 A/m² acceptance gate, and conditional saving is not reported as
full-system saving while receiver/regeneration energy remains unknown.

### ERV først, EO for hele den resterende latentlasten

Den separate studien av passiv ERV fulgt av EO helt ned til tilluftens
fuktighetsforhold kjøres med:

```bash
python3 -B scripts/make_post_erv_full_eo_study_v1.py --jobs 8 --overwrite
```

Konfigurasjonen ligger i `config/post_erv_full_eo_study_v1.json`, resultatene i
`outputs/post_erv_full_eo_study_v1`, og tolkningen er dokumentert i
`docs/POST_ERV_FULL_EO_STUDY_v1.md`. Studien rapporterer både det idealiserte
eksakte coil-endepunktet og et konservativt nær-endepunkt. Receiver/sluk og
varmeavvisning er ikke lukket, så ingen rad er en fullsystempåstand.

### Prosentstudie for økende EO-andel etter ERV

Den videre studien varierer hvor mye av den endelige ERV-til-tilluft-lasten
EO tar, og beholder samtidig den historiske prosentdefinisjonen som egen akse:

```bash
python3 -B scripts/make_post_erv_eo_percentage_sweep_v1.py \
  --jobs 8 --output-dir outputs/post_erv_eo_percentage_sweep_v1 --overwrite
```

Det historiske «10 %»-caset tilsvarer 22,1925 % av restlasten, O30 tilsvarer
72,7003 %, og O50 er allerede passert av ERV-en. Det eksakte 100 %-punktet har
en separat, idealisert sensible-only coil-gren; nær-endepunktsgrenen brukes som
konservativ kontrollreferanse. Se
[konfigurasjonen](config/post_erv_eo_percentage_sweep_v1.json),
[den norske tolkningen](docs/POST_ERV_EO_PERCENTAGE_SWEEP_v1.md) og
[det auditerte sammendraget](outputs/post_erv_eo_percentage_sweep_v1/SUMMARY.md).
Receiver-/slukenergi og varmeavvisning er fortsatt uløst, så prosentkurven er
ikke en validert fullsystemoptimalisering.

### 1 V-designfront og receiverdiagnostikk etter ERV

Den balanserte, samplede 1 V-fronten ligger mellom 76,3281 og 76,4062 %
fullført restlast; O30 har en betinget 0,9858 V-kandidat. Alle 160
receiverdiagnoser med positiv lokal margin krevde negativ spenning over hele
arealet og er urankbare. Se [tolkningen](docs/POST_ERV_EO_DESIGN_FRONTIER_v1.md)
og [auditen](outputs/post_erv_eo_design_frontier_v1/audit.json). Ingen rad
tillater en fullsystempåstand.

## Repository philosophy

The repository exposes one canonical model chain. Historical development generations remain in the original HeiQ_V2 research repository, while three reviewed source implementations are retained here behind explicit compatibility adapters.
