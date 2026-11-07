/* WTFTD — maps tab and the vehicle + map bar.
   The mission is a vehicle and a map / scenario, picked in any order: the vehicle in its tab (its setup —
   loadout, ammo, cheats… — stays in its panel), the map here or in the panel's first step.
   S.pick = { vehicle, scenario, variant } (remembered); the open vehicle's setup follows S.pick.scenario.
   Saved variants (S.variants, user/variants.json) = { id, name, sid, edits }: a scenario and its map edits. */
'use strict';

const MP = { kind: '', q: '', thumbs: new Map(), observer: null };
// kind filters of the maps tab ('fit' = scenarios made for the picked vehicle)
const MAP_KINDS = ['ground', 'air', 'heli', 'ship', 'boat'];

function savePick() { store.set('pick', S.pick); }

// the map's settings, for any vehicle (and kept in saved variants)
const MAP_DEFAULTS = { environment: '', weather: '', enemies: '', heading: '' };
const mapDefaults = () => JSON.parse(JSON.stringify(MAP_DEFAULTS));
S.map = Object.assign(mapDefaults(), store.get('mapset', {}));
delete S.map.targets;  // the former "Training targets" (now Vehicles by BR in the map editor)
function saveMap() { store.set('mapset', S.map); }

// the mission's own options: type, and a title / file name kept for the vehicle + map they were written for
function missionKey() { return [S.pick.vehicle || S.cfg?.vehicle, S.pick.scenario, S.pick.variant || ''].join('|'); }
// difficulty ('' = the game's briefing asks) and diffSet {difficulty: {setting: value}} hold for every mission, like its type
S.mission = Object.assign({ missionType: '', title: '', fileName: '', description: '', key: '', difficulty: '', diffSet: {} }, store.get('mission', {}));
function missionOpts() {
  const own = S.mission.key === missionKey(), d = S.mission.difficulty || '';
  return { missionType: S.mission.missionType || S.status.settings?.missionType || 'singleMission',
    title: own ? S.mission.title : '', fileName: own ? S.mission.fileName : '', description: own ? S.mission.description || '' : '',
    difficulty: d, difficultySettings: d ? S.mission.diffSet?.[d] || {} : undefined };
}
function saveMission() { store.set('mission', S.mission); }

// a mission's own setup (My missions → Load) brings its map settings back
function mapFromSetup(cfg) {
  const ch = cfg.cheats || {};
  S.map = {
    environment: cfg.environment || '', weather: cfg.weather || '',
    enemies: ch.hostileEnemies ? 'hostile' : ch.passiveEnemies ? 'passive' : '',
    heading: cfg.heading == null ? '' : cfg.heading,
  };
  saveMap();
  const d = DIFFS.includes(cfg.difficulty) ? cfg.difficulty : '';
  S.mission = { missionType: cfg.missionType || '', title: cfg.title || '', fileName: cfg.fileName || '', description: cfg.description || '', key: '',
    difficulty: d, diffSet: d ? { ...S.mission.diffSet, [d]: clone(cfg.difficultySettings || {}) } : S.mission.diffSet || {} };
  setTimeout(() => { S.mission.key = missionKey(); saveMission(); });  // once the pick holds the mission's vehicle and map
}

const pickedVehicle = () => S.byId.get(S.pick.vehicle) || null;
const pickedScenario = () => S.scenarios.find(s => s.id === S.pick.scenario) || null;
const scenarioFits = (s, v) => !v || kindsFor(v.c).includes(s.kind);
const scenarioName = s => (s.title ? t(s.title) : I18N.map(s.map));
// a map's name; the hangar levels have none in the game's files: their scenarios' title then
const mapName = (map, list) => (I18N.map(map) !== map ? I18N.map(map) : list?.[0]?.title ? t(list[0].title) : map);

const clone = o => JSON.parse(JSON.stringify(o));
const sameEdits = (a, b) => JSON.stringify(a || {}) === JSON.stringify(b || {});
const savedVariant = () => (S.variants || []).find(x => x.id === S.pick.variant) || null;
const editsCount = e => (e ? Object.keys(e.units || {}).length + (e.add || []).length + (e.player ? 1 : 0) + Object.keys(e.areas || {}).length : 0);

async function loadVariants() {
  try { S.variants = await api('variants'); } catch { S.variants = []; }
  if (S.pick.variant && !savedVariant()) { S.pick.variant = ''; savePick(); }
}
async function persistVariants() {
  try { await api('variants', { variants: S.variants }); } catch (e) { toastErr(e); }
  $('#myMapCount').textContent = (S.variants || []).length || '';
  if (!$('#view-mymaps').classList.contains('hidden')) renderMyMaps();
}

// the picked saved variant's edits into a setup of its scenario that has none of its own
function applyPickedVariant(cfg) {
  const sv = savedVariant();
  if (cfg && sv && sv.sid === cfg.scenario && (!cfg.edits || cfg.edits.sid !== sv.sid)) cfg.edits = clone(sv.edits);
}

// the open vehicle's setup takes the picked scenario (and a saved variant's edits)
function pickScenario(id, variantId = '') {
  if (!S.scenarios.some(s => s.id === id)) return;
  const was = S.pick.variant;
  S.pick.scenario = id;
  S.pick.variant = variantId || '';
  savePick();
  // the open panel takes it when it suits its vehicle, or when that vehicle is the mission's (or there is none)
  const pv = S.byId.get(S.cfg?.vehicle);
  if (S.cfg && (!pv || pv.id === S.pick.vehicle || scenarioFits(S.scenarios.find(s => s.id === id), pv))) {
    S.cfg.scenario = id;
    const sv = savedVariant();
    if (sv) S.cfg.edits = clone(sv.edits);
    else if (was && S.cfg.edits?.sid === id) S.cfg.edits = null;  // back to the official variant: no edits
  }
  const sv = savedVariant();
  if (sv) S.map = Object.assign(mapDefaults(), clone(sv.map || {}));
  else if (was) S.map = mapDefaults();
  saveMap();
  if (S.sel) renderDrawer();
  renderPickbar();
  if (!$('#view-maps').classList.contains('hidden')) renderMaps();
  if ($('#dlgMap').open) renderMapDialog();
}

function pickVehicle(id) {
  S.pick.vehicle = id || '';
  savePick();
  renderPickbar();
  if (S.sel) renderDrawer();
}

// the open panel's vehicle becomes the mission's; the map changes only when the picked one doesn't suit it
function selectVehicle(id, { ownMap = false } = {}) {
  const v = S.byId.get(id);
  if (!v) return;
  const ps = pickedScenario();
  const vc = S.cfg?.vehicle === id ? S.cfg : S.cfgs.get(id);  // the vehicle's setup: open panel, or kept one
  let own = vc?.scenario || '';
  const ownScen = S.scenarios.find(s => s.id === own);
  if (!ownMap && (!ownScen || !scenarioFits(ownScen, v))) own = (scenariosFor(v, false)[0] || S.scenarios[0])?.id || '';
  if (own && (ownMap || (ps && !scenarioFits(ps, v)))) {
    if (ps && !ownMap && own !== ps.id) toast({ title: t('pick.switched', { map: scenarioName(ps), other: scenarioName(S.scenarios.find(s => s.id === own)) }), ms: 6000 });
    if (own !== S.pick.scenario) { S.pick.scenario = own; S.pick.variant = ''; }
  }
  S.pick.vehicle = id;
  if (vc && S.pick.scenario) vc.scenario = S.pick.scenario;
  savePick();
  renderPickbar();
  if (S.sel) renderDrawer();
}

// the picked vehicle's setup, without changing the open panel's
async function pickedCfg(v) {
  if (S.cfg?.vehicle === v.id) return S.cfg;
  let c = S.cfgs.get(v.id);
  if (!c) {
    let d = S.details.get(v.id);
    if (!d) {
      try { d = await api('vehicle/' + encodeURIComponent(v.id)); S.details.set(v.id, d); }
      catch (e) { toastErr(e); return null; }
    }
    c = defaultCfg(v, d);
    S.cfgs.set(v.id, c);
  }
  c.edits = S.cfg ? S.cfg.edits : c.edits;  // the map's latest edits
  return c;
}

// ------------------------------------------------------------------ the bar
function renderPickbar() {
  const bar = $('#pickbar');
  if (!bar) return;
  const v = pickedVehicle(), s = pickedScenario(), sv = savedVariant();
  const mismatch = v && s && !scenarioFits(s, v);
  const slot = (kind, filled, thumb, name, sub, emptyKey) => `
    <div class="pk-slot${filled ? '' : ' empty'}" data-pk="${kind}" role="button" tabindex="0">
      <span class="pk-thumb">${thumb}</span>
      <span class="pk-txt"><small>${esc(t('pick.' + kind))}</small><b>${esc(filled ? name : t(emptyKey))}</b>${sub ? `<span>${sub}</span>` : ''}</span>
      ${filled ? `<button class="icon-btn pk-clear" data-pk-clear="${kind}" title="${esc(t('pick.clear'))}">${icon('x', 'ic-sm')}</button>` : '<span class="pk-clear ghost"></span>'}
    </div>`;
  bar.innerHTML = `
    ${slot('vehicle', !!v, v ? unitImgTag(v.id) : icon('all'), v ? I18N.unit(v.id) : '', v ? esc(className(v.k)) : '', 'pick.chooseVehicle')}
    <span class="pk-plus">+</span>
    ${slot('map', !!s, s ? `<span class="pk-map" data-level="${esc(s.map)}"></span>` : icon('map'), s ? (sv ? sv.name : scenarioName(s)) : '',
      s ? esc(t('kind.' + s.kind)) + (sv ? ` · ${esc(scenarioName(s))}` : '') + (mismatch ? ` <span class="pk-warn">${esc(t('pick.mismatch'))}</span>` : '') : '', 'pick.chooseMap')}
    <button class="icon-btn pk-mission" data-pk-mission title="${esc(t('mission.title'))}">${icon('gear')}</button>
    <button class="icon-btn pk-mission" data-pk-save title="${esc(t('combo.save'))}" ${v && s ? '' : 'disabled'}>${icon('save')}</button>
    <button class="btn btn-primary" data-pk-go ${v && s ? '' : 'disabled'}>${icon('play')}<span>${esc(t('action.generate'))}</span></button>`;
  observeThumbs(bar);
}

async function createFromPick(btn) {
  const v = pickedVehicle(), s = pickedScenario();
  if (!v || !s) return;
  const c = await pickedCfg(v);
  if (!c) return;
  c.scenario = s.id;
  applyPickedVariant(c);
  const open = S.cfg;
  S.cfg = c;  // the mission is the picked vehicle's setup on the picked map
  try { await generate(btn); } finally { S.cfg = open || c; }
}

function onPickbarClick(e) {
  const clear = e.target.closest('[data-pk-clear]');
  if (clear) {
    e.stopPropagation();
    if (clear.dataset.pkClear === 'vehicle') pickVehicle('');
    else { S.pick.scenario = ''; S.pick.variant = ''; savePick(); renderPickbar(); if (!$('#view-maps').classList.contains('hidden')) renderMaps(); }
    return;
  }
  if (e.target.closest('[data-pk-go]')) return createFromPick(e.target.closest('[data-pk-go]'));
  if (e.target.closest('[data-pk-mission]')) return openMissionDialog();
  if (e.target.closest('[data-pk-save]')) return saveCombo();
  const slot = e.target.closest('[data-pk]');
  if (!slot) return;
  if (slot.dataset.pk === 'map') return showView('maps');
  showView('vehicles');
  if (S.pick.vehicle) openVehicle(S.pick.vehicle);
  else $('#search').focus();
}

// ------------------------------------------------------------------ mission window (type, title, file name, difficulty)
function openMissionDialog() {
  renderMissionDialog();
  $('#dlgMission').showModal();
  if (!S.difficulty) getData('difficulty.json').catch(() => ({})).then(d => { S.difficulty = d; if ($('#dlgMission').open) renderMissionDialog(); });
}

function renderMissionDialog() {
  const v = pickedVehicle(), o = missionOpts();
  const vid = v?.id || S.cfg?.vehicle || '';
  const auto = vid && S.cfg?.vehicle === vid ? autoTitle() : `Test Drive: ${v ? I18N.unit(v.id) : '…'}`;
  $('#missionDlgBody').innerHTML = `<p class="hint">${esc(t('mission.hint'))}</p>
    <div class="field"><label>${esc(t('adv.missionType'))}</label>
      <select data-mo="missionType">${['singleMission', 'testFlight'].map(m => `<option value="${m}"${o.missionType === m ? ' selected' : ''}>${esc(t('adv.missionType.' + m))}</option>`).join('')}</select></div>
    <div class="field"><label>${esc(t('adv.title'))}</label><input type="text" data-mo="title" value="${esc(o.title)}" placeholder="${esc(auto)}"></div>
    <div class="field"><label>${esc(t('adv.fileName'))}</label><input type="text" data-mo="fileName" value="${esc(o.fileName)}" placeholder="wtftd_${esc(vid || '…')}"></div>
    <div class="field"><label>${esc(t('adv.description'))}</label><textarea data-mo="description" rows="3" maxlength="1000" placeholder="${esc(t('adv.descriptionHint'))}">${esc(o.description)}</textarea></div>
    ${difficultyHTML(v)}`;
}

// the mission's own difficulty: the game's preset for the kind of vehicle (data/difficulty.json), each setting changeable
const DIFFS = ['arcade', 'realistic', 'hardcore'];
const diffPreset = v => S.difficulty?.presets?.[{ armada: 'air', ships: 'ship' }[blockFor(v?.c || 'air')] || 'tank']?.[S.mission.difficulty];

function difficultyHTML(v) {
  if (!S.difficulty?.options?.length) return '';  // data built before the game's presets were read
  const d = S.mission.difficulty, preset = diffPreset(v), own = S.mission.diffSet?.[d] || {};
  const pick = `<div class="field"><label>${esc(I18N.diff('title'))}</label><select data-mdiff-pick><option value="">${esc(t('mission.diffInGame'))}</option>${
    DIFFS.map(x => `<option value="${x}"${x === d ? ' selected' : ''}>${esc(I18N.diff(x))}</option>`).join('')}</select></div>`;
  if (!preset) return pick;
  const val = k => own[k] ?? preset[k], name = k => esc(I18N.diff(k)) + (k in own ? ' ●' : '');
  const lists = S.difficulty.options.filter(o => o.n).map(o => `<div class="shell-pick part"><label>${name(o.k)}</label><select data-mdiff="${o.k}">${
    Array.from({ length: o.n }, (_, i) => `<option value="${i}"${+val(o.k) === i ? ' selected' : ''}>${esc(I18N.diff(`${o.k}.${i}`))}</option>`).join('')}</select></div>`).join('');
  const switches = S.difficulty.options.filter(o => !o.n).map(o => `<label class="switch"><input type="checkbox" data-mdiff="${o.k}"${val(o.k) ? ' checked' : ''}><span class="sw"></span><span>${name(o.k)}</span></label>`).join('');
  const reset = Object.keys(own).length ? `<button class="btn btn-ghost btn-sm" data-mdiff-reset>${icon('refresh', 'ic-sm')}${esc(I18N.diff('reset'))}</button>` : '';
  return `${pick}<p class="hint">${esc(t('mission.diffHint'))}</p>${lists}<div class="mod-switches">${switches}</div>${reset}`;
}

function onDifficultyInput(e) {
  const el = e.target, d = S.mission.difficulty;
  if (el.matches('[data-mdiff-reset], [data-mdiff-reset] *')) delete S.mission.diffSet?.[d];
  else if (e.type !== 'change') return false;
  else if (el.matches('[data-mdiff-pick]')) S.mission.difficulty = el.value;
  else if (el.dataset.mdiff) {
    const k = el.dataset.mdiff, preset = diffPreset(pickedVehicle());
    if (!preset) return true;
    // a switch keeps the preset's type: some on/off settings are 0/1 in the game's files
    const v = el.type === 'checkbox' ? (typeof preset[k] === 'number' ? +el.checked : el.checked) : +el.value;
    const own = ((S.mission.diffSet ||= {})[d] ||= {});
    if (v === preset[k]) delete own[k]; else own[k] = v;
  } else return false;
  saveMission();
  renderMissionDialog();
  return true;
}

function onMissionInput(e) {
  if (onDifficultyInput(e)) return;
  const key = e.target.dataset.mo;
  if (!key) return;
  if (S.mission.key !== missionKey()) Object.assign(S.mission, { title: '', fileName: '', description: '', key: missionKey() });
  S.mission[key] = e.target.value.trim();
  if (key === 'fileName') S.mission.fileName = S.mission.fileName.replace(/[^A-Za-z0-9_\-]+/g, '_');
  saveMission();
}

// ------------------------------------------------------------------ map thumbnails (the game's tactical map)
async function thumbUrl(level) {
  if (MP.thumbs.has(level)) return MP.thumbs.get(level);
  // the small copy of the map (the full one is 4096 px: the editor only)
  const p = api('level-map/' + encodeURIComponent(level)).then(m => m?.layers?.[0]?.thumb || m?.layers?.[0]?.url || null).catch(() => null);
  MP.thumbs.set(level, p);
  return p;
}

// two at a time: a map not decoded yet takes 1-8 s (one after the other on the server), and the browser asks
// only 6 things at a time from WTFTD: the maps tab would hold up every other picture (the Weapons tab's icons…)
const THUMB_JOBS = { queue: [], busy: 0, max: 2 };
function nextThumb() {
  while (THUMB_JOBS.busy < THUMB_JOBS.max && THUMB_JOBS.queue.length) {
    const el = THUMB_JOBS.queue.shift();
    if (!el.isConnected) continue;
    if (!el.offsetParent) { MP.observer.observe(el); continue; }  // its tab was left: when it shows again
    THUMB_JOBS.busy++;
    thumbUrl(el.dataset.level).then(url => new Promise(done => {
      if (!url) { el.classList.add('none'); return done(); }
      const img = new Image();
      img.onload = img.onerror = () => { el.style.backgroundImage = `url("${url}")`; done(); };
      img.src = url;
    })).finally(() => { THUMB_JOBS.busy--; nextThumb(); });
  }
}

function observeThumbs(root) {
  const els = $$('[data-level]:not([data-thumb])', root);
  if (!els.length) return;
  if (!MP.observer) {
    MP.observer = new IntersectionObserver(entries => {
      for (const en of entries) {
        if (!en.isIntersecting) continue;
        MP.observer.unobserve(en.target);
        THUMB_JOBS.queue.push(en.target);
      }
      nextThumb();
    }, { rootMargin: '200px' });
  }
  for (const el of els) { el.dataset.thumb = '1'; MP.observer.observe(el); }
}

// ------------------------------------------------------------------ maps tab
function mapsShown() {
  const v = pickedVehicle();
  if (MP.kind === 'fit' && !v) MP.kind = '';
  const q = norm(MP.q || '');
  const shown = s => (MP.kind === 'fit' ? scenarioFits(s, v) : !MP.kind || s.kind === MP.kind || (MP.kind === 'heli' && s.kind === 'ucav'))
    && (!q || norm(I18N.map(s.map) + ' ' + s.map + ' ' + scenarioName(s)).includes(q));
  const byMap = new Map();
  for (const s of S.scenarios) if (shown(s)) (byMap.get(s.map) || byMap.set(s.map, []).get(s.map)).push(s);
  const fits = list => list.some(s => scenarioFits(s, v));
  return [...byMap.entries()].sort((a, b) => (fits(b[1]) - fits(a[1])) || mapName(a[0], a[1]).localeCompare(mapName(b[0], b[1])));
}

const kindIcon = k => icon(CAT_ICON[k === 'ucav' ? 'heli' : k] || 'map', 'ic-sm');
const editCount = sid => (S.cfg?.edits?.sid === sid ? editsCount(S.cfg.edits) : 0);

function renderMaps() {
  const v = pickedVehicle();
  const maps = mapsShown();
  const kinds = [...(v ? ['fit'] : []), '', ...MAP_KINDS];
  $('#mapKinds').innerHTML = kinds.map(k => `<button class="${MP.kind === k ? 'active' : ''}" data-mkind="${k}">${esc(k === 'fit' ? t('maps.fit', { vehicle: I18N.unit(v.id) }) : k ? t('kind.' + k) : t('maps.all'))}</button>`).join('');
  $('#mapCount').textContent = t('maps.count', { n: maps.length });
  // one tile per map (its variants open in a window): the test-drive maps, then the game's other maps
  const tile = ([map, list]) => {
    const picked = list.find(s => s.id === S.pick.scenario);
    const kinds = [...new Set(list.map(s => (s.kind === 'ucav' ? 'heli' : s.kind)))];
    return `<button class="mp-tile${picked ? ' active' : ''}" data-mmap="${esc(map)}">
      <span class="mp-thumb" data-level="${esc(map)}"><span class="mp-name">${esc(mapName(map, list))}</span></span>
      <span class="mp-foot"><span class="mp-kinds">${kinds.map(k => `<span title="${esc(t('kind.' + k))}">${kindIcon(k)}</span>`).join('')}</span>
        <span class="muted">${esc(list.length === 1 ? t('maps.variant') : t('maps.variants', { n: list.length }))}</span>
        ${picked ? `<span class="chip">${icon('check', 'ic-sm')}${esc(t('kind.' + picked.kind))}</span>` : ''}</span>
    </button>`;
  };
  const official = maps.filter(([, list]) => list.some(s => !s.free));
  const battles = maps.filter(([, list]) => list.every(s => s.free) && list.some(s => s.battle));
  const others = maps.filter(([, list]) => list.every(s => s.free && !s.battle));
  const section = (title, hint, list) => (list.length ? `<div class="mp-section"><h3>${esc(title)} <span class="muted">${list.length}</span></h3>
    ${hint ? `<p class="hint">${esc(hint)}</p>` : ''}<div class="mp-grid">${list.map(tile).join('')}</div></div>` : '');
  $('#mapGrid').innerHTML = maps.length
    ? section(t('maps.official'), '', official) + section(t('maps.battles'), t('maps.battlesHint'), battles)
      + section(t('maps.others'), t('maps.othersHint'), others)
    : `<div class="empty">${icon('search', 'ic-xl')}<p>${esc(t('results.empty'))}</p></div>`;
  observeThumbs($('#mapGrid'));
}

function openMapDialog(map) {
  MP.map = map;
  renderMapDialog();
  const dlg = $('#dlgMap');
  if (!dlg.open) dlg.showModal();
}

function renderMapDialog() {
  const map = MP.map;
  if (!map) return;
  const v = pickedVehicle();
  const levels = new Set(S.status.levels || []);
  const list = (mapsShown().find(([m]) => m === map)?.[1] || S.scenarios.filter(s => s.map === map))
    .slice().sort((a, b) => scenarioFits(b, v) - scenarioFits(a, v)
      || (a.battle?.layout || 0) - (b.battle?.layout || 0) || (a.battle?.side || '').localeCompare(b.battle?.side || ''));
  $('#mapDlgName').textContent = mapName(map, list);
  const row = s => {
    const off = v && !scenarioFits(s, v);
    const missing = levels.size && !levels.has(s.map);
    const picked = S.pick.scenario === s.id && !S.pick.variant;
    const edits = picked ? editCount(s.id) : 0;
    const chips = [
      ...s.tags.filter(x => x !== 'heli' && x !== 'ucav' && x !== 'destroyer' && x !== 'battle').map(x => `<span class="chip info">${esc(I18N.tOr('tag.' + x, x))}</span>`),
      s.nation ? `<span class="chip">${flagHTML(s.nation, 'flag')} ${esc(t('scenario.targets', { nation: nationName(s.nation) }))}</span>` : '',
      `<span class="chip dim">${esc(t('scenario.start.' + s.start))}</span>`,
      s.battle ? `<span class="chip info" title="${esc(t('maps.battlesHint'))}">${esc(t('maps.battleSide', { side: s.battle.side.toUpperCase() }))}${s.battle.layout > 1 ? ' · ' + esc(t('maps.layout', { n: s.battle.layout })) : ''}</span>`
        : s.free ? `<span class="chip info" title="${esc(t('maps.othersHint'))}">${esc(t('maps.bare'))}</span>` : '',
      off ? `<span class="chip warn">${esc(t('pick.mismatch'))}</span>` : '',
      missing ? `<span class="chip warn">${esc(t('scenario.notInstalled'))}</span>` : '',
    ].join('');
    return `<div class="mv-row${picked ? ' active' : ''}${off ? ' off' : ''}${missing ? ' disabled' : ''}" data-mpick="${esc(s.id)}">
      <span class="mv-main"><span class="mp-kind">${kindIcon(s.kind)}${esc(t('kind.' + s.kind))}${s.title ? ` · ${esc(t(s.title))}` : ''}</span>
        <span class="chips">${chips}</span></span>
      <span class="mv-acts">
        <button class="btn btn-sm${picked ? ' btn-primary' : ''}" data-mpick="${esc(s.id)}" ${missing ? 'disabled' : ''}>${picked ? icon('check', 'ic-sm') : ''}<span>${esc(t(picked ? 'maps.chosen' : 'maps.choose'))}</span></button>
        <button class="btn btn-sm btn-ghost" data-medit="${esc(s.id)}" ${missing ? 'disabled' : ''}>${icon('map', 'ic-sm')}<span>${esc(t('maps.edit'))}</span>${edits ? `<span class="chip">${esc(t('editor.changes', { n: edits }))}</span>` : ''}</button>
        ${picked && (edits || !sameEdits(S.map, mapDefaults())) ? `<button class="btn btn-sm" data-msave="${esc(s.id)}">${icon('save', 'ic-sm')}<span>${esc(t('variant.save'))}</span></button>` : ''}
      </span></div>${(S.variants || []).filter(x => x.sid === s.id).map(x => savedRow(x, s, missing)).join('')}`;
  };
  const savedRow = (sv, s, missing) => {
    const picked = S.pick.variant === sv.id;
    const dirty = picked && (!sameEdits(S.cfg?.edits, sv.edits) || !sameEdits(S.map, Object.assign(mapDefaults(), sv.map || {})));
    return `<div class="mv-row mv-saved${picked ? ' active' : ''}${missing ? ' disabled' : ''}" data-mvar="${esc(sv.id)}">
      <span class="mv-main"><span class="mp-kind">${icon('star', 'ic-sm')}${esc(sv.name)}</span>
        <span class="chips"><span class="chip dim">${esc(t('variant.of', { name: scenarioName(s) }))}</span><span class="chip">${esc(t('editor.changes', { n: editsCount(sv.edits) }))}</span>${dirty ? `<span class="chip warn">${esc(t('variant.modified'))}</span>` : ''}</span></span>
      <span class="mv-acts">
        <button class="btn btn-sm${picked ? ' btn-primary' : ''}" data-mvar="${esc(sv.id)}" ${missing ? 'disabled' : ''}>${picked ? icon('check', 'ic-sm') : ''}<span>${esc(t(picked ? 'maps.chosen' : 'maps.choose'))}</span></button>
        <button class="btn btn-sm btn-ghost" data-mvedit="${esc(sv.id)}" ${missing ? 'disabled' : ''}>${icon('map', 'ic-sm')}<span>${esc(t('maps.edit'))}</span></button>
        ${dirty ? `<button class="btn btn-sm" data-mvsave="${esc(sv.id)}">${icon('save', 'ic-sm')}<span>${esc(t('variant.update'))}</span></button>` : ''}
        <button class="icon-btn" data-mvren="${esc(sv.id)}" title="${esc(t('variant.rename'))}">${icon('sliders', 'ic-sm')}</button>
        <button class="icon-btn btn-danger" data-mvdel="${esc(sv.id)}" title="${esc(t('action.delete'))}">${icon('trash', 'ic-sm')}</button>
      </span></div>`;
  };
  const chosen = list.find(s => s.id === S.pick.scenario);
  $('#mapDlgBody').innerHTML = `<div class="mv-thumb" data-level="${esc(map)}"></div>
    <p class="hint">${esc(t('maps.dialogHint'))}</p>
    <div class="mv-list">${list.map(row).join('')}</div>
    ${chosen ? mapSettingsHTML(chosen) : `<p class="hint">${esc(t('mapset.pickFirst'))}</p>`}`;
  observeThumbs($('#mapDlgBody'));
}

// ------------------------------------------------------------------ map settings (time, weather, enemies)
function mapSettingsHTML(s) {
  const m = S.map;
  const seg = (key, values, cur, label) => `<div class="seg seg-wrap" data-mset="${key}">${values.map(x => `<button class="${cur === x ? 'active' : ''}" data-v="${x}">${esc(label(x))}</button>`).join('')}</div>`;
  return `<div class="mset">
    <div class="opt-group-title">${icon('sliders', 'ic-sm')} ${esc(t('mapset.title', { name: savedVariant()?.name || scenarioName(s) }))}</div>
    <p class="hint">${esc(t('mapset.hint'))}</p>
    <div class="field"><label>${esc(t('mapset.enemies'))}</label>${seg('enemies', ['', 'passive', 'hostile'], m.enemies, x => t('mapset.enemies.' + (x || 'scenario')))}</div>
    <div class="field"><label>${esc(t('cond.time'))}</label>${seg('environment', ['', ...ENVS], m.environment, x => (x ? t('env.' + x) : t('cond.keep')))}</div>
    <div class="field"><label>${esc(t('cond.weather'))}</label>
      <select data-mset-weather><option value="">${esc(t('cond.keep'))}</option>${WEATHERS.map(w => `<option value="${w}"${m.weather === w ? ' selected' : ''}>${esc(t('weather.' + w))}</option>`).join('')}</select></div>
  </div>`;
}

function onMapSettings(e) {
  const b = e.target.closest('[data-mset] [data-v]');
  if (!b) return false;
  const key = b.closest('[data-mset]').dataset.mset;
  S.map[key] = b.dataset.v;
  saveMap();
  renderMapDialog();
  return true;
}

// the setup the map editor works on: the picked vehicle's, else a bare one (its edits follow the vehicle picked next)
async function setupForScenario(sid, variantId = '') {
  const v = pickedVehicle();
  const s = S.scenarios.find(x => x.id === sid);
  if (S.cfg) {
    // keep it
  } else if (v) {
    S.cfg = await pickedCfg(v);
    if (!S.cfg) return false;
  } else {
    S.cfg = { vehicle: '', block: s?.block || 'armada', altitude: 1500, scenario: sid, edits: S.cfg?.edits };
  }
  pickScenario(sid, variantId);
  return true;
}

function openMapsView() {
  const v = pickedVehicle();
  if (MP.kind === '' && v && !MP.touched) MP.kind = 'fit';
  renderMaps();
}

function bindMaps() {
  if (!S.pick) S.pick = { vehicle: '', scenario: '' };
  $('#pickbar').addEventListener('click', onPickbarClick);
  $('#pickbar').addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.matches('[data-pk]')) onPickbarClick(e); });
  $('#missionDlgBody').addEventListener('change', onMissionInput);
  $('#missionDlgBody').addEventListener('click', onDifficultyInput);
  $('#missionDlgBody').addEventListener('input', e => { if (e.target.dataset.mo !== 'missionType') onMissionInput(e); });
  $('#mapKinds').addEventListener('click', e => {
    const b = e.target.closest('[data-mkind]');
    if (!b) return;
    MP.kind = b.dataset.mkind;
    MP.touched = true;
    renderMaps();
  });
  $('#mapSearch').addEventListener('input', debounce(e => { MP.q = e.target.value; renderMaps(); }, 150));
  $('#mapGrid').addEventListener('click', e => {
    const b = e.target.closest('[data-mmap]');
    if (b) openMapDialog(b.dataset.mmap);
  });
  $('#mapDlgBody').addEventListener('click', async e => {
    if (onMapSettings(e)) return;
    if (await onVariantClick(e)) return;
    const edit = e.target.closest('[data-medit]');
    if (edit) {
      if (edit.disabled || !(await setupForScenario(edit.dataset.medit))) return;
      return openEditor();
    }
    const pick = e.target.closest('[data-mpick]');
    if (pick && !pick.closest('.disabled')) await setupForScenario(pick.dataset.mpick);
  });
  $('#mapDlgBody').addEventListener('change', e => {
    if (e.target.dataset.msetWeather !== undefined) { S.map.weather = e.target.value; saveMap(); renderMapDialog(); }
    if (e.target.dataset.msetHeading !== undefined) {
      const h = e.target.value.trim();
      S.map.heading = h === '' ? '' : String(((Math.round(+h) % 360) + 360) % 360);
      saveMap(); renderMapDialog();
    }
    if (e.target.dataset.msetBr !== undefined) renderMapDialog();
  });
  // the map editor closes: show its changes here too
  $('#dlgEditor').addEventListener('close', () => {
    if ($('#dlgMap').open) renderMapDialog();
    if (!$('#view-maps').classList.contains('hidden')) renderMaps();
  });
  loadVariants().then(() => { renderPickbar(); if ($('#dlgMap').open) renderMapDialog(); });
  renderPickbar();
}

// saved variants: save the current edits under a name, choose, edit, update, rename, delete
async function onVariantClick(e) {
  const b = e.target.closest('[data-msave], [data-mvsave], [data-mvren], [data-mvdel], [data-mvedit], [data-mvar]');
  if (!b || b.disabled || b.closest('.disabled')) return false;
  const byId = id => (S.variants || []).find(x => x.id === id);
  if (b.dataset.msave) {
    const s = S.scenarios.find(x => x.id === b.dataset.msave);
    const n = (S.variants || []).filter(x => x.sid === s.id).length + 1;
    const name = await promptText(t('variant.saveTitle'), `${scenarioName(s)} ${n}`);
    if (!name) return true;
    const sv = { id: 'v' + Date.now().toString(36), name: name.slice(0, 80), sid: s.id, edits: clone(S.cfg?.edits || null), map: clone(S.map) };
    (S.variants ||= []).push(sv);
    await persistVariants();
    pickScenario(s.id, sv.id);
    toast({ title: t('variant.saved', { name: sv.name }) });
    return true;
  }
  if (b.dataset.mvsave) {
    const sv = byId(b.dataset.mvsave);
    if (sv) { sv.edits = clone(S.cfg?.edits || null); sv.map = clone(S.map); await persistVariants(); renderMapDialog(); toast({ title: t('variant.saved', { name: sv.name }) }); }
    return true;
  }
  if (b.dataset.mvren) {
    const sv = byId(b.dataset.mvren);
    const name = sv && await promptText(t('variant.rename'), sv.name);
    if (name) { sv.name = name.slice(0, 80); await persistVariants(); renderMapDialog(); renderPickbar(); }
    return true;
  }
  if (b.dataset.mvdel) {
    const i = (S.variants || []).findIndex(x => x.id === b.dataset.mvdel);
    if (i < 0) return true;
    const [sv] = S.variants.splice(i, 1);
    if (S.pick.variant === sv.id) { S.pick.variant = ''; savePick(); }
    await persistVariants();
    renderMapDialog(); renderPickbar();
    toast({ title: t('variant.deleted', { name: sv.name }), actions: [{ label: t('variant.undo'), run: async () => {
      S.variants.splice(i, 0, sv); await persistVariants(); renderMapDialog();
    } }] });
    return true;
  }
  const sv = byId(b.dataset.mvedit || b.dataset.mvar);
  if (!sv || !(await setupForScenario(sv.sid, sv.id))) return true;
  if (b.dataset.mvedit) openEditor();
  return true;
}
