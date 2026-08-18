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

See `docs/MODEL_CHAIN.md` for the numerical hierarchy and `docs/CLAIM_BOUNDARY.md` for interpretation limits.

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

## Repository philosophy

Only the current canonical model chain is retained here. Historical development generations remain in the original HeiQ_V2 research repository.
