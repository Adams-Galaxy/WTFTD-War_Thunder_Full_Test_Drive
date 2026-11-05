/* WTFTD — quick scenario editor: top-down map of the scenario's units.
   Edits live in S.cfg.edits = { sid, units: {name: {...}}, add: [{...}] } and are applied server-side. */
'use strict';

const ED_BLOCK_CATS = { tankModels: ['ground'], armada: ['air', 'heli'], ships: ['ship', 'boat'] };
const ED_COLORS = { enemy: '#ff5a4f', ally: '#5ab8ff', player: '#f3b33d', other: '#c3cad4' };
const ED_SPACING = { tankModels: 40, armada: 150, ships: 300, air_defence: 40, structures: 60, wheeled_vehicles: 40, tracked_vehicles: 40, radars: 60, infantry: 20, objectGroups: 60 };  // between units placed / pasted side by side
// the block a unit is added as when copied (template air defence / vehicles become ground units)
const ED_ROUTE_BLOCKS = ['tankModels', 'armada', 'ships', 'wheeled_vehicles', 'tracked_vehicles', 'infantry'];  // what can drive
const ED_ROUTE_SPEED = { tankModels: 30, wheeled_vehicles: 50, tracked_vehicles: 30, infantry: 6, ships: 40 };  // km/h, aircraft: their own
const ED_ROUTE_POINTS = 40;  // mission.ROUTE_POINTS
const ED_ADD_BLOCK = { tankModels: 'tankModels', armada: 'armada', ships: 'ships', air_defence: 'tankModels',
  tracked_vehicles: 'tankModels', wheeled_vehicles: 'tankModels', structures: 'structures', radars: 'radars', infantry: 'infantry', objectGroups: 'objectGroups' };
// the map moved from the keyboard, by the keys' places: Z Q S D on a French keyboard, W A S D on an English one
const ED_PAN_KEYS = { KeyW: [0, 1], KeyS: [0, -1], KeyA: [-1, 0], KeyD: [1, 0] };

const ED = {
  data: null, sel: null, multi: [], keys: new Set(), mode: 'select', addBlock: 'tankModels', addSide: 'enemy', addN: 1, zones: false, scenery: true,
  view: { scale: 1, cx: 0, cz: 0 }, drag: null, canvas: null, ctx: null, search: '', resTab: 'all', layers: [],
  labels: [], clip: null, mouse: null, byName: new Map(), configuring: false,
  auto: { src: 'me', br: 5.0, nations: [], who: 'enemy', fire: '' },
  vf: null,  // the vehicle picker's filters (edVfReset)
  hidden: [],  // dialogs closed while a unit's loadout is configured (the map window): back when the editor closes  // "Vehicles by BR"
};

function edEdits() {
  const c = S.cfg;
  if (!c.edits || c.edits.sid !== c.scenario) c.edits = { sid: c.scenario, units: {}, add: [] };
  c.edits.areas ||= {};
  return c.edits;
}
function edCount() {
  const e = S.cfg?.edits;
  if (!e || e.sid !== S.cfg.scenario) return 0;
  return Object.keys(e.units || {}).length + (e.add || []).length + (e.player ? 1 : 0) + Object.keys(e.areas || {}).length;
}

// a unit's name; objects of the game's templates have no translated name: "uk_40mm_bofors_airfield" -> "40mm bofors airfield"
const edUnitName = cls => (S.byId.has(cls) || I18N.unit(cls) !== cls ? I18N.unit(cls)
  : String(cls || '').replace(/^(us|ussr|uk|germ|jp|it|fr|cn|sw|il|ger)_/i, '').replace(/_/g, ' '));

// ------------------------------------------------------------------ the scenario's zones (areas)
// once your start is set here, the scenario's own start zones follow it (or are no longer used): not drawn
// the battle maps' capture zones and spawns (labelled) are always drawn
const edZones = () => (ED.data.areas || []).filter(z => (ED.zones || z.label) && !(z.player && edEdits().player));
const edZonePos = z => ({ ...z, ...(edEdits().areas[z.name] || {}) });
const edZoneColor = (z0, info) => (info.role && info.role !== 'other' ? ED_COLORS[info.role] : z0.used ? '#e9edf2' : 'rgba(255,255,255,.5)');
// a point of the map in a zone: a box's sizes are its widths (the battle maps' spawns and capture zones all lie within half of
// them), a sphere's or a cylinder's its radius
function edInZone(z, x, y) {
  const a = z.yaw * Math.PI / 180, dx = x - z.x, dy = y - z.z, u = dx * Math.cos(a) + dy * Math.sin(a), v = dy * Math.cos(a) - dx * Math.sin(a);
  return /box/i.test(z.type) ? Math.abs(u) <= z.sx / 2 && Math.abs(v) <= z.sz / 2 : Math.hypot(u, v) <= z.sx;
}
const edFlyer = () => S.cfg.block === 'armada';
// what the scenario puts in a zone: its units by vehicle (most first), and the side they fight for
function edZoneInfo(z0) {
  const counts = new Map(), sides = new Set(), blocks = new Map();
  for (const n of z0.units || []) {
    const u = ED.byName.get(n);
    if (!u) continue;
    const st = edUnitState(u);
    if (st.removed) continue;
    counts.set(st.cls, (counts.get(st.cls) || 0) + (+st.count || 1));
    blocks.set(u.block, (blocks.get(u.block) || 0) + (+st.count || 1));
    sides.add(edSide(st) === 'other' && u.army && u.army !== (ED.data.army || 1) ? 'enemy' : edSide(st));
  }
  const classes = [...counts].sort((a, b) => b[1] - a[1]);
  const role = z0.player ? 'player' : sides.has('enemy') ? 'enemy' : sides.has('ally') ? 'ally' : classes.length ? 'other' : '';
  const block = [...blocks].sort((a, b) => b[1] - a[1])[0]?.[0] || '';  // what most of them are: the marker's shape
  return { classes, role, block };
}
function edZoneLabel(z0, info = edZoneInfo(z0)) {
  if (z0.player) return t('editor.zoneYou');
  if (z0.label) return z0.label[0] === '@' ? t(z0.label.slice(1)) : t('editor.capture', { zone: z0.label });
  if (!info.classes.length) return z0.name.replace(/_/g, ' ');
  const names = info.classes.slice(0, 2).map(([c]) => edUnitName(c));
  return names.join(', ') + (info.classes.length > 2 ? ` +${info.classes.length - 2}` : '');
}
// the start as it will be: position / heading from the editor, mode (ground / air) and speed
function edStart() {
  const p = ED.data.units.find(u => u.player);
  if (!p) return null;
  const pos = edPlayerPos(p);
  const g = edGround(pos.x, pos.z);
  const scen = S.scenarios.find(s => s.id === S.cfg.scenario);
  // the scenario's own start until it is changed here (or the marker was lifted well above the ground)
  const air = edFlyer() && (pos.mode ? pos.mode === 'air' : ED.data.spawn?.runway ? false : scen?.start === 'air' || pos.y > (g ?? 0) + 50);
  // an air start the scenario's scripts place: its marker may sit on the ground, show the height WTFTD would use
  const y = air && !pos.mode && g != null && pos.y < g + 50 ? Math.round(g + (S.cfg.altitude || 1500)) : pos.y;
  return { ...pos, y, air, speed: pos.speed ?? (S.cfg.speed || 450) };
}
// compass heading (0 = north, clockwise, what the game shows) <-> yaw of a game tm (from +x towards +z)
const edCompass = yaw => Math.round(((90 - (yaw || 0)) % 360 + 360) % 360);
const edYaw = compass => ((90 - compass) % 360 + 360) % 360;
const edCardinal = c => ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(c / 45) % 8];
function edSetStart(patch) {
  const s = edStart();
  const e = edEdits();
  e.player = { x: s.x, y: s.y, z: s.z, yaw: Math.round(s.yaw || 0), ...(edFlyer() ? { mode: s.air ? 'air' : 'ground', speed: s.speed } : {}), ...e.player, ...patch };
}
// zones where the selected unit(s) may appear: only for units the scenario places in game (no spot of their
// own); a unit with its own marker is shown by it alone (the zones it respawns in list every vehicle)
const edSelZones = () => {
  const names = new Set(edSelUnits().filter(u => u.runtime).map(u => u.name).filter(Boolean));
  return names.size ? (ED.data.areas || []).filter(z => (z.units || []).some(n => names.has(n))) : [];
};
// what the map shows of the zones: their outline (Zones on), and always a marker of the vehicles the
// scenario brings into a zone (its spawn points), whatever the zoom
function edZoneItems(dpr) {
  const hl = new Set(edSelZones().map(z => z.name));
  const outlined = new Set(edZones());
  const all = new Set([...outlined, ...(ED.data.areas || []).filter(z => !z.player && z.units?.length)]);
  const out = [];
  for (const z0 of all) {
    const z = edZonePos(z0), info = edZoneInfo(z0);
    const sel = ED.sel?.zone === z0.name || hl.has(z0.name);
    const spawn = !!info.classes.length && !z0.player;
    // zones at their real size (Zones on): one too small to see is left out, its vehicles keep their marker
    const outline = outlined.has(z0) && Math.max(z.sx, z.sz) * ED.view.scale >= 3 * dpr;
    if (outline || spawn) out.push({ z0, z, info, sel, spawn, outline });
  }
  return out;
}
function edDrawZones(dpr) {
  const { ctx } = ED;
  for (const { z0, z, info, sel, spawn, outline } of edZoneItems(dpr)) {
    const color = edZoneColor(z0, info);
    const [cx, cy] = edToScreen(z.x, z.z);
    if (outline) {
      const box = /box/i.test(z.type), rx = z.sx * ED.view.scale / (box ? 2 : 1), rz = z.sz * ED.view.scale / (box ? 2 : 1);
      ctx.save();
      if (!M3.on) { ctx.translate(cx, cy); ctx.rotate(-z.yaw * Math.PI / 180); }
      ctx.setLineDash(z0.used ? [6 * dpr, 4 * dpr] : [2 * dpr, 4 * dpr]);
      ctx.lineWidth = (sel ? 2.5 : 1.5) * dpr;
      ctx.strokeStyle = sel ? ED_COLORS.player : color;
      ctx.globalAlpha = z0.used || sel ? 0.9 : 0.5;
      ctx.fillStyle = color;
      ctx.beginPath();
      if (M3.on) edZoneRim(z); else if (box) ctx.rect(-rx, -rz, rx * 2, rz * 2); else ctx.ellipse(0, 0, rx, rx, 0, 0, Math.PI * 2);
      ctx.stroke();
      if (!M3.on) { ctx.globalAlpha = info.role ? 0.1 : 0.04; ctx.fill(); }  // in 3D the zone is a volume (m3Zones)
      ctx.restore();
    }
    if (spawn) edZoneMarker(cx, cy, info, sel, dpr);  // a marker of what appears there
    // labels last, under the units' own (edDrawZoneLabels)
    const own = ED.sel?.zone === z0.name;
    if ((z0.used || sel) && (outline || spawn || own)) ED.zoneLabels.push({ text: edZoneLabel(z0, info), x: cx, y: spawn ? cy - 19 * dpr : cy,
      color: sel ? ED_COLORS.player : info.role && info.role !== 'other' ? color : '#e9edf2', force: own,
      prio: own ? 0 : z0.player ? 1 : info.role === 'enemy' || info.role === 'ally' ? 2 : info.role ? 3 : 4 });
  }
}
// a zone's outline laid on the ground of the 3D map
function edZoneRim(z) {
  const { ctx } = ED, a = z.yaw * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), box = /box/i.test(z.type);
  let on = false;
  for (let i = 0; i <= 64; i++) {
    const k = (i % 16) / 8 - 1;
    const [u, v] = box ? [[k, -1], [1, k], [-k, 1], [-1, -k]][Math.floor(i / 16) % 4].map((w, n) => w * (n ? z.sz : z.sx) / 2) : [Math.cos(i / 32 * Math.PI) * z.sx, Math.sin(i / 32 * Math.PI) * z.sx];
    const wx = z.x + u * c - v * s, wz = z.z + u * s + v * c, [px, py] = edToScreen(wx, wz, Math.max(edGround(wx, wz) ?? 0, M3.water ?? -Infinity));
    if (px < -1e5) { on = false; continue; }  // behind the camera
    if (on) ctx.lineTo(px, py); else ctx.moveTo(px, py);
    on = true;
  }
}
// the vehicle shape of a unit block: aircraft a triangle, ships a diamond, the rest a square
function edShape(block, sx, sy, r) {
  const { ctx } = ED;
  ctx.beginPath();
  if (block === 'armada') { ctx.moveTo(sx, sy - r); ctx.lineTo(sx + r, sy + r * 0.8); ctx.lineTo(sx - r, sy + r * 0.8); ctx.closePath(); }
  else if (block === 'ships') { ctx.moveTo(sx, sy - r); ctx.lineTo(sx + r, sy); ctx.lineTo(sx, sy + r); ctx.lineTo(sx - r, sy); ctx.closePath(); }
  else ctx.rect(sx - r * 0.85, sy - r * 0.85, r * 1.7, r * 1.7);
}
// the vehicle the scenario brings into a zone: its shape, a dashed white outline (not a unit of its own)
function edZoneMarker(sx, sy, info, sel, dpr) {
  const { ctx } = ED;
  const r = 6 * dpr;
  ctx.save();
  ctx.fillStyle = ED_COLORS[info.role] || ED_COLORS.other;
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.3 * dpr; ctx.setLineDash([2.5 * dpr, 2 * dpr]);
  edShape(info.block, sx, sy, r);
  ctx.fill(); ctx.stroke();
  if (sel) {  // selected, or where the selected unit may appear
    ctx.setLineDash([]); ctx.strokeStyle = ED_COLORS.player; ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.arc(sx, sy, r + 5 * dpr, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
}
function edDrawZoneLabels(dpr) {
  for (const l of ED.zoneLabels.sort((a, b) => a.prio - b.prio)) edPill(l.text, l.x, l.y, l.color, dpr, { center: true, force: l.force, small: true });
}
// a label on a dark pill, skipped when it would cover one already drawn (shown on hover instead)
function edPill(text, x, y, color, dpr, { center = false, force = false, small = false } = {}) {
  const { ctx } = ED;
  ctx.save();
  ctx.font = `600 ${(small ? 11.5 : 12.5) * dpr}px Segoe UI, sans-serif`;
  const w = ctx.measureText(text).width + 12 * dpr, h = (small ? 18 : 20) * dpr;
  const x0 = center ? x - w / 2 : x, y0 = y - h / 2;
  const box = [x0 - 2 * dpr, y0 - 2 * dpr, x0 + w + 2 * dpr, y0 + h + 2 * dpr];
  if (!force && ED.labels.some(b => box[0] < b[2] && box[2] > b[0] && box[1] < b[3] && box[3] > b[1])) { ctx.restore(); return false; }
  ED.labels.push(box);
  ctx.fillStyle = 'rgba(10,13,18,.78)';
  ctx.beginPath();
  if (ctx.roundRect) ctx.roundRect(x0, y0, w, h, h / 2); else ctx.rect(x0, y0, w, h);
  ctx.fill();
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, x0 + 6 * dpr, y0 + h / 2 + 0.5 * dpr);
  ctx.restore();
  return true;
}
function edHitZone(sx, sy) {
  const dpr = window.devicePixelRatio || 1, [wx, wz] = edToWorld(sx, sy);
  const sky = M3.on && wx === ED.view.cx && wz === ED.view.cz;  // no ground under the pointer: m3ToWorld gives the view's centre
  let best = null, bd = Infinity;
  for (const { z0, z, outline, spawn } of edZoneItems(dpr)) {
    const [cx, cy] = edToScreen(z.x, z.z);
    const d = Math.hypot(cx - sx, cy - sy);
    if ((d <= (spawn ? 12 : 6) * dpr || outline && !sky && edInZone(z, wx, wz)) && d < bd) { bd = d; best = z0; }
  }
  return best;
}
// a heading arrow, in points of the canvas: it points along the ground, so it turns with the 3D view, and keeps its length on
// screen, so that its tip stays clear of the unit's marker on a low view
function edHeadingTip(p, dpr) {
  const a = (p.yaw || 0) * Math.PI / 180, L = 34 * dpr / ED.view.scale;
  const [sx, sy] = edToScreen(p.x, p.z, p.y), [ex, ey] = edToScreen(p.x + Math.cos(a) * L, p.z + Math.sin(a) * L, p.y);
  const k = 34 * dpr / (Math.hypot(ex - sx, ey - sy) || 1);
  return { sx, sy, tx: sx + (ex - sx) * k, ty: sy + (ey - sy) * k };
}
// the start's heading arrow: its tip (screen) can be dragged to turn it
function edArrowTip(dpr) {
  const s = edStart();
  return s ? edHeadingTip(s, dpr) : null;
}
// the selected units that can be turned: those whose place the mission holds, not those its scripts bring in
const edTurnable = () => edSelUnits().filter(u => { const st = edUnitState(u); return !st.removed && !st.tpl && !st.player && (st.added || st.edit); });
function edDrawArrow(dpr) {
  const tip = edArrowTip(dpr);
  if (tip) edArrow(tip, ED_COLORS.player, ED.sel?.player, dpr);
  for (const u of edTurnable()) { const st = edUnitState(u); edArrow(edHeadingTip(st, dpr), ED_COLORS[edSide(st)], true, dpr); }
}
function edArrow(tip, color, handle, dpr) {
  const { ctx } = ED;
  ctx.save();
  ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 3 * dpr;
  ctx.beginPath(); ctx.moveTo(tip.sx, tip.sy); ctx.lineTo(tip.tx, tip.ty); ctx.stroke();
  const a = Math.atan2(tip.ty - tip.sy, tip.tx - tip.sx), h = 9 * dpr;
  ctx.beginPath(); ctx.moveTo(tip.tx + Math.cos(a) * 2 * dpr, tip.ty + Math.sin(a) * 2 * dpr);
  ctx.lineTo(tip.tx - Math.cos(a - 0.5) * h, tip.ty - Math.sin(a - 0.5) * h);
  ctx.lineTo(tip.tx - Math.cos(a + 0.5) * h, tip.ty - Math.sin(a + 0.5) * h); ctx.closePath(); ctx.fill();
  if (handle) {  // the handle to turn it
    ctx.lineWidth = 2 * dpr; ctx.strokeStyle = '#fff';
    ctx.beginPath(); ctx.arc(tip.tx, tip.ty, 6 * dpr, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
}

async function openEditor() {
  const sid = S.cfg.scenario;
  ED.configuring = false;  // a unit's loadout left unfinished (another vehicle opened meanwhile)
  ED.before = S.cfg.edits ? JSON.stringify(S.cfg.edits) : null;  // Cancel puts these back
  try { ED.data = await api('scenario-units/' + encodeURIComponent(sid)); } catch (e) { toastErr(e); return; }
  edResolveStart(ED.data);
  ED.data.sid = sid;
  ED.byName = new Map(ED.data.units.map(u => [u.name, u]));
  edEdits();
  await edAutoRefresh();  // units following your vehicle: its BR may have changed
  edSelect([]); ED.mode = 'select'; ED.search = '';
  ED.layers = [];
  ED.terrain = null;
  edLoadTerrain(ED.data.level);
  let map = null;
  try { map = await api('level-map/' + encodeURIComponent(ED.data.level || '')); } catch { /* unknown level */ }
  edMapHint(map?.layers?.length ? '' : map?.noOodle ? 'editor.noOodle' : 'editor.noMap');
  for (const l of map?.layers || []) {
    const layer = { ...l, img: null };
    ED.layers.push(layer);
    const img = new Image();
    img.onload = () => { layer.img = img; edDraw(); };
    img.onerror = () => { if (!ED.layers.some(x => x.img)) edMapHint('editor.mapError'); };
    img.src = l.url;
  }
  $('#dlgEditor').showModal();
  ED.canvas = $('#edCanvas');
  ED.ctx = ED.canvas.getContext('2d');
  edResize();
  edFit();
  edRenderPanel();
  edDraw();
}
// the editor done: the dialogs closed while a unit's loadout was configured (the map window), back as they were
function edRestoreHidden() {
  for (const d of ED.hidden.splice(0)) if (!d.open) d.showModal();
}
// back to the editor as it was (after configuring a unit's loadout in the vehicle panel)
function edResume() {
  $('#dlgEditor').showModal();
  edResize();
  edRenderPanel();
  edDraw();
}

// the scenario's triggers decide where you and some units really appear: show that, not the raw unit position
function edResolveStart(data) {
  const p = data.units.find(u => u.player);
  if (p && data.spawn) {
    Object.assign(p, { tmX: p.x, tmZ: p.z, x: data.spawn.x, y: data.spawn.y, z: data.spawn.z }, data.spawn.yaw != null ? { yaw: data.spawn.yaw } : {});
  }
  for (const u of data.units) {
    if (u.tp?.start) Object.assign(u, { x: u.tp.x, y: u.tp.y, z: u.tp.z });
  }
}

function edMapHint(key) {
  $('#edMapHint').classList.toggle('hidden', !key);
  if (key) $('#edMapHint span').textContent = t(key);
}

// ------------------------------------------------------------------ geometry
function edAllPoints() {  // what the map shows: template units the scenario places in game have no known spot
  const e = edEdits();
  return [...ED.data.units.filter(u => !u.runtime), ...e.add.map((a, idx) => ({ ...a, added: true, idx }))];
}
function edFit() {
  const pts = edAllPoints().filter(u => u.edit || u.player || u.added);
  const src = pts.length ? pts : ED.data.units;
  const xs = src.map(u => u.x), zs = src.map(u => u.z);
  const minx = Math.min(...xs), maxx = Math.max(...xs), minz = Math.min(...zs), maxz = Math.max(...zs);
  const w = ED.canvas.width, h = ED.canvas.height;
  const span = Math.max(maxx - minx, maxz - minz, 400) * 1.25;
  ED.view = { scale: Math.min(w, h) / span, cx: (minx + maxx) / 2, cz: (minz + maxz) / 2 };
}
function edFitMap() {
  const l = ED.layers[ED.layers.length - 1];  // the most detailed layer (ground battle map when there is one)
  if (!l) return edFit();
  const w = ED.canvas.width, h = ED.canvas.height;
  const span = Math.max(l.max[0] - l.min[0], l.max[1] - l.min[1]) * 1.04;
  ED.view = { scale: Math.min(w, h) / span, cx: (l.min[0] + l.max[0]) / 2, cz: (l.min[1] + l.max[1]) / 2 };
}
// brings the selected unit(s) into view (a unit placed in game: the zones it may appear in), with a short glide
function edFocus() {
  const pts = [];
  for (const u of edSelUnits()) {
    const st = edUnitState(u);
    if (!u.runtime) pts.push(st);
  }
  if (!pts.length) pts.push(...edSelZones().map(edZonePos));
  if (!pts.length) return;
  const dpr = window.devicePixelRatio || 1;
  const xs = pts.map(p => p.x), zs = pts.map(p => p.z);
  const minx = Math.min(...xs), maxx = Math.max(...xs), minz = Math.min(...zs), maxz = Math.max(...zs);
  const w = ED.canvas.width, h = ED.canvas.height;
  let scale = ED.view.scale;
  const span = Math.max(maxx - minx, maxz - minz) * 1.3;
  if (span * scale > Math.min(w, h)) scale = Math.min(w, h) / span;  // they don't fit: zoom out
  if (scale * 300 < 40 * dpr) scale = Math.min(Math.min(w, h) / Math.max(span, 1), 40 * dpr / 300 * 4);  // too far to read: zoom in
  const from = { ...ED.view }, to = { scale, cx: (minx + maxx) / 2, cz: (minz + maxz) / 2 };
  const t0 = performance.now(), dur = 280;
  clearTimeout(ED.glide);
  const step = () => {  // timers, not animation frames: it ends at the target even when the window isn't drawn
    const k = Math.min(1, (performance.now() - t0) / dur), e = 1 - (1 - k) ** 3;
    ED.view = { scale: from.scale * (to.scale / from.scale) ** e, cx: from.cx + (to.cx - from.cx) * e, cz: from.cz + (to.cz - from.cz) * e };
    edDraw();
    if (k < 1) ED.glide = setTimeout(step, 16);
  };
  step();
}
const edToScreen = (x, z, y) => (M3.on ? m3ToScreen(x, z, y) : [ED.canvas.width / 2 + (x - ED.view.cx) * ED.view.scale, ED.canvas.height / 2 - (z - ED.view.cz) * ED.view.scale]);
const edToWorld = (sx, sy) => (M3.on ? m3ToWorld(sx, sy) : [ED.view.cx + (sx - ED.canvas.width / 2) / ED.view.scale, ED.view.cz - (sy - ED.canvas.height / 2) / ED.view.scale]);

function edResize() {
  const box = ED.canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  ED.canvas.width = Math.max(300, box.width) * dpr;
  ED.canvas.height = Math.max(300, box.height) * dpr;
  ED.canvas.style.width = box.width + 'px';
  ED.canvas.style.height = box.height + 'px';
}

// ------------------------------------------------------------------ state per unit
function edUnitState(u) {
  const e = edEdits();
  if (u.added) return { ...u, removed: false };
  const ov = e.units[u.name] || {};
  return { ...u, ...ov, cls: ov.cls || u.cls, removed: !!ov.remove, moved: ov.x != null, ox: u.x, oz: u.z };
}
// u: a unit state (edUnitState), so the side picked in the editor wins
function edSide(u) {
  if (u.player) return 'player';
  if (!u.edit && !u.added) return 'other';  // scenery / objects, whatever their team
  if (u.side === 'ally' || u.side === 'enemy') return u.side;  // a shared map can hold anything
  if (u.added) return 'enemy';
  if (!u.army) return 'other';
  return u.army === (ED.data.army || 1) ? 'ally' : 'enemy';
}
// movement choices for a side: enemies can hunt you, allies can escort you
function edBehaviors(side, air, added, routable) {
  return [['', added ? 'editor.move.free' : 'editor.asScenario'], ...(air ? [] : [['stay', 'editor.move.stay']]),
    side === 'ally' ? ['follow', 'editor.move.follow'] : ['hunt', 'editor.move.hunt'], ...(routable ? [['route', 'editor.move.route']] : [])];
}
const edMovable = u => u.added || (u.edit && !u.tpl && !u.removed);
// a route: points drawn on the map, shared by the units selected (a convoy keeps the gaps of its start)
const edRoutable = u => !u.tpl && ED_ROUTE_BLOCKS.includes(u.block);
const edRouteUnits = () => edSelUnits().filter(edRoutable);
const edRouteSpeed = st => +st.routeSpeed || (st.block === 'armada' ? +st.speed || 450 : ED_ROUTE_SPEED[st.block]);
const edRouteAt = (st, x, z) => ({ x: Math.round(x), z: Math.round(z),
  y: st.block === 'armada' ? Math.round(st.y) : st.block === 'ships' ? 0 : Math.round(edGroundY(x, z) * 10) / 10 });
function edRoutePoint(x, z) {
  for (const u of edRouteUnits()) {
    const st = edUnitState(u);
    if ((st.route || []).length < ED_ROUTE_POINTS) edSet(u, { route: [...(st.route || []), edRouteAt(st, x, z)] });
  }
}
function edRouteMove(i, x, z) {
  for (const u of edRouteUnits()) {
    const st = edUnitState(u);
    if (st.route?.[i]) edSet(u, { route: st.route.map((p, k) => (k === i ? edRouteAt(st, x, z) : p)) });
  }
}
function edRouteBack() {
  for (const u of edRouteUnits()) edSet(u, { route: (edUnitState(u).route || []).slice(0, -1) });
}
// the point of the selected route under the pointer (-1: none)
function edRouteHit(sx, sy) {
  const st = edRouteUnits().map(edUnitState)[0];
  return (st?.route || []).findIndex(p => {
    const [a, b] = edToScreen(p.x, p.z);
    return Math.hypot(a - sx, b - sy) < 10 * (window.devicePixelRatio || 1);
  });
}
// the Route movement picked: drawing starts; any other movement ends it
function edRouteMode(beh) {
  if (beh === 'route') for (const u of edRouteUnits()) edSet(u, { routeSpeed: edRouteSpeed(edUnitState(u)) });
  if (beh === 'route' || ED.mode === 'route') ED.mode = beh === 'route' ? 'route' : 'select';
}
// its vehicle (and loadout) can change: the scenario's own and added units, and template units the mission can
// carry itself (server: mission.inline_imports)
const edSwappable = u => !u.tpl || !!u.swap;

// ------------------------------------------------------------------ selection (one unit, several, the start or a zone)
const edKey = u => (u.added ? 'add:' + u.idx : 'u:' + u.name);
const edSelKeys = () => (ED.multi.length ? ED.multi : ED.sel?.key ? [ED.sel.key] : []);
function edUnitByKey(key) {
  const [kind, id] = key.split(/:(.*)/s);
  if (kind === 'add') { const a = edEdits().add[+id]; return a ? { ...a, added: true, idx: +id } : null; }
  return ED.byName.get(id) || null;
}
const edSelUnits = () => edSelKeys().map(edUnitByKey).filter(Boolean);
function edSelect(keys) {
  keys = [...new Set(keys)];
  ED.multi = keys.length > 1 ? keys : [];
  ED.sel = keys.length === 1 ? { key: keys[0] } : null;
  ED.search = '';
  if (ED.mode === 'route') ED.mode = 'select';
}
function edToggle(key) {
  const cur = edSelKeys();
  edSelect(cur.includes(key) ? cur.filter(k => k !== key) : [...cur, key]);
}
const edIsSelected = u => (u.player ? !!ED.sel?.player : edSelKeys().includes(edKey(u)));
// removes added units (by index) and / or takes scenario units out of the mission
function edRemoveUnits(us) {
  const e = edEdits();
  const added = us.filter(u => u.added).map(u => u.idx).sort((a, b) => b - a);
  for (const i of added) e.add.splice(i, 1);
  for (const u of us.filter(u => !u.added && !u.player)) edSet(u, { remove: true });
  if (added.length) edSelect(edSelKeys().filter(k => !k.startsWith('add:')));
}

// ------------------------------------------------------------------ copy / paste / duplicate
function edCopy() {
  const us = edSelUnits().map(edUnitState).filter(u => !u.removed && (u.added || ED_ADD_BLOCK[u.block]));
  if (!us.length) return false;
  const cx = us.reduce((s, u) => s + u.x, 0) / us.length, cz = us.reduce((s, u) => s + u.z, 0) / us.length;
  ED.clip = us.map(u => {
    const block = u.added ? u.block : ED_ADD_BLOCK[u.block];
    return {
      block, cls: u.cls, dx: u.x - cx, dz: u.z - cz, y: u.y, agl: block === 'armada' ? u.y - (edGround(u.x, u.z) ?? 0) : 0,
      yaw: Math.round(u.yaw || 0), count: +u.count || 1, speed: u.speed || 450, side: edSide(u) === 'ally' ? 'ally' : 'enemy',
      attack: ['fire_at_will', 'return_fire', 'hold_fire'].includes(u.attack) ? u.attack : 'fire_at_will',
      behavior: ['stay', 'hunt', 'follow', 'route'].includes(u.behavior) && !(block === 'armada' && u.behavior === 'stay') ? u.behavior : '',
      ...(u.behavior === 'route' ? { route: u.route, routeSpeed: u.routeSpeed, routeLoop: u.routeLoop } : {}),
      ...(u.wave ? { wave: u.wave } : {}),
      ...(u.loadout ? { loadout: JSON.parse(JSON.stringify(u.loadout)) } : {}),
    };
  });
  $('#edPaste')?.classList.remove('hidden');
  return true;
}
function edPaste(x, z) {
  if (!ED.clip?.length) return;
  const e = edEdits(), keys = [];
  for (const c of ED.clip) {
    const { dx, dz, agl, ...unit } = JSON.parse(JSON.stringify(c));
    const px = Math.round(x + dx), pz = Math.round(z + dz), g = edGround(px, pz);
    const y = unit.block === 'armada' ? (g != null ? Math.round(g + Math.max(agl, 100)) : unit.y)
      : unit.block === 'ships' ? 0 : Math.round(edGroundY(px, pz) * 10) / 10;
    e.add.push({ ...unit, x: px, y, z: pz });
    keys.push('add:' + (e.add.length - 1));
  }
  edSelect(keys);
}
function edDuplicate() {
  const us = edSelUnits().map(edUnitState);
  if (!edCopy()) return;
  const cx = us.reduce((s, u) => s + u.x, 0) / us.length, cz = us.reduce((s, u) => s + u.z, 0) / us.length;
  const step = Math.max(...ED.clip.map(c => ED_SPACING[c.block] || 40));
  edPaste(cx + step, cz - step);
}
// Ctrl+V with the pointer on the map pastes there (the copied group centred on it); otherwise, and with the
// Paste button, the group follows the pointer until a click drops it
function edPasteHere() {
  if (!ED.clip?.length) return;
  if (ED.over && ED.mouse) edPaste(...ED.mouse);
  else edPlacing(true);
}
function edPlacing(on) {
  ED.placing = on && !!ED.clip?.length;
  ED.canvas?.classList.toggle('placing', ED.placing);
  if (ED.placing) toast({ title: t('editor.pasteClick'), ms: 3000 });
}
// what Ctrl+V / a click would paste, under the pointer
function edDrawGhost(dpr) {
  if (!ED.placing || !ED.over || !ED.mouse) return;
  const { ctx } = ED;
  ctx.save();
  ctx.globalAlpha = 0.6;
  ctx.setLineDash([3 * dpr, 3 * dpr]);
  for (const c of ED.clip) {
    const [sx, sy] = edToScreen(ED.mouse[0] + c.dx, ED.mouse[1] + c.dz);
    ctx.fillStyle = ED_COLORS[c.side] || ED_COLORS.enemy; ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5 * dpr;
    edShape(c.block, sx, sy, 7 * dpr);
    ctx.fill(); ctx.stroke();
  }
  ctx.restore();
}

// ------------------------------------------------------------------ drawing
function edDraw() {
  const { ctx, canvas } = ED;
  if (!ctx) return;
  const dpr = window.devicePixelRatio || 1;
  const css = getComputedStyle(document.documentElement);
  ED.labels = [];
  ED.zoneLabels = [];
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (M3.on) { m3Camera(); m3Redraw(); edDrawItems(dpr); return; }
  ctx.fillStyle = css.getPropertyValue('--bg-2').trim() || '#0e1217';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  // tactical maps of the level (full map, then the detailed ground battle map), placed by their world extents
  const hasMap = ED.layers.some(l => l.img);
  ctx.save();
  ctx.imageSmoothingQuality = 'high';
  for (const l of ED.layers) {
    if (!l.img) continue;
    const [mnx, mnz] = l.min, [mxx, mxz] = l.max;
    const [sx0, yTop] = edToScreen(mnx, l.zUp ? mxz : mnz), [sx1, yBot] = edToScreen(mxx, l.zUp ? mnz : mxz);
    ctx.globalAlpha = 0.92;
    if (yBot >= yTop) ctx.drawImage(l.img, sx0, yTop, sx1 - sx0, yBot - yTop);
    else { ctx.save(); ctx.translate(0, yTop); ctx.scale(1, -1); ctx.drawImage(l.img, sx0, 0, sx1 - sx0, yTop - yBot); ctx.restore(); }
  }
  ctx.restore();
  if (hasMap) {  // a shade over the map: markers and labels stand out from its pale terrain
    ctx.fillStyle = 'rgba(8,11,16,.32)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  // grid
  const target = 90 * dpr / ED.view.scale;
  const step = [25, 50, 100, 250, 500, 1000, 2500, 5000, 10000].find(s => s >= target) || 10000;
  const [wx0, wz1] = edToWorld(0, 0), [wx1, wz0] = edToWorld(canvas.width, canvas.height);
  ctx.strokeStyle = hasMap ? 'rgba(255,255,255,.07)' : (css.getPropertyValue('--line').trim() || '#232b37');
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = Math.floor(wx0 / step) * step; x <= wx1; x += step) { const [sx] = edToScreen(x, 0); ctx.moveTo(sx, 0); ctx.lineTo(sx, canvas.height); }
  for (let z = Math.floor(wz0 / step) * step; z <= wz1; z += step) { const [, sy] = edToScreen(0, z); ctx.moveTo(0, sy); ctx.lineTo(canvas.width, sy); }
  ctx.stroke();
  // scale bar
  ctx.fillStyle = hasMap ? '#d7dde5' : css.getPropertyValue('--muted').trim();
  ctx.font = `${11 * dpr}px Segoe UI, sans-serif`;
  const barPx = step * ED.view.scale;
  ctx.fillRect(14 * dpr, canvas.height - 18 * dpr, barPx, 2 * dpr);
  ctx.fillText(`${step} m`, 14 * dpr, canvas.height - 24 * dpr);
  edDrawItems(dpr);
}

// what is on the map, flat or in 3D
function edDrawItems(dpr) {
  const { ctx, canvas } = ED;
  const player = ED.data.units.find(u => u.player);
  const pPos = player ? edPlayerPos(player) : null;
  const rw = ED.data.spawn?.runway;
  if (rw) {  // runway the scenario spawns you on
    const [a, b] = edToScreen(rw[0][0], rw[0][1]), [c, d] = edToScreen(rw[1][0], rw[1][1]);
    ctx.save(); ctx.lineCap = 'round';
    ctx.strokeStyle = 'rgba(0,0,0,.45)'; ctx.lineWidth = 9 * dpr; ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke();
    ctx.strokeStyle = ED_COLORS.player + 'cc'; ctx.lineWidth = 5 * dpr; ctx.setLineDash([10 * dpr, 8 * dpr]);
    ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); ctx.restore();
  }
  for (const u of ED.data.units) {  // where units respawn later in the mission
    if (!u.tp || u.tp.start || !(u.edit || u.player)) continue;
    const [a, b] = edToScreen(u.tp.x, u.tp.z), [c, d] = edToScreen(u.x, u.z);
    ctx.save(); ctx.setLineDash([2 * dpr, 4 * dpr]); ctx.strokeStyle = 'rgba(255,255,255,.4)'; ctx.lineWidth = 1 * dpr;
    ctx.beginPath(); ctx.moveTo(c, d); ctx.lineTo(a, b); ctx.stroke(); ctx.setLineDash([]);
    ctx.strokeStyle = ED_COLORS[edSide(edUnitState(u))] || '#fff'; ctx.lineWidth = 2 * dpr;
    ctx.beginPath(); ctx.arc(a, b, 6 * dpr, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
  }
  // hunt / escort lines
  for (const u of edAllPoints().map(edUnitState)) {
    if ((u.behavior === 'hunt' || u.behavior === 'follow') && pPos && !u.removed) {
      const [a, b] = edToScreen(u.x, u.z), [c, d] = edToScreen(pPos.x, pPos.z);
      ctx.setLineDash([6 * dpr, 6 * dpr]); ctx.strokeStyle = ED_COLORS[u.behavior === 'hunt' ? 'enemy' : 'ally'] + '99';
      ctx.beginPath(); ctx.moveTo(a, b); ctx.lineTo(c, d); ctx.stroke(); ctx.setLineDash([]);
    }
  }
  edDrawZones(dpr);
  edDrawRoutes(dpr);
  // markers: others first, then editable, then player; labels the other way round (the player's first)
  const pts = edAllPoints().map(edUnitState).filter(u => ED.scenery || u.edit || u.added || u.player);
  pts.sort((a, b) => (a.edit || a.added ? 1 : 0) - (b.edit || b.added ? 1 : 0) + (a.player ? 2 : 0) - (b.player ? 2 : 0));
  for (const u of pts) edMarker(u, u.player ? pPos : u, dpr);
  for (const u of pts.slice().reverse()) edMarkerLabel(u, u.player ? pPos : u, dpr);
  edDrawZoneLabels(dpr);
  edDrawArrow(dpr);  // over the labels: its tip is a handle
  edDrawGhost(dpr);
  if (ED.drag?.kind === 'box' && ED.drag.moved) {  // area selection
    const { sx, sy, x2, y2 } = ED.drag;
    ctx.save(); ctx.setLineDash([5 * dpr, 4 * dpr]); ctx.strokeStyle = ED_COLORS.player; ctx.lineWidth = 1.5 * dpr;
    ctx.fillStyle = 'rgba(243,179,61,.08)';
    ctx.fillRect(Math.min(sx, x2), Math.min(sy, y2), Math.abs(x2 - sx), Math.abs(y2 - sy));
    ctx.strokeRect(Math.min(sx, x2), Math.min(sy, y2), Math.abs(x2 - sx), Math.abs(y2 - sy));
    ctx.restore();
  }
}

// the routes: a line from the unit through its points, an arrow on each leg, back to the first point when it loops
function edDrawRoutes(dpr) {
  const { ctx } = ED;
  for (const u of edAllPoints().map(edUnitState)) {
    if (u.behavior !== 'route' || !u.route?.length || u.removed) continue;
    const sel = edIsSelected(u), pts = [[u.x, u.z], ...u.route.map(p => [p.x, p.z])].map(([x, z]) => edToScreen(x, z));
    if (u.routeLoop) pts.push(pts[1]);
    ctx.save();
    ctx.strokeStyle = ctx.fillStyle = ED_COLORS[edSide(u)];
    ctx.globalAlpha = sel ? 1 : 0.6; ctx.lineWidth = (sel ? 2 : 1.5) * dpr;
    ctx.beginPath(); pts.forEach(([a, b], i) => (i ? ctx.lineTo(a, b) : ctx.moveTo(a, b))); ctx.stroke();
    pts.slice(1).forEach(([a, b], i) => {
      const [c, d] = pts[i], mx = (a + c) / 2, my = (b + d) / 2, turn = Math.atan2(b - d, a - c), s = 6 * dpr;
      ctx.beginPath(); ctx.arc(a, b, (sel ? 4 : 2.5) * dpr, 0, Math.PI * 2); ctx.fill();
      if (Math.hypot(a - c, b - d) < 30 * dpr) return;  // no room for an arrow
      ctx.beginPath(); ctx.moveTo(mx + Math.cos(turn) * s, my + Math.sin(turn) * s);
      ctx.lineTo(mx + Math.cos(turn + 2.5) * s, my + Math.sin(turn + 2.5) * s);
      ctx.lineTo(mx + Math.cos(turn - 2.5) * s, my + Math.sin(turn - 2.5) * s); ctx.fill();
    });
    ctx.restore();
  }
}

function edPlayerPos(p) {
  const pl = edEdits().player;
  return pl ? { ...p, ...pl } : p;
}

function edMarker(u, pos, dpr) {
  const { ctx } = ED;
  const [sx, sy] = edToScreen(pos.x, pos.z, pos.y);
  const side = edSide(u);
  const editable = u.edit || u.added || u.player;
  if (u.moved && !u.removed) {  // where the unit was in the scenario
    const [ox, oy] = edToScreen(u.ox, u.oz);
    ctx.save(); ctx.setLineDash([3 * dpr, 4 * dpr]); ctx.strokeStyle = 'rgba(255,255,255,.55)'; ctx.lineWidth = 1.5 * dpr;
    ctx.beginPath(); ctx.moveTo(ox, oy); ctx.lineTo(sx, sy); ctx.stroke();
    ctx.beginPath(); ctx.arc(ox, oy, 3 * dpr, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
  }
  const r = (editable ? 7 : 3.5) * dpr;
  const color = ED_COLORS[side];
  ctx.save();
  ctx.globalAlpha = u.removed ? 0.35 : editable ? 1 : 0.85;
  ctx.fillStyle = color;
  ctx.strokeStyle = u.added ? '#fff' : 'rgba(0,0,0,.75)';
  ctx.lineWidth = (u.added ? 2 : editable ? 1 : 1.2) * dpr;
  if (u.player) { ctx.beginPath(); ctx.arc(sx, sy, r + 2 * dpr, 0, Math.PI * 2); }
  else edShape(u.block, sx, sy, r);  // scenery / objects: a small one with a dark outline, readable on any terrain
  ctx.fill(); ctx.stroke();
  if (editable && !u.player && !u.tpl && !u.removed) {  // the way it faces
    const tip = edHeadingTip(u, dpr), a = Math.atan2(tip.ty - tip.sy, tip.tx - tip.sx);
    ctx.save(); ctx.strokeStyle = color; ctx.lineWidth = 2 * dpr; ctx.beginPath();
    ctx.moveTo(sx + Math.cos(a) * r, sy + Math.sin(a) * r); ctx.lineTo(sx + Math.cos(a) * (r + 7 * dpr), sy + Math.sin(a) * (r + 7 * dpr));
    ctx.stroke(); ctx.restore();
  }
  if (u.removed) {
    ctx.strokeStyle = '#fff'; ctx.lineWidth = 2 * dpr; ctx.beginPath();
    ctx.moveTo(sx - r, sy - r); ctx.lineTo(sx + r, sy + r); ctx.moveTo(sx + r, sy - r); ctx.lineTo(sx - r, sy + r); ctx.stroke();
  }
  if (u.behavior === 'stay' && !u.removed) {
    ctx.fillStyle = '#fff'; ctx.fillRect(sx - 2 * dpr, sy - 2 * dpr, 4 * dpr, 4 * dpr);
  }
  if (u.loadout && !u.removed) {  // its own loadout
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(sx + r * 0.9, sy - r * 0.9, 2.5 * dpr, 0, Math.PI * 2); ctx.fill();
  }
  if (u.wave && !u.removed) {  // its wave
    ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.arc(sx - r, sy - r, 6.5 * dpr, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = '#14171c'; ctx.font = `700 ${10 * dpr}px system-ui, sans-serif`; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillText(u.wave, sx - r, sy - r + 0.5 * dpr);
  }
  if (edIsSelected(u)) {
    ctx.globalAlpha = 1;
    ctx.strokeStyle = ED_COLORS.player; ctx.lineWidth = 2 * dpr; ctx.beginPath(); ctx.arc(sx, sy, r + 6 * dpr, 0, Math.PI * 2); ctx.stroke();
  }
  ctx.restore();
}
function edMarkerLabel(u, pos, dpr) {
  const editable = u.edit || u.added || u.player;
  if (!editable || (!u.player && !edIsSelected(u) && ED.view.scale * 300 < 40 * dpr)) return;
  const [sx, sy] = edToScreen(pos.x, pos.z);
  const r = 7 * dpr;
  const label = u.player ? t('editor.you') : I18N.unit(u.cls) + (u.count > 1 ? ` ×${u.count}` : '');
  edPill(label, sx + r + 4 * dpr, sy, u.removed ? 'rgba(255,255,255,.45)' : u.player ? ED_COLORS.player : '#f2f4f7', dpr,
    { force: u.player || edIsSelected(u) });
}

// ------------------------------------------------------------------ interaction
function edHit(sx, sy, { all = false } = {}) {
  const dpr = window.devicePixelRatio || 1;
  let best = null, bd = (all ? 10 : 14) * dpr;
  for (const u of edAllPoints().map(edUnitState)) {
    if (!all && !(u.edit || u.added || u.player)) continue;
    if (all && !ED.scenery && !(u.edit || u.added || u.player)) continue;
    const pos = u.player ? edPlayerPos(u) : u;
    const [x, y] = edToScreen(pos.x, pos.z);
    const d = Math.hypot(x - sx, y - sy);
    if (d < bd) { bd = d; best = u; }
  }
  return best;
}

function edCanvasPoint(ev) {
  const rect = ED.canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  return [(ev.clientX - rect.left) * dpr, (ev.clientY - rect.top) * dpr];
}

// what is under the pointer, in plain words
function edTip(ev, sx, sy) {
  const tip = $('#edTip');
  const u = edHit(sx, sy, { all: true });
  const z = u ? null : edHitZone(sx, sy);
  if (!u && !z) { tip.classList.add('hidden'); return; }
  if (u) {
    const side = edSide(u);
    const sideTxt = t({ player: 'editor.you', enemy: 'editor.enemy', ally: 'editor.ally', other: 'editor.scenery' }[side]);
    tip.innerHTML = `<b>${esc(u.player ? t('editor.playerStart') : edUnitName(u.cls))}${u.count > 1 ? ` ×${u.count}` : ''}</b>
      <span><i class="dot ${side}"></i>${esc(sideTxt)}${u.name && !u.player ? ' · ' + esc(u.name) : ''}${u.tpl ? ' · ' + esc(t('editor.tpl')) : ''}</span>`;
  } else {
    const info = edZoneInfo(z);
    tip.innerHTML = `<b>${esc(edZoneLabel(z, info))}</b><span>${esc(t('editor.zone'))} · ${esc(z.name)}</span>`;
  }
  const rect = ED.canvas.getBoundingClientRect();
  tip.style.left = Math.min(ev.clientX - rect.left + 14, rect.width - 260) + 'px';
  tip.style.top = (ev.clientY - rect.top + 16) + 'px';
  tip.classList.remove('hidden');
}

// ground height of the level (decoded from the game's heightmap by the server), when it has one
async function edLoadTerrain(level) {
  try {
    const meta = await api('terrain/' + encodeURIComponent(level || ''));
    if (!meta.available) return;
    const buf = await (await fetch(meta.url)).arrayBuffer();
    if (ED.data?.level !== level) return;
    ED.terrain = { ...meta, grid: new Uint16Array(buf) };
    edRenderPanel();
  } catch { /* no terrain: heights are estimated */ }
}

function edGround(x, z) {
  const T = ED.terrain;
  if (!T) return null;
  const fx = (x - T.ofs[0]) / T.cell, fz = (z - T.ofs[1]) / T.cell;
  const i = Math.floor(fx), j = Math.floor(fz);
  if (i < 0 || j < 0 || i >= T.w - 1 || j >= T.h - 1) return null;
  const tx = fx - i, tz = fz - j, g = T.grid, w = T.w;
  const v = (g[j * w + i] * (1 - tx) + g[j * w + i + 1] * tx) * (1 - tz) + (g[(j + 1) * w + i] * (1 - tx) + g[(j + 1) * w + i + 1] * tx) * tz;
  return T.hmin + v * T.hscale / 65535;
}

function edGroundY(x, z) {
  const g = edGround(x, z);
  if (g != null) return g + 0.5;  // on the ground (+0.5 m so the vehicle settles on it)
  // no heightmap: the nearest known ground-level unit gives the terrain height (+1 m)
  let best = null, bd = Infinity;
  for (const u of ED.data.units) {
    if (u.block === 'armada') continue;
    const d = Math.hypot(u.x - x, u.z - z);
    if (d < bd) { bd = d; best = u; }
  }
  return best ? best.y + 1 : 50;
}

// places ED.addN new units, side by side across the way they face (towards you)
function edAdd(x, z) {
  const e = edEdits();
  const block = ED.addBlock;
  const player = ED.data.units.find(u => u.player);
  const defaultCls = { tankModels: S.cfg.vehicle && S.byId.get(S.cfg.vehicle)?.c === 'ground' ? S.cfg.vehicle : 'ussr_t_72a',
    armada: 'mig-21_mf', ships: 'us_destroyer_fletcher', objectGroups: 'ammunition_box_a' }[block];
  const yaw = player ? Math.atan2(player.z - z, player.x - x) * 180 / Math.PI : 0;
  const n = Math.max(1, Math.min(20, +ED.addN || 1)), sp = ED_SPACING[block], a = yaw * Math.PI / 180;
  const keys = [];
  for (let i = 0; i < n; i++) {
    const off = (i - (n - 1) / 2) * sp;
    const px = x - Math.sin(a) * off, pz = z + Math.cos(a) * off;
    const y = block === 'armada' ? Math.max((player?.y || 0) + 800, (edGround(px, pz) ?? 0) + 800) : block === 'ships' ? 0 : Math.round(edGroundY(px, pz) * 10) / 10;
    e.add.push({ block, cls: defaultCls, x: Math.round(px), y: Math.round(y), z: Math.round(pz), yaw: Math.round(yaw), count: 1, attack: 'fire_at_will', behavior: '', speed: 450, side: ED.addSide });
    keys.push('add:' + (e.add.length - 1));
  }
  edSelect(keys);
  ED.mode = 'select';
}

// moves your start to x, z (height: on the ground, or in the air for an air start)
function edMovePlayer(x, z) {
  const e = edEdits();
  const p = ED.data.units.find(u => u.player);
  if (!p) return;
  const onGround = S.cfg.block === 'tankModels' && edGround(x, z) != null;
  let y = onGround ? Math.round(edGroundY(x, z) * 10) / 10 : (e.player?.y ?? p.y);
  // an aircraft moved off its runway starts in the air
  if (S.cfg.block === 'armada' && !e.player) y = Math.max(y, Math.round((edGround(x, z) ?? p.y) + (S.cfg.altitude || 1000)));
  const s = edStart();
  if (s && edFlyer()) y = s.air ? Math.max(y, Math.round((edGround(x, z) ?? 0) + 100)) : Math.round(edGroundY(x, z) * 10) / 10;
  e.player = { ...(e.player || {}), x: Math.round(x), y, z: Math.round(z), yaw: e.player?.yaw ?? Math.round(p.yaw || 0),
    ...(edFlyer() ? { mode: s?.air ? 'air' : 'ground', speed: s?.speed ?? 450 } : {}) };
}
function edPanKeys(now) {
  if (!ED.keys.size) { ED.panAt = 0; return; }
  const yaw = M3.on ? M3.yaw : 0, c = Math.cos(yaw), s = Math.sin(yaw);
  const step = Math.min((now - (ED.panAt || now)) / 1000, 0.05) * 0.6 * ED.canvas.height / ED.view.scale;
  ED.panAt = now;
  for (const code of ED.keys) {
    const [right, up] = ED_PAN_KEYS[code];
    ED.view.cx += (right * c - up * s) * step;
    ED.view.cz += (right * s + up * c) * step;
  }
  edDraw();
  requestAnimationFrame(edPanKeys);
}

// moves a unit (added or the scenario's) to x, z: ground units stay on the ground
function edMoveUnit(u, x, z) {
  const e = edEdits();
  if (u.added) {
    const a = e.add[u.idx];
    a.x = Math.round(x); a.z = Math.round(z);
    if (a.block !== 'armada' && a.block !== 'ships') a.y = Math.round(edGroundY(x, z) * 10) / 10;
  } else {
    edSet(u, { x: Math.round(x), z: Math.round(z), ...(u.block === 'tankModels' ? { y: Math.round(edGroundY(x, z) * 10) / 10 } : {}) });
  }
}

function edBind() {
  const cv = $('#edCanvas');
  edBindMenu();
  cv.addEventListener('pointerdown', ev => {
    if (ev.button === 2) {  // the right button opens the menu (edBindMenu); in 3D, dragged, it turns the view
      if (M3.on) { cv.setPointerCapture(ev.pointerId); M3.orbit = { x: ev.clientX, y: ev.clientY, moved: false }; }
      return;
    }
    const [sx, sy] = edCanvasPoint(ev);
    clearTimeout(ED.glide);  // the map is the user's again
    cv.setPointerCapture(ev.pointerId);
    $('#edTip').classList.add('hidden');
    if (ED.placing) {  // drops the copied units here
      edPaste(...edToWorld(sx, sy));
      edPlacing(false);
      edRenderPanel(); edDraw();
      return;
    }
    if (ED.mode === 'add') {
      const [x, z] = edToWorld(sx, sy);
      edAdd(x, z);
      edRenderPanel(); edDraw();
      return;
    }
    if (ED.mode === 'route') {
      const i = edRouteHit(sx, sy);
      if (i >= 0) ED.drag = { kind: 'way', i, moved: false };
      else edRoutePoint(...edToWorld(sx, sy));
      edRenderPanel(); edDraw();
      return;
    }
    const scale = window.devicePixelRatio || 1, near = tip => Math.hypot(tip.tx - sx, tip.ty - sy) < 12 * scale;
    const start = ED.sel?.player ? edArrowTip(scale) : null, grip = edTurnable().map(edUnitState).find(st => near(edHeadingTip(st, scale)));
    if (grip || (start && near(start))) {
      ED.drag = { kind: 'turn', grip, moved: false };
      return;
    }
    const add = ev.ctrlKey || ev.metaKey || ev.shiftKey;
    const hit = edHit(sx, sy);
    if (hit && add && !hit.player) {  // Ctrl / Shift + click: one more (or one less) in the selection
      edToggle(edKey(hit));
      ED.drag = null;
      edRenderPanel(); edDraw();
      return;
    }
    const zone = hit || add ? null : edHitZone(sx, sy);
    if (hit && !hit.player && ED.multi.includes(edKey(hit))) {  // drag the whole selection
      const [wx, wz] = edToWorld(sx, sy);
      const items = edSelUnits().map(edUnitState).filter(edMovable).map(u => ({ u, x: u.x, z: u.z }));
      ED.drag = { kind: 'group', wx, wz, items, moved: false };
    } else if (hit) {
      ED.sel = hit.player ? { player: true } : { key: edKey(hit) };
      ED.multi = [];
      ED.search = '';
      ED.drag = edMovable(hit) || hit.player ? { kind: 'unit', u: hit, moved: false } : null;
      edRenderPanel(); edDraw();
    } else if (add) {  // Shift / Ctrl + drag on the map: select an area
      ED.drag = { kind: 'box', sx, sy, x2: sx, y2: sy, keep: edSelKeys(), moved: false };
    } else if (zone) {
      ED.sel = { zone: zone.name };
      ED.multi = [];
      ED.drag = { kind: 'zone', z: zone, moved: false };
      edRenderPanel(); edDraw();
    } else {
      ED.drag = { kind: 'pan', sx, sy, cx: ED.view.cx, cz: ED.view.cz, moved: false };
    }
  });
  cv.addEventListener('pointermove', ev => {
    const [sx, sy] = edCanvasPoint(ev);
    if (M3.orbit) {
      if (Math.hypot(ev.clientX - M3.orbit.x, ev.clientY - M3.orbit.y) > 2) M3.orbit.moved = true;
      M3.yaw += (ev.clientX - M3.orbit.x) * 0.006;
      M3.pitch = Math.max(M3_PITCH[1], Math.min(M3_PITCH[0], M3.pitch + (ev.clientY - M3.orbit.y) * 0.005));
      M3.orbit.x = ev.clientX; M3.orbit.y = ev.clientY;
      edDraw();
      return;
    }
    ED.mouse = edToWorld(sx, sy);
    if (!ED.drag) { if (ED.placing) edDraw(); else edTip(ev, sx, sy); return; }
    if (ED.drag.kind === 'pan') {
      if (Math.hypot(sx - ED.drag.sx, sy - ED.drag.sy) > 4 * (window.devicePixelRatio || 1)) ED.drag.moved = true;
      if (M3.on) m3Pan(ED.drag, sx, sy);
      else {
        ED.view.cx = ED.drag.cx - (sx - ED.drag.sx) / ED.view.scale;
        ED.view.cz = ED.drag.cz + (sy - ED.drag.sy) / ED.view.scale;
      }
    } else if (ED.drag.kind === 'box') {
      Object.assign(ED.drag, { x2: sx, y2: sy, moved: true });
    } else if (ED.drag.kind === 'turn') {
      const p = ED.drag.grip || edStart(), at = M3.on ? m3AtHeight(sx, sy, p.y) : edToWorld(sx, sy);
      if (at) {
        const yaw = (Math.round(Math.atan2(at[1] - p.z, at[0] - p.x) * 180 / Math.PI) + 360) % 360;
        if (ED.drag.grip) edTurnable().forEach(u => edSet(u, { yaw })); else edSetStart({ yaw });
      }
      ED.drag.moved = true;
    } else if (ED.drag.kind === 'zone') {
      const [x, z] = edToWorld(sx, sy);
      edEdits().areas[ED.drag.z.name] = { x: Math.round(x), z: Math.round(z) };
      ED.drag.moved = true;
    } else if (ED.drag.kind === 'way') {
      edRouteMove(ED.drag.i, ...edToWorld(sx, sy));
      ED.drag.moved = true;
    } else if (ED.drag.kind === 'group') {
      const [x, z] = edToWorld(sx, sy);
      const dx = x - ED.drag.wx, dz = z - ED.drag.wz;
      for (const it of ED.drag.items) edMoveUnit(it.u, it.x + dx, it.z + dz);
      ED.drag.moved = true;
    } else {
      const [x, z] = edToWorld(sx, sy);
      if (ED.drag.u.player) edMovePlayer(x, z);
      else edMoveUnit(ED.drag.u, x, z);
      ED.drag.moved = true;
    }
    edDraw();
  });
  cv.addEventListener('pointerup', () => {
    if (M3.orbit && !M3.orbit.moved) M3.orbit = null;  // a plain right click: the menu follows
    const d = ED.drag;
    ED.drag = null;
    if (d?.kind === 'box') {
      if (d.moved) {
        const [x0, x1] = [Math.min(d.sx, d.x2), Math.max(d.sx, d.x2)], [y0, y1] = [Math.min(d.sy, d.y2), Math.max(d.sy, d.y2)];
        const inside = edAllPoints().map(edUnitState).filter(u => (u.edit || u.added) && !u.player).filter(u => {
          const [x, y] = edToScreen(u.x, u.z);
          return x >= x0 && x <= x1 && y >= y0 && y <= y1;
        });
        edSelect([...d.keep, ...inside.map(edKey)]);
      }
      edRenderPanel(); edDraw();
    } else if (d?.kind === 'pan' && !d.moved) {  // a click on the map itself: nothing selected any more
      if (ED.sel || ED.multi.length) { edSelect([]); edRenderPanel(); edDraw(); }
    } else if (d?.moved) edRenderPanel();
  });
  cv.addEventListener('pointerenter', () => { ED.over = true; });
  cv.addEventListener('pointerleave', () => { ED.over = false; $('#edTip').classList.add('hidden'); if (ED.placing) edDraw(); });
  cv.addEventListener('wheel', ev => {
    ev.preventDefault();
    clearTimeout(ED.glide);
    const [sx, sy] = edCanvasPoint(ev);
    const [wx, wz] = edToWorld(sx, sy);
    ED.view.scale *= ev.deltaY < 0 ? 1.18 : 1 / 1.18;
    const [nx, nz] = edToWorld(sx, sy);
    ED.view.cx += wx - nx; ED.view.cz += wz - nz;
    edDraw();
  }, { passive: false });
  window.addEventListener('resize', () => { if ($('#dlgEditor').open) { edResize(); edDraw(); } });

  $('#edPanel').addEventListener('click', ev => { edPanelClick(ev); });
  $('#edPanel').addEventListener('change', edPanelChange);
  $('#edPanel').addEventListener('toggle', ev => { if (ev.target.classList?.contains('ed-auto')) ED.auto.open = ev.target.open; }, true);
  $('#edPanel').addEventListener('input', ev => {
    if (ev.target.id === 'edSearch') { ED.search = ev.target.value; edRenderResults(); }
    if (ev.target.dataset.edvfn) {  // BR range (dual slider): the list follows while dragging
      const box = ev.target.closest('.range'), f = ED.vf ||= edVfReset();
      let [a, b] = [...box.querySelectorAll('input')].map(i => +i.value);
      if (a > b) [a, b] = [b, a];
      Object.assign(f, { brMin: a, brMax: b });
      const pct = x => ((x - BR_MIN) / (BR_MAX - BR_MIN)) * 100;
      Object.assign($('#edBrFill').style, { left: pct(a) + '%', right: (100 - pct(b)) + '%' });
      $('#edBrMinLabel').textContent = a.toFixed(1); $('#edBrMaxLabel').textContent = b.toFixed(1);
      edRenderResults();
    }
    if (ev.target.dataset.edautof === 'br') ev.target.nextElementSibling.textContent = `BR ${(+ev.target.value).toFixed(1)}`;
    if (['pyaw', 'uyaw'].includes(ev.target.dataset.edf)) {  // the arrow turns with the slider
      const yaw = edYaw(+ev.target.value);
      if (ev.target.dataset.edf === 'pyaw') edSetStart({ yaw }); else edTurnable().forEach(u => edSet(u, { yaw }));
      ev.target.nextElementSibling.textContent = `${ev.target.value}° ${edCardinal(+ev.target.value)}`;
      edDraw();
    }
  });
  $('#ed3d').addEventListener('change', () => { m3Toggle(); edDraw(); });
  $('#edAddN').addEventListener('change', ev => { ED.addN = Math.max(1, Math.min(20, +ev.target.value || 1)); ev.target.value = ED.addN; });
  $('#edTools').addEventListener('click', ev => {
    const b = ev.target.closest('button'); if (!b) return;
    if (b.dataset.edmode) { ED.mode = b.dataset.edmode; if (b.dataset.block) ED.addBlock = b.dataset.block; }
    if (b.dataset.edside) ED.addSide = b.dataset.edside;
    if (b.dataset.edact === 'fit') edFit();
    if (b.dataset.edact === 'fitMap') edFitMap();
    if (b.dataset.edact === 'reset') { S.cfg.edits = { sid: S.cfg.scenario, units: {}, add: [], areas: {} }; edSelect([]); }
    if (b.dataset.edact === 'zones') { ED.zones = !ED.zones; if (!ED.zones && ED.sel?.zone && !edZoneItems(window.devicePixelRatio || 1).some(i => i.z0.name === ED.sel.zone)) ED.sel = null; }
    if (b.dataset.edact === 'scenery') ED.scenery = !ED.scenery;
    if (b.dataset.edact === 'paste') edPlacing(true);
    edRenderPanel(); edDraw();
  });
  $('#edDone').addEventListener('click', () => { $('#dlgEditor').close(); edRestoreHidden(); });
  $('#edCancel').addEventListener('click', () => {  // the map as it was when the editor opened
    if (ED.before) S.cfg.edits = JSON.parse(ED.before); else delete S.cfg.edits;
    edPlacing(false);
    $('#dlgEditor').close();
    edRestoreHidden();
  });
  $('#dlgEditor').addEventListener('keydown', ev => {
    if (ev.target.closest('input, select, textarea')) return;
    const mod = ev.ctrlKey || ev.metaKey, k = ev.key.toLowerCase();
    if (!mod && ED_PAN_KEYS[ev.code]) {
      if (!ED.keys.size) requestAnimationFrame(edPanKeys);
      ED.keys.add(ev.code);
      ev.preventDefault();
      return;
    }
    if (mod && k === 'c') { if (edCopy()) toast({ title: t('editor.copied', { n: ED.clip.length }), ms: 2000 }); }
    else if (mod && k === 'v') { edPasteHere(); }
    else if (mod && k === 'd') { edDuplicate(); }
    else if (mod && k === 'a') { edSelect(edAllPoints().map(edUnitState).filter(u => (u.edit || u.added) && !u.player).map(edKey)); }
    else if (k === 'escape' && ED.placing) { edPlacing(false); }
    else if (k === 'escape' && ED.mode === 'route') { ED.mode = 'select'; }
    else if (ED.mode === 'route' && ['delete', 'backspace'].includes(k)) { edRouteBack(); }
    else if (k === 'escape' && (ED.sel || ED.multi.length)) { edSelect([]); }
    else if (['delete', 'backspace'].includes(k)) {
      const us = edSelUnits();
      if (!us.length) return;
      if (us.length === 1 && !us[0].added && edUnitState(us[0]).removed) edSet(us[0], { remove: false });
      else edRemoveUnits(us);
      if (us.length === 1 && us[0].added) edSelect([]);
    } else return;
    ev.preventDefault();
    edRenderPanel(); edDraw();
  });
  window.addEventListener('keyup', ev => ED.keys.delete(ev.code));
  window.addEventListener('blur', () => ED.keys.clear());
  $('#dlgEditor').addEventListener('close', () => {
    ED.keys.clear();
    if (ED.configuring) return;
    if (M3.on) m3Toggle();
    if (S.sel) renderDrawer();
    edRestoreHidden();
  });
}

// ------------------------------------------------------------------ right click: what can be done right there
// the items for what is under the pointer (a unit, the selection, your start, a zone or the map at x, z)
function edMenuItems(sx, sy) {
  const [x, z] = edToWorld(sx, sy);
  const hit = edHit(sx, sy), zone = hit ? null : edHitZone(sx, sy);
  const items = [], sep = () => items.length && items[items.length - 1] !== '-' && items.push('-');
  const redraw = () => { edRenderPanel(); edDraw(); };
  const copy = () => { if (edCopy()) toast({ title: t('editor.copied', { n: ED.clip.length }), ms: 2000 }); };
  if (hit?.player) {
    ED.sel = { player: true }; ED.multi = [];
    if (edFlyer()) {
      const s = edStart();
      for (const [mode, key] of [['ground', 'editor.startGround'], ['air', 'editor.startAir']]) {
        items.push({ label: t(key), on: s.air === (mode === 'air'), run: () => {
          const g = edGround(s.x, s.z), air = mode === 'air';
          edSetStart({ mode, y: air ? Math.max(s.y, Math.round((g ?? s.y) + (S.cfg.altitude || 1500))) : Math.round(edGroundY(s.x, s.z) * 10) / 10, speed: air ? (s.speed || 450) : 0 });
        } });
      }
    }
    if (edEdits().player) { sep(); items.push({ label: t('mods.reset'), icon: 'refresh', run: () => { delete edEdits().player; } }); }
  } else if (hit) {
    if (!edSelKeys().includes(edKey(hit))) edSelect([edKey(hit)]);  // right click on a unit selects it, as on a desktop
    const us = edSelUnits(), sts = us.map(edUnitState);
    const canCopy = sts.some(u => !u.removed && (u.added || ED_ADD_BLOCK[u.block]));
    if (us.length === 1) {
      const u = us[0], st = sts[0], side = edSide(st);
      if (!st.removed && edSwappable(u) && S.byId.get(st.cls)) items.push({ label: t('editor.configure') + ' · ' + t('editor.loadout'), icon: 'sliders', run: () => edConfigure(edKey(u)) });
      if (!st.removed && !u.tpl) {
        sep();
        for (const sd of ['enemy', 'ally']) items.push({ label: t('editor.' + sd), dot: sd, on: side === sd, run: () => {
          const beh = edUnitState(u).behavior;
          const keep = !(beh === 'hunt' && sd === 'ally') && !(beh === 'follow' && sd === 'enemy');
          edSet(u, { side: sd, ...(keep ? {} : { behavior: '' }) });
        } });
      }
      if (!st.removed) {
        sep();
        for (const [beh, key] of edBehaviors(side, u.block === 'armada', u.added)) items.push({ label: t(key), on: (st.behavior || '') === beh, run: () => edSet(u, { behavior: beh }) });
      }
    } else {
      sep();
      for (const sd of ['enemy', 'ally']) items.push({ label: t('editor.' + sd), dot: sd, run: () => edMultiClick({ dataset: { edmside: sd } }) });
    }
    sep();
    if (canCopy) {
      items.push({ label: t('editor.copy'), key: 'Ctrl+C', run: copy });
      items.push({ label: t('editor.duplicate'), key: 'Ctrl+D', run: edDuplicate });
    }
    if (us.length === 1 && sts[0].moved && !us[0].added) items.push({ label: t('editor.resetPos'), icon: 'refresh', run: () => edSet(us[0], { x: null, y: null, z: null }) });
    sep();
    if (sts.some(u => u.removed && !u.added)) items.push({ label: t('editor.restore'), icon: 'refresh', run: () => { for (const u of us) if (!u.added) edSet(u, { remove: false }); } });
    if (sts.some(u => !u.removed)) items.push({ label: t(us.length === 1 && us[0].added ? 'action.delete' : us.length > 1 ? 'editor.removeSel' : 'editor.remove'), icon: 'trash', key: 'Del', danger: true,
      run: () => { const added = us.length === 1 && us[0].added; edRemoveUnits(us.filter(u => u.added || !edUnitState(u).removed)); if (added) edSelect([]); } });
    if (us.length > 1) items.push({ label: t('editor.clearSel'), icon: 'x', key: 'Esc', run: () => edSelect([]) });
  } else {
    if (zone) {
      ED.sel = { zone: zone.name }; ED.multi = [];
      if (edEdits().areas[zone.name]) { items.push({ label: t('mods.reset') + ' · ' + t('editor.zone'), icon: 'refresh', run: () => { delete edEdits().areas[zone.name]; } }); sep(); }
    }
    if (ED.clip?.length) items.push({ label: t('editor.menu.pasteHere'), key: 'Ctrl+V', run: () => edPaste(x, z) });
    sep();
    for (const [block, key, ic] of [['tankModels', 'editor.menu.addGround', 'ground'], ['armada', 'editor.menu.addAir', 'air'], ['ships', 'editor.menu.addShip', 'ship'], ['objectGroups', 'editor.menu.addAsset', 'cube']]) {
      items.push({ label: t(key), icon: ic, dot: ED.addSide, run: () => { const b = ED.addBlock; ED.addBlock = block; edAdd(x, z); ED.addBlock = b; } });
    }
    if (ED.data.units.some(u => u.player)) { sep(); items.push({ label: t('editor.menu.startHere'), dot: 'player', run: () => { edMovePlayer(x, z); ED.sel = { player: true }; ED.multi = []; } }); }
    sep();
    items.push({ label: t('editor.menu.center'), run: () => { ED.view.cx = x; ED.view.cz = z; } });
    items.push({ label: t('editor.fit'), run: edFit });
    if (ED.layers.length) items.push({ label: t('editor.fitMap'), run: edFitMap });
  }
  if (items[items.length - 1] === '-') items.pop();
  return items.map(it => (it === '-' ? it : { ...it, run: () => { it.run(); redraw(); } }));
}
function edOpenMenu(ev) {
  ev.preventDefault();
  if (M3.orbit) { M3.orbit = null; return; }  // the end of turning the 3D view
  if (ED.mode === 'route') { ED.mode = 'select'; edRenderPanel(); edDraw(); return; }
  edPlacing(false);
  $('#edTip').classList.add('hidden');
  const [sx, sy] = edCanvasPoint(ev);
  const items = edMenuItems(sx, sy);
  edRenderPanel(); edDraw();  // what the menu acts on is now selected
  const menu = $('#edMenu');
  ED.menu = items;
  menu.innerHTML = items.map((it, i) => (it === '-' ? '<hr>' : `<button data-mi="${i}" class="${it.danger ? 'danger' : ''}${it.on ? ' on' : ''}">
      <span class="ed-mi-ic">${it.dot ? `<i class="dot ${it.dot}"></i>` : it.icon ? icon(it.icon, 'ic-sm') : it.on ? icon('check', 'ic-sm') : ''}</span>
      <span>${esc(it.label)}</span>${it.on && it.dot ? icon('check', 'ic-sm') : ''}${it.key ? `<kbd>${esc(it.key)}</kbd>` : ''}</button>`)).join('');
  menu.classList.remove('hidden');
  const box = menu.parentElement.getBoundingClientRect(), mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = Math.max(4, Math.min(ev.clientX - box.left, box.width - mw - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(ev.clientY - box.top, box.height - mh - 4)) + 'px';
  menu.querySelector('button')?.focus({ preventScroll: true });
}
const edCloseMenu = () => { $('#edMenu')?.classList.add('hidden'); ED.menu = null; };
function edBindMenu() {
  const menu = $('#edMenu');
  $('#edCanvas').addEventListener('contextmenu', edOpenMenu);
  menu.addEventListener('contextmenu', ev => ev.preventDefault());
  menu.addEventListener('click', ev => {
    const b = ev.target.closest('button[data-mi]');
    if (!b) return;
    const it = ED.menu?.[+b.dataset.mi];
    edCloseMenu();
    it?.run();
  });
  menu.addEventListener('keydown', ev => {
    const bs = [...menu.querySelectorAll('button')], i = bs.indexOf(document.activeElement);
    if (ev.key === 'ArrowDown' || ev.key === 'ArrowUp') { ev.preventDefault(); ev.stopPropagation(); bs[(i + (ev.key === 'ArrowDown' ? 1 : bs.length - 1)) % bs.length]?.focus(); }
    else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopPropagation(); edCloseMenu(); }
  });
  document.addEventListener('pointerdown', ev => { if (ED.menu && !menu.contains(ev.target)) edCloseMenu(); }, true);
  $('#edCanvas').addEventListener('wheel', edCloseMenu, { passive: true });
  $('#dlgEditor').addEventListener('close', edCloseMenu);
}

// ------------------------------------------------------------------ vehicles by BR
// every unit gets a vehicle of its own kind (fighter, bomber, tank, SPAA…) at the BR closest to the one
// chosen (your vehicle's, or any), of the nations picked (none: all), one nation after the other
const ED_AUTO_KINDS = { ground: ['tank', 'heavy_tank', 'tank_destroyer'], air: ['fighter', 'assault', 'bomber'], heli: ['helicopter'],
  ship: ['destroyer', 'cruiser'], boat: ['torpedo_boat', 'gun_boat', 'torpedo_gun_boat', 'submarine_chaser'] };
const edBR = v => v?.br?.[1];
// vehicles of the research trees (not killstreak, event or test ones)
let edTreeSet = null;
function edTreeIds() {
  if (edTreeSet) return edTreeSet;
  edTreeSet = new Set();
  const walk = n => { if (Array.isArray(n)) n.forEach(walk); else if (n && typeof n === 'object') { if (typeof n.id === 'string') edTreeSet.add(n.id); Object.values(n).forEach(walk); } };
  walk(S.trees || {});
  return edTreeSet;
}
const edMyBR = () => edBR(S.byId.get(S.cfg?.vehicle));
function edAutoBR() { return ED.auto.src === 'me' && edMyBR() ? edMyBR() : +ED.auto.br; }
// the units it applies to: the selection, or every unit of a side
function edAutoUnits(selection) {
  // every unit, those the scenario places in game too (not drawn, their vehicle can still change)
  const us = selection ? edSelUnits() : [...ED.data.units, ...edEdits().add.map((a, idx) => ({ ...a, added: true, idx }))]
    .filter(u => (u.edit || u.added) && !u.player);
  return us.filter(u => {
    const st = edUnitState(u);
    if (st.removed || !edSwappable(u) || !ED_BLOCK_CATS[u.block]) return false;
    return selection || ED.auto.who === 'all' || edSide(st) === ED.auto.who;
  });
}
// gives the units vehicles near br; follow: they keep following your vehicle's BR (edAutoRefresh)
function edAutoPick(units, br, nations, follow, fire = '') {
  const groups = new Map();  // same kind of vehicle: picked in turn among the closest
  for (const u of units) {
    const cur = S.byId.get(edUnitState(u).cls);
    const c = cur && ED_BLOCK_CATS[u.block].includes(cur.c) ? cur.c : ED_BLOCK_CATS[u.block][0];
    const k = cur?.k && (ED_AUTO_KINDS[c] || []).concat(['SPAA']).includes(cur.k) ? cur.k : '';
    const key = c + '|' + k;
    if (!groups.has(key)) groups.set(key, { c, k, units: [] });
    groups.get(key).units.push(u);
  }
  let n = 0;
  const tree = edTreeIds();
  for (const { c, k, units: us } of groups.values()) {
    const kinds = k ? [k] : ED_AUTO_KINDS[c] || [];
    // vehicles that fire on their own: armed, not a SAM battery's radar ("<x>_fcs", the slot) or launcher
    // (AI ones don't fire, even with the battery's radar next to them: checked in game)
    const cands = S.vehicles.filter(v => v.c === c && !v.h && edBR(v) && (!tree.size || tree.has(v.id)) && (v.wg?.length || v.wp?.length) && !/_(launcher|fcs)$/.test(v.id)
      && (!nations.length || nations.includes(v.n)) && (!kinds.length || kinds.includes(v.k)));
    let near = [];
    for (const w of [0.35, 0.7, 1.4, 3, 99]) {
      near = cands.filter(v => Math.abs(edBR(v) - br) <= w);
      if (near.length >= Math.min(3, us.length)) break;
    }
    if (!near.length) continue;
    near.sort((a, b) => Math.abs(edBR(a) - br) - Math.abs(edBR(b) - br) || a.id.localeCompare(b.id));
    // several nations: one of each in turn, closest BR first
    let order = near;
    if (nations.length !== 1) {
      const by = new Map();
      for (const v of near) { if (!by.has(v.n)) by.set(v.n, []); by.get(v.n).push(v); }
      order = [];
      while ([...by.values()].some(l => l.length)) for (const l of by.values()) if (l.length) order.push(l.shift());
    }
    us.forEach((u, i) => {
      // Attacks: enemy aircraft also hunt you (on their route they don't engage anyone)
      const hunt = fire === 'fire_at_will' && u.block === 'armada' && edSide(edUnitState(u)) === 'enemy';
      edSet(u, { cls: order[i % order.length].id, auto: follow ? { nations } : null, ...(fire ? { attack: fire } : {}), ...(hunt ? { behavior: 'hunt' } : {}) });
      n++;
    });
  }
  return n;
}
function edAutoApply(selection) {
  const br = edAutoBR(), follow = ED.auto.src === 'me' && !!edMyBR();
  const n = edAutoPick(edAutoUnits(selection), br, ED.auto.nations, follow, ED.auto.fire);
  if (follow) edEdits().autoBR = br;
  toast({ title: t('editor.auto.done', { n, br: br.toFixed(1) }), ms: 2500 });
}
// units that follow your vehicle (chosen with "My vehicle")
function edAutoFollowers() {
  const e = S.cfg?.edits;
  if (!e || !ED.data || e.sid !== ED.data.sid) return [];
  return [...ED.data.units.filter(u => e.units?.[u.name]?.auto), ...(e.add || []).map((a, idx) => ({ ...a, added: true, idx })).filter(a => a.auto)];
}
// when the BR of your vehicle changed since: those units get vehicles near the new one (editor opening,
// mission created); true when they did
async function edAutoRefresh() {
  const e = S.cfg?.edits, br = edMyBR();
  if (!e || e.sid !== S.cfg.scenario || !br || e.autoBR === br) return false;
  if (!Object.values(e.units || {}).some(x => x?.auto) && !(e.add || []).some(a => a.auto)) return false;
  if (ED.data?.sid !== S.cfg.scenario) {  // the scenario's units, as the editor loads them
    let data;
    try { data = await api('scenario-units/' + encodeURIComponent(S.cfg.scenario)); } catch { return false; }
    ED.data = data;
    ED.data.sid = S.cfg.scenario;
    ED.byName = new Map(ED.data.units.map(u => [u.name, u]));
  }
  const byNation = new Map();
  for (const u of edAutoFollowers()) {
    const nats = (u.added ? u.auto : e.units[u.name].auto).nations || [];
    const key = nats.join(',');
    if (!byNation.has(key)) byNation.set(key, { nats, us: [] });
    byNation.get(key).us.push(u);
  }
  let n = 0;
  for (const { nats, us } of byNation.values()) n += edAutoPick(us, br, nats, true);
  e.autoBR = br;
  if (n) toast({ title: t('editor.auto.followed', { n, br: br.toFixed(1) }), ms: 4000 });
  return n > 0;
}
function edAutoHTML(selection) {
  const a = ED.auto, my = edMyBR(), src = a.src === 'me' && my ? 'me' : 'br';
  const n = edAutoUnits(selection).length, follow = edAutoFollowers().length;
  return `<details class="ed-auto"${a.open ? ' open' : ''}><summary>${icon('bolt', 'ic-sm')} ${esc(t('editor.auto.title'))}</summary>
    <p class="hint">${esc(t('editor.auto.hint'))}</p>
    <div class="field"><label>BR</label><div class="seg">
      <button class="${src === 'me' ? 'active' : ''}" data-edauto="src:me"${my ? '' : ' disabled'}>${esc(t('editor.auto.mine', { br: my ? my.toFixed(1) : '–' }))}</button>
      <button class="${src === 'br' ? 'active' : ''}" data-edauto="src:br">${esc(t('editor.auto.custom'))}</button></div>
      ${src === 'me' ? `<small class="muted">${esc(t('editor.auto.followHint'))}</small>` : ''}
      ${src === 'br' ? `<div class="slider-row" style="margin-top:8px"><input type="range" min="1" max="${BR_MAX}" step="0.3" data-edautof="br" value="${+a.br}"><output>BR ${(+a.br).toFixed(1)}</output></div>` : ''}</div>
    <div class="field"><label>${esc(t('editor.auto.nation'))} <span class="muted">· ${esc(a.nations.length ? a.nations.map(nationName).join(', ') : t('editor.auto.allNations'))}</span></label>
      <div class="nations ed-nations${a.nations.length ? ' has-active' : ''}">${NATIONS.map(x => `<button class="nation${a.nations.includes(x) ? ' active' : ''}" data-edauto="nat:${x}" title="${esc(nationName(x))}">
        <img src="${flagImg(x)}" alt=""></button>`).join('')}</div>
      ${a.nations.length ? `<button class="btn btn-ghost btn-sm" data-edauto="natAll">${esc(t('editor.auto.allNations'))}</button>` : ''}</div>
    <div class="field"><label>${esc(t('editor.fire'))}</label><div class="seg">
      ${[['', 'editor.asScenario'], ['fire_at_will', 'editor.fire.aggressive']].map(([k, l]) => `<button class="${(a.fire || '') === k ? 'active' : ''}" data-edauto="fire:${k}">${esc(t(l))}</button>`).join('')}</div>
      <small class="muted">${esc(t('editor.auto.fireHint'))}</small></div>
    ${selection ? '' : `<div class="field"><label>${esc(t('editor.auto.who'))}</label><div class="seg">
      ${[['enemy', 'editor.enemies'], ['ally', 'editor.allies'], ['all', 'editor.auto.all']].map(([k, l]) => `<button class="${a.who === k ? 'active' : ''}" data-edauto="who:${k}">${esc(t(l))}</button>`).join('')}</div></div>`}
    <div class="row gap"><button class="btn btn-sm" data-edauto="apply"${n ? '' : ' disabled'}>${icon('bolt', 'ic-sm')}${esc(t('editor.auto.apply', { n }))}</button>
      ${follow ? `<button class="btn btn-ghost btn-sm" data-edauto="stop">${esc(t('editor.auto.stop'))}</button>` : ''}</div>
    ${follow ? `<p class="hint">${esc(t('editor.auto.following', { n: follow }))}</p>` : ''}
  </details>`;
}
// a click in the block: true when handled
function edAutoClick(b) {
  const v = b.dataset.edauto;
  if (!v) return false;
  if (v === 'apply') edAutoApply(ED.multi.length > 0);
  else if (v === 'natAll') ED.auto.nations = [];
  else if (v.startsWith('nat:')) {  // one more nation, or one less
    const x = v.slice(4), l = ED.auto.nations;
    ED.auto.nations = l.includes(x) ? l.filter(y => y !== x) : [...l, x];
  }
  else if (v === 'stop') for (const u of edAutoFollowers()) edSet(u, { auto: null });
  else { const [k, x] = v.split(':'); ED.auto[k] = x; }
  edRenderPanel(); edDraw();
  return true;
}

// ------------------------------------------------------------------ side panel
function edSelected() {
  if (!ED.sel) return null;
  if (ED.sel.player) return ED.data.units.find(u => u.player);
  if (!ED.sel.key) return null;
  return edUnitByKey(ED.sel.key);
}

function edSet(u, patch) {
  const e = edEdits();
  if ('cls' in patch && !('loadout' in patch) && patch.cls !== edUnitState(u).cls) patch = { ...patch, loadout: null };  // another vehicle: its own default loadout
  if ('cls' in patch && !('auto' in patch)) patch = { ...patch, auto: null };  // picked by hand: no longer follows your vehicle
  if (u.added) {
    const a = e.add[u.idx];
    Object.assign(a, patch);
    if (a.loadout == null) delete a.loadout;
    if (a.auto == null) delete a.auto;
    return;
  }
  const cur = Object.assign({}, e.units[u.name], patch);
  for (const k of Object.keys(cur)) if (cur[k] === '' || cur[k] == null || cur[k] === false || (k === 'cls' && cur[k] === u.cls) || (k === 'count' && +cur[k] === +u.count) || (u.tpl && k === 'attack' && !['hold_fire', 'fire_at_will'].includes(cur[k])) || (k === 'side' && cur[k] === edSide({ ...u, side: '' }))) delete cur[k];
  if (Object.keys(cur).length) e.units[u.name] = cur; else delete e.units[u.name];
}

function edRenderPanel() {
  $$('#edTools [data-edmode]').forEach(b => b.classList.toggle('active', b.dataset.edmode === ED.mode && (ED.mode !== 'add' || b.dataset.block === ED.addBlock)));
  $$('#edTools [data-edside]').forEach(b => b.classList.toggle('active', b.dataset.edside === ED.addSide));
  $('#edFitMap').classList.toggle('hidden', !ED.layers.length);
  $('#edPaste').classList.toggle('hidden', !ED.clip?.length);
  $('#edHint').textContent = ED.mode === 'route' ? t('editor.hintRoute') : ED.mode === 'add' ? t(ED.addBlock === 'objectGroups' ? 'editor.hintAddAsset' : ED.addSide === 'ally' ? 'editor.hintAddAlly' : 'editor.hintAdd') : t('editor.hintSelect');
  ED.canvas?.classList.toggle('routing', ED.mode === 'route');
  $('#edChanges').textContent = t('editor.changes', { n: edCount() });
  $('#edZones')?.classList.toggle('active', ED.zones);
  $('#edScenery')?.classList.toggle('active', ED.scenery);
  const panel = $('#edInspector');
  if (ED.multi.length) { panel.innerHTML = edMultiHTML(); edRenderResults(); edRenderList(); return; }
  if (ED.sel?.zone) {
    const z0 = (ED.data.areas || []).find(z => z.name === ED.sel.zone);
    if (z0) {
      const z = edZonePos(z0), moved = !!edEdits().areas[z0.name];
      const info = edZoneInfo(z0);
      const what = info.classes.length ? `<p class="hint">${esc(t('editor.zoneUnits'))}</p>
        <div class="ed-zunits">${info.classes.map(([c, n]) => `<div class="ed-zunit">${listThumb(c)}<span>${flagHTML(S.byId.get(c)?.n)}${esc(edUnitName(c))}</span><b>${n > 1 ? '×' + n : ''}</b></div>`).join('')}</div>` : '';
      panel.innerHTML = `<div class="ed-title">${icon('target', 'ic-sm')} <b>${esc(edZoneLabel(z0, info))}</b></div>
        <div class="ed-sub muted">${esc(t('editor.zone'))} · ${esc(z0.name)}${z0.type ? ' · ' + esc(z0.type) : ''} · ${Math.round(z0.sx)} × ${Math.round(z0.sz)} m</div>
        ${z0.player ? `<p class="hint">${esc(t('editor.zonePlayer'))}</p>` : ''}${what}
        ${!z0.player && !info.classes.length ? `<p class="hint">${esc(t(z0.used ? 'editor.zoneUsed' : 'editor.zoneUnused'))}</p>` : ''}
        <div class="field-row"><div class="field"><label>X</label><input type="number" data-edzone="x" value="${Math.round(z.x)}"></div>
          <div class="field"><label>Z</label><input type="number" data-edzone="z" value="${Math.round(z.z)}"></div></div>
        ${moved ? `<button class="btn btn-ghost btn-sm" data-edact="resetZone">${icon('refresh', 'ic-sm')}${esc(t('mods.reset'))}</button>` : ''}`;
      edRenderList();
      return;
    }
  }
  const u = edSelected();
  if (!u) { panel.innerHTML = `<p class="hint">${esc(t('editor.noSel'))}</p><p class="hint">${esc(t('editor.multiHint'))}</p>${edAutoHTML(false)}`; edRenderList(); return; }
  if (u.player) {
    const p = edStart();
    const sp = ED.data.spawn;
    const spawnNote = sp ? `<p class="hint">${esc(t(edEdits().player ? 'editor.spawnMoved' : sp.runway ? 'editor.spawnRunway' : 'editor.spawnArea'))}</p>` : '';
    const modeSeg = edFlyer() ? `<div class="field"><label>${esc(t('cond.start'))}</label><div class="seg">
        <button class="${p.air ? '' : 'active'}" data-edstart="ground">${esc(t('editor.startGround'))}</button>
        <button class="${p.air ? 'active' : ''}" data-edstart="air">${esc(t('editor.startAir'))}</button></div></div>` : '';
    const airFields = p.air ? `<div class="field-row"><div class="field"><label>${esc(t('cond.altitude'))} (m)</label><input type="number" data-edf="py" value="${Math.round(p.y)}">${edGroundInfo(p, true, 'py')}</div>
        <div class="field"><label>${esc(t('cond.speed'))} (km/h)</label><input type="number" min="0" max="3000" step="10" data-edf="pspeed" value="${Math.round(p.speed)}"></div></div>`
      : `<div class="field"><label>${esc(t('editor.height'))}</label><input type="number" data-edf="py" value="${Math.round(p.y)}">${edGroundInfo(p, edFlyer() || S.cfg.block !== 'tankModels', 'py')}</div>`;
    panel.innerHTML = `<div class="ed-title">${icon('target', 'ic-sm')} ${esc(t('editor.playerStart'))}</div>
      <p class="hint">${esc(t(edFlyer() ? 'editor.playerHintAir' : 'editor.playerHint'))}</p>${spawnNote}
      ${modeSeg}${airFields}
      ${edHeadingField(p.yaw, 'pyaw')}
      ${edEdits().player ? `<button class="btn btn-ghost btn-sm" data-edact="resetPlayer">${icon('refresh', 'ic-sm')}${esc(t('mods.reset'))}</button>` : ''}`;
    edRenderList();
    return;
  }
  const st = edUnitState(u);
  const cats = ED_BLOCK_CATS[u.block] || [];
  const v = S.byId.get(st.cls);
  const air = u.block === 'armada';
  const side = edSide(st);
  const behaviors = edBehaviors(side, air, u.added, edRoutable(st));
  const moveSeg = `<div class="field"><label>${esc(t('editor.move'))}</label><div class="seg seg-wrap${behaviors.length === 4 ? 2 : 3}">
      ${behaviors.map(([k, l]) => `<button class="${(st.behavior || '') === k ? 'active' : ''}" data-edbeh="${k}">${esc(t(l))}</button>`).join('')}
    </div>${st.behavior === 'follow' ? `<small class="muted">${esc(t('editor.followHint'))}</small>` : ''}${st.moves && !u.added ? `<small class="muted">${esc(t('editor.movesHint'))}</small>` : ''}</div>`;
  const removed = `<p class="hint">${esc(t('editor.removedHint'))}</p><button class="btn btn-sm" data-edact="restore">${icon('refresh', 'ic-sm')}${esc(t('editor.restore'))}</button>`;
  const copyBtns = ED_ADD_BLOCK[u.block] || u.added ? `<button class="btn btn-ghost btn-sm" data-edact="copy">${esc(t('editor.copy'))}</button>
      <button class="btn btn-ghost btn-sm" data-edact="duplicate">${esc(t('editor.duplicate'))}</button>` : '';
  if (u.tpl) {
    panel.innerHTML = `<div class="ed-title">${v ? flagHTML(v.n) : ''}<b>${esc(v ? I18N.unit(v.id) : st.cls)}</b></div>
      <div class="ed-sub muted">${esc(u.name)} · ${esc(t('editor.fromTemplate'))}</div>
      ${st.removed ? removed : `
      <p class="hint">${esc(t(u.swap ? 'editor.tplNoteSwap' : 'editor.tplNote'))}${u.runtime ? ' ' + esc(t('editor.runtimeNote')) + (edSelZones().length ? ' ' + esc(t('editor.runtimeZones', { n: edSelZones().length })) : '') : u.area ? ' ' + esc(t('editor.areaNote', { area: u.area })) : ''}</p>
      <div class="field"><label>${esc(t('editor.fire'))}</label><select data-edf="attack">
        ${[['', 'editor.asScenario'], ['fire_at_will', 'editor.fire.aggressive'], ['hold_fire', 'editor.fire.passive']].map(([k, l]) => `<option value="${k}"${(['hold_fire', 'fire_at_will'].includes(st.attack) ? st.attack : '') === k ? ' selected' : ''}>${esc(t(l))}</option>`).join('')}
      </select></div>
      ${u.swap ? edVehicleField(cats) + edLoadoutField(st) : ''}
      ${moveSeg}
      <div class="row gap ed-actions">${copyBtns}
      <button class="btn btn-ghost btn-sm btn-danger" data-edact="remove">${icon('trash', 'ic-sm')}${esc(t('editor.remove'))}</button></div>`}`;
    edRenderList();
    return;
  }
  const sideSeg = `<div class="field"><label>${esc(t('editor.side'))}</label><div class="seg ed-side">
      <button class="${side === 'enemy' ? 'active' : ''}" data-edside="enemy"><i class="dot enemy"></i>${esc(t('editor.enemy'))}</button>
      <button class="${side === 'ally' ? 'active' : ''}" data-edside="ally"><i class="dot ally"></i>${esc(t('editor.ally'))}</button></div></div>`;
  if (u.block === 'objectGroups') {  // an asset: what it is, whose it is
    edLoadObjects();
    panel.innerHTML = `<div class="ed-title"><b>${esc(I18N.unit(st.cls))}</b></div>
      <div class="ed-sub muted">${esc(t('editor.added'))} · ${esc(t('editor.block.objectGroups'))}</div>
      ${sideSeg}
      ${edHeadingField(st.yaw, 'uyaw')}
      ${edAssetField()}
      <div class="row gap ed-actions">${copyBtns}
        <button class="btn btn-ghost btn-sm btn-danger" data-edact="delete">${icon('trash', 'ic-sm')}${esc(t('action.delete'))}</button></div>`;
    edRenderResults();
    edRenderList();
    return;
  }
  panel.innerHTML = `<div class="ed-title">${v ? flagHTML(v.n) : ''}<b>${esc(v ? I18N.unit(v.id) : st.cls)}</b>${v?.br ? `<span class="chip">${fmtBR(v.br[1])}</span>` : ''}</div>
    <div class="ed-sub muted">${esc(u.added ? t('editor.added') : u.name)} · ${esc(t('editor.block.' + u.block))}</div>
    ${u.tp ? `<p class="hint">${esc(t(u.tp.start ? (st.moved ? 'editor.tpStartMoved' : 'editor.tpStart') : 'editor.tpLater'))}</p>` : ''}
    ${st.removed ? removed : `
    ${sideSeg}
    ${edTurnable().length ? edHeadingField(st.yaw, 'uyaw') : ''}
    <div class="field-row">
      <div class="field"><label>${esc(t('editor.count'))}</label><input type="number" min="1" max="12" data-edf="count" value="${+st.count || 1}"></div>
      <div class="field"><label>${esc(t('editor.fire'))}</label><select data-edf="attack">
        ${[['', 'editor.asScenario'], ['fire_at_will', 'editor.fire.aggressive'], ['return_fire', 'editor.fire.return'], ['hold_fire', 'editor.fire.passive']]
          .filter(([k]) => k || !u.added).map(([k, l]) => `<option value="${k}"${(st.attack || '') === k && (k || !u.added) ? ' selected' : ''}>${esc(t(l))}</option>`).join('')}
      </select></div>
    </div>
    ${moveSeg}
    ${edRouteHTML([st])}${edWaveHTML([st])}
    ${air ? `<div class="field-row"><div class="field"><label>${esc(t('cond.altitude'))}</label><input type="number" data-edf="y" value="${Math.round(st.y)}">${edGroundInfo(st, true)}</div>
      ${u.added ? `<div class="field"><label>${esc(t('cond.speed'))} (km/h)</label><input type="number" data-edf="speed" value="${Math.round(st.speed || 450)}"></div>` : ''}</div>` : ''}
    ${u.block === 'tankModels' && (u.added || st.moved) ? `<div class="field"><label>${esc(t('editor.height'))}</label><input type="number" data-edf="y" value="${Math.round(st.y)}">${edGroundInfo(st, false) || `<small class="muted">${esc(t('editor.heightHint'))}</small>`}</div>` : ''}
    ${edVehicleField(cats.length ? cats : ['ground'], u.added)}
    ${edLoadoutField(st)}
    <div class="row gap ed-actions">
      ${st.moved ? `<button class="btn btn-ghost btn-sm" data-edact="resetPos">${icon('refresh', 'ic-sm')}${esc(t('editor.resetPos'))}</button>` : ''}
      ${copyBtns}
      <button class="btn btn-ghost btn-sm btn-danger" data-edact="${u.added ? 'delete' : 'remove'}">${icon('trash', 'ic-sm')}${esc(t(u.added ? 'action.delete' : 'editor.remove'))}</button>
    </div>`}`;
  edRenderResults();
  edRenderList();
}

const edHeadingField = (yaw, f) => `<div class="field"><label>${esc(t('editor.heading'))}</label><div class="slider-row"><input type="range" min="0" max="359" step="1" data-edf="${f}" value="${edCompass(yaw)}"><output>${edCompass(yaw)}° ${esc(edCardinal(edCompass(yaw)))}</output></div>
    <small class="muted">${esc(t('editor.headingHint'))}</small></div>`;
const edLoadObjects = () => { if (!S.objects) getData('objects.json').then(list => { S.objects = list; edRenderPanel(); }).catch(() => { S.objects = []; }); };
// the asset picker: the game's object groups, by name (they have no picture)
const edAssetField = () => `<div class="field"><label>${esc(t('editor.block.objectGroups'))}</label>
    <input id="edSearch" type="search" placeholder="${esc(t('editor.searchAsset'))}" value="${esc(ED.search)}" autocomplete="off">
    <div class="ed-count muted" id="edCount"></div>
    <div class="ed-results" id="edResults" data-cats=""></div></div>`;
// the vehicle picker: all the game's vehicles of that kind (pictures) or the user's saved ones (My vehicles)
function edVehicleField(cats, objects = false) {
  const mine = (S.setups || []).filter(s => cats.includes(S.byId.get(s.vehicle)?.c)).length;
  return `<div class="field"><label>${esc(t('editor.vehicle'))}</label>
    <div class="seg ed-restabs"><button class="${ED.resTab === 'all' ? 'active' : ''}" data-edtab="all">${esc(t('editor.allVehicles'))}</button>
      <button class="${ED.resTab === 'mine' ? 'active' : ''}" data-edtab="mine">${esc(t('editor.myVehicles'))}${mine ? ` <span class="muted">${mine}</span>` : ''}</button>
      ${objects ? `<button class="${ED.resTab === 'objects' ? 'active' : ''}" data-edtab="objects">${esc(t('editor.objects'))}</button>` : ''}</div>
    ${ED.resTab !== 'mine' ? `<input id="edSearch" type="search" placeholder="${esc(t('editor.searchVehicle'))}" value="${esc(ED.search)}" autocomplete="off">` : ''}
    ${ED.resTab === 'all' ? edFilterHTML(cats) : ''}
    <div class="ed-count muted" id="edCount"></div>
    <div class="ed-results" id="edResults" data-cats="${cats.join(',')}"></div></div>`;
}
// the picker's filters, as the Vehicles menu's: nations, rank, battle rating (its AB / RB / SB mode), type
const edVfReset = () => ({ nations: [], ranks: [], roles: [], brMin: BR_MIN, brMax: BR_MAX });
function edFilterHTML(cats) {
  const f = ED.vf ||= edVfReset();
  const pool = S.vehicles.filter(v => cats.includes(v.c));
  const maxRank = Math.max(...pool.map(v => v.r || 0), 1);
  const counts = {};
  for (const v of pool) for (const r of v.ro || []) counts[r] = (counts[r] || 0) + 1;
  const roles = ROLE_ORDER.filter(r => counts[r]);
  const pct = x => ((x - BR_MIN) / (BR_MAX - BR_MIN)) * 100;
  const changed = f.nations.length || f.ranks.length || f.roles.length || f.brMin > BR_MIN || f.brMax < BR_MAX;
  return `<div class="ed-filters">
    <div class="side-title">${esc(t('filters.nations'))}</div>
    <div class="nations${f.nations.length ? ' has-active' : ''}">${NATIONS.map(x => `<button class="nation${f.nations.includes(x) ? ' active' : ''}" data-edvf="nat:${x}" title="${esc(nationName(x))}">
      <img src="${flagImg(x)}" alt=""></button>`).join('')}</div>
    <div class="side-title">${esc(t('filters.rank'))}</div>
    <div class="ranks">${Array.from({ length: maxRank }, (_, k) => k + 1).map(r => `<button class="rank-chip${f.ranks.includes(r) ? ' active' : ''}" data-edvf="rank:${r}">${ROMAN[r] || r}</button>`).join('')}</div>
    <div class="side-title">${esc(t('filters.br'))}</div>
    <div class="range">
      <div class="range-track"><div class="range-fill" id="edBrFill" style="left:${pct(f.brMin)}%;right:${100 - pct(f.brMax)}%"></div></div>
      <input type="range" min="${BR_MIN}" max="${BR_MAX}" step="0.1" data-edvfn="brMin" value="${f.brMin}">
      <input type="range" min="${BR_MIN}" max="${BR_MAX}" step="0.1" data-edvfn="brMax" value="${f.brMax}">
    </div>
    <div class="range-labels"><span id="edBrMinLabel">${f.brMin.toFixed(1)}</span><span id="edBrMaxLabel">${f.brMax.toFixed(1)}</span></div>
    ${roles.length > 1 ? `<div class="side-title">${esc(t('filters.type'))}</div>
    <div class="roles">${roles.map(r => `<button class="role-chip${f.roles.includes(r) ? ' active' : ''}" data-edvf="role:${r}">
      <span>${esc(I18N.role(r))}</span><i>${I18N.num(counts[r])}</i></button>`).join('')}</div>` : ''}
    ${changed ? `<button class="btn btn-ghost btn-sm btn-block" data-edvf="clear">${icon('refresh', 'ic-sm')}${esc(t('filters.reset'))}</button>` : ''}
  </div>`;
}
function edLoadoutSummary(st) {
  const lo = st.loadout;
  if (!lo) return t('editor.loadoutDefault');
  if (lo.name) return lo.name;
  if (lo.pylons) return t('loadout.customRow');
  const v = S.byId.get(st.cls), p = S.details.get(st.cls)?.pr.find(x => x.id === lo.preset);
  return v && p ? presetLabel(v, p) : lo.preset || t('editor.loadoutOwn');
}
function edLoadoutField(st) {
  if (!S.byId.get(st.cls)) return '';
  return `<div class="field"><label>${esc(t('editor.loadout'))}</label><div class="ed-lo">
    <span${st.loadout ? ' class="on"' : ''}>${esc(edLoadoutSummary(st))}</span>
    <button class="btn btn-sm" data-edact="loadout">${icon('sliders', 'ic-sm')}${esc(t('editor.configure'))}</button>
    ${st.loadout ? `<button class="icon-btn" data-edact="loadoutReset" title="${esc(t('mods.reset'))}">${icon('refresh', 'ic-sm')}</button>` : ''}
  </div></div>`;
}

// the route of the selected unit(s): drawn on the map, with its speed and what happens at the end
function edRouteHTML(sts) {
  const us = sts.filter(edRoutable), first = us[0];
  if (!first || !us.every(u => u.behavior === 'route')) return '';
  const on = ED.mode === 'route', n = first.route?.length || 0;
  const same = f => (us.every(u => f(u) === f(first)) ? f(first) : undefined);
  const speed = same(edRouteSpeed), loop = same(u => !!u.routeLoop);
  return `<div class="field"><div class="ed-lo"><span>${esc(t('editor.routePoints', { n }))}</span>
      <button class="btn btn-sm${on ? ' btn-primary' : ''}" data-edact="routeDraw">${icon(on ? 'check' : 'map', 'ic-sm')}${esc(t(on ? 'editor.routeDone' : 'editor.routeDraw'))}</button>
      ${n ? `<button class="icon-btn" data-edact="routeBack" title="${esc(t('editor.routeBack'))}">${icon('x', 'ic-sm')}</button>
      <button class="icon-btn" data-edact="routeClear" title="${esc(t('editor.routeClear'))}">${icon('trash', 'ic-sm')}</button>` : ''}
    </div></div>
    <div class="field-row"><div class="field"><label>${esc(t('cond.speed'))} (km/h)</label><input type="number" min="1" max="3000" data-edm="routeSpeed" value="${esc(speed ?? '')}" placeholder="${esc(t('editor.mixed'))}"></div>
      <div class="field"><label>${esc(t('editor.routeEnd'))}</label><select data-edm="routeLoop">${loop === undefined ? `<option value="__mixed" selected disabled>${esc(t('editor.mixed'))}</option>` : ''}
        <option value="0"${loop === false ? ' selected' : ''}>${esc(t('editor.routeStop'))}</option>
        <option value="1"${loop ? ' selected' : ''}>${esc(t('editor.routeLoop'))}</option></select></div></div>`;
}
// the wave of the selected enemies
function edWaveHTML(sts) {
  const us = sts.filter(u => !u.tpl && edSide(u) === 'enemy');
  if (!us.length) return '';
  const wave = us.every(u => (u.wave || 0) === (us[0].wave || 0)) ? us[0].wave || 0 : undefined, loop = !!edEdits().waveLoop;
  return `<div class="field-row"><div class="field"><label>${esc(t('editor.wave'))}</label><select data-edm="wave">${wave === undefined ? `<option value="__mixed" selected disabled>${esc(t('editor.mixed'))}</option>` : ''}
      ${[0, 1, 2, 3, 4, 5, 6, 7, 8, 9].map(n => `<option value="${n}"${wave === n ? ' selected' : ''}>${n || esc(t('editor.waveNone'))}</option>`).join('')}</select></div>
    <div class="field"><label>${esc(t('editor.waveEnd'))}</label><select data-edwaveloop>
      <option value="0"${loop ? '' : ' selected'}>${esc(t('editor.waveStop'))}</option>
      <option value="1"${loop ? ' selected' : ''}>${esc(t('editor.waveLoop'))}</option></select></div></div>
    <small class="muted ed-wavehint">${esc(t('editor.waveHint', { cheat: t('cheat.targetsBack') }))}</small>`;
}

// several units selected: what they share, changed for all at once
function edMultiHTML() {
  const sts = edSelUnits().map(edUnitState);
  const own = sts.filter(u => !u.tpl);  // vehicle, side, count: the scenario's own and added units
  const air = own.filter(u => u.block === 'armada');
  const same = (arr, f) => (arr.length && arr.every(x => f(x) === f(arr[0])) ? f(arr[0]) : undefined);
  const counts = new Map();
  for (const u of sts) counts.set(u.cls, (counts.get(u.cls) || 0) + 1);
  const side = same(own, edSide), attack = same(sts, u => u.attack || ''), beh = same(sts, u => u.behavior || ''), cnt = same(own, u => +u.count || 1);
  const swp = sts.filter(edSwappable);  // vehicle: template units the mission can carry too
  const cats = [...new Set(swp.flatMap(u => ED_BLOCK_CATS[u.block] || []))];
  const mixed = `<option value="__mixed" selected disabled>${esc(t('editor.mixed'))}</option>`;
  const behs = [['', 'editor.asScenario'], ...(own.every(u => u.block === 'armada') ? [] : [['stay', 'editor.move.stay']]), ['hunt', 'editor.move.hunt'], ['follow', 'editor.move.follow'],
    ...(sts.some(edRoutable) ? [['route', 'editor.move.route']] : [])];
  return `<div class="ed-title">${icon('target', 'ic-sm')} <b>${esc(t('editor.selected', { n: sts.length }))}</b></div>
    <div class="ed-chips">${[...counts].map(([c, n]) => `<span class="chip">${esc(edUnitName(c))}${n > 1 ? ` ×${n}` : ''}</span>`).join('')}</div>
    <p class="hint">${esc(t('editor.multiHint'))}</p>
    ${own.length ? `<div class="field"><label>${esc(t('editor.side'))}</label><div class="seg ed-side">
      <button class="${side === 'enemy' ? 'active' : ''}" data-edmside="enemy"><i class="dot enemy"></i>${esc(t('editor.enemy'))}</button>
      <button class="${side === 'ally' ? 'active' : ''}" data-edmside="ally"><i class="dot ally"></i>${esc(t('editor.ally'))}</button></div></div>` : ''}
    ${edTurnable().length ? edHeadingField(edUnitState(edTurnable()[0]).yaw, 'uyaw') : ''}
    <div class="field-row">
      ${own.length ? `<div class="field"><label>${esc(t('editor.count'))}</label><input type="number" min="1" max="12" data-edm="count" value="${cnt ?? ''}" placeholder="${esc(t('editor.mixed'))}"></div>` : ''}
      <div class="field"><label>${esc(t('editor.fire'))}</label><select data-edm="attack">${attack === undefined ? mixed : ''}
        ${[['', 'editor.asScenario'], ['fire_at_will', 'editor.fire.aggressive'], ['return_fire', 'editor.fire.return'], ['hold_fire', 'editor.fire.passive']]
          .map(([k, l]) => `<option value="${k}"${attack === k ? ' selected' : ''}>${esc(t(l))}</option>`).join('')}</select></div>
    </div>
    <div class="field"><label>${esc(t('editor.move'))}</label><div class="seg seg-wrap3">
      ${behs.map(([k, l]) => `<button class="${beh === k ? 'active' : ''}" data-edmbeh="${k}">${esc(t(l))}</button>`).join('')}</div>
      <small class="muted">${esc(t('editor.multiMoveHint'))}</small></div>
    ${edRouteHTML(sts)}${edWaveHTML(sts)}
    ${air.length ? `<div class="field-row"><div class="field"><label>${esc(t('cond.altitude'))}</label><input type="number" data-edm="y" value="${same(air, u => Math.round(u.y)) ?? ''}" placeholder="${esc(t('editor.mixed'))}"></div>
      <div class="field"><label>${esc(t('cond.speed'))} (km/h)</label><input type="number" data-edm="speed" value="${same(air, u => Math.round(u.speed || 450)) ?? ''}" placeholder="${esc(t('editor.mixed'))}"></div></div>` : ''}
    ${swp.length ? edVehicleField(cats) : ''}
    ${edAutoHTML(true)}
    <div class="row gap ed-actions">
      <button class="btn btn-ghost btn-sm" data-edact="copy">${esc(t('editor.copy'))}</button>
      <button class="btn btn-ghost btn-sm" data-edact="duplicate">${esc(t('editor.duplicate'))}</button>
      ${sts.some(u => u.removed) ? `<button class="btn btn-ghost btn-sm" data-edact="restoreSel">${icon('refresh', 'ic-sm')}${esc(t('editor.restore'))}</button>` : ''}
      <button class="btn btn-ghost btn-sm btn-danger" data-edact="removeSel">${icon('trash', 'ic-sm')}${esc(t('editor.removeSel'))}</button>
      <button class="btn btn-ghost btn-sm" data-edact="clearSel">${icon('x', 'ic-sm')}${esc(t('editor.clearSel'))}</button>
    </div>`;
}

// under a height field: ground level here, and height above it (aircraft) or a button to put the unit on it
function edGroundInfo(u, air, field = 'y') {
  const g = edGround(u.x, u.z);
  if (g == null) return '';
  const agl = Math.round(u.y - g);
  return `<small class="muted ed-ground">${esc(t('editor.groundHere', { h: Math.round(g) }))}${air ? ` · ${esc(t('editor.agl', { h: agl }))}` : ''}
    ${!air && Math.abs(u.y - g - 0.5) > 0.6 ? `<button class="btn btn-ghost btn-xs" data-edground="${field}">${esc(t('editor.onGround'))}</button>` : ''}</small>`;
}

function edRenderResults() {
  const box = $('#edResults');
  if (!box) return;
  const cats = box.dataset.cats.split(',');
  const cur = ED.multi.length ? '' : (() => { const u = edSelected(); return u ? edUnitState(u).cls : ''; })();
  const assets = !box.dataset.cats;
  if (ED.resTab === 'mine' && !assets) {
    const list = (S.setups || []).filter(s => cats.includes(S.byId.get(s.vehicle)?.c));
    box.innerHTML = list.map(s => `<button class="ed-vc" data-edsetup="${esc(s.id)}" title="${esc(s.name)}">
        <div class="ed-vc-img">${unitImgTag(s.vehicle)}</div><span class="ed-vc-name">${esc(s.name)}</span>
        <span class="ed-vc-sub">${flagHTML(S.byId.get(s.vehicle)?.n)}${esc(I18N.unit(s.vehicle))}</span></button>`).join('')
      || `<p class="hint">${esc(t('editor.noMine'))}</p>`;
    return;
  }
  const q = norm(ED.search), f = ED.vf ||= edVfReset();
  if (ED.resTab === 'objects' || assets) {  // AA guns, trucks, buildings, radars...: from the game's own unit folders; or its assets
    const list = (S.objects || []).filter(o => (o.b === 'objectGroups') === assets && (!q || norm(`${I18N.unit(o.id)} ${o.id}`).includes(q)));
    const count = $('#edCount');
    if (count) count.textContent = I18N.num(list.length);
    box.innerHTML = list.map(o => `<button class="ed-vc${o.id === cur ? ' active' : ''}" data-edobj="${esc(o.id)}" data-edblock="${esc(o.b)}" title="${esc(I18N.unitFull(o.id))}">
        <div class="ed-vc-img">${assets ? icon('cube', 'ic') : `${unitImgTag(o.id)}<span class="ed-vc-br">${esc(t('editor.block.' + o.b))}</span>`}</div>
        <span class="ed-vc-name">${esc(I18N.unit(o.id))}</span></button>`).join('') || `<p class="hint">${esc(t('results.empty'))}</p>`;
    return;
  }
  // every vehicle of that kind that the filters keep, by BR (the Vehicles menu's AB / RB / SB mode)
  const fullBR = f.brMin <= BR_MIN && f.brMax >= BR_MAX;
  const list = S.vehicles.filter(v => cats.includes(v.c) && (!q || v._s.includes(q))  // the non-playable ones too: AI sites to fight
    && (!f.nations.length || f.nations.includes(v.n)) && (!f.ranks.length || f.ranks.includes(v.r))
    && (!f.roles.length || (v.ro || []).some(r => f.roles.includes(r)))
    && (fullBR || (brOf(v) != null && brOf(v) >= f.brMin - 0.01 && brOf(v) <= f.brMax + 0.01)));
  list.sort((a, b) => (brOf(a) ?? 99) - (brOf(b) ?? 99) || I18N.unit(a.id).localeCompare(I18N.unit(b.id)));
  const count = $('#edCount');
  if (count) count.textContent = t('editor.vehiclesCount', { n: list.length });
  box.innerHTML = list.map(v => `<button class="ed-vc${v.id === cur ? ' active' : ''}" data-edcls="${esc(v.id)}" title="${esc(I18N.unitFull(v.id))}">
      <div class="ed-vc-img">${unitImgTag(v.id)}<span class="ed-vc-br">${v.h ? esc(t('badge.hidden')) : fmtBR(brOf(v))}</span></div>
      <span class="ed-vc-name">${flagHTML(v.n)}${esc(I18N.unit(v.id))}</span></button>`).join('')
    || `<p class="hint">${esc(t('results.empty'))}</p>`;
}

function edRenderList() {
  const e = edEdits();
  const groups = { enemy: [], ally: [] };
  const keys = edSelKeys();
  for (const u of ED.data.units.filter(x => x.edit)) {
    const st = edUnitState(u);
    const side = edSide(st);
    const changed = !!e.units[u.name];
    (groups[side] || groups.enemy).push(`<button class="ed-row${keys.includes('u:' + u.name) ? ' active' : ''}${st.removed ? ' removed' : ''}" data-edsel="u:${esc(u.name)}">
      <i class="dot ${side}"></i><span>${esc(edUnitName(st.cls))}${st.count > 1 ? ` ×${st.count}` : ''}</span>${u.tpl ? `<i class="chip dim">${esc(t(u.runtime ? 'editor.runtime' : 'editor.tpl'))}</i>` : ''}${changed ? '<b>●</b>' : ''}</button>`);
  }
  e.add.forEach((a, i) => {
    const side = a.side === 'ally' ? 'ally' : 'enemy';
    groups[side].push(`<button class="ed-row added${keys.includes('add:' + i) ? ' active' : ''}" data-edsel="add:${i}">
      <i class="dot ${side}"></i><span>${esc(I18N.unit(a.cls))}${a.count > 1 ? ` ×${a.count}` : ''}</span><b>+</b></button>`);
  });
  const html = ['enemy', 'ally'].filter(k => groups[k].length)
    .map(k => `<div class="ed-group">${esc(t(k === 'enemy' ? 'editor.enemies' : 'editor.allies'))} <span class="muted">${groups[k].length}</span></div>${groups[k].join('')}`).join('');
  $('#edList').innerHTML = html || `<p class="hint">${esc(t('editor.noUnits'))}</p>`;
}

// the loadout of an AI unit, set in the vehicle panel like the player's (the editor waits meanwhile)
async function edConfigure(key) {
  const u = edUnitByKey(key);
  if (!u) return;
  const st = edUnitState(u);
  // until back in the editor: its "close" event (fired a moment later) must not end the editing session
  ED.configuring = true;
  $('#dlgEditor').close();
  // the map window (the editor opened from it) would stay over the vehicle panel: closed meanwhile
  for (const d of $$('dialog[open]')) { if (!ED.hidden.includes(d)) ED.hidden.push(d); d.close(); }
  await openUnitLoadout(st.cls, st.loadout, { name: I18N.unit(st.cls) }, res => {
    const cur = edUnitByKey(key);
    if (res && cur) edSet(cur, { loadout: { ...res, vehicle: st.cls } });
    ED.configuring = false;
    edResume();
  });
}
// a saved vehicle (My vehicles) for the selected unit(s): its vehicle and loadout
async function edUseSetup(id) {
  const s = (S.setups || []).find(x => x.id === id);
  const v = s && S.byId.get(s.vehicle);
  if (!v) return;
  const lo = await loadoutFromSetup(s);
  for (const u of edSelUnits()) {
    const st = edUnitState(u);
    if (!edSwappable(st) || !(ED_BLOCK_CATS[u.block] || []).includes(v.c)) continue;
    edSet(u, { cls: s.vehicle, loadout: lo ? { ...lo, vehicle: s.vehicle } : null });
  }
  edRenderPanel(); edDraw();
}

function edPanelClick(ev) {
  const b = ev.target.closest('button'); if (!b) return;
  if (b.dataset.edsel) {
    const inList = !!b.closest('#edList');  // before the panel is drawn again
    if (ev.ctrlKey || ev.metaKey || ev.shiftKey) edToggle(b.dataset.edsel); else edSelect([b.dataset.edsel]);
    edRenderPanel(); edDraw();
    if (inList) edFocus();
    return;
  }
  if (b.dataset.edtab) {
    ED.resTab = b.dataset.edtab;
    if (ED.resTab === 'objects') edLoadObjects();
    edRenderPanel();
    return;
  }
  if (b.dataset.edvf) {  // the vehicle picker's filters
    const [k, x] = b.dataset.edvf.split(/:(.*)/s), f = ED.vf ||= edVfReset();
    const toggle = (list, v) => (list.includes(v) ? list.filter(y => y !== v) : [...list, v]);
    if (k === 'clear') ED.vf = edVfReset();
    else if (k === 'nat') f.nations = toggle(f.nations, x);
    else if (k === 'rank') f.ranks = toggle(f.ranks, +x);
    else if (k === 'role') f.roles = toggle(f.roles, x);
    edRenderPanel();
    return;
  }
  if (edAutoClick(b)) return;
  if (b.dataset.edsetup) { edUseSetup(b.dataset.edsetup); return; }
  switch (b.dataset.edact) {
    case 'copy': if (edCopy()) toast({ title: t('editor.copied', { n: ED.clip.length }), ms: 2000 }); edRenderPanel(); return;
    case 'duplicate': edDuplicate(); edRenderPanel(); edDraw(); return;
    case 'clearSel': edSelect([]); edRenderPanel(); edDraw(); return;
    case 'removeSel': edRemoveUnits(edSelUnits()); edRenderPanel(); edDraw(); return;
    case 'restoreSel': for (const u of edSelUnits()) if (!u.added) edSet(u, { remove: false }); edRenderPanel(); edDraw(); return;
    case 'loadout': if (ED.sel?.key) edConfigure(ED.sel.key); return;
    case 'routeDraw': ED.mode = ED.mode === 'route' ? 'select' : 'route'; edRenderPanel(); return;
    case 'routeBack': edRouteBack(); edRenderPanel(); edDraw(); return;
    case 'routeClear': for (const u of edRouteUnits()) edSet(u, { route: null }); edRenderPanel(); edDraw(); return;
    case 'resetZone': delete edEdits().areas[ED.sel.zone]; edRenderPanel(); edDraw(); return;
  }
  if (ED.multi.length) { edMultiClick(b); return; }
  const u = edSelected();
  if (!u) return;
  if (b.dataset.edobj) { edSet(u, { cls: b.dataset.edobj, block: b.dataset.edblock }); }
  else if (b.dataset.edcls) {  // back from an object: the vehicle's own block
    const kind = S.byId.get(b.dataset.edcls)?.c, block = Object.keys(ED_BLOCK_CATS).find(k => ED_BLOCK_CATS[k].includes(kind));
    edSet(u, { cls: b.dataset.edcls, ...(u.added && block ? { block } : {}) });
  }
  else if (b.dataset.edbeh !== undefined) { edSet(u, { behavior: b.dataset.edbeh }); edRouteMode(b.dataset.edbeh); }
  else if (b.dataset.edside) {
    const beh = edUnitState(u).behavior;
    // hunting you only makes sense for enemies, escorting you only for allies
    const keep = !(beh === 'hunt' && b.dataset.edside === 'ally') && !(beh === 'follow' && b.dataset.edside === 'enemy');
    edSet(u, { side: b.dataset.edside, ...(keep ? {} : { behavior: '' }) });
  }
  else if (b.dataset.edact === 'remove') { edSet(u, { remove: true }); }
  else if (b.dataset.edact === 'restore') { edSet(u, { remove: false }); }
  else if (b.dataset.edact === 'resetPos') { edSet(u, { x: null, y: null, z: null, yaw: null }); }
  else if (b.dataset.edact === 'delete') { edEdits().add.splice(u.idx, 1); edSelect([]); }
  else if (b.dataset.edact === 'loadoutReset') { edSet(u, { loadout: null }); }
  else if (b.dataset.edact === 'resetPlayer') { delete edEdits().player; }
  else if (b.dataset.edstart) {
    const s = edStart(), g = edGround(s.x, s.z);
    const air = b.dataset.edstart === 'air';
    edSetStart({ mode: air ? 'air' : 'ground', y: air ? Math.max(s.y, Math.round((g ?? s.y) + (S.cfg.altitude || 1500))) : Math.round(edGroundY(s.x, s.z) * 10) / 10,
      speed: air ? (s.speed || 450) : 0 });
  }
  else if (b.dataset.edground) {
    if (b.dataset.edground === 'py') {
      const p = edPlayerPos(u);
      edSetStart({ y: Math.round(edGroundY(p.x, p.z) * 10) / 10 });
    } else {
      const st = edUnitState(u);
      edSet(u, u.added ? { y: Math.round(edGroundY(st.x, st.z) * 10) / 10 } : { x: st.x, z: st.z, y: Math.round(edGroundY(st.x, st.z) * 10) / 10 });
    }
  }
  else return;
  edRenderPanel(); edDraw();
}
// a change for every selected unit it applies to
function edMultiClick(b) {
  const us = edSelUnits();
  if (b.dataset.edcls) {
    const v = S.byId.get(b.dataset.edcls);
    for (const u of us) if (edSwappable(u) && v && (ED_BLOCK_CATS[u.block] || []).includes(v.c)) edSet(u, { cls: v.id });
  } else if (b.dataset.edmside) {
    for (const u of us) {
      if (u.tpl) continue;
      const beh = edUnitState(u).behavior;
      const keep = !(beh === 'hunt' && b.dataset.edmside === 'ally') && !(beh === 'follow' && b.dataset.edmside === 'enemy');
      edSet(u, { side: b.dataset.edmside, ...(keep ? {} : { behavior: '' }) });
    }
  } else if (b.dataset.edmbeh !== undefined) {
    const beh = b.dataset.edmbeh;
    for (const u of us) {
      const side = edSide(edUnitState(u));
      // hunting: enemies only, escorting: allies only, staying still: not aircraft
      if ((beh === 'hunt' && side !== 'enemy') || (beh === 'follow' && side !== 'ally') || (beh === 'stay' && u.block === 'armada') || (beh === 'route' && !edRoutable(u))) continue;
      edSet(u, { behavior: beh });
    }
    edRouteMode(beh);
  } else return;
  edRenderPanel(); edDraw();
}

function edPanelChange(ev) {
  const el = ev.target, f = el.dataset.edf;
  if (el.dataset.edautof) { ED.auto[el.dataset.edautof] = el.value; edRenderPanel(); return; }
  if (el.dataset.edzone && ED.sel?.zone) {
    const z0 = (ED.data.areas || []).find(z => z.name === ED.sel.zone);
    const cur = edZonePos(z0);
    edEdits().areas[z0.name] = { x: cur.x, z: cur.z, [el.dataset.edzone]: +el.value };
    edRenderPanel(); edDraw();
    return;
  }
  if (el.dataset.edwaveloop !== undefined) { edEdits().waveLoop = el.value === '1'; return; }
  if (el.dataset.edm && el.value !== '' && el.value !== '__mixed') {  // several units
    for (const u of edSelUnits()) {
      const st = edUnitState(u);
      if (el.dataset.edm === 'count' && !u.tpl) edSet(u, { count: Math.max(1, Math.min(12, +el.value || 1)) });
      else if (el.dataset.edm === 'attack') edSet(u, { attack: el.value });
      else if (el.dataset.edm === 'y' && u.block === 'armada' && !u.tpl) edSet(u, u.added ? { y: +el.value } : { x: st.x, z: st.z, y: +el.value });
      else if (el.dataset.edm === 'speed' && u.block === 'armada' && u.added) edSet(u, { speed: +el.value });
      else if (el.dataset.edm === 'routeSpeed' && edRoutable(u)) edSet(u, { routeSpeed: Math.max(1, Math.min(3000, +el.value || 1)) });
      else if (el.dataset.edm === 'routeLoop' && edRoutable(u)) edSet(u, { routeLoop: el.value === '1' });
      else if (el.dataset.edm === 'wave' && !u.tpl) edSet(u, { wave: +el.value || null });
    }
    edRenderPanel(); edDraw();
    return;
  }
  if (!f) return;
  const u = edSelected(); if (!u) return;
  if (f === 'py' || f === 'pyaw' || f === 'pspeed') {
    edSetStart(f === 'py' ? { y: +el.value } : f === 'pyaw' ? { yaw: edYaw(+el.value) } : { speed: Math.max(0, Math.min(3000, +el.value || 0)) });
  } else if (f === 'count') edSet(u, { count: Math.max(1, Math.min(12, +el.value || 1)) });
  else if (f === 'attack') edSet(u, { attack: el.value });
  else if (f === 'speed') edSet(u, { speed: +el.value });
  else if (f === 'y') {
    const st = edUnitState(u);
    edSet(u, u.added ? { y: +el.value } : { x: st.x, z: st.z, y: +el.value });  // a height change keeps the unit where it is
  }
  edRenderPanel(); edDraw();
}
