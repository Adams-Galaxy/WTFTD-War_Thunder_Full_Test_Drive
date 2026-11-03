/* WTFTD — Cockpit: your aircraft's instruments in a window of their own, handy on a second screen. Reads what the game
   reports about your own aircraft (the same readings as Flight data, four times a second); nothing else. */
'use strict';
const $ = s => document.querySelector(s);
const A0 = -135, A1 = 135;  // the needle's sweep, degrees from straight up
const pt = (r, a) => [100 + r * Math.sin(a * Math.PI / 180), 100 - r * Math.cos(a * Math.PI / 180)];
const arc = (r, a, b) => { const [x0, y0] = pt(r, a), [x1, y1] = pt(r, b); return `M${x0},${y0} A${r},${r} 0 ${b - a > 180 ? 1 : 0} 1 ${x1},${y1}`; };
const num = (v, d = 0) => v == null ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });

// scale: [min, max] (a function of the reading when it depends on the aircraft), red: where the red zone starts
const GAUGES = [
  { key: 'ias', name: 'IAS km/h', scale: v => [0, Math.ceil((v.vne || 1500) / 100) * 100], red: v => v.vne && v.vne * .93 },
  { key: 'alt', name: 'ALT m', scale: v => [0, Math.max(5000, Math.ceil((v.alt || 0) / 5000) * 5000)] },
  { key: 'vy', name: 'CLIMB m/s', scale: () => [-100, 100], digits: 0 },
  { key: 'g', name: 'G', scale: () => [-4, 12], digits: 1, red: () => 9 },
];
const STRIP = [['mach', 'MACH', 2], ['aoa', 'AOA °', 1], ['heading', 'HDG °', 0], ['throttle', 'THROTTLE %', 0], ['fuel_pct', 'FUEL %', 0],
  ['range', 'RANGE km', 0], ['turn_rate', 'TURN °/s', 1], ['sep', 'SEP m/s', 0]];
const SWITCHES = [['gear', 'GEAR'], ['flaps', 'FLAPS'], ['airbrake', 'BRAKE']];

function build() {
  $('#gauges').innerHTML = GAUGES.map(g => `<div class="gauge" id="g-${g.key}"><svg viewBox="0 0 200 200"><g class="face"></g>
    <line class="needle" x1="100" y1="100" x2="100" y2="28"/><circle cx="100" cy="100" r="5" fill="#f3b33d"/>
    <text class="val" x="100" y="150"></text><text class="name" x="100" y="170">${g.name}</text></svg></div>`).join('');
  $('#strip').innerHTML = STRIP.map(([k, label]) => `<div class="cell" id="c-${k}"><small>${label}</small><b>—</b></div>`).join('')
    + SWITCHES.map(([k, label]) => `<div class="cell" id="c-${k}"><small>${label}</small><b>—</b></div>`).join('');
}

const faces = {};  // the dial drawn for each gauge, redrawn only when its scale or red zone moves
function face(g, v) {
  const [lo, hi] = g.scale(v), red = g.red?.(v), id = `${lo}|${hi}|${red}`;
  if (faces[g.key] === id) return [lo, hi];
  faces[g.key] = id;
  const at = x => A0 + (A1 - A0) * (x - lo) / (hi - lo);
  const ticks = Array.from({ length: 11 }, (_, i) => {
    const a = A0 + (A1 - A0) * i / 10, [x0, y0] = pt(78, a), [x1, y1] = pt(88, a), [tx, ty] = pt(66, a);
    return `<line class="tick" x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}"/>${i % 2 ? '' : `<text x="${tx}" y="${ty + 3}">${num(lo + (hi - lo) * i / 10)}</text>`}`;
  }).join('');
  $(`#g-${g.key} .face`).innerHTML = `<path class="arc" d="${arc(92, A0, A1)}"/>${red && red < hi ? `<path class="red" d="${arc(92, at(red), A1)}"/>` : ''}${ticks}`;
  return [lo, hi];
}

function show(now) {
  for (const g of GAUGES) {
    const [lo, hi] = face(g, now), v = now[g.key];
    const a = v == null ? A0 : A0 + (A1 - A0) * Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    $(`#g-${g.key} .needle`).setAttribute('transform', `rotate(${a} 100 100)`);
    $(`#g-${g.key} .val`).textContent = num(v, g.digits ?? 0);
  }
  for (const [k, , d] of STRIP) $(`#c-${k} b`).textContent = num(now[k], d);
  for (const [k] of SWITCHES) {
    const v = now[k], cell = $(`#c-${k}`);
    $(`#c-${k} b`).textContent = v == null ? '—' : v > 1 ? `${Math.round(v)} %` : 'UP';
    cell.classList.toggle('on', v > 1);
    cell.classList.toggle('alert', now[k + '_pct'] >= 100);  // gear_pct, flaps_pct: past their limit speed
  }
}

// the HUD: the overlay's style for this aircraft, drawn by the server for the size of this window
let hudOn = false;
try { hudOn = localStorage.getItem('wtftd.cockpitHud') === '1'; } catch { /* no storage: the instruments */ }
function setHud(on) {
  hudOn = on;
  try { localStorage.setItem('wtftd.cockpitHud', on ? '1' : '0'); } catch { /* kept for this window only */ }
  $('#mode').classList.toggle('on', on);
  document.body.classList.toggle('hud', on);
}
$('#mode').addEventListener('click', () => setHud(!hudOn));
setHud(hudOn);

async function pollHud() {
  const st = await (await fetch(`/api/hud/${innerWidth}x${innerHeight}`)).json();
  $('#off').hidden = st.flying;
  $('#gauges').hidden = $('#strip').hidden = true;
  $('#hud').hidden = !st.flying;
  $('#plane').textContent = st.aircraft || '';
  $('#msg').textContent = '';
  $('#hud').setAttribute('viewBox', `0 0 ${innerWidth} ${innerHeight}`);
  hudDraw($('#hud'), st.shapes, st.color, st.alert, Date.now() % 1000 < 500);
}

async function poll() {
  try {
    if (hudOn) {
      await pollHud();
      return setTimeout(poll, 100);
    }
    $('#hud').hidden = true;
    const st = await (await fetch('/api/flight/999999999')).json();  // no trace rows: only the latest reading
    const flying = st.flying && st.now && Object.keys(st.now).length;
    $('#off').hidden = !!flying;
    $('#gauges').hidden = $('#strip').hidden = !flying;
    $('#plane').textContent = st.aircraft || '';
    $('#msg').textContent = '';
    if (flying) show(st.now);
  } catch {
    $('#msg').textContent = 'WTFTD is not running.';
  }
  setTimeout(poll, 250);
}

build();
poll();
