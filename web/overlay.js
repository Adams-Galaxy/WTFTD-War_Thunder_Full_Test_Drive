/* WTFTD — My overlay: what the in-flight window shows and how it looks, and the alarms' thresholds and sounds.
   Kept in settings.json "overlay" (checked by alarms.clean). Every change is saved at once and the server sends the
   lines back filled with sample values, so the preview here is what the window draws. */
'use strict';

const OV = { cfg: null, screen: [3840, 2160], lines: [], input: null, timer: 0, profile: '', keys: new Map(), sounds: [], hud: {}, hudPlace: 'cockpit',
             trying: null, trialGlow: null, open: new Set() };  // trying: the alarm tried, {i, j, value}; open: the alarms unfolded, 'line:alarm'
const OV_MAX_BLOCKS = 3, OV_MAX_TESTS = 4, OV_MAX_RULES = 6, OV_GAP_MS = 700, OV_REPEAT_MS = 300;
const OV_SOUND_RATE = 22050, OV_SOUND_S = 15;  // what a sound is kept as: enough for an alarm, and it fits a request
const OV_TYPES = ['fighter', 'assault', 'bomber', 'helicopter', 'jet', 'prop', 'tank', 'ship'];
const OV_WHEN = ['always', 'gear', 'flaps', 'airbrake', 'alarm', 'own', 'log'];
const OV_LIMITS = { airframe: [93, 1400], gear: [90, 1000], flaps: [90, 700], load: [90, 1200], aoa: [90, 500] };  // an alarm on the aircraft's limit: %, Hz
const OV_PARTS = ['name', 'value', 'unit'];  // what of a line can flash with its alarm
// a line's value that has a limit or a reference: [its value against it, its %, what follows], what tells it's the line's
// (the first one found, in this order: the gear's and the flaps' speed is IAS too)
const OV_SHOWN = {
  turn: ['{turn} / {turn_ref} s', 'turn_pct', '', ['{turn}', '{turn_ref}', '{turn_pct']],
  fuel: ['{fuel} / {fuel_max} kg', 'fuel_pct', '', ['{fuel}', '{fuel_max}', '{fuel_pct']],
  gear: ['{ias} / {gear_max} km/h', 'gear_pct', '', ['{gear_max}', '{gear_pct']],
  flaps: ['{ias} / {flaps_max} km/h', 'flaps_pct', '', ['{flaps_max}', '{flaps_pct']],
  load: ['{g} / {g_lim}', 'load_pct', '', ['{g}', '{g_lim}', '{load_pct']],
  aoa: ['{aoa} / {aoa_crit}°', 'aoa_pct', '', ['{aoa}', '{aoa_crit}', '{aoa_pct']],
  mach: ['{mach} / {mne}', 'airframe_pct', '', ['{mach}', '{mne}']],
  airframe: ['{ias} / {vne} km/h', 'airframe_pct', ' {swept}', ['{ias}', '{vne}', '{airframe_pct']],
};
const OV_SHOWN_AS = ['value', 'percent', 'gauge', 'valuePct', 'valueGauge'];  // how: each one's text, see ovShownText
const OV_FONTS = ['Consolas', 'Cascadia Mono', 'Courier New', 'Lucida Console', 'Segoe UI', 'Bahnschrift', 'Arial', 'Tahoma', 'Verdana', 'Impact'];
const OV_VALUES = {
  vehicle: ['vehicle'],
  speed: ['speed', 'ias', 'tas', 'mach', 'hspeed', 'accel', 'sep', 'vne', 'mne', 'margin', 'airframe_pct', 'swept'],
  gearflaps: ['gear', 'gear_max', 'gear_pct', 'flaps', 'flaps_max', 'flaps_pct', 'airbrake'],
  flight: ['alt', 'vy', 'aoa', 'aoa_crit', 'aoa_low', 'aoa_pct', 'aos', 'g', 'g_max', 'g_lim', 'g_neg', 'load_pct', 'turn', 'turn_ref', 'turn_pct', 'turn_rate', 'turn_radius', 'roll', 'pitch', 'bank', 'heading'],
  engine: ['throttle', 'rpm', 'thrust', 'thrust_total', 'twr', 'mass', 'power', 'oil', 'fuel', 'fuel_max', 'fuel_pct', 'burn', 'fuel_time', 'range', 'wep', 'wep_s'],
  stats: ['kd', 'winrate', 'battles', 'kills', 'deaths', 'live_kd', 'live_kills', 'live_deaths'],
};

function ovShow(st) {
  OV.lines = st.lines;
  if (OV.trying) ovTrySend();  // a change while trying: tried again with it
  OV.screen = st.screen;
  OV.hud = st.hud || {};
  OV.map = st.map || [];
  OV.mapAt = [st.cfg.mapX, st.cfg.mapY, st.cfg.mapSize];  // how the server drew it: a drag or the grip changes it from there
  OV.drawnScale = [st.cfg, ...st.cfg.blocks].map(b => b.scale);  // the text blocks' size in the lines it sent
  ovDraw();
  ovDrawHud();
}

// the HUD of the place picked under Where, as the server drew it with the sample values
// the minimap's sample, and the frame the mouse takes it by; moved at once while dragged, drawn again when saved
function ovDrawMap() {
  const svg = $('#ovMapLive'), hit = $('#ovMapHit'), c = OV.cfg, shapes = OV.map || [];
  const k = $('#ovScreen').clientWidth / OV.screen[0], dx = (c.mapX - (OV.mapAt?.[0] ?? c.mapX)) * k, dy = (c.mapY - (OV.mapAt?.[1] ?? c.mapY)) * k;
  const [ox, oy] = OV.mapAt || [c.mapX, c.mapY], s = c.mapSize / (OV.mapAt?.[2] || c.mapSize);  // grown around its corner
  svg.setAttribute('viewBox', `0 0 ${OV.screen[0]} ${OV.screen[1]}`);
  svg.style.opacity = c.mapOpacity / 100;  // its own: the minimap has a window of its own
  svg.style.transformOrigin = `${ox * k}px ${oy * k}px`;
  svg.style.transform = `translate(${dx}px, ${dy}px) scale(${s})`;
  hudDraw(svg, shapes, c.hudColor, c.alert);
  const xs = [], ys = [];
  for (const s of shapes) {
    const pts = s[0] === 'p' ? s[1] : s[0] === 'l' ? s.slice(1, 5) : s.slice(1, 3);
    pts.forEach((v, i) => (i % 2 ? ys : xs).push(v));
  }
  hit.classList.toggle('hidden', !xs.length);
  if (xs.length) Object.assign(hit.style, { left: `${(ox + (Math.min(...xs) - ox) * s) * k + dx}px`, top: `${(oy + (Math.min(...ys) - oy) * s) * k + dy}px`,
                                            width: `${(Math.max(...xs) - Math.min(...xs)) * s * k}px`, height: `${(Math.max(...ys) - Math.min(...ys)) * s * k}px` });
}

function ovDrawHud() {
  const svg = $('#ovHudLive'), c = OV.cfg;
  svg.setAttribute('viewBox', `0 0 ${OV.screen[0]} ${OV.screen[1]}`);
  svg.style.opacity = c.opacity / 100;
  hudDraw(svg, OV.hud[OV.hudPlace] || [], c.hudColor, c.alert);
  ovDrawMap();
  $$('#ovHudPlace button').forEach(b => b.classList.toggle('active', b.dataset.place === OV.hudPlace));
  $$('#view-overlay [data-hudplace]').forEach(row => row.classList.toggle('hidden', row.dataset.hudplace !== OV.hudPlace));
}

// saved a moment after the last change, not at every key
function ovSave() {
  clearTimeout(OV.timer);
  OV.timer = setTimeout(ovFlush, 150);
}
async function ovFlush(extra = {}) {
  clearTimeout(OV.timer);
  OV.timer = 0;
  try { ovShow(await api('overlay', { cfg: OV.cfg, profile: OV.profile, ...extra })); } catch (e) { toastErr(e); }
}

// a text block on the picture: kept from one drawing to the next, a drag holds on to it
function ovBlockEl(i) {
  const box = $('#ovScreen');
  let el = box.querySelector(`.ov-text[data-b="${i}"]`);
  if (!el) {
    el = Object.assign(document.createElement('div'), { className: 'ov-text' });
    el.dataset.b = i;
    box.append(el);
  }
  return el;
}

function ovDraw() {
  const box = $('#ovScreen'), c = OV.cfg;
  box.style.aspectRatio = `${OV.screen[0]} / ${OV.screen[1]}`;
  const first = c.lines.flatMap(l => l.rules || []).find(r => r.glow);  // the first alarm with a halo, as the window shows it
  const glow = OV.trying ? OV.trialGlow : first && [first.color || c.alert, first.glowSize];  // or the tried alarm's, while it's on
  box.style.boxShadow = glow ? `inset 0 0 ${box.clientHeight * glow[1] / 100}px ${glow[0]}` : '';

  const k = box.clientWidth / OV.screen[0];
  const look = { fontFamily: `"${c.font}", monospace`, fontWeight: c.bold ? 700 : 400, fontStyle: c.italic ? 'italic' : 'normal' };
  const stroke = scale => (c.outline ? `${2 * c.outline * scale}px ${c.outlineColor}` : '');
  const html = (rows, scale) => rows.map(([s, color, size, blinks, , parts]) => `<div style="color:${esc(color)};font-size:${size * scale}px;margin-bottom:${c.spacing * scale}px">${(parts || []).map(([p, tint, flash, off]) => `<span class="${flash ? 'ov-blink' : ''}" style="color:${esc(tint)};--ov-flash:${flash === true ? 400 : flash}ms;--ov-off:${esc(off || 'transparent')}">${esc(p)}</span>`).join('') || '&nbsp;'}</div>`).join('');
  [c, ...c.blocks].forEach((spot, i) => {
    const text = ovBlockEl(i), rows = OV.lines.filter(l => (l[4] || 0) === i), boxed = spot.frame || spot.background, pad = boxed ? (10 + spot.frame) * k : 0;
    Object.assign(text.style, look, { left: `${spot.x * k}px`, top: `${spot.y * k}px`, opacity: c.opacity / 100, webkitTextStroke: stroke(k),
                                      textShadow: c.outline ? '' : `0 0 ${Math.max(1, 3 * k)}px #000, 0 0 ${Math.max(1, 2 * k)}px #000`,  // the overlay's halo
                                      gridTemplateRows: `repeat(${Math.max(1, Math.ceil(rows.length / spot.columns))}, auto)`, columnGap: `${c.size * k}px`,
                                      margin: `${-pad}px 0 0 ${-pad}px`, padding: boxed ? `${10 * k}px` : '',
                                      border: spot.frame ? `${Math.max(1, spot.frame * k)}px solid ${spot.frameColor}` : '',
                                      background: spot.background ? `color-mix(in srgb, ${spot.background} ${spot.bgOpacity}%, transparent)` : '' });
    text.innerHTML = html(rows, k) + '<i class="ov-grip" aria-hidden="true"></i>';
    const grown = spot.scale / (OV.drawnScale?.[i] || spot.scale);  // at once while the grip moves, drawn again when saved
    Object.assign(text.style, { transformOrigin: '0 0', transform: grown === 1 ? '' : `scale(${grown})` });
  });
  box.querySelectorAll('.ov-text').forEach(el => { if (+el.dataset.b > c.blocks.length) el.remove(); });
  // the same text big enough to read: the size of the letters compared with each other, not on the screen
  const zoom = $('#ovZoom'), scale = 22 / Math.max(c.size, 1);
  Object.assign(zoom.style, look, { webkitTextStroke: stroke(scale) });
  zoom.innerHTML = html(OV.lines, scale);
}

const ovOpt = (v, label, on) => `<option value="${esc(v)}"${v === on ? ' selected' : ''}>${esc(label)}</option>`;
const ovSounds = on => ovOpt('', t('ov.soundBeep'), on) + OV.sounds.map(s => ovOpt(s, s.replace(/\.wav$/i, ''), on)).join('');
// a sound is picked where it's used: the list, and the button that adds a file to it. pick: what the new file goes to
const ovSoundHTML = (attr, on, pick) => `<div class="ov-sound"><label class="ov-mini"><span>${esc(t('ov.sound'))}</span><select ${attr}>${ovSounds(on)}</select></label>
      <button class="btn btn-sm" data-ovpick="${pick}">${esc(t('ov.soundAdd'))}</button></div>`;
const ovField = (label, html) => `<label class="ov-mini"><span>${esc(label)}</span>${html}</label>`;

// the values a condition can test: numbers only
const ovCondNames = () => Object.values(OV_VALUES).flat().filter(x => !['swept', 'fuel_time', 'wep', 'vehicle'].includes(x));
// one condition of a line's showing (if) or its own alert (rule); n: 0 for the first, then its place in test.more
function ovCondHTML(part, n, cond, join) {
  const names = ovCondNames();
  const first = n === 0, value = `<select data-oc="${part}.value">${first && part !== 'rule' ? ovOpt('', t('ov.redNone'), cond?.value ?? '') : ''}${names.map(x => ovOpt(x, t('ov.v.' + x), cond?.value)).join('')}</select>`;
  const link = first ? '<span></span>' : `<select data-oc="${part}.join"${n > 1 ? ' disabled' : ''}>${ovOpt('and', t('ov.and'), join)}${ovOpt('or', t('ov.or'), join)}</select>`;
  return `<div class="ov-cond" data-n="${n}">${link}${value}${cond ? `<select class="ov-op" data-oc="${part}.op">${['>', '<'].map(o => ovOpt(o, o, cond.op)).join('')}</select>
      <input type="number" step="any" data-oc="${part}.at" value="${esc(cond.at)}">` : ''}${first ? '' : `<button class="icon-btn" data-ocdel="${part}" title="${esc(t('action.delete'))}">${icon('x', 'ic-sm')}</button>`}</div>`;
}

// a list of conditions: a line's showing (if), or one of its alarms on a value (rule)
function ovTestHTML(part, label, test) {
  const conds = [test, ...(test?.more || [])].map((x, n) => ovCondHTML(part, n, x, test?.join)).join('');
  const add = test && (test.more?.length || 0) < OV_MAX_TESTS - 1 ? `<button class="btn btn-sm btn-ghost" data-ocadd="${part}">${esc(t('ov.addCond'))}</button>` : '';
  return `<div class="ov-test"><span class="ov-test-name">${esc(label)}</span><div class="ov-conds">${conds}${add}</div></div>`;
}

// one of a line's alarms: on one of the aircraft's limits (in % of it), or on any value. Its thresholds (red, beep, the
// value where the beeps become continuous), its sound, and the line in it: colour, the parts that flash, repeat, delay
// one of a line's alarms: folded, a line that says what it does and its buttons; unfolded, three groups, each field the
// same width: when it goes off, how it sounds, how the line looks in it
function ovRuleHTML(r, i, j) {
  const tried = OV.trying?.i === i && OV.trying?.j === j, open = tried || OV.open.has(`${i}:${j}`);
  const name = r.limit ? t('ov.alarm.' + r.limit) : t('ov.alarmValue');
  const head = `<div class="ov-rule-head"><span class="ov-dot" style="background:${esc(r.color || OV.cfg.alert)}"></span>
      <b>${esc(name)}</b><span class="ov-rule-sum">${esc(ovRuleSummary(r))}</span>
      <span class="ov-rule-btns"><button class="btn btn-sm" data-ovruletest>${esc(t('ov.test'))}</button>
        <button class="btn btn-sm${tried ? ' btn-primary' : ''}" data-ortrybtn>${esc(t(tried ? 'ov.tryStop' : 'ov.try'))}</button>
        <button class="btn btn-sm btn-ghost" data-ortoggle aria-expanded="${open}">${esc(t(open ? 'action.close' : 'ov.edit'))}</button>
        <button class="icon-btn btn-danger" data-ordel title="${esc(t('ov.removeAlarm'))}">${icon('trash')}</button></span></div>`;
  const range = ovTryRange(r);
  const trial = tried ? `<div class="ov-try"><input type="range" data-ortry min="${range[0]}" max="${range[1]}" step="${range[2]}" value="${OV.trying.value}">
      <output>${esc(ovTryText(r, OV.trying.value))}</output><small class="muted">${esc(t('ov.tryHint'))}</small></div>` : '';
  if (!open) return `<div class="ov-rule${tried ? ' ov-tried' : ''}" data-j="${j}">${head}${trial}</div>`;
  const num = (key, label, value, extra = '') => ovField(label, `<input type="number" data-or="${key}" value="${value ?? ''}"${extra}>`);
  const sw = (key, label, on) => `<label class="switch"><input type="checkbox" data-or="${key}"${on ? ' checked' : ''}><span class="sw"></span><span>${esc(t(label))}</span></label>`;
  const sec = (title, html) => `<div class="ov-sec"><h4>${esc(t(title))}</h4><div class="ov-dyn-row">${html}</div></div>`;
  const gap = num('gap', t('ov.gap'), r.gap, ` min="0" max="5000" step="50"${r.full == null ? ' disabled' : ''}`);
  const withBeep = ` placeholder="${esc(t('ov.withBeep'))}"`, after = num('after', t('ov.after'), r.after || '', ' min="0" max="10000" step="100" placeholder="0"');
  const trigger = r.limit
    ? sec('ov.sec.trigger', `${num('red', t('ov.redFrom'), r.red, ` min="1" max="200"${withBeep}`)}${num('at', t('ov.beepFrom'), r.at, ' min="1" max="200"')}${after}
        ${sw('dyn', 'ov.dynamic', r.full != null)}${num('full', t('ov.fullAtPct'), r.full ?? 100, ` min="1" max="200"${r.full == null ? ' disabled' : ''}`)}${gap}`)
    : `<div class="ov-sec"><h4>${esc(t('ov.sec.trigger'))}</h4>${ovTestHTML('rule', t('ov.ownAlert'), r)}<div class="ov-dyn-row">
        ${num('red', t('ov.redFromValue'), r.red, ` step="any"${withBeep}`)}${num('full', t('ov.fullAt'), r.full, ` step="any" placeholder="${esc(t('ov.noFull'))}"`)}${gap}${after}</div></div>`;
  const sound = sec('ov.sec.sound', `${ovSoundHTML('data-or="sound"', r.sound, `line:${i}:${j}`)}
      ${num('hz', t('ov.pitch'), r.hz, ` min="37" max="32767" step="50"${r.sound ? ' disabled' : ''}`)}${num('ms', t('ov.length'), r.ms, ` min="10" max="2000" step="10"${r.sound ? ' disabled' : ''}`)}
      ${num('repeat', t('ov.repeat'), r.repeat || '', ` min="0" max="10000" step="50" placeholder="${OV_REPEAT_MS}"`)}`);
  const look = sec('ov.sec.look', `<label class="ov-mini ov-swatch"><span>${esc(t('ov.alarmColor'))}</span><span class="ov-color"><input type="color" data-or="color" value="${esc(r.color || OV.cfg.alert)}">
        <button class="icon-btn${r.color ? '' : ' hidden'}" data-orclear title="${esc(t('ov.sameAsAlert'))}">${icon('x', 'ic-sm')}</button></span></label>
      <div class="ov-mini ov-flash"><span>${esc(t('ov.flash'))}</span><div class="ov-parts">${OV_PARTS.map(x => `<label><input type="checkbox" data-orblink="${x}"${(r.blink || []).includes(x) ? ' checked' : ''}>${esc(t('ov.part.' + x))}</label>`).join('')}</div></div>
      ${num('flashMs', t('ov.flashMs'), r.flashMs || '', ` min="0" max="4000" step="50" placeholder="${esc(t('ov.withBeeps'))}"`)}
      ${sw('glow', 'ov.glow', r.glow)}${num('glowSize', t('ov.glowSize'), r.glowSize, ` min="3" max="50"${r.glow ? '' : ' disabled'}`)}${sw('glowFlash', 'ov.glowFlash', r.glowFlash)}`);
  return `<div class="ov-rule open${tried ? ' ov-tried' : ''}" data-j="${j}">${head}${trial}<div class="ov-rule-body">${trigger}${sound}${look}</div></div>`;
}
// what an alarm does, in a few words: its thresholds, its break, its own sound, its glow
function ovRuleSummary(r) {
  const pct = r.limit ? ' %' : '', cond = r.limit ? '' : `${t('ov.v.' + r.value)} ${r.op} ${r.at}${r.more?.length ? ` +${r.more.length}` : ''}`;
  const bits = r.limit ? [`${t('ov.sum.red')} ${r.red ?? r.at}${pct}`, `${t('ov.sum.beep')} ${r.at}${pct}`] : [cond, r.red != null ? `${t('ov.sum.red')} ${r.red}` : ''];
  if (r.full != null) bits.push(`${t('ov.sum.full')} ${r.full}${pct}`);
  if (r.sound) bits.push(`♪ ${r.sound.replace(/\.wav$/i, '')}`);
  if (r.glow) bits.push(t('ov.glow').toLowerCase());
  return bits.filter(Boolean).join(' · ');
}

// Try: the slider of an alarm's value, from where it's quiet to past its break; a limit's in % of it
function ovTryRange(r) {
  if (r.limit) return [0, Math.max(120, (r.full ?? 100) + 10), 0.5];
  const marks = [r.at, r.red, r.full].filter(Number.isFinite), lo = Math.min(...marks), hi = Math.max(...marks);
  const span = Math.max(hi - lo, Math.abs(r.at) * 0.25, 1), round = v => +v.toPrecision(4);
  return [round(lo >= 0 ? Math.max(0, lo - span * 0.6) : lo - span * 0.6), round(hi + span * 0.6), span >= 50 ? 1 : span >= 5 ? 0.1 : 0.01];
}
// where a trial starts: just short of the alarm
function ovTryStart(r) {
  const [min, max] = ovTryRange(r), first = r.op === '<' ? Math.max(r.at, r.red ?? r.at) : Math.min(r.at, r.red ?? r.at);
  return Math.min(max, Math.max(min, r.op === '<' ? first + (max - min) * 0.1 : first - (max - min) * 0.1));
}
const ovTryText = (r, v) => r.limit ? `${(+v).toFixed(1)} %` : `${t('ov.v.' + r.value)} ${+(+v).toPrecision(6)}`;
// the trial to the server, the newest value only: it draws the overlay on the screen and beeps
async function ovTrySend() {
  if (OV.trySending) { OV.tryAgain = true; return; }
  OV.trySending = true;
  try {
    const tr = OV.trying, res = await api('overlay-try', tr ? { profile: OV.profile, line: tr.i, rule: tr.j, value: tr.value } : { profile: OV.profile, on: false });
    OV.lines = res.lines;
    OV.trialGlow = res.glow;
    if (OV.trying && !res.on) { OV.trying = null; ovRenderLines(); }  // refused (not Windows) or gone
    ovDraw();
  } catch (e) { toastErr(e); }
  OV.trySending = false;
  if (OV.tryAgain) { OV.tryAgain = false; ovTrySend(); }
}
setInterval(() => { if (OV.trying) ovTrySend(); }, 20000);  // still there: the server stops a trial left a minute alone
function ovTryStop() {
  if (!OV.trying) return;
  OV.trying = null;
  ovTrySend();
}

// the value of a line that has a limit or a reference: by what its text shows, else by its alarm on a limit (a line
// written by hand, its name only); null for the others (altitude, heading...)
function ovShownKind(l) {
  const shown = Object.keys(OV_SHOWN).find(k => OV_SHOWN[k][3].some(x => l.text.includes(x)));
  return shown || (l.rules || []).find(x => x.limit && OV_SHOWN[x.limit])?.limit || null;
}
// what follows the line's name, shown so; bar: its gauge's spec, 'bar', 'bar20' or 'bar20/5'
function ovShownText(kind, how, bar = 'bar') {
  const [value, pct, tail] = OV_SHOWN[kind];
  return { value, percent: `{${pct}} %`, gauge: `{${pct}:${bar}}`, valuePct: `${value}  {${pct}} %`, valueGauge: `${value}  {${pct}:${bar}}` }[how] + tail;
}
// a line's gauge: [its blocks, the % each is worth, that worth set by hand], 10 blocks of 10 % unless its text says;
// and back to its spec
function ovBarOf(l) {
  const m = l.text.match(/:bar(\d*)(?:\/([\d.]+))?\}/), size = Math.min(40, Math.max(1, +(m?.[1] || 10)));
  return [size, +(m?.[2] || 0) || +(100 / size).toFixed(1), !!m?.[2]];
}
const ovBarSpec = (size, step) => (size === 10 && step === 10 ? 'bar' : step === +(100 / size).toFixed(1) ? `bar${size}` : `bar${size}/${step}`);
function ovShownAs(l, kind) {
  const at = l.text.indexOf('{'), rest = at < 0 ? '' : l.text.slice(at).trim();
  const spec = ovBarSpec(...ovBarOf(l).slice(0, 2)), same = OV_SHOWN_AS.find(how => ovShownText(kind, how, spec).trim() === rest);  // as the buttons wrote it
  if (same) return same;
  const pct = OV_SHOWN[kind][1], bar = l.text.includes(`{${pct}:bar`), num = l.text.includes(`{${pct}}`), value = l.text.includes(OV_SHOWN[kind][0].match(/\{\w+\}/)[0]);
  return bar ? (value ? 'valueGauge' : 'gauge') : num ? (value ? 'valuePct' : 'percent') : 'value';  // written by hand
}
// the line's buttons, under its text: its value, its %, a gauge, or the value with one of them
function ovShownHTML(l, i) {
  const kind = ovShownKind(l);
  if (!kind) return '';
  const now = ovShownAs(l, kind), [size, step] = ovBarOf(l);
  const gauge = now === 'gauge' || now === 'valueGauge' ? `<span class="ov-bar-set">${ovField(t('ov.barSize'), `<input type="number" data-olbar="size" min="1" max="40" value="${size}">`)}
      ${ovField(t('ov.barStep'), `<input type="number" data-olbar="step" min="0.1" max="100" step="any" value="${step}">`)}</span>` : '';
  return `<div class="ov-showas"><span>${esc(t('ov.showAs'))}</span>${OV_SHOWN_AS.map(how => `<label><input type="radio" name="ovshown-${i}" data-olshown value="${how}"${how === now ? ' checked' : ''}>${esc(t('ov.shown.' + how))}</label>`).join('')}${gauge}</div>`;
}
// rewrites what follows the line's name (the text before its first value)
function ovSetShown(l, how, bar = ovBarSpec(...ovBarOf(l).slice(0, 2))) {
  const kind = ovShownKind(l), at = l.text.indexOf('{'), name = at < 0 ? `${l.text.trimEnd()} ` : l.text.slice(0, at);
  if (kind) l.text = name + ovShownText(kind, how, bar);
}

// a line's alarms, in sight under it, and a menu to add one
function ovLineAlarmsHTML(l, i) {
  const rules = l.rules || [];
  const kinds = [...Object.keys(OV_LIMITS).map(a => ovOpt(a, t('ov.alarm.' + a), '')), ovOpt('value', t('ov.alarmValue'), '')].join('');
  const add = rules.length < OV_MAX_RULES ? `<label class="ov-mini ov-add-alarm"><span>${esc(t('ov.addAlarm'))}</span><select data-oradd><option value="">…</option>${kinds}</select></label>` : '';
  return `<div class="ov-line-alarms">${rules.length ? `<span class="ov-alarms-title">${esc(t('ov.lineAlarms'))}</span>` : ''}${rules.map((r, j) => ovRuleHTML(r, i, j)).join('')}${add}</div>`;
}
// where a condition lives: [the object holding it, its key]; a line's 'if', or one of its alarms
function ovOwner(el, part) {
  const line = OV.cfg.lines[+el.closest('.ov-line').dataset.i];
  return part === 'rule' ? [line.rules, +el.closest('.ov-rule').dataset.j] : [line, part];
}
const ovRuleOf = el => ovOwner(el, 'rule')[0][+el.closest('.ov-rule').dataset.j];
// a new alarm: on one of the aircraft's limits, or on the line's first value (any above 0, else the G load above 9)
function ovNewRule(l, kind) {
  const common = { more: [], join: 'and', ms: 150, sound: '', red: null, gap: OV_GAP_MS, color: '', blink: [], repeat: 0, after: 0, glow: false, glowSize: 18, glowFlash: false, flashMs: 0 };
  if (OV_LIMITS[kind]) return { ...common, limit: kind, value: '', op: '>', at: OV_LIMITS[kind][0], full: 100, hz: OV_LIMITS[kind][1] };
  const value = (l.text.match(/\{(\w+)/) || [])[1], known = ovCondNames().includes(value);
  return { ...common, limit: '', value: known ? value : 'g', op: '>', at: known ? 0 : 9, full: null, hz: 1000 };
}

function ovLineColor(l, key, label) {
  return `<label class="ov-mini ov-swatch"><span>${esc(t(label))}</span><span class="ov-color"><input type="color" data-ol="${key}" value="${esc(l[key] || l.color || OV.cfg.color)}">
      <button class="icon-btn${l[key] ? '' : ' hidden'}" data-olclear="${key}" title="${esc(t('ov.sameAsText'))}">${icon('x', 'ic-sm')}</button></span></label>`;
}

function ovMoreHTML(l, i) {
  const on = (key, label) => `<label class="switch"><input type="checkbox" data-ol="${key}"${l[key] ? ' checked' : ''}><span class="sw"></span><span>${esc(t(label))}</span></label>`;
  return `<details class="ov-more"${l.open ? ' open' : ''}><summary>${esc(t('ov.more'))}</summary><div class="ov-opts">
      <div class="ov-switches">${on('hideNA', 'ov.hideNA')}</div>
      <div class="ov-line-look">${ovLineColor(l, 'valueColor', 'ov.valueColor')}${ovLineColor(l, 'unitColor', 'ov.unitColor')}</div>
      ${ovTestHTML('if', t('ov.showIf'), l.if)}</div></details>`;
}

// every block the same card, the main one too
function ovRenderBlocks() {
  $('#ovBlocks').innerHTML = [OV.cfg, ...OV.cfg.blocks].map((b, i) => {
    const num = (key, label, extra = '') => `<div class="field"><label>${esc(label)}</label><input type="number" data-ob="${key}" value="${b[key]}"${extra}></div>`;
    return `<div class="ov-card ov-block" data-i="${i}">
      <div class="row-between"><h3 class="ov-h">${esc(t('ov.blockN', { n: i + 1 }))}</h3>${i ? `<button class="icon-btn btn-danger" data-obdel title="${esc(t('action.delete'))}">${icon('trash')}</button>` : ''}</div>
      <div class="field-row">${num('x', 'X')}${num('y', 'Y')}</div>
      <div class="field"><label>${esc(t('ov.blockTitle'))}</label><input type="text" data-ob="title" value="${esc(b.title || '')}" maxlength="120"></div>
      <div class="field-row"><div class="field"><label>${esc(t('ov.feed'))}</label><select data-ob="feed">${['', 'chat', 'log'].map(f => ovOpt(f, t('ov.feed.' + (f || 'lines')), b.feed || '')).join('')}</select></div>
        ${num('rows', t('ov.feedRows'), ` min="1" max="20"${b.feed ? '' : ' disabled'}`)}</div>
      <div class="field-row">${num('scale', t('ov.blockSize'), ' min="10" max="400"')}${num('columns', t('ov.columns'), ' min="1" max="4"')}</div>
      <div class="field-row">${num('frame', t('ov.frame'), ' min="0" max="8"')}<div class="field"><label>${esc(t('ov.frameColor'))}</label><input type="color" data-ob="frameColor" value="${esc(b.frameColor)}"${b.frame ? '' : ' disabled'}></div></div>
      <label class="switch"><input type="checkbox" data-ob="hasBg"${b.background ? ' checked' : ''}><span class="sw"></span><span>${esc(t('ov.background'))}</span></label>
      <div class="field-row"><div class="field"><label>${esc(t('ov.bgColor'))}</label><input type="color" data-ob="background" value="${esc(b.background || b.lastBg || '#000000')}"${b.background ? '' : ' disabled'}></div>
        <div class="field"><label>${esc(t('ov.bgOpacity'))}</label><select data-ob="bgOpacity"${b.background ? '' : ' disabled'}>${[100, 75, 50, 25].map(n => ovOpt(n, `${n} %`, b.bgOpacity)).join('')}</select></div></div>
      <button class="btn btn-sm" data-obline>${esc(t('ov.addLine'))}</button></div>`;
  }).join('');
  $('#ovAddBlock').classList.toggle('hidden', OV.cfg.blocks.length >= OV_MAX_BLOCKS);
}

// a sound of any kind the browser can read (mp3, ogg, wav...) as a short mono .wav, in base64
async function ovSoundData(file) {
  const raw = await new OfflineAudioContext(1, 1, OV_SOUND_RATE).decodeAudioData(await file.arrayBuffer());
  const context = new OfflineAudioContext(1, Math.max(1, Math.ceil(Math.min(raw.duration, OV_SOUND_S) * OV_SOUND_RATE)), OV_SOUND_RATE);
  const source = Object.assign(context.createBufferSource(), { buffer: raw });
  source.connect(context.destination);
  source.start();
  const pcm = (await context.startRendering()).getChannelData(0), out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  [...'RIFF'].forEach((c, i) => out.setUint8(i, c.charCodeAt(0)));
  out.setUint32(4, 36 + pcm.length * 2, true);
  [...'WAVEfmt '].forEach((c, i) => out.setUint8(8 + i, c.charCodeAt(0)));
  [[16, 16, 4], [20, 1, 2], [22, 1, 2], [24, OV_SOUND_RATE, 4], [28, OV_SOUND_RATE * 2, 4], [32, 2, 2], [34, 16, 2]].forEach(([at, v, n]) => out[n === 4 ? 'setUint32' : 'setUint16'](at, v, true));
  [...'data'].forEach((c, i) => out.setUint8(36 + i, c.charCodeAt(0)));
  out.setUint32(40, pcm.length * 2, true);
  pcm.forEach((v, i) => out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 32767, true));
  return new Promise((done, fail) => Object.assign(new FileReader(), { onload: e => done(e.target.result.split(',')[1]), onerror: fail }).readAsDataURL(new Blob([out.buffer])));
}

function ovAddLine(block) {
  OV.cfg.lines.push({ text: '', when: 'always', color: '', size: 0, block, rules: [] });
  ovRenderLines();
  ovTab('lines');
  $$('#ovLines .ov-tpl').pop().focus();
  ovSave();
}

function ovRenderLines() {
  const opt = ovOpt, blocks = OV.cfg.blocks.length;
  $('#ovLines').innerHTML = OV.cfg.lines.map((l, i) => `<div class="ov-line${blocks ? ' ov-blocks' : ''}" data-i="${i}">
      <div class="ov-move"><button class="icon-btn" data-ovmove="-1"${i ? '' : ' disabled'} title="${esc(t('ov.up'))}">▲</button><button class="icon-btn" data-ovmove="1"${i < OV.cfg.lines.length - 1 ? '' : ' disabled'} title="${esc(t('ov.down'))}">▼</button></div>
      <input type="text" class="ov-tpl" data-ol="text" value="${esc(l.text)}" maxlength="120" spellcheck="false">
      <label class="ov-mini"><span>${esc(t('ov.when'))}</span><select data-ol="when">${OV_WHEN.map(w => opt(w, t('ov.when.' + w), l.when)).join('')}</select></label>
      ${blocks ? ovField(t('ov.block'), `<select data-ol="block">${Array.from({ length: blocks + 1 }, (_, n) => opt(n, n + 1, l.block || 0)).join('')}</select>`) : ''}
      <label class="ov-mini ov-num"><span>${esc(t('ov.lineSize'))}</span><input type="number" data-ol="size" min="0" max="400" value="${l.size || ''}" placeholder="${esc(OV.cfg.size)}"></label>
      <label class="ov-mini ov-swatch"><span>${esc(t('ov.lineColor'))}</span><input type="color" data-ol="color" value="${esc(l.color || OV.cfg.color)}"></label>
      <button class="icon-btn ov-clear${l.color ? '' : ' hidden'}" data-ovnocolor title="${esc(t('ov.noColor'))}">${icon('x', 'ic-sm')}</button>
      <button class="icon-btn btn-danger" data-ovdel title="${esc(t('action.delete'))}">${icon('trash')}</button>${ovShownHTML(l, i)}${ovLineAlarmsHTML(l, i)}${ovMoreHTML(l, i)}</div>`).join('');
}

// the picture behind the text: the player's own screenshot, shrunk to what the page shows, kept in this browser profile
function ovShowBg() {
  const url = store.get('overlayBg', ''), box = $('#ovScreen');
  box.style.backgroundImage = url ? `url("${url}")` : '';
  box.classList.toggle('has-bg', !!url);
  $('#ovBgRemove').classList.toggle('hidden', !url);
}
async function ovSetBg(file) {
  try {
    const img = await createImageBitmap(file), k = Math.min(1, 1600 / img.width), c = document.createElement('canvas');
    c.width = img.width * k;
    c.height = img.height * k;
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    store.set('overlayBg', c.toDataURL('image/jpeg', .8));
    ovShowBg();
  } catch (e) { toastErr(e); }
}

const ovProfileName = key => (!key ? t('ov.profile.all') : key.startsWith('type:') ? t('ov.type.' + key.slice(5)) : I18N.unit(key));

function ovRenderProfiles(st) {
  OV.profile = st.profile;
  $('#ovProfile').innerHTML = ['', ...st.profiles].map(k => `<option value="${esc(k)}"${k === st.profile ? ' selected' : ''}>${esc(ovProfileName(k))}</option>`).join('');
  $('#ovProfileDelete').classList.toggle('hidden', !st.profile);
  $('#ovActive').textContent = st.aircraft ? t('ov.active', { aircraft: I18N.unit(st.aircraft), profile: ovProfileName(st.active) }) : '';
}

// the colours that can follow the text's: a cross takes them back to it
const ovFollowed = key => OV.cfg[key] || OV.cfg.color;
function ovShowClears() {
  $$('#view-overlay [data-ovclear]').forEach(b => b.classList.toggle('hidden', !OV.cfg[b.dataset.ovclear]));
}

function ovRender(st) {
  OV.cfg = st.cfg;
  OV.sounds = st.sounds;
  OV.device = st.device;
  $('#ovDevice').innerHTML = ovOpt('', t('ov.deviceDefault'), st.device) + st.devices.map(d => ovOpt(d, d, st.device)).join('');
  ovRenderProfiles(st);
  $('#ovEnabled').checked = st.enabled;
  $('#ovOnScreen').checked = st.onScreen;
  $$('#view-overlay [data-ov]').forEach(el => {
    if (el.type === 'checkbox') el.checked = OV.cfg[el.dataset.ov];
    else el.value = el.type === 'color' ? ovFollowed(el.dataset.ov) : OV.cfg[el.dataset.ov];
  });
  ovShowClears();
  $$('#view-overlay [data-ovkey]').forEach(el => { el.value = OV.cfg[el.dataset.ovkey + 'Name']; });
  ovRenderBlocks();
  ovRenderLines();
  ovShow(st);
}

async function openOverlayView() {
  try { ovRender(await api('overlay/' + encodeURIComponent(OV.profile))); } catch (e) { toastErr(e); }
}

// leaving the tab takes the sample off the screen
function leaveOverlayView() {
  ovTryStop();
  if ($('#ovOnScreen').checked) {
    $('#ovOnScreen').checked = false;
    api('overlay-preview', { on: false }).catch(() => {});
  }
}

function ovInsert(name) {
  const edited = OV.input?.isConnected ? OV.input : null, input = edited || $$('#ovLines .ov-tpl').pop();
  if (!input) return;
  input.setRangeText(`{${name}}`, edited ? input.selectionStart : input.value.length, edited ? input.selectionEnd : input.value.length, 'end');
  input.focus();
  input.dispatchEvent(new Event('input', { bubbles: true }));
}

function ovTab(tab) {
  $$('#ovTabs button').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  $$('#view-overlay .ov-panel').forEach(p => p.classList.toggle('hidden', p.dataset.panel !== tab));
  store.set('overlayTab', tab);
}

// the minimap taken by its frame: its place in px, like a text block's
function ovDragMap(e) {
  const hit = e.target, c = OV.cfg, k = $('#ovScreen').clientWidth / OV.screen[0];
  const start = { x: c.mapX, y: c.mapY, px: e.clientX, py: e.clientY };
  e.preventDefault();
  hit.setPointerCapture(e.pointerId);
  const move = ev => {
    c.mapX = Math.round(start.x + (ev.clientX - start.px) / k);
    c.mapY = Math.round(start.y + (ev.clientY - start.py) / k);
    $('#ovMapX').value = c.mapX;
    $('#ovMapY').value = c.mapY;
    ovDrawMap();
    ovSave();
  };
  hit.addEventListener('pointermove', move);
  hit.addEventListener('pointerup', () => hit.removeEventListener('pointermove', move), { once: true });
}

// a text block's size (its %) or the minimap's (px) from the grip in its corner, with the width the mouse gives it
function ovResize(e, grip) {
  const owner = grip.parentElement, c = OV.cfg, k = $('#ovScreen').clientWidth / OV.screen[0], map = owner.id === 'ovMapHit';
  const i = map ? -1 : +owner.dataset.b, spot = map ? c : i ? c.blocks[i - 1] : c, key = map ? 'mapSize' : 'scale';
  const width = map ? c.mapSize * k : owner.getBoundingClientRect().width, start = spot[key], x0 = e.clientX;
  e.preventDefault();
  owner.setPointerCapture(e.pointerId);  // the block, not its grip: drawing the block again replaces the grip
  const move = ev => {
    const grown = start * Math.max(0.05, (width + ev.clientX - x0) / width);
    spot[key] = Math.round(map ? Math.min(3000, Math.max(80, grown)) : Math.min(400, Math.max(10, grown)));
    const field = map ? $('#ovMapSize') : $(`.ov-block[data-i="${i}"] [data-ob="scale"]`);
    if (field) field.value = spot[key];
    if (map) ovDrawMap();
    else ovDraw();
    ovSave();
  };
  owner.addEventListener('pointermove', move);
  owner.addEventListener('pointerup', () => owner.removeEventListener('pointermove', move), { once: true });
}

function ovDrag() {
  const box = $('#ovScreen');
  box.addEventListener('pointerdown', e => {
    const grip = e.target.closest('.ov-grip');
    if (grip) return ovResize(e, grip);
    if (e.target.id === 'ovMapHit') return ovDragMap(e);
    const text = e.target.closest('.ov-text');
    if (!text) return;
    e.preventDefault();
    text.setPointerCapture(e.pointerId);
    const i = +text.dataset.b, spot = i ? OV.cfg.blocks[i - 1] : OV.cfg, card = $(`.ov-block[data-i="${i}"]`);
    const k = box.clientWidth / OV.screen[0], start = { x: spot.x, y: spot.y, px: e.clientX, py: e.clientY };
    const move = ev => {
      spot.x = Math.round(start.x + (ev.clientX - start.px) / k);
      spot.y = Math.round(start.y + (ev.clientY - start.py) / k);
      $('[data-ob="x"]', card).value = spot.x;
      $('[data-ob="y"]', card).value = spot.y;
      ovDraw();
      ovSave();
    };
    text.addEventListener('pointermove', move);
    text.addEventListener('pointerup', () => text.removeEventListener('pointermove', move), { once: true });
  });
}

function bindOverlay() {
  $('[data-view="overlay"]').classList.toggle('hidden', !S.status?.alarms);  // Windows only
  OV.keys = new Map([...OV_TYPES.map(k => [t('ov.type.' + k), 'type:' + k]),
                     ...S.vehicles.filter(v => v.c === 'air' || v.c === 'heli').map(v => [I18N.unit(v.id), v.id])]);
  $('#ovNewList').innerHTML = [...OV.keys.keys()].map(n => `<option value="${esc(n)}">`).join('');
  $('#ovProfile').addEventListener('change', async e => {
    if (OV.timer) await ovFlush();  // what was being typed goes to the overlay it was typed for
    OV.profile = e.target.value;
    ovRender(await api('overlay/' + encodeURIComponent(OV.profile)));
    if ($('#ovOnScreen').checked) api('overlay-preview', { on: true, profile: OV.profile }).catch(toastErr);
  });
  $('#ovProfileAdd').addEventListener('click', async () => {
    const field = $('#ovNewProfile'), key = OV.keys.get(field.value.trim());
    if (!key) return toast({ title: t('ov.noSuch'), err: true });
    OV.profile = key;  // starts as a copy of the overlay on screen
    try { ovRender(await api('overlay', { cfg: OV.cfg, profile: key })); } catch (e) { return toastErr(e); }
    field.value = '';
  });
  $('#ovProfileDelete').addEventListener('click', async () => {
    const key = OV.profile, before = OV.cfg;
    try { OV.profile = ''; ovRender(await api('overlay-profile-delete', { profile: key })); } catch (e) { return toastErr(e); }
    toast({ title: t('ov.profileDeleted', { name: ovProfileName(key) }), actions: [{ label: t('ov.undo'), run: async () => { OV.profile = key; ovRender(await api('overlay', { cfg: before, profile: key })); } }] });
  });
  $('#ovFonts').innerHTML = OV_FONTS.map(f => `<option value="${esc(f)}">`).join('');
  $('#ovValues').innerHTML = Object.entries(OV_VALUES).map(([group, names]) => `<div class="ov-group"><b>${esc(t('ov.g.' + group))}</b>${names.map(n => `<button class="chip ov-chip" data-ovv="${n}" title="{${n}}">${esc(t('ov.v.' + n))}</button>`).join('')}</div>`).join('');
  ovDrag();
  ovTab(store.get('overlayTab', 'lines'));
  $('#ovTabs').addEventListener('click', e => { if (e.target.dataset.tab) ovTab(e.target.dataset.tab); });
  const view = $('#view-overlay');
  view.addEventListener('focusin', e => { if (e.target.classList.contains('ov-tpl')) OV.input = e.target; });
  view.addEventListener('input', e => {
    const el = e.target, value = el.type === 'checkbox' ? el.checked : el.type === 'number' ? parseInt(el.value, 10) : el.value;
    if (el.dataset.ov) {
      if (el.type === 'number' && Number.isNaN(value)) return;
      OV.cfg[el.dataset.ov] = value;
      if (el.dataset.ov === 'size' || el.dataset.ov === 'color') ovRenderLines();  // what lines without their own show
      if (el.dataset.ov === 'alert') ovRenderLines();  // the alarms that follow it show it
      if (['mapX', 'mapY', 'mapSize', 'mapOpacity'].includes(el.dataset.ov)) ovDrawMap();
      ovShowClears();
      ovDraw();
    } else if (el.dataset.ol) {
      const line = OV.cfg.lines[+el.closest('.ov-line').dataset.i];
      line[el.dataset.ol] = el.dataset.ol === 'size' || el.dataset.ol === 'block' ? +value || 0 : value;
      const kind = el.dataset.ol === 'text' && ovShownKind(line), now = kind && ovShownAs(line, kind);  // its text written by hand
      if (now) $$('[data-olshown]', el.closest('.ov-line')).forEach(x => { x.checked = x.value === now; });
      if (el.dataset.ol === 'color') $('.ov-clear', el.closest('.ov-line')).classList.remove('hidden');
      if (el.dataset.ol === 'valueColor' || el.dataset.ol === 'unitColor') $(`[data-olclear="${el.dataset.ol}"]`, el.closest('.ov-line')).classList.remove('hidden');
    } else if (el.dataset.or) {  // one of a line's alarms: an empty field is none (red with its beep, no continuous sound)
      const rule = ovRuleOf(el), key = el.dataset.or, v = parseFloat(el.value), box = el.closest('.ov-rule');
      if (key === 'dyn') {  // its break: the value in its field, 100 % at first
        const full = $('[data-or="full"]', box), v = parseFloat(full.value);
        rule.full = el.checked ? (Number.isFinite(v) ? v : 100) : null;
        full.disabled = !el.checked;
      }
      else if (key === 'glow' || key === 'glowFlash') { rule[key] = el.checked; $('[data-or="glowSize"]', box).disabled = !rule.glow; ovDraw(); }
      else if (key === 'glowSize') { if (!Number.isFinite(v)) return; rule[key] = v; ovDraw(); }
      else if (key === 'color') { rule.color = el.value; $('[data-orclear]', box).classList.remove('hidden'); ovDraw(); }
      else if (key === 'sound') { rule.sound = el.value; ovRenderLines(); }
      else if (key === 'at' || key === 'hz' || key === 'ms') { if (!Number.isFinite(v)) return; rule[key] = v; }
      else if (key === 'full' && rule.limit && !Number.isFinite(v)) return;  // a limit's break left empty: kept as it was
      else rule[key] = Number.isFinite(v) ? v : key === 'gap' ? OV_GAP_MS : ['repeat', 'after', 'flashMs'].includes(key) ? 0 : null;
      if (key === 'dyn' || key === 'full') $('[data-or="gap"]', box).disabled = rule.full == null;
    } else if ('olshown' in el.dataset) {
      ovSetShown(OV.cfg.lines[+el.closest('.ov-line').dataset.i], el.value);
      ovRenderLines();
    } else if (el.dataset.olbar) {  // the gauge's blocks or step: its spec rewritten in the line, the field kept as typed
      const line = OV.cfg.lines[+el.closest('.ov-line').dataset.i], v = parseFloat(el.value), [size, step, set] = ovBarOf(line);
      if (!Number.isFinite(v) || v <= 0) return;
      const blocks = Math.min(40, Math.max(1, Math.round(v))), auto = +(100 / blocks).toFixed(1);  // a step not set: full at 100 % still
      const spec = el.dataset.olbar === 'size' ? ovBarSpec(blocks, set ? step : auto) : ovBarSpec(size, +v.toFixed(1));
      if (el.dataset.olbar === 'size' && !set) $('[data-olbar="step"]', el.closest('.ov-line')).value = auto;
      line.text = line.text.replace(/:bar[\d./]*\}/g, `:${spec}}`);
      $('[data-ol="text"]', el.closest('.ov-line')).value = line.text;
    } else if ('ortry' in el.dataset) {
      const r = ovRuleOf(el);
      OV.trying.value = parseFloat(el.value);
      $('output', el.parentNode).textContent = ovTryText(r, OV.trying.value);
      return ovTrySend();
    } else if (el.dataset.orblink) {
      ovRuleOf(el).blink = OV_PARTS.filter(x => $(`[data-orblink="${x}"]`, el.closest('.ov-rule')).checked);
    } else if ('oradd' in el.dataset) {
      if (!el.value) return;
      const line = OV.cfg.lines[+el.closest('.ov-line').dataset.i];
      (line.rules ||= []).push(ovNewRule(line, el.value));
      OV.open.add(`${+el.closest('.ov-line').dataset.i}:${line.rules.length - 1}`);
      ovRenderLines();
    } else if (el.dataset.oc) {
      const [part, key] = el.dataset.oc.split('.'), [box, at] = ovOwner(el, part), n = +(el.closest('.ov-cond')?.dataset.n || 0);
      const v = el.type === 'number' ? parseFloat(el.value) || 0 : el.value;
      if (key === 'value' && !n && !v) box[at] = null;
      else if (n && key !== 'join') box[at].more[n - 1][key] = v;
      else box[at] = { op: '>', at: 0, more: [], ...box[at], [key]: v };
      if (key === 'value' || key === 'sound') ovRenderLines();
    } else if (el.dataset.ob) {
      const i = +el.closest('.ov-block').dataset.i, spot = i ? OV.cfg.blocks[i - 1] : OV.cfg, key = el.dataset.ob;
      if (key === 'hasBg') {
        spot.background = el.checked ? spot.lastBg || '#000000' : '';
        ovRenderBlocks();
      } else if (key === 'title' || key === 'feed') {
        spot[key] = el.value;
        if (key === 'feed') ovRenderBlocks();
      } else if (el.type === 'color') {
        spot[key] = el.value;
        if (key === 'background') spot.lastBg = el.value;
      } else {
        const v = parseInt(el.value, 10);
        if (Number.isNaN(v)) return;
        spot[key] = v;
        if (key === 'frame') ovRenderBlocks();
      }
      ovDraw();
    } else return;
    ovSave();
  });
  view.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (!b || !OV.cfg) return;  // a click before the settings came
    const row = b.closest('.ov-line'), i = row ? +row.dataset.i : -1, lines = OV.cfg.lines;
    if (b.dataset.ovv) return ovInsert(b.dataset.ovv);
    if ('ortrybtn' in b.dataset) {
      const j = +b.closest('.ov-rule').dataset.j, again = OV.trying?.i === i && OV.trying?.j === j;
      OV.trying = again ? null : { i, j, value: ovTryStart(lines[i].rules[j]) };
      ovRenderLines();
      await ovFlush();  // tried as set, not as last saved
      return ovTrySend();
    }
    if ('ortoggle' in b.dataset) {
      const key = `${i}:${b.closest('.ov-rule').dataset.j}`;
      OV.open.has(key) ? OV.open.delete(key) : OV.open.add(key);
      return ovRenderLines();
    }
    if (b.dataset.ovmove || 'ovdel' in b.dataset || 'ordel' in b.dataset) { ovTryStop(); OV.open.clear(); }
    if ('ovruletest' in b.dataset) { await ovFlush(); return api('overlay-test', { line: i, rule: +b.closest('.ov-rule').dataset.j, profile: OV.profile }).catch(toastErr); }
    if (b.dataset.ovpick) { OV.pick = b.dataset.ovpick; return $('#ovSoundFile').click(); }
    if ('obline' in b.dataset) return ovAddLine(+b.closest('.ov-block').dataset.i);
    if (b.dataset.ovclear) { OV.cfg[b.dataset.ovclear] = ''; $(`[data-ov="${b.dataset.ovclear}"]`).value = ovFollowed(b.dataset.ovclear); ovShowClears(); ovDraw(); return ovSave(); }
    if (b.dataset.ocadd) { const [box, at] = ovOwner(b, b.dataset.ocadd); box[at].more = [...(box[at].more || []), { value: 'alt', op: '>', at: 0 }]; }
    else if (b.dataset.ocdel) { const [box, at] = ovOwner(b, b.dataset.ocdel); box[at].more.splice(+b.closest('.ov-cond').dataset.n - 1, 1); }
    else if (b.dataset.olclear) { lines[i][b.dataset.olclear] = ''; }
    else if ('ordel' in b.dataset) lines[i].rules.splice(+b.closest('.ov-rule').dataset.j, 1);
    else if ('orclear' in b.dataset) ovRuleOf(b).color = '';
    if (b.dataset.ocadd || b.dataset.ocdel || b.dataset.olclear || 'ordel' in b.dataset || 'orclear' in b.dataset) { ovRenderLines(); return ovSave(); }
    if ('obdel' in b.dataset) {
      const at = +b.closest('.ov-block').dataset.i;  // its lines go back to the main block, the next ones move up
      OV.cfg.blocks.splice(at - 1, 1);
      lines.forEach(l => { l.block = l.block === at ? 0 : l.block > at ? l.block - 1 : l.block; });
      ovRenderBlocks();
      ovRenderLines();
      ovDraw();
      return ovSave();
    }
    if (b.dataset.ovmove) { const to = i + +b.dataset.ovmove; [lines[i], lines[to]] = [lines[to], lines[i]]; }
    else if ('ovdel' in b.dataset) lines.splice(i, 1);
    else if ('ovnocolor' in b.dataset) lines[i].color = '';
    else return;
    ovRenderLines();
    ovSave();
  });
  view.addEventListener('toggle', e => {  // a line's options stay open through the redrawing
    if (e.target.matches('.ov-more')) OV.cfg.lines[+e.target.closest('.ov-line').dataset.i].open = e.target.open;
  }, true);
  $('#ovAddBlock').addEventListener('click', () => {
    OV.cfg.blocks.push({ x: OV.cfg.x + 200, y: OV.cfg.y + 200 * (OV.cfg.blocks.length + 1), scale: 100 });
    ovRenderBlocks();
    ovRenderLines();
    ovDraw();
    ovSave();
  });
  $('#ovDevice').addEventListener('change', e => api('settings', { audioDevice: e.target.value }).catch(toastErr));
  $('#ovSoundFile').addEventListener('change', async e => {
    const file = e.target.files[0];
    e.target.value = '';
    if (!file) return;
    try {
      const saved = await api('sound-import', { name: file.name, data: await ovSoundData(file) }), [kind, key, j] = OV.pick.split(':');
      OV.sounds = saved.sounds;
      if (kind === 'line') OV.cfg.lines[+key].rules[+j].sound = saved.file;
      ovRenderLines();
      ovSave();
    } catch { toast({ title: t('ov.soundBad'), err: true }); }
  });
  ovShowBg();
  $('#ovBgFile').addEventListener('change', e => { if (e.target.files[0]) ovSetBg(e.target.files[0]); e.target.value = ''; });
  $('#ovBgRemove').addEventListener('click', () => { store.set('overlayBg', ''); ovShowBg(); });
  addEventListener('paste', e => {
    const image = [...e.clipboardData.files].find(f => f.type.startsWith('image/'));
    if (image && !$('#view-overlay').classList.contains('hidden')) ovSetBg(image);
  });
  $('#ovAddLine').addEventListener('click', () => ovAddLine(0));
  $('#ovEnabled').addEventListener('change', e => ovFlush({ enabled: e.target.checked }));
  $('#ovOnScreen').addEventListener('change', e => api('overlay-preview', { on: e.target.checked, profile: OV.profile }).catch(toastErr));
  $('#ovReset').addEventListener('click', async () => {
    const before = OV.cfg;
    const profile = OV.profile;
    try { ovRender(await api('overlay', { reset: true, profile })); } catch (e) { return toastErr(e); }
    toast({ title: t('ov.resetDone'), actions: [{ label: t('ov.undo'), run: async () => ovRender(await api('overlay', { cfg: before, profile })) }] });
  });
  $$('#view-overlay [data-ovkey]').forEach(field => field.addEventListener('keydown', e => {
    e.preventDefault();
    if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;
    const mods = [[e.ctrlKey, 17, 'Ctrl'], [e.shiftKey, 16, 'Shift'], [e.altKey, 18, 'Alt']].filter(m => m[0]);
    const none = e.key === 'Escape' || e.key === 'Backspace', key = field.dataset.ovkey;
    OV.cfg[key] = none ? [] : [...mods.map(m => m[1]), e.keyCode];
    OV.cfg[key + 'Name'] = none ? '' : [...mods.map(m => m[2]), e.code.replace(/^(Key|Digit)/, '')].join('+');
    field.value = OV.cfg[key + 'Name'];
    ovSave();
  }));
  const ovSetKey = (field, codes, name) => {
    OV.cfg[field.dataset.ovkey] = codes;
    OV.cfg[field.dataset.ovkey + 'Name'] = field.value = name;
    ovSave();
  };
  $$('#view-overlay [data-ovkey]').forEach(field => {
    field.addEventListener('mousedown', e => {  // the middle and side buttons; the left one picks the field
      const vk = { 1: 4, 3: 5, 4: 6 }[e.button];
      if (vk && document.activeElement === field) { e.preventDefault(); ovSetKey(field, [vk], `Mouse ${{ 1: 3, 3: 4, 4: 5 }[e.button]}`); }
    });
    field.addEventListener('focus', async () => {  // a joystick button: the server watches them while the field waits
      while (document.activeElement === field && S.status?.alarms) {
        const asked = Date.now(), got = await api('overlay-joy').catch(() => ({}));
        if (got.key && document.activeElement === field) {
          const n = got.key - 256;
          ovSetKey(field, [got.key], `Joy ${(n >> 5) + 1} B${(n & 31) + 1}`);
          break;
        }
        if (!got.key && Date.now() - asked < 1000) break;  // no joystick reader here
      }
    });
  });
  addEventListener('resize', () => { if (OV.cfg && !$('#view-overlay').classList.contains('hidden')) ovDraw(); });
  $('#ovHudPlace').addEventListener('click', e => {
    const b = e.target.closest('[data-place]');
    if (!b) return;
    OV.hudPlace = b.dataset.place;
    store.set('overlayHudPlace', OV.hudPlace);
    ovDrawHud();
  });
  OV.hudPlace = store.get('overlayHudPlace', 'cockpit') === 'outside' ? 'outside' : 'cockpit';
}
