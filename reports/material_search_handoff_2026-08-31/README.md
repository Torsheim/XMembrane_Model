# Prior material-search consolidation

This directory consolidates the material work already present under
`/home/torsheim/HeiQ`. It is an internal evidence handoff, not a claim that the
material search started from zero and not a procurement ranking.

## Main report

- `HeiQ_XMembrane_Prior_Material_Search_Consolidation_2026-08-31.pdf`
- `HeiQ_XMembrane_Prior_Material_Search_Consolidation_2026-08-31.tex`

The report's phase conclusion is:

- previous work already established ion, chemistry, architecture and synthetic
  property directions;
- Selemion CMVN in Li+ form is the strongest local evidence-anchor coupon if it
  is obtainable, not a validated performance winner;
- the leading route is a Li+-form CEM/ionomer, with Na+, non-PFSA sulfonated,
  microporous and composite/porous routes retained;
- Nafion NR211/NR212 are controls only;
- no named record has a complete same-sample MAT-01--MAT-09 property bundle;
- post-ERV O30 is the first system-relevant controlled-flow coupon target;
- direct EO inside the ERV remains a secondary/open architecture with 0/320
  full-coupled passes in the current screen;
- the post-release fixed-area direct-ERV weather replay was also reviewed:
  O80/O50 pass its declared engineering screen, O30 fails stack/engineering,
  and every full-system claim remains false;
- the next task is a traceable supplier/availability sheet and controlled
  same-sample coupon qualification, not another broad hypothetical sweep.

V8.1 is the latest hash-frozen English delivery layer and has no scientific
delta from V8. The V8 Current Result and Decision Report remains governing;
the model-closure report is supporting provenance. This directory is an
internal post-release addendum and does not modify V8 or V8.1.

## Machine-readable handoff

The `data/` directory contains:

- `named_material_register.csv`
- `literature_lead_register.csv`
- `candidate_availability_sheet.csv`
- `development_route_register.csv`
- `synthetic_target_register.csv`
- `qualification_matrix.csv`
- `gap_to_current_targets.csv`
- `historical_screen_milestones.csv`
- `superseded_constraint_register.csv`
- `model_conflict_register.csv`
- `alias_register.csv`
- `source_inventory.csv`
- `workspace_inventory_summary.csv`
- `handoff_summary.json`
- `output_manifest.csv`

The source inventory binds 75 current, historical, archive and workspace
records by path, size and SHA-256. The workspace inventory covers five HeiQ
roots plus the single top-level collection utility. The existing
Windows Downloads manifest is retained as 45 rows representing 31 unique PDFs
and 14 duplicates.

## Rebuild and verify

From the project root:

```bash
python3 scripts/build_material_search_handoff_v1.py --check-only
python3 scripts/build_material_search_handoff_v1.py
python3 -m pytest -q -s tests/test_material_search_handoff_v1.py
cd reports/material_search_handoff_2026-08-31
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  HeiQ_XMembrane_Prior_Material_Search_Consolidation_2026-08-31.tex
```

The `-s` pytest option avoids an unrelated temporary-file failure in the local
pytest capture layer. The targeted suite passes 8/8 tests.

The current energy, gradient and claim-boundary interpretation remains in the
governing V8 Current Result and Decision Report under
`reports/team_result_atlas_v8/`. The model-closure report under
`reports/model_closure_2026-08-31/` is supporting provenance.
