/* WTFTD — What changed: everything that moved between two game versions (wtftd/patches.py, which also holds the table of what's
   compared: labels, units and colours come from it). One patch at a time, one group at a time in its tab. */
'use strict';

const CH_PAGE = 200;  // vehicles, weapons or maps added at a time: a patch can move every battle rating of the game
const CH = { groups: [], fields: {}, patches: [], rows: null, id: '', cache: {}, subjects: {}, tab: store.get('changesTab', 'br'), more: {}, touched: new Map(),
             q: '', nat: '', cat: '', mode: '', mine: false, seen: store.get('changesSeen', ''), hidden: '', loading: null };

// a value that's a name, or a list of them: what the table's unit says
const CH_NAMES = { weapon: k => I18N.weapon(k), bullet: k => I18N.bullet(k), sensor: k => I18N.sensor(k), avionics: k => t('mods.av.' + k),
                   flag: k => t('arm.f.' + k), guidance: k => (k ? t('arm.g.' + k) : '—') };

const chShell = sid => {
  const [gun, belt, ...bullets] = sid.split('|');
  return bullets.length ? bullets.map(b => I18N.bullet(b)).join(', ') : `${I18N.weapon(gun)} · ${belt ? I18N.mod(belt) || belt.replace(/_/g, ' ') : t('ammo.default')}`;
};

// what a row is about, whatever the current data still has of it
function chName(r) {
  const k = r[1], f = CH.fields[k];
  if (f.of === 's') return chShell(r[0]);
  if (f.group === 'weapon') return AR.byId.get(r[0]) ? arName(AR.byId.get(r[0])) : r[2] && k === 'w.gone' ? r[2] : I18N.arm(r[0]);
  if (f.group === 'map') return k === 'm.gone' ? r[2] : mbMapName(r[0]);
  return S.byId.has(r[0]) ? I18N.unit(r[0]) : k === 'gone' ? r[2] : k === 'new' ? r[3] : I18N.unit(r[0]);
}

// the vehicles a row concerns: itself, those firing that shell, those carrying that weapon; a map, none
function chVehicles(r) {
  const k = r[1], f = CH.fields[k];
  if (k === 'gone') return [{ id: r[0], n: r[4][0], c: r[4][1] }];
  const ids = f.of === 's' ? r[4] : f.group === 'weapon' ? AR.data?.carriers[r[0]] || [] : f.group === 'map' ? [] : [r[0]];
  return ids.map(id => S.byId.get(id)).filter(Boolean);
}

const chFound = r => (r.text ??= norm([r.name, ...chVehicles(r).map(v => v._s || v.id)].join(' ')));

function chShown() {
  const q = norm(CH.q), mine = new Set([...S.favs, ...S.setups.map(s => s.vehicle), ...HG.owned]), any = CH.nat || CH.cat || CH.mine;
  return CH.rows.filter(r => !(CH.mode && /(ab|rb|sb)$/.test(r[1]) && !r[1].endsWith(CH.mode)) && (!q || chFound(r).includes(q))
    && (!any || chVehicles(r).some(v => (!CH.nat || v.n === CH.nat) && (!CH.cat || v.c === CH.cat) && (!CH.mine || mine.has(v.id)))));
}

function chValue(r, f, x) {
  if (x == null) return '—';
  if (CH_NAMES[f.unit]) return [...new Set([x].flat().map(CH_NAMES[f.unit]))].join(', ') || '—';
  if (f.of === 'w') return arFmt(r[1].slice(2), x, AR.byId.get(r[0])?.c);
  const n = new Intl.NumberFormat(I18N.code, { minimumFractionDigits: f.digits < 2 ? f.digits : 0, maximumFractionDigits: f.digits });  // 11.0 like a BR
  return [x].flat().map(y => n.format(y)).join(' / ') + (f.unit ? ` ${f.unit}` : '');
}

// 1 better, -1 worse, 0 not known: several numbers must all go the same way
function chDir(f, a, b) {
  if (!f.better || a == null || b == null) return 0;
  const was = [a].flat(), up = was.some((x, i) => [b].flat()[i] > x), down = was.some((x, i) => [b].flat()[i] < x);
  return up === down ? 0 : (up ? 1 : -1) * f.better;
}

function chSubject(r) {
  const k = r[1], f = CH.fields[k], v = S.byId.get(r[0]);
  if (f.of === 's') {
    const list = r[4].map(id => S.byId.get(id)).filter(Boolean), shown = list.slice(0, 3);
    return `<span class="ch-sub"><b>${esc(r.name)}</b><small>${shown.map(x => mbVehicle(x.id)).join(', ')}${list.length > 3 ? ` <span class="muted">+${I18N.num(list.length - 3)}</span>` : ''}</small></span>`;
  }
  if (f.group === 'weapon') {
    const it = AR.byId.get(r[0]);
    return it ? `<button class="mb-link" data-chweapon="${esc(it.id)}">${ammoIcon(it.ic)}<span>${esc(r.name)}</span></button>` : esc(r.name);
  }
  if (f.group === 'map') return k === 'm.gone' ? esc(r.name) : mbMap(r[0]);
  return v ? `${mbVehicle(r[0], flagHTML(v.n) + unitImgTag(r[0]))}${v.h || v.ra === 6 ? rarityTag(v) : ''}` : esc(r.name);
}

// the value column of what's new or removed: it has no before and after
function chWhat(r) {
  const v = S.byId.get(r[0]), it = AR.byId.get(r[0]);
  if (v) return `${className(v.k)}${v.r ? ` · ${t('rank', { r: ROMAN[v.r] || v.r })}` : ''}`;
  return it ? t('arm.cat.' + it.c) : '—';
}

// a group's rows, one list per vehicle, weapon, shell or map: sorted by name, a subject's rows follow each other
function chSubjects(rows) {
  const out = [];
  for (const r of rows) {
    if (out.at(-1)?.[0][0] !== r[0]) out.push([]);
    out.at(-1).push(r);
  }
  return out;
}

// one change of a subject: name, before → after, on a grid shared by the subject's lines
function chChange(r) {
  const k = r[1], f = CH.fields[k], v = S.byId.get(r[0]);
  if (f.of === '') {
    const after = k === 'new' && v ? esc(`BR ${fmtBR(brOf(v))}`) : `<span class="chip ${k.endsWith('new') ? 'info' : 'dim'}">${esc(t(f.label))}</span>`;
    return `<span class="ch-k">${esc(chWhat(r))}</span><span></span><span></span><span>${after}</span>`;
  }
  const dir = chDir(f, r[2], r[3]), now = esc(chValue(r, f, r[3]));
  return `<span class="ch-k">${esc(t(f.label))}</span><span class="muted">${esc(chValue(r, f, r[2]))}</span><span class="ch-to">→</span>
    <span>${dir ? `<span class="chip ${dir > 0 ? 'info' : 'warn'}" title="${esc(t(dir > 0 ? 'ch.better' : 'ch.worse'))}">${now}</span>` : now}</span>`;
}

// battle ratings: a vehicle on one line, the three modes side by side; one that didn't move shows its BR, greyed
const CH_BR = ['brab', 'brrb', 'brsb'];
function chBrRow(rows) {
  const v = S.byId.get(rows[0][0]), by = Object.fromEntries(rows.map(r => [r[1], r]));
  const rank = by.rank ? `<small class="muted ch-rank">${esc(t('filters.rank'))} ${ROMAN[by.rank[2]] || by.rank[2] || '?'} → ${ROMAN[by.rank[3]] || by.rank[3] || '?'}</small>` : '';
  const cell = (k, i) => {
    const r = by[k];
    if (!r) return `<td class="muted">${v?.br?.[i] != null ? fmtBR(v.br[i]) : ''}</td>`;
    const d = r[2] != null && r[3] != null ? r[3] - r[2] : 0;
    return `<td><span class="muted">${fmtBR(r[2])}</span> <span class="ch-to">→</span> <b>${fmtBR(r[3])}</b>${d ? ` <span class="ch-d ${d > 0 ? 'up' : 'down'}">${d > 0 ? '+' : '-'}${fmtBR(Math.abs(d))}</span>` : ''}</td>`;
  };
  return `<tr><td>${chSubject(rows[0])}${rank}</td>${CH_BR.map(cell).join('')}</tr>`;
}

// vehicles whose battle rating went up, and down, in any mode
function chUpDown(subjects) {
  const moved = s => s.filter(r => CH_BR.includes(r[1]) && r[2] != null && r[3] != null).map(r => r[3] - r[2]);
  return [subjects.filter(s => moved(s).some(d => d > 0)).length, subjects.filter(s => moved(s).some(d => d < 0)).length];
}

function chTable(g) {
  const subjects = CH.subjects[g] || [], n = CH.more[g] || CH_PAGE, left = subjects.length - n, br = g === 'br';
  const head = br ? [t('ch.about'), t('filters.mode.ab'), t('filters.mode.rb'), t('filters.mode.sb')] : [t('ch.about'), t('ch.title')];
  return `<div class="ar-scroll"><table class="ar-table ch-table${br ? ' ch-br' : ''}"><thead><tr>${head.map(h => `<th>${esc(h)}</th>`).join('')}</tr></thead>
    <tbody>${subjects.slice(0, n).map(s => (br ? chBrRow(s) : `<tr><td>${chSubject(s[0])}</td><td><div class="ch-list">${s.map(chChange).join('')}</div></td></tr>`)).join('')}</tbody></table></div>
    ${left > 0 ? `<button class="btn btn-sm ch-more" data-chmore="${g}">${esc(t('ch.more', { n: I18N.num(Math.min(left, CH_PAGE)) }))}</button>` : ''}`;
}

function chRender() {
  const body = $('#chBody');
  $('#chBar').classList.toggle('hidden', !CH.patches.length);
  if (!CH.patches.length) {
    body.innerHTML = `<div class="empty">${icon('refresh', 'ic-xl')}<p>${esc(t('ch.empty'))}</p><p>${esc(t('ch.emptyHint'))}</p></div>`;
    return;
  }
  if (!CH.rows) { body.innerHTML = `<div class="empty"><p>${esc(t('arm.loading'))}</p></div>`; return; }
  const p = CH.patches.find(x => x.id === CH.id);
  const by = {};
  for (const r of chShown()) (by[CH.fields[r[1]].group] ||= []).push(r);
  CH.subjects = Object.fromEntries(Object.entries(by).map(([g, rows]) => [g, chSubjects(rows)]));  // counted by vehicle, weapon or map
  const present = CH.groups.filter(g => CH.subjects[g]);
  const [up, down] = CH.subjects.br ? chUpDown(CH.subjects.br) : [0, 0];
  const ud = up || down ? `<span class="ch-ud"><span class="ch-d up">▲ ${I18N.num(up)}</span><span class="ch-d down">▼ ${I18N.num(down)}</span></span>` : '';
  const notes = [p.back && t('ch.back', { from: p.from, to: p.to }), p.schema && t('ch.schema')].filter(Boolean);
  const tab = present.includes(CH.tab) ? CH.tab : present[0];  // the one picked, while the filters leave it something
  body.innerHTML = `${notes.map(x => `<p class="hint ch-note">${icon('target', 'ic-sm')}<span>${esc(x)}</span></p>`).join('')}
    ${present.length ? `<div class="ar-cats ch-tabs" role="tablist">${present.map(g => `<button class="chipbtn${g === tab ? ' active' : ''}" role="tab" data-chtab="${g}">
      ${esc(t('ch.group.' + g))}<span class="n">${I18N.num(CH.subjects[g].length)}</span>${g === 'br' ? ud : ''}</button>`).join('')}</div>
    <div class="ch-rows">${chTable(tab)}</div>` : `<div class="empty"><p>${esc(t('ch.none'))}</p></div>`}`;
}

// a patch's rows, sorted once: by name, a vehicle's values together
async function chPick(id) {
  CH.id = id;
  CH.rows = null;
  chRender();
  const rows = CH.cache[id] ||= await api('changes/' + id);
  if (CH.id !== id) return;
  if (!rows[0]?.name) {
    for (const r of rows) r.name = chName(r);
    rows.sort((a, b) => CH.groups.indexOf(CH.fields[a[1]].group) - CH.groups.indexOf(CH.fields[b[1]].group) || a.name.localeCompare(b.name, I18N.code, { numeric: true }));
  }
  CH.rows = rows;
  CH.more = {};
  chRender();
}

function chFilters() {
  CH.more = {};
  chRender();
}

function chUnseen() {
  const at = CH.patches.findIndex(p => p.id === CH.seen);
  const list = CH.patches.slice(0, at < 0 ? undefined : at).filter(p => !p.back);
  const n = list.reduce((sum, p) => sum + Object.values(p.counts).reduce((a, b) => a + b, 0), 0);
  $('#changeCount').textContent = n ? I18N.num(n) : '';
}

// the update banner's link: until the page has been opened, or the banner closed
const chBannerDue = st => !!st.patch && st.patch !== CH.seen && st.patch !== CH.hidden;

async function chLoad() {
  Object.assign(CH, await api('changes'));
  chUnseen();
  const last = CH.patches[0];
  if (!last || last.back) return;  // gone back: what the latest patch moved isn't what the panel shows
  const rows = CH.cache[last.id] ||= await api('changes/' + last.id);
  for (const r of rows) {
    const f = CH.fields[r[1]];
    for (const id of f.of === 's' ? r[4] : f.of === 'v' ? [r[0]] : []) CH.touched.set(id, (CH.touched.get(id) || 0) + 1);
  }
  if (S.sel && $('#drawer .hero')) renderDrawer();
}

// the vehicle panel's quiet line
function chPanelLine(v) {
  const n = CH.touched.get(v.id);
  return n ? `<button class="mb-link ch-line" data-act="changes">${esc(t('ch.vehicleLine', { v: CH.patches[0].to, n: I18N.num(n) }))}</button>` : '';
}

function chShowVehicle(v) {
  Object.assign(CH, { q: I18N.unit(v.id), nat: '', cat: '', mode: '', mine: false, id: '' });
  $('#chSearch').value = CH.q;
  $('#chNation').value = $('#chCat').value = '';
  $('#chMine').checked = false;
  $$('#chMode button').forEach(x => x.classList.toggle('active', !x.dataset.m));
  showView('changes');
}

async function openChangesView() {
  try {
    await CH.loading;
    CH.seen = CH.patches[0]?.id || CH.seen;
    store.set('changesSeen', CH.seen);
    chUnseen();
    $('#updateBanner.done')?.classList.add('hidden');
    $('#chPatch').innerHTML = CH.patches.map(p => `<option value="${esc(p.id)}">${esc(`${p.from} → ${p.to} · ${new Date(p.at * 1000).toLocaleDateString(I18N.code)}${p.back ? ` · ${t('ch.backShort')}` : ''}`)}</option>`).join('');
    if (!CH.patches.length) return chRender();
    if (!AR.data) await openWeaponsView();  // names, carriers and links of the weapons
    if (!CH.patches.some(p => p.id === CH.id)) await chPick(CH.patches[0].id);
    else chRender();
    $('#chPatch').value = CH.id;
  } catch (e) { toastErr(e); }
}

function bindChanges() {
  CH.loading = chLoad().catch(() => {});
  $('#chNation').innerHTML = `<option value="">${esc(t('arm.allNations'))}</option>${NATIONS.map(n => `<option value="${n}">${esc(nationName(n))}</option>`).join('')}`;
  $('#chCat').innerHTML = `<option value="">${esc(t('ch.allTypes'))}</option>${CATS.slice(1).map(c => `<option value="${c}">${esc(t('cat.' + c))}</option>`).join('')}`;
  $('#chPatch').addEventListener('change', e => chPick(e.target.value).catch(toastErr));
  $('#chSearch').addEventListener('input', debounce(e => { CH.q = e.target.value; chFilters(); }, 120));
  $('#chNation').addEventListener('change', e => { CH.nat = e.target.value; chFilters(); });
  $('#chCat').addEventListener('change', e => { CH.cat = e.target.value; chFilters(); });
  $('#chMine').addEventListener('change', e => { CH.mine = e.target.checked; chFilters(); });
  $('#chMode').addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    CH.mode = b.dataset.m;
    $$('#chMode button').forEach(x => x.classList.toggle('active', x === b));
    chFilters();
  });
  const body = $('#chBody');
  body.addEventListener('click', e => {
    const b = e.target.closest('[data-chtab], [data-chmore], [data-chweapon]');
    if (b?.dataset.chtab) {
      CH.tab = b.dataset.chtab;
      store.set('changesTab', CH.tab);
      chRender();
      // scrolled down another tab's list: this one starts right under the tabs, which stay at the top
      const page = $('.content'), below = $('#chBody .ch-rows').getBoundingClientRect().top - page.getBoundingClientRect().top - $('#chBody .ch-tabs').offsetHeight;
      if (below < 0) page.scrollTop += below;
    } else if (b?.dataset.chmore) {
      const g = b.dataset.chmore;
      CH.more[g] = (CH.more[g] || CH_PAGE) + CH_PAGE;
      $('#chBody .ch-rows').innerHTML = chTable(g);
    } else if (b?.dataset.chweapon) openWeapon(b.dataset.chweapon);
    else mbFollow(e);
  });
}
