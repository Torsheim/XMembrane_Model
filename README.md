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

## Final model-phase closeout (2026-09-02)

The hash-frozen English V10 package is the governing delivery. Its final
project closeout report governs wherever wording or status differs from an
earlier report or supporting note:

- `deliverables/current/2026-09-02_v10/`
- `reports/final_project_closeout_2026-09-02/HeiQ_XMembrane_Final_Project_Closeout_2026-09-02_v10.pdf`

V8/V8.1, V9 and the model-closure report remain historical provenance. See
`reports/README.md` for the short report map and `docs/REPOSITORY_LAYOUT.md` for
the source-file naming policy.

The model phase is complete; the technology is not validated. Direct EO inside
the ERV membrane/core is the selected modelling architecture. Post-ERV O30 is
retained only as a controlled coupon-test boundary and historical comparator.
No real membrane, sustainable electrode mechanism, module performance or net
full-system energy saving has been demonstrated. The successor phase, if
started, is measured same-sample material, electrode and controlled-flow coupon
qualification. Three important interpretation rules are now frozen:

- current density and membrane area are reported design coordinates, not
  acceptance limits in the exploratory screen;
- a positive passive surface-gradient direction is not required for actively
  driven EO transport, but bulk-to-surface film losses remain an engineering
  diagnostic that the coupon experiment must measure;
- purely blocking capacitive electrodes provide finite startup displacement,
  not demonstrated continuous EO duty.

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

The later reduced-order capacitive-electrode screen is run with:

```bash
PYTHONPATH=src python3 scripts/run_capacitive_electrode_study_v1.py --overwrite
```

It replaces the steady electrode assumption with a signed transient RC state,
checks blocking DC, symmetric cycling, diagnostic leakage and a dual frozen
replay of the stored direct-ERV cases. The original stored terminal-voltage
limit is the primary duration diagnostic; a separate 1.8 V replay is retained
only as an optimistic capacity upper bound. Neither is an electrode
electrochemical-window constraint. See
`docs/CAPACITIVE_ELECTRODE_TRANSIENT_STUDY_2026-09-01.md`. The capacitance is an
unmeasured sensitivity coordinate and the result is not a dynamic full-core or
full-system claim.

Build the current fail-closed V10 closeout package from the curated source
revision with:

```bash
python3 scripts/package_final_closeout_v10.py \
  --expected-source-revision "$(git rev-parse HEAD)"
```

The package is written atomically to `deliverables/current/2026-09-02_v10`.
Its verification authority is `verification/V10_STATUS.json`; the packager
checks the report and evidence bindings, scientific audits, complete source and
result archives, checksums and the live full test suite before publication.

`scripts/run_final_delivery_check_v1.py` is retained only as the historical
31 August checker. Its report/nested-manifest configuration predates the
September electrode and combined-sensitivity evidence and is not the V10
release gate.

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
