const pptxgen = require('pptxgenjs');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'OpenAI Codex for HeiQ / XMembrane';
pptx.company = 'HeiQ / XMembrane';
pptx.subject = 'Technical formulation and numerical implementation of the coupled XMembrane ERV model';
pptx.title = 'XMembrane Active-ERV Model — Technical Formulation and Numerical Implementation';
pptx.lang = 'en-US';
pptx.theme = { headFontFace: 'Lato', bodyFontFace: 'Lato', lang: 'en-US' };

const C = {
  navy: '0B1F33', navy2: '143B59', ink: '142635', muted: '5E7080', gray: '91A2AF',
  cyan: '00AFCB', teal: '00B9A8', blue: '347BC8', orange: 'F39A55', red: 'E45756',
  green: '68B984', white: 'FFFFFF', bg: 'F4F7F9', line: 'D5E1E7', light: 'EAF1F4',
  paleBlue: 'E6F0FA', paleTeal: 'E2F5F2', paleOrange: 'FFF0E2', paleRed: 'FCE9E8'
};
const S = pptx.ShapeType;

pptx.defineSlideMaster({
  title: 'TECH',
  background: { color: C.bg },
  objects: [
    { rect: { x: 0, y: 0, w: 13.333, h: 0.10, fill: { color: C.cyan }, line: { color: C.cyan } } },
    { text: { text: 'HEIQ / XMEMBRANE  •  TECHNICAL MODEL REVIEW', options: { x: 0.62, y: 7.12, w: 4.2, h: 0.17, fontFace: 'Lato', fontSize: 7.5, bold: true, color: C.muted, margin: 0 } } },
    { text: { text: 'MODEL BASIS • 02 SEP 2026', options: { x: 9.7, y: 7.12, w: 2.75, h: 0.17, fontFace: 'Lato', fontSize: 7.5, color: C.gray, align: 'right', margin: 0 } } }
  ],
  slideNumber: { x: 12.65, y: 7.11, w: 0.26, h: 0.18, fontFace: 'Lato', fontSize: 8, color: C.gray, align: 'right', margin: 0 }
});

function text(slide, value, x, y, w, h, o = {}) {
  slide.addText(value, {
    x, y, w, h, fontFace: o.fontFace || 'Lato', fontSize: o.fontSize || 16,
    color: o.color || C.ink, bold: !!o.bold, italic: !!o.italic,
    align: o.align || 'left', valign: o.valign || 'mid', margin: o.margin ?? 0,
    fit: o.fit || 'shrink', breakLine: false, isTextBox: true,
    charSpacing: o.charSpacing, rotate: o.rotate, paraSpaceAfterPt: o.paraSpaceAfterPt || 0,
    ...o
  });
}
function rr(slide, x, y, w, h, fill = C.white, line = C.line, r = 0.08) {
  slide.addShape(S.roundRect, { x, y, w, h, rectRadius: r, fill: { color: fill }, line: { color: line, width: 1 } });
}
function line(slide, x, y, w, h, color = C.line, width = 1, dash = 'solid') {
  slide.addShape(S.line, { x, y, w, h, line: { color, width, dashType: dash } });
}
function arrow(slide, x1, y1, x2, y2, color = C.cyan, width = 2.2, begin = 'none', end = 'triangle') {
  slide.addShape(S.line, { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width, beginArrowType: begin, endArrowType: end } });
}
function heading(slide, kicker, title, subtitle = '') {
  text(slide, kicker.toUpperCase(), 0.65, 0.37, 5.4, 0.22, { fontSize: 9.5, bold: true, color: C.cyan, charSpacing: 1.5 });
  text(slide, title, 0.65, 0.68, 12.0, 0.55, { fontSize: 27, bold: true, color: C.navy });
  if (subtitle) text(slide, subtitle, 0.67, 1.23, 11.9, 0.32, { fontSize: 12.3, color: C.muted });
}
function pill(slide, label, x, y, w, fill = C.light, color = C.navy) {
  rr(slide, x, y, w, 0.32, fill, fill);
  text(slide, label.toUpperCase(), x + 0.06, y + 0.01, w - 0.12, 0.28, { fontSize: 8.5, bold: true, color, align: 'center', charSpacing: 0.65 });
}
function eq(slide, value, x, y, w, h, fill = C.light, size = 17, color = C.navy) {
  rr(slide, x, y, w, h, fill, fill);
  text(slide, value, x + 0.16, y + 0.05, w - 0.32, h - 0.10, { fontFace: 'Cambria Math', fontSize: size, color, align: 'center' });
}
function card(slide, x, y, w, h, title, body, accent = C.cyan, fill = C.white) {
  rr(slide, x, y, w, h, fill, C.line);
  slide.addShape(S.rect, { x, y, w: 0.07, h, fill: { color: accent }, line: { color: accent } });
  text(slide, title, x + 0.22, y + 0.13, w - 0.38, 0.30, { fontSize: 13.5, bold: true, color: C.navy });
  text(slide, body, x + 0.22, y + 0.48, w - 0.38, h - 0.58, { fontSize: 10.8, color: C.muted, valign: 'top', breakLine: true, paraSpaceAfterPt: 4 });
}
function bullets(slide, items, x, y, w, h, o = {}) {
  const runs = [];
  items.forEach((item, i) => runs.push({ text: item, options: { bullet: { indent: o.indent || 15 }, hanging: 4, breakLine: i < items.length - 1 } }));
  slide.addText(runs, { x, y, w, h, fontFace: 'Lato', fontSize: o.fontSize || 13, color: o.color || C.ink, margin: 0, valign: 'top', paraSpaceAfterPt: o.space || 8, fit: 'shrink' });
}
function ref(slide, value) {
  text(slide, value, 0.67, 6.85, 11.8, 0.16, { fontSize: 7.2, color: C.gray, italic: true, align: 'left' });
}
function badge(slide, value, x, y, color = C.cyan) {
  slide.addShape(S.ellipse, { x, y, w: 0.42, h: 0.42, fill: { color }, line: { color: C.white, width: 1 } });
  text(slide, String(value), x, y, 0.42, 0.40, { fontSize: 12, bold: true, color: C.white, align: 'center' });
}
function status(slide, x, y, good = true, label = '') {
  slide.addShape(S.ellipse, { x, y, w: 0.24, h: 0.24, fill: { color: good ? C.teal : C.red }, line: { color: good ? C.teal : C.red } });
  text(slide, good ? '✓' : '!', x, y - 0.01, 0.24, 0.25, { fontSize: 10.5, bold: true, color: C.white, align: 'center' });
  if (label) text(slide, label, x + 0.34, y - 0.03, 3.0, 0.30, { fontSize: 11.5, color: C.ink });
}
function codebox(slide, lines, x, y, w, h, title = 'ALGORITHM') {
  rr(slide, x, y, w, h, C.navy2, C.navy2);
  text(slide, title, x + 0.20, y + 0.15, w - 0.40, 0.23, { fontSize: 8.5, bold: true, color: C.cyan, charSpacing: 1.2 });
  text(slide, lines, x + 0.24, y + 0.52, w - 0.48, h - 0.66, { fontFace: 'Liberation Mono', fontSize: 10.2, color: 'E8F2F6', valign: 'top', breakLine: true, paraSpaceAfterPt: 4 });
}

// 1 Cover
{
  const s = pptx.addSlide(); s.background = { color: C.navy };
  s.addShape(S.rect, { x: 0, y: 0, w: 13.333, h: 0.11, fill: { color: C.cyan }, line: { color: C.cyan } });
  text(s, 'HEIQ / XMEMBRANE', 0.72, 0.53, 3.2, 0.26, { fontSize: 11, bold: true, color: C.cyan, charSpacing: 1.5 });
  text(s, 'Active-ERV Model', 0.72, 1.23, 7.1, 0.62, { fontSize: 36, bold: true, color: C.white });
  text(s, 'Technical Formulation and Numerical Implementation', 0.72, 1.90, 7.6, 0.74, { fontSize: 25, bold: true, color: 'D8E6ED' });
  text(s, 'Peer-review deck', 0.74, 2.90, 3.0, 0.33, { fontSize: 16, color: C.cyan });
  text(s, 'Control volumes • constitutive laws • boundary conditions • solver hierarchy • conservation audits • validation map', 0.74, 3.42, 6.9, 0.70, { fontSize: 14, color: 'BFD1DA', valign: 'top' });
  rr(s, 8.25, 0.78, 4.32, 5.92, C.navy2, '284B65');
  text(s, 'MODEL NESTING', 8.65, 1.08, 3.52, 0.25, { fontSize: 9.5, bold: true, color: C.cyan, align: 'center', charSpacing: 1.4 });
  const layers = [
    ['HVAC ledger', C.blue], ['ERV / coil endpoints', C.teal], ['Axial two-stream core', C.cyan],
    ['Gas films', C.orange], ['1D membrane BVP', C.white]
  ];
  layers.forEach((l, i) => {
    const inset = i * 0.28;
    rr(s, 8.63 + inset, 1.63 + i * 0.68, 3.56 - 2 * inset, 0.51, i === 4 ? 'FFFFFF' : '173F5C', i === 4 ? 'FFFFFF' : '2A5470');
    text(s, l[0], 8.77 + inset, 1.73 + i * 0.68, 3.28 - 2 * inset, 0.25, { fontSize: 11.5, bold: true, color: i === 4 ? C.navy : l[1], align: 'center' });
  });
  arrow(s, 10.41, 5.21, 10.41, 5.78, C.cyan, 2.5);
  text(s, 'local physics → system response', 8.86, 5.95, 3.10, 0.28, { fontSize: 10.5, color: 'C9D9E1', align: 'center' });
  text(s, 'Model basis: controlled repository state, 02 September 2026', 0.74, 6.90, 7.2, 0.20, { fontSize: 8.5, color: '8FA7B4' });
}

// 2 Review scope
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Review scope', 'What is being reviewed—and what is not', 'The review target is the model formulation and implementation, not the commercial viability claim.');
  card(s, 0.72, 1.72, 3.78, 2.02, 'Reviewed model object', 'Steady moist-air states coupled to voltage-controlled water transport through an active membrane, integrated across an ERV core and linked to a reduced cooling-coil model.', C.cyan);
  card(s, 4.78, 1.72, 3.78, 2.02, 'Primary review questions', 'Are the governing equations internally consistent?\nAre boundary conditions physically admissible?\nAre numerical roots and balances closed?\nAre assumptions visible?', C.blue);
  card(s, 8.84, 1.72, 3.78, 2.02, 'Excluded from proof', 'Commercial membrane availability, long-term durability, complete receiver hardware, full thermal management, CAPEX and annual building performance.', C.orange);
  rr(s, 0.72, 4.15, 11.90, 1.70, C.white, C.line);
  pill(s, 'Model outputs', 1.00, 4.43, 1.42, C.paleTeal, C.teal);
  const outs = ['local j and Nw', 'surface activities', 'required area', 'water balance', 'EO power', 'remaining coil power'];
  outs.forEach((v, i) => pill(s, v, 2.70 + (i % 3) * 2.95, 4.35 + Math.floor(i / 3) * 0.62, 2.45, i < 3 ? C.paleBlue : C.paleTeal, i < 3 ? C.blue : C.teal));
  text(s, 'Review principle: distinguish numerical verification, experimental validation and system closure.', 0.72, 6.22, 11.90, 0.35, { fontSize: 15, bold: true, color: C.navy, align: 'center' });
}

// 3 Architecture and control volumes
{
  const s = pptx.addSlide('TECH');
  heading(s, 'System definition', 'Architecture and nested control volumes');
  const nodes = [
    ['CV-1', 'Outdoor / return air', 'bulk psychrometric states', C.blue],
    ['CV-2', 'Active ERV core', 'heat + passive moisture + EO', C.cyan],
    ['CV-3', 'Cooling coil', 'ADP, condensate, reheat', C.teal],
    ['CV-4', 'Power ledger', 'compressor + fans + EO + losses', C.navy]
  ];
  nodes.forEach((n, i) => {
    const x = 0.68 + i * 3.08;
    card(s, x, 1.82, 2.62, 1.48, `${n[0]}  ${n[1]}`, n[2], n[3]);
    if (i < 3) arrow(s, x + 2.66, 2.56, x + 3.02, 2.56, C.cyan, 2.6);
  });
  rr(s, 1.83, 3.78, 7.66, 1.78, C.white, C.line);
  text(s, 'CV-2 is itself nested', 2.10, 3.99, 2.0, 0.28, { fontSize: 13, bold: true, color: C.navy });
  const nested = [['gas film', C.orange], ['membrane x ∈ [0,L]', C.cyan], ['gas film', C.orange]];
  nested.forEach((n, i) => {
    rr(s, 2.28 + i * 2.28, 4.52, 1.88, 0.62, i === 1 ? C.paleTeal : C.paleOrange, i === 1 ? C.teal : C.orange);
    text(s, n[0], 2.42 + i * 2.28, 4.68, 1.60, 0.28, { fontSize: 11.5, bold: true, color: n[1], align: 'center' });
    if (i < 2) arrow(s, 4.20 + i * 2.28, 4.83, 4.52 + i * 2.28, 4.83, C.gray, 1.8);
  });
  rr(s, 9.80, 3.78, 2.82, 1.78, C.navy2, C.navy2);
  text(s, 'Conservation contract', 10.08, 4.03, 2.26, 0.30, { fontSize: 13, bold: true, color: C.cyan, align: 'center' });
  text(s, 'water removed from process\n= water gained by receiver', 10.11, 4.56, 2.20, 0.62, { fontFace: 'Cambria Math', fontSize: 15, color: C.white, align: 'center', breakLine: true });
  ref(s, 'Architecture used in the selected interpretation: EO embedded in the ERV membrane; no separate post-ERV EO stage.');
}

// 4 Hierarchy and code provenance
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Implementation hierarchy', 'Canonical numerical chain and source ownership');
  const rows = [
    ['1', 'Local membrane transport (V2)', '1D activity + voltage; analytical power-law or H-Nafion BVP', 'heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py', C.cyan],
    ['2', 'Axial process integration (V3)', 'local state re-solved as process humidity changes with area', 'src/heiq/wp1/axial/*', C.blue],
    ['3', 'Coupled gas receiver (V12.1)', 'process and receiver updated with the same transported water', 'src/heiq/wp1/receiver/coupled_integration.py', C.teal],
    ['4', 'Direct active-ERV screening', 'balanced endpoints + segmented local sizing + coil linkage', 'src/heiq/wp1/studies/direct_eo_erv.py', C.orange],
    ['5', 'Study / optimisation workflows', 'targets, parameter sweeps, basis checks and result auditing', 'src/heiq/wp1/studies/* and scripts/*', C.navy]
  ];
  rows.forEach((r, i) => {
    const y = 1.63 + i * 0.93;
    rr(s, 0.72, y, 11.92, 0.75, C.white, C.line);
    badge(s, r[0], 0.93, y + 0.16, r[4]);
    text(s, r[1], 1.55, y + 0.10, 2.72, 0.30, { fontSize: 13, bold: true, color: C.navy });
    text(s, r[2], 4.45, y + 0.10, 4.03, 0.45, { fontSize: 10.5, color: C.muted, valign: 'top' });
    text(s, r[3], 8.70, y + 0.10, 3.55, 0.44, { fontFace: 'Liberation Mono', fontSize: 8.4, color: r[4], valign: 'top' });
    if (i < rows.length - 1) arrow(s, 1.14, y + 0.75, 1.14, y + 0.91, C.gray, 1.4);
  });
  ref(s, 'Controlled model map: docs/MODEL_CHAIN.md. Research models; generated outputs should be reproducible from source.');
}

// 5 sign conventions
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Mathematical basis', 'Coordinates, signs and conserved quantities');
  rr(s, 0.72, 1.67, 7.62, 2.20, C.white, C.line);
  text(s, 'PROCESS / SOURCE', 1.00, 1.95, 1.80, 0.25, { fontSize: 9.5, bold: true, color: C.blue, align: 'center', charSpacing: 1.0 });
  text(s, 'RECEIVER', 6.26, 1.95, 1.45, 0.25, { fontSize: 9.5, bold: true, color: C.teal, align: 'center', charSpacing: 1.0 });
  rr(s, 2.14, 2.43, 4.64, 0.72, C.paleTeal, C.teal);
  text(s, 'membrane thickness  L', 2.28, 2.61, 4.36, 0.29, { fontSize: 13, bold: true, color: C.navy, align: 'center' });
  arrow(s, 2.12, 3.42, 6.82, 3.42, C.cyan, 2.7);
  text(s, 'x = 0', 1.92, 3.44, 0.76, 0.25, { fontSize: 11, bold: true, color: C.navy, align: 'center' });
  text(s, 'x = L', 6.42, 3.44, 0.76, 0.25, { fontSize: 11, bold: true, color: C.navy, align: 'center' });
  arrow(s, 3.45, 2.18, 5.52, 2.18, C.orange, 2.2);
  text(s, 'positive Nw and j', 3.56, 1.91, 1.86, 0.24, { fontSize: 10, bold: true, color: C.orange, align: 'center' });
  card(s, 8.62, 1.67, 4.00, 2.20, 'Primary conserved rate', 'Steady local water flux Nw [mol m⁻² s⁻¹].\n\nIntegrated transfer is obtained from ∫A Nw dA and must match both air-stream balances.', C.cyan);
  const basis = [
    ['Humidity ratio', 'w = kg water / kg dry air'],
    ['Water activity', 'aw = pv / psat(T)'],
    ['Electrical sign', 'positive j follows source → receiver'],
    ['Thermal basis', 'steady bulk states; no dynamic storage']
  ];
  basis.forEach((b, i) => card(s, 0.72 + i * 3.00, 4.27, 2.72, 1.45, b[0], b[1], [C.blue,C.cyan,C.orange,C.teal][i]));
  ref(s, 'Positive-flux convention is declared in heiq_pre_receiver_model.py and used by the axial/receiver APIs.');
}

// 6 psychrometric layer
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Air-side property layer', 'Moist-air states are calculated on a dry-air basis');
  eq(s, 'psat(T) = Buck equation over liquid water', 0.72, 1.63, 3.76, 0.65, C.paleBlue, 15);
  eq(s, 'w = 0.621945 · pv / (p − pv)', 0.72, 2.43, 3.76, 0.65, C.paleBlue, 17);
  eq(s, 'aw = pv / psat(T)', 0.72, 3.23, 3.76, 0.65, C.paleBlue, 18);
  eq(s, 'h = 1.006T + w(2501 + 1.86T)', 0.72, 4.03, 3.76, 0.65, C.paleBlue, 16);
  eq(s, 'v = Rd T(1 + 1.6078w) / p', 0.72, 4.83, 3.76, 0.65, C.paleBlue, 16);
  rr(s, 4.82, 1.63, 3.70, 3.85, C.white, C.line);
  pill(s, 'State vector', 5.12, 1.94, 1.36, C.paleTeal, C.teal);
  text(s, '{ T, RH, w, h, Tdew, v, p }', 5.15, 2.54, 3.03, 0.48, { fontFace: 'Cambria Math', fontSize: 21, bold: true, color: C.navy, align: 'center' });
  bullets(s, [
    'RH and activity are numerically identical for ideal moist air at the same temperature basis.',
    'Humidity ratio, not RH, is the conserved air-stream water coordinate.',
    'The model rejects vapor pressure ≥ total pressure and negative humidity ratio.'
  ], 5.18, 3.24, 2.98, 1.75, { fontSize: 11.5, space: 7 });
  rr(s, 8.86, 1.63, 3.76, 3.85, C.navy2, C.navy2);
  pill(s, 'Airflow basis', 9.20, 1.94, 1.48, '1B4A68', C.cyan);
  text(s, 'actual inlet CFM', 9.24, 2.49, 3.00, 0.30, { fontSize: 14, bold: true, color: C.white, align: 'center' });
  text(s, 'dry-air mass flow derived from dry-air partial pressure', 9.30, 2.91, 2.88, 0.61, { fontSize: 11.5, color: 'CADAE2', align: 'center' });
  line(s, 9.28, 3.72, 2.92, 0, '31556C', 1);
  text(s, 'or standard dry-air CFM', 9.24, 4.00, 3.00, 0.30, { fontSize: 14, bold: true, color: C.white, align: 'center' });
  text(s, 'reference T and p explicitly declared', 9.30, 4.42, 2.88, 0.48, { fontSize: 11.5, color: 'CADAE2', align: 'center' });
  text(s, 'The basis must not change silently between cases.', 4.82, 5.89, 7.80, 0.43, { fontSize: 14, bold: true, color: C.red, align: 'center' });
  ref(s, 'Implementation: src/heiq/wp1/airside/properties.py. Saturation pressure: Buck correlation.');
}

// 7 passive ERV
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Passive reference model', 'ERV endpoints are effectiveness-based and balance-closed');
  eq(s, 'TOA,out = TOA,in − εs,eff(TOA,in − Texh,in)', 0.72, 1.68, 5.60, 0.72, C.paleBlue, 16);
  eq(s, 'wOA,out = wOA,in − εl,eff(wOA,in − wexh,in)', 0.72, 2.56, 5.60, 0.72, C.paleBlue, 16);
  text(s, 'εeff = ε · min(1, ṁexh / ṁOA)', 1.30, 3.49, 4.43, 0.37, { fontFace: 'Cambria Math', fontSize: 18, bold: true, color: C.navy, align: 'center' });
  card(s, 0.72, 4.13, 5.60, 1.52, 'Endpoint closure', 'Receiver outlet humidity is obtained from the water balance. Receiver outlet enthalpy is obtained from the total moist-air enthalpy balance.', C.cyan);
  rr(s, 6.66, 1.68, 5.96, 3.97, C.white, C.line);
  pill(s, 'Acceptance checks', 7.00, 1.98, 1.84, C.paleTeal, C.teal);
  const cs = [
    '0 ≤ sensible and latent effectiveness ≤ 1',
    'positive dry-air flows and fan efficiency',
    'water-balance residual finite and closed',
    'enthalpy-balance residual finite and closed',
    'no supersaturated outlet state',
    'both-side pressure-drop fan power included'
  ];
  cs.forEach((v, i) => status(s, 7.10, 2.56 + i * 0.46, true, v));
  eq(s, 'Pfan = [ṁOA vOA Δp + ṁexh vexh Δp] / ηfan', 6.66, 5.91, 5.96, 0.63, C.paleTeal, 15);
  ref(s, 'Implementation: run_erv() in src/heiq/wp1/studies/direct_eo_erv.py.');
}

// 8 gas films
{
  const s = pptx.addSlide('TECH');
  heading(s, 'External mass transfer', 'Finite gas films connect bulk air to membrane surface activity');
  eq(s, 'Nw = Ks(as,bulk − as,surface)', 0.72, 1.69, 4.02, 0.70, C.paleOrange, 18);
  eq(s, 'Nw = Kr(ar,surface − ar,bulk)', 0.72, 2.55, 4.02, 0.70, C.paleOrange, 18);
  rr(s, 5.08, 1.69, 7.54, 3.13, C.white, C.line);
  const chain = [
    ['Dh = 2g', 'parallel-plate hydraulic diameter'],
    ['Re = ρuDh/μ', 'flow regime'],
    ['Sc = μ/(ρDv)', 'momentum / vapor diffusivity'],
    ['Sh(Re,Sc)', '7.54 laminar; smooth transition; turbulent screen'],
    ['kg = ShDv/Dh', 'gas transfer coefficient'],
    ['Kactivity = scale · kg · csat', 'mol m⁻² s⁻¹ per activity']
  ];
  chain.forEach((c, i) => {
    const col = i % 3, row = Math.floor(i / 3), x = 5.34 + col * 2.34, y = 1.98 + row * 1.25;
    pill(s, c[0], x, y, 1.82, col === 0 ? C.paleBlue : col === 1 ? C.paleTeal : C.paleOrange, col === 0 ? C.blue : col === 1 ? C.teal : C.orange);
    text(s, c[1], x, y + 0.40, 1.82, 0.50, { fontSize: 9.5, color: C.muted, align: 'center', valign: 'top' });
    if (i < 5 && i !== 2) arrow(s, x + 1.85, y + 0.17, x + 2.18, y + 0.17, C.gray, 1.5);
  });
  rr(s, 0.72, 5.12, 11.90, 1.16, C.navy2, C.navy2);
  text(s, 'Review implication', 1.02, 5.38, 1.62, 0.27, { fontSize: 12.5, bold: true, color: C.cyan });
  text(s, 'A high intrinsic membrane flux does not guarantee a high system flux. Film coefficients depend on temperature, channel gap, velocity, pressure and the selected correlation regime.', 2.79, 5.29, 9.20, 0.48, { fontSize: 13.5, color: C.white });
  ref(s, 'Implementation: calculate_film_state() in src/heiq/wp1/airside/properties.py.');
}

// 9 membrane conservation
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Local membrane model', 'Steady water flux combines EO drag and Fickian back-diffusion');
  eq(s, 'Nw = nd(aw) · j/F − Dw(aw) Sw(aw) · daw/dx', 0.86, 1.64, 11.60, 0.82, C.light, 21);
  card(s, 0.86, 2.81, 3.55, 1.77, 'EO contribution', 'NEO = nd j/F\n\nnd (or tw) is mol H₂O transported per mol elementary charge.', C.cyan, C.paleTeal);
  card(s, 4.88, 2.81, 3.55, 1.77, 'Diffusive contribution', 'Ndiff = −Dw Sw daw/dx\n\nThe sign follows the local activity gradient and can oppose EO.', C.blue, C.paleBlue);
  card(s, 8.90, 2.81, 3.55, 1.77, 'Steady-state constraint', 'Nw is spatially constant through a 1D membrane with no internal water source, sink or accumulation.', C.orange, C.paleOrange);
  arrow(s, 2.68, 4.83, 10.62, 4.83, C.cyan, 2.6);
  text(s, 'positive transport: process → receiver', 4.70, 4.98, 3.95, 0.30, { fontSize: 12, bold: true, color: C.cyan, align: 'center' });
  rr(s, 0.86, 5.54, 11.60, 0.72, C.white, C.line);
  text(s, 'Model class: one-dimensional, steady, isothermal within each local solve; local properties vary with water activity.', 1.10, 5.74, 11.12, 0.29, { fontSize: 14, bold: true, color: C.navy, align: 'center' });
  ref(s, 'Governing equations declared in heiq_pre_receiver_material_analyses/heiq_pre_receiver_model.py.');
}

// 10 properties
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Constitutive closure', 'Material properties are local functions of water activity');
  eq(s, 'D(aw) = Dref (aw/aref)^pD', 0.72, 1.67, 3.68, 0.74, C.paleBlue, 18);
  eq(s, 'σ(aw) = σref (aw/aref)^pσ', 0.72, 2.58, 3.68, 0.74, C.paleTeal, 18);
  eq(s, 'S(aw) = Sref (aw/aref)^pS', 0.72, 3.49, 3.68, 0.74, C.paleOrange, 18);
  eq(s, 'B(aw) = D(aw)S(aw)', 0.72, 4.40, 3.68, 0.74, C.light, 18);
  rr(s, 4.76, 1.67, 3.65, 3.47, C.navy2, C.navy2);
  text(s, 'INVERSE-DESIGN VECTOR', 5.10, 1.99, 2.97, 0.28, { fontSize: 9.5, bold: true, color: C.cyan, align: 'center', charSpacing: 1.3 });
  text(s, '{ nd, Dref, σref, Sref, L, pD, pσ, pS, ASRseries }', 5.08, 2.59, 3.02, 1.00, { fontFace: 'Cambria Math', fontSize: 19, bold: true, color: C.white, align: 'center' });
  text(s, 'A feasible point is a simultaneous property combination—not evidence that one real material exhibits the full vector.', 5.12, 3.93, 2.94, 0.76, { fontSize: 12, color: 'CBDCE4', align: 'center' });
  rr(s, 8.77, 1.67, 3.85, 3.47, C.white, C.line);
  pill(s, 'Hydration feedback', 9.11, 1.99, 1.85, C.paleRed, C.red);
  const fb = ['local aw ↓', 'σ ↓', 'ASR ↑', 'j ↓ at fixed V', 'EO flux ↓'];
  fb.forEach((v, i) => {
    pill(s, v, 9.21, 2.55 + i * 0.48, 2.96, i === 2 ? C.paleOrange : C.light, i === 2 ? C.orange : C.navy);
    if (i < fb.length - 1) arrow(s, 10.69, 2.89 + i * 0.48, 10.69, 3.01 + i * 0.48, C.gray, 1.2);
  });
  rr(s, 0.72, 5.50, 11.90, 0.79, C.paleOrange, C.paleOrange);
  text(s, 'nd is an input for the material-neutral power-law model; it is not derived from D, S or σ.', 0.98, 5.70, 11.38, 0.34, { fontSize: 14, bold: true, color: C.navy, align: 'center' });
  ref(s, 'The alternative H-Nafion implementation derives local hydration-dependent D, σ, S and drag from declared correlations.');
}

// 11 voltage model
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Electrochemical closure', 'The voltage equation contains ohmic and water-activity terms');
  eq(s, 'dV/dx = j/σ(aw) + nd(aw) RT/F · d ln(aw)/dx', 0.80, 1.62, 11.74, 0.78, C.light, 20);
  const parts = [
    ['Membrane ohmic', 'Vohm = j ∫₀ᴸ dx/σ(aw)', 'hydration-dependent ASR', C.blue],
    ['Water polarization', 'Vwater = ∫ nd RT/F · d ln aw', 'reversible activity work', C.cyan],
    ['Series resistance', 'Vseries = j · ASRseries', 'contacts and current collectors', C.orange],
    ['Fixed voltage', 'Vfixed', 'electrode / declared lower-bound loss', C.red]
  ];
  parts.forEach((p, i) => card(s, 0.72 + i * 3.00, 2.76, 2.72, 1.67, p[0], p[1] + '\n\n' + p[2], p[3]));
  eq(s, 'Vterminal = Vohm + Vwater + Vseries + Vfixed', 1.20, 4.84, 10.90, 0.77, C.paleTeal, 20);
  rr(s, 1.20, 5.91, 10.90, 0.48, C.navy2, C.navy2);
  text(s, 'Applied terminal voltage is the control input; current density is the solved response.', 1.48, 6.02, 10.34, 0.28, { fontSize: 14, bold: true, color: C.white, align: 'center' });
  ref(s, 'Power accounting uses applied terminal voltage, not a nominal voltage cap.');
}

// 12 boundary conditions
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Boundary-value problem', 'Gas-film equations determine the membrane surface activities');
  rr(s, 0.72, 1.63, 11.90, 2.17, C.white, C.line);
  pill(s, 'bulk source', 1.02, 1.92, 1.50, C.paleBlue, C.blue);
  pill(s, 'surface source', 3.22, 1.92, 1.62, C.paleOrange, C.orange);
  pill(s, 'surface receiver', 8.47, 1.92, 1.72, C.paleOrange, C.orange);
  pill(s, 'bulk receiver', 10.84, 1.92, 1.44, C.paleTeal, C.teal);
  arrow(s, 2.57, 2.80, 3.20, 2.80, C.blue, 2.2);
  arrow(s, 4.87, 2.80, 8.43, 2.80, C.cyan, 3.0);
  arrow(s, 10.22, 2.80, 10.81, 2.80, C.teal, 2.2);
  text(s, 'Ks', 2.74, 2.46, 0.32, 0.24, { fontFace: 'Cambria Math', fontSize: 14, bold: true, color: C.blue, align: 'center' });
  text(s, '1D membrane', 6.03, 2.43, 1.30, 0.27, { fontSize: 11, bold: true, color: C.cyan, align: 'center' });
  text(s, 'Kr', 10.37, 2.46, 0.32, 0.24, { fontFace: 'Cambria Math', fontSize: 14, bold: true, color: C.teal, align: 'center' });
  eq(s, 'as,surf = as,bulk − Nw/Ks', 0.72, 4.13, 3.75, 0.72, C.paleBlue, 17);
  eq(s, 'ar,surf = ar,bulk + Nw/Kr', 4.78, 4.13, 3.75, 0.72, C.paleTeal, 17);
  eq(s, '0 < as,surf, ar,surf < 1', 8.84, 4.13, 3.78, 0.72, C.paleOrange, 17);
  card(s, 0.72, 5.18, 5.78, 1.03, 'Physical flux bracket', 'Finite films impose row-specific lower and upper flux bounds before a surface reaches aw = 0 or 1.', C.orange);
  card(s, 6.82, 5.18, 5.80, 1.03, 'Surface-direction audit', 'Midpoint and n+1 segment-boundary states are checked so a limiting end state is not hidden.', C.cyan);
  ref(s, 'Activity bounds use ACTIVITY_EPS = 1×10⁻⁷. Surface violations fail the local solution.');
}

// 13 power-law local solver
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Local solver A', 'The power-law model reduces to a monotone scalar flux equation');
  eq(s, 'R(Nw) = Nw − nd j/F + (Bref/L) ∫as,surf^ar,surf (a/aref)^(pD+pS) da = 0', 0.72, 1.62, 11.90, 0.77, C.light, 16);
  codebox(s,
    '1  derive admissible flux interval from films\n2  initialize with mean-property conductance\n3  update surface activities from Nw\n4  evaluate exact power-law integral\n5  Newton update Nw within physical bracket\n6  reconstruct ASR and voltage components\n7  accept only if residual and surfaces pass',
    0.72, 2.76, 5.55, 3.35, 'EXACT POWER-LAW REDUCTION');
  rr(s, 6.62, 2.76, 6.00, 3.35, C.white, C.line);
  pill(s, 'Why this is useful', 6.97, 3.04, 1.81, C.paleTeal, C.teal);
  bullets(s, [
    'Constant drag removes the need for a spatial BVP solve.',
    'D, S and σ still vary locally through analytical power-law integrals.',
    'The flux residual tolerance is evaluated explicitly.',
    'The activity profile can be reconstructed exactly after convergence.'
  ], 7.02, 3.57, 5.10, 1.65, { fontSize: 12.5, space: 8 });
  eq(s, 'ASRmem = L · [∫ a^(pD+pS−pσ) da] / [σref ∫ a^(pD+pS) da]', 6.98, 5.36, 5.26, 0.50, C.paleBlue, 12.5);
  ref(s, 'Default screening configuration: 12 Newton flux iterations; relative flux residual tolerance 1×10⁻⁷.');
}

// 14 H-Nafion BVP
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Local solver B', 'The H-Nafion branch solves activity and voltage as a nonlinear BVP');
  rr(s, 0.72, 1.62, 5.56, 4.72, C.white, C.line);
  pill(s, 'Unknown fields and parameters', 1.03, 1.93, 2.54, C.paleTeal, C.teal);
  eq(s, 'y(ξ) = [ aw(ξ), V(ξ) ]', 1.05, 2.46, 4.88, 0.60, C.light, 17);
  eq(s, 'p = [ Nw, j ]', 1.05, 3.18, 4.88, 0.60, C.light, 17);
  eq(s, 'daw/dξ = L[nd j/F − Nw]/[D S]', 1.05, 3.90, 4.88, 0.66, C.paleBlue, 15);
  eq(s, 'dV/dξ = L j/σ + nd RT/F · (1/aw)daw/dξ', 1.05, 4.68, 4.88, 0.73, C.paleTeal, 14.5);
  text(s, 'ξ = x/L ∈ [0,1]', 1.05, 5.70, 4.88, 0.28, { fontFace: 'Cambria Math', fontSize: 14, bold: true, color: C.navy, align: 'center' });
  rr(s, 6.63, 1.62, 5.99, 4.72, C.navy2, C.navy2);
  pill(s, 'Four boundary conditions', 6.98, 1.93, 2.35, '1C4A68', C.cyan);
  const bcs = [
    'aw(0) = as,bulk − Nw/Ks',
    'aw(1) = ar,bulk + Nw/Kr',
    'V(0) = 0',
    'V(1) = Vapplied − Vfixed − jASRseries'
  ];
  bcs.forEach((v, i) => eq(s, v, 7.00, 2.48 + i * 0.70, 5.22, 0.52, '1A4563', 14.5, C.white));
  text(s, 'Local λ(aw), D(λ,T), σ(λ,T), S(aw) and nd(λ) are evaluated inside the ODE.', 7.05, 5.48, 5.12, 0.50, { fontSize: 11.5, color: 'CBDCE4', align: 'center' });
  ref(s, 'SciPy solve_bvp; default tolerance 2×10⁻⁵ and maximum 400 mesh nodes. Correlation-domain validity is reported separately.');
}

// 15 voltage root
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Voltage control', 'Current is obtained by a bracketed root solve at each local state');
  codebox(s,
    'given Vapplied\n\n1  set jlow = 0\n2  derive jhigh from gas-film surface limit\n3  solve local flux/profile at jlow and jhigh\n4  verify Vapplied is bracketed\n5  bisect current interval\n6  re-solve local state at jmid\n7  stop when |Vcalc − Vapplied| ≤ tolerance',
    0.72, 1.65, 5.34, 4.77, 'VOLTAGE → CURRENT');
  rr(s, 6.42, 1.65, 6.20, 2.25, C.white, C.line);
  pill(s, 'Default numerical controls', 6.76, 1.96, 2.43, C.paleBlue, C.blue);
  const vals = [
    ['Bisection iterations', '36'],
    ['Absolute voltage tolerance', '2 × 10⁻⁶ V'],
    ['Relative voltage tolerance', '2 × 10⁻⁶'],
    ['Internal search ceiling', 'numerical guard']
  ];
  vals.forEach((v, i) => {
    text(s, v[0], 6.82, 2.50 + i * 0.33, 3.38, 0.25, { fontSize: 10.5, color: C.muted });
    text(s, v[1], 10.26, 2.50 + i * 0.33, 1.93, 0.25, { fontSize: 10.5, bold: true, color: C.navy, align: 'right' });
  });
  rr(s, 6.42, 4.22, 6.20, 2.20, C.paleOrange, C.orange);
  pill(s, 'Interpretation', 6.76, 4.51, 1.52, 'FBE1C8', C.orange);
  text(s, 'The internal current ceiling bounds the root search. It is not an engineering acceptance limit.', 6.80, 5.03, 5.42, 0.54, { fontSize: 13.5, bold: true, color: C.navy, align: 'center' });
  text(s, 'A legacy 21 A/m² acceptance gate has been superseded. Current density is reported as a diagnostic unless an explicit sensitivity is declared.', 6.83, 5.66, 5.35, 0.48, { fontSize: 11.2, color: C.muted, align: 'center' });
  ref(s, 'Voltage root implementation: solve_powerlaw_voltage_control().');
}

// 16 local gating
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Fail-closed behavior', 'Local states are rejected with explicit failure categories');
  const ok = [
    'voltage root bracket exists', 'profile / scalar solve converged', '0 < surface activities < 1',
    'finite positive current', 'finite positive net flux', 'terminal-voltage reconstruction passes'
  ];
  rr(s, 0.72, 1.62, 5.74, 4.62, C.paleTeal, C.paleTeal);
  pill(s, 'Required for acceptance', 1.04, 1.92, 2.21, 'C7EDE7', C.teal);
  ok.forEach((v, i) => status(s, 1.08, 2.55 + i * 0.50, true, v));
  const bad = [
    'below reversible voltage', 'physical/profile bracket failure', 'voltage root non-convergence',
    'activity profile out of bounds', 'non-positive water flux', 'internal search ceiling encountered'
  ];
  rr(s, 6.80, 1.62, 5.82, 4.62, C.paleRed, C.paleRed);
  pill(s, 'Reported failure modes', 7.13, 1.92, 2.13, 'F6D4D2', C.red);
  bad.forEach((v, i) => status(s, 7.18, 2.55 + i * 0.50, false, v));
  text(s, 'Missing or failed components remain unavailable; they are not silently set to zero.', 0.72, 6.46, 11.90, 0.32, { fontSize: 14, bold: true, color: C.red, align: 'center' });
  ref(s, 'Failure mapping: status_category() and coupled_local_gate().');
}

// 17 axial integration
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Axial process integration', 'The local membrane problem is re-solved as the air state changes with area');
  eq(s, 'dwprocess/dA = −Mw Nw / ṁda,process', 0.72, 1.62, 4.22, 0.70, C.paleBlue, 18);
  eq(s, 'dTprocess/dA = fheat(Vj) / [ṁda cp,moist]', 0.72, 2.48, 4.22, 0.70, C.paleOrange, 17);
  card(s, 0.72, 3.52, 4.22, 1.58, 'Thermal modes', 'Isothermal: dT/dA = 0.\nAdiabatic upper bound: a declared fraction of local cell power heats the process air.', C.orange);
  codebox(s,
    'for each area step ΔA:\n  solve local state at step start\n  predict w and T at step end\n  solve local state at predicted end\n  halve ΔA if end state fails\n  integrate mean flux and mean power\n  shorten final step exactly at target\n  update air state and continue',
    5.28, 1.62, 4.65, 3.48, 'PREDICTOR–CORRECTOR');
  rr(s, 10.27, 1.62, 2.35, 3.48, C.white, C.line);
  pill(s, 'Audits', 10.66, 1.94, 1.55, C.paleTeal, C.teal);
  const aud = ['target event resolved', 'water integral = air balance', 'power integrated by area', 'max j / min Nw retained', 'step failure categorized'];
  aud.forEach((v, i) => {
    status(s, 10.55, 2.51 + i * 0.48, true);
    text(s, v, 10.88, 2.48 + i * 0.48, 1.45, 0.32, { fontSize: 9.8, color: C.ink });
  });
  rr(s, 0.72, 5.45, 11.90, 0.84, C.navy2, C.navy2);
  text(s, 'Why area is the integration coordinate', 1.03, 5.67, 2.78, 0.28, { fontSize: 12.5, bold: true, color: C.cyan });
  text(s, 'The duty is proportional to local flux × active area, and the required total area is an output.', 3.99, 5.62, 8.10, 0.38, { fontSize: 13.5, color: C.white });
  ref(s, 'Native derivative and local-state interfaces: src/heiq/wp1/axial/local_state.py and axial/integration.py.');
}

// 18 coupled receiver
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Two-stream integration', 'The same local flux updates process and receiver water balances');
  rr(s, 0.72, 1.64, 11.90, 1.58, C.white, C.line);
  arrow(s, 1.15, 2.05, 11.95, 2.05, C.blue, 3.2);
  arrow(s, 11.95, 2.72, 1.15, 2.72, C.teal, 3.2);
  text(s, 'process direction  +A', 1.23, 1.74, 2.13, 0.25, { fontSize: 10, bold: true, color: C.blue });
  text(s, 'counter-current receiver', 9.85, 2.79, 2.10, 0.25, { fontSize: 10, bold: true, color: C.teal, align: 'right' });
  for (let i = 0; i < 8; i++) {
    rr(s, 1.27 + i * 1.33, 2.21, 0.83, 0.35, i === 4 ? C.paleTeal : C.light, i === 4 ? C.teal : C.line);
  }
  eq(s, 'Δṁw = N̄w Mw ΔA', 0.72, 3.56, 3.70, 0.67, C.paleTeal, 18);
  eq(s, 'wP,next = wP − Δṁw/ṁP', 4.72, 3.56, 3.70, 0.67, C.paleBlue, 17);
  eq(s, 'wR,next = wR ± Δṁw/ṁR', 8.72, 3.56, 3.90, 0.67, C.paleOrange, 17);
  card(s, 0.72, 4.56, 5.75, 1.41, 'Counter-current boundary construction', 'Integration starts at the process inlet paired with the receiver outlet. That receiver outlet is conditioned by the target and the global water balance.', C.cyan);
  card(s, 6.80, 4.56, 5.82, 1.41, 'Published only when closed', 'If the process target is not reached, the assumed counter-current receiver outlet is not a solved physical boundary and is returned as unavailable.', C.red);
  text(s, 'Required residuals: process balance + receiver balance + counter-current far-end boundary.', 0.72, 6.31, 11.90, 0.32, { fontSize: 13.5, bold: true, color: C.navy, align: 'center' });
  ref(s, 'Implementation: integrate_coupled_receiver_case() in src/heiq/wp1/receiver/coupled_integration.py.');
}

// 19 direct active ERV segmentation
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Selected active-ERV screening path', 'Balanced endpoints are interpolated, then each segment is locally sized');
  const stages = [
    ['1', 'Choose process outlet w', 'defines requested total water duty'],
    ['2', 'Close receiver endpoint', 'same transferred water; balanced dry-air flows'],
    ['3', 'Prescribe sensible endpoint', 'effectiveness-based process temperature'],
    ['4', 'Interpolate bulk states', 'typically 8 counter-current segments'],
    ['5', 'Solve local membrane', 'midpoints plus n+1 physical boundaries'],
    ['6', 'Size and integrate', 'Ai = ṅw,i/Nw,i; P = ΣVi ji Ai']
  ];
  stages.forEach((v, i) => {
    const x = 0.67 + i * 2.08;
    rr(s, x, 1.90, 1.75, 2.57, C.white, C.line);
    badge(s, v[0], x + 0.66, 1.66, i < 3 ? C.blue : i < 5 ? C.cyan : C.teal);
    text(s, v[1], x + 0.16, 2.26, 1.43, 0.55, { fontSize: 13, bold: true, color: C.navy, align: 'center' });
    text(s, v[2], x + 0.17, 3.11, 1.41, 0.75, { fontSize: 10.2, color: C.muted, align: 'center', valign: 'top' });
    if (i < stages.length - 1) arrow(s, x + 1.78, 3.11, x + 2.02, 3.11, C.cyan, 1.9);
  });
  rr(s, 0.72, 4.95, 7.36, 1.15, C.paleOrange, C.orange);
  text(s, 'Reduced-order assumption', 1.00, 5.17, 2.12, 0.28, { fontSize: 12.5, bold: true, color: C.orange });
  text(s, 'Bulk T and w are interpolated between balanced endpoints; they are not obtained from a conjugate axial heat-and-mass PDE.', 3.20, 5.10, 4.46, 0.49, { fontSize: 12.5, color: C.navy });
  rr(s, 8.37, 4.95, 4.25, 1.15, C.paleTeal, C.teal);
  text(s, 'Boundary robustness', 8.67, 5.17, 1.63, 0.28, { fontSize: 12.5, bold: true, color: C.teal });
  text(s, 'n segments require n+1 boundary solves so midpoint-only feasibility cannot hide an end-state reversal.', 10.42, 5.10, 1.80, 0.50, { fontSize: 10.3, color: C.navy });
  ref(s, 'Implementation: build_direct_eo_endpoints(), build_segments() and solve_segmented_transport().');
}

// 20 comparison integration paths
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Model topology', 'Two integration paths answer different questions');
  rr(s, 0.72, 1.63, 5.78, 4.70, C.paleTeal, C.paleTeal);
  pill(s, 'Path A • coupled V12.1', 1.06, 1.95, 2.25, 'C8EDE7', C.teal);
  text(s, 'State-marching receiver model', 1.08, 2.48, 5.06, 0.36, { fontSize: 17, bold: true, color: C.navy, align: 'center' });
  bullets(s, [
    'Process and receiver humidity evolve step by step with area.',
    'Local membrane problem is re-solved at start and end of each step.',
    'Counter-current outlet is conditioned and audited at the far end.',
    'Adaptive step halving and exact target-event shortening.',
    'Best for target-reaching area / receiver sensitivity studies.'
  ], 1.13, 3.03, 4.93, 2.17, { fontSize: 12.2, space: 8 });
  rr(s, 6.82, 1.63, 5.80, 4.70, C.paleOrange, C.paleOrange);
  pill(s, 'Path B • direct active ERV', 7.16, 1.95, 2.47, 'F9DEC4', C.orange);
  text(s, 'Endpoint-segmented screening model', 7.18, 2.48, 5.06, 0.36, { fontSize: 17, bold: true, color: C.navy, align: 'center' });
  bullets(s, [
    'Balanced process and receiver endpoints are constructed first.',
    'Bulk states are linearly interpolated through a fixed segment count.',
    'Each segment is sized at a representative local state.',
    'Explicit boundary-state direction and voltage audits are added.',
    'Best for fast architecture / material frontier screening.'
  ], 7.23, 3.03, 4.93, 2.17, { fontSize: 12.2, space: 8 });
  rr(s, 1.25, 5.65, 10.85, 0.45, C.navy2, C.navy2);
  text(s, 'Outputs from the two paths are not interchangeable unless material, geometry, receiver and numerical basis are matched.', 1.50, 5.74, 10.35, 0.27, { fontSize: 12.5, bold: true, color: C.white, align: 'center' });
  ref(s, 'This distinction explains why different O30 area studies can produce different—but internally valid—numbers.');
}

// 21 coil model
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Cooling-coil coupling', 'Remaining latent and sensible duty is solved from a reduced ADP model');
  eq(s, 'wtarget = BF · win + (1 − BF) · wADP', 0.72, 1.64, 5.40, 0.70, C.paleBlue, 18);
  eq(s, 'hoff = BF · hin + (1 − BF) · hADP', 0.72, 2.50, 5.40, 0.70, C.paleBlue, 18);
  eq(s, 'Q̇cool = ṁda(hin − hoff)', 0.72, 3.36, 5.40, 0.70, C.paleTeal, 18);
  eq(s, 'ṁcond = ṁda(win − woff)', 0.72, 4.22, 5.40, 0.70, C.paleTeal, 18);
  eq(s, 'Pcomp = Q̇cool / COP', 0.72, 5.08, 5.40, 0.70, C.paleOrange, 18);
  rr(s, 6.48, 1.64, 6.14, 2.46, C.white, C.line);
  pill(s, 'COP scaling', 6.83, 1.96, 1.42, C.paleTeal, C.teal);
  eq(s, 'COPCarnot = Tevap / (Tcond − Tevap)', 6.84, 2.50, 5.40, 0.64, C.light, 17);
  text(s, 'COP = COPrated [1 + ηcons(COPCarnot/COPCarnot,rated − 1)]', 6.86, 3.30, 5.38, 0.39, { fontFace: 'Cambria Math', fontSize: 13.5, color: C.navy, align: 'center' });
  rr(s, 6.48, 4.44, 6.14, 1.34, C.paleOrange, C.orange);
  text(s, 'Physical checks', 6.82, 4.69, 1.46, 0.28, { fontSize: 12.5, bold: true, color: C.orange });
  text(s, 'off-coil RH ≤ 1; supply RH ≤ 1; finite COP; reheat mode explicitly declared; “none” is invalid if reheat is required.', 8.45, 4.63, 3.75, 0.61, { fontSize: 11.6, color: C.navy });
  text(s, 'The coil is a reduced endpoint model—not a refrigerant-cycle simulation.', 6.48, 6.12, 6.14, 0.29, { fontSize: 12.5, bold: true, color: C.red, align: 'center' });
  ref(s, 'Implementation: solve_coil() and _scaled_cop() in src/heiq/wp1/studies/direct_eo_erv.py.');
}

// 22 hydraulics
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Hydraulic screen', 'Membrane area is translated into channel length and fan power');
  const chain = [
    ['Air volume flow', 'V̇ = ṁda · v'], ['Total channel width', 'Wtot = V̇/(u g)'],
    ['Channel length', 'ℓ = A/(Nsides Wtot)'], ['Reynolds number', 'Re = ρuDh/μ'],
    ['Pressure drop', 'laminar or Blasius screen'], ['Fan power', 'Pfan = V̇Δp/ηfan']
  ];
  chain.forEach((v, i) => {
    const x = 0.68 + i * 2.08;
    card(s, x, 1.82, 1.76, 2.16, v[0], v[1], i < 3 ? C.blue : i < 5 ? C.orange : C.teal);
    if (i < chain.length - 1) arrow(s, x + 1.79, 2.90, x + 2.03, 2.90, C.gray, 1.6);
  });
  eq(s, 'Δp = 12 μ ℓ u / g²    (Re ≤ 2300)', 0.72, 4.40, 5.55, 0.68, C.paleBlue, 17);
  eq(s, 'Δp = f (ℓ/Dh) ρu²/2,   f = 0.3164 Re⁻⁰·²⁵', 0.72, 5.24, 5.55, 0.68, C.paleOrange, 16);
  rr(s, 6.62, 4.40, 6.00, 1.52, C.navy2, C.navy2);
  pill(s, 'Conservative selection', 6.98, 4.71, 2.13, '1D4967', C.cyan);
  text(s, 'Selected active-core fan power = max(native ideal-channel estimate, declared ERV pressure-drop floor).', 7.04, 5.23, 5.12, 0.43, { fontSize: 13, bold: true, color: C.white, align: 'center' });
  text(s, 'This is a packaging screen; manifolds, maldistribution and fouling remain outside the model.', 0.72, 6.34, 11.90, 0.31, { fontSize: 13.5, bold: true, color: C.red, align: 'center' });
  ref(s, 'Implementation: src/heiq/wp1/engineering/channels.py and direct_eo_core_hydraulics().');
}

// 23 power ledger
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Energy accounting', 'Electrical identities are checked locally before system totals are formed');
  eq(s, 'Vterminal j = Vmembrane j + j²ASRseries + Vfixed j', 0.72, 1.63, 7.20, 0.74, C.light, 18);
  eq(s, 'PEO,cell = ∫A Vterminal j dA', 0.72, 2.53, 7.20, 0.74, C.paleTeal, 18);
  eq(s, 'PEO,grid = PEO,cell / ηelectronics', 0.72, 3.43, 7.20, 0.74, C.paleBlue, 18);
  eq(s, 'Pknown = PAC + PEO,grid + Pfans + Pcommon + included losses', 0.72, 4.33, 7.20, 0.74, C.paleOrange, 16);
  rr(s, 8.27, 1.63, 4.35, 3.44, C.white, C.line);
  pill(s, 'Ledger discipline', 8.62, 1.94, 1.76, C.paleTeal, C.teal);
  const led = [
    'component power identity checked per area step',
    'missing terms remain unavailable—not zero',
    'site / grid conversion efficiency declared',
    'common loads applied consistently to comparators',
    'system claim disabled if required component unresolved'
  ];
  led.forEach((v, i) => status(s, 8.63, 2.49 + i * 0.45, true, v));
  rr(s, 8.27, 5.37, 4.35, 0.77, C.paleRed, C.red);
  text(s, 'Receiver regeneration and heat rejection are not closed in the selected gas-receiver architecture.', 8.55, 5.54, 3.79, 0.38, { fontSize: 11.5, bold: true, color: C.navy, align: 'center' });
  text(s, 'System savings are conditional until the full ledger is closed.', 0.72, 6.34, 7.20, 0.31, { fontSize: 13.5, bold: true, color: C.red, align: 'center' });
  ref(s, 'Boundary discipline is also documented in docs/SYSTEM_ENERGY_CLOSURE_STUDY.md.');
}

// 24 inverse design
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Parameter exploration', 'The framework supports forward prediction and inverse design');
  rr(s, 0.72, 1.65, 5.64, 1.52, C.paleBlue, C.paleBlue);
  pill(s, 'Forward model', 1.02, 1.94, 1.49, 'D2E5F7', C.blue);
  text(s, 'measured material vector + operating point', 1.02, 2.45, 2.35, 0.34, { fontSize: 12, bold: true, color: C.navy, align: 'center' });
  arrow(s, 3.54, 2.62, 4.11, 2.62, C.blue, 2.2);
  text(s, 'system flux, area and power', 4.24, 2.45, 1.74, 0.34, { fontSize: 12, bold: true, color: C.navy, align: 'center' });
  rr(s, 6.68, 1.65, 5.94, 1.52, C.paleTeal, C.paleTeal);
  pill(s, 'Inverse design', 6.99, 1.94, 1.54, 'C7EDE7', C.teal);
  text(s, 'target humidity, voltage and area contract', 6.99, 2.45, 2.35, 0.34, { fontSize: 12, bold: true, color: C.navy, align: 'center' });
  arrow(s, 9.51, 2.62, 10.08, 2.62, C.teal, 2.2);
  text(s, 'required property region', 10.21, 2.45, 1.90, 0.34, { fontSize: 12, bold: true, color: C.navy, align: 'center' });
  rr(s, 0.72, 3.57, 11.90, 2.39, C.white, C.line);
  pill(s, 'Default screening domains', 1.04, 3.88, 2.24, C.light, C.navy);
  const pars = [
    ['nd', '0.3–120', 'log'], ['Dref', '10⁻¹²–10⁻⁹ m²/s', 'log'], ['σref', '0.1–50 S/m', 'log'],
    ['L', '10–100 μm', 'log / set'], ['V', '0.003–2.5 V', 'log'], ['Sref', '10⁴–10⁵ mol m⁻³ aw⁻¹', 'set'],
    ['pD', '0–4', 'uniform'], ['pσ', '0–8', 'uniform'], ['pS', '−1–2', 'uniform']
  ];
  pars.forEach((p, i) => {
    const col = i % 3, row = Math.floor(i / 3), x = 1.05 + col * 3.75, y = 4.42 + row * 0.47;
    text(s, p[0], x, y, 0.58, 0.28, { fontFace: 'Cambria Math', fontSize: 12, bold: true, color: [C.blue,C.cyan,C.orange][col] });
    text(s, p[1], x + 0.64, y, 1.93, 0.28, { fontSize: 10.5, color: C.navy });
    text(s, p[2], x + 2.59, y, 0.62, 0.28, { fontSize: 9.5, color: C.gray, align: 'right' });
  });
  text(s, 'Sampling is not a probability model unless distributions are physically justified.', 0.72, 6.29, 11.90, 0.31, { fontSize: 13.5, bold: true, color: C.red, align: 'center' });
  ref(s, 'Ranges shown from heiq_pre_receiver_material_analyses/config/default.json; downstream studies may override them.');
}

// 25 verification
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Numerical verification', 'Conservation, equivalence and convergence checks are explicit');
  rr(s, 0.72, 1.63, 4.00, 4.63, C.navy2, C.navy2);
  text(s, '41', 1.06, 2.02, 3.30, 0.72, { fontSize: 42, bold: true, color: C.cyan, align: 'center' });
  text(s, 'selected relevant tests passed', 1.05, 2.80, 3.32, 0.33, { fontSize: 13.5, bold: true, color: C.white, align: 'center' });
  text(s, 'Executed 02 Sep 2026', 1.05, 3.22, 3.32, 0.26, { fontSize: 9.5, color: 'BFD1DA', align: 'center' });
  line(s, 1.12, 3.72, 3.18, 0, '335971', 1);
  const ts = ['membrane thermodynamics', 'axial equivalence', 'receiver API', 'gradient closure', 'direct active ERV', 'O30 required-area workflow'];
  ts.forEach((v, i) => { status(s, 1.06, 3.98 + i * 0.31, true); text(s, v, 1.39, 3.95 + i * 0.31, 2.77, 0.25, { fontSize: 9.8, color: 'E1EBF0' }); });
  rr(s, 5.07, 1.63, 3.55, 4.63, C.white, C.line);
  pill(s, 'Residual audits', 5.40, 1.94, 1.58, C.paleTeal, C.teal);
  const rs = ['local flux residual', 'terminal-voltage error', 'process water balance', 'receiver water balance', 'counter-current boundary', 'segment continuity', 'electrical component identity'];
  rs.forEach((v, i) => status(s, 5.42, 2.54 + i * 0.43, true, v));
  rr(s, 8.97, 1.63, 3.65, 4.63, C.paleOrange, C.orange);
  pill(s, 'Step-halving audit', 9.30, 1.94, 1.79, 'F9DEC4', C.orange);
  text(s, '20 m² step', 9.32, 2.62, 1.34, 0.28, { fontSize: 11, color: C.muted });
  text(s, '10,499.7174 m²', 10.61, 2.62, 1.58, 0.28, { fontSize: 11, bold: true, color: C.navy, align: 'right' });
  text(s, '10 m² step', 9.32, 3.03, 1.34, 0.28, { fontSize: 11, color: C.muted });
  text(s, '10,499.6770 m²', 10.61, 3.03, 1.58, 0.28, { fontSize: 11, bold: true, color: C.navy, align: 'right' });
  line(s, 9.30, 3.50, 2.90, 0, 'E9B98F', 1);
  text(s, 'relative difference', 9.32, 3.78, 1.47, 0.28, { fontSize: 11, color: C.muted });
  text(s, '0.000385%', 10.80, 3.74, 1.40, 0.34, { fontSize: 18, bold: true, color: C.orange, align: 'right' });
  text(s, 'Fixed case-94 basis at receiver multiplier 3.0.', 9.33, 4.39, 2.84, 0.48, { fontSize: 10.5, color: C.muted, align: 'center' });
  rr(s, 9.31, 5.18, 2.88, 0.63, C.paleRed, C.paleRed);
  text(s, 'Verification ≠ experimental validation', 9.47, 5.29, 2.56, 0.34, { fontSize: 11.5, bold: true, color: C.red, align: 'center' });
  ref(s, 'Test command covered six relevant test modules; convergence example from docs/O30_REQUIRED_AREA_1V_v1.md.');
}

// 26 version/basis matrix
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Basis control', 'Published O30 numbers must be tied to their exact model contract');
  rr(s, 0.72, 1.63, 11.90, 4.73, C.white, C.line);
  const widths = [2.50, 2.52, 2.25, 2.18, 2.45];
  const x0 = 0.72;
  const xs = [x0]; widths.slice(0,-1).forEach((v,i)=>xs.push(xs[i]+v));
  const headers = ['Study basis', 'Integration method', 'Fixed basis', 'Illustrative O30 area', 'Interpretation'];
  headers.forEach((h, i) => {
    s.addShape(S.rect, { x: xs[i], y: 1.63, w: widths[i], h: 0.65, fill: { color: C.navy2 }, line: { color: C.white, width: 0.5 } });
    text(s, h, xs[i] + 0.10, 1.79, widths[i] - 0.20, 0.29, { fontSize: 10.5, bold: true, color: C.white, align: 'center' });
  });
  const table = [
    ['Selected final-system interpretation', '8-segment endpoint sizing', 'selected material frontier; architecture-specific endpoint assumptions', '5,899 m² at 1 V', 'Used for the earlier 418.4 kW system interpretation'],
    ['Nonlinear required-area study', 'coupled V12.1 target-reaching integration', 'legacy case-94 material + fixed channel geometry + receiver multiplier', '10,499.7–12,139.9 m² at 1 V', 'Receiver airflow changes area and core power'],
    ['Canonical local hierarchy', 'V2 local → V3 axial → V12.1 receiver', 'declared per workflow', 'not one universal value', 'Model chain; outputs depend on explicit contract']
  ];
  table.forEach((row, r) => {
    const y = 2.28 + r * 1.25;
    row.forEach((v, i) => {
      s.addShape(S.rect, { x: xs[i], y, w: widths[i], h: 1.25, fill: { color: r % 2 ? 'F7F9FA' : C.white }, line: { color: C.line, width: 0.6 } });
      text(s, v, xs[i] + 0.13, y + 0.12, widths[i] - 0.26, 0.94, { fontSize: i === 3 ? 11.5 : 10.2, bold: i === 0 || i === 3, color: i === 3 ? (r === 0 ? C.teal : r === 1 ? C.orange : C.navy) : C.ink, align: i === 3 ? 'center' : 'left', valign: 'top' });
    });
  });
  rr(s, 1.13, 6.17, 11.08, 0.47, C.paleRed, C.paleRed);
  text(s, 'Different areas are not a contradiction when material, geometry, receiver boundary and integration method differ—but they must never be merged.', 1.35, 6.27, 10.64, 0.27, { fontSize: 12, bold: true, color: C.red, align: 'center' });
  ref(s, 'Sources: selected v9 interpretation and docs/O30_REQUIRED_AREA_1V_v1.md.');
}

// 27 assumptions and uncertainty
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Assumption ledger', 'The model is strongest where conservation is explicit—and weakest where closure is prescribed');
  const groups = [
    ['Well constrained numerically', ['local sign convention', 'water balances', 'voltage reconstruction', 'surface admissibility', 'target-event resolution'], C.teal, C.paleTeal],
    ['Prescribed model closures', ['sensible / latent effectiveness', 'power-law property shapes', 'film correlation and scale', 'segment bulk interpolation', 'scaled-Carnot COP'], C.orange, C.paleOrange],
    ['Not yet experimentally closed', ['vapor nd for target material', 'RH-resolved ASR under load', 'electrode heat and losses', 'receiver water handling', 'manifolds / fouling / lifetime'], C.red, C.paleRed]
  ];
  groups.forEach((g, i) => {
    const x = 0.72 + i * 4.03;
    rr(s, x, 1.65, 3.76, 4.69, g[3], g[3]);
    pill(s, g[0], x + 0.27, 1.96, 3.22, i === 0 ? 'C7EDE7' : i === 1 ? 'F9DEC4' : 'F6D4D2', g[2]);
    g[1].forEach((v, j) => {
      status(s, x + 0.36, 2.70 + j * 0.57, i === 0);
      text(s, v, x + 0.72, 2.65 + j * 0.57, 2.62, 0.34, { fontSize: 11.5, color: C.navy });
    });
    text(s, i === 0 ? 'Verification evidence' : i === 1 ? 'Sensitivity required' : 'Experimental evidence required', x + 0.30, 5.79, 3.16, 0.28, { fontSize: 10.5, bold: true, color: g[2], align: 'center' });
  });
  ref(s, 'The inverse-design property vector is a target region, not a validated material identification.');
}

// 28 validation map
{
  const s = pptx.addSlide('TECH');
  heading(s, 'Experimental validation map', 'Each high-impact model term should have a direct measurement pathway');
  const rows = [
    ['Net EO transport Nw', 'matched polarity reversal + EO-off control', 'mass gain/loss on both gas streams', 'direction, repeatability, uncertainty'],
    ['Effective drag nd', 'measure NEO and current at the same state', 'nd = NEO F/j', 'vapor-specific—not liquid-cell inferred'],
    ['D(aw)S(aw)', 'passive activity-gradient series', 'steady diffusion flux vs. Δaw and L', 'separate films from membrane'],
    ['σ(aw) / ASR', 'impedance or DC under representative RH', 'area resistance and temperature', 'same hydration as flux test'],
    ['Gas films Ks, Kr', 'vary velocity and channel gap', 'flux response + blank-cell pressure drop', 'test Sh correlation and bypass'],
    ['Voltage / heat ledger', 'simultaneous V, I and calorimetry', 'V components, electrical heat partition', 'stable operation near 1 V'],
    ['Receiver closure', 'meter inlet/outlet humidity and any condensate', 'full donor/receiver water balance', 'saturation and removal mechanism']
  ];
  rr(s, 0.72, 1.58, 11.90, 4.96, C.white, C.line);
  const ws = [2.20, 3.02, 3.02, 3.66], xs = [0.72,2.92,5.94,8.96];
  ['Model quantity','Experiment','Measured observable','Acceptance focus'].forEach((h,i)=>{
    s.addShape(S.rect,{x:xs[i],y:1.58,w:ws[i],h:0.56,fill:{color:C.navy2},line:{color:C.white,width:0.5}});
    text(s,h,xs[i]+0.10,1.72,ws[i]-0.20,0.26,{fontSize:10,bold:true,color:C.white,align:'center'});
  });
  rows.forEach((r,ri)=>{
    const y=2.14+ri*0.62;
    r.forEach((v,i)=>{
      s.addShape(S.rect,{x:xs[i],y,w:ws[i],h:0.62,fill:{color:ri%2?'F7F9FA':C.white},line:{color:C.line,width:0.5}});
      text(s,v,xs[i]+0.11,y+0.08,ws[i]-0.22,0.44,{fontSize:i===0?10.2:9.3,bold:i===0,color:i===0?C.navy:C.muted,valign:'top'});
    });
  });
  text(s, 'A coupon test should target the incremental EO duty—not the total active-core water transfer that already includes passive recovery.', 0.72, 6.67, 11.90, 0.28, { fontSize: 12.5, bold: true, color: C.navy, align: 'center' });
}

// 29 peer review conclusion
{
  const s = pptx.addSlide(); s.background = { color: C.navy };
  s.addShape(S.rect, { x: 0, y: 0, w: 13.333, h: 0.11, fill: { color: C.cyan }, line: { color: C.cyan } });
  text(s, 'PEER-REVIEW CONCLUSION', 0.72, 0.52, 3.2, 0.26, { fontSize: 10, bold: true, color: C.cyan, charSpacing: 1.5 });
  text(s, 'The model is auditable because its balances and failure modes are explicit.', 0.72, 1.14, 8.12, 1.08, { fontSize: 31, bold: true, color: C.white, valign: 'top' });
  const cols = [
    ['STRENGTH', 'Conservation, voltage closure, surface bounds and numerical statuses are enforced rather than assumed.', C.teal],
    ['KEY APPROXIMATION', 'The selected active-ERV path interpolates balanced bulk endpoints; it is not a conjugate axial PDE.', C.orange],
    ['VALIDATION GAP', 'The inverse-designed material vector and receiver / thermal hardware remain experimentally open.', C.red]
  ];
  cols.forEach((v,i)=>{
    const x=0.72+i*4.05;
    rr(s,x,2.76,3.72,2.12,C.navy2,'2A4C64');
    text(s,v[0],x+0.24,3.03,3.24,0.27,{fontSize:9.5,bold:true,color:v[2],align:'center',charSpacing:1.1});
    text(s,v[1],x+0.34,3.55,3.04,0.83,{fontSize:13,color:C.white,align:'center',valign:'top'});
  });
  rr(s,0.72,5.38,11.82,0.78,'103552','244B65');
  text(s,'Recommended review focus',1.01,5.60,2.21,0.27,{fontSize:12.5,bold:true,color:C.cyan});
  text(s,'Are the chosen constitutive ranges defensible? Is endpoint interpolation adequate? What data will close the receiver and heat ledger?',3.35,5.51,8.64,0.46,{fontSize:14,color:C.white});
  text(s,'HeiQ / XMembrane  •  Technical formulation and numerical implementation  •  02 September 2026',0.72,6.91,8.5,0.19,{fontSize:8.3,color:'90A8B5'});
}

pptx.writeFile({ fileName: 'deliverables/HeiQ_XMembrane_Technical_Model_Peer_Review_English_2026-09-02.pptx' });
