const pptxgen = require('pptxgenjs');

const pptx = new pptxgen();
pptx.layout = 'LAYOUT_WIDE';
pptx.author = 'OpenAI Codex for HeiQ / XMembrane';
pptx.company = 'HeiQ / XMembrane';
pptx.subject = 'Coupled electro-osmotic ERV model and O30 operating point';
pptx.title = 'Electro-Osmotic Water Transport Integrated into an ERV';
pptx.lang = 'en-US';
pptx.theme = {
  headFontFace: 'Lato',
  bodyFontFace: 'Lato',
  lang: 'en-US'
};
pptx.defineSlideMaster({
  title: 'MASTER',
  background: { color: 'F5F8FA' },
  objects: [
    { rect: { x: 0, y: 0, w: 13.333, h: 0.10, fill: { color: '00AFCB' }, line: { color: '00AFCB' } } },
    { text: { text: 'HEIQ  /  XMEMBRANE', options: { x: 0.65, y: 7.12, w: 2.4, h: 0.18, fontFace: 'Lato', fontSize: 8, bold: true, color: '5B6B78', margin: 0 } } },
    { text: { text: 'COUPLED MODEL • SEPTEMBER 2026', options: { x: 9.65, y: 7.12, w: 3.03, h: 0.18, fontFace: 'Lato', fontSize: 8, color: '7B8B98', align: 'right', margin: 0 } } }
  ],
  slideNumber: { x: 12.72, y: 7.11, w: 0.22, h: 0.18, fontFace: 'Lato', fontSize: 8, color: '7B8B98', align: 'right', margin: 0 }
});

const C = {
  navy: '0B1F33', navy2: '123653', cyan: '00AFCB', teal: '00BDAA', blue: '3178C6',
  lime: 'A8D241', orange: 'F4A261', red: 'E45756', ink: '142635', muted: '5B6B78',
  pale: 'EAF3F6', paleBlue: 'E8F1FA', paleTeal: 'E6F7F4', paleOrange: 'FFF2E6',
  line: 'D4E0E6', white: 'FFFFFF', bg: 'F5F8FA', gray: 'A7B6C2', lightGray: 'E8EEF2'
};

const S = pptx.ShapeType;
const A = pptx.ShapeType;

function addText(slide, text, x, y, w, h, opts = {}) {
  slide.addText(text, {
    x, y, w, h, fontFace: opts.fontFace || 'Lato', fontSize: opts.fontSize || 18,
    color: opts.color || C.ink, bold: opts.bold || false, italic: opts.italic || false,
    align: opts.align || 'left', valign: opts.valign || 'mid', margin: opts.margin === undefined ? 0 : opts.margin,
    breakLine: false, fit: opts.fit || 'shrink', bullet: opts.bullet,
    paraSpaceAfterPt: opts.paraSpaceAfterPt || 0, isTextBox: true,
    ...opts
  });
}

function title(slide, kicker, heading, sub = '') {
  addText(slide, kicker.toUpperCase(), 0.66, 0.38, 4.7, 0.24, { fontSize: 10, bold: true, color: C.cyan, charSpacing: 1.6 });
  addText(slide, heading, 0.66, 0.70, 11.95, 0.56, { fontSize: 28, bold: true, color: C.navy, fit: 'shrink' });
  if (sub) addText(slide, sub, 0.68, 1.27, 11.75, 0.35, { fontSize: 13, color: C.muted });
}

function roundRect(slide, x, y, w, h, fill, line = fill, radius = 0.12) {
  slide.addShape(S.roundRect, { x, y, w, h, rectRadius: radius, fill: { color: fill }, line: { color: line, width: 1 } });
}

function pill(slide, text, x, y, w, fill = C.pale, color = C.navy) {
  roundRect(slide, x, y, w, 0.34, fill, fill);
  addText(slide, text.toUpperCase(), x + 0.08, y + 0.01, w - 0.16, 0.30, { fontSize: 9, bold: true, color, align: 'center', charSpacing: 0.7 });
}

function metric(slide, x, y, w, value, unit, label, accent = C.cyan, note = '') {
  roundRect(slide, x, y, w, 1.35, C.white, C.line);
  slide.addShape(S.rect, { x, y, w: 0.08, h: 1.35, fill: { color: accent }, line: { color: accent } });
  addText(slide, value, x + 0.25, y + 0.13, w - 0.5, 0.49, { fontSize: 29, bold: true, color: C.navy });
  addText(slide, unit, x + 0.25, y + 0.60, w - 0.5, 0.26, { fontSize: 11, bold: true, color: accent });
  addText(slide, label, x + 0.25, y + 0.86, w - 0.5, 0.30, { fontSize: 11.5, color: C.muted, valign: 'top' });
  if (note) addText(slide, note, x + 0.25, y + 1.13, w - 0.5, 0.16, { fontSize: 8.5, color: C.gray });
}

function node(slide, x, y, w, h, heading, body, accent = C.cyan, fill = C.white) {
  roundRect(slide, x, y, w, h, fill, C.line);
  slide.addShape(S.rect, { x, y, w: 0.08, h, fill: { color: accent }, line: { color: accent } });
  addText(slide, heading, x + 0.24, y + 0.12, w - 0.38, 0.27, { fontSize: 14, bold: true, color: C.navy });
  addText(slide, body, x + 0.24, y + 0.42, w - 0.38, h - 0.53, { fontSize: 10.5, color: C.muted, valign: 'top', breakLine: true, paraSpaceAfterPt: 5 });
}

function arrow(slide, x1, y1, x2, y2, color = C.cyan, width = 2.5, end = 'triangle') {
  slide.addShape(S.line, { x: x1, y: y1, w: x2 - x1, h: y2 - y1, line: { color, width, beginArrowType: 'none', endArrowType: end } });
}

function sectionBand(slide, text, y, color = C.navy) {
  slide.addShape(S.rect, { x: 0.0, y, w: 13.333, h: 0.53, fill: { color }, line: { color } });
  addText(slide, text, 0.68, y + 0.03, 11.8, 0.44, { fontSize: 16, bold: true, color: C.white });
}

function addBullets(slide, items, x, y, w, h, opts = {}) {
  const runs = [];
  items.forEach((item, i) => {
    runs.push({ text: item, options: { bullet: { indent: opts.indent || 16 }, hanging: opts.hanging || 4, breakLine: i < items.length - 1 } });
  });
  slide.addText(runs, { x, y, w, h, fontFace: 'Lato', fontSize: opts.fontSize || 15, color: opts.color || C.ink,
    margin: 0, breakLine: false, valign: 'top', paraSpaceAfterPt: opts.space || 10, fit: 'shrink' });
}

function formula(slide, txt, x, y, w, h, accent = C.paleBlue) {
  roundRect(slide, x, y, w, h, accent, accent);
  addText(slide, txt, x + 0.18, y + 0.06, w - 0.36, h - 0.12, { fontFace: 'Cambria Math', fontSize: 17, color: C.navy, align: 'center' });
}

function check(slide, x, y, good = true) {
  slide.addShape(S.ellipse, { x, y, w: 0.26, h: 0.26, fill: { color: good ? C.teal : C.red }, line: { color: good ? C.teal : C.red } });
  addText(slide, good ? '✓' : '!', x, y - 0.01, 0.26, 0.27, { fontSize: 12, bold: true, color: C.white, align: 'center' });
}

// 1 — Cover
{
  const slide = pptx.addSlide();
  slide.background = { color: C.navy };
  slide.addShape(S.rect, { x: 0, y: 0, w: 13.333, h: 0.11, fill: { color: C.cyan }, line: { color: C.cyan } });
  addText(slide, 'HEIQ  /  XMEMBRANE', 0.72, 0.54, 3.0, 0.30, { fontSize: 12, bold: true, color: C.cyan, charSpacing: 1.6 });
  addText(slide, 'Electro-Osmotic Water\nTransport Integrated into an ERV', 0.72, 1.35, 7.5, 1.70, { fontSize: 34, bold: true, color: C.white, valign: 'top', breakLine: true });
  addText(slide, 'Coupled model • O30 operating point • Validation path', 0.74, 3.24, 6.5, 0.38, { fontSize: 16, color: 'BFD2DD' });
  pill(slide, 'Model synthesis', 0.74, 4.04, 1.65, C.navy2, C.cyan);
  pill(slide, 'English deck', 2.54, 4.04, 1.55, C.navy2, C.cyan);
  pill(slide, 'September 2026', 4.24, 4.04, 1.88, C.navy2, C.cyan);
  addText(slide, 'A physically based screening model that links moist-air thermodynamics, passive recovery, local membrane transport and cooling-coil power.', 0.74, 4.75, 6.7, 0.92, { fontSize: 15, color: 'D9E5EB', valign: 'top' });

  // abstract active-membrane visual
  roundRect(slide, 8.25, 0.78, 4.35, 5.95, C.navy2, C.navy2);
  addText(slide, 'ACTIVE ERV CORE', 8.63, 1.15, 3.6, 0.30, { fontSize: 11, bold: true, color: C.cyan, align: 'center', charSpacing: 1.4 });
  for (let i = 0; i < 7; i++) {
    const yy = 1.77 + i * 0.58;
    slide.addShape(S.line, { x: 8.78, y: yy, w: 3.25, h: 0, line: { color: i % 2 ? C.teal : C.blue, width: 5, transparency: 5 } });
    arrow(slide, i % 2 ? 11.74 : 9.06, yy, i % 2 ? 9.06 : 11.74, yy, i % 2 ? C.teal : C.blue, 1.5);
  }
  for (let i = 0; i < 9; i++) {
    const xx = 9.02 + i * 0.36;
    slide.addShape(S.ellipse, { x: xx, y: 3.55 + (i % 3) * 0.14, w: 0.09, h: 0.09, fill: { color: C.cyan, transparency: 10 }, line: { color: C.cyan, transparency: 100 } });
    arrow(slide, xx + 0.04, 3.43, xx + 0.04, 2.60, C.cyan, 1.1);
  }
  addText(slide, 'water transport', 9.50, 4.25, 1.8, 0.25, { fontSize: 10, color: 'BFD2DD', align: 'center' });
  formula(slide, 'Net transport = EO − back-diffusion', 8.78, 5.30, 3.30, 0.72, C.navy);
  addText(slide, 'Prepared from the controlled model description and selected final result set', 0.74, 6.94, 8.0, 0.20, { fontSize: 9, color: '8FA8B5' });
}

// 2 — Executive takeaway
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Executive takeaway', 'The model identifies a promising—but conditional—energy window', 'Selected O30 operating point; active membrane integrated directly into the ERV core.');
  metric(slide, 0.68, 1.90, 2.86, '418.4', 'kW', 'Known modeled total power', C.teal, 'Active ERV + EO + AC');
  metric(slide, 3.76, 1.90, 2.86, '125.34', 'kW', 'Conditional power window', C.cyan, 'vs. passive ERV + AC');
  metric(slide, 6.84, 1.90, 2.86, '5,899', 'm²', 'Selected active membrane area', C.blue, 'at 1.0 V terminal voltage');
  metric(slide, 9.92, 1.90, 2.74, '23.05', '%', 'Reduction in known modeled power', C.lime, 'EO-on vs. EO-off');
  roundRect(slide, 0.68, 3.60, 7.55, 2.45, C.white, C.line);
  pill(slide, 'What the result means', 0.94, 3.87, 2.10, C.paleTeal, C.teal);
  addBullets(slide, [
    'The passive ERV delivers the largest established reduction: 622.66 kW versus AC-only.',
    'EO adds 1,228.3 kg/h of incremental water-transfer duty at O30.',
    'Reduced latent load can lower both condensate duty and compressor lift.'
  ], 0.98, 4.35, 6.90, 1.48, { fontSize: 14.5, space: 9 });
  roundRect(slide, 8.48, 3.60, 4.18, 2.45, C.paleOrange, C.orange);
  pill(slide, 'Claim boundary', 8.75, 3.87, 1.65, 'FBE3C8', C.orange);
  addText(slide, 'This is not yet a validated net saving.', 8.78, 4.38, 3.45, 0.38, { fontSize: 17, bold: true, color: C.navy });
  addText(slide, 'Receiver, thermal management, power electronics, manifolds and additional hardware must collectively remain below 125.34 kW.', 8.78, 4.87, 3.42, 0.90, { fontSize: 12.5, color: C.muted, valign: 'top' });
  sectionBand(slide, 'Decision framing: validate the membrane vector and close the omitted subsystem losses before making a net-savings claim.', 6.36, C.navy2);
}

// 3 — Comparators
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'System comparison', 'Three systems isolate what passive recovery and EO each contribute');
  const xs = [0.72, 4.61, 8.50];
  const heads = ['1  •  AC only', '2  •  Passive ERV + AC', '3  •  Active ERV + EO + AC'];
  const values = ['1,166.400 kW', '543.741 kW', '418.400 kW'];
  const bodies = [
    'Outdoor air is treated directly by the cooling coil.',
    'Sensible and latent recovery reduce the coil duty before cooling.',
    'Voltage-driven water transport is added inside the same ERV membrane.'
  ];
  const colors = [C.orange, C.blue, C.teal];
  for (let i = 0; i < 3; i++) {
    roundRect(slide, xs[i], 1.65, 3.54, 3.18, C.white, C.line);
    slide.addShape(S.rect, { x: xs[i], y: 1.65, w: 3.54, h: 0.11, fill: { color: colors[i] }, line: { color: colors[i] } });
    addText(slide, heads[i], xs[i] + 0.25, 1.98, 3.04, 0.36, { fontSize: 16, bold: true, color: C.navy, align: 'center' });
    addText(slide, values[i], xs[i] + 0.25, 2.57, 3.04, 0.52, { fontSize: 28, bold: true, color: colors[i], align: 'center' });
    addText(slide, bodies[i], xs[i] + 0.35, 3.35, 2.84, 0.80, { fontSize: 12.5, color: C.muted, align: 'center', valign: 'top' });
    addText(slide, i === 0 ? 'BASELINE' : i === 1 ? 'EO OFF' : 'EO ON', xs[i] + 1.12, 4.36, 1.30, 0.28, { fontSize: 9, bold: true, color: colors[i], align: 'center', charSpacing: 1.2 });
  }
  arrow(slide, 4.33, 3.23, 4.56, 3.23, C.cyan, 2.5);
  arrow(slide, 8.22, 3.23, 8.45, 3.23, C.cyan, 2.5);
  roundRect(slide, 1.10, 5.25, 5.35, 1.00, C.paleBlue, C.paleBlue);
  addText(slide, '622.659 kW', 1.34, 5.40, 1.75, 0.33, { fontSize: 21, bold: true, color: C.blue });
  addText(slide, 'Passive ERV reduction vs. AC only', 3.06, 5.40, 3.05, 0.33, { fontSize: 13, color: C.navy });
  roundRect(slide, 6.84, 5.25, 5.35, 1.00, C.paleTeal, C.paleTeal);
  addText(slide, '125.340 kW', 7.08, 5.40, 1.86, 0.33, { fontSize: 21, bold: true, color: C.teal });
  addText(slide, 'Incremental EO window vs. EO off', 8.92, 5.40, 2.95, 0.33, { fontSize: 13, color: C.navy });
  addText(slide, 'Do not label the full AC-only → active-ERV difference as “EO savings.”', 0.72, 6.54, 11.95, 0.30, { fontSize: 13, bold: true, color: C.red, align: 'center' });
}

// 4 — Architecture
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Selected architecture', 'EO is embedded in the ERV membrane—not added as a separate downstream stage', 'The cooling coil remains in the system and completes cooling and dehumidification after O30.');
  addText(slide, 'OUTDOOR / PROCESS AIR', 0.78, 1.92, 2.2, 0.24, { fontSize: 10, bold: true, color: C.blue, charSpacing: 1.2 });
  arrow(slide, 0.90, 2.50, 2.08, 2.50, C.blue, 4);
  node(slide, 2.12, 1.92, 3.18, 1.18, 'Active ERV membrane', 'Passive sensible + latent recovery\nEO transport under applied voltage', C.cyan, C.white);
  arrow(slide, 5.32, 2.50, 6.08, 2.50, C.blue, 4);
  node(slide, 6.12, 1.92, 2.72, 1.18, 'Cooling coil', 'Remaining sensible + latent duty\nADP / bypass-factor solution', C.blue, C.white);
  arrow(slide, 8.86, 2.50, 10.04, 2.50, C.blue, 4);
  node(slide, 10.08, 1.92, 2.42, 1.18, 'Supply air', 'Final temperature and\nhumidity target', C.teal, C.white);
  addText(slide, 'EXHAUST / RECEIVER AIR', 0.78, 4.68, 2.3, 0.24, { fontSize: 10, bold: true, color: C.teal, charSpacing: 1.2 });
  arrow(slide, 11.76, 4.20, 2.80, 4.20, C.teal, 4);
  addText(slide, 'counter-current flow', 6.00, 4.37, 2.25, 0.27, { fontSize: 11, color: C.muted, italic: true, align: 'center' });
  arrow(slide, 3.72, 3.18, 3.72, 4.02, C.cyan, 3.2);
  pill(slide, 'Transferred water', 2.83, 3.48, 1.78, C.paleTeal, C.teal);
  roundRect(slide, 0.78, 5.18, 11.72, 1.12, C.white, C.line);
  addText(slide, 'Physical mechanisms', 1.04, 5.37, 1.84, 0.28, { fontSize: 14, bold: true, color: C.navy });
  const mech = [
    ['HEAT', 'warm → cool', C.orange],
    ['DIFFUSION', 'activity gradient', C.blue],
    ['EO', 'ionic current drags water', C.cyan]
  ];
  mech.forEach((m, i) => {
    pill(slide, m[0], 3.08 + i * 2.87, 5.35, 1.15, m[2] === C.orange ? C.paleOrange : m[2] === C.blue ? C.paleBlue : C.paleTeal, m[2]);
    addText(slide, m[1], 4.34 + i * 2.87, 5.36, 1.45, 0.29, { fontSize: 11.5, color: C.muted });
  });
}

// 5 — Model chain
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'End-to-end model chain', 'Local membrane physics is evaluated inside a complete HVAC energy balance');
  const steps = [
    ['1', 'Moist-air states', 'T, RH, w, h, dew point'],
    ['2', 'Passive ERV', 'sensible + latent effectiveness'],
    ['3', 'Local membrane', 'EO − diffusion + films'],
    ['4', 'Core integration', '8 representative segments'],
    ['5', 'Cooling coil', 'ADP, BF, condensate, COP'],
    ['6', 'Power comparison', 'compressor + fans + EO + losses']
  ];
  steps.forEach((s, i) => {
    const x = 0.72 + i * 2.06;
    roundRect(slide, x, 2.02, 1.74, 2.18, C.white, C.line);
    slide.addShape(S.ellipse, { x: x + 0.60, y: 1.73, w: 0.54, h: 0.54, fill: { color: i < 2 ? C.blue : i < 4 ? C.cyan : i === 4 ? C.teal : C.navy }, line: { color: C.white, width: 2 } });
    addText(slide, s[0], x + 0.60, 1.75, 0.54, 0.49, { fontSize: 15, bold: true, color: C.white, align: 'center' });
    addText(slide, s[1], x + 0.16, 2.47, 1.42, 0.46, { fontSize: 14, bold: true, color: C.navy, align: 'center' });
    addText(slide, s[2], x + 0.16, 3.10, 1.42, 0.66, { fontSize: 10.5, color: C.muted, align: 'center', valign: 'top' });
    if (i < 5) arrow(slide, x + 1.78, 3.08, x + 2.00, 3.08, C.cyan, 2.4);
  });
  roundRect(slide, 0.72, 4.73, 12.00, 1.18, C.navy2, C.navy2);
  addText(slide, 'Core modeling principle', 0.98, 4.95, 2.12, 0.29, { fontSize: 13, bold: true, color: C.cyan });
  addText(slide, 'Every kilogram of water removed from the process air must appear in the exhaust stream, and every included electrical load is carried into the final comparison.', 3.15, 4.87, 8.96, 0.55, { fontSize: 15, color: C.white });
  addText(slide, 'Forward model: measured membrane vector → system outcome', 1.15, 6.25, 4.75, 0.32, { fontSize: 13, bold: true, color: C.blue, align: 'center' });
  addText(slide, 'Inverse design: required system outcome → target material region', 7.00, 6.25, 5.25, 0.32, { fontSize: 13, bold: true, color: C.teal, align: 'center' });
  arrow(slide, 5.92, 6.42, 6.76, 6.42, C.gray, 1.8, 'triangle');
}

// 6 — Psychrometrics and passive ERV
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Layer 1', 'Psychrometrics and passive ERV recovery set the boundary conditions');
  node(slide, 0.72, 1.72, 3.55, 1.38, 'Moist-air state vector', 'Temperature T\nRelative humidity RH\nHumidity ratio w\nEnthalpy h, dew point and specific volume', C.blue, C.white);
  formula(slide, 'w = m_water / m_dry air', 0.72, 3.34, 3.55, 0.68, C.paleBlue);
  formula(slide, 'h ≈ 1.006T + w(2501 + 1.86T)', 0.72, 4.18, 3.55, 0.78, C.paleBlue);
  formula(slide, 'ṁw = ṁda (win − wout)', 0.72, 5.12, 3.55, 0.68, C.paleBlue);
  arrow(slide, 4.54, 3.80, 5.11, 3.80, C.cyan, 3);
  node(slide, 5.18, 1.72, 3.55, 1.38, 'Passive ERV effectiveness', 'Sensible effectiveness εs updates temperature.\nLatent effectiveness εl updates humidity ratio.', C.cyan, C.white);
  formula(slide, 'Tout = TOA − εs(TOA − Texh)', 5.18, 3.34, 3.55, 0.68, C.paleTeal);
  formula(slide, 'wout = wOA − εl(wOA − wexh)', 5.18, 4.18, 3.55, 0.78, C.paleTeal);
  formula(slide, 'Pfan = V̇ Δp / ηfan', 5.18, 5.12, 3.55, 0.68, C.paleTeal);
  arrow(slide, 9.00, 3.80, 9.57, 3.80, C.cyan, 3);
  roundRect(slide, 9.64, 1.72, 3.05, 4.08, C.white, C.line);
  pill(slide, 'Balance checks', 10.20, 2.02, 1.94, C.paleOrange, C.orange);
  const checks = [
    'Process / exhaust water balance',
    'Enthalpy balance',
    'No untreated condensation state',
    'Fan pressure-drop penalty'
  ];
  checks.forEach((t, i) => {
    check(slide, 10.01, 2.73 + i * 0.64, true);
    addText(slide, t, 10.40, 2.69 + i * 0.64, 1.93, 0.35, { fontSize: 11.5, color: C.ink });
  });
  addText(slide, 'Output: local T and water-activity boundaries for the active membrane.', 9.96, 5.25, 2.37, 0.36, { fontSize: 11.5, bold: true, color: C.navy, align: 'center' });
}

// 7 — Local membrane
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Layer 2', 'Net water transport is EO drag minus opposing diffusion');
  formula(slide, 'Nw = tw · j / F  −  Dw(aw) Sw(aw) · daw/dx', 1.00, 1.68, 11.30, 0.84, C.pale);
  roundRect(slide, 0.86, 2.90, 5.72, 2.10, C.paleTeal, C.paleTeal);
  pill(slide, 'Electro-osmotic term', 1.15, 3.18, 2.06, 'CBEFE8', C.teal);
  addText(slide, 'NEO = tw · j / F', 1.18, 3.70, 2.23, 0.42, { fontFace: 'Cambria Math', fontSize: 23, bold: true, color: C.navy });
  addText(slide, 'Ionic current carries additional water through the membrane.', 3.46, 3.50, 2.67, 0.84, { fontSize: 13, color: C.muted, valign: 'top' });
  roundRect(slide, 6.75, 2.90, 5.72, 2.10, C.paleBlue, C.paleBlue);
  pill(slide, 'Diffusive term', 7.04, 3.18, 1.58, 'D4E6F7', C.blue);
  addText(slide, 'Ndiff = −Dw Sw · daw/dx', 7.06, 3.70, 2.79, 0.42, { fontFace: 'Cambria Math', fontSize: 21, bold: true, color: C.navy });
  addText(slide, 'Activity gradients can oppose the desired EO direction.', 9.74, 3.50, 2.23, 0.84, { fontSize: 13, color: C.muted, valign: 'top' });
  arrow(slide, 5.94, 4.55, 7.03, 4.55, C.gray, 2.2, 'triangle');
  roundRect(slide, 0.86, 5.35, 11.61, 0.95, C.navy2, C.navy2);
  addText(slide, 'tw is an input in the current inverse-design model—not a predicted material property.', 1.18, 5.55, 7.45, 0.34, { fontSize: 16, bold: true, color: C.white });
  addText(slide, 'High tw values remain hypothetical until measured in vapor–membrane–vapor conditions.', 8.55, 5.46, 3.44, 0.53, { fontSize: 11.5, color: 'C9D8E0', align: 'right' });
  addText(slide, 'Practical gross EO flux:  JEO,gross ≈ 0.672 · tw · j  [g m⁻² h⁻¹]', 1.14, 6.48, 11.05, 0.30, { fontFace: 'Cambria Math', fontSize: 15, color: C.navy, align: 'center' });
}

// 8 — voltage/materials
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Layer 3', 'Voltage control couples transport to hydration-dependent resistance');
  formula(slide, 'dV/dx = j / σ(aw)  +  tw · RT/F · d ln(aw)/dx', 0.82, 1.65, 7.12, 0.78, C.pale);
  const comps = [
    ['Ohmic drop', 'Vohm = j · ASRmembrane', 'Thickness ↑ or conductivity ↓ → voltage ↑', C.blue],
    ['Water polarization', 'Vwater = tw · RT/F · ln(ar/as)', 'Higher tw also raises reversible water work', C.cyan],
    ['Series + fixed losses', 'j · ASRseries + Vfixed', 'Electrodes, contacts and electronics matter', C.orange]
  ];
  comps.forEach((c, i) => node(slide, 0.82 + i * 2.42, 2.75, 2.18, 2.02, c[0], c[1] + '\n\n' + c[2], c[3], C.white));
  roundRect(slide, 8.24, 1.65, 4.38, 4.75, C.navy2, C.navy2);
  addText(slide, 'MATERIAL VECTOR', 8.60, 1.96, 3.66, 0.28, { fontSize: 11, bold: true, color: C.cyan, align: 'center', charSpacing: 1.5 });
  addText(slide, '{ tw, D, S, σ, L, ASR }', 8.60, 2.46, 3.66, 0.48, { fontFace: 'Cambria Math', fontSize: 24, bold: true, color: C.white, align: 'center' });
  const props = [
    ['D(aw)', 'water diffusivity'],
    ['σ(aw)', 'ionic conductivity'],
    ['S(aw)', 'differential sorption capacity']
  ];
  props.forEach((p, i) => {
    roundRect(slide, 8.72, 3.20 + i * 0.73, 3.42, 0.54, '173C59', '173C59');
    addText(slide, p[0], 8.91, 3.29 + i * 0.73, 0.84, 0.28, { fontFace: 'Cambria Math', fontSize: 14, bold: true, color: C.cyan });
    addText(slide, p[1], 9.77, 3.29 + i * 0.73, 2.12, 0.28, { fontSize: 11, color: 'D6E4EA' });
  });
  addText(slide, 'Drying can reduce σ, increase resistance, lower current and raise the required voltage.', 8.78, 5.58, 3.30, 0.49, { fontSize: 12.5, bold: true, color: C.white, align: 'center' });
  addText(slide, 'At fixed terminal voltage, current density is solved—not freely selected.', 0.88, 5.50, 6.75, 0.72, { fontSize: 16, bold: true, color: C.navy, align: 'center' });
}

// 9 — films and segmentation
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Core integration', 'Gas films and changing air states make local solutions essential');
  addText(slide, 'PROCESS AIR', 0.80, 1.65, 1.50, 0.25, { fontSize: 10, bold: true, color: C.blue, charSpacing: 1.1 });
  arrow(slide, 0.82, 2.20, 12.15, 2.20, C.blue, 3.2);
  addText(slide, 'EXHAUST AIR', 0.80, 4.98, 1.50, 0.25, { fontSize: 10, bold: true, color: C.teal, charSpacing: 1.1 });
  arrow(slide, 12.15, 4.55, 0.82, 4.55, C.teal, 3.2);
  for (let i = 0; i < 8; i++) {
    const x = 1.15 + i * 1.39;
    roundRect(slide, x, 2.58, 1.10, 1.50, i === 5 ? C.paleTeal : C.white, i === 5 ? C.teal : C.line);
    addText(slide, `${i + 1}`, x + 0.35, 2.73, 0.40, 0.30, { fontSize: 13, bold: true, color: i === 5 ? C.teal : C.gray, align: 'center' });
    arrow(slide, x + 0.55, 3.12, x + 0.55, 3.69, C.cyan, 1.8);
    addText(slide, i === 5 ? 'local\nsolve' : 'T, w\nupdate', x + 0.17, 3.45, 0.76, 0.42, { fontSize: 9.5, bold: i === 5, color: i === 5 ? C.teal : C.muted, align: 'center', breakLine: true });
  }
  formula(slide, 'Nw = Ks(as,bulk − as,surface)', 0.82, 5.35, 3.52, 0.67, C.paleBlue);
  formula(slide, 'Ai = ṅw,i / Nw,i', 4.61, 5.35, 2.38, 0.67, C.pale);
  formula(slide, 'P EO = Σ Vi ji Ai', 7.25, 5.35, 2.38, 0.67, C.paleTeal);
  formula(slide, 'Nw = Kr(ar,surface − ar,bulk)', 9.89, 5.35, 2.43, 0.67, C.paleBlue);
  roundRect(slide, 0.82, 6.30, 11.50, 0.48, C.paleOrange, C.paleOrange);
  addText(slide, 'Illustrative boundary case: 16.80 mg/h gross Faraday rate → 12.37 mg/h net (73.6%) after films and back-diffusion.', 1.00, 6.38, 11.14, 0.27, { fontSize: 12, bold: true, color: C.navy, align: 'center' });
}

// 10 — cooling coil
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'HVAC linkage', 'Pre-drying can reduce condensate duty and improve compressor COP');
  const flow = [
    ['Active ERV outlet', 'Lower w before coil', C.cyan],
    ['Coil ADP solution', 'BF mixes inlet and ADP states', C.blue],
    ['Cooling load', 'ṁda(hin − hoff-coil)', C.blue],
    ['Variable COP', 'scaled Carnot relation', C.teal],
    ['Electrical power', 'Qcool / COP + reheat', C.navy]
  ];
  flow.forEach((f, i) => {
    node(slide, 0.68 + i * 2.52, 2.00, 2.10, 1.42, f[0], f[1], f[2], C.white);
    if (i < 4) arrow(slide, 2.80 + i * 2.52, 2.71, 3.12 + i * 2.52, 2.71, C.cyan, 2.4);
  });
  roundRect(slide, 0.68, 3.85, 5.86, 2.05, C.paleBlue, C.paleBlue);
  pill(slide, 'Coil equations', 0.98, 4.12, 1.50, 'D4E6F7', C.blue);
  addText(slide, 'woff = BF · win + (1 − BF) · wADP', 0.98, 4.58, 5.20, 0.34, { fontFace: 'Cambria Math', fontSize: 17, color: C.navy, align: 'center' });
  addText(slide, 'ṁcond = ṁda(win − woff)', 0.98, 5.03, 5.20, 0.34, { fontFace: 'Cambria Math', fontSize: 17, color: C.navy, align: 'center' });
  roundRect(slide, 6.80, 3.85, 5.85, 2.05, C.paleTeal, C.paleTeal);
  pill(slide, 'Double benefit', 7.10, 4.12, 1.50, 'CBEFE8', C.teal);
  check(slide, 7.17, 4.70, true);
  addText(slide, 'Less water must be condensed', 7.54, 4.65, 4.40, 0.34, { fontSize: 14, bold: true, color: C.navy });
  check(slide, 7.17, 5.24, true);
  addText(slide, 'Higher evaporating temperature may increase COP', 7.54, 5.17, 4.40, 0.48, { fontSize: 14, bold: true, color: C.navy });
  addText(slide, 'The coil remains necessary at O30.', 0.68, 6.38, 11.97, 0.34, { fontSize: 15, bold: true, color: C.red, align: 'center' });
}

// 11 — O30 moisture pathway
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Selected operating point', 'O30 is an intermediate humidity state—not the final supply condition');
  const y = 2.20;
  const states = [
    { x: 0.78, w: 3.00, v: '13.215', unit: 'g/kg dry air', h: 'Passive ERV outlet', c: C.blue },
    { x: 4.92, w: 3.00, v: '8.886', unit: 'g/kg dry air', h: 'O30 active ERV outlet', c: C.cyan },
    { x: 9.06, w: 3.00, v: '≈ 7.3', unit: 'g/kg dry air', h: 'Final target: 20°C / 50% RH*', c: C.teal }
  ];
  states.forEach((s, i) => {
    roundRect(slide, s.x, y, s.w, 2.05, C.white, C.line);
    slide.addShape(S.rect, { x: s.x, y, w: s.w, h: 0.10, fill: { color: s.c }, line: { color: s.c } });
    addText(slide, s.h, s.x + 0.20, y + 0.32, s.w - 0.40, 0.40, { fontSize: 13.5, bold: true, color: C.navy, align: 'center' });
    addText(slide, s.v, s.x + 0.20, y + 0.89, s.w - 0.40, 0.54, { fontSize: 32, bold: true, color: s.c, align: 'center' });
    addText(slide, s.unit, s.x + 0.20, y + 1.48, s.w - 0.40, 0.28, { fontSize: 11, color: C.muted, align: 'center' });
    if (i < 2) arrow(slide, s.x + s.w + 0.12, y + 1.03, s.x + s.w + 1.00, y + 1.03, C.cyan, 3.2);
  });
  addText(slide, 'ACTIVE ERV', 3.75, 2.80, 1.12, 0.26, { fontSize: 9.5, bold: true, color: C.cyan, align: 'center', charSpacing: 1.0 });
  addText(slide, 'COOLING COIL', 7.86, 2.80, 1.15, 0.26, { fontSize: 9.5, bold: true, color: C.blue, align: 'center', charSpacing: 1.0 });
  roundRect(slide, 0.78, 4.73, 11.28, 1.20, C.navy2, C.navy2);
  addText(slide, 'Interpretation', 1.03, 4.95, 1.35, 0.30, { fontSize: 13, bold: true, color: C.cyan });
  addText(slide, 'EO removes most of the remaining moisture after passive recovery; the coil still cools and dehumidifies to the final supply state.', 2.52, 4.88, 8.98, 0.48, { fontSize: 15, color: C.white });
  addText(slide, '*Approximate humidity ratio at 101.3 kPa; the model uses the exact psychrometric state.', 0.82, 6.26, 11.19, 0.26, { fontSize: 9.5, color: C.gray, italic: true });
}

// 12 — energy accounting
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Power accounting', 'Known power falls by 125.34 kW versus the same ERV with EO switched off');
  const data = [
    { name: 'AC only', value: 1166.400, color: C.orange },
    { name: 'Passive ERV + AC', value: 543.741, color: C.blue },
    { name: 'Active ERV + EO + AC', value: 418.400, color: C.teal }
  ];
  const baseX = 2.88, maxW = 8.62, scale = maxW / 1200;
  data.forEach((d, i) => {
    const yb = 1.92 + i * 1.18;
    addText(slide, d.name, 0.72, yb + 0.08, 1.95, 0.38, { fontSize: 13, bold: true, color: C.navy, align: 'right' });
    slide.addShape(S.roundRect, { x: baseX, y: yb, w: maxW, h: 0.58, fill: { color: C.lightGray }, line: { color: C.lightGray }, rectRadius: 0.07 });
    slide.addShape(S.roundRect, { x: baseX, y: yb, w: d.value * scale, h: 0.58, fill: { color: d.color }, line: { color: d.color }, rectRadius: 0.07 });
    addText(slide, `${d.value.toFixed(3)} kW`, baseX + d.value * scale + 0.12, yb + 0.10, 1.05, 0.34, { fontSize: 12, bold: true, color: d.color });
  });
  // scale
  for (let v = 0; v <= 1200; v += 200) {
    const xx = baseX + v * scale;
    slide.addShape(S.line, { x: xx, y: 5.34, w: 0, h: 0.12, line: { color: C.gray, width: 1 } });
    addText(slide, String(v), xx - 0.22, 5.48, 0.44, 0.22, { fontSize: 9, color: C.muted, align: 'center' });
  }
  addText(slide, 'Known electrical power [kW]', 6.03, 5.84, 2.42, 0.24, { fontSize: 10.5, bold: true, color: C.muted, align: 'center' });
  roundRect(slide, 0.72, 6.18, 5.52, 0.60, C.paleBlue, C.paleBlue);
  addText(slide, 'Passive recovery: −622.659 kW', 0.95, 6.30, 5.06, 0.30, { fontSize: 14, bold: true, color: C.blue, align: 'center' });
  roundRect(slide, 6.50, 6.18, 5.99, 0.60, C.paleTeal, C.paleTeal);
  addText(slide, 'Incremental EO window: −125.340 kW  |  −23.05%', 6.73, 6.30, 5.53, 0.30, { fontSize: 14, bold: true, color: C.teal, align: 'center' });
}

// 13 — O30 water and active power
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'O30 mass and power balance', 'Separate total core transport from the incremental EO duty');
  const total = 4365.9, passive = 3137.6, eo = 1228.3;
  const x = 0.82, y = 2.05, w = 7.15;
  addText(slide, 'Water transport through active ERV core', x, 1.70, w, 0.28, { fontSize: 13, bold: true, color: C.navy });
  slide.addShape(S.roundRect, { x, y, w, h: 0.76, fill: { color: C.lightGray }, line: { color: C.lightGray }, rectRadius: 0.08 });
  slide.addShape(S.roundRect, { x, y, w: w * passive / total, h: 0.76, fill: { color: C.blue }, line: { color: C.blue }, rectRadius: 0.08 });
  slide.addShape(S.rect, { x: x + w * passive / total - 0.08, y, w: w * eo / total + 0.08, h: 0.76, fill: { color: C.cyan }, line: { color: C.cyan } });
  addText(slide, 'Passive  3,137.6 kg/h', x + 0.18, y + 0.17, w * passive / total - 0.35, 0.34, { fontSize: 13, bold: true, color: C.white, align: 'center' });
  addText(slide, 'EO increment\n1,228.3 kg/h', x + w * passive / total, y + 0.05, w * eo / total, 0.60, { fontSize: 12.5, bold: true, color: C.navy, align: 'center', breakLine: true });
  addText(slide, 'Total = 4,365.9 kg/h', x, y + 0.93, w, 0.28, { fontSize: 12.5, bold: true, color: C.navy, align: 'center' });
  metric(slide, 0.82, 3.53, 2.22, '740', 'g m⁻² h⁻¹', 'Average total core flux', C.blue);
  metric(slide, 3.19, 3.53, 2.22, '208', 'g m⁻² h⁻¹', 'EO increment / area', C.cyan);
  metric(slide, 5.56, 3.53, 2.41, '200–250', 'g m⁻² h⁻¹', 'Coupon-test target range', C.teal);
  roundRect(slide, 8.33, 1.70, 4.14, 4.95, C.white, C.line);
  pill(slide, 'Known active-system split', 8.70, 2.02, 2.83, C.pale, C.navy);
  addText(slide, '316.910', 8.76, 2.60, 1.55, 0.46, { fontSize: 27, bold: true, color: C.blue, align: 'right' });
  addText(slide, 'kW', 10.38, 2.72, 0.43, 0.24, { fontSize: 11, bold: true, color: C.blue });
  addText(slide, 'remaining AC power', 10.92, 2.68, 1.13, 0.32, { fontSize: 11, color: C.muted });
  slide.addShape(S.line, { x: 8.78, y: 3.26, w: 3.30, h: 0, line: { color: C.line, width: 1 } });
  addText(slide, '≈101.490', 8.76, 3.52, 1.55, 0.46, { fontSize: 27, bold: true, color: C.cyan, align: 'right' });
  addText(slide, 'kW', 10.38, 3.64, 0.43, 0.24, { fontSize: 11, bold: true, color: C.cyan });
  addText(slide, 'included active-core and other contributions', 10.92, 3.43, 1.18, 0.66, { fontSize: 10.5, color: C.muted, valign: 'top' });
  slide.addShape(S.line, { x: 8.78, y: 4.27, w: 3.30, h: 0, line: { color: C.line, width: 1 } });
  addText(slide, '418.400 kW', 8.74, 4.55, 3.35, 0.54, { fontSize: 27, bold: true, color: C.teal, align: 'center' });
  addText(slide, 'known modeled total', 8.74, 5.13, 3.35, 0.28, { fontSize: 11.5, color: C.muted, align: 'center' });
  roundRect(slide, 8.74, 5.66, 3.35, 0.65, C.paleOrange, C.paleOrange);
  addText(slide, 'Unmodeled losses must fit within 125.34 kW.', 8.95, 5.76, 2.92, 0.38, { fontSize: 11.5, bold: true, color: C.navy, align: 'center' });
}

// 14 — frontier
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Selected result frontier', 'Deeper drying trades voltage, membrane area and system power');
  const pts = [
    { h: 12.000, p: 490.475, a: 6519, v: 0.10 },
    { h: 11.000, p: 446.484, a: 8669, v: 0.10 },
    { h: 10.000, p: 429.256, a: 7066, v: 0.50 },
    { h: 9.000, p: 422.938, a: 5758, v: 1.00 },
    { h: 8.886, p: 418.400, a: 5899, v: 1.00 }
  ];
  const px = 0.92, py = 1.87, pw = 7.12, ph = 3.82;
  // axes
  slide.addShape(S.line, { x: px, y: py, w: 0, h: ph, line: { color: C.gray, width: 1.2 } });
  slide.addShape(S.line, { x: px, y: py + ph, w: pw, h: 0, line: { color: C.gray, width: 1.2 } });
  const xmin = 8.5, xmax = 12.3, ymin = 410, ymax = 500;
  const mapX = h => px + (h - xmin) / (xmax - xmin) * pw;
  const mapY = p => py + ph - (p - ymin) / (ymax - ymin) * ph;
  for (let p = 420; p <= 500; p += 20) {
    const yy = mapY(p);
    slide.addShape(S.line, { x: px, y: yy, w: pw, h: 0, line: { color: C.line, width: 0.8, transparency: 25 } });
    addText(slide, String(p), px - 0.56, yy - 0.12, 0.43, 0.24, { fontSize: 9.5, color: C.muted, align: 'right' });
  }
  [9,10,11,12].forEach(h => addText(slide, h.toFixed(0), mapX(h) - 0.22, py + ph + 0.12, 0.44, 0.24, { fontSize: 9.5, color: C.muted, align: 'center' }));
  for (let i = 0; i < pts.length - 1; i++) {
    slide.addShape(S.line, { x: mapX(pts[i].h), y: mapY(pts[i].p), w: mapX(pts[i+1].h)-mapX(pts[i].h), h: mapY(pts[i+1].p)-mapY(pts[i].p), line: { color: C.cyan, width: 2.5 } });
  }
  pts.forEach((d, i) => {
    const xx = mapX(d.h), yy = mapY(d.p);
    slide.addShape(S.ellipse, { x: xx - 0.11, y: yy - 0.11, w: 0.22, h: 0.22, fill: { color: i === pts.length - 1 ? C.teal : C.cyan }, line: { color: C.white, width: 1.2 } });
    addText(slide, `${d.v.toFixed(2)} V\n${d.a.toLocaleString('en-US')} m²`, xx - 0.64, yy - (i === 0 ? -0.19 : 0.60), 1.28, 0.45, { fontSize: 8.5, bold: i === pts.length - 1, color: i === pts.length - 1 ? C.teal : C.muted, align: 'center', breakLine: true });
  });
  addText(slide, 'Active ERV outlet humidity ratio [g/kg dry air]', 2.55, 6.10, 4.70, 0.25, { fontSize: 10, bold: true, color: C.muted, align: 'center' });
  addText(slide, 'Known total power [kW]', 0.04, 3.24, 0.32, 1.32, { fontSize: 10, bold: true, color: C.muted, rotate: 270, align: 'center' });
  roundRect(slide, 8.40, 1.87, 4.15, 3.82, C.white, C.line);
  pill(slide, 'O30 selection', 8.76, 2.17, 1.58, C.paleTeal, C.teal);
  addText(slide, '8.886 g/kg', 8.76, 2.74, 3.36, 0.42, { fontSize: 25, bold: true, color: C.teal, align: 'center' });
  addText(slide, '1.00 V  •  5,899 m²  •  418.400 kW', 8.76, 3.27, 3.36, 0.38, { fontSize: 13, bold: true, color: C.navy, align: 'center' });
  addText(slide, 'The optimum is not simply the lowest voltage or smallest area. Higher voltage can reduce required area while increasing electrical stress and power.', 8.85, 3.86, 3.18, 1.05, { fontSize: 12.5, color: C.muted, align: 'center', valign: 'top' });
  roundRect(slide, 8.76, 5.03, 3.36, 0.40, C.paleOrange, C.paleOrange);
  addText(slide, 'Screening area cap: 9,000 m²', 8.93, 5.10, 3.02, 0.25, { fontSize: 11, bold: true, color: C.orange, align: 'center' });
  roundRect(slide, 0.92, 6.48, 11.63, 0.38, C.paleOrange, C.paleOrange);
  addText(slide, 'Full dehumidification required at least ≈17,253 m² in the valid screening—outside the selected area cap.', 1.10, 6.53, 11.27, 0.26, { fontSize: 11.5, bold: true, color: C.navy, align: 'center' });
}

// 15 — scope and claim boundary
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Model scope', 'A high-value screening model—not a validated commercial module');
  roundRect(slide, 0.72, 1.64, 5.87, 4.95, C.paleTeal, C.paleTeal);
  pill(slide, 'What the model is', 1.03, 1.95, 1.85, 'CBEFE8', C.teal);
  const yes = [
    'Physically based research model',
    '1D transport through membrane thickness',
    'Segmented counter-current ERV core',
    'Coupled water balance between air streams',
    'Voltage-controlled ionic transport',
    'Reduced but realistic coil / energy model',
    'Forward + inverse-design screening tool'
  ];
  yes.forEach((t, i) => { check(slide, 1.08, 2.56 + i * 0.49, true); addText(slide, t, 1.47, 2.51 + i * 0.49, 4.52, 0.32, { fontSize: 12.5, color: C.ink }); });
  roundRect(slide, 6.82, 1.64, 5.83, 4.95, C.paleOrange, C.paleOrange);
  pill(slide, 'What it is not', 7.13, 1.95, 1.70, 'FBE3C8', C.orange);
  const no = [
    'Full 2D / 3D CFD or conjugate PDE model',
    'Validated commercial ERV module',
    'Validated electrochemical electrode model',
    'Dynamic aging, fouling or durability model',
    'Proof that high tw is achievable in vapor',
    'Closed receiver / drainage / heat-rejection design',
    'CAPEX or lifecycle-cost model'
  ];
  no.forEach((t, i) => { check(slide, 7.18, 2.56 + i * 0.49, false); addText(slide, t, 7.57, 2.51 + i * 0.49, 4.48, 0.32, { fontSize: 12.5, color: C.ink }); });
  addText(slide, 'Use the model to define the experiment and the material target—not to skip them.', 0.72, 6.78, 11.93, 0.28, { fontSize: 14, bold: true, color: C.navy, align: 'center' });
}

// 16 — validation path
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Validation path', 'The next experiment must close transport, electrical and balance claims together');
  const gates = [
    ['1', 'Polarity-dependent net water flux', 'Demonstrate reversible directionality and quantify net flux.'],
    ['2', 'Effective tw in vapor', 'Derive from EO flux and current under representative RH.'],
    ['3', 'Conductivity / ASR at the same RH', 'Measure the electrical state that actually supports the flux.'],
    ['4', 'Passive back-diffusion', 'Run matched EO-off controls across the same activity gradient.'],
    ['5', 'Donor / receiver closure', 'Mass-balance both air streams; identify saturation or film limits.'],
    ['6', 'Stable operation at 1 V', 'Track current, heat, electrodes and performance over time.']
  ];
  gates.forEach((g, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.72 + col * 6.08, y = 1.70 + row * 1.52;
    roundRect(slide, x, y, 5.78, 1.20, C.white, C.line);
    slide.addShape(S.ellipse, { x: x + 0.22, y: y + 0.25, w: 0.66, h: 0.66, fill: { color: i < 2 ? C.cyan : i < 4 ? C.blue : C.teal }, line: { color: C.white, width: 1.5 } });
    addText(slide, g[0], x + 0.22, y + 0.25, 0.66, 0.64, { fontSize: 18, bold: true, color: C.white, align: 'center' });
    addText(slide, g[1], x + 1.07, y + 0.17, 4.40, 0.32, { fontSize: 14, bold: true, color: C.navy });
    addText(slide, g[2], x + 1.07, y + 0.53, 4.40, 0.46, { fontSize: 11.5, color: C.muted, valign: 'top' });
  });
  roundRect(slide, 0.72, 6.38, 11.86, 0.48, C.navy2, C.navy2);
  addText(slide, 'Success criterion: measured membrane + hardware performance preserves a positive margin inside the 125.34 kW conditional window.', 0.98, 6.45, 11.34, 0.29, { fontSize: 12.5, bold: true, color: C.white, align: 'center' });
}

// 17 — conclusion
{
  const slide = pptx.addSlide();
  slide.background = { color: C.navy };
  slide.addShape(S.rect, { x: 0, y: 0, w: 13.333, h: 0.11, fill: { color: C.cyan }, line: { color: C.cyan } });
  addText(slide, 'CONCLUSION', 0.74, 0.62, 2.10, 0.28, { fontSize: 11, bold: true, color: C.cyan, charSpacing: 1.6 });
  addText(slide, 'The model defines a credible target.\nThe experiment must decide whether it is real.', 0.74, 1.18, 8.00, 1.22, { fontSize: 31, bold: true, color: C.white, breakLine: true, valign: 'top' });
  const cards = [
    ['SYSTEM', '418.4 kW known modeled total at O30'],
    ['MARGIN', '125.34 kW conditional window vs. passive ERV + AC'],
    ['HARDWARE', '5,899 m² active membrane at 1 V'],
    ['MATERIAL', 'Inverse-design vector still requires vapor validation']
  ];
  cards.forEach((c, i) => {
    const x = 0.74 + (i % 2) * 4.25, y = 3.00 + Math.floor(i / 2) * 1.22;
    roundRect(slide, x, y, 3.86, 0.90, C.navy2, '24465F');
    addText(slide, c[0], x + 0.22, y + 0.15, 0.95, 0.23, { fontSize: 9, bold: true, color: C.cyan, charSpacing: 1.0 });
    addText(slide, c[1], x + 1.15, y + 0.12, 2.42, 0.56, { fontSize: 12.5, bold: true, color: C.white, valign: 'top' });
  });
  roundRect(slide, 9.18, 1.16, 3.40, 4.90, '102E47', '24465F');
  addText(slide, 'RECOMMENDED NEXT MOVE', 9.52, 1.55, 2.72, 0.34, { fontSize: 10.5, bold: true, color: C.cyan, align: 'center', charSpacing: 1.3 });
  addText(slide, 'Build the vapor coupon test around the incremental target:', 9.55, 2.20, 2.65, 0.62, { fontSize: 15, color: 'D7E4EA', align: 'center' });
  addText(slide, '200–250', 9.55, 3.02, 2.65, 0.58, { fontSize: 34, bold: true, color: C.white, align: 'center' });
  addText(slide, 'g m⁻² h⁻¹ net, polarity-dependent water transport', 9.55, 3.65, 2.65, 0.70, { fontSize: 13, bold: true, color: C.cyan, align: 'center' });
  addText(slide, 'paired with current, ASR, thermal and donor/receiver balance measurements.', 9.55, 4.63, 2.65, 0.82, { fontSize: 12, color: 'C6D7DF', align: 'center' });
  addText(slide, 'HeiQ / XMembrane  •  Coupled model synthesis  •  September 2026', 0.74, 6.92, 8.30, 0.20, { fontSize: 9, color: '8FA8B5' });
}

// 18 — Appendix equations
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Appendix A', 'Core equation map');
  const eqs = [
    ['Psychrometrics', 'h = 1.006T + w(2501 + 1.86T)\nṁw = ṁda(win − wout)'],
    ['Passive ERV', 'Tout = TOA − εs(TOA − Texh)\nwout = wOA − εl(wOA − wexh)'],
    ['Membrane flux', 'Nw = tw j/F − Dw(aw)Sw(aw) daw/dx'],
    ['Voltage', 'Vterminal = Vohm + Vwater + jASRseries + Vfixed'],
    ['Core integration', 'Atotal = Σ Ai\nPEO = Σ Vi ji Ai'],
    ['Cooling coil', 'Q̇cool = ṁda(hin − hoff)\nPcompressor = Q̇cool / COP']
  ];
  eqs.forEach((e, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.72 + col * 6.08, y = 1.68 + row * 1.57;
    roundRect(slide, x, y, 5.78, 1.22, C.white, C.line);
    pill(slide, e[0], x + 0.24, y + 0.18, 1.56, i < 2 ? C.paleBlue : i < 4 ? C.paleTeal : C.pale, i < 2 ? C.blue : i < 4 ? C.teal : C.navy);
    addText(slide, e[1], x + 1.97, y + 0.18, 3.50, 0.80, { fontFace: 'Cambria Math', fontSize: 15, color: C.navy, align: 'center', breakLine: true });
  });
  addText(slide, 'All balances are evaluated on a dry-air basis unless stated otherwise.', 0.72, 6.56, 11.84, 0.28, { fontSize: 11.5, italic: true, color: C.muted, align: 'center' });
}

// 19 — Appendix gross flux table
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Appendix B', 'Gross EO flux scales linearly with tw and current density');
  addText(slide, 'At j = 10 A/m², before back-diffusion and gas-film losses', 0.72, 1.48, 11.90, 0.30, { fontSize: 13, color: C.muted });
  const vals = [[10,67],[20,134],[30,202],[50,336],[75,504],[100,672]];
  const tx = 0.96, ty = 2.03, tw = 5.1, rowH = 0.58;
  slide.addShape(S.rect, { x: tx, y: ty, w: tw, h: rowH, fill: { color: C.navy2 }, line: { color: C.navy2 } });
  addText(slide, 'tw', tx + 0.20, ty + 0.12, 1.15, 0.28, { fontFace: 'Cambria Math', fontSize: 13, bold: true, color: C.white, align: 'center' });
  addText(slide, 'Gross EO flux [g m⁻² h⁻¹]', tx + 1.45, ty + 0.12, 3.33, 0.28, { fontSize: 12.5, bold: true, color: C.white, align: 'center' });
  vals.forEach((v, i) => {
    const yy = ty + rowH * (i + 1);
    slide.addShape(S.rect, { x: tx, y: yy, w: tw, h: rowH, fill: { color: i % 2 ? C.pale : C.white }, line: { color: C.line, width: 0.7 } });
    addText(slide, String(v[0]), tx + 0.20, yy + 0.12, 1.15, 0.28, { fontSize: 13, bold: true, color: C.navy, align: 'center' });
    addText(slide, String(v[1]), tx + 1.45, yy + 0.12, 3.33, 0.28, { fontSize: 13, color: C.navy, align: 'center' });
  });
  roundRect(slide, 6.56, 2.03, 5.70, 4.06, C.white, C.line);
  pill(slide, 'Interpretation', 6.90, 2.34, 1.56, C.paleTeal, C.teal);
  addText(slide, 'JEO,gross ≈ 0.672 · tw · j', 6.90, 3.02, 5.02, 0.48, { fontFace: 'Cambria Math', fontSize: 23, bold: true, color: C.navy, align: 'center' });
  addBullets(slide, [
    'Gross Faradaic transport is not the useful system flux.',
    'Back-diffusion and gas-film resistance reduce net transport.',
    'High tw also increases the water-polarization voltage term.',
    'The complete property vector—not a single number—sets feasibility.'
  ], 7.02, 3.75, 4.74, 1.75, { fontSize: 13, space: 8 });
  roundRect(slide, 6.90, 5.50, 5.02, 0.34, C.paleOrange, C.paleOrange);
  addText(slide, 'Treat high tw values as design coordinates until measured.', 7.07, 5.54, 4.68, 0.25, { fontSize: 11, bold: true, color: C.navy, align: 'center' });
}

// 20 — Appendix FAQ
{
  const slide = pptx.addSlide('MASTER');
  title(slide, 'Appendix C', 'Questions the audience is likely to ask');
  const qa = [
    ['Is tw measured for the selected membrane?', 'No. It is an inverse-design parameter until measured under relevant vapor conditions.'],
    ['Why not use liquid-cell values directly?', 'Hydration, morphology, conductivity and interfacial transport can differ radically between liquid and two gas streams.'],
    ['Why is not all gross EO flux useful?', 'Back-diffusion, activity gradients and gas films oppose or limit the desired transport.'],
    ['Why is the membrane area so large?', 'The air flow is ~150,000 CFM while local net flux is limited; compact ERVs use many thin parallel channels to create area.'],
    ['Is 23.05% a documented saving?', 'No. It is a reduction in the known modeled sum; all omitted losses must fit inside 125.34 kW.'],
    ['What would validate the concept?', 'Matched polarity tests, vapor tw, RH-resolved ASR, back-diffusion, mass balance, heat and stable 1 V operation.']
  ];
  qa.forEach((q, i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = 0.72 + col * 6.08, y = 1.62 + row * 1.64;
    roundRect(slide, x, y, 5.78, 1.34, C.white, C.line);
    addText(slide, q[0], x + 0.24, y + 0.16, 5.30, 0.35, { fontSize: 13.5, bold: true, color: C.navy });
    addText(slide, q[1], x + 0.24, y + 0.57, 5.30, 0.60, { fontSize: 11.5, color: C.muted, valign: 'top' });
  });
  addText(slide, 'Controlled references: docs/MODEL_CHAIN.md and the Final Result and Decision Report (v9, 31 Aug 2026).', 0.72, 6.72, 11.85, 0.24, { fontSize: 9.5, color: C.gray, align: 'center' });
}

pptx.writeFile({ fileName: 'deliverables/HeiQ_XMembrane_Coupled_Model_English_2026-09-02.pptx' });
