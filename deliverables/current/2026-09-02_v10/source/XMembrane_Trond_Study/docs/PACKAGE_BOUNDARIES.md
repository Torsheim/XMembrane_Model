# Canonical package boundaries

The canonical workflow and integration code lives under
`src/heiq/wp1`. The package does not yet contain an
independent reimplementation of every reviewed numerical
solver.

## Native package components

The following calculation layers are implemented directly
in the package:

- air-side thermophysical properties and channel models;
- axial targets, local-state assembly and integration;
- receiver basis construction and coupled integration;
- channel, geometry and stack engineering;
- pre-architecture study orchestration;
- bottleneck and direct-liquid workflow integration.

The migrated workflows import these package APIs directly.
They do not dynamically load another workflow script or
place legacy workflow modules in their calculation context.

## Retained compatibility adapters

Three package modules form the explicit boundary to reviewed
source implementations:

| Adapter | Retained source | Current purpose |
|---|---|---|
| `heiq.wp1.membrane.local_transport` | `heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py` | Loads configuration and executes the reviewed V2 local membrane solvers. |
| `heiq.wp1.airside.legacy_v3` | `scripts/make_wp1_pre_receiver_axial_v3.py` | Supports retained configuration-loading compatibility and source validation. |
| `heiq.wp1.receiver.legacy_v12` | `scripts/make_wp1_closed_receiver_system_v12.py` | Supports retained JSON loading and unchanged-source validation. |

The V2 membrane adapter remains part of the runtime
calculation path. The package must therefore not be
described as a fully independent rewrite of the local
transport solver.

The V3 and V12 sources remain reviewed reference baselines.
Native axial and receiver calculations do not call their
integration engines.

## Installation boundary

The adapters resolve retained sources relative to the
repository root. Consequently, the supported installation
is currently an editable installation from a complete
repository checkout:

```bash
python -m pip install -e ".[dev]"
```

A wheel containing only the packages under `src` is not a
standalone numerical distribution while these adapters are
required.

## Enforcement

`tests/test_package_boundaries.py` restricts dynamic Python
loading inside `src/heiq/wp1` to the three adapter modules
listed above. It also prevents the migrated workflows from
reintroducing direct references to the retained solver
scripts or legacy workflow-context objects.

Numerical equivalence tests compare native package layers
with the retained reference calculations. Moving the V2
local solver into native package code would be a separate
migration phase requiring its own equivalence review.
