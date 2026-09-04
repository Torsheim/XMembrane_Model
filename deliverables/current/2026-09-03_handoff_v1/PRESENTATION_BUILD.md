# Presentation build and verification

This note covers the current Version 10 peer-review deck, its supporting
figures, and the self-contained HTML explainer in this handoff supplement.
The controlled Version 10 closeout report remains the governing scientific
authority. The files here are presentation aids and do not reopen or amend
that release.

## Build inputs

- `deliverables/build_simulated_system_setup.py`
- `deliverables/build_peer_review_figures.py`
- `deliverables/build_xmembrane_peer_review_deck.js`
- `package.json` and `package-lock.json`
- `requirements-docs-presentations.txt`
- `constraints/v10-python-3.10.txt`

The HTML explainer is maintained directly as
`presentations/HeiQ_XMembrane_Model_Explainer_V10_2026-09-03.html`. It has no
network, font, image, or JavaScript-package dependency.

## Locked dependencies

Install Python presentation dependencies from the repository root with:

```bash
python3 -m pip install -r requirements-docs-presentations.txt
```

Install the exact Node dependency tree with:

```bash
npm ci
```

The JavaScript lock fixes `pptxgenjs` at 4.0.1. The Python requirements are
exactly pinned through `constraints/v10-python-3.10.txt` and
`requirements-docs-presentations.txt`.

Required system tools and fonts:

- LibreOffice Impress for the PPTX-to-PDF export;
- Poppler (`pdfinfo`, `pdftotext`, and optionally `pdftoppm`) for inspection;
- Lato and Liberation Mono; a math font is used as the platform fallback for
  the requested Cambria Math face.

The checked build environment used Python 3.10.12, Node.js 22.17.0, npm
11.4.2, LibreOffice 7.3.7.2, Poppler 22.02.0, Lato, Liberation Mono, and Latin
Modern Math as the Linux math-font fallback.

## Rebuild

From the repository root:

```bash
npm run build:presentations
libreoffice --headless --convert-to pdf \
  --outdir deliverables/current/2026-09-03_handoff_v1/presentations \
  deliverables/current/2026-09-03_handoff_v1/presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pptx
```

`npm run build:presentations` regenerates the system figure, the eight model
review figures, their contact sheet, and the PPTX. LibreOffice performs the
explicit PDF export. Individual rendered slide PNGs under
`presentations/rendered/` are local visual-inspection scratch and are not part
of the controlled handoff payload.

## Required interpretation

The current PPTX, PDF, and HTML must all preserve these boundaries:

- model phase complete; technology not validated;
- direct EO inside the ERV is the selected modelling architecture;
- the primary O30 capacitive replay retains the original 0.025 V terminal
  limit and gives 16.2% retention after one hour and 0.68% over 24 hours;
- 98.5% and 4.6% belong only to the separate optimistic 1.8 V
  current-commanded upper bound, not a same-voltage replay;
- purely blocking electrodes provide finite startup displacement, not
  continuous duty, and an ideal symmetric complete cycle gives zero net EO
  transport;
- `t_w = 50` with `D_ref = 1e-10 m2/s` is a synthetic sensitivity, not a
  material identification; it closes transport in 4/8 cases and the full
  coupled system in 0/8 cases;
- no sustained-duty or full-system performance claim is enabled.

The deterministic handoff packager checks these terms before writing
`MANIFEST.json` and `SHA256SUMS`.

## Structural and visual checks

The generated presentation was checked as follows:

```bash
node --check deliverables/build_xmembrane_peer_review_deck.js
python3 -m py_compile \
  deliverables/build_simulated_system_setup.py \
  deliverables/build_peer_review_figures.py
pdfinfo deliverables/current/2026-09-03_handoff_v1/presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pdf
pdftotext -layout \
  deliverables/current/2026-09-03_handoff_v1/presentations/HeiQ_XMembrane_Technical_Model_Peer_Review_V10_2026-09-03.pdf -
```

The PPTX contains 31 wide-screen slides and the PDF contains 31 pages. The
cover, the electrode-boundary slide, the V9/V10 interpretation boundary, the
final conclusion, and the updated electrode-transient figure were inspected
visually after PDF export. Text was also extracted from both PPTX and PDF to
confirm that the required V10 wording survived conversion.
