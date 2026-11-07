/* WTFTD — your library: My maps (saved map variants), My vehicles (saved vehicle setups), My missions
   (saved vehicle + map combos, and the mission files created in the game). Everything can be shared:
   a code / .wtftd file says what it holds (kind: vehicle, map, mission) and is imported into its list. */
'use strict';

S.combos = [];

// a vehicle's own setup: what a saved vehicle keeps (no map, map settings or mission options)
function vehicleOnly(c) {
  const { _autoTitle, scenario, edits, targets, environment, weather, heading, title, fileName, description, missionType, ...cfg } = c || {};
  cfg.cheats = { ...(c?.cheats || {}) };
  delete cfg.cheats.passiveEnemies;
  delete cfg.cheats.hostileEnemies;
  return cfg;
}

// map settings held by a full setup (a mission's, or an old shared one)
function mapSettingsOf(cfg) {
  const ch = cfg?.cheats || {};
  return {
    environment: cfg?.environment || '', weather: cfg?.weather || '',
    enemies: ch.hostileEnemies ? 'hostile' : ch.passiveEnemies ? 'passive' : '', heading: cfg?.heading == null ? '' : cfg.heading,
  };
}

async function vehicleDetails(id) {
  let d = S.details.get(id);
  if (!d) {
    try { d = await api('vehicle/' + encodeURIComponent(id)); S.details.set(id, d); }
    catch (e) { toastErr(e); return null; }
  }
  return d;
}

const newId = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 5);
const listDate = ms => (ms ? new Date(ms).toLocaleDateString(I18N.code) : '');

// ------------------------------------------------------------------ My vehicles
function renderSetups() {
  const el = $('#setupList');
  $('#setupCount').textContent = S.setups.length || '';
  if (!S.setups.length) { el.innerHTML = `<div class="empty">${icon('save', 'ic-xl')}<p>${esc(t('setups.empty'))}</p></div>`; return; }
  // the sidebar's filters apply here too
  const pass = vehicleFilter({ hidden: true });
  const shown = S.setups.filter(s => { const v = S.byId.get(s.vehicle); return !v || pass(v); });
  if (!shown.length) { el.innerHTML = `<div class="empty">${icon('search', 'ic-xl')}<p>${esc(t('setups.noMatch', { n: S.setups.length }))}</p></div>`; return; }
  el.innerHTML = shown.map(s => {
    const v = S.byId.get(s.vehicle);
    const picked = S.pick.vehicle === s.vehicle;
    return `<div class="list-item">${listThumb(s.vehicle)}
      <div class="list-main"><div class="list-title">${v ? flagHTML(v.n) : ''}${esc(s.name)}</div>
        <div class="list-sub">${esc(v ? I18N.unit(v.id) : s.vehicle)} · ${listDate(s.created)}</div></div>
      <div class="list-actions">
        <button class="btn btn-sm${picked ? '' : ' btn-primary'}" data-vchoose="${esc(s.id)}" ${v ? '' : 'disabled'}>${icon(picked ? 'check' : 'play', 'ic-sm')}<span>${esc(t('maps.choose'))}</span></button>
        <button class="btn btn-sm btn-ghost" data-vopen="${esc(s.id)}" ${v ? '' : 'disabled'}>${esc(t('library.open'))}</button>
        <button class="icon-btn" data-vshare="${esc(s.id)}" title="${esc(t('share.button'))}">${icon('share')}</button>
        <button class="icon-btn btn-danger" data-vdel="${esc(s.id)}" title="${esc(t('action.delete'))}">${icon('trash')}</button></div></div>`;
  }).join('') + (shown.length < S.setups.length ? `<p class="hint mb-note">${esc(t('setups.hidden', { n: S.setups.length - shown.length }))}</p>` : '');
}

// a saved vehicle into the bar, its setup kept for the mission (the open panel, if any, stays as it is)
async function chooseVehicleSetup(st, open = false) {
  const v = S.byId.get(st.vehicle);
  const d = v && await vehicleDetails(v.id);
  if (!d) return;
  const cfg = normalizeCfg(v, d, vehicleOnly(st.cfg));
  const ps = pickedScenario();
  if (ps && scenarioFits(ps, v)) cfg.scenario = ps.id;
  cfg.edits = S.cfg ? S.cfg.edits : null;
  S.cfgs.set(v.id, cfg);
  if (S.cfg?.vehicle === v.id) S.cfg = cfg;
  if (open) { showView('vehicles'); await openVehicle(v.id); }
  selectVehicle(v.id);
  renderSetups();
  if (!open) toast({ title: t('library.chosen', { name: st.name }), ms: 2500 });
}

function onSetupListClick(e) {
  const b = e.target.closest('button');
  if (!b) return;
  const st = S.setups.find(x => x.id === (b.dataset.vchoose || b.dataset.vopen || b.dataset.vshare || b.dataset.vdel));
  if (!st) return;
  if (b.dataset.vchoose) chooseVehicleSetup(st);
  else if (b.dataset.vopen) chooseVehicleSetup(st, true);
  else if (b.dataset.vshare) openShareObj(shareVehicle(st.cfg, st.vehicle, st.name), st.name);
  else if (b.dataset.vdel) { S.setups = S.setups.filter(x => x !== st); persistSetups(); }
}

// ------------------------------------------------------------------ My maps (saved variants)
function renderMyMaps() {
  const el = $('#myMapList');
  const list = S.variants || [];
  $('#myMapCount').textContent = list.length || '';
  if (!list.length) { el.innerHTML = `<div class="empty">${icon('map', 'ic-xl')}<p>${esc(t('mymaps.empty'))}</p></div>`; return; }
  el.innerHTML = list.map(sv => {
    const s = S.scenarios.find(x => x.id === sv.sid);
    const picked = S.pick.variant === sv.id;
    return `<div class="list-item"><div class="list-thumb"><span class="pk-map" data-level="${esc(s?.map || '')}"></span></div>
      <div class="list-main"><div class="list-title">${icon('star', 'ic-sm')} ${esc(sv.name)}</div>
        <div class="list-sub">${esc(s ? `${mapName(s.map, [s])} · ${t('kind.' + s.kind)}` : sv.sid)} · ${esc(t('editor.changes', { n: editsCount(sv.edits) }))}</div></div>
      <div class="list-actions">
        <button class="btn btn-sm${picked ? '' : ' btn-primary'}" data-mchoose="${esc(sv.id)}" ${s ? '' : 'disabled'}>${icon(picked ? 'check' : 'play', 'ic-sm')}<span>${esc(t('maps.choose'))}</span></button>
        <button class="btn btn-sm btn-ghost" data-mopen="${esc(sv.id)}" ${s ? '' : 'disabled'}>${esc(t('library.open'))}</button>
        <button class="icon-btn" data-mshare="${esc(sv.id)}" title="${esc(t('share.button'))}">${icon('share')}</button>
        <button class="icon-btn btn-danger" data-mdel="${esc(sv.id)}" title="${esc(t('action.delete'))}">${icon('trash')}</button></div></div>`;
  }).join('');
  observeThumbs(el);
}

async function onMyMapsClick(e) {
  const b = e.target.closest('button');
  if (!b) return;
  const sv = (S.variants || []).find(x => x.id === (b.dataset.mchoose || b.dataset.mopen || b.dataset.mshare || b.dataset.mdel));
  if (!sv) return;
  if (b.dataset.mchoose) {
    await setupForScenario(sv.sid, sv.id);
    renderMyMaps();
    toast({ title: t('library.chosen', { name: sv.name }), ms: 2500 });
  } else if (b.dataset.mopen) {
    await setupForScenario(sv.sid, sv.id);
    showView('maps');
    openMapDialog(S.scenarios.find(x => x.id === sv.sid)?.map);
  } else if (b.dataset.mshare) openShareObj(shareMap(sv), sv.name);
  else if (b.dataset.mdel) {
    S.variants = S.variants.filter(x => x !== sv);
    if (S.pick.variant === sv.id) { S.pick.variant = ''; savePick(); renderPickbar(); }
    await persistVariants();
    renderMyMaps();
  }
}

// ------------------------------------------------------------------ My missions: saved combos + created files
async function loadCombos() {
  try { S.combos = await api('combos'); } catch { S.combos = []; }
}
async function persistCombos() {
  try { await api('combos', { combos: S.combos }); } catch (e) { toastErr(e); }
  refreshMissions();
}

// the bar's vehicle + map (its variant, edits, map settings, mission options) saved under a name
async function saveCombo() {
  const v = pickedVehicle(), s = pickedScenario();
  if (!v || !s) return toast({ title: t('combo.needBoth'), ms: 3500 });
  const c = await pickedCfg(v);
  if (!c) return;
  const sv = savedVariant();
  const o = missionOpts();
  const name = await promptText(t('combo.saveTitle'), o.title || autoTitleFor({ ...c, scenario: s.id }));
  if (!name) return;
  S.combos.unshift({
    id: newId(), name: name.slice(0, 100), vehicle: v.id, cfg: vehicleOnly(c), sid: s.id,
    variantId: sv?.id || '', variantName: sv?.name || '', edits: c.edits?.sid === s.id ? clone(c.edits) : null,
    map: clone(S.map), mission: { missionType: S.mission.missionType || '', title: o.title, fileName: o.fileName, description: o.description }, created: Date.now(),
  });
  await persistCombos();
  toast({ title: t('combo.saved', { name }), ms: 3000 });
}

// a saved mission back into the bar: vehicle setup, map, its edits and settings, mission options
async function applyCombo(cb) {
  const v = S.byId.get(cb.vehicle);
  const d = v && await vehicleDetails(v.id);
  if (!d || !S.scenarios.some(x => x.id === cb.sid)) return false;
  const cfg = normalizeCfg(v, d, { ...vehicleOnly(cb.cfg), scenario: cb.sid });
  cfg.edits = cb.edits ? clone(cb.edits) : null;
  S.cfgs.set(v.id, cfg);
  if (S.cfg) { if (S.cfg.vehicle === v.id) S.cfg = cfg; else S.cfg.edits = cfg.edits; }  // map edits follow
  S.map = Object.assign(mapDefaults(), clone(cb.map || {}));
  saveMap();
  S.pick = { vehicle: v.id, scenario: cb.sid, variant: (S.variants || []).some(x => x.id === cb.variantId) ? cb.variantId : '' };
  savePick();
  S.mission = { missionType: cb.mission?.missionType || '', title: cb.mission?.title || '', fileName: cb.mission?.fileName || '', description: cb.mission?.description || '', key: missionKey() };
  saveMission();
  renderPickbar();
  if (S.sel) renderDrawer();
  return true;
}

async function refreshMissions() {
  try { S.missions = await api('missions'); } catch { S.missions = []; }
  $('#missionCount').textContent = (S.combos.length + S.missions.length) || '';
  const comboEl = $('#comboList');
  comboEl.innerHTML = S.combos.length ? S.combos.map(cb => {
    const v = S.byId.get(cb.vehicle), s = S.scenarios.find(x => x.id === cb.sid);
    const ok = v && s;
    return `<div class="list-item">${listThumb(cb.vehicle)}
      <div class="list-main"><div class="list-title">${v ? flagHTML(v.n) : ''}${esc(cb.name)}</div>
        <div class="list-sub">${esc(v ? I18N.unit(v.id) : cb.vehicle)} + ${esc(cb.variantName || (s ? scenarioName(s) : cb.sid))} · ${listDate(cb.created)}</div></div>
      <div class="list-actions">
        <button class="btn btn-sm" data-cchoose="${esc(cb.id)}" ${ok ? '' : 'disabled'}>${esc(t('maps.choose'))}</button>
        <button class="btn btn-sm btn-primary" data-ccreate="${esc(cb.id)}" ${ok ? '' : 'disabled'}>${icon('play', 'ic-sm')}<span>${esc(t('action.generate'))}</span></button>
        <button class="icon-btn" data-cshare="${esc(cb.id)}" title="${esc(t('share.button'))}">${icon('share')}</button>
        <button class="icon-btn btn-danger" data-cdel="${esc(cb.id)}" title="${esc(t('action.delete'))}">${icon('trash')}</button></div></div>`;
  }).join('') : `<div class="empty">${icon('save', 'ic-xl')}<p>${esc(t('combo.empty'))}</p></div>`;
  const el = $('#missionList');
  if (!S.missions.length) { el.innerHTML = `<div class="empty">${icon('file', 'ic-xl')}<p>${esc(t('missions.empty'))}</p></div>`; return; }
  el.innerHTML = S.missions.map(m => {
    const vid = m.vehicle || m.file.replace(/^wtftd_/, '').replace(/\.blk$/, '');
    const v = S.byId.get(vid);
    return `<div class="list-item">${listThumb(vid)}
      <div class="list-main"><div class="list-title">${v ? flagHTML(v.n) : ''}${esc(v ? I18N.unit(v.id) : vid)}</div>
        <div class="list-sub"><code>${esc(m.file)}</code> · ${new Date(m.mtime * 1000).toLocaleString(I18N.code)}</div></div>
      <div class="list-actions">${v ? `<button class="btn btn-sm" data-open="${esc(vid)}" data-file="${esc(m.file)}">${esc(t('action.load'))}</button>
        <button class="icon-btn" data-fshare="${esc(m.file)}" title="${esc(t('share.button'))}">${icon('share')}</button>` : ''}
        <button class="icon-btn btn-danger" data-delm="${esc(m.file)}" title="${esc(t('action.delete'))}">${icon('trash')}</button></div></div>`;
  }).join('');
}

const missionSetup = async file => {
  try { return await api('mission-setup/' + encodeURIComponent(file.replace(/\.blk$/, ''))); } catch { return null; }
};

async function onMissionListClick(e) {
  const b = e.target.closest('button');
  if (!b || b.disabled) return;
  const cb = S.combos.find(x => x.id === (b.dataset.cchoose || b.dataset.ccreate || b.dataset.cshare || b.dataset.cdel));
  if (cb) {
    if (b.dataset.cchoose && await applyCombo(cb)) toast({ title: t('library.chosen', { name: cb.name }), ms: 2500 });
    else if (b.dataset.ccreate && await applyCombo(cb)) createFromPick(b);
    else if (b.dataset.cshare) openShareObj(shareMission(cb), cb.name);
    else if (b.dataset.cdel) { S.combos = S.combos.filter(x => x !== cb); persistCombos(); }
    return;
  }
  if (b.dataset.open) {
    // restore the exact setup the mission was created with (cheats, mods, loadout…) when we have it
    const cfg = await missionSetup(b.dataset.file);
    showView('vehicles');
    openVehicle(b.dataset.open, cfg && cfg.vehicle === b.dataset.open ? cfg : null, { select: true });
  } else if (b.dataset.fshare) {
    const cfg = await missionSetup(b.dataset.fshare);
    if (cfg?.vehicle) openShareObj(shareMission(comboFromSetup(cfg, cfg.title || b.dataset.fshare)), cfg.title || b.dataset.fshare);
    else toast({ title: t('share.noSetup'), err: true });
  } else if (b.dataset.delm) {
    try { S.missions = await api('delete-mission', { file: b.dataset.delm }); } catch (err) { toastErr(err); }
    refreshMissions();
  }
}

// a full setup (a created mission's, or an old shared code) as a saved mission
function comboFromSetup(cfg, name) {
  return {
    id: newId(), name: String(name || cfg.title || I18N.unit(cfg.vehicle)).slice(0, 100), vehicle: cfg.vehicle, cfg: vehicleOnly(cfg),
    sid: cfg.scenario, variantId: '', variantName: '', edits: cfg.edits && cfg.edits.sid === cfg.scenario ? cfg.edits : null,
    map: mapSettingsOf(cfg), mission: { missionType: cfg.missionType || '', title: cfg.title || '', fileName: cfg.fileName || '', description: cfg.description || '' }, created: Date.now(),
  };
}

// ------------------------------------------------------------------ sharing
const shareVehicle = (cfg, vehicle, name) => ({ app: 'WTFTD', v: 2, kind: 'vehicle', name, vehicle, cfg: vehicleOnly({ ...cfg, vehicle }) });
const shareMap = sv => ({ app: 'WTFTD', v: 2, kind: 'map', name: sv.name, sid: sv.sid, edits: sv.edits || null, map: sv.map || null });
const shareMission = cb => {
  const { id, created, variantId, ...rest } = cb;
  return { app: 'WTFTD', v: 2, kind: 'mission', ...rest };
};

// an imported code / file into its list
async function importShared(text) {
  try {
    const data = await decodeShare(text);
    const kind = data.kind || (data.cfg?.scenario ? 'mission' : 'vehicle');  // v1 codes: a full setup
    const vehicle = data.vehicle || data.cfg?.vehicle;
    if (kind !== 'map' && !S.byId.has(vehicle)) throw new Error(t('share.unknownVehicle', { id: vehicle }));
    const sid = data.sid || data.cfg?.scenario;
    if (kind !== 'vehicle' && !S.scenarios.some(x => x.id === sid)) throw new Error(t('share.unknownMap', { id: sid }));
    let name = data.name || data.title || data.cfg?.title || '';
    if (kind === 'vehicle') {
      name ||= I18N.unit(vehicle);
      S.setups.unshift({ id: newId(), name, vehicle, cfg: vehicleOnly({ ...data.cfg, vehicle }), created: Date.now() });
      await persistSetups();
      showView('setups');
    } else if (kind === 'map') {
      name ||= scenarioName(S.scenarios.find(x => x.id === sid));
      (S.variants ||= []).push({ id: 'v' + newId(), name, sid, edits: data.edits || null, map: data.map || null });
      await persistVariants();
      showView('mymaps');
    } else if (kind === 'challenge') {
      await cgImport(data);
    } else {
      const cb = data.v === 2 ? { ...data, id: newId(), created: Date.now(), variantId: '' } : comboFromSetup(data.cfg, name);
      delete cb.app; delete cb.v; delete cb.kind;
      name = cb.name ||= I18N.unit(vehicle);
      S.combos.unshift(cb);
      await persistCombos();
      showView('missions');
    }
    $('#dlgImport').close();
    toast({ title: t('share.imported', { name }), sub: t('share.importedHint.' + kind), ms: 6000 });
  } catch (e) { toastErr(e); }
}

// ------------------------------------------------------------------ wiring
function bindLibrary() {
  $('#myMapList').addEventListener('click', onMyMapsClick);
  $('#comboList').addEventListener('click', onMissionListClick);
  for (const id of ['#btnImportMaps', '#btnImportMissions']) $(id).addEventListener('click', openImport);
  loadCombos().then(refreshMissions);
  loadVariants().then(() => { if (!$('#view-mymaps').classList.contains('hidden')) renderMyMaps(); $('#myMapCount').textContent = (S.variants || []).length || ''; });
}
