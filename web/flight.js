/* WTFTD — Flight data: curves of what the game reports in flight, live or from a recorded log, and the CSV recorder.
   One strip per value on a shared time axis: values of very different sizes never share a scale. The strips' headers
   name the value and give its number, the latest one or the one under the mouse. */
'use strict';

const FL = { rows: [], seq: 0, units: {}, sel: store.get('flightSel', ['ias', 'alt', 'g', 'fuel']), span: store.get('flightSpan', 300),
             log: '', timer: 0, mouse: null, recording: null, flying: false, aircraft: null };
const FL_GAP_S = 5;  // no reading for this long: the line breaks instead of joining two flights
const FL_STRIP = 96, FL_AXIS = 24, FL_HEAD = 20, FL_LEFT = 60;  // FL_LEFT: the strips' lowest and highest numbers
const FL_STEPS = [5, 10, 30, 60, 120, 300, 600, 1800, 3600];

const flNum = v => v.toLocaleString(I18N.code, { maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 2 });
const flTime = s => `${s < 0 ? '-' : ''}${Math.floor(Math.abs(s) / 60)}:${String(Math.floor(Math.abs(s) % 60)).padStart(2, '0')}`;

// an aircraft's breaking limits: the vehicle panel, and the sheet of the one flown
function limitsHTML(lim) {
  if (!lim) return '';
  const kmh = v => `${flNum(v)} km/h`, pos = p => `${Math.round(p * 100)} %`;
  const rows = [['speed', kmh(lim.v)], ['mach', flNum(lim.m)], ['gear', lim.gear ? kmh(lim.gear) : t('lim.none')],
                ['eng', lim.eng], ['fuel', `${flNum(Math.max(...lim.fuel))} kg`], ['mass', `${flNum(lim.mass)} kg`]];
  const wide = [[t('lim.flaps'), lim.flaps?.map(([p, v]) => `${pos(p)}: ${kmh(v)}`).join(' · ')],
                [t('lim.sweep'), lim.sw?.map(([p, v, m]) => `${pos(p)}: ${kmh(v)}, M ${flNum(m)}`).join(' · ')]].filter(x => x[1]);
  return `<div class="lim"><div class="lim-title">${esc(t('lim.title'))}</div>
    <div class="vstats">${rows.map(([k, v]) => `<div class="vstat"><span>${esc(t('lim.' + k))}</span><b>${esc(v)}</b></div>`).join('')}</div>
    ${wide.map(([k, v]) => `<div class="lim-wide"><span>${esc(k)}</span>${esc(v)}</div>`).join('')}</div>`;
}

async function flSheet(id) {
  FL.aircraft = id;
  const el = $('#flSheet');
  el.classList.toggle('hidden', !id);
  if (!id) return;
  try {
    const d = await api('vehicle/' + encodeURIComponent(id));
    el.innerHTML = `<div class="row-between"><div><small class="muted">${esc(t('fl.current'))}</small> <b>${esc(I18N.unit(id))}</b></div>
      <button class="btn btn-sm" data-flopen="${esc(id)}">${esc(t('fl.open'))}</button></div>${limitsHTML(d.st?.lim)}`;
  } catch { el.classList.add('hidden'); }
}

function flShown() {
  if (FL.log || !FL.span || !FL.rows.length) return FL.rows;
  const from = FL.rows.at(-1).t - FL.span;
  return FL.rows.filter(r => r.t >= from);
}

function flDraw() {
  const cv = $('#flCanvas'), rows = flShown(), names = FL.sel;
  $('#flEmpty').classList.toggle('hidden', rows.length > 1);
  cv.classList.toggle('hidden', rows.length <= 1 || !names.length);
  if (rows.length <= 1 || !names.length) return;
  const css = getComputedStyle(document.documentElement), tok = n => css.getPropertyValue(n).trim();
  const H = names.length * FL_STRIP + FL_AXIS;
  cv.style.height = `${H}px`;
  const W = cv.clientWidth, dpr = devicePixelRatio || 1;
  cv.width = W * dpr;
  cv.height = H * dpr;
  const c = cv.getContext('2d');
  c.scale(dpr, dpr);
  c.font = `12px ${tok('--font')}`;
  const pad = 12, t0 = rows[0].t, t1 = rows.at(-1).t, x = t => FL_LEFT + (t - t0) / ((t1 - t0) || 1) * (W - FL_LEFT - pad);
  const hovered = FL.mouse == null ? null : rows.reduce((a, b) => (Math.abs(x(b.t) - FL.mouse) < Math.abs(x(a.t) - FL.mouse) ? b : a));
  names.forEach((name, i) => {
    const top = i * FL_STRIP, plotTop = top + FL_HEAD, plotH = FL_STRIP - FL_HEAD - 8;
    const vals = rows.map(r => r[name]).filter(v => v != null);
    const unit = FL.units[name] || '';
    c.textBaseline = 'middle';
    c.textAlign = 'left';
    c.fillStyle = tok('--text-2');
    c.fillText(`${t('ov.v.' + name)}${unit ? ` (${unit})` : ''}`, pad, top + FL_HEAD / 2);
    c.strokeStyle = tok('--line');
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(FL_LEFT, plotTop + plotH + .5);
    c.lineTo(W - pad, plotTop + plotH + .5);
    c.stroke();
    if (!vals.length) {
      c.textAlign = 'right';
      c.fillStyle = tok('--muted');
      c.fillText(t('fl.na'), W - pad, top + FL_HEAD / 2);
      return;
    }
    let lo = Math.min(...vals), hi = Math.max(...vals);
    if (hi - lo < 1e-6) { lo -= 1; hi += 1; }
    const y = v => plotTop + plotH - (v - lo) / (hi - lo) * plotH;
    c.textAlign = 'right';
    c.fillStyle = tok('--muted');
    c.font = `10.5px ${tok('--font')}`;
    c.textBaseline = 'top';
    c.fillText(flNum(hi), FL_LEFT - 8, plotTop);
    c.textBaseline = 'bottom';
    c.fillText(flNum(lo), FL_LEFT - 8, plotTop + plotH);
    c.font = `12px ${tok('--font')}`;
    c.strokeStyle = tok('--chart-line');
    c.lineWidth = 2;
    c.lineJoin = 'round';
    c.beginPath();
    let last = null;
    for (const r of rows) {
      if (r[name] == null) { last = null; continue; }
      if (last == null || r.t - last > FL_GAP_S) c.moveTo(x(r.t), y(r[name]));
      else c.lineTo(x(r.t), y(r[name]));
      last = r.t;
    }
    c.stroke();
    const at = hovered && hovered[name] != null ? hovered : rows.findLast(r => r[name] != null);
    c.textAlign = 'right';
    c.textBaseline = 'middle';
    c.fillStyle = tok('--text');
    c.font = `600 13px ${tok('--font')}`;
    c.fillText(`${flNum(at[name])}${unit ? ` ${unit}` : ''}`, W - pad, top + FL_HEAD / 2);
    c.font = `12px ${tok('--font')}`;
    if (hovered && hovered[name] != null) {
      c.beginPath();
      c.arc(x(hovered.t), y(hovered[name]), 4, 0, Math.PI * 2);
      c.fillStyle = tok('--chart-line');
      c.strokeStyle = tok('--surface');
      c.lineWidth = 2;
      c.fill();
      c.stroke();
    }
  });
  // the time axis: minutes:seconds from the start of a log, before now when live
  const axisY = names.length * FL_STRIP + FL_AXIS / 2, step = FL_STEPS.find(s => (t1 - t0) / s <= 8) || 7200;
  const label = s => flTime(FL.log ? s - t0 : s - t1);
  c.fillStyle = tok('--muted');
  c.textBaseline = 'middle';
  c.textAlign = 'center';
  for (let s = t1; s >= t0; s -= step) c.fillText(label(s), Math.min(x(s), W - 24), axisY);
  if (hovered) {
    c.strokeStyle = tok('--muted');
    c.lineWidth = 1;
    c.beginPath();
    c.moveTo(x(hovered.t) + .5, 0);
    c.lineTo(x(hovered.t) + .5, names.length * FL_STRIP);
    c.stroke();
    const text = label(hovered.t), w = c.measureText(text).width + 12;
    c.fillStyle = tok('--surface-3');
    c.fillRect(x(hovered.t) - w / 2, axisY - 9, w, 18);
    c.fillStyle = tok('--text');
    c.fillText(text, x(hovered.t), axisY);
  }
}

function flState() {
  const rec = $('#flRecord');
  rec.classList.toggle('btn-danger', !!FL.recording);
  $('#flRecordLabel').textContent = t(FL.recording ? 'fl.stop' : 'fl.record');
  $('#flState').textContent = FL.recording ? t('fl.recording', { file: FL.recording }) : FL.log ? '' : t(FL.flying ? 'fl.flying' : 'fl.waiting');
}

// live: asks every second, and only what's new
async function flPoll() {
  clearTimeout(FL.timer);
  if ($('#view-flight').classList.contains('hidden')) return;
  try {
    const st = await api('flight/' + FL.seq);
    FL.units = st.units;
    FL.flying = st.flying;
    FL.recording = st.log;
    if (st.aircraft !== FL.aircraft) flSheet(st.aircraft);
    if (st.rows.length && !FL.log) {
      FL.rows = FL.rows.concat(st.rows).slice(-3600);
      FL.seq = st.rows.at(-1).n;
    }
    flState();
    if (!FL.log) flDraw();
  } catch { /* the app is closing */ }
  FL.timer = setTimeout(flPoll, 1000);
}

// a recorded flight in numbers (wtftd/flightlog.py report): peaks with where they happened, time to climb, sustained turn
function flReportHTML(r) {
  if (!r?.s) return '';
  const at = x => [x.ias != null && `${flNum(x.ias)} km/h`, x.alt != null && `${flNum(x.alt)} m`, x.g != null && `${flNum(x.g)} G`].filter(Boolean).join(' · ');
  const row = (label, v, ctx) => `<div class="vstat" title="${esc(ctx || '')}"><span>${esc(label)}</span><b>${esc(v)}</b></div>`;
  const rows = [row(t('fl.rep.time'), flTime(r.s)),
    r.ias && row(t('fl.rep.ias'), `${flNum(r.ias.v)} km/h`, at(r.ias)),
    r.mach && row(t('fl.rep.mach'), `M ${flNum(r.mach.v)}`, at(r.mach)),
    r.alt && row(t('fl.rep.alt'), `${flNum(r.alt.v)} m`),
    r.climb && row(t('fl.rep.climb'), `${flNum(r.climb.v)} m/s`, at(r.climb)),
    r.g && row(t('fl.rep.g'), `${flNum(r.g.v)} G`, at(r.g)),
    r.turn && row(t('fl.rep.turn'), `${flNum(r.turn.v)} °/s`, at(r.turn)),
    r.sustained && row(t('fl.rep.sustained'), `${flNum(r.sustained.v)} °/s`, `${at(r.sustained)} · ${t('fl.rep.during', { s: r.sustained.s })}`),
    ...r.climbTo.map(([m, s]) => row(t('fl.rep.climbTo', { m: flNum(m) }), flTime(s))),
    r.fuel != null && row(t('fl.rep.fuel'), `${flNum(r.fuel)} kg`)].filter(Boolean);
  return `<div class="lim"><div class="lim-title">${esc(t('fl.rep.title'))}</div><div class="vstats">${rows.join('')}</div>
    <small class="muted">${esc(t('fl.rep.note'))}</small></div>`;
}

async function flLogs(selected = '') {
  let logs = [];
  try { logs = await api('flight-logs'); } catch { /* none yet */ }
  $('#flSource').innerHTML = `<option value="">${esc(t('fl.live'))}</option>` + logs.map(l => `<option value="${esc(l.name)}"${l.name === selected ? ' selected' : ''}>${esc(l.name)} · ${Math.ceil(l.size / 1024)} KB</option>`).join('');
}

async function flSource(name) {
  FL.log = name;
  FL.rows = [];
  FL.seq = 0;
  $('#flDelete').classList.toggle('hidden', !name);
  $('#flSpan').classList.toggle('hidden', !!name);
  $('#flAcmi').classList.toggle('hidden', !name);
  $('#flReport').classList.add('hidden');
  if (name) {
    try {
      const log = await api('flight-logs/' + encodeURIComponent(name));
      FL.rows = log.rows;
      $('#flReport').innerHTML = flReportHTML(log.report);
      $('#flReport').classList.toggle('hidden', !$('#flReport').innerHTML);
    } catch (e) { toastErr(e); }
  }
  flState();
  flDraw();
  if (!name) flPoll();
}

// a recording from elsewhere (a Test bench run): its curves, report and Tacview export
async function flOpenLog(name) {
  FL.log = name;
  showView('flight');
  await flSource(name);
}

async function openFlightView() {
  await flLogs(FL.log);
  flPoll();
  flDraw();
}

// the values and the span picked, kept under a name in this browser profile
function flRenderViews(on = '') {
  const names = Object.keys(store.get('flightViews', {})).sort();
  $('#flView').innerHTML = `<option value="">—</option>${names.map(n => `<option value="${esc(n)}"${n === on ? ' selected' : ''}>${esc(n)}</option>`).join('')}`;
  $('#flViewDelete').classList.toggle('hidden', !on);
}

function flPickView(name) {
  const view = store.get('flightViews', {})[name];
  if (view) {
    FL.sel = view.sel;
    FL.span = view.span;
    store.set('flightSel', FL.sel);
    store.set('flightSpan', FL.span);
    $$('#flSpan button').forEach(b => b.classList.toggle('active', +b.dataset.s === FL.span));
    flRenderValues();
    flDraw();
  }
  $('#flViewDelete').classList.toggle('hidden', !view);
}

function flRenderValues() {
  $('#flValues').innerHTML = Object.entries(OV_VALUES).filter(([group]) => group !== 'vehicle').map(([group, names]) => `<div class="ov-group"><b>${esc(t('ov.g.' + group))}</b>${names.filter(n => !['swept', 'fuel_time', 'wep'].includes(n)).map(n => `<button class="chip ov-chip${FL.sel.includes(n) ? ' on' : ''}" data-flv="${n}" aria-pressed="${FL.sel.includes(n)}">${esc(t('ov.v.' + n))}</button>`).join('')}</div>`).join('');
}

function bindFlight() {
  $('[data-view="flight"]').classList.toggle('hidden', !S.status?.flight);  // the game read in flight: Windows and Linux
  $('#flCockpit').classList.toggle('hidden', !S.status?.alarms);  // as the overlay: Windows only
  flRenderValues();
  flRenderViews();
  $$('#flSpan button').forEach(b => b.classList.toggle('active', +b.dataset.s === FL.span));
  $('#flSpan').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    FL.span = +b.dataset.s;
    store.set('flightSpan', FL.span);
    $$('#flSpan button').forEach(x => x.classList.toggle('active', x === b));
    flDraw();
  });
  $('#flValues').addEventListener('click', e => {
    const name = e.target.closest('[data-flv]')?.dataset.flv;
    if (!name) return;
    FL.sel = FL.sel.includes(name) ? FL.sel.filter(n => n !== name) : [...FL.sel, name];
    store.set('flightSel', FL.sel);
    flRenderValues();
    flDraw();
  });
  const cv = $('#flCanvas');
  cv.addEventListener('mousemove', e => { FL.mouse = e.offsetX; flDraw(); });
  cv.addEventListener('mouseleave', () => { FL.mouse = null; flDraw(); });
  addEventListener('resize', () => { if (!$('#view-flight').classList.contains('hidden')) flDraw(); });
  $('#flSource').addEventListener('change', e => flSource(e.target.value));
  $('#flView').addEventListener('change', e => flPickView(e.target.value));
  $('#flViewSave').addEventListener('click', () => {
    const field = $('#flViewName'), name = field.value.trim() || $('#flView').value;
    if (!name) return field.focus();
    store.set('flightViews', { ...store.get('flightViews', {}), [name]: { sel: FL.sel, span: FL.span } });
    field.value = '';
    flRenderViews(name);
  });
  $('#flViewDelete').addEventListener('click', () => {
    const views = store.get('flightViews', {});
    delete views[$('#flView').value];
    store.set('flightViews', views);
    flRenderViews();
  });
  $('#flShot').addEventListener('click', () => {  // the curves on the page's own background: a canvas has none
    const cv = $('#flCanvas'), out = Object.assign(document.createElement('canvas'), { width: cv.width, height: cv.height }), c = out.getContext('2d');
    c.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();
    c.fillRect(0, 0, out.width, out.height);
    c.drawImage(cv, 0, 0);
    Object.assign(document.createElement('a'), { href: out.toDataURL('image/png'), download: `${FL.log.replace(/\.csv$/, '') || 'flight'}.png` }).click();
  });
  $('#flRecord').addEventListener('click', async () => {
    const stopping = !!FL.recording;
    try {
      FL.recording = (await api('flight-log', { on: !stopping })).log;
      flState();
      if (stopping) { await flLogs(FL.log); toast({ title: t('fl.saved') }); }
    } catch (e) { toastErr(e); }
  });
  $('#flDelete').addEventListener('click', async () => {
    try { await api('flight-log-delete', { name: FL.log }); } catch (e) { return toastErr(e); }
    await flLogs();
    flSource('');
  });
  $('#flFolder').addEventListener('click', () => api('flight-logs-open', {}).catch(toastErr));
  $('#flCockpit').addEventListener('click', () => window.open('cockpit.html', 'wtftd-cockpit', 'popup,width=960,height=560'));
  $('#flAcmi').addEventListener('click', async () => {  // the flight as a Tacview file
    const r = await fetch('/api/flight-logs/' + encodeURIComponent(FL.log) + '/acmi');
    if (!r.ok) return toastErr(new Error((await r.json().catch(() => ({}))).error || r.statusText));
    const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(await r.blob()), download: FL.log.replace(/\.csv$/, '') + '.txt.acmi' });
    a.click();
    URL.revokeObjectURL(a.href);
  });
  $('#flSheet').addEventListener('click', e => {
    const id = e.target.closest('[data-flopen]')?.dataset.flopen;
    if (id) { showView('vehicles'); openVehicle(id); }
  });
}
