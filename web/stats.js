/* WTFTD — vehicle stats: shown on the vehicle card, sortable, filterable (min / max), plus search by
   carried weapon / ammunition. Data: vehicles.json  v.s = {stat: value}, v.wp = [weapon & ammo keys]. */
'use strict';

const AIR = ['air', 'heli'], NAVAL = ['boat', 'ship'], ALL_CATS = ['ground', 'air', 'heli', 'boat', 'ship'];
// better: 1 = higher is better (sorted descending), -1 = lower is better, 0 = neutral
// mode: one value per game mode, the one of the AB / RB / SB control counts. eco: in the panel's Economy block
const STATS = {
  spd: { cats: ALL_CATS, unit: 'km/h', better: 1 },
  rev: { cats: ['ground'], unit: 'km/h', better: 1 },
  pw: { cats: ['ground', 'air'], unit: 'hp/t', better: 1 },
  hp: { cats: ['ground', ...NAVAL], unit: 'hp', better: 1 },
  t: { cats: ['ground'], unit: 't', better: 0 },
  armT: { cats: ['ground'], unit: 'mm', better: 1, triple: true },
  armH: { cats: ['ground'], unit: 'mm', better: 1, triple: true },
  trav: { cats: ['ground'], unit: '°/s', better: 1 },
  vert: { cats: ['ground'], unit: '°/s', better: 1 },
  cal: { cats: ['ground', ...NAVAL], unit: 'mm', better: 1 },
  kin: { cats: ['ground'], unit: 'mm', better: 1 },
  heat: { cats: ['ground'], unit: 'mm', better: 1 },
  rel: { cats: ['ground'], unit: 's', better: -1, digits: 1 },
  turn: { cats: AIR, unit: 's', better: -1, digits: 1 },
  roll: { cats: ['air'], unit: '°/s', better: 1 },
  climb: { cats: AIR, unit: 'm/s', better: 1, digits: 1 },
  alt: { cats: AIR, unit: 'm', better: 0 },
  ceil: { cats: AIR, unit: 'm', better: 1 },
  tw: { cats: AIR, unit: '', better: 1, digits: 2 },
  wl: { cats: ['air'], unit: 'kg/m²', better: -1 },
  disp: { cats: NAVAL, unit: 't', better: 0 },
  crew: { cats: ALL_CATS, unit: '', better: 0 },
  rp: { cats: ALL_CATS, unit: 'RP', better: -1, eco: true },
  sl: { cats: ALL_CATS, unit: 'SL', better: -1, eco: true },
  rep: { cats: ALL_CATS, unit: 'SL', better: -1, eco: true, mode: true },
  slm: { cats: ALL_CATS, unit: '%', better: 1, eco: true, mode: true },
  rpm: { cats: ALL_CATS, unit: '%', better: 1, eco: true },
  fr: { cats: ALL_CATS, unit: '', better: 1, eco: true },
};
const MODES = ['ab', 'rb', 'sb'];

// aircraft: propeller planes have a power-to-weight ratio, jets a thrust-to-weight ratio (not comparable)
const statLabel = (k, cat) => t(cat === 'air' && k === 'pw' ? 'stat.pwProp' : cat === 'air' && k === 'tw' ? 'stat.twJet' : 'stat.' + k)
  + (STATS[k].mode ? ` · ${t('filters.mode.' + MODES[S.f.brMode])}` : '');
const statKeys = cat => Object.keys(STATS).filter(k => (cat === 'all' ? ['spd', 'crew'].includes(k) || STATS[k].eco : STATS[k].cats.includes(cat)));
// Stats shown stock (false) or with all modules researched (true). v.s = fully upgraded, v.su = stock values
S.upg = store.get('upg', 1) !== 0;
function statAt(v, k) {
  const pick = x => (STATS[k].mode && Array.isArray(x) ? x[S.f.brMode] : x);
  const x = pick(v.s?.[k]);
  if (Array.isArray(x)) return x;
  if (typeof x !== 'number') return null;
  const su = pick(v.su?.[k]);
  return !S.upg && typeof su === 'number' ? su : x;
}
// one comparable number per stat (armor: the front plate)
const statVal = (v, k) => { const x = statAt(v, k); return Array.isArray(x) ? x[0] : x; };

function upgSwitchHTML(estimated) {
  return `<div class="upg" title="${esc(estimated ? t('upg.estimated') : '')}">
    <div class="seg seg-sm" role="group" aria-label="${esc(t('upg.label'))}">
      <button type="button" class="${S.upg ? '' : 'active'}" data-upgset="0">${esc(t('upg.stock'))}</button>
      <button type="button" class="${S.upg ? 'active' : ''}" data-upgset="1">${esc(t('upg.full'))}</button>
    </div>
  </div>`;
}

function setUpgrade(on) {
  if (S.upg === on) return;
  S.upg = on;
  store.set('upg', on ? 1 : 0);
  if (S.sel && $('#vstatsWrap')) $('#vstatsWrap').outerHTML = statsBlockHTML(S.sel);
  if ($('#dlgCompare')?.open) renderCompareTable();
  if (S.f.sort?.startsWith('s:') || Object.keys(S.f.stats || {}).length) applyFilters();
}
document.addEventListener('click', e => { const b = e.target.closest('[data-upgset]'); if (b) setUpgrade(b.dataset.upgset === '1'); });

function fmtStat(k, x) {
  if (x == null) return '—';
  if (k === 'rep' && x === 0) return t('eco.free');
  const d = STATS[k];
  const n = val => I18N.num(+(+val).toFixed(d.digits ?? 0));
  const txt = Array.isArray(x) ? x.map(n).join(' / ') : n(x);
  return d.unit ? `${txt} ${d.unit}` : txt;
}

// ------------------------------------------------------------------ filters
function statsMatch(v) {
  const f = S.f.stats || {};
  for (const [k, [lo, hi]] of Object.entries(f)) {
    if (lo == null && hi == null) continue;
    if (!STATS[k] || !STATS[k].cats.includes(v.c)) continue;  // stat of another vehicle type: ignore
    const x = statVal(v, k);
    if (x == null || (lo != null && x < lo) || (hi != null && x > hi)) return false;
  }
  return true;
}

// ------------------------------------------------------------------ weapon picker
// S.f.wsel = ["<weapon / ammo key>" | "T:<ammo type>"]: the vehicle must carry all of them.
const WP = { arsenal: null, cat: '', q: '' };
const WP_CATS = ['aam_ir', 'aam_radar', 'agm', 'atgm', 'rockets', 'bombs', 'guided_bombs', 'nuke', 'torpedoes', 'mines', 'pods', 'fuel', 'gun', 'ammo'];

function ammoType(tp) {
  const x = (tp || '').toLowerCase();
  for (const [re, lab] of [[/^atgm/, 'ATGM'], [/^sam/, 'SAM'], [/^apds_fs/, 'APFSDS'], [/^apds/, 'APDS'], [/^apcr/, 'APCR'],
    [/^heat_fs/, 'HEATFS'], [/^heat/, 'HEAT'], [/^hesh/, 'HESH'], [/^aphe/, 'APHE'], [/^apcbc/, 'APCBC'], [/^sap/, 'SAP'],
    [/^ap/, 'AP'], [/^smoke/, 'Smoke'], [/^shrapnel/, 'Shrapnel'], [/^(he|frag)/, 'HE'], [/^rocket/, 'Rocket']]) if (re.test(x)) return lab;
  return x.split('_')[0].toUpperCase();
}

const NOT_WEAPON = /countermeasure|flare|chaff/i, NOT_TYPES = new Set(['FLR', 'CHFF']);
const carried = v => (v._carry ||= new Set([...(v.wg || []), ...(v.wp || []), ...(v.wa || [])].filter(k => !NOT_WEAPON.test(k))));
function ammoTypes(v) {
  if (!v._types) v._types = new Set((v.wa || []).map(k => WP.arsenal?.[k]?.t).filter(Boolean).map(ammoType).filter(x => !NOT_TYPES.has(x)));
  return v._types;
}
const wpName = k => k.startsWith('T:') ? t('wpick.anyType', { type: k.slice(2) }) : (WP.arsenal?.[k]?.c === 'ammo' ? I18N.bullet(k) : I18N.weapon(k));
// several game files can hold the same weapon (variants, containers): one entry per displayed name
const carriedNames = v => (v._names ||= new Set([...carried(v)].map(wpName)));

function weaponMatch(v) {
  const sel = S.f.wsel || [];
  if (!sel.length) return true;
  return sel.every(k => k.startsWith('T:') ? ammoTypes(v).has(k.slice(2)) : carriedNames(v).has(wpName(k)));
}

function wpIcon(k) {
  const a = WP.arsenal?.[k];
  if (k.startsWith('T:')) return `<span class="wp-badge">${esc(k.slice(2))}</span>`;
  if (a?.ic) return ammoIcon(a.ic);
  if (a?.c === 'gun') return `<span class="wp-badge gun">${a.cal ? esc(Math.round(a.cal)) + '<i>mm</i>' : icon('ammo', 'ic-sm')}</span>`;
  if (a?.c === 'ammo') return `<span class="wp-badge">${esc(ammoType(a.t))}</span>`;
  return '<span class="wicon-ph"></span>';
}

async function openWeaponPicker() {
  if (!WP.arsenal) {
    try { WP.arsenal = await getData('arsenal.json'); } catch { WP.arsenal = {}; }
    for (const v of S.vehicles) delete v._types;
  }
  WP.q = '';
  $('#wpSearch').value = '';
  renderWeaponPicker();
  $('#dlgWeapons').showModal();
  $('#wpSearch').focus();
}

function renderWeaponPicker() {
  const sel = new Set(S.f.wsel || []);
  // what the vehicles of the current type carry, and how many of them
  const byName = new Map(), types = new Map();  // name -> {k: representative key, n: vehicles}
  for (const v of S.vehicles) {
    if ((v.h && !S.f.hidden) || (S.f.cat !== 'all' && v.c !== S.f.cat)) continue;
    const seen = new Set();
    for (const k of carried(v)) {
      const name = wpName(k);
      let e = byName.get(name);
      if (!e) byName.set(name, e = { k, n: 0 });
      else if (!WP.arsenal[e.k]?.ic && WP.arsenal[k]?.ic) e.k = k;  // prefer a key with a game icon
      if (!seen.has(name)) { seen.add(name); e.n++; }
    }
    for (const tp of ammoTypes(v)) types.set(tp, (types.get(tp) || 0) + 1);
  }
  const counts = new Map([...byName.values()].map(e => [e.k, e.n]));
  const catOf = k => WP.arsenal[k]?.c || 'other';
  const present = WP_CATS.filter(c => [...counts.keys()].some(k => catOf(k) === c));
  if (WP.cat && !present.includes(WP.cat)) WP.cat = '';
  $('#wpCats').innerHTML = `<button class="chipbtn${!WP.cat ? ' active' : ''}" data-wpcat="">${esc(t('cat.all'))}</button>`
    + present.map(c => `<button class="chipbtn${WP.cat === c ? ' active' : ''}" data-wpcat="${c}">${esc(t('wcat.' + c))}</button>`).join('');
  const q = norm(WP.q);
  let items = [...counts.entries()].filter(([k]) => (!WP.cat || catOf(k) === WP.cat) && (!q || norm(wpName(k) + ' ' + k).includes(q)));
  // shell types ("any APFSDS") first in the ammunition category
  if (!WP.cat || WP.cat === 'ammo') {
    const typeItems = [...types.entries()].map(([tp, n]) => ['T:' + tp, n]).filter(([k]) => !q || norm(k.slice(2)).includes(q));
    items = WP.cat === 'ammo' ? [...typeItems, ...items] : [...items, ...typeItems];
  }
  const typesFirst = WP.cat === 'ammo' ? 1 : -1;
  items.sort((a, b) => (b[0].startsWith('T:') - a[0].startsWith('T:')) * typesFirst || b[1] - a[1] || wpName(a[0]).localeCompare(wpName(b[0])));
  const max = 360;
  $('#wpGrid').innerHTML = items.slice(0, max).map(([k, n]) => `<button class="wp-tile${sel.has(k) ? ' active' : ''}" data-wpk="${esc(k)}" title="${esc(wpName(k))}">
      ${wpIcon(k)}<span class="wp-name">${esc(wpName(k))}</span><span class="wp-n">${esc(t('wpick.count', { n: I18N.num(n) }))}</span></button>`).join('')
    + (items.length > max ? `<p class="hint wp-more">${esc(t('wpick.more', { n: items.length - max }))}</p>` : '')
    + (!items.length ? `<p class="hint">${esc(t('results.empty'))}</p>` : '');
  renderWeaponChosen();
}

function renderWeaponChosen() {
  const sel = S.f.wsel || [];
  const chips = sel.map(k => `<span class="wp-chip">${wpIcon(k)}<span>${esc(wpName(k))}</span><button data-wprm="${esc(k)}" title="${esc(t('action.delete'))}">${icon('x', 'ic-sm')}</button></span>`).join('');
  $('#wpChosen').innerHTML = chips || `<span class="hint">${esc(t('wpick.hint'))}</span>`;
  $('#wpSelSide').innerHTML = chips;
  $('#wpCount').textContent = sel.length ? t('results.count', { n: I18N.num(S.filtered?.length || 0) }) : '';
}

function bindWeaponPicker() {
  const toggle = k => {
    const sel = new Set(S.f.wsel || []);
    sel.has(k) ? sel.delete(k) : sel.add(k);
    S.f.wsel = [...sel];
    applyFilters();
  };
  $('#dlgWeapons').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.wpcat !== undefined) { WP.cat = b.dataset.wpcat; return renderWeaponPicker(); }
    if (b.dataset.wpk) { toggle(b.dataset.wpk); return renderWeaponPicker(); }
    if (b.dataset.wprm) { toggle(b.dataset.wprm); return renderWeaponPicker(); }
    if (b.id === 'wpClear') { S.f.wsel = []; applyFilters(); return renderWeaponPicker(); }
    if (b.id === 'wpDone' || b.id === 'wpClose') $('#dlgWeapons').close();
  });
  $('#wpSearch').addEventListener('input', debounce(e => { WP.q = e.target.value; renderWeaponPicker(); }, 100));
  $('#statFilters').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.id === 'btnWeapons') openWeaponPicker();
    if (b.dataset.wprm) { toggle(b.dataset.wprm); renderWeaponChosen(); }
  });
}

// ------------------------------------------------------------------ sorting
function statCmp(sort) {
  const k = sort?.startsWith('s:') ? sort.slice(2) : null;
  if (!k || !STATS[k]) return null;
  const dir = STATS[k].better === -1 ? 1 : -1;  // best first
  return (a, b) => {
    const x = statVal(a, k), y = statVal(b, k);
    if (x == null || y == null) return (x == null) - (y == null);
    return (x - y) * dir || (brOf(a) ?? 99) - (brOf(b) ?? 99);
  };
}

function updateSortOptions() {
  const sel = $('#sort');
  if (!sel) return;
  const keys = statKeys(S.f.cat);
  if (S.f.sort?.startsWith('s:') && !keys.includes(S.f.sort.slice(2))) S.f.sort = 'br';
  const base = ['br', 'rank', 'name', 'nation', 'rarity'].map(k => `<option value="${k}">${esc(t('sort.' + k))}</option>`).join('');
  sel.innerHTML = base + `<optgroup label="${esc(t('stats.title'))}">${keys.map(k => `<option value="s:${k}">${esc(statLabel(k, S.f.cat))}${STATS[k].better ? (STATS[k].better > 0 ? ' ↓' : ' ↑') : ''}</option>`).join('')}</optgroup>`;
  sel.value = S.f.sort;
}

// ------------------------------------------------------------------ sidebar
function renderStatFilters() {
  const box = $('#statFilters');
  if (!box) return;
  const f = S.f.stats || {};
  const keys = statKeys(S.f.cat);
  box.innerHTML = `<div class="wsearch"><span>${esc(t('filters.weapon'))}</span>
      <button type="button" class="btn btn-sm btn-block" id="btnWeapons">${icon('ammo', 'ic-sm')}<span>${esc(t('wpick.button'))}</span></button>
      <div class="wp-side" id="wpSelSide"></div></div>
    ${S.f.cat === 'all' ? `<p class="hint">${esc(t('filters.statsPickType'))}</p>` : ''}
    <div class="stat-rows">${keys.map(k => {
      const [lo, hi] = f[k] || [];
      const unit = STATS[k].unit ? ` (${STATS[k].unit})` : '';
      return `<div class="stat-row${lo != null || hi != null ? ' on' : ''}" title="${esc(statLabel(k, S.f.cat) + unit)}"><span>${esc(statLabel(k, S.f.cat))}</span>
        <input type="number" step="any" data-stat="${k}" data-b="0" value="${lo ?? ''}" placeholder="${esc(t('filters.min'))}">
        <input type="number" step="any" data-stat="${k}" data-b="1" value="${hi ?? ''}" placeholder="${esc(t('filters.max'))}"></div>`;
    }).join('')}</div>`;
  if ((S.f.wsel || []).length) (WP.arsenal ? Promise.resolve() : getData('arsenal.json').then(a => { WP.arsenal = a; }).catch(() => {}))
    .then(() => { if ($('#wpSelSide')) $('#wpSelSide').innerHTML = (S.f.wsel || []).map(k => `<span class="wp-chip">${wpIcon(k)}<span>${esc(wpName(k))}</span><button data-wprm="${esc(k)}">${icon('x', 'ic-sm')}</button></span>`).join(''); });
}

function bindStatFilters() {
  const box = $('#statFilters');
  box.addEventListener('change', e => {
    const el = e.target;
    if (el.dataset.stat === undefined) return;
    const stats = S.f.stats ||= {};
    const cur = stats[el.dataset.stat] || [null, null];
    cur[+el.dataset.b] = el.value === '' ? null : +el.value;
    if (cur[0] == null && cur[1] == null) delete stats[el.dataset.stat]; else stats[el.dataset.stat] = cur;
    el.closest('.stat-row').classList.toggle('on', cur[0] != null || cur[1] != null);
    applyFilters();
  });
  bindWeaponPicker();
}

// ------------------------------------------------------------------ vehicle card / drawer
function cardStatHTML(v) {
  const k = S.f.sort?.startsWith('s:') ? S.f.sort.slice(2) : null;
  if (!k || !STATS[k]) return '';
  return `<span class="card-stat" title="${esc(statLabel(k, v.c))}">${esc(fmtStat(k, statAt(v, k)))}</span>`;
}

// the line of vehicles to research up to this one (v.rq = the one before it), with what it costs in all and what each pays in RP
function researchPath(v) {
  const path = [];
  for (let x = v; x && !path.includes(x) && path.length < 80; x = S.byId.get(x.rq)) path.unshift(x);
  return path;
}

// done: what the player has, left out of the sums; in the panel, the plan's button
function researchPathHTML(v, done = HG.owned, panel = done === HG.owned) {
  const path = researchPath(v), left = path.filter(x => !done.has(x.id));
  if (path.length < 2) return panel ? `<div class="rpath"><button class="btn btn-sm btn-ghost" data-act="goal">${esc(t('hg.addGoal'))}</button></div>` : '';
  const sum = k => left.reduce((n, x) => n + (x.s?.[k] || 0), 0);
  const cost = (x, k) => (x.s?.[k] ? `${I18N.num(x.s[k])} ${STATS[k].unit}` : '—');
  const sums = `${t(left.length < path.length ? 'hg.left' : 'path.count', { n: left.length })} · ${I18N.num(sum('rp'))} RP · ${I18N.num(sum('sl'))} SL`;
  return `<details class="rpath"><summary>${esc(t('path.title'))}${panel ? ` · ${esc(sums)}` : ''}</summary>
    <ol>${path.map(x => `<li class="${done.has(x.id) ? 'done' : ''}"><span>${esc(I18N.unit(x.id))}</span><span>${cost(x, 'rp')}</span><span>${cost(x, 'sl')}</span><span title="${esc(t('stat.rpm'))}">${esc(fmtStat('rpm', x.s?.rpm))}</span></li>`).join('')}</ol>
    <small class="muted">${esc(t('path.note'))}</small>${panel ? `<button class="btn btn-sm btn-ghost rpath-goal" data-act="goal">${esc(t('hg.addGoal'))}</button>` : ''}</details>`;
}

// the panel's Economy block: the mode's numbers, repairs stock and with all upgrades when they differ
function economyHTML(v) {
  const repair = (label, list) => [label, list?.[S.f.brMode] === undefined ? null : fmtStat('rep', list[S.f.brMode])];
  const tiles = [[t('stat.rp'), v.s?.rp != null && fmtStat('rp', v.s.rp)], [t('stat.sl'), v.s?.sl != null && fmtStat('sl', v.s.sl)],
    ...(v.su?.rep ? [repair(`${t('stat.rep')} · ${t('upg.stock')}`, v.su.rep), repair(`${t('stat.rep')} · ${t('upg.full')}`, v.s.rep)] : [repair(t('stat.rep'), v.s?.rep)]),
    [t('stat.slm'), v.s?.slm && fmtStat('slm', v.s.slm[S.f.brMode])], [t('stat.rpm'), v.s?.rpm != null && fmtStat('rpm', v.s.rpm)],
    [t('stat.fr'), v.s?.fr != null && fmtStat('fr', v.s.fr)]].filter(x => x[1]);
  if (!tiles.length) return '';
  return `<div class="lim eco"><div class="lim-title row-between"><span>${esc(t('eco.title'))}</span>
      <div class="seg seg-xs">${MODES.map((m, i) => `<button data-act="ecoMode" data-mode="${i}" class="${i === S.f.brMode ? 'active' : ''}">${esc(t('filters.mode.' + m))}</button>`).join('')}</div></div>
    <div class="vstats">${tiles.map(([k, x]) => `<div class="vstat"><span>${esc(k)}</span><b>${esc(x)}</b></div>`).join('')}</div></div>`;
}

function statsBlockHTML(v) {
  const keys = statKeys(v.c).filter(k => v.s?.[k] != null && !STATS[k].eco);
  if (!keys.length && !v.s?.rep) return '<div id="vstatsWrap"></div>';
  const hasUpg = v.su && Object.keys(v.su).length;
  const estimated = hasUpg && ['air', 'heli'].includes(v.c);
  return `<div id="vstatsWrap">${hasUpg ? upgSwitchHTML(estimated) : ''}<div class="vstats">${keys.map(k => {
    const chg = v.su?.[k] != null;
    const tip = STATS[k].triple ? t('stat.armHint') : chg ? `${t('upg.stock')}: ${fmtStat(k, v.su[k])} → ${t('upg.full')}: ${fmtStat(k, v.s[k])}` : '';
    return `<div class="vstat${chg ? ' upg-chg' : ''}" title="${esc(tip)}"><span>${esc(statLabel(k, v.c))}</span><b>${esc(fmtStat(k, statAt(v, k)))}</b></div>`;
  }).join('')}</div>${economyHTML(v)}${researchPathHTML(v)}</div>`;
}
