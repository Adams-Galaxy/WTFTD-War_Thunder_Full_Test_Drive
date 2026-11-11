/* WTFTD — Test bench: a guided test flown by the player in a mission WTFTD writes, the numbers read from the game by
   wtftd/bench.py. Everything here is labelled measured: the stat card only stands next to it. */
'use strict';

const BN = { runs: [], game: '', live: null, lastId: '', timer: 0, test: 'top', view: 'top', vehicle: '', only: '', form: {}, preset: '', fuel: 50, upg: true,
             sel: store.get('benchSel', {}), opened: new Set(), mouse: null, drawn: [] };
const BN_TESTS = ['top', 'climb', 'turn', 'accel', 'bleed', 'stall'], BN_HELI = ['top', 'climb', 'accel'];
const BN_FIELDS = { top: ['altitude'], climb: ['altitude', 'speed'], turn: ['altitude', 'speed'], accel: ['altitude', 'from', 'to'], bleed: ['altitude', 'speed'], stall: ['altitude'] };
const BN_AXES = { top: ['ov.v.alt', 'm', 'ov.v.tas', 'km/h'], climb: ['ov.v.alt', 'm', 'ov.v.vy', 'm/s'], turn: ['ov.v.ias', 'km/h', 'stat.turn', 's'] };
const BN_CHECKS = ['full', 'idle', 'gear', 'flaps', 'airbrake', 'wings', 'banked', 'level', 'climbing', 'steady'];
const BN_COLOURS = 5;  // runs laid over each other on a chart: one colour each, kept while the others come and go
const BN_HEIGHT = 300, BN_LEFT = 60, BN_RIGHT = 16, BN_TOP = 26, BN_BOTTOM = 34;
const BN_MAP = 'free_air_archipelago_air';  // 262 km of sea and islands, at sea level, nothing else on it

const bnKm = v => `${flNum(Math.round(v))} km/h`, bnM = v => `${flNum(Math.round(v))} m`;
const bnShare = f => ({ altitude: bnM(f.altitude), speed: bnKm(f.speed || 0), from: bnKm(f.from || 0), to: bnKm(f.to || 0) });
const bnTitle = (id, test, f) => t('bn.mission', { vehicle: I18N.unit(id), test: t('bn.t.' + test), alt: bnM(f.altitude) });
const bnRun = id => BN.runs.find(r => r.id === id);
const bnComparable = r => !r.custom && !r.cheats;

// the kind of aircraft a default depends on: propeller, jet, helicopter
const bnKind = v => (v.c === 'heli' ? 2 : v.s?.tw != null ? 1 : 0);
function bnDefaults(v, test) {
  const k = bnKind(v);
  return { top: { altitude: k === 2 ? 500 : v.s?.alt || 3000 }, climb: { altitude: [300, 500, 100][k], speed: [280, 500, 120][k] },
           turn: { altitude: 1000, speed: [350, 600, 150][k] }, accel: { altitude: [500, 1000, 200][k], from: [300, 500, 50][k], to: [500, 900, 200][k] },
           bleed: { altitude: 1000, speed: [450, 800, 150][k] }, stall: { altitude: 2000 } }[test];
}
// the speed the mission starts at, km/h. Near the top speed, so that the wait for it is short
function bnStartSpeed(v, test, f) {
  return { top: Math.round((v.s?.spd || airStartSpeed(v)) * .9), climb: f.speed, turn: f.speed, accel: Math.max(f.from - 30, 50), bleed: f.speed + 30,
           stall: airStartSpeed(v) }[test];
}

// ------------------------------------------------------------------ what a run measured
function bnBest(r, key, sign = 1) { return r.points.reduce((a, b) => (sign * b[key] > sign * a[key] ? b : a), r.points[0]); }

// the stat card's number for a run: stock or with all upgrades, as it was flown
function bnCard(r, key) {
  const v = S.byId.get(r.vehicle);
  return r.allMods ? v?.s?.[key] : v?.su?.[key] ?? v?.s?.[key];
}

function bnResult(r) {
  const p = r.points[0];
  if (!p) return '';
  if (r.test === 'top') { const b = bnBest(r, 'tas'); return `${bnKm(b.tas)} · ${bnM(b.alt)}${r.points.length > 1 ? ` · ${t('bn.points', { n: r.points.length })}` : ''}`; }
  if (r.test === 'climb') return `${flNum(p.vy)} m/s · ${bnM(p.from)} → ${bnM(p.to)} · ${flTime(p.s)}`;
  if (r.test === 'turn') { const b = bnBest(r, 's', -1); return `${flNum(b.s)} s · ${bnKm(b.ias)} · ${bnM(b.radius)} · ${flNum(b.g)} G${r.points.length > 1 ? ` · ${t('bn.points', { n: r.points.length })}` : ''}`; }
  if (r.test === 'accel') return `${flNum(p.s)} s · ${bnKm(p.from)} → ${bnKm(p.to)}`;
  if (r.test === 'bleed') return `−${bnKm(p.lost)} · ${bnKm(p.v0)} → ${bnKm(p.v1)} · ${flNum(p.s)} s · ${flNum(p.g)} G`;
  return bnKm(p.ias);
}

// the stat card next to a result: top speed at the card's altitude, climb, turn time, and how far the measure is from it
function bnCardCell(r) {
  if (r.test === 'top') {
    const spd = bnCard(r, 'spd'), alt = bnCard(r, 'alt'), near = r.points.filter(p => Math.abs(p.alt - alt) <= 500).sort((a, b) => Math.abs(a.alt - alt) - Math.abs(b.alt - alt))[0];
    return spd ? `${bnKm(spd)} · ${bnM(alt)}${near ? ` (${near.tas >= spd ? '+' : '−'}${flNum(Math.abs(Math.round(near.tas - spd)))})` : ''}` : '—';
  }
  const key = { climb: 'climb', turn: 'turn' }[r.test], card = key && bnCard(r, key);
  if (!card) return '—';
  const got = r.test === 'climb' ? r.points[0].vy : bnBest(r, 's', -1).s;
  return `${flNum(card)} ${r.test === 'climb' ? 'm/s' : 's'} (${got >= card ? '+' : '−'}${flNum(Math.abs(+(got - card).toFixed(1)))})`;
}

// the altitude flown, which the player may have changed from the one asked
function bnFlown(r) {
  const alts = r.points.map(p => p.alt ?? p.from).filter(x => x != null), lo = Math.min(...alts), hi = Math.max(...alts);
  return !alts.length ? '' : hi - lo < 100 ? bnM(lo) : `${bnM(lo)} – ${bnM(hi)}`;
}

function bnConditions(r) {
  const v = S.byId.get(r.vehicle);
  return [t('bn.cond.fuel', { n: flNum(r.fuel) }), presetLabel(v || { id: r.vehicle }, { id: r.preset || 'default', w: [] }), t(r.allMods ? 'upg.full' : 'upg.stock'), bnFlown(r), t('bn.cond.game', { v: r.game })].filter(Boolean).join(' · ');
}
// what must match for two runs to stand side by side: the aircraft and its loadout are what's being compared
const bnSameKey = r => [r.fuel, r.allMods, r.difficulty, /(^|_)default$/.test(r.preset) || !r.preset].join();

// one run as named figures, for the panel and Compare
function bnFigures(r) {
  if (!r.points.length) return [];
  const one = (key, label, value, text, better, order) => ({ key, label, value, text, better, order, run: r });
  if (r.test === 'top') return r.points.map(p => one(`top:${Math.round(p.alt / 500) * 500}`, t('bn.fig.top', { alt: bnM(Math.round(p.alt / 500) * 500) }), p.tas, bnKm(p.tas), 1, 1e-6 * p.alt));
  if (r.test === 'climb') return [one('climb', t('bn.fig.climb'), r.points[0].vy, `${flNum(r.points[0].vy)} m/s`, 1, 1)];
  if (r.test === 'turn') { const b = bnBest(r, 's', -1); return [one('turn', t('bn.fig.turn', { v: bnKm(b.ias) }), b.s, `${flNum(b.s)} s`, -1, 2)]; }
  if (r.test === 'accel') { const p = r.points[0]; return [one(`accel:${p.from}-${p.to}`, t('bn.fig.accel', { a: flNum(p.from), b: flNum(p.to) }), p.s, `${flNum(p.s)} s`, -1, 3)]; }
  if (r.test === 'bleed') { const p = r.points[0], at = Math.round(p.v0 / 50) * 50; return [one(`bleed:${at}`, t('bn.fig.bleed', { v: bnKm(at) }), p.lost, bnKm(p.lost), -1, 4)]; }
  return [one('stall', t('bn.t.stall'), r.points[0].ias, bnKm(r.points[0].ias), -1, 5)];
}

// the latest stock figure of each kind; game: only that version's. A custom vehicle or a run with cheats says nothing of the real one
function bnMeasured(id, game = '') {
  const out = new Map();
  for (const r of [...BN.runs].reverse()) {
    if (r.vehicle !== id || !bnComparable(r) || (game && r.game !== game)) continue;
    for (const x of bnFigures(r)) if (!out.has(x.key)) out.set(x.key, x);
  }
  return [...out.values()].sort((a, b) => a.order - b.order);
}

function bnPanelHTML(v) {
  if (!AIR.includes(v.c) || !S.status?.flight) return '';
  const rows = bnMeasured(v.id);
  return `<div class="lim"><div class="row-between lim-title"><span>${esc(t('bn.measured'))}</span><button class="btn btn-sm" data-act="bench">${esc(t('nav.bench'))}</button></div>
    ${rows.length ? `<div class="vstats">${rows.map(x => `<div class="vstat" title="${esc(bnConditions(x.run))}"><span>${esc(x.label)}</span><b>${esc(x.text)}</b></div>`).join('')}</div>` : ''}</div>`;
}

function bnCompareRows(list) {
  const figures = new Map(list.map(v => [v.id, new Map(bnMeasured(v.id, BN.game).map(x => [x.key, x]))]));
  const keys = new Map([...figures.values()].flatMap(m => [...m.values()]).sort((a, b) => a.order - b.order).map(x => [x.key, x]));
  return [...keys.values()].map(k => {
    const cells = list.map(v => figures.get(v.id).get(k.key)), have = cells.filter(Boolean);
    const same = new Set(have.map(x => bnSameKey(x.run))).size === 1;
    const best = same && have.length > 1 ? (k.better > 0 ? Math.max : Math.min)(...have.map(x => x.value)) : null;
    return `<tr><th>${esc(k.label)}<small>${esc(t('bn.measured'))}${same ? '' : ` · ${esc(t('bn.otherConditions'))}`}</small></th>${cells.map(x => (x
      ? `<td class="${x.value === best ? 'best' : ''}" title="${esc(bnConditions(x.run))}">${esc(x.text)}</td>` : '<td><span class="muted">—</span></td>')).join('')}</tr>`;
  }).join('');
}

// ------------------------------------------------------------------ the test to fly
function bnSetVehicle(id, test = BN.test) {
  const v = S.byId.get(id);
  BN.vehicle = v ? id : '';
  BN.test = v?.c === 'heli' && !BN_HELI.includes(test) ? 'top' : test;
  BN.form = v ? bnDefaults(v, BN.test) : {};
  BN.preset = '';
}

async function bnRenderForm() {
  const v = S.byId.get(BN.vehicle), tests = v?.c === 'heli' ? BN_HELI : BN_TESTS;
  $('#bnTests').innerHTML = BN_TESTS.map(k => `<button class="opt${k === BN.test ? ' active' : ''}${tests.includes(k) ? '' : ' disabled'}" data-bntest="${k}"${tests.includes(k) ? '' : ' disabled'}>
      <span class="opt-main"><span class="opt-title">${esc(t('bn.t.' + k))}</span><span class="opt-sub">${esc(t('bn.d.' + k))}</span></span><span class="opt-radio"></span></button>`).join('');
  $('#bnVehicle').value = v ? hgGoalName(v) : '';
  let d = null;
  try { d = v && await vehicleDetails(v.id); } catch (e) { toastErr(e); }
  const c = v && (S.cfgs.get(v.id) || (d && defaultCfg(v, d)));
  const altered = !!c && ((cdkOn() && (countMods(c.mods) > 0 || !!c.pylons)) || Object.values(c.cheats).some(Boolean));
  const presets = (d?.pr || []).map(p => `<option value="${esc(p.id)}"${p.id === (BN.preset || c?.preset) ? ' selected' : ''}>${esc(presetLabel(v, p))}</option>`).join('');
  const cap = d?.st?.fuel;
  $('#bnSetup').innerHTML = `<div class="field-row">
      <div class="field"><label for="bnPreset">${esc(t('step.loadout'))}</label><select id="bnPreset"${v && !c?.pylons ? '' : ' disabled'}>${presets}</select></div>
      <div class="field"><span class="bn-label">${esc(t('upg.label'))}</span><div class="seg bn-seg" id="bnUpg"><button class="${BN.upg ? '' : 'active'}" data-up="0">${esc(t('upg.stock'))}</button><button class="${BN.upg ? 'active' : ''}" data-up="1">${esc(t('upg.full'))}</button></div></div></div>
    <div class="field"><label for="bnFuel">${esc(t('cond.fuel'))}</label><div class="slider-row"><input type="range" id="bnFuel" min="5" max="100" step="5" value="${BN.fuel}"><output id="bnFuelText">${esc(bnFuelText(cap))}</output></div></div>
    <div class="field-row">${(BN_FIELDS[BN.test] || []).map(k => `<div class="field"><label for="bnF-${k}">${esc(t('bn.f.' + k))}</label><input type="number" id="bnF-${k}" data-bnf="${k}" min="0" max="40000" step="${k === 'altitude' ? 100 : 10}" value="${BN.form[k] ?? ''}"${v ? '' : ' disabled'}></div>`).join('')}</div>
    ${altered ? `<p class="hint bn-altered"><span class="chip warn">${esc(t('bn.notComparable'))}</span> ${esc(t('bn.alteredHint'))}</p>` : ''}`;
  $('#bnCreate').disabled = !v || !d;
}

const bnFuelText = cap => `${BN.fuel} %${cap ? ` · ~${flNum(Math.round(cap * BN.fuel / 100))} kg` : ''}`;

async function bnCreate(btn) {
  const v = S.byId.get(BN.vehicle);
  if (!v) return;
  const f = { ...BN.form }, wanted = BN_FIELDS[BN.test];
  if (wanted.some(k => !(+f[k] >= 0)) || (BN.test === 'accel' && +f.to <= +f.from)) return toast({ title: t('bn.badField'), err: true, ms: 4000 });
  btn.disabled = true;
  try {
    const d = await vehicleDetails(v.id), c = S.cfgs.get(v.id) || defaultCfg(v, d), block = d.b || blockFor(v.c), preset = BN.preset || c.preset;
    const custom = cdkOn() && (countMods(c.mods) > 0 || !!c.pylons), cheats = Object.values(c.cheats).some(Boolean);
    const scenario = S.scenarios.find(s => s.id === BN_MAP) || S.scenarios.find(s => s.free && s.kind === 'air' && s.id.startsWith('free_'));
    const title = bnTitle(v.id, BN.test, f), plan = { ...f, vehicle: v.id, test: BN.test, preset, fuel: BN.fuel, allMods: BN.upg, difficulty: 'realistic', custom, cheats };
    const r = await api('generate', {
      scenario: scenario?.id, vehicle: v.id, block, preset, ammo: ammoPayload({ ...c, block, vehicle: v.id }), environment: 'Noon', weather: 'clear', difficulty: 'realistic',
      start: 'air', altitude: +f.altitude, speed: bnStartSpeed(v, BN.test, f), heading: null, missionType: 'singleMission', allMods: BN.upg, fuel: BN.fuel,
      title, fileName: `wtftd_bench_${v.id}`, description: t('bn.do.' + BN.test, bnShare(f)),
      mods: cdkOn() ? modsPayload(c.mods) : undefined, pylons: cdkOn() && c.pylons ? c.pylons : undefined, cheats: { ...c.cheats }, bench: plan });
    toast({ title: t('toast.generated', { file: r.file }), sub: t('toast.generatedHint', { title }) + (r.cdkFiles?.length ? ' ' + t('toast.cdkHint', { n: r.cdkFiles.length }) : ''), ms: 12000,
            actions: [{ label: t('action.launch'), icon: 'play', primary: true, run: launchGame }, { label: t('action.openFolder'), icon: 'folder', run: () => api('open-folder', {}) }] });
    refreshMissions();
    bnPoll();
  } catch (e) { toastErr(e); }
  finally { btn.disabled = false; }
}

// ------------------------------------------------------------------ while the player flies
const bnChecks = list => list.map(c => `<span class="chip ${c.ok ? 'ok' : 'warn'}">${icon(c.ok ? 'check' : 'x', 'ic-sm')}${esc(t('bn.chk.' + c.key))}</span>`).join('');

function bnWhy(x) {
  return `<div class="bn-why"><b>${esc(flTime(x.t))}</b><span class="muted">${esc(t('bn.during', { s: flNum(x.s) }))}</span><span>${esc(BN_CHECKS.includes(x.why) ? t('bn.failed', { what: t('bn.chk.' + x.why) }) : x.why === 'paused' ? t('bn.paused') : t('bn.why.' + x.why, { v: x.v == null ? '' : flNum(x.v) }))}</span></div>`;
}

// what's kept of a flight, and why the rest wasn't
function bnFlightHTML(r, title) {
  const held = r.points?.length, list = r.rejected || [];
  return `<div class="row-between"><b>${esc(title)}</b>${held ? `<span class="chip ok">${icon('check', 'ic-sm')}${esc(bnResult(r))}</span>` : `<span class="chip warn">${icon('x', 'ic-sm')}${esc(t('bn.nothing'))}</span>`}</div>
    ${list.length ? `<details class="bn-refused"${held ? '' : ' open'}><summary>${esc(t('bn.refused', { n: list.length }))}</summary>${list.map(bnWhy).join('')}</details>` : ''}`;
}

function bnRenderLive() {
  const st = BN.live || {}, plan = st.plan, live = st.live, now = live?.now;
  $('#bnStop').classList.toggle('hidden', !plan);
  const show = (key, v) => (v == null ? '' : `<div class="vstat"><span>${esc(t(key))}</span><b>${esc(v)}</b></div>`);
  const done = st.last && st.last.vehicle ? bnFlightHTML(st.last, t('bn.lastFlight', { v: I18N.unit(st.last.vehicle) })) : '';
  if (!plan) { $('#bnLiveBody').innerHTML = `<p class="hint bn-idle">${esc(t('bn.idle'))}</p>${done}`; return; }
  const what = t('bn.do.' + plan.test, bnShare(plan));
  const state = st.recording ? (live?.paused ? t('bn.paused') : t('bn.recording')) : t('bn.waiting', { title: bnTitle(plan.vehicle, plan.test, plan) });
  const need = live?.need ? t('bn.held', { s: flNum(Math.min(live.held, live.need)), of: flNum(live.need) }) : live?.held ? t('bn.heldFor', { s: flNum(live.held) }) : '';
  $('#bnLiveBody').innerHTML = `<p class="bn-state"><span class="chip ${st.recording ? 'ok' : 'info'}">${esc(state)}</span>${need ? ` <span class="muted">${esc(need)}</span>` : ''}</p>
    <p class="hint">${esc(what)}</p>
    ${live ? `<div class="bn-checks">${bnChecks(live.checks)}</div>
      <div class="vstats">${show('ov.v.ias', now.ias != null && bnKm(now.ias))}${show('ov.v.alt', now.alt != null && bnM(now.alt))}${show('ov.v.vy', now.vy != null && `${flNum(now.vy)} m/s`)}${show('ov.v.throttle', now.throttle != null && `${flNum(now.throttle)} %`)}${show('ov.v.bank', now.bank != null && `${flNum(now.bank)}°`)}${show('ov.v.g', now.g != null && `${flNum(now.g)} G`)}</div>` : ''}
    ${st.found?.points?.length ? `<p class="bn-state"><span class="chip ok">${icon('check', 'ic-sm')}${esc(bnResult({ ...plan, points: st.found.points }))}</span></p>` : ''}
    ${st.recording ? '' : done}`;
}

async function bnPoll() {
  clearTimeout(BN.timer);
  if ($('#view-bench').classList.contains('hidden')) return;
  try {
    BN.live = await api('bench-live');
    const id = BN.live.last?.id;
    if (id && id !== BN.lastId) {
      BN.lastId = id;
      await bnLoad();
      if (bnRun(id)) { BN.view = BN.live.last.test; bnPick(bnRun(id), true); }
      bnRenderResults();
    }
    bnRenderLive();
  } catch { /* the app is closing */ }
  BN.timer = setTimeout(bnPoll, 1000);
}

// ------------------------------------------------------------------ results
const bnSeries = r => (r.test === 'top' ? r.points.map(p => [p.alt, p.tas]) : r.test === 'climb' ? (r.points[0]?.curve || []).map(c => [c[0], c[1]]) : r.test === 'turn' ? r.points.map(p => [p.ias, p.s]) : [])
  .sort((a, b) => a[0] - b[0]);
const bnListed = () => BN.runs.filter(r => r.test === BN.view && (!BN.only || r.vehicle === BN.only)).reverse();
const bnSlots = test => (BN.sel[test] ||= []);
const bnSlot = r => bnSlots(r.test).indexOf(r.id);

function bnPick(r, on) {
  const slots = bnSlots(r.test), at = bnSlot(r);
  if (!on) { if (at >= 0) slots[at] = null; }
  else if (at < 0) {
    const free = slots.indexOf(null), slot = free >= 0 ? free : slots.length;
    if (slot >= BN_COLOURS) return toast({ title: t('compare.max', { n: BN_COLOURS }), err: true, ms: 3500 });
    slots[slot] = r.id;
  }
  store.set('benchSel', BN.sel);
}

const bnColour = slot => getComputedStyle(document.documentElement).getPropertyValue(`--bench-${slot + 1}`).trim();
const bnDrawn = () => bnListed().filter(r => bnSlot(r) >= 0 && bnSeries(r).length);

// round numbers for an axis
function bnTicks(lo, hi, count = 5) {
  const raw = (hi - lo) / count || 1, mag = 10 ** Math.floor(Math.log10(raw)), step = [1, 2, 5, 10].find(x => x * mag >= raw) * mag;
  const out = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6));
  return out;
}

function bnDraw() {
  const cv = $('#bnCanvas'), axes = BN_AXES[BN.view], runs = axes ? bnDrawn() : [];
  $('#bnChart').classList.toggle('hidden', !axes || !bnListed().length);
  $('#bnNoCurve').classList.toggle('hidden', !axes || runs.length > 0);
  cv.classList.toggle('hidden', !runs.length);
  BN.drawn = [];
  if (!runs.length) return;
  const css = getComputedStyle(document.documentElement), tok = n => css.getPropertyValue(n).trim();
  const W = cv.clientWidth, dpr = devicePixelRatio || 1;
  cv.style.height = `${BN_HEIGHT}px`;
  cv.width = W * dpr;
  cv.height = BN_HEIGHT * dpr;
  const c = cv.getContext('2d');
  c.scale(dpr, dpr);
  const series = runs.map(r => ({ r, pts: bnSeries(r), slot: bnSlot(r) }));
  // the stat card: a level line, or for top speed the one point it gives
  const refs = runs.flatMap(r => {
    const slot = bnSlot(r);
    if (r.test === 'top') return bnCard(r, 'spd') && bnCard(r, 'alt') ? [{ slot, at: [bnCard(r, 'alt'), bnCard(r, 'spd')] }] : [];
    const y = bnCard(r, r.test === 'climb' ? 'climb' : 'turn');
    return y ? [{ slot, y }] : [];
  });
  const xs = [...series.flatMap(s => s.pts.map(p => p[0])), ...refs.filter(x => x.at).map(x => x.at[0])];
  const ys = [...series.flatMap(s => s.pts.map(p => p[1])), ...refs.map(x => x.y ?? x.at[1])];
  let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const padX = (x1 - x0 || Math.abs(x1) || 1) * .06, padY = (y1 - y0 || Math.abs(y1) || 1) * .1;
  x0 -= padX; x1 += padX; y0 -= padY; y1 += padY;
  const px = v => BN_LEFT + (v - x0) / (x1 - x0) * (W - BN_LEFT - BN_RIGHT), py = v => BN_TOP + (y1 - v) / (y1 - y0) * (BN_HEIGHT - BN_TOP - BN_BOTTOM);
  const base = BN_HEIGHT - BN_BOTTOM;
  c.font = `12px ${tok('--font')}`;
  c.fillStyle = tok('--text-2');
  c.textBaseline = 'middle';
  c.textAlign = 'left';
  c.fillText(`${t(axes[2])} (${axes[3]})`, 12, 12);
  c.textAlign = 'right';
  c.fillText(`${t(axes[0])} (${axes[1]})`, W - BN_RIGHT, BN_HEIGHT - 8);
  c.font = `10.5px ${tok('--font')}`;
  c.lineWidth = 1;
  for (const v of bnTicks(y0, y1)) {
    c.strokeStyle = tok('--line');
    c.beginPath();
    c.moveTo(BN_LEFT, Math.round(py(v)) + .5);
    c.lineTo(W - BN_RIGHT, Math.round(py(v)) + .5);
    c.stroke();
    c.fillStyle = tok('--muted');
    c.textAlign = 'right';
    c.fillText(flNum(v), BN_LEFT - 8, py(v));
  }
  c.textAlign = 'center';
  for (const v of bnTicks(x0, x1, Math.max(3, Math.floor((W - BN_LEFT) / 90)))) c.fillText(flNum(v), px(v), base + 12);
  for (const ref of refs) {  // dashed: not a measure
    c.strokeStyle = c.fillStyle = bnColour(ref.slot);
    c.lineWidth = 1.5;
    c.setLineDash([5, 4]);
    if (ref.at) {
      c.save();
      c.translate(px(ref.at[0]), py(ref.at[1]));
      c.rotate(Math.PI / 4);
      c.setLineDash([]);
      c.strokeRect(-4.5, -4.5, 9, 9);
      c.restore();
    } else {
      c.beginPath();
      c.moveTo(BN_LEFT, py(ref.y));
      c.lineTo(W - BN_RIGHT, py(ref.y));
      c.stroke();
    }
  }
  for (const s of series) {
    const colour = bnColour(s.slot);
    c.strokeStyle = colour;
    c.lineWidth = 2;
    c.lineJoin = 'round';
    c.setLineDash(bnComparable(s.r) ? [] : [2, 4]);  // a custom vehicle or cheats: not the real aircraft
    c.beginPath();
    s.pts.forEach((p, i) => (i ? c.lineTo(px(p[0]), py(p[1])) : c.moveTo(px(p[0]), py(p[1]))));
    c.stroke();
    c.setLineDash([]);
    for (const p of s.pts) {
      c.beginPath();
      c.arc(px(p[0]), py(p[1]), 4, 0, Math.PI * 2);
      c.fillStyle = colour;
      c.strokeStyle = tok('--surface');
      c.lineWidth = 2;
      c.fill();
      c.stroke();
      BN.drawn.push({ x: px(p[0]), y: py(p[1]), s, p });
    }
  }
  const near = BN.mouse && BN.drawn.reduce((a, b) => (Math.hypot(b.x - BN.mouse[0], b.y - BN.mouse[1]) < Math.hypot(a.x - BN.mouse[0], a.y - BN.mouse[1]) ? b : a));
  if (near && Math.hypot(near.x - BN.mouse[0], near.y - BN.mouse[1]) < 40) {
    c.beginPath();
    c.arc(near.x, near.y, 6, 0, Math.PI * 2);
    c.strokeStyle = tok('--text');
    c.lineWidth = 2;
    c.stroke();
    c.font = `12px ${tok('--font')}`;
    const text = `${I18N.unit(near.s.r.vehicle)} · ${flNum(near.p[0])} ${axes[1]} · ${flNum(near.p[1])} ${axes[3]}`, w = c.measureText(text).width + 16;
    const left = Math.max(BN_LEFT, Math.min(near.x - w / 2, W - BN_RIGHT - w)), top = near.y > BN_TOP + 34 ? near.y - 34 : near.y + 14;
    c.fillStyle = tok('--surface-3');
    c.fillRect(left, top, w, 22);
    c.fillStyle = tok('--text');
    c.textAlign = 'left';
    c.fillText(text, left + 8, top + 11);
  }
}

function bnRenderResults() {
  const list = bnListed(), axes = BN_AXES[BN.view];
  if (list[0] && !BN.opened.has(BN.view) && !list.some(r => bnSlot(r) >= 0)) bnPick(list[0], true);  // a first look shows the latest run
  BN.opened.add(BN.view);
  const drawn = bnDrawn();
  $$('#bnView button').forEach(b => b.classList.toggle('active', b.dataset.v === BN.view));
  const flown = [...new Set(BN.runs.filter(r => r.test === BN.view).map(r => r.vehicle))];
  $('#bnOnly').innerHTML = `<option value="">${esc(t('bn.allAircraft'))}</option>${flown.map(id => `<option value="${esc(id)}"${id === BN.only ? ' selected' : ''}>${esc(I18N.unit(id))}</option>`).join('')}`;
  $('#bnLegend').innerHTML = axes && drawn.length ? `${drawn.map(r => `<span class="bn-key" style="--c:${bnColour(bnSlot(r))}"><i></i>${esc(I18N.unit(r.vehicle))}<span class="muted">${esc(bnConditions(r))}</span>${bnComparable(r) ? '' : `<span class="chip warn">${esc(t('bn.notComparable'))}</span>`}</span>`).join('')}
    <span class="bn-key bn-card muted"><i></i>${esc(t('bn.cardKey'))}</span>` : '';
  $('#bnTable').innerHTML = list.length ? `<div class="ar-scroll"><table class="ar-table bn-table"><thead><tr>${axes ? `<th class="bn-tick"><span class="bn-hide">${esc(t('bn.overlay'))}</span></th>` : ''}<th>${esc(t('mb.vehicle'))}</th><th>${esc(t('bn.measured'))}</th><th>${esc(t('bn.card'))}</th><th>${esc(t('bn.conditions'))}</th><th>${esc(t('bn.date'))}</th><th></th></tr></thead>
    <tbody>${list.map(r => `<tr>${axes ? `<td class="bn-tick"><label class="bn-pick"><input type="checkbox" data-bnsel="${esc(r.id)}"${bnSlot(r) >= 0 ? ' checked' : ''} aria-label="${esc(t('bn.overlay'))}"></label></td>` : ''}
      <td>${mbVehicle(r.vehicle, unitImgTag(r.vehicle))}</td><td>${esc(bnResult(r))}</td><td>${esc(bnCardCell(r))}</td>
      <td class="bn-cond">${esc(bnConditions(r))}${r.custom ? ` <span class="chip warn">${esc(t('bn.custom'))}</span>` : ''}${r.cheats ? ` <span class="chip warn">${esc(t('step.cheats'))}</span>` : ''}</td>
      <td>${esc(mbDate(r.time))}</td><td class="hg-actions">${r.log ? `<button class="btn btn-sm" data-bnlog="${esc(r.log)}">${esc(t('nav.flight'))}</button>` : ''}
        <button class="icon-btn btn-danger" data-bndel="${esc(r.id)}" title="${esc(t('action.delete'))}">${icon('trash', 'ic-sm')}</button></td></tr>`).join('')}</tbody></table></div>`
    : `<div class="empty bn-empty">${icon('target', 'ic-xl')}<p>${esc(t('bn.empty'))}</p></div>`;
  bnDraw();
}

async function bnLoad() {
  const data = await api('bench');
  BN.runs = data.runs;
  BN.game = data.game;
  for (const test of Object.keys(BN.sel)) BN.sel[test] = Array.isArray(BN.sel[test]) ? BN.sel[test].map(id => (bnRun(id) ? id : null)) : [];
  if (data.damaged) toast({ title: t('bn.damaged'), err: true, ms: 8000 });
}

async function openBenchView() {
  $('#bnVehicles').innerHTML = S.vehicles.filter(v => AIR.includes(v.c)).map(v => `<option value="${esc(hgGoalName(v))}"></option>`).join('');
  await bnRenderForm();
  try { await bnLoad(); } catch (e) { toastErr(e); }
  bnRenderResults();
  bnPoll();
}

function bnFrom(v) {
  closeDrawer();
  bnSetVehicle(v.id);
  showView('bench');
}

function bindBench() {
  $('[data-view="bench"]').classList.toggle('hidden', !S.status?.flight);  // same reader as Flight data: Windows and Linux
  bnLoad().then(() => { if (S.sel) renderDrawer(); }).catch(() => {});
  $('#bnView').innerHTML = BN_TESTS.map(k => `<button data-v="${k}">${esc(t('bn.t.' + k))}</button>`).join('');
  $('#bnView').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    BN.view = b.dataset.v;
    bnRenderResults();
  });
  $('#bnOnly').addEventListener('change', e => { BN.only = e.target.value; bnRenderResults(); });
  $('#bnTests').addEventListener('click', e => {
    const b = e.target.closest('[data-bntest]');
    if (!b || b.disabled) return;
    bnSetVehicle(BN.vehicle, b.dataset.bntest);
    BN.test = b.dataset.bntest;
    BN.view = BN.test;
    bnRenderForm();
    bnRenderResults();
  });
  $('#bnVehicle').addEventListener('change', e => {
    const v = S.vehicles.find(x => AIR.includes(x.c) && hgGoalName(x) === e.target.value);
    if (v) { bnSetVehicle(v.id); bnRenderForm(); }
  });
  const setup = $('#bnSetup');
  setup.addEventListener('input', e => {
    if (e.target.id === 'bnFuel') { BN.fuel = +e.target.value; $('#bnFuelText').textContent = bnFuelText(S.details.get(BN.vehicle)?.st?.fuel); }
    else if (e.target.dataset.bnf) BN.form[e.target.dataset.bnf] = +e.target.value;
  });
  setup.addEventListener('change', e => { if (e.target.id === 'bnPreset') BN.preset = e.target.value; });
  setup.addEventListener('click', e => {
    const b = e.target.closest('[data-up]');
    if (!b) return;
    BN.upg = b.dataset.up === '1';
    $$('#bnUpg button').forEach(x => x.classList.toggle('active', x === b));
  });
  $('#bnCreate').addEventListener('click', e => bnCreate(e.currentTarget));
  $('#bnStop').addEventListener('click', async () => {
    try { await api('bench-stop', {}); } catch (e) { toastErr(e); }
    bnPoll();
  });
  $('#bnTable').addEventListener('click', async e => {
    mbFollow(e);
    const log = e.target.closest('[data-bnlog]')?.dataset.bnlog, del = e.target.closest('[data-bndel]')?.dataset.bndel;
    if (log) flOpenLog(log);
    if (del) {
      try {
        const gone = bnRun(del);
        BN.runs = (await api('bench-delete', { id: del })).runs;
        bnPick(gone, false);
      } catch (err) { return toastErr(err); }
      bnRenderResults();
    }
  });
  $('#bnTable').addEventListener('change', e => {
    const id = e.target.dataset.bnsel;
    if (!id) return;
    bnPick(bnRun(id), e.target.checked);
    bnRenderResults();
  });
  const cv = $('#bnCanvas');
  cv.addEventListener('mousemove', e => { BN.mouse = [e.offsetX, e.offsetY]; bnDraw(); });
  cv.addEventListener('mouseleave', () => { BN.mouse = null; bnDraw(); });
  addEventListener('resize', () => { if (!$('#view-bench').classList.contains('hidden')) bnDraw(); });
}
