/* WTFTD — pylon loadout editor, laid out like the in-game one:
   rows = presets (first row: your custom loadout), columns = pylons, cells = weapon icons.
   cfg.pylons = { slot: "<official option name>" | { w: "<catalog weapon key>", n: count[, cw: "<My weapons id>", mod] } } */
'use strict';

const WCATS = ['aam_ir', 'aam_radar', 'sam', 'agm', 'atgm', 'rockets', 'bombs', 'guided_bombs', 'nuke', 'torpedoes', 'mines', 'fuel', 'pods', 'gun'];
const NEEDS = { radar: 'need.radar', laser: 'need.laser', saclos: 'need.saclos', tv: 'need.tv' };
const LP = { slot: null, q: '', cat: '', nonStd: false, weapons: null, loading: null };

const ammoIcon = ic => (ic ? `<img class="wicon" src="/img/ammo/${encodeURIComponent(ic)}.png" alt="" loading="lazy">` : '<span class="wicon-ph"></span>');

async function loadWeapons() {
  if (LP.weapons) return LP.weapons;
  if (!LP.loading) LP.loading = getData('weapons.json').then(w => { LP.weapons = w; return w; }).catch(() => ({}));
  return LP.loading;
}

// pylons: the game's WeaponSlots, else (fixed presets only) the attachment points their presets use
const pylonsOf = d => (d.sl?.length ? d.sl : d.lp) || [];
const presetPylons = p => p.s || p.ls || null;
function slotsSorted(d) { return [...pylonsOf(d)].sort((a, b) => (a.t ?? a.i) - (b.t ?? b.i)); }
function slotOption(d, slotIdx, name) { return pylonsOf(d).find(s => s.i === slotIdx)?.o.find(o => o.n === name); }
const optionIcon = o => o.ic || weaponIconId(o.w[0]?.[0] || '');

function needWarning(d, g) {
  if (!NEEDS[g]) return '';
  return (d.cap || []).includes(g) ? '' : t(NEEDS[g]);
}

// one cell of the grid for a pylon value (official option name or catalog pick)
function cellHTML(d, slot, val, editable, active) {
  let inner = '', title = t('ammo.empty'), warn = '';
  if (typeof val === 'string' && val) {
    const o = slotOption(d, slot.i, val);
    if (o) { inner = ammoIcon(optionIcon(o)); title = o.w.map(([k, n]) => `${n}× ${I18N.weapon(k)}`).join(', '); }
  } else if (val && typeof val === 'object') {
    const w = LP.weapons?.[val.w];
    if (w) {
      inner = ammoIcon(w.ic) + (val.n > 1 ? `<span class="wcount">${+val.n}</span>` : '') + (val.cw ? '<i class="lmine">★</i>' : '');
      title = `${+val.n || 1}× ${pylonWeaponName(val)}`;
      warn = needWarning(d, w.g);
    }
  }
  const cls = ['lcell', editable ? 'edit' : '', active ? 'active' : '', val && typeof val === 'object' ? 'nonstd' : '', val?.cw ? 'mine' : '', warn ? 'warn' : ''].join(' ');
  const drag = val && S.cfg.pylons ? ` draggable="true" data-ldrag="${slot.i}"` : '';  // onto the Custom row: loadoutDrag
  return editable
    ? `<button class="${cls}" data-lcell="${slot.i}"${drag} title="${esc(title + (warn ? ' — ⚠ ' + warn : ''))}">${inner}${warn ? '<i class="lwarn">!</i>' : ''}</button>`
    : `<span class="${cls}"${drag} title="${esc(title)}">${inner}</span>`;
}

// a pylon's catalog pick: the game's name, or the name of one of My weapons (the one saved with the pylon if deleted)
const pylonMine = val => (val?.cw ? MW.list.find(x => x.id === val.cw) : null);
const pylonWeaponName = val => pylonMine(val)?.name || val.nm || I18N.weapon(val.w);

function loadoutGridHTML(v, d) {
  if (!LP.weapons) { loadWeapons().then(() => { if (S.sel) renderDrawer(); }); }
  const c = S.cfg;
  const slots = slotsSorted(d);
  const custom = !!c.pylons;
  const head = `<div class="lrow lhead"><span class="llabel"></span>${slots.map(s => `<span class="lcol"${s.e && !d.sl?.length ? ` title="${esc(s.e)}"` : ''}>${s.i}</span>`).join('')}</div>`;
  const bound = boundLoadout(c), name = bound?.name || t('loadout.customRow');
  const customRow = custom ? `<div class="lrow lcustom active"><span class="llabel" title="${esc(name)}">${icon('sliders', 'ic-sm')} ${esc(name)}</span>
      ${slots.map(s => cellHTML(d, s, c.pylons[s.i], true, LP.slot === s.i)).join('')}</div>` : '';
  const savedRows = cdkOn() ? savedLoadouts(v.id).map(sl => `<div class="lrow lsaved${custom && sl === bound ? ' current' : ''}" data-lsaved="${esc(sl.id)}" title="${esc(t('loadout.useSaved'))}">
      <span class="llabel">${icon('star', 'ic-sm')} ${esc(sl.name)}</span>
      ${slots.map(s => cellHTML(d, s, sl.pylons[s.i], false, false)).join('')}</div>`).join('') : '';
  const presetRows = d.pr.filter(p => presetPylons(p) || !p.w.length).map(p => {
    const active = !custom && c.preset === p.id;
    return `<div class="lrow${active ? ' active' : ''}" data-lrow="${esc(p.id)}" title="${esc(custom ? t('loadout.copyPreset') : t('loadout.usePreset'))}">
      <span class="llabel">${esc(presetLabel(v, p))}</span>
      ${slots.map(s => cellHTML(d, s, (presetPylons(p) || {})[s.i], false, false)).join('')}</div>`;
  }).join('');
  const picker = custom && LP.slot != null ? pickerHTML(v, d) : '';  // right under the Custom row, above the presets
  const grid = `<div class="lgrid" style="--lcols:${slots.length}">${head}${customRow}${picker}${savedRows}${presetRows}</div>`;
  const toggle = cdkOn()
    ? `<div class="lsave"><label class="switch"><input type="checkbox" data-bind-cfg="customPylons" ${custom ? 'checked' : ''}><span class="sw"></span><span>${esc(t('loadout.custom'))}</span></label>${custom ? loadoutBarHTML(c, bound) : ''}</div>`
    : `<p class="hint">${esc(t('loadout.note'))}</p>`;
  return toggle + `<div class="lgrid-wrap">${grid}</div>` + (custom ? `<p class="hint" style="margin-top:8px">${esc(t('loadout.dragHint'))}</p>` + summaryHTML(d) : `<p class="hint" style="margin-top:8px">${esc(t('loadout.gridHint'))}</p>`);
}

// ------------------------------------------------------------------ saved custom loadouts (user/loadouts.json)
// S.loadouts = [{ id, vehicle, name, pylons }]; cfg.loadout = the id of the one the Custom row edits
S.loadouts = [];
async function loadLoadouts() { try { S.loadouts = await api('loadouts'); } catch { S.loadouts = []; } }
async function persistLoadouts() { try { await api('loadouts', { loadouts: S.loadouts }); } catch (e) { toastErr(e); } }
const savedLoadouts = vid => S.loadouts.filter(x => x.vehicle === vid);
const boundLoadout = c => (c?.pylons && c.loadout ? S.loadouts.find(x => x.id === c.loadout && x.vehicle === c.vehicle) || null : null);
const loadoutDirty = (c, sl) => JSON.stringify(c.pylons) !== JSON.stringify(sl.pylons);

function loadoutBarHTML(c, sl) {
  const dirty = sl && loadoutDirty(c, sl);
  return `<span class="lsave-state">${sl ? '' : esc(t('loadout.unsaved'))}${dirty ? `<span class="chip warn">${esc(t('loadout.modified'))}</span>` : ''}</span>
    <button class="btn btn-sm" data-lbar="save" ${sl && !dirty ? 'disabled' : ''}>${icon('save', 'ic-sm')}<span>${esc(t('action.save'))}</span></button>
    ${sl ? `<button class="btn btn-sm btn-ghost" data-lbar="rename">${esc(t('variant.rename'))}</button>` : ''}
    <button class="btn btn-sm btn-ghost" data-lbar="new">+ ${esc(t('loadout.new'))}</button>
    ${sl ? `<button class="icon-btn btn-danger" data-lbar="delete" title="${esc(t('action.delete'))}">${icon('trash', 'ic-sm')}</button>` : ''}`;
}

// the bar's buttons: save (the loadout being edited, else a new one), rename, new (a copy of the Custom row), delete
async function loadoutBar(act) {
  const c = S.cfg, sl = boundLoadout(c);
  if (act === 'delete') {
    const i = S.loadouts.indexOf(sl);
    if (i < 0) return;
    S.loadouts.splice(i, 1);
    await persistLoadouts();
    toast({ title: t('loadout.deleted', { name: sl.name }), actions: [{ label: t('variant.undo'), run: async () => {
      S.loadouts.splice(i, 0, sl); await persistLoadouts(); if (S.sel) renderDrawer();
    } }] });
    return;
  }
  if (act === 'rename') {
    const name = sl && await promptText(t('variant.rename'), sl.name);
    if (!name) return;
    sl.name = name.slice(0, 80);
  } else if (act === 'save' && sl) sl.pylons = structuredClone(c.pylons);
  else {
    const name = await promptText(t('loadout.saveTitle'), `${t('loadout.customRow')} ${savedLoadouts(c.vehicle).length + 1}`);
    if (!name) return;
    const nl = { id: newId(), vehicle: c.vehicle, name: name.slice(0, 80), pylons: structuredClone(c.pylons) };
    S.loadouts.push(nl);
    c.loadout = nl.id;
  }
  await persistLoadouts();
  toast({ title: t('loadout.saved', { name: boundLoadout(c).name }), ms: 2500 });
}

// ------------------------------------------------------------------ fixed presets (aircraft without WeaponSlots)
// Laid out like the game does it (gui weaponryPresetsParams.nut getTiers): 13 columns, weapon groups in the
// order bombs / rockets / guns / air-to-ground / air-to-air, the first one centred (an even count leaves the
// middle empty), the next ones in symmetric pairs outwards; heaviest first inside a group.
const LEGACY_COLS = 13;
const LEGACY_GROUP = { bombs: 0, 'guided bombs': 0, torpedoes: 0, mines: 0, rockets: 1, atgm: 3, aam: 4 };

function legacyGroup(k) {
  const tt = LP.weapons?.[k]?.t;
  if (!tt) return /^(cannon|gun)/i.test(k) ? 2 : -1;
  return LEGACY_GROUP[tt] ?? -1;  // drop tanks, targeting pods: not in the grid
}

function legacyTiers(p) {
  const W = LEGACY_COLS, mid = Math.ceil(W / 2) - 1, spare = [];
  // guns count by their rounds: always more than the grid holds
  const blocks = p.w.map(([k, n]) => ({ k, n, g: legacyGroup(k), m: LP.weapons?.[k]?.m || 0 }))
    .filter(b => b.g >= 0).map(b => ({ ...b, ammo: b.g === 2 ? b.n * 100 : b.n }));
  const byGroup = blocks.reduce((s, b) => s + b.ammo, 0) > W;
  const tier = (b, items) => ({ k: b.k, n: items, ic: weaponIconId(b.k) });
  const distribute = (b, central) => {
    const even = b.n % 2 === 0;
    if (byGroup) return !central && even ? [tier(b, b.n / 2), tier(b, b.n / 2)] : [tier(b, b.n)];
    const out = [];
    for (let i = 0; i < b.n; i++) {
      if (central && even && i === b.n / 2) out.push({});
      out.push(tier(b, 1));
    }
    return out;
  };
  const index = (tiers, count) => {
    if (count === 0) {
      const delta = Math.ceil(tiers.length / 2) - 1;
      tiers.forEach((x, i) => { x.id = mid - (delta - i); });
      return tiers;
    }
    if (tiers.length % 2) spare.push(tiers.pop());
    const lim = tiers.length / 2, delta = Math.ceil(count / 2);
    for (let i = 0; i < lim; i++) { tiers[i].id = mid + delta + i; tiers[i + lim].id = mid - delta - i; }
    return tiers;
  };
  const res = [];
  for (let gi = 0; gi < 5; gi++) {
    for (const b of blocks.filter(x => x.g === gi).sort((a, c) => c.m - a.m || c.ammo - a.ammo)) {
      res.push(...index(distribute(b, res.length === 0), res.length));
    }
  }
  while (res.length > W) spare.push(res.shift(), res.pop());
  res.push(...index(Array.from({ length: W - res.length }, () => ({})), res.length));
  for (const x of res) {
    if (x.k || !spare.length) continue;
    const s = spare.pop();
    if (s?.k) Object.assign(x, { k: s.k, n: s.n, ic: s.ic });
  }
  const cols = Array(W).fill(null);
  for (const x of res) if (x.k && x.id >= 0 && x.id < W) cols[x.id] = x;
  return cols;
}

function legacyGridHTML(v, d) {
  if (!LP.weapons) loadWeapons().then(() => { if (S.sel) renderDrawer(); });
  const rows = d.pr.map(p => {
    const cell = x => (x
      ? `<span class="lcell" title="${esc(`${x.n}× ${I18N.weapon(x.k)}`)}">${ammoIcon(x.ic)}${x.n > 1 ? `<span class="wcount">${x.n}</span>` : ''}</span>`
      : '<span class="lcell"></span>');
    return `<div class="lrow${S.cfg.preset === p.id ? ' active' : ''}" data-lrow="${esc(p.id)}" title="${esc(t('loadout.usePreset'))}">
      <span class="llabel">${esc(presetLabel(v, p))}</span>${legacyTiers(p).map(cell).join('')}</div>`;
  }).join('');
  // custom loadout (custom vehicles): one weapon per attachment point, written as a preset of plain weapons
  const toggle = cdkOn() && d.lp?.length
    ? `<label class="switch" style="margin:2px 0 8px"><input type="checkbox" data-bind-cfg="customPylons"><span class="sw"></span><span>${esc(t('loadout.custom'))}</span></label>` : '';
  return `${toggle}<div class="lgrid-wrap"><div class="lgrid fixed" style="--lcols:${LEGACY_COLS}">${rows}</div></div>
    <p class="hint" style="margin-top:8px">${esc(t('loadout.legacyHint'))}</p>`;
}

function summaryHTML(d) {
  const rows = [];
  for (const s of slotsSorted(d)) {
    const val = S.cfg.pylons[s.i];
    if (!val) continue;
    if (typeof val === 'string') {
      const o = slotOption(d, s.i, val);
      if (o) rows.push(`<li><b>${s.i}</b>${ammoIcon(optionIcon(o))}<span>${esc(o.w.map(([k, n]) => `${n}× ${I18N.weapon(k)}`).join(', '))}</span></li>`);
    } else {
      const w = LP.weapons?.[val.w];
      const warn = w ? needWarning(d, w.g) : '';
      rows.push(`<li class="${warn ? 'warn' : ''}"><b>${s.i}</b>${ammoIcon(w?.ic)}<span>${+val.n || 1}× ${esc(pylonWeaponName(val))} <i class="chip ${val.cw ? 'info' : 'dim'}">${esc(t(val.cw ? 'myw.chip' : 'loadout.nonStd'))}</i>${warn ? `<em>⚠ ${esc(warn)}</em>` : ''}</span></li>`);
    }
  }
  return rows.length ? `<ul class="lsummary">${rows.join('')}</ul>` : `<p class="hint" style="margin-top:8px">${esc(t('loadout.pickHint'))}</p>`;
}

function pickerHTML(v, d) {
  const slot = pylonsOf(d).find(s => s.i === LP.slot);
  if (!slot) return '';
  const cur = S.cfg.pylons[slot.i];
  const cats = WCATS.filter(cat => slot.o.some(o => o.c === cat) || (LP.nonStd && LP.weapons && Object.values(LP.weapons).some(w => w.c === cat)));
  const countBox = cur && typeof cur === 'object'
    ? `<label class="lcount">${esc(t('editor.count'))} <input type="number" min="1" max="8" value="${cur.n || 1}" data-lcount></label>` : '';
  return `<div class="lpicker">
    <div class="lp-head"><b>${esc(t('loadout.pylon', { n: slot.i }))}</b>${countBox}
      <button class="btn btn-ghost btn-sm" data-lempty>${esc(t('ammo.empty'))}</button>
      <button class="icon-btn" data-lclose title="${esc(t('action.close'))}">${icon('x', 'ic-sm')}</button></div>
    <div class="lp-tools">
      <label class="search lp-search">${icon('search')}<input type="search" data-lsearch value="${esc(LP.q)}" placeholder="${esc(t('loadout.searchWeapon'))}" autocomplete="off"></label>
      <label class="switch"><input type="checkbox" data-lnonstd ${LP.nonStd ? 'checked' : ''}><span class="sw"></span><span>${esc(t('loadout.showNonStd'))}</span></label>
    </div>
    <div class="lp-cats"><button class="chipbtn${!LP.cat ? ' active' : ''}" data-lcat="">${esc(t('cat.all'))}</button>
      ${cats.map(cat => `<button class="chipbtn${LP.cat === cat ? ' active' : ''}" data-lcat="${cat}">${esc(t('wcat.' + cat))}</button>`).join('')}</div>
    <div class="lp-list" id="lpList">${pickerListHTML(d, slot)}</div>
  </div>`;
}

function pickerListHTML(d, slot) {
  const q = norm(LP.q);
  const cur = S.cfg.pylons[slot.i];
  const groups = {};
  // standard options of this pylon
  for (const o of slot.o) {
    const cat = o.c || 'other';
    if (LP.cat && cat !== LP.cat) continue;
    const label = o.w.map(([k, n]) => `${n}× ${I18N.weapon(k)}`).join(', ');
    if (q && !norm(label + ' ' + o.n).includes(q)) continue;
    (groups[cat] ||= { std: [], ext: [] }).std.push(`<button class="lp-item${cur === o.n ? ' active' : ''}" data-lpick="${esc(o.n)}">${ammoIcon(optionIcon(o))}<span>${esc(label)}</span><i class="chip info">${esc(t('loadout.standard'))}</i></button>`);
  }
  // any weapon of the game
  if (LP.nonStd && LP.weapons) {
    const counts = {};
    for (const [k, w] of Object.entries(LP.weapons)) {
      if (LP.cat && w.c !== LP.cat) continue;
      const name = I18N.weapon(k);
      if (q && !norm(name + ' ' + k).includes(q)) continue;
      counts[w.c] = (counts[w.c] || 0) + 1;
      if (counts[w.c] > (q || LP.cat ? 80 : 12)) continue;
      const warn = needWarning(d, w.g);
      const sel = cur && typeof cur === 'object' && cur.w === k;
      (groups[w.c] ||= { std: [], ext: [] }).ext.push(`<button class="lp-item${sel ? ' active' : ''}${warn ? ' warn' : ''}" data-lpickw="${esc(k)}" title="${esc(warn)}">
        ${ammoIcon(w.ic)}<span>${esc(name)}</span>${w.g ? `<i class="chip dim">${esc(t('guide.' + w.g))}</i>` : ''}${warn ? '<i class="lwarn">!</i>' : ''}</button>`);
    }
    for (const [cat, n] of Object.entries(counts)) {
      const shown = q || LP.cat ? 80 : 12;
      if (n > shown && groups[cat]) groups[cat].ext.push(`<p class="hint lp-more">${esc(t('loadout.more', { n: n - shown }))}</p>`);
    }
  }
  // My weapons (modified copies of catalog weapons): any pylon, as the game's other weapons
  const mine = MW.list.filter(cw => LP.weapons?.[cw.w] && (!LP.cat || LP.weapons[cw.w].c === LP.cat)
    && (!q || norm(cw.name + ' ' + I18N.weapon(cw.w)).includes(q)));
  const mineHTML = mine.length ? `<div class="lp-group lp-mine"><div class="opt-group-title">★ ${esc(t('nav.myWeapons'))}</div>
    ${mine.map(cw => {
      const w = LP.weapons[cw.w], warn = needWarning(d, w.g);
      const sel = cur && typeof cur === 'object' && cur.cw === cw.id;
      return `<button class="lp-item${sel ? ' active' : ''}${warn ? ' warn' : ''}" data-lpickcw="${esc(cw.id)}" title="${esc(warn || t('myw.basedOn', { name: I18N.weapon(cw.w) }))}">
        ${ammoIcon(cw.ic || w.ic)}<span>${cw.mod?.kt ? '☢ ' : ''}${esc(cw.name)}</span><i class="chip info">${esc(t('myw.chip'))}</i>${warn ? '<i class="lwarn">!</i>' : ''}</button>`;
    }).join('')}</div>` : '';
  const order = [...WCATS, 'other'];
  const html = mineHTML + order.filter(cat => groups[cat]).map(cat => `<div class="lp-group"><div class="opt-group-title">${esc(I18N.tOr('wcat.' + cat, cat))}</div>
      ${groups[cat].std.join('')}${groups[cat].ext.join('')}</div>`).join('');
  return html || `<p class="hint">${esc(t('results.empty'))}</p>`;
}

// ------------------------------------------------------------------ events (called from the drawer handlers)
function loadoutClick(b, v, d) {
  const c = S.cfg;
  if (b.dataset.lbar) { loadoutBar(b.dataset.lbar).then(() => { if (S.sel) renderDrawer(); }); return true; }
  if (b.dataset.lcell !== undefined) { LP.slot = LP.slot === +b.dataset.lcell ? null : +b.dataset.lcell; LP.q = ''; return true; }
  if (b.dataset.lclose !== undefined) { LP.slot = null; return true; }
  if (b.dataset.lempty !== undefined) { delete c.pylons[LP.slot]; return true; }
  if (b.dataset.lpick) { c.pylons[LP.slot] = b.dataset.lpick; return true; }
  if (b.dataset.lpickw) { c.pylons[LP.slot] = { w: b.dataset.lpickw, n: 1 }; return true; }
  if (b.dataset.lpickcw) {  // one of My weapons; its changes and name kept with the pylon (shared setups, deleted weapon)
    const cw = MW.list.find(x => x.id === b.dataset.lpickcw);
    if (cw) c.pylons[LP.slot] = { w: cw.w, n: 1, cw: cw.id, nm: cw.name, mod: cw.mod };
    return true;
  }
  if (b.dataset.lcat !== undefined) { LP.cat = b.dataset.lcat; return true; }
  return false;
}

function loadoutRowClick(row, v, d) {
  const c = S.cfg;
  if (row.dataset.lsaved) {  // a saved loadout into the Custom row; unsaved changes there can be brought back
    const sl = S.loadouts.find(x => x.id === row.dataset.lsaved), was = boundLoadout(c);
    if (!sl) return;
    const lost = c.pylons && Object.keys(c.pylons).length && (!was || loadoutDirty(c, was)) && loadoutDirty(c, sl)
      ? { pylons: c.pylons, loadout: c.loadout } : null;
    Object.assign(c, { pylons: structuredClone(sl.pylons), loadout: sl.id });
    LP.slot = null;
    if (lost) toast({ title: t('loadout.replaced'), actions: [{ label: t('variant.undo'), run: () => { Object.assign(c, lost); if (S.cfg === c && S.sel) renderDrawer(); } }] });
    return;
  }
  const p = d.pr.find(x => x.id === row.dataset.lrow);
  if (!p) return;
  if (c.pylons) c.pylons = Object.fromEntries(Object.entries(presetPylons(p) || {}).map(([k, val]) => [+k, val]));  // copy into custom
  else c.preset = p.id;
}

function loadoutChange(el) {
  const c = S.cfg;
  if (el.dataset.lnonstd !== undefined) { LP.nonStd = el.checked; return true; }
  if (el.dataset.lcount !== undefined) {
    const cur = c.pylons[LP.slot];
    if (cur && typeof cur === 'object') cur.n = Math.max(1, Math.min(8, +el.value || 1));
    return true;
  }
  return false;
}

// ------------------------------------------------------------------ drag and drop onto the Custom row
// a pylon's value as pylon `to` takes it: the same option, one with the same weapons, else its weapon as a catalog
// pick ('' when empty); null when it can't go there (several weapons in the option, weapon outside the catalog)
function fitPylon(d, from, to, val) {
  if (!val) return '';
  if (typeof val === 'object') return structuredClone(val);
  const o = slotOption(d, from, val), slot = pylonsOf(d).find(s => s.i === to);
  if (!o || !slot) return null;
  const same = slot.o.find(x => x.n === val) || slot.o.find(x => JSON.stringify(x.w) === JSON.stringify(o.w));
  if (same) return same.n;
  const [k, n] = o.w[0];
  return o.w.length === 1 && LP.weapons?.[k] ? { w: k, n: Math.min(n, 8) } : null;
}

// what dropping the dragged pylon on Custom pylon `to` writes: a copy, or with swap (Custom row only) both pylons
function dropPlan(to, swap) {
  const g = LP.drag, c = S.cfg, d = S.details.get(S.sel.id);
  if (!g || !c.pylons || (g.custom && g.slot === to)) return null;
  const plan = { [to]: fitPylon(d, g.slot, to, g.val) };
  if (swap && g.custom) plan[g.slot] = fitPylon(d, to, g.slot, c.pylons[to]);
  return Object.values(plan).includes(null) ? null : plan;
}

// every drag event of the drawer; true when a drop changed the loadout
function loadoutDrag(e) {
  const c = S.cfg, cell = e.target.closest?.('.lcell'), swap = e.ctrlKey || e.metaKey;
  if (e.type === 'dragstart') {
    if (!cell?.dataset.ldrag) return false;
    const slot = +cell.dataset.ldrag, row = cell.closest('[data-lrow], [data-lsaved]');
    const p = row?.dataset.lrow && S.details.get(S.sel.id).pr.find(x => x.id === row.dataset.lrow);
    const from = !row ? c.pylons : p ? presetPylons(p) : S.loadouts.find(x => x.id === row.dataset.lsaved)?.pylons;
    LP.drag = { slot, custom: !row, val: (from || {})[slot] };
    e.dataTransfer.setData('text/plain', '');  // Firefox starts a drag only with data
    e.dataTransfer.effectAllowed = 'copyMove';
    return false;
  }
  if (e.type === 'dragend') { LP.drag = null; return false; }
  const to = cell?.dataset.lcell !== undefined ? +cell.dataset.lcell : null;
  const plan = to !== null ? dropPlan(to, swap) : null;
  if (e.type === 'dragleave') cell?.classList.remove('ldrop');
  if (e.type === 'dragover') {
    cell?.classList.toggle('ldrop', !!plan);
    if (plan) { e.preventDefault(); e.dataTransfer.dropEffect = swap && LP.drag.custom ? 'move' : 'copy'; }
  }
  if (e.type !== 'drop' || !plan) return false;
  e.preventDefault();
  LP.drag = null;
  for (const [k, val] of Object.entries(plan)) { if (val) c.pylons[k] = val; else delete c.pylons[k]; }
  return true;
}

function loadoutInput(el) {
  if (el.dataset.lsearch === undefined) return false;
  LP.q = el.value;
  const d = S.details.get(S.sel.id);
  const slot = pylonsOf(d).find(s => s.i === LP.slot);
  if (slot) $('#lpList').innerHTML = pickerListHTML(d, slot);
  return true;
}
