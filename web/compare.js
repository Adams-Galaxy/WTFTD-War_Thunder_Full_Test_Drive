/* WTFTD — compare up to 5 vehicles side by side: BR, stats (best value highlighted), guns, shell types. */
'use strict';

const CMP_MAX = 5;
S.compare = (store.get('compare', []) || []).filter(id => typeof id === 'string').slice(0, CMP_MAX);

const inCompare = id => S.compare.includes(id);

function toggleCompare(id) {
  if (inCompare(id)) S.compare = S.compare.filter(x => x !== id);
  else {
    if (S.compare.length >= CMP_MAX) { toast({ title: t('compare.max', { n: CMP_MAX }), err: true, ms: 3500 }); return; }
    S.compare = [...S.compare, id];
  }
  store.set('compare', S.compare);
  renderCompareTray();
  if (S.sel) renderDrawer();
}

function compareButtonHTML(v) {
  const on = inCompare(v.id);
  return `<button class="icon-btn${on ? ' on' : ''}" data-act="compare" title="${esc(t(on ? 'compare.remove' : 'compare.add'))}">${icon('sliders')}</button>`;
}

function renderCompareTray() {
  const tray = $('#compareTray');
  const list = S.compare.map(id => S.byId.get(id)).filter(Boolean);
  tray.classList.toggle('hidden', !list.length);
  if (!list.length) return;
  tray.innerHTML = `<div class="ct-items">${list.map(v => `<span class="ct-item" title="${esc(I18N.unitFull(v.id))}">
      <span class="ct-img">${unitImgTag(v.id, true)}</span>${flagHTML(v.n)}<span class="ct-name">${esc(I18N.unit(v.id))}</span>
      <button data-ctrm="${esc(v.id)}" title="${esc(t('compare.remove'))}">${icon('x', 'ic-sm')}</button></span>`).join('')}</div>
    <button class="btn btn-ghost btn-sm" data-ctact="clear">${esc(t('compare.clear'))}</button>
    <button class="btn btn-primary btn-sm" data-ctact="open"${list.length < 2 ? ' disabled' : ''}>${icon('sliders', 'ic-sm')}<span>${esc(t('compare.button', { n: list.length }))}</span></button>`;
}

async function openCompare() {
  if (!WP.arsenal) { try { WP.arsenal = await getData('arsenal.json'); } catch { WP.arsenal = {}; } }
  if (!S.sensors) { try { S.sensors = await getData('sensors.json'); } catch { S.sensors = {}; } }
  await Promise.all(S.compare.map(id => vehicleDetails(id).catch(() => null)));  // systems, guns, flight model
  renderCompareTable();
  $('#dlgCompare').showModal();
}

const CMP_SECTIONS = ['br', 'perf', 'fm', 'fire', 'prot', 'optics', 'radar', 'warn', 'av', 'crew', 'eco'];
const CMP_STAT_SEC = { spd: 'perf', rev: 'perf', hp: 'perf', t: 'perf', pw: 'perf', disp: 'perf', alt: 'perf', ceil: 'perf', climb: 'perf',
  turn: 'perf', roll: 'perf', tw: 'perf', wl: 'perf', cal: 'fire', kin: 'fire', heat: 'fire', rel: 'fire', trav: 'fire', vert: 'fire',
  armT: 'prot', armH: 'prot', crew: 'crew', rp: 'eco', sl: 'eco', rep: 'eco', slm: 'eco', rpm: 'eco', fr: 'eco' };
const CMP_DASH = '<span class="muted">—</span>';

// one row: a cell per vehicle ({ html, n: the number to rank, cls } or null). The best value is highlighted when the
// numbers differ (better 1 = higher, -1 = lower); a row whose cells differ is marked, to be seen at a glance.
function cmpRow(label, cells, { better = 0, hint = '' } = {}) {
  if (!cells.some(Boolean)) return '';
  const nums = cells.map(c => c?.n).filter(x => typeof x === 'number');
  const best = better && nums.length > 1 && new Set(nums).size > 1 ? (better > 0 ? Math.max : Math.min)(...nums) : null;
  const differ = new Set(cells.map(c => c?.html ?? '')).size > 1;
  return `<tr${differ ? ' class="cmp-diff"' : ''}><th>${esc(label)}${hint ? `<small>${esc(hint)}</small>` : ''}</th>${cells.map(c => (c
    ? `<td class="${[best != null && c.n === best ? 'best' : '', c.cls || ''].join(' ').trim()}">${c.html}</td>` : `<td>${CMP_DASH}</td>`)).join('')}</tr>`;
}

const cmpKm = m => `${I18N.num(+(m / 1000).toFixed(1))} km`;
const cmpBands = bs => {  // radar bands as letters, runs joined: [3, 4, 5, 8] -> D-F, I
  const out = [];
  for (let i = 0; i < bs.length; i++) {
    let j = i;
    while (j + 1 < bs.length && bs[j + 1] === bs[j] + 1) j++;
    out.push(j > i ? `${'ABCDEFGHIJKLMNOP'[bs[i]]}-${'ABCDEFGHIJKLMNOP'[bs[j]]}` : 'ABCDEFGHIJKLMNOP'[bs[i]]);
    i = j;
  }
  return out.join(', ');
};

function renderCompareTable() {
  const list = S.compare.map(id => S.byId.get(id)).filter(Boolean);
  if (!list.length) { $('#dlgCompare').close(); return; }
  const D = list.map(v => S.details.get(v.id) || {});
  // what each vehicle is fitted with: researched (sy) or stock (sy.su replaces what modules bring)
  const Y = D.map(d => (S.upg || !d.sy?.su ? d.sy || {} : { ...d.sy, ...d.sy.su }));
  const rows = {};
  const add = (sec, label, cells, opt) => { rows[sec] = (rows[sec] || '') + cmpRow(label, cells, opt); };
  const cell = (text, n, cls) => (text == null || text === '' ? null : { html: esc(text), n, cls });
  const chips = arr => (arr?.length ? { html: arr.map(x => `<span class="cmp-chip">${esc(x)}</span>`).join('') } : null);
  const num = (x, unit, digits = 0) => (x ? cell(`${I18N.num(+(+x).toFixed(digits))}${unit === '°' ? unit : unit ? ' ' + unit : ''}`, x) : null);
  const yes = on => (on ? cell(t('compare.yes')) : null);
  const uniq = a => [...new Set(a)];
  const AIRY = list.map(v => AIR.includes(v.c));

  ['AB', 'RB', 'SB'].forEach((m, i) => add('br', `BR ${m}`, list.map(v => (v.br?.[i] != null ? { html: esc(fmtBR(v.br[i])), n: v.br[i] } : null))));
  // the vehicles' stats, in the usual order, when at least one vehicle has a value
  const one = list.every(v => v.c === list[0].c) ? list[0].c : 'all';
  for (const k of Object.keys(STATS).filter(k => list.some(v => STATS[k].cats.includes(v.c) && v.s?.[k] != null))) {
    add(CMP_STAT_SEC[k] || 'perf', statLabel(k, one), list.map(v => (v.s?.[k] != null ? cell(fmtStat(k, statAt(v, k)), statVal(v, k), v.su?.[k] != null ? 'upg-chg' : '') : null)),
      { better: STATS[k].better, hint: STATS[k].triple ? t('stat.armHint') : '' });
  }
  rows.perf = (rows.perf || '') + bnCompareRows(list);
  add('perf', t('compare.gears'), Y.map(y => (y.gr ? cell(`${y.gr[0]} / ${y.gr[1]}`) : null)));

  // flight model: the airframe's limits
  const lim = D.map(d => d.st?.lim || {});
  add('fm', t('compare.vne'), lim.map(l => num(l.v, 'km/h')), { better: 1 });
  add('fm', t('compare.mach'), lim.map(l => num(l.m, 'M', 2)), { better: 1 });
  add('fm', t('compare.gearLimit'), lim.map(l => num(l.gear, 'km/h')), { better: 1 });
  add('fm', t('compare.aoa'), lim.map(l => num(l.aoa?.[0]?.[1], '°', 1)), { better: 1 });
  add('fm', t('compare.emptyMass'), lim.map(l => num(l.mass, 'kg')));
  add('fm', t('compare.fuel'), lim.map(l => num(l.fuel?.[0], 'kg')), { better: 1 });
  add('fm', t('compare.engines'), lim.map(l => num(l.eng)));

  // firepower
  const main = D.map((d, i) => (list[i].c === 'ground' ? (d.am || []).find(g => g.trig === 'gunner0') : null));
  add('fire', t('compare.mainAmmo'), main.map(g => num(g?.cap)), { better: 1 });
  add('fire', t('compare.elevation'), Y.map(y => (y.el ? cell(`${I18N.num(y.el[0])}° / +${I18N.num(y.el[1])}°`) : null)));
  add('fire', t('compare.stab'), Y.map(y => (y.stab ? cell(t(y.stab[0] && y.stab[1] ? 'compare.stab2' : y.stab[0] ? 'compare.stabV' : 'compare.stabH')
    + (y.stab[2] ? ` · ${t('compare.upTo', { n: y.stab[2] })}` : ''), y.stab[0] + y.stab[1]) : null)), { better: 1 });
  add('fire', t('compare.autoloader'), Y.map((y, i) => (list[i].c === 'ground' ? yes(y.al) : null)));
  add('fire', t('compare.guns'), list.map((v, i) => {
    const groups = (D[i].am || []).filter(g => g.w && !NOT_WEAPON.test(g.w));
    const html = groups.length
      ? groups.map(g => { const cal = WP.arsenal[g.w]?.cal; return `<span class="cmp-chip" title="${esc(t('compare.roundsEach', { n: g.cap }))}">${cal ? `<b>${Math.round(cal)}</b> ` : ''}${esc(I18N.weapon(g.w))}${g.n > 1 ? ` ×${g.n}` : ''}${g.cap ? ` · ${I18N.num(g.cap)}` : ''}</span>`; }).join('')
      : (v.wg || []).filter(k => !NOT_WEAPON.test(k)).slice(0, 4).map(k => `<span class="cmp-chip">${WP.arsenal[k]?.cal ? `<b>${Math.round(WP.arsenal[k].cal)}</b> ` : ''}${esc(I18N.weapon(k))}</span>`).join('');
    return html ? { html } : null;
  }));
  add('fire', t('compare.shells'), list.map(v => (ammoTypes(v).size ? { html: [...ammoTypes(v)].map(tp => `<span class="wp-badge">${esc(tp)}</span>`).join(' ') } : null)));
  add('fire', t('compare.pylons'), list.map(v => {
    const n = new Set((v.wp || []).filter(k => !NOT_WEAPON.test(k) && !['fuel', 'other'].includes(WP.arsenal[k]?.c)).map(k => I18N.weapon(k))).size;
    return n ? cell(t('compare.nWeapons', { n }), n) : null;
  }), { better: 1 });
  add('fire', t('compare.maxLoad'), Y.map(y => num(y.ml, 'kg')), { better: 1 });
  add('fire', t('compare.fireDirectors'), Y.map(y => num(y.fd)), { better: 1 });

  // protection
  add('prot', t('compare.aps'), Y.map(y => (y.aps ? cell(`${y.aps[1]}° · ${t('compare.shots', { n: y.aps[0] })}`, y.aps[0]) : null)), { better: 1 });
  add('prot', t('compare.smokeGrenades'), Y.map(y => num(y.sg)), { better: 1 });
  add('prot', t('compare.ess'), Y.map(y => num(y.ess)), { better: 1 });

  // optics and night vision
  const zoom = z => (z ? cell(z.map(x => `${I18N.num(x)}×`).join(' - '), z[z.length - 1]) : null);
  add('optics', t('compare.sightGunner'), Y.map(y => zoom(y.zg)), { better: 1 });
  add('optics', t('compare.sightCommander'), Y.map(y => zoom(y.zc)), { better: 1 });
  for (const [r, key] of [['g', 'compare.nvGunner'], ['c', 'compare.nvCommander'], ['d', 'compare.nvDriver'], ['p', 'compare.nvPilot'], ['s', 'compare.nvSight']]) {
    add('optics', t(key), Y.map(y => { const x = y.nv?.[r]; return x ? cell(`${t(x[0] === 't' ? 'compare.thermal' : 'compare.ir')} · ${t('compare.gen', { n: x[1] })}`, (x[0] === 't') * 10 + x[1]) : null; }), { better: 1 });
  }
  add('optics', t('compare.rangefinder'), Y.map(y => (y.rf ? cell(t('compare.rf.' + y.rf), y.rf === 'laser' ? 2 : 1) : null)), { better: 1 });
  add('optics', t('compare.att'), Y.map(y => yes(y.att)));

  // radar: search radars (aircraft radars search and track), tracking radars, IRST and optical trackers, ESM
  const sens = (y, kind) => (y.se || []).filter(s => s[1] === kind).map(([key, , s]) => ({ name: I18N.sensor(key), ...s }));
  const radio = Y.map(y => sens(y, 'radar').filter(s => s.k.startsWith('radar')));
  const search = radio.map(l => l.filter(s => !['t', 'rf'].includes(s.ro))), track = radio.map(l => l.filter(s => ['t', 'rf'].includes(s.ro)));
  const names = l => chips(uniq(l.map(s => s.name)));
  const range = l => (l.length ? num(Math.max(...l.map(s => s.r || 0)) || null, '') : null);
  add('radar', t('compare.searchRadar'), search.map(names));
  add('radar', t('compare.detRange'), search.map(l => { const c = range(l); return c && { ...c, html: esc(cmpKm(c.n)) }; }), { better: 1 });
  add('radar', t('compare.scanZone'), search.map(l => {
    const z = l.map(s => s.z).filter(Boolean).sort((a, b) => b[0] * b[1] - a[0] * a[1])[0];
    return z ? cell(`${z[0]}° × ${z[1]}°`, z[0] * z[1]) : null;
  }), { better: 1 });
  add('radar', t('compare.lookDown'), search.map(l => chips(uniq(l.flatMap(s => s.ld || [])).sort().map(x => t('compare.ld.' + x)))));
  add('radar', t('compare.tws'), search.map(l => {
    if (l.some(s => s.ram)) return cell(t('compare.ram'), 1000);
    const tws = l.map(s => s.tws).filter(Boolean).sort((a, b) => b[1] - a[1])[0];
    return tws ? cell(`${{ tws: 'TWS', plus: 'TWS+', esa: 'TWS ESA' }[tws[0]]} · ${t('compare.targets', { n: tws[1] })}`, tws[1]) : null;
  }), { better: 1 });
  add('radar', t('compare.surface'), radio.map(l => chips(uniq(l.flatMap(s => s.sf || [])).map(x => t('compare.sf.' + x)))));
  add('radar', t('compare.trackRadar'), track.map(names));
  add('radar', t('compare.trackRange'), track.map(l => { const c = range(l); return c && { ...c, html: esc(cmpKm(c.n)) }; }), { better: 1 });
  add('radar', t('compare.radarModes'), radio.map(l => chips([
    ...['iff', 'bvr', 'acm', 'hms', 'sarh', 'mg'].filter(k => l.some(s => s[k])).map(k => t('compare.m.' + k)),
    ...['nctr', 'dl'].filter(k => l.some(s => s[k])).map(k => t('compare.m.' + k, { n: Math.max(...l.map(s => s[k] || 0)) }))])));
  add('radar', t('compare.bands'), radio.map(l => cell(cmpBands(uniq(l.flatMap(s => s.b || [])).sort((a, b) => a - b)))));
  add('radar', t('compare.irst'), Y.map(y => names(sens(y, 'radar').filter(s => /irst|tv/.test(s.k)))));
  add('radar', t('compare.esm'), Y.map(y => names(sens(y, 'radar').filter(s => s.k === 'esm'))));

  // warning receivers and countermeasures
  const rwr = Y.map(y => sens(y, 'rwr')), maw = Y.map(y => sens(y, 'mlws'));
  add('warn', t('mods.sensor.rwr'), rwr.map(names));
  add('warn', t('compare.rwrRange'), rwr.map(l => { const c = range(l); return c && { ...c, html: esc(cmpKm(c.n)) }; }), { better: 1 });
  add('warn', t('compare.bands'), rwr.map(l => cell(cmpBands(uniq(l.flatMap(s => s.b || [])).sort((a, b) => a - b)))));
  add('warn', t('compare.rwrAlerts'), rwr.map(l => {
    const max = k => Math.max(0, ...l.map(s => s[k] || 0));
    return chips([l.some(s => s.lk) && t('compare.lock'), max('ln') === 1 ? t('compare.launch') : max('ln') > 1 && t('compare.launchN', { n: max('ln') }),
      max('dg') > 1 && t('compare.threatTypes', { n: max('dg') }), max('trk') && t('compare.tracks', { n: max('trk') }),
      l.some(s => s.ss) && t('compare.signal'), l.some(s => s.iff) && t('compare.m.iff')].filter(Boolean));
  }));
  add('warn', t('mods.sensor.mlws'), maw.map(l => chips(uniq(l.map(s => `${s.name} · ${t(s.rd ? 'compare.mawRadar' : 'compare.mawIr')}`)))));
  add('warn', t('compare.mawRange'), maw.map(l => { const c = range(l); return c && { ...c, html: esc(cmpKm(c.n)) }; }), { better: 1 });
  add('warn', t('mods.sensor.lws'), Y.map(y => names(sens(y, 'lws'))));
  add('warn', t('compare.cm'), Y.map(y => num(y.cm)), { better: 1 });
  add('warn', t('compare.autoCm'), Y.map(y => (y.acm ? cell(y.acm[0].map(k => t('mods.sensor.' + k)).join(' + ')
    + (y.acm[1] ? ` · ${t('compare.programs', { n: y.acm[1] })}` : '')) : null)));

  // avionics (aircraft): sights and designators, then the guidance of the weapons they can use
  add('av', t('compare.sights'), D.map((d, i) => (AIRY[i] ? chips((d.av || []).map(k => t('mods.av.' + k))) : null)));
  add('av', t('compare.guidance'), D.map((d, i) => (AIRY[i] ? chips((d.cap || []).map(g => t('guide.' + g))) : null)));

  // crew seats (ground)
  add('crew', t('compare.seats'), Y.map(y => (y.crew ? chips(['commander', 'gunner', 'loader', 'driver', 'machine_gunner'].filter(s => y.crew[s])
    .map(s => t('compare.seat.' + s) + (y.crew[s] > 1 ? ` ×${y.crew[s]}` : ''))) : null)));

  const head = list.map(v => `<th><div class="cmp-head">
      <button class="icon-btn cmp-rm" data-ctrm="${esc(v.id)}" title="${esc(t('compare.remove'))}">${icon('x', 'ic-sm')}</button>
      <div class="cmp-img">${unitImgTag(v.id, true)}</div>
      <div class="cmp-name">${flagHTML(v.n)}<b>${esc(I18N.unit(v.id))}</b></div>
      <div class="muted">${esc(className(v.k))}${v.r ? ' · ' + esc(t('rank', { r: ROMAN[v.r] || v.r })) : ''}</div>
      <button class="btn btn-ghost btn-sm" data-ctopen="${esc(v.id)}">${esc(t('compare.open'))}</button></div></th>`).join('');
  const upg = list.some((v, i) => (v.su && Object.keys(v.su).length) || D[i].sy?.su) ? upgSwitchHTML(list.some(v => v.su && AIR.includes(v.c))) : '';
  // vehicle columns share the width equally (fixed layout), the label column keeps its own
  $('#cmpTable').innerHTML = `${upg}<p class="cmp-legend muted"><span class="cmp-diff-mark"></span>${esc(t('compare.legend'))}</p>
    <table class="cmp" style="min-width:${200 + list.length * 190}px"><colgroup><col class="cmp-label">${list.map(() => '<col>').join('')}</colgroup>
    <thead><tr><th></th>${head}</tr></thead><tbody>
    ${CMP_SECTIONS.filter(s => rows[s]).map(s => `<tr class="cmp-sec"><th colspan="${list.length + 1}">${esc(t('compare.sec.' + s))}</th></tr>${rows[s]}`).join('')}
  </tbody></table>`;
}

function bindCompare() {
  const onClick = e => {
    const b = e.target.closest('button'); if (!b) return;
    if (b.dataset.ctrm) { toggleCompare(b.dataset.ctrm); if ($('#dlgCompare').open) renderCompareTable(); }
    else if (b.dataset.ctact === 'clear') { S.compare = []; store.set('compare', []); renderCompareTray(); if (S.sel) renderDrawer(); }
    else if (b.dataset.ctact === 'open') openCompare();
    else if (b.dataset.ctopen) { $('#dlgCompare').close(); showView('vehicles'); openVehicle(b.dataset.ctopen); }
  };
  $('#compareTray').addEventListener('click', onClick);
  $('#dlgCompare').addEventListener('click', onClick);
  renderCompareTray();
}
