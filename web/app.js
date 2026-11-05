/* WTFTD front-end */
'use strict';

const t = (k, v) => I18N.t(k, v);
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const icon = (id, cls = 'ic') => `<svg class="${cls}"><use href="#i-${id}"/></svg>`;
const ROMAN = ['', 'I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];
const CATS = ['all', 'ground', 'air', 'heli', 'boat', 'ship'];
const CAT_ICON = { all: 'all', ground: 'ground', air: 'air', heli: 'heli', boat: 'boat', ship: 'ship' };
const NATIONS = ['usa', 'germany', 'ussr', 'britain', 'japan', 'china', 'italy', 'france', 'sweden', 'israel'];
const NATION_TINT = { usa: '#3d6fd6', germany: '#8d96a5', ussr: '#d1453b', britain: '#2f8a63', japan: '#d65a5a', china: '#e2a92b', italy: '#2fa262', france: '#4766dd', sweden: '#f0c637', israel: '#4fa6e3', other: '#5b6b84' };
const SCENARIO_KINDS = { ground: ['ground'], air: ['air'], heli: ['heli', 'ucav'], boat: ['boat'], ship: ['ship'] };
// the top menu: each menu's pages, shown as sub-tabs under it when it has several
const MENUS = { vehicles: ['vehicles', 'setups', 'hangar', 'changes', 'mods'], maps: ['maps', 'mymaps'], weapons: ['weapons', 'myweapons'], missions: ['missions', 'challenges'],
                inflight: ['overlay', 'flight', 'battle', 'history', 'bench'] };
const AVIONICS = ['laserDesignator', 'havePointOfInterestDesignator', 'hasHelmetDesignator', 'haveCCIPForGun', 'haveCCIPForRocket', 'haveCCIPForBombs', 'haveCCRPForBombs', 'haveCCRPForGun'];
const ENVS = ['Day', 'Morning', 'Noon', 'Evening', 'Dusk', 'Dawn', 'Night'];
const WEATHERS = ['clear', 'good', 'hazy', 'thin_clouds', 'cloudy', 'cloudy_windy', 'overcast', 'poor', 'rain', 'thunder', 'blind'];
const AMMO_COLORS = ['#f3b33d', '#5ab8ff', '#5fcf8a', '#d482ff'];
const BR_MIN = 1.0;
let BR_MAX = 14.3;  // the BR sliders' top: the highest BR in the game data once it's loaded (Gaijin raises it)

const store = {
  get(k, d) { try { const v = localStorage.getItem('wtftd.' + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('wtftd.' + k, JSON.stringify(v)); } catch { /* storage unavailable */ } },
};

const S = {
  status: null,
  menuPage: {},
  vehicles: [],
  byId: new Map(),
  scenarios: [],
  details: new Map(),
  favs: new Set(store.get('favs', [])),
  setups: [],
  missions: [],
  filtered: [],
  rendered: 0,
  sel: null,      // selected vehicle record
  cfg: null,      // current setup: the open panel's vehicle
  cfgs: new Map(),  // every vehicle's setup, kept while browsing (vehicle id -> setup)
  openStep: '',  // setup steps all start closed
  showAllScen: false,
  pick: Object.assign({ vehicle: '', scenario: '' }, store.get('pick', {})),  // vehicle + map of the mission (maps.js)
  showUnofficial: false,
  f: Object.assign({ cat: 'all', nations: [], ranks: [], brMode: 1, brMin: BR_MIN, brMax: BR_MAX, fav: false, owned: false, prem: false, hidden: false, q: '', sort: 'br', view: 'tree', stats: {}, wsel: [] }, store.get('filters', {})),
  trees: {},
  openGroups: new Set(),
};

// ------------------------------------------------------------------ API
async function api(path, body) {
  const opt = body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
  const r = await fetch('/api/' + path, opt);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.error || r.statusText), { data });
  return data;
}
async function getData(name) {
  const r = await fetch('data/' + name, { cache: 'no-cache' });
  if (!r.ok) throw new Error(name);
  return r.json();
}

// ------------------------------------------------------------------ helpers
const unitImg = id => `/img/unit/${encodeURIComponent(id)}.png`;

// Images already shown once are rendered "loaded" right away (no fade / lazy wait on re-render);
// known-missing ones are not requested again. Remembered across page loads.
const IMG_OK = new Set(store.get('imgOk', []));
const IMG_BAD = new Set();
const saveImgOk = debounce(() => store.set('imgOk', [...IMG_OK].slice(-6000)), 1500);
function unitImgTag(id, eager = false) {
  const src = unitImg(id);
  if (IMG_BAD.has(src)) return '';
  const ok = IMG_OK.has(src);
  return `<img src="${src}" alt="" decoding="async"${ok ? ' class="loaded"' : eager ? '' : ' loading="lazy"'}>`;
}
document.addEventListener('load', e => {
  const img = e.target;
  if (img.tagName !== 'IMG' || !img.getAttribute('src')?.startsWith('/img/unit/')) return;
  img.classList.add('loaded');
  if (!IMG_OK.has(img.getAttribute('src'))) { IMG_OK.add(img.getAttribute('src')); saveImgOk(); }
}, true);
// what stands in for a picture that doesn't load (here, not in the markup: the page allows no inline code)
document.addEventListener('error', e => {
  const img = e.target;
  if (img.tagName !== 'IMG') return;
  const src = img.getAttribute('src') || '';
  if (src.startsWith('/img/unit/')) {
    IMG_BAD.add(src);
    IMG_OK.delete(src);
    img.remove();
  } else if (img.classList.contains('shell')) img.remove();
  else if (img.classList.contains('wicon')) img.replaceWith(Object.assign(document.createElement('span'), { className: 'wicon-ph' }));
  else if (img.closest('.nation')) img.replaceWith(Object.assign(document.createElement('span'), { className: 'fallback', textContent: src.slice(10, 13).toUpperCase() }));
  else if (src.startsWith('/img/flag/')) img.style.visibility = 'hidden';
}, true);
document.addEventListener('click', e => e.target.closest('[data-close]')?.closest('dialog').close());
const flagImg = n => `/img/flag/${n}.svg`;
const brOf = (v, mode = S.f.brMode) => v.br?.[mode] ?? null;
const fmtBR = b => (b == null ? '—' : b.toFixed(1));
const norm = s => String(s || '').normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[\s\-_.()'"/]+/g, '');
const className = k => I18N.tOr('class.' + k, k ? I18N.role(k.toLowerCase()) : t('class.'));  // game's own name for unlisted classes
const nationName = n => I18N.tOr('nation.' + n, n);
const kindsFor = cat => SCENARIO_KINDS[cat] || [cat];
const blockFor = cat => ({ ground: 'tankModels', air: 'armada', heli: 'armada', boat: 'ships', ship: 'ships' }[cat]);

function flagHTML(n, cls = 'flag') {
  if (!n || n === 'other') return `<span class="${cls}"></span>`;
  return `<img class="${cls}" src="${flagImg(n)}" alt="${esc(nationName(n))}" title="${esc(nationName(n))}" loading="lazy">`;
}

function debounce(fn, ms) { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; }

function toast({ title, sub = '', err = false, actions = [], ms = 6000 }) {
  const el = document.createElement('div');
  el.className = 'toast' + (err ? ' err' : '');
  el.innerHTML = `<div class="toast-ic">${icon(err ? 'x' : 'check', 'ic-sm')}</div>
    <div class="toast-main"><div class="toast-title">${esc(title)}</div>${sub ? `<div class="toast-sub">${esc(sub)}</div>` : ''}
    ${actions.length ? `<div class="toast-actions">${actions.map((a, i) => `<button class="btn btn-sm ${a.primary ? 'btn-primary' : 'btn-ghost'}" data-i="${i}">${a.icon ? icon(a.icon, 'ic-sm') : ''}${esc(a.label)}</button>`).join('')}</div>` : ''}</div>
    <button class="icon-btn" data-close>${icon('x', 'ic-sm')}</button>`;
  const close = () => { el.classList.add('out'); setTimeout(() => el.remove(), 200); };
  el.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b) return;
    if (b.hasAttribute('data-close')) return close();
    const a = actions[+b.dataset.i];
    if (a) { a.run(); close(); }
  });
  $('#toasts').appendChild(el);
  if (ms) setTimeout(close, ms);
}
const toastErr = e => toast({ title: t('toast.error', { msg: e.message || e }), err: true });


// ------------------------------------------------------------------ theme
const themePref = () => store.get('theme', 'dark');
const resolveTheme = pref => (pref === 'system' ? (matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark') : pref);
function applyTheme(pref = themePref()) {
  store.set('theme', pref);
  const t = resolveTheme(pref);
  document.documentElement.dataset.theme = t;
  const use = $('#btnTheme use');
  if (use) use.setAttribute('href', t === 'light' ? '#i-moon' : '#i-sun');
}
matchMedia('(prefers-color-scheme: light)').addEventListener('change', () => { if (themePref() === 'system') applyTheme('system'); });

// ------------------------------------------------------------------ boot
let LOCALES = [{ code: 'en', name: 'English' }];

// first launch: the system / browser language when the app has it, else English
function systemLang() {
  const codes = LOCALES.map(l => l.code);
  for (const tag of navigator.languages || [navigator.language || '']) {
    const c = String(tag).toLowerCase().split('-')[0];
    if (codes.includes(c)) return c;
  }
  return 'en';
}

async function boot() {
  S.status = await api('status');
  try { LOCALES = await (await fetch('locales/index.json')).json(); } catch { /* English only */ }
  const lang = S.status.settings?.lang || store.get('lang', '') || systemLang();
  await I18N.init(lang, S.status.data?.langs || ['en']);
  I18N.apply();
  applyTheme(S.status.settings?.theme || themePref());
  $('#btnTheme').addEventListener('click', () => {
    const next = resolveTheme(themePref()) === 'light' ? 'dark' : 'light';
    applyTheme(next);
    api('settings', { theme: next }).then(st => { S.status = st; }).catch(() => {});
  });
  renderStatus();

  if (!S.status.dataReady) { showOnboarding(); return; }
  const [vehicles, scenarios, trees, bulletIcons] = await Promise.all([getData('vehicles.json'), getData('scenarios.json'), getData('trees.json').catch(() => ({})), getData('bullet_icons.json').catch(() => ({}))]);
  S.bulletIcons = bulletIcons;
  S.trees = trees;
  S.vehicles = vehicles;
  S.scenarios = scenarios;
  S.byId = new Map(vehicles.map(v => [v.id, v]));
  BR_MAX = Math.max(BR_MAX, ...vehicles.flatMap(v => v.br || []).filter(Number.isFinite));
  if (S.f.brMax >= (S.f.brTop ?? 14.3) - 0.01) S.f.brMax = BR_MAX;  // the whole range, saved under an older top, stays whole
  S.f.brTop = BR_MAX;
  $('#brMin').max = $('#brMax').max = BR_MAX;
  for (const v of vehicles) v._s = norm(I18N.unit(v.id)) + '|' + norm(I18N.unitFull(v.id)) + '|' + norm(v.id);

  buildSidebar();
  bindUI();
  applyFilters();
  refreshSetups();
  refreshMissions();
  watchUpdates();
  edBind();
  bindStatFilters();
  bindShare();
  bindAppInfo();
  bindCompare();
  bindWeapons();
  bindMyWeapons();
  bindOverlay();
  bindFlight();
  bindBattle();
  bindHistory();
  bindChanges();
  bindHangar();
  bindMods();
  bindBench();
  bindChallenges();
  bindMaps();
  bindLibrary();
  showView(store.get('startView', 'vehicles'));
  store.set('startView', 'vehicles');
}

// v a whole version ahead of w (2.60.x against 2.59.x): the datamine then has the dev server's; a patch ahead is the live game's
function versionAhead(v, w) {
  const major = x => String(x || '').split('.').slice(0, 2).map(Number), a = major(v), b = major(w);
  return (a[0] - b[0] || a[1] - b[1]) > 0;
}

// the Data button's menu: the two databases WTFTD can keep (the installed game's, the datamine's), one click to switch
function dataMenu() {
  const st = S.status, box = $('#dataMenu');
  if (!box.classList.contains('hidden')) return box.classList.add('hidden');
  const ahead = m => m.source !== 'game' && st.data?.source === 'game' ? versionAhead(m.version, st.data.version) : m === st.data && !!st.dataAhead;
  const name = m => t(m.source === 'game' ? (m.circuit === 'dev' ? 'data.menu.gameDev' : 'data.menu.game') : ahead(m) ? 'data.menu.datamineDev' : 'data.menu.datamine');
  const day = m => (m.built ? new Date(m.built * 1000).toLocaleDateString(I18N.code) : '');
  const row = (m, on) => `<button class="dm-row${on ? ' on' : ''}" role="menuitemradio" aria-checked="${on}"${on ? ' disabled' : ' data-dm="switch"'}>
    ${on ? icon('check', 'ic-sm') : '<i class="dm-sp"></i>'}<span><b>${esc(name(m))}</b><small class="muted">${esc(t('settings.version', { version: m.version, date: day(m) }))}</small></span></button>`;
  const other = st.other?.version ? row(st.other, false)
    : `<button class="dm-row" role="menuitem" data-dm="build"><i class="dm-sp"></i><span><b>${esc(t(st.dataSource === 'game' ? 'data.menu.buildDatamine' : 'data.menu.buildGame'))}</b>
      <small class="muted">${esc(t('data.menu.buildHint'))}</small></span></button>`;
  box.innerHTML = `${row(st.data, true)}${other}<button class="dm-row dm-foot" role="menuitem" data-dm="settings">${esc(t('data.menu.settings'))}</button>`;
  box.classList.remove('hidden');
}

// the page reloaded on the page it shows
function reloadOnPage() {
  store.set('startView', $('.view:not(.hidden)')?.id.replace('view-', '') || 'vehicles');
  location.reload();
}

async function dataMenuPick(e) {
  const b = e.target.closest('[data-dm]');
  if (!b) return;
  $('#dataMenu').classList.add('hidden');
  try {
    if (b.dataset.dm === 'settings') return openSettings('source');
    if (b.dataset.dm === 'build') { await api('dev-build', {}); return showView('changes'); }  // its progress shows there
    S.status = await api('data-switch', {});
    reloadOnPage();  // everything the page read comes from the other database now
  } catch (err) { toastErr(err); }
}

function renderStatus() {
  const st = S.status;
  const game = st.gameFound
    ? `<span class="pill ok" title="${esc(st.gameDir)}"><span class="dot"></span>${esc(t('status.gameFound'))}</span>`
    : `<span class="pill bad" id="pillGame" title="${esc(t('settings.gameDirHint'))}"><span class="dot"></span>${esc(t('status.gameMissing'))}</span>`;
  // where the data comes from, and a click to change it: the installed game, or the datamine (the dev server's when ahead of it)
  const src = st.data?.source === 'game' ? (st.data.circuit === 'dev' ? 'gamedev' : 'game') : st.dataAhead ? 'dev' : 'datamine';
  const data = st.data?.version
    ? `<button class="pill pill-data${src.endsWith('dev') ? ' warn' : ''}" id="pillData" title="${esc(`${t('settings.version', { version: st.data.version, date: new Date(st.data.built * 1000).toLocaleDateString(I18N.code) })} · ${t('source.from.' + (st.data.source || 'datamine'))}\n${t('status.dataHint')}`)}">${esc(t('status.data', { version: st.data.version }))} · ${esc(t('status.src.' + src))}</button>`
    : `<span class="pill bad"><span class="dot"></span>${esc(t('status.noData'))}</span>`;
  $('#status').innerHTML = game + data;
  $('#pillGame')?.addEventListener('click', openSettings);
  $('#pillData')?.addEventListener('click', dataMenu);
  if (typeof renderAppVersion === 'function' && APP.info) renderAppVersion();
}

// ------------------------------------------------------------------ sidebar & filters
// rarity badge: 6 non-playable, 5 removed, 4 event, 3 pack, 2 squadron, 1 premium
function rarityTag(v) {
  const ra = v.ra || 0;
  const [cls, key] = v.h || ra === 6 ? ['hid', 'badge.hidden'] : ra === 5 ? ['hid', 'badge.removed'] : ra === 4 || v.g ? ['ev', 'badge.event']
    : ra === 3 ? ['ev', 'badge.pack'] : ra === 2 ? ['sq', 'badge.squadron'] : ra === 1 || v.p ? ['prem', 'badge.premium'] : [];
  return key ? `<span class="tagx ${cls}">${esc(t(key))}</span>` : '';
}

const ROLE_ORDER = ['light_tank', 'medium_tank', 'heavy_tank', 'tank_destroyer', 'spaa', 'missile_tank',
  'fighter', 'jet_fighter', 'interceptor', 'aa_fighter', 'assault', 'strike_aircraft', 'bomber', 'dive_bomber', 'light_bomber',
  'frontline_bomber', 'longrange_bomber', 'jet_bomber', 'torpedo', 'naval_aircraft', 'hydroplane', 'strike_ucav',
  'attack_helicopter', 'utility_helicopter', 'boat', 'torpedo_boat', 'gun_boat', 'torpedo_gun_boat', 'heavy_boat',
  'heavy_gun_boat', 'armored_boat', 'submarine_chaser', 'minelayer', 'barge', 'frigate', 'destroyer', 'light_cruiser',
  'heavy_cruiser', 'battlecruiser', 'battleship'];

function renderRoles() {
  const box = $('#roles'), sec = $('#roleSection');
  if (!box || !sec) return;
  sec.classList.toggle('hidden', S.f.cat === 'all');
  if (S.f.cat === 'all') { box.innerHTML = ''; return; }
  const counts = {};
  for (const v of S.vehicles) if (v.c === S.f.cat && (!v.h || S.f.hidden)) for (const r of v.ro || []) counts[r] = (counts[r] || 0) + 1;
  const sel = S.f.roles || [];
  box.innerHTML = ROLE_ORDER.filter(r => counts[r]).map(r => `<button class="role-chip${sel.includes(r) ? ' active' : ''}" data-role="${r}">
      <span>${esc(I18N.role(r))}</span><i>${I18N.num(counts[r])}</i></button>`).join('');
}

function buildSidebar() {
  renderRoles();
  const counts = { all: 0 };
  for (const v of S.vehicles) if (!v.h || S.f.hidden) { counts.all++; counts[v.c] = (counts[v.c] || 0) + 1; }
  $('#cats').innerHTML = CATS.map(c => `<button class="cat${S.f.cat === c ? ' active' : ''}" data-cat="${c}">
      <svg><use href="#i-${CAT_ICON[c]}"/></svg><span>${esc(t('cat.' + c))}</span><span class="n">${I18N.num(counts[c] || 0)}</span></button>`).join('');

  $('#nations').innerHTML = NATIONS.map(n => `<button class="nation${S.f.nations.includes(n) ? ' active' : ''}" data-n="${n}" title="${esc(nationName(n))}">
      <img src="${flagImg(n)}" alt=""></button>`).join('');
  $('#nations').classList.toggle('has-active', S.f.nations.length > 0);

  const maxRank = Math.max(8, ...S.vehicles.map(v => v.r || 0));
  $('#ranks').innerHTML = Array.from({ length: maxRank }, (_, i) => i + 1)
    .map(r => `<button class="rank-chip${S.f.ranks.includes(r) ? ' active' : ''}" data-r="${r}">${ROMAN[r] || r}</button>`).join('');

  $$('#brMode button').forEach(b => b.classList.toggle('active', +b.dataset.mode === S.f.brMode));
  $('#brMin').value = S.f.brMin; $('#brMax').value = S.f.brMax;
  updateBrRange();
  $('#optFav').checked = S.f.fav; $('#optOwned').checked = S.f.owned; $('#optPrem').checked = S.f.prem; $('#optHidden').checked = S.f.hidden;
  updateSortOptions();
  renderStatFilters();
  $('#search').value = S.f.q;
}

function updateBrRange() {
  let a = +$('#brMin').value, b = +$('#brMax').value;
  if (a > b) [a, b] = [b, a];
  S.f.brMin = a; S.f.brMax = b;
  const pct = x => ((x - BR_MIN) / (BR_MAX - BR_MIN)) * 100;
  $('#brFill').style.left = pct(a) + '%';
  $('#brFill').style.right = (100 - pct(b)) + '%';
  $('#brMinLabel').textContent = a.toFixed(1);
  $('#brMaxLabel').textContent = b.toFixed(1);
}

// filters shared by grid and tree (the tree shows one nation / one category at a time)
function matcher() {
  const f = S.f, q = norm(f.q);
  const fullBR = f.brMin <= BR_MIN && f.brMax >= BR_MAX;
  return v => {
    if (f.ranks.length && !f.ranks.includes(v.r)) return false;
    if (f.roles?.length && !(v.ro || []).some(r => f.roles.includes(r))) return false;
    if (!fullBR) { const b = brOf(v); if (b == null || b < f.brMin - 0.01 || b > f.brMax + 0.01) return false; }
    if (f.fav && !S.favs.has(v.id)) return false;
    if (f.owned && !HG.owned.has(v.id)) return false;
    if (f.prem && !v.p && !v.g) return false;
    if (q && !v._s.includes(q)) return false;
    if (!statsMatch(v) || !weaponMatch(v)) return false;
    return true;
  };
}

// the sidebar's filters as one test: the vehicles tab, and My vehicles (with hidden ones, saved on purpose)
function vehicleFilter({ hidden = S.f.hidden } = {}) {
  const f = S.f, ok = matcher();
  return v => !(v.h && !hidden) && (f.cat === 'all' || v.c === f.cat) && (!f.nations.length || f.nations.includes(v.n)) && ok(v);
}

function applyFilters() {
  const f = S.f;
  store.set('filters', f);
  if (!$('#view-setups').classList.contains('hidden')) renderSetups();
  const view = currentView();
  $$('#viewMode button').forEach(b => b.classList.toggle('active', b.dataset.v === view));
  $('#sortWrap').classList.toggle('hidden', view === 'tree');
  syncStickyOffset();
  if (view === 'tree') return renderTree();
  $('#tree').classList.add('hidden');
  $('#grid').classList.remove('hidden');
  let list = S.vehicles.filter(vehicleFilter());
  const name = v => I18N.unit(v.id);
  const cmp = {
    br: (a, b) => (brOf(a) ?? 99) - (brOf(b) ?? 99) || (a.r - b.r) || name(a).localeCompare(name(b)),
    rank: (a, b) => (a.r || 99) - (b.r || 99) || (brOf(a) ?? 99) - (brOf(b) ?? 99),
    name: (a, b) => name(a).localeCompare(name(b), I18N.code, { numeric: true }),
    nation: (a, b) => NATIONS.indexOf(a.n) - NATIONS.indexOf(b.n) || (brOf(a) ?? 99) - (brOf(b) ?? 99),
    rarity: (a, b) => (b.ra || 0) - (a.ra || 0) || (brOf(a) ?? 99) - (brOf(b) ?? 99),
  }[f.sort] || statCmp(f.sort) || (() => 0);
  list.sort(cmp);
  S.filtered = list;
  S.rendered = 0;
  $('#grid').innerHTML = '';
  $('#gridEmpty').classList.toggle('hidden', list.length > 0);
  const noOwned = f.owned && !HG.owned.size;  // nothing marked yet: where to do it
  $('#gridEmpty p').textContent = t(noOwned ? 'hg.emptyGrid' : 'results.empty');
  $('#gridHangar').classList.toggle('hidden', !noOwned);
  $('#resultsCount').innerHTML = `<b>${I18N.num(list.length)}</b>${esc(t('results.count', { n: '' }).trim())}`;
  renderMore();
  requestAnimationFrame(fillGrid);
}

// one click on a card marks the vehicle: a span, a card is already a button
const ownMarkHTML = (v, cls) => `<span class="${cls}${HG.owned.has(v.id) ? ' on' : ''}" data-own="${esc(v.id)}" role="button" title="${esc(t(HG.owned.has(v.id) ? 'hg.unmark' : 'hg.mark'))}">${icon('check', 'ic-sm')}</span>`;

function cardHTML(v) {
  const br = brOf(v);
  const cls = ['card', v.p ? 'prem' : '', v.h ? 'hid' : '', S.sel?.id === v.id ? 'selected' : ''].join(' ');
  const tag = rarityTag(v);
  return `<button class="${cls}" data-id="${esc(v.id)}" style="--tint:${NATION_TINT[v.n] || NATION_TINT.other}">
    <div class="card-img">
      ${unitImgTag(v.id)}
      <svg class="ph"><use href="#i-${CAT_ICON[v.c]}"/></svg>
      ${v.r ? `<span class="card-rank">${ROMAN[v.r] || v.r}</span>` : ''}
      ${br != null ? `<span class="card-br">${fmtBR(br)}</span>` : ''}
      ${cardStatHTML(v)}
      ${S.favs.has(v.id) ? `<svg class="card-fav"><use href="#i-star"/></svg>` : ''}
      ${ownMarkHTML(v, 'card-own')}
    </div>
    <div class="card-body">${flagHTML(v.n)}
      <div class="card-txt"><div class="card-name" title="${esc(I18N.unitFull(v.id))}">${esc(I18N.unit(v.id))}</div>
      <div class="card-sub"><span>${esc(className(v.k))}</span>${tag}</div></div>
    </div></button>`;
}

function renderMore() {
  const next = S.filtered.slice(S.rendered, S.rendered + 96);
  if (!next.length) return;
  $('#grid').insertAdjacentHTML('beforeend', next.map(cardHTML).join(''));
  S.rendered += next.length;
}

// Keep adding cards while the end of the grid is within ~1.5 screens of the viewport.
function fillGrid() {
  const content = $('.content');
  if ($('#grid').classList.contains('hidden')) return;
  let guard = 0;
  while (S.rendered < S.filtered.length && guard++ < 40) {
    const gap = $('#sentinel').getBoundingClientRect().top - content.getBoundingClientRect().bottom;
    if (gap > content.clientHeight * 1.5) break;
    renderMore();
  }
}

// the tree header sticks right under the results bar, whatever its height
function syncStickyOffset() {
  const h = $('.results-bar')?.offsetHeight;
  if (h) document.documentElement.style.setProperty('--rb-h', h + 'px');
}
window.addEventListener('resize', () => syncStickyOffset());

// "All" always lists every vehicle in the grid; the research tree is per vehicle type
// The research tree needs one vehicle type and one nation. Without a nation the grid lists that type
// for every nation; the nation picker only shows when the user explicitly asks for the tree view.
const currentView = () => {
  if (S.f.cat === 'all' || S.f.view !== 'tree') return 'grid';
  return S.f.nations.length === 1 || S.pickNation ? 'tree' : 'grid';
};

function setFilter(patch) {
  if (!('view' in patch)) S.pickNation = false;
  Object.assign(S.f, patch);
  buildSidebar();
  applyFilters();
  if ('brMode' in patch && S.sel) renderDrawer();  // the panel's Economy block goes by it
}

// ------------------------------------------------------------------ research tree
const TREE_CATS = ['ground', 'air', 'heli', 'boat', 'ship'];
const SPECIAL_FLAGS = ['gift', 'event', 'clan', 'market', 'removed'];

function treeCardHTML(it, ok) {
  const v = S.byId.get(it.id);
  if (!v) return '';
  const f = it.f || [];
  const br = brOf(v);
  const cls = ['tcard', HG.owned.has(v.id) ? 'owned' : '', f.includes('gift') || v.p ? 'prem' : '', f.includes('clan') ? 'clan' : '', f.includes('removed') ? 'removed' : '',
    ok(v) ? '' : 'dim', S.sel?.id === v.id ? 'selected' : ''].join(' ');
  const tag = f.includes('removed') ? 'badge.removed' : f.includes('clan') ? 'badge.squadron' : f.includes('event') ? 'badge.event' : '';
  return `<button class="${cls}" data-id="${esc(v.id)}" title="${esc(I18N.unitFull(v.id))}" style="--tint:${NATION_TINT[v.n] || NATION_TINT.other}">
    <span class="tcard-img">${unitImgTag(v.id)}<svg class="ph"><use href="#i-${CAT_ICON[v.c]}"/></svg></span>
    <span class="tcard-name">${esc(I18N.unit(v.id))}</span>
    <span class="tcard-meta">${br != null ? `<b>${fmtBR(br)}</b>` : ''}${tag ? `<i>${esc(t(tag))}</i>` : ''}${S.favs.has(v.id) ? `<svg class="tfav"><use href="#i-star"/></svg>` : ''}${ownMarkHTML(v, 'tcard-own')}</span>
  </button>`;
}

function treeItemHTML(it, ok) {
  if (!it.g) return treeCardHTML(it, ok);
  const open = S.openGroups.has(it.g);
  const members = it.u.filter(m => S.byId.has(m.id));
  const first = S.byId.get(members[0]?.id);
  if (!first) return '';
  const anyOk = members.some(m => ok(S.byId.get(m.id)));
  const brs = members.map(m => brOf(S.byId.get(m.id))).filter(b => b != null);
  const lo = Math.min(...brs), hi = Math.max(...brs);
  const brTxt = brs.length ? (lo === hi ? fmtBR(lo) : `${fmtBR(lo)}–${fmtBR(hi)}`) : '';
  return `<div class="tgroup${open ? ' open' : ''}${anyOk ? '' : ' dim'}">
    <button class="tcard tfolder" data-group="${esc(it.g)}" title="${esc(t('tree.group', { n: members.length }))}" style="--tint:${NATION_TINT[first.n] || NATION_TINT.other}">
      <span class="tcard-img">${unitImgTag(first.id)}<svg class="ph"><use href="#i-${CAT_ICON[first.c]}"/></svg><span class="tcount">${members.length}</span></span>
      <span class="tcard-name">${esc(I18N.unit(it.g))}</span>
      <span class="tcard-meta"><b>${brTxt}</b><svg class="tchev"><use href="#i-chev"/></svg></span>
    </button>
    ${open ? `<div class="tgroup-items">${members.map(m => treeCardHTML(m, ok)).join('')}</div>` : ''}
  </div>`;
}

function renderTree() {
  const el = $('#tree');
  $('#grid').classList.add('hidden');
  $('#gridEmpty').classList.add('hidden');
  el.classList.remove('hidden');
  S.filtered = [];
  const nation = S.f.nations.length === 1 ? S.f.nations[0] : null;
  if (!nation) {
    $('#resultsCount').innerHTML = esc(t('tree.pickNation'));
    el.innerHTML = `<div class="nation-pick">${NATIONS.filter(n => S.trees[n]).map(n => `<button class="npick" data-pick="${n}" style="--tint:${NATION_TINT[n]}">
      <img src="${flagImg(n)}" alt=""><span>${esc(nationName(n))}</span></button>`).join('')}</div>`;
    return;
  }
  const trees = S.trees[nation] || {};
  const cat = TREE_CATS.includes(S.f.cat) ? S.f.cat : 'ground';
  const cols = trees[cat] || [];
  const ok = matcher();
  const tabs = `<div class="tree-head">
      <div class="tree-title">${flagHTML(nation, 'flag')}<h2>${esc(nationName(nation))}</h2></div>
      <div class="seg tree-tabs">${TREE_CATS.filter(c => trees[c]).map(c => `<button class="${c === cat ? 'active' : ''}" data-tcat="${c}"><svg class="ic-sm"><use href="#i-${CAT_ICON[c]}"/></svg>${esc(t('cat.' + c))}</button>`).join('')}</div>
    </div>`;
  if (!cols.length) {
    $('#resultsCount').innerHTML = '';
    el.innerHTML = tabs + `<div class="empty"><p>${esc(t('tree.empty'))}</p></div>`;
    return;
  }
  const count = cols.reduce((n, c) => n + c.reduce((m, it) => m + (it.g ? it.u.length : 1), 0), 0);
  $('#resultsCount').innerHTML = `<b>${I18N.num(count)}</b>${esc(t('results.count', { n: '' }).trim())}`;
  const special = cols.map(c => c.every(it => (it.g ? it.u : [it]).every(u => (u.f || []).some(x => SPECIAL_FLAGS.includes(x)) || S.byId.get(u.id)?.p)));
  const ranks = [...new Set(cols.flat().map(it => it.r))].sort((a, b) => a - b);
  const cell = (c, i, r) => `<div class="tcell${special[i] ? ' special' : ''}">${c.filter(it => it.r === r).map(it => treeItemHTML(it, ok)).join('')}</div>`;
  const rows = ranks.map(r => `<div class="trow"><div class="trank"><span>${ROMAN[r] || r}</span></div>${cols.map((c, i) => cell(c, i, r)).join('')}</div>`).join('');
  const heads = `<div class="trow thead"><div class="trank"></div>${cols.map((c, i) => `<div class="tcell${special[i] ? ' special' : ''}">${special[i] ? `<span>${esc(t('tree.premium'))}</span>` : ''}</div>`).join('')}</div>`;
  el.innerHTML = tabs + `<div class="tree-scroll"><div class="tree-grid" style="--cols:${cols.length}">${heads}${rows}</div></div>`;
}

function onTreeClick(e) {
  const own = e.target.closest('[data-own]');
  if (own) return hgToggle(own.dataset.own);
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.pick) return setFilter({ nations: [b.dataset.pick], cat: TREE_CATS.includes(S.f.cat) ? S.f.cat : 'ground' });
  if (b.dataset.tcat) return setFilter({ cat: b.dataset.tcat });
  if (b.dataset.group) {
    S.openGroups.has(b.dataset.group) ? S.openGroups.delete(b.dataset.group) : S.openGroups.add(b.dataset.group);
    return renderTree();
  }
  if (b.dataset.id) openVehicle(b.dataset.id);
}

// ------------------------------------------------------------------ UI bindings
function bindUI() {
  const grid = $('#grid');
  grid.addEventListener('click', e => {
    const own = e.target.closest('[data-own]');
    if (own) return hgToggle(own.dataset.own);
    const c = e.target.closest('.card');
    if (c) openVehicle(c.dataset.id);
  });
  const tree = $('#tree');
  tree.addEventListener('click', onTreeClick);
  $('#viewMode').addEventListener('click', e => {
    const b = e.target.closest('button'); if (!b) return;
    const patch = { view: b.dataset.v };
    S.pickNation = b.dataset.v === 'tree' && S.f.nations.length !== 1;
    if (b.dataset.v === 'tree' && S.f.cat === 'all') patch.cat = 'ground';  // a tree shows one vehicle type
    if (b.dataset.v === 'tree' && S.f.nations.length > 1) patch.nations = [S.f.nations[0]];
    setFilter(patch);
  });
  $('.content').addEventListener('scroll', fillGrid, { passive: true });
  // drag the drawer's left edge to resize it (remembered)
  const setDrawerW = w => document.documentElement.style.setProperty('--drawer-w', Math.round(w) + 'px');
  const savedW = store.get('drawerW', 0);
  if (savedW) setDrawerW(Math.min(savedW, innerWidth - 320));
  $('#drawer').addEventListener('pointerdown', e => {
    if (!e.target.classList.contains('drawer-resize')) return;
    e.preventDefault();
    e.target.setPointerCapture(e.pointerId);
    document.body.classList.add('resizing');
    const move = ev => setDrawerW(Math.max(420, Math.min(innerWidth - 320, innerWidth - ev.clientX)));
    const up = () => {
      e.target.removeEventListener('pointermove', move);
      document.body.classList.remove('resizing');
      store.set('drawerW', parseInt(getComputedStyle(document.documentElement).getPropertyValue('--drawer-w'), 10));
    };
    e.target.addEventListener('pointermove', move);
    e.target.addEventListener('pointerup', up, { once: true });
  });
  window.addEventListener('resize', fillGrid);

  $('#cats').addEventListener('click', e => { const b = e.target.closest('.cat'); if (b) setFilter({ cat: b.dataset.cat, roles: [] }); });
  $('#roles').addEventListener('click', e => {
    const b = e.target.closest('[data-role]'); if (!b) return;
    const cur = new Set(S.f.roles || []);
    cur.has(b.dataset.role) ? cur.delete(b.dataset.role) : cur.add(b.dataset.role);
    setFilter({ roles: [...cur] });
  });
  $('#nations').addEventListener('click', e => {
    const b = e.target.closest('.nation'); if (!b) return;
    const n = b.dataset.n, cur = new Set(S.f.nations);
    if (currentView() === 'tree') return setFilter({ nations: [n] });
    if (e.ctrlKey || e.shiftKey) cur.has(n) ? cur.delete(n) : cur.add(n);
    else if (cur.size === 1 && cur.has(n)) cur.clear();
    else if (cur.has(n)) cur.delete(n); else cur.add(n);
    setFilter({ nations: [...cur] });
  });
  $('#ranks').addEventListener('click', e => {
    const b = e.target.closest('.rank-chip'); if (!b) return;
    const r = +b.dataset.r, cur = new Set(S.f.ranks);
    cur.has(r) ? cur.delete(r) : cur.add(r);
    setFilter({ ranks: [...cur] });
  });
  $('#brMode').addEventListener('click', e => { const b = e.target.closest('button'); if (b) setFilter({ brMode: +b.dataset.mode }); });
  const brChanged = debounce(applyFilters, 120);
  ['#brMin', '#brMax'].forEach(s => $(s).addEventListener('input', () => { updateBrRange(); brChanged(); }));
  $('#optFav').addEventListener('change', e => setFilter({ fav: e.target.checked }));
  $('#optOwned').addEventListener('change', e => setFilter({ owned: e.target.checked }));
  $('#optPrem').addEventListener('change', e => setFilter({ prem: e.target.checked }));
  $('#optHidden').addEventListener('change', e => setFilter({ hidden: e.target.checked }));
  $('#sort').addEventListener('change', e => setFilter({ sort: e.target.value }));
  $('#btnReset').addEventListener('click', () => setFilter({ cat: 'all', nations: [], ranks: [], brMin: BR_MIN, brMax: BR_MAX, fav: false, owned: false, prem: false, hidden: false, q: '', stats: {}, wsel: [], roles: [] }));
  $('#search').addEventListener('input', debounce(e => { S.f.q = e.target.value; applyFilters(); }, 90));

  $$('.tab').forEach(b => b.addEventListener('click', () => showView(S.menuPage[b.dataset.menu] || menuPages(b.dataset.menu)[0])));
  $$('.subtab').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
  $('#btnSettings').addEventListener('click', openSettings);
  $('#dataMenu').addEventListener('click', dataMenuPick);
  document.addEventListener('click', e => { if (!e.target.closest('#dataMenu, #pillData')) $('#dataMenu').classList.add('hidden'); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#dataMenu').classList.add('hidden'); });
  $('#btnLaunchTop').addEventListener('click', launchGame);
  $('#btnOpenFolder').addEventListener('click', () => api('open-folder', {}).catch(toastErr));
  $('#btnSaveSettings').addEventListener('click', saveSettings);
  $('#btnCdkCleanup').addEventListener('click', cdkCleanup);
  $('#btnUninstall').addEventListener('click', openUninstall);
  $('#dlgUninstall').addEventListener('click', onUninstallClick);
  $('#dlgUninstall').addEventListener('change', renderUninstallState);
  $('#setHosts').addEventListener('change', hostWarnings);
  $('#btnUpdate').addEventListener('click', () => startUpdate($('#updateLog'), $('#btnUpdate')));
  $('#btnRemoveDatamine').addEventListener('click', async () => {
    try {
      S.status = await api('remove-datamine', {});
      $('#rowDatamine').classList.add('hidden');
      toast({ title: t('settings.datamineRemoved') });
    } catch (e) { toastErr(e); }
  });
  $('#btnCopyPreview').addEventListener('click', async () => {
    await navigator.clipboard.writeText($('#previewText').textContent);
    $('#btnCopyPreview').textContent = t('action.copied');
    setTimeout(() => { $('#btnCopyPreview').textContent = t('action.copy'); }, 1400);
  });

  document.addEventListener('keydown', e => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); showView('vehicles'); $('#search').focus(); $('#search').select(); }
    else if (e.key === 'Escape' && !document.querySelector('dialog[open]') && S.sel) { closeDrawer(); }
  });

  $('#missionList').addEventListener('click', onMissionListClick);
  $('#setupList').addEventListener('click', onSetupListClick);
}

const menuPages = menu => MENUS[menu].filter(v => !$(`.subtab[data-view="${v}"]`)?.classList.contains('hidden'));  // Windows only pages

function showView(name) {
  const menu = Object.keys(MENUS).find(m => MENUS[m].includes(name)), pages = menuPages(menu);
  S.menuPage[menu] = name;  // the menu comes back to it
  $$('.tab').forEach(b => b.classList.toggle('active', b.dataset.menu === menu));
  $('.tab.active')?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  $$('.subtab').forEach(b => { b.classList.toggle('active', b.dataset.view === name); b.classList.toggle('off', !pages.includes(b.dataset.view)); });
  document.body.classList.toggle('sub-on', pages.length > 1);
  $$('.view').forEach(v => v.classList.toggle('hidden', v.id !== 'view-' + name));
  document.body.classList.toggle('view-weapons', name === 'weapons');
  document.body.classList.toggle('view-maps', name === 'maps');
  document.body.classList.toggle('no-sidebar', name !== 'vehicles' && name !== 'setups');  // the filters: vehicles, My vehicles
  document.body.classList.toggle('pick-on', ['vehicles', 'maps', 'mymaps', 'setups'].includes(name));  // the vehicle + map bar
  if (name === 'maps') openMapsView();
  if (name === 'weapons') { if (S.sel) closeDrawer(); openWeaponsView(); }
  if (name === 'missions') refreshMissions();
  if (name === 'setups') renderSetups();
  if (name === 'mymaps') renderMyMaps();
  if (name === 'myweapons') renderMyWeapons();
  if (name === 'overlay') openOverlayView();
  else leaveOverlayView();
  if (name === 'flight') openFlightView();
  if (name === 'battle') openBattleView();
  if (name === 'history') openHistoryView();
  if (name === 'bench') openBenchView();
  if (name === 'changes') openChangesView();
  if (name === 'hangar') openHangarView();
  if (name === 'mods') openModsView();
  if (name === 'challenges') openChallengesView();
}

// ------------------------------------------------------------------ vehicle drawer
// opens a vehicle's panel; a loaded setup / mission (cfg) also selects it for the mission
async function openVehicle(id, cfg = null, { select = !!cfg } = {}) {
  const v = S.byId.get(id);
  if (!v) return;
  if (S.ai) aiEnd(false, false);  // an AI unit's loadout left unfinished
  S.sel = v;
  $$('.card.selected, .tcard.selected').forEach(c => c.classList.remove('selected'));
  $$(`.card[data-id="${CSS.escape(id)}"], .tcard[data-id="${CSS.escape(id)}"]`).forEach(c => c.classList.add('selected'));
  let d = S.details.get(id);
  if (!d) {
    try { d = await api('vehicle/' + encodeURIComponent(id)); S.details.set(id, d); }
    catch (e) { toastErr(e); return; }
  }
  if (S.sel !== v) return;
  // every vehicle keeps its setup while browsing; map edits follow from one vehicle to the next
  const hadCfg = !!S.cfg, prevEdits = S.cfg?.edits;
  if (S.cfg?.vehicle) S.cfgs.set(S.cfg.vehicle, S.cfg);
  S.cfg = cfg ? normalizeCfg(v, d, cfg) : S.cfgs.get(id) || defaultCfg(v, d);
  S.cfgs.set(id, S.cfg);
  if (!cfg && hadCfg) S.cfg.edits = prevEdits;
  // the picked map goes to the panel when it suits the vehicle (or was picked with this very vehicle)
  const ps = pickedScenario();
  const ownMap = !!cfg?.scenario;  // a mission's setup: its map, settings and edits come back with it
  if (ownMap) mapFromSetup(cfg);
  else if (ps && (scenarioFits(ps, v) || S.pick.vehicle === id)) S.cfg.scenario = ps.id;
  applyPickedVariant(S.cfg);
  if (select) selectVehicle(id, { ownMap });
  else renderPickbar();
  S.openStep = '';
  if (typeof LP !== 'undefined') LP.slot = null;
  renderDrawer({ keepScroll: false });
  $('.layout').classList.add('drawer-open');
  $('#drawer').setAttribute('aria-hidden', 'false');
}

// ------------------------------------------------------------------ an AI unit's loadout (map editor)
// the vehicle panel edits it like the player's (loadout, ammo); the editor gets {ui, preset, ammo, pylons} back
const aiLoadoutOf = (c, name = '') => ({ ...(name ? { name } : {}), ui: { preset: c.preset, ammo: JSON.parse(JSON.stringify(c.ammo)), pylons: c.pylons || null },
  preset: c.preset, ammo: ammoPayload(c), ...(cdkOn() && c.pylons ? { pylons: c.pylons } : {}) });
async function vehicleDetails(id) {
  let d = S.details.get(id);
  if (!d) { d = await api('vehicle/' + encodeURIComponent(id)); S.details.set(id, d); }
  return d;
}
async function openUnitLoadout(vid, loadout, { name = '' } = {}, done) {
  const v = S.byId.get(vid);
  let d;
  try { d = v && await vehicleDetails(vid); } catch (e) { toastErr(e); }
  if (!d) { done(null); return; }
  if (S.ai) aiEnd(false, false);
  S.ai = { sel: S.sel, cfg: S.cfg, step: S.openStep, done, name };
  S.sel = v;
  S.cfg = normalizeCfg(v, d, { ...(loadout?.ui || {}), scenario: S.ai.cfg?.scenario });
  S.openStep = 'loadout';
  if (typeof LP !== 'undefined') LP.slot = null;
  renderDrawer({ keepScroll: false });
  $('.layout').classList.add('drawer-open');
  $('#drawer').setAttribute('aria-hidden', 'false');
}
// back to what the panel showed before; reopen: hand the result to the editor (null: cancelled)
function aiEnd(apply, reopen = true) {
  const ai = S.ai;
  if (!ai) return;
  const res = apply ? aiLoadoutOf(S.cfg) : null;
  S.ai = null;
  S.cfg = ai.cfg;
  S.openStep = ai.step;
  if (ai.sel && S.cfg) { S.sel = ai.sel; renderDrawer({ keepScroll: false }); } else closeDrawer();
  if (reopen) ai.done(res);
}
// a saved vehicle (My vehicles) as an AI unit's loadout
async function loadoutFromSetup(s) {
  const v = S.byId.get(s.vehicle);
  let d;
  try { d = v && await vehicleDetails(v.id); } catch { return null; }
  return d ? aiLoadoutOf(normalizeCfg(v, d, s.cfg || {}), s.name) : null;
}

function closeDrawer() {
  $('.layout').classList.remove('drawer-open');
  $('#drawer').setAttribute('aria-hidden', 'true');
  $$('.card.selected, .tcard.selected').forEach(c => c.classList.remove('selected'));
  S.sel = null;
}

function scenariosFor(v, all = S.showAllScen) {
  const kinds = kindsFor(v.c);
  const levels = new Set(S.status.levels || []);
  const score = s => (kinds.includes(s.kind) ? 100 : 0) + (s.nation && s.nation === v.n ? 20 : 0)
    + (s.tags.includes('universal') ? (v.r >= 6 ? 12 : 4) : 0) + (s.tags.includes('jet') && v.r >= 5 ? 6 : 0)
    + (levels.size && !levels.has(s.map) ? -50 : 0) + (s.tags.includes('destroyer') === (v.k === 'destroyer' || v.k === 'cruiser') ? 2 : 0)
    + (s.free ? -40 : 0);  // the game's other maps (bare scenarios) after the test-drive ones
  return S.scenarios.filter(s => all || kinds.includes(s.kind)).sort((a, b) => score(b) - score(a) || I18N.map(a.map).localeCompare(I18N.map(b.map)));
}

function mainGun(d, v) { return v.c === 'ground' ? (d.am[0] || null) : null; }

function defaultAmmo(v, d) {
  if (v.c === 'ground') {
    const g = mainGun(d, v);
    if (!g) return [];
    const opts = g.opts.filter(o => !o.x);
    const def = opts[0] || g.opts[0];
    return [{ id: def ? def.id : '', count: g.cap || 30 }, { id: null, count: 0 }, { id: null, count: 0 }, { id: null, count: 0 }];
  }
  return d.am.slice(0, 4).map(g => ({ id: '', count: (g.cap || 0) * (g.n || 1) }));
}

// air start speed that suits the aircraft (km/h): drones and helicopters slow, propeller planes 450,
// early jets (rank V and below) 700, later jets 1000
function airStartSpeed(v) {
  if (v.c === 'heli') return 150;
  if (v.ro?.includes('drone')) return 100;
  if (v.s?.tw == null) return 450;
  return (v.r || 0) <= 5 ? 700 : 1000;
}

function defaultCfg(v, d) {
  const scen = scenariosFor(v, false)[0] || S.scenarios[0];
  const name = I18N.unit(v.id);
  return {
    vehicle: v.id, block: d.b || blockFor(v.c), scenario: scen?.id,
    preset: d.pr[0]?.id || '', ammo: defaultAmmo(v, d),
    environment: '', weather: '', start: 'scenario', altitude: 1500, speed: airStartSpeed(v), heading: '', fuel: 0,
    missionType: S.status.settings?.missionType || 'singleMission', allMods: true, mods: {}, pylons: null,
    cheats: { immortal: false, noOverload: false, superMobility: false, infAmmo: false, noReload: false, infFuel: false, passiveEnemies: false, hostileEnemies: false, ghost: false, crew: '', repairEvery: 0, hotkeys: false, targetsBack: false },
    title: '', fileName: '', _autoTitle: `Test Drive: ${name}`,
  };
}

function normalizeCfg(v, d, cfg) {
  const base = defaultCfg(v, d);
  const c = Object.assign({}, base, cfg, { vehicle: v.id, block: d.b || blockFor(v.c) });
  if (!S.scenarios.some(s => s.id === c.scenario)) c.scenario = base.scenario;
  if (!d.pr.some(p => p.id === c.preset) && c.preset !== 'wtftd_custom') c.preset = base.preset;
  c.cheats = Object.assign({}, base.cheats, cfg.cheats || {});
  delete c.targets;  // former "Training targets"
  if (cfg.edits && cfg.edits.sid) c.edits = JSON.parse(JSON.stringify(cfg.edits));
  // setups saved with a mission use the server format: convert back to the UI's
  c.mods = JSON.parse(JSON.stringify(c.mods || {}));
  delete c.mods.noReload;
  for (const g of Object.values(c.mods.guns || {})) {
    if (g.shells && '' in g.shells) { g.shells._ = g.shells['']; delete g.shells['']; }
  }
  if (v.c === 'ground' && Array.isArray(cfg.ammo)) {
    const first = base.ammo[0]?.id ?? '';  // a missile launcher's set: setups saved before the default one was left out
    c.ammo = !cfg.ammo.length ? base.ammo : [0, 1, 2, 3].map(i => {  // empty: a battery's radar saved before it had missiles
      const a = cfg.ammo[i];
      return a && (a.id || a.count) ? { id: a.id || first, count: +a.count || 0 } : { id: i === 0 ? first : null, count: 0 };
    });
  }
  if (c.heading == null) c.heading = '';
  if (c.preset === 'wtftd_custom') c.preset = base.preset;
  if (c.title && c.title === autoTitleFor(c)) c.title = '';
  if (c.fileName === `wtftd_${v.id}`) c.fileName = '';
  return c;
}

// the start all preset names of a vehicle share ("bf_109e_3_" for Bf-109E-3_4xSC50, Bf-109E-3_SC250…)
function presetPrefix(v) {
  const ids = (S.details.get(v.id)?.pr || []).map(p => p.id.toLowerCase().replace(/-/g, '_'));
  if (ids.length < 2) return '';
  let pre = ids[0];
  for (const s of ids) while (pre && !s.startsWith(pre)) pre = pre.slice(0, -1);
  return pre.slice(0, pre.lastIndexOf('_') + 1);
}

function presetLabel(v, p) {
  const id = p.id;
  if (/(^|_)default$/.test(id) && !p.w.length) return t('loadout.default');
  const prefix = v.id.toLowerCase().replace(/-/g, '_');
  let s = id.toLowerCase().replace(/-/g, '_');
  for (const pre of [presetPrefix(v), prefix + '_', prefix.replace(/^nt_/, '') + '_', prefix.split('_').slice(0, 2).join('_') + '_']) if (pre && s.startsWith(pre)) { s = s.slice(pre.length); break; }
  // then what is left of the vehicle's own name (fw_190a_5_u2: "190a_5_4xsc50", "190_flamm_250")
  const own = prefix.split('_');
  const words = s.split('_').filter(Boolean);
  while (words.length > 1 && own.some(o => o && o.startsWith(words[0]))) words.shift();
  s = words.join('_');
  if (s === 'default') return t('loadout.default');
  return words.map(w => {
    if (/^\d+x$/.test(w)) return `${w.slice(0, -1)}×`;  // 3x_aero_131a -> 3× Aero 131A
    const m = /^(\d+)x([a-z0-9].*)$/.exec(w);  // 4xsc50 -> SC50 ×4, as the game writes it
    if (m) return `${m[2].toUpperCase()} ×${m[1]}`;
    return /\d/.test(w) || w.length <= 3 ? w.toUpperCase() : w[0].toUpperCase() + w.slice(1);
  }).join(' ');
}

// a weapon's icon from the game's own table (weapons.json "ic"); gun pods have none there
function weaponIconId(k) {
  const ic = LP.weapons?.[k]?.ic;
  if (ic) return ic;
  return /^cannon/i.test(k) ? 'multibarrel_box_cannon' : /^gun/i.test(k) ? 'machine_gun' : '';
}

function presetChips(p) {
  if (!p.w.length) return `<span class="chip dim">${esc(t('loadout.empty'))}</span>`;
  return p.w.map(([k, n]) => {
    const ic = weaponIconId(k);
    return `<span class="chip${ic ? ' chip-w' : ''}">${ic ? ammoIcon(ic) : ''}<b>${n}×</b>${esc(I18N.weapon(k))}</span>`;
  }).join('');
}

function ammoLabel(o, belt = false, showPen = true) {
  const types = o.t.map(x => I18N.btype(x)).join(' / ');
  if (belt) {
    const m = o.id ? I18N.mod(o.id) : t('ammo.default');
    return `${m || o.id.replace(/_/g, ' ')}${types ? ` (${types})` : ''}`;
  }
  const names = o.b.map(b => I18N.bullet(b)).join(', ');
  const pen = showPen && (o.s?.k || o.s?.h || (o.s?.pc && Math.max(...o.s.pc.map(r => r[1]))));  // armor-piercing / HEAT / the others' curve
  return `${types || '?'}${names ? ' · ' + names : ''}${pen ? ' · ' + t('ammo.pen', { mm: Math.round(pen) }) : ''}${o.id ? '' : ' — ' + t('ammo.default')}`;
}

// Penetration by distance (mm of flat armor, shell at 0°) of the gun's shells: the table of the shell's file, or computed
// by the builder (s.pe) from the speed left at each distance.
const PEN_COLORS = [...AMMO_COLORS, '#ff7a6b', '#7de3d6'];
const PEN_DIST = [100, 500, 1000, 2000];
function curveAt(pc, d) {  // [[x, y], ...] by x, in straight lines; null beyond its end
  if (d <= pc[0][0]) return pc[0][1];
  for (let i = 1; i < pc.length; i++) {
    const [d0, p0] = pc[i - 1], [d1, p1] = pc[i];
    if (d <= d1) return Math.round(p0 + (p1 - p0) * (d - d0) / (d1 - d0));
  }
  return null;
}

function penChart(g, loaded, belt = false) {
  const shells = g.opts.filter(o => o.s?.pc && (S.showUnofficial || !o.x) && (!belt || loaded.has(o.id)));  // a belt: the one picked
  if (!shells.length) return '';
  const W = 300, H = 130, L = 32, R = 8, T = 8, B = 18;
  const dmax = Math.min(4000, Math.max(...shells.map(o => o.s.pc.at(-1)[0])));  // the tables end with far-off 0 mm rows
  const clip = pc => [...pc.filter(([d]) => d <= dmax), ...(pc.at(-1)[0] > dmax && pc.some(([d]) => d < dmax) ? [[dmax, curveAt(pc, dmax)]] : [])];
  const top = Math.ceil(Math.max(...shells.flatMap(o => o.s.pc.map(r => r[1]))) / 50) * 50;  // a missile that speeds up peaks later
  const X = d => L + d / dmax * (W - L - R), Y = p => H - B - p / top * (H - B - T);
  const color = o => PEN_COLORS[shells.indexOf(o) % PEN_COLORS.length];
  const grid = [0, 1, 2, 3, 4].map(i => `<line class="grid" x1="${L}" x2="${W - R}" y1="${Y(top * i / 4)}" y2="${Y(top * i / 4)}"/><text x="${L - 4}" y="${Y(top * i / 4) + 3}" text-anchor="end">${Math.round(top * i / 4)}</text>`).join('');
  const xs = [0, .25, .5, .75, 1].map(f => `<text x="${X(dmax * f)}" y="${H - 4}" text-anchor="middle">${Math.round(dmax * f)}</text>`).join('');
  const lines = shells.map(o => `<polyline fill="none" stroke="${color(o)}" stroke-width="${loaded.has(o.id) ? 2.5 : 1.5}" points="${clip(o.s.pc).map(([d, p]) => `${X(d)},${Y(p)}`).join(' ')}"/>`
    + clip(o.s.pc).map(([d, p]) => `<circle cx="${X(d)}" cy="${Y(p)}" r="3" fill="${color(o)}"><title>${esc(ammoLabel(o, belt))} · ${d} m: ${p} mm</title></circle>`).join('')).join('');
  const rows = shells.map(o => `<tr><td><i style="background:${color(o)}"></i>${o.s.pe ? '≈ ' : ''}${esc(ammoLabel(o, belt, false))}${loaded.has(o.id) ? ' ●' : ''}</td><td>${o.s.pc[0][1]}</td>${PEN_DIST.map(d => {
    const p = curveAt(o.s.pc, d);
    return `<td>${p == null ? '<span class="muted">—</span>' : p}</td>`;
  }).join('')}</tr>`).join('');
  return `<div class="pen-chart"><div class="pen-title">${esc(t('ammo.penChart'))}</div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(t('ammo.penChart'))}">${grid}${xs}<text x="${W - R}" y="${T + 2}" text-anchor="end">${esc(t('ammo.penAxis'))}</text>${lines}</svg>
    <table><thead><tr><th></th><th>10 m</th>${PEN_DIST.map(d => `<th>${d} m</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table>
    <small class="muted">${esc(t('ammo.penNote'))}</small></div>`;
}

function stepHTML(key, num, title, summary, body) {
  const open = S.openStep === key;
  return `<section class="step${open ? ' open' : ''}" data-step="${key}">
    <button class="step-head" data-toggle="${key}"><span class="step-num">${num}</span><span class="step-title">${esc(title)}</span>
      <span class="step-sum">${summary}</span><svg class="step-chev"><use href="#i-chev"/></svg></button>
    <div class="step-body">${open ? body() : ''}</div></section>`;
}

function renderDrawer({ keepScroll = true, reveal = null } = {}) {
  const v = S.sel, d = S.details.get(v.id), c = S.cfg;
  const prevScroll = keepScroll ? ($('#drawer .dr-scroll')?.scrollTop || 0) : 0;
  const scen = S.scenarios.find(s => s.id === c.scenario);
  const preset = d.pr.find(p => p.id === c.preset);
  const isFlyer = d.b === 'armada';
  const fav = S.favs.has(v.id);
  const brs = ['AB', 'RB', 'SB'].map((m, i) => `<div class="stat br"><small>${m}</small><b>${fmtBR(v.br?.[i])}</b></div>`).join('');

  const ammoSum = (() => {
    if (v.c === 'ground') {
      const g = mainGun(d, v); if (!g) return '';
      const used = c.ammo.filter(a => a.id !== null).reduce((s, a) => s + (+a.count || 0), 0);
      return esc(t('ammo.capacity', { used, cap: g.cap }));
    }
    return d.am.length ? esc(`${d.am.length} × ${t('ammo.belt').toLowerCase()}`) : '';
  })();
  const condSum = c.fuel ? `${c.fuel} %` : t('cond.keep');

  $('#drawer').style.setProperty('--tint', NATION_TINT[v.n] || NATION_TINT.other);
  $('#drawer').innerHTML = `
    <div class="drawer-resize" title="${esc(t('drawer.resize'))}"></div>
    <div class="dr-scroll">
      <div class="hero">
        <div class="hero-top">
          <div class="row gap">${v.r ? `<span class="chip">${esc(t('rank', { r: ROMAN[v.r] || v.r }))}</span>` : ''}<span class="chip">${icon(CAT_ICON[v.c], 'ic-sm')}${esc(className(v.k))}</span>
            ${v.h ? `<span class="tagx hid">${esc(t('badge.hidden'))}</span>` : v.p ? `<span class="tagx prem">${esc(t('badge.premium'))}</span>` : ''}</div>
          <div class="hero-actions">
            <button class="icon-btn${fav ? ' on' : ''}" data-act="fav" title="${esc(t(fav ? 'drawer.unfavorite' : 'drawer.favorite'))}">${icon('star')}</button>
            <button class="icon-btn${HG.owned.has(v.id) ? ' on' : ''}" data-act="own" title="${esc(t(HG.owned.has(v.id) ? 'hg.unmark' : 'hg.mark'))}">${icon('check')}</button>
            ${compareButtonHTML(v)}
            <button class="icon-btn" data-act="model3d" title="${esc(t('model.view'))}">${icon('cube')}</button>
            <a class="icon-btn" href="https://wiki.warthunder.com/unit/${encodeURIComponent(v.id)}" target="_blank" rel="noopener" title="${esc(t('drawer.wiki'))}">${icon('ext')}</a>
            <button class="icon-btn" data-act="close" title="${esc(t('drawer.close'))}">${icon('x')}</button>
          </div>
        </div>
        <div class="hero-img">${unitImgTag(v.id, true)}</div>
        <div class="hero-name">${flagHTML(v.n)}<h2>${esc(I18N.unit(v.id))}</h2></div>
        <div class="hero-full">${esc(I18N.unitFull(v.id))} · <code>${esc(v.id)}</code></div>
        <div class="hero-stats">${brs}</div>
        ${statsBlockHTML(v)}
        ${S.ai ? '' : chPanelLine(v)}
        ${S.ai ? '' : moPanelHTML(v)}
        ${limitsHTML(d.st?.lim)}
        ${S.ai ? '' : bnPanelHTML(v)}
      </div>
      ${S.ai ? `<div class="ai-banner">${icon('target', 'ic-sm')}<div><b>${esc(t('ai.title'))}</b>${esc(t('ai.hint'))}</div></div>` : ''}
      ${stepHTML('loadout', 1, t('step.loadout'), esc(c.pylons ? t('loadout.customShort', { n: Object.keys(c.pylons).length }) : preset ? presetLabel(v, preset) : t('loadout.default')), () => loadoutBody(v, d))}
      ${stepHTML('ammo', 2, t('step.ammo'), ammoSum, () => ammoBody(v, d))}
      ${S.ai ? '' : `${cdkOn() ? stepHTML('mods', 3, t('step.mods'), esc(countMods(c.mods) ? t('mods.count', { n: countMods(c.mods) }) : t('mods.stockShort')), () => modsBody(v, d)) : ''}
      ${stepHTML('cheats', cdkOn() ? 4 : 3, t('step.cheats'), esc(cheatsSummary()), () => cheatsBody())}
      ${isFlyer ? stepHTML('conditions', cdkOn() ? 5 : 4, t('step.fuel'), esc(condSum), () => conditionsBody(isFlyer)) : ''}
      ${stepHTML('advanced', cdkOn() ? (isFlyer ? 6 : 5) : (isFlyer ? 5 : 4), t('step.advanced'), esc(t(c.allMods ? 'adv.allModsOn' : 'adv.allModsOff')), () => advancedBody())}`}
    </div>
    ${S.lastGen?.vid === v.id && !S.ai ? `<div class="gen-done">${icon('check', 'ic-sm')}
      <div><b>${esc(t('toast.generated', { file: S.lastGen.file }))}</b><span>${esc(t('toast.generatedHint', { title: S.lastGen.title }))}</span></div>
      <button class="icon-btn" data-act="genDone" title="${esc(t('action.close'))}">${icon('x', 'ic-sm')}</button></div>` : ''}
    ${S.ai ? `<div class="dr-foot">
      <button class="btn btn-ghost btn-lg" data-act="aiCancel">${icon('x')}<span>${esc(t('ai.cancel'))}</span></button>
      <button class="btn btn-primary btn-lg" data-act="aiApply">${icon('check')}<span>${esc(t('ai.apply'))}</span></button>
    </div>` : `<div class="dr-foot">
      <button class="icon-btn" data-act="save" title="${esc(t('vehicle.save'))}">${icon('save')}</button>
      <button class="icon-btn" data-act="share" title="${esc(t('share.button'))}">${icon('share')}</button>
      <button class="btn btn-ghost" data-act="preview">${icon('file')}<span>${esc(t('action.preview'))}</span></button>
      ${S.pick.vehicle === v.id
        ? `<button class="btn btn-ghost btn-lg" data-act="select">${icon('check')}<span>${esc(t('pick.selected'))}</span></button>`
        : `<button class="btn btn-primary btn-lg" data-act="select">${icon('play')}<span>${esc(t('pick.select'))}</span></button>`}
    </div>`}`;
  bindDrawer();
  const sc = $('#drawer .dr-scroll');
  sc.scrollTop = prevScroll;
  if (reveal) {
    const el = $(`.step[data-step="${reveal}"]`, sc);
    if (el) {
      const top = el.offsetTop - 8;
      if (top < sc.scrollTop || top > sc.scrollTop + sc.clientHeight - 120) sc.scrollTo({ top, behavior: 'smooth' });
    }
  }
}

function loadoutBody(v, d) {
  const c = S.cfg;
  if (d.pr.length <= 1 && !(d.pr[0]?.w.length) && !(cdkOn() && (d.sl?.length || d.lp?.length))) return `<p class="hint">${esc(t('loadout.none'))}</p>`;
  const items = d.pr.map(p => `<button class="opt${c.preset === p.id ? ' active' : ''}" data-preset="${esc(p.id)}">
      <span class="opt-main"><span class="opt-title">${esc(presetLabel(v, p))}</span>
        <span class="chips">${presetChips(p)}${p.req ? `<span class="chip dim" title="${esc(p.req)}">${esc(t('loadout.requires', { mod: I18N.mod(p.req) || p.req }))}</span>` : ''}</span></span>
      <span class="opt-radio"></span></button>`).join('');
  if (d.sl?.length) return loadoutGridHTML(v, d);
  if (d.lp?.length && c.pylons) return loadoutGridHTML(v, d);  // fixed presets, custom: one column per attachment point
  if (d.b === 'armada' && d.pr.some(p => p.w.length)) return legacyGridHTML(v, d);  // fixed presets, as in the game
  // weapon icons need the catalog: draw again once it is loaded
  if (!LP.weapons) loadWeapons().then(w => { if (w && S.sel?.id === v.id) renderDrawer(); });
  return `<div class="opt-list">${items}</div>${d.b === 'armada' ? `<p class="hint" style="margin-top:12px">${esc(t('loadout.note'))}</p>` : ''}`;
}

// shell / belt icons from the game's own table (data/bullet_icons.json): a belt is drawn like the hangar
// draws it, its bullets in order repeated up to 4 (a countermeasure: once)
const shellImg = tp => {
  const ic = S.bulletIcons?.icons || {}, id = ic[String(tp || '').split('@')[0]] || ic.default_shell;
  return id ? `<img class="shell" src="/img/ammo/${encodeURIComponent(id)}.png" alt="" loading="lazy">` : '';
};
function beltIcons(o, once = false) {
  const types = o?.t || [];
  const n = once ? types.length : types.length * Math.max(1, Math.floor(4 / types.length));
  return types.length ? `<span class="belt">${Array.from({ length: n }, (_, i) => shellImg(types[i % types.length])).join('')}</span>` : '';
}

// countermeasure launcher whose capacity the game splits between flares and chaff
const cmFlare = g => g.trig === 'countermeasures' && g.opts.length === 2 ? g.opts.find(o => o.t?.[0] === 'flr') : null;
const cmChaff = g => cmFlare(g) ? g.opts.find(o => o.t?.[0] === 'chff') : null;
const cmTotal = g => (g.cap || 0) * (g.n || 1);
// the game sets countermeasures per launcher: totals move by the number of launchers
const cmStep = (g, n) => Math.round(n / (g.n || 1)) * (g.n || 1);
// chaff count of a split launcher's setting (saved missions: {chaff: {id, count}}; older setups: the chaff belt = all chaff)
const cmChaffCount = (g, a) => {
  const raw = a?.chaff && typeof a.chaff === 'object' ? +a.chaff.count || 0 : a?.chaff;
  return cmStep(g, Math.max(0, Math.min(cmTotal(g), raw ?? (a?.id && a.id === cmChaff(g)?.id ? cmTotal(g) : 0))));
};

function cmBody(g, i, a) {
  const total = cmTotal(g), ch = cmChaffCount(g, a), fl = total - ch, step = g.n || 1;
  const row = (o, n, key) => `<div class="cm-row">${shellImg(o.t[0])}<span>${esc(I18N.btype(o.t[0]))}</span>
      <input type="number" min="0" max="${total}" step="${step}" data-cm="${i}" data-cm-key="${key}" value="${n}"></div>`;
  return `${row(cmFlare(g), fl, 'flares')}${row(cmChaff(g), ch, 'chaff')}
    <input type="range" class="cm-range" min="0" max="${total}" step="${step}" data-cm="${i}" data-cm-key="chaff" value="${ch}">
    <small class="muted">${esc(t('ammo.cmSplit', { n: total }))}</small>`;
}

function ammoOptions(g, selected, belt) {
  const opts = g.opts.filter(o => S.showUnofficial || !o.x || o.id === selected);
  return opts.map(o => `<option value="${esc(o.id)}"${o.id === selected ? ' selected' : ''}>${esc(ammoLabel(o, belt))}${o.x ? ' ⚠' : ''}</option>`).join('');
}

function ammoBody(v, d) {
  const c = S.cfg;
  const unofficialToggle = d.am.some(g => g.opts.some(o => o.x))
    ? `<label class="switch" style="margin-top:4px"><input type="checkbox" data-bind="showUnofficial" ${S.showUnofficial ? 'checked' : ''}><span class="sw"></span><span>${esc(t('ammo.showUnofficial'))}</span></label>` : '';
  if (v.c === 'ground') {
    const g = mainGun(d, v);
    if (!g) return `<p class="hint">${esc(t('ammo.none'))}</p>`;
    const used = c.ammo.filter(a => a.id !== null).reduce((s, a) => s + (+a.count || 0), 0);
    const over = g.cap && used > g.cap;
    const slots = c.ammo.map((a, i) => `<div class="slot">
        <span class="slot-n" style="color:${a.id !== null ? AMMO_COLORS[i] : ''}">${i + 1}</span>
        <span class="slot-ic">${a.id !== null ? shellImg(g.opts.find(o => o.id === a.id)?.t?.[0]) : ''}</span>
        <select data-ammo="${i}"><option value="__empty"${a.id === null ? ' selected' : ''}>— ${esc(t('ammo.empty'))} —</option>${ammoOptions(g, a.id, false)}</select>
        <div class="stepper"><button data-step-ammo="${i}" data-d="-1">−</button><input type="number" min="0" data-count="${i}" value="${a.id === null ? 0 : a.count}" ${a.id === null ? 'disabled' : ''}><button data-step-ammo="${i}" data-d="1">+</button></div>
      </div>`).join('');
    const bar = g.cap ? c.ammo.map((a, i) => a.id === null ? '' : `<span style="width:${Math.min(100, (a.count / Math.max(g.cap, used)) * 100)}%;background:${AMMO_COLORS[i]}"></span>`).join('') : '';
    return `<div class="gun"><div class="gun-head">${icon('ammo', 'ic-sm')}<span class="gun-name">${esc(I18N.weapon(g.w))}</span>
        <div class="mini-actions"><button class="btn btn-ghost btn-sm" data-act="fill">${esc(t('ammo.fill'))}</button><button class="btn btn-ghost btn-sm" data-act="split">${esc(t('ammo.split'))}</button></div></div>
      ${slots}
      ${g.cap ? `<div class="cap"><div class="cap-bar">${bar}</div><div class="cap-legend${over ? ' over' : ''}"><span>${esc(t('ammo.capacity', { used, cap: g.cap }))}</span>${over ? `<span>${esc(t('ammo.overCap'))}</span>` : ''}</div></div>` : ''}
    </div>${penChart(g, new Set(c.ammo.filter(a => a.id !== null).map(a => a.id)))}${d.am.filter(x => x !== g && x.opts.some(o => /^(atgm|sam)/.test(o.t?.[0]))).map(x => penChart(x, new Set())).join('')}${unofficialToggle}${sightHTML()}`;
  }
  if (!d.am.length) return `<p class="hint">${esc(t('ammo.none'))}</p>`;
  const guns = d.am.map((g, i) => `<div class="gun"><div class="gun-head">${icon('ammo', 'ic-sm')}<span class="gun-name">${esc(I18N.weapon(g.w))}</span>
      ${g.n > 1 ? `<span class="chip">${esc(t('ammo.guns', { n: g.n }))}</span>` : ''}</div>
      ${cmChaff(g) && i < 4 ? cmBody(g, i, c.ammo[i]) + '</div>' : `<div class="belt-row">${beltIcons(g.opts.find(o => o.id === (c.ammo[i]?.id ?? '')), g.trig === 'countermeasures')}
        <select data-belt="${i}">${ammoOptions(g, c.ammo[i]?.id ?? '', true)}</select></div>${penChart(g, new Set([c.ammo[i]?.id ?? '']), true)}</div>`}`).join('');
  return `<p class="hint">${esc(t('ammo.beltNote'))}</p>${guns}${unofficialToggle}`;
}

// ------------------------------------------------------------------ custom sight (ground vehicles, sights.py)
async function loadSights(force = false) {
  if (S.sights && !force) return;
  S.sights = { dir: '', sights: [], loading: true };
  try { S.sights = await api('sights'); } catch { S.sights = { dir: '', sights: [] }; }
  if (S.sel?.c === 'ground' && S.openStep === 'ammo') renderDrawer();
}

function sightHTML() {
  if (!S.sights) { loadSights(); return ''; }
  const cur = S.cfg.sight || '';
  const known = S.sights.sights.some(x => x.id === cur);
  return `<div class="field sight-field"><label>${esc(t('sight.label'))}</label>
    <div class="field-row"><select data-sight>
      <option value="">${esc(t('sight.default'))}</option>
      ${cur && !known ? `<option value="${esc(cur)}" selected>${esc(cur.split('/').pop().replace(/\.blk$/i, ''))} ⚠</option>` : ''}
      ${S.sights.sights.map(x => `<option value="${esc(x.id)}"${x.id === cur ? ' selected' : ''}>${esc(x.name)} · ${esc(x.folder || t('sight.library'))}</option>`).join('')}
    </select><button class="btn btn-sm btn-ghost" data-act="sightImport">${icon('file', 'ic-sm')}<span>${esc(t('sight.import'))}</span></button></div>
    <small class="muted">${esc(t('sight.hint'))}</small>
    ${S.sights.loading ? '' : S.sights.dir ? '' : `<small class="warn">${esc(t('sight.noDir'))}</small>`}</div>`;
}

function importSight() {
  const inp = document.createElement('input');
  inp.type = 'file';
  inp.accept = '.blk';
  inp.onchange = async () => {
    const f = inp.files?.[0];
    if (!f) return;
    try {
      const r = await api('sight-import', { name: f.name, text: await f.text() });
      S.sights = { dir: r.dir, sights: r.sights };
      if (S.cfg) S.cfg.sight = r.id;
      renderDrawer();
    } catch (e) { toastErr(e); }
  };
  inp.click();
}

function conditionsBody(isFlyer) {
  const c = S.cfg;
  const seg = (name, values, cur, label) => `<div class="seg seg-wrap" data-seg="${name}">
      <button class="${!cur ? 'active' : ''}" data-v="">${esc(t('cond.keep'))}</button>
      ${values.map(x => `<button class="${cur === x ? 'active' : ''}" data-v="${x}">${esc(t(label + x))}</button>`).join('')}</div>`;
  return `${isFlyer ? `<p class="hint">${esc(t('cond.startMoved'))}</p>
      <div class="field"><label>${esc(t('cond.fuel'))}</label><div class="slider-row"><input type="range" min="0" max="100" step="5" data-fuel value="${c.fuel || 0}"><output>${fuelLabel(c.fuel)}</output></div>
        <small class="muted">${esc(t('cond.fuelHint'))}</small></div>` : ''}`;
}

// "45 % · ~1 230 kg" (tank capacity from the flight model, or the custom value in Modifications)
function fuelLabel(pct) {
  if (!pct) return esc(t('cond.fuelKeep'));
  const cap = S.cfg.mods?.fuel ?? S.details.get(S.cfg.vehicle)?.st?.fuel;
  return `${pct} %${cap ? ` · ~${Math.round(cap * pct / 100).toLocaleString()} kg` : ''}`;
}

function advancedBody() {
  const c = S.cfg;
  return `<label class="switch"><input type="checkbox" data-check="allMods" ${c.allMods ? 'checked' : ''}><span class="sw"></span><span>${esc(t('adv.allMods'))}</span></label>`;
}

function autoTitleFor(c) {
  const s = S.scenarios.find(x => x.id === c.scenario);
  const sv = c.scenario === S.pick.scenario ? savedVariant() : null;
  return `Test Drive: ${I18N.unit(c.vehicle)}${sv ? ' - ' + sv.name : s ? ' - ' + I18N.map(s.map) : ''}`;
}
const autoTitle = () => autoTitleFor(S.cfg);

function bindDrawer() {
  const dr = $('#drawer');
  dr.onclick = e => {
    const row = e.target.closest('[data-lrow]');
    if (row) { loadoutRowClick(row, S.sel, S.details.get(S.sel.id)); return renderDrawer(); }
    const b = e.target.closest('button, a');
    if (!b) return;
    const c = S.cfg, v = S.sel, d = S.details.get(v.id);
    if (loadoutClick(b, v, d)) return renderDrawer();
    if (b.dataset.crew !== undefined) { c.cheats.crew = b.dataset.crew; delete c.cheats.expertCrew; return renderDrawer(); }
    if (b.dataset.modreset) { setPath(c.mods, b.dataset.modreset, null); return renderDrawer(); }
    if (b.dataset.toggle) { S.openStep = S.openStep === b.dataset.toggle ? '' : b.dataset.toggle; return renderDrawer({ reveal: S.openStep }); }
    if (b.dataset.preset !== undefined) { c.preset = b.dataset.preset; return renderDrawer(); }
    if (b.dataset.stepAmmo !== undefined) {
      const i = +b.dataset.stepAmmo, a = c.ammo[i];
      if (a.id === null) return;
      const g = mainGun(d, v);
      const stepSize = g && g.cap >= 200 ? 10 : 1;
      a.count = Math.max(0, (+a.count || 0) + (+b.dataset.d) * stepSize);
      return renderDrawer();
    }
    const seg = b.closest('[data-seg]');
    if (seg) { c[seg.dataset.seg] = b.dataset.v; return renderDrawer(); }
    switch (b.dataset.act) {
      case 'close': return S.ai ? aiEnd(false) : closeDrawer();
      case 'aiApply': return aiEnd(true);
      case 'aiCancel': return aiEnd(false);
      case 'fav': return toggleFav(v.id);
      case 'own': return hgToggle(v.id);
      case 'skin3d': return moPreview(b.dataset.skin);
      case 'skinOpen': return moOpen('skin', b.dataset.skin);
      case 'goal': return hgAddGoal(v.id);
      case 'changes': return chShowVehicle(v);
      case 'ecoMode': return setFilter({ brMode: +b.dataset.mode });
      case 'compare': return toggleCompare(v.id);
      case 'bench': return bnFrom(v);
      case 'model3d': return openModel('vehicle', v.id, I18N.unit(v.id));
      case 'select': return selectVehicle(v.id);
      case 'preview': return preview();
      case 'save': return saveSetup();
      case 'share': return openShare();
      case 'reset-mods': c.mods = {}; return renderDrawer();
      case 'editor': return openEditor();
      case 'genDone': S.lastGen = null; return renderDrawer();
      case 'sightImport': return importSight();
      case 'fill': {
        const g = mainGun(d, v); const used = c.ammo.reduce((s, a, i) => s + (a.id !== null && i > 0 ? +a.count : 0), 0);
        if (c.ammo[0].id !== null) c.ammo[0].count = Math.max(0, g.cap - used);
        return renderDrawer();
      }
      case 'split': {
        const g = mainGun(d, v); const act = c.ammo.filter(a => a.id !== null);
        act.forEach((a, i) => { a.count = Math.floor(g.cap / act.length) + (i < g.cap % act.length ? 1 : 0); });
        return renderDrawer();
      }
    }
  };
  dr.onchange = e => {
    const el = e.target, c = S.cfg;
    if (el.dataset.bind) { S[el.dataset.bind] = el.checked; return renderDrawer(); }
    if (el.dataset.sight !== undefined) { if (el.value) c.sight = el.value; else delete c.sight; return renderDrawer(); }
    if (el.dataset.ammo !== undefined) {
      const a = c.ammo[+el.dataset.ammo];
      const was = a.id;
      a.id = el.value === '__empty' ? null : el.value;
      if (was === null && a.id !== null && !a.count) {
        const g = mainGun(S.details.get(S.sel.id), S.sel);
        a.count = Math.min(10, g?.cap || 10);
        const used = c.ammo.reduce((sum, x) => sum + (x.id !== null ? +x.count || 0 : 0), 0);
        const over = g?.cap ? used - g.cap : 0;
        const first = c.ammo.find(x => x !== a && x.id !== null);
        if (over > 0 && first) first.count = Math.max(0, first.count - over);
      }
      return renderDrawer();
    }
    if (el.dataset.count !== undefined) { c.ammo[+el.dataset.count].count = Math.max(0, parseInt(el.value, 10) || 0); return renderDrawer(); }
    if (el.dataset.cm !== undefined) {
      const i = +el.dataset.cm, g = S.details.get(S.sel.id).am[i], total = cmTotal(g);
      const n = cmStep(g, Math.max(0, Math.min(total, parseInt(el.value, 10) || 0)));
      c.ammo[i] = Object.assign(c.ammo[i] || {}, { id: '', count: total, chaff: el.dataset.cmKey === 'chaff' ? n : total - n });
      return renderDrawer();
    }
    if (el.dataset.belt !== undefined) { const i = +el.dataset.belt; c.ammo[i] = Object.assign(c.ammo[i] || {}, { id: el.value }); return renderDrawer(); }
    if (el.dataset.field) { c[el.dataset.field] = el.value; if (el.dataset.field === 'missionType') { renderDrawer(); } return; }
    if (el.dataset.check) { c[el.dataset.check] = el.checked; return renderDrawer(); }
    if (el.dataset.cheat) {
      c.cheats[el.dataset.cheat] = el.checked;
      return renderDrawer();
    }
    if (el.dataset.cheatnum) { c.cheats[el.dataset.cheatnum] = +el.value; return renderDrawer(); }
    if (el.dataset.mod) {
      const val = el.value.trim() === '' ? null : +el.value;
      setPath(c.mods, el.dataset.mod, Number.isFinite(val) ? val : null);
      return renderDrawer();
    }
    if (el.dataset.modshell !== undefined) { (S.modShell ||= {})[el.dataset.modshell] = el.value; return renderDrawer(); }
    if (el.dataset.modsel) { setPath(c.mods, el.dataset.modsel, el.value || null); return renderDrawer(); }
    if (el.dataset.modav) {  // an override only when it differs from the aircraft's own
      const own = (S.details.get(c.vehicle)?.av || []).includes(el.dataset.modav);
      setPath(c.mods, `avionics.${el.dataset.modav}`, el.checked === own ? null : el.checked);
      return renderDrawer();
    }
    if (el.dataset.bindCfg === 'customPylons') {
      const p = S.details.get(S.sel.id).pr.find(x => x.id === c.preset);
      c.pylons = el.checked ? Object.fromEntries(Object.entries((p && presetPylons(p)) || {}).map(([k, val]) => [+k, val])) : null;
      LP.slot = null;
      return renderDrawer();
    }
    if (loadoutChange(el)) return renderDrawer();
    if (el.dataset.pylon !== undefined) { if (el.value) c.pylons[el.dataset.pylon] = el.value; else delete c.pylons[el.dataset.pylon]; return renderDrawer(); }
  };
  dr.oninput = e => {
    const el = e.target;
    if (loadoutInput(el)) return;
    if (el.dataset.cm !== undefined && el.type === 'range') {  // flares / chaff counts follow the slider live
      const i = +el.dataset.cm, g = S.details.get(S.sel.id).am[i], total = cmTotal(g);
      const ch = cmStep(g, Math.max(0, Math.min(total, parseInt(el.value, 10) || 0)));
      S.cfg.ammo[i] = Object.assign(S.cfg.ammo[i] || {}, { id: '', count: total, chaff: ch });
      const box = el.parentElement;
      box.querySelector(`input[type=number][data-cm="${i}"][data-cm-key="flares"]`).value = total - ch;
      box.querySelector(`input[type=number][data-cm="${i}"][data-cm-key="chaff"]`).value = ch;
      return;
    }
    if (el.dataset.cheatnum) { el.nextElementSibling.textContent = +el.value ? `${el.value} s` : t('cheat.off'); return; }
    if (el.dataset.fuel !== undefined) { S.cfg.fuel = +el.value; el.nextElementSibling.textContent = fuelLabel(S.cfg.fuel); return; }
    if (el.dataset.num) { S.cfg[el.dataset.num] = +el.value; el.nextElementSibling.textContent = `${el.value} ${el.dataset.num === 'altitude' ? 'm' : 'km/h'}`; }
  };
}

function toggleFav(id) {
  S.favs.has(id) ? S.favs.delete(id) : S.favs.add(id);
  store.set('favs', [...S.favs]);
  const card = $(`.card[data-id="${CSS.escape(id)}"]`);
  if (card) card.outerHTML = cardHTML(S.byId.get(id));
  if (currentView() === 'tree') renderTree();
  if (S.sel?.id === id) renderDrawer();
}

// ------------------------------------------------------------------ mission actions
// belts / shells of a setup as the server wants them (countermeasure launchers split in flares + chaff)
function ammoPayload(c) {
  return c.ammo.map((a, i) => {
      const g = c.block === 'armada' ? S.details.get(c.vehicle)?.am[i] : null;
      if (g && cmChaff(g)) {  // split countermeasure launcher
        const total = cmTotal(g), ch = cmChaffCount(g, a);
        if (ch === 0) return { id: '', count: total };
        if (ch === total) return { id: cmChaff(g).id, count: total };
        return { id: '', count: total - ch, chaff: { id: cmChaff(g).id, count: ch } };
      }
      return a && a.id !== null ? { id: a.id || '', count: +a.count || 0 } : { id: '', count: 0 };
  });
}

function missionPayload() {
  const c = S.cfg;
  return {
    scenario: c.scenario, vehicle: c.vehicle, block: c.block, preset: c.preset,
    ammo: ammoPayload(c),
    environment: S.map.environment, weather: S.map.weather, start: 'scenario', altitude: c.altitude, speed: c.speed,
    heading: null, missionType: missionOpts().missionType, allMods: c.allMods,
    fuel: (c.block === 'armada' && c.fuel) || null,
    title: missionOpts().title || autoTitle(), fileName: missionOpts().fileName || `wtftd_${c.vehicle}`,
    description: missionOpts().description || undefined,
    mods: cdkOn() ? Object.assign(modsPayload(c.mods), c.cheats.noReload ? { noReload: true } : {}) : undefined,
    pylons: cdkOn() && c.pylons ? c.pylons : undefined,
    cheats: { ...c.cheats, passiveEnemies: S.map.enemies === 'passive', hostileEnemies: S.map.enemies === 'hostile' },
    hotkeyTexts: c.cheats.hotkeys ? hotkeyTexts() : undefined,
    sight: c.block === 'tankModels' && c.sight ? c.sight : undefined,
    edits: c.edits && c.edits.sid === c.scenario ? { ...c.edits, waveText: t('editor.waveText') } : undefined,
  };
}

async function generate(btn, extra = {}) {
  btn.disabled = true;
  btn.querySelector('span').textContent = t('action.generating');
  try {
    await edAutoRefresh();  // map editor units that follow your vehicle's BR
    const body = { ...missionPayload(), ...extra };
    const r = await api('generate', body);
    S.lastGen = { vid: S.cfg.vehicle, file: r.file, title: body.title };  // stays shown above the button
    if (S.sel && S.sel.id === S.cfg.vehicle) renderDrawer();
    toast({
      title: t('toast.generated', { file: r.file }),
      sub: t('toast.generatedHint', { title: body.title }) + (r.cdkFiles?.length ? ' ' + t('toast.cdkHint', { n: r.cdkFiles.length }) : '')
        + (r.sight?.error ? ' ' + t('sight.failed', { error: r.sight.error })
          : r.sight?.vehicles?.length ? ' ' + t('sight.installed', { file: r.sight.file, vehicle: r.sight.vehicles.map(x => I18N.unit(x)).join(', ') }) : ''),
      ms: r.sight ? 20000 : 12000,
      actions: [{ label: t('action.launch'), icon: 'play', primary: true, run: launchGame }, { label: t('action.openFolder'), icon: 'folder', run: () => api('open-folder', {}) }],
    });
    refreshMissions();
  } catch (e) { toastErr(e); }
  finally { btn.disabled = false; btn.querySelector('span').textContent = t('action.generate'); }
}

async function preview() {
  try {
    await edAutoRefresh();  // map editor units that follow your vehicle's BR
    const r = await api('preview', missionPayload());
    $('#previewName').textContent = r.file;
    const extra = Object.entries(r.files || {}).map(([path, text]) => `\n\n// ===== content/pkg_local/${path}\n${text}`).join('');
    $('#previewText').textContent = r.text + extra;
    $('#dlgPreview').showModal();
  } catch (e) { toastErr(e); }
}

async function launchGame() {
  try { await api('launch', {}); toast({ title: t('toast.launched'), ms: 4000 }); } catch (e) { toastErr(e); }
}

function promptText(title, value) {
  return new Promise(resolve => {
    const dlg = $('#dlgPrompt');
    $('#promptTitle').textContent = title;
    $('#promptInput').value = value;
    dlg.onclose = () => resolve(dlg.returnValue === 'ok' ? $('#promptInput').value.trim() : null);
    dlg.showModal();
    $('#promptInput').select();
  });
}

async function saveSetup() {
  const c = S.cfg;
  const p = S.details.get(c.vehicle)?.pr.find(x => x.id === c.preset);
  const name = await promptText(t('vehicle.saveName'), `${I18N.unit(c.vehicle)}${c.pylons ? ' · ' + t('loadout.customRow') : p && p.w.length ? ' · ' + presetLabel(S.byId.get(c.vehicle), p) : ''}`);
  if (!name) return;
  const cfg = vehicleOnly(c);
  S.setups.unshift({ id: Date.now().toString(36), name, vehicle: c.vehicle, cfg, created: Date.now() });
  await persistSetups();
  toast({ title: t('vehicle.saved', { name }), ms: 3000 });
}

async function persistSetups() {
  try { await api('setups', { setups: S.setups }); } catch (e) { toastErr(e); }
  $('#setupCount').textContent = S.setups.length || '';
  renderSetups();
}

async function refreshSetups() {
  try { S.setups = await api('setups'); } catch { S.setups = []; }
  $('#setupCount').textContent = S.setups.length || '';
  renderSetups();
}

function listThumb(vid) {
  return `<div class="list-thumb">${unitImgTag(vid, true)}</div>`;
}

// ------------------------------------------------------------------ cheats (mission rules)
const CHEATS = [
  ['immortal', 'cheat.immortal', 'cheat.immortalHint'],
  ['noOverload', 'cheat.noOverload', 'cheat.noOverloadHint', 'flyer'],  // custom aircraft / helicopters only
  ['superMobility', 'cheat.superMobility', 'cheat.superMobilityHint', 'ground,air'],  // custom ground vehicles / aircraft
  ['infAmmo', 'cheat.infAmmo', 'cheat.infAmmoHint'],
  ['noReload', 'cheat.noReload', 'cheat.noReloadHint'],
  ['infFuel', 'cheat.infFuel', 'cheat.infFuelHint'],
  ['ghost', 'cheat.ghost', 'cheat.ghostHint'],
  ['targetsBack', 'cheat.targetsBack', 'cheat.targetsBackHint'],
  ['hotkeys', 'cheat.hotkeys', 'cheat.hotkeysHint'],
];
// in-mission keys: the hints the mission shows, in the player's language (mission.HOTKEY_TEXTS)
const hotkeyTexts = () => Object.fromEntries(['on', 'off', 'immortal', 'reload', 'passive', 'repair', 'targets', 'start', 'help', 'intro']
  .map(k => [k, t('hk.' + k)]));

function cheatsBody() {
  const ch = S.cfg.cheats;
  const cat = S.byId.get(S.cfg.vehicle)?.c, flyer = ['air', 'heli'].includes(cat);
  const rows = CHEATS.filter(([, , , only]) => !only || (only === 'flyer' ? flyer : only.split(',').includes(cat))).map(([k, label, hint]) => `<label class="cheat${ch[k] ? ' on' : ''}">
      <input type="checkbox" data-cheat="${k}" ${ch[k] ? 'checked' : ''}><span class="sw"></span>
      <span class="cheat-txt"><b>${esc(t(label))}</b><small>${esc(t(hint))}${k === 'noReload' && !cdkOn() ? ' ' + esc(t('cheat.noReloadCdk')) : ''}${['noOverload', 'superMobility'].includes(k) && !cdkOn() ? ' ' + esc(t('cheat.needsCdk')) : ''}</small></span></label>`).join('');
  const crew = ch.crew || (ch.expertCrew ? 'expert' : '');
  return `<div class="cheats">${rows}</div>
    <div class="field" style="margin-top:12px"><label>${esc(t('cheat.crew'))}</label>
      <div class="seg">${['', 'expert', 'ace'].map(k => `<button class="${crew === k ? 'active' : ''}" data-crew="${k}">${esc(t('cheat.crew.' + (k || 'default')))}</button>`).join('')}</div>
      <small class="muted">${esc(t('cheat.crewHint'))}</small></div>
    <div class="field" style="margin-top:12px"><label>${esc(t('cheat.repair'))}</label>
      <div class="slider-row"><input type="range" min="0" max="60" step="5" data-cheatnum="repairEvery" value="${ch.repairEvery || 0}"><output>${ch.repairEvery ? ch.repairEvery + ' s' : esc(t('cheat.off'))}</output></div>
      <small class="muted">${esc(t('cheat.repairHint'))}</small></div>`;
}

function cheatsSummary() {
  const n = CHEATS.filter(([k]) => S.cfg.cheats[k]).length + (S.cfg.cheats.repairEvery ? 1 : 0) + (S.cfg.cheats.crew ? 1 : 0);
  return n ? t('cheat.count', { n }) : t('cheat.none');
}

// ------------------------------------------------------------------ custom vehicle (CDK) modifications
const cdkOn = () => S.status?.cdk?.enabled !== false;
const hostOf = cat => (S.status?.settings?.hosts || {})[cat] || S.status?.cdk?.defaultHosts?.[cat] || '';

// field: [path, label key, stock value, unit, step]; values are stored in cfg.mods by path
function modFields(v, d) {
  const st = d.st || {};
  const f = [];
  if (v.c === 'ground') {
    f.push({ sec: 'mods.mobility' });
    if (st.hp != null) f.push(['hp', 'mods.hp', st.hp, 'hp', 10]);
    if (st.rpm != null) f.push(['rpm', 'mods.rpm', st.rpm, 'rpm', 50]);
    if (st.mass != null) f.push(['mass', 'mods.mass', st.mass, 'kg', 100]);
    if (st.brake != null) f.push(['brake', 'mods.brake', st.brake, 'N', 1000]);
    if (st.gear != null) f.push(['speedMul', 'mods.speedMul', 1, '×', 0.05]);
  } else if (v.c === 'air' || v.c === 'heli') {
    if (st.fm) {
      f.push({ sec: 'mods.flight' });
      if (st.mass != null) f.push(['mass', 'mods.mass', st.mass, 'kg', 50]);
      if (st.fuel != null) f.push(['fuel', 'mods.fuel', st.fuel, 'kg', 50]);
      if (st.thrust) f.push(['thrustMul', 'mods.thrustMul', 1, '×', 0.05]);
      if (st.tboost != null) f.push(['tboost', 'mods.tboost', st.tboost, '×', 0.01]);
      if (st.abboost != null) f.push(['abboost', 'mods.abboost', st.abboost, '×', 0.01]);
    }
  }
  return f;
}

function getPath(o, path) { return path.split('.').reduce((a, k) => (a == null ? a : a[k]), o); }
function setPath(o, path, val) {
  const ks = path.split('.');
  let cur = o;
  ks.slice(0, -1).forEach(k => { cur = cur[k] ||= {}; });
  if (val === null) delete cur[ks.at(-1)]; else cur[ks.at(-1)] = val;
}
function countMods(m) {
  if (!m || typeof m !== 'object') return 0;
  return Object.values(m).reduce((n, x) => n + (x && typeof x === 'object' ? countMods(x) : 1), 0);
}

function modInput(path, label, stock, unit, step) {
  const val = getPath(S.cfg.mods, path);
  const changed = val != null && val !== '';
  const fmt = x => (Math.abs(x) >= 100 ? Math.round(x) : +(+x).toFixed(3));
  return `<div class="mod${changed ? ' changed' : ''}">
    <label>${esc(t(label))}</label>
    <div class="mod-in"><input type="number" step="${step}" data-mod="${esc(path)}" value="${changed ? esc(val) : ''}" placeholder="${esc(fmt(stock))}"><span>${esc(unit)}</span>
    ${changed ? `<button class="icon-btn" data-modreset="${esc(path)}" title="${esc(t('mods.reset'))}">${icon('refresh', 'ic-sm')}</button>` : ''}</div>
    <small>${esc(t('mods.stock', { v: fmt(stock) + (unit === '×' ? '×' : ' ' + unit) }))}</small>
  </div>`;
}

function modsBody(v, d) {
  if (!cdkOn()) return `<p class="hint">${esc(t('mods.off'))}</p>`;
  const host = hostOf(v.c);
  const customAir = (v.c === 'air' || v.c === 'heli') && (S.status?.cdk?.airMethod || 'custom') === 'custom';
  const note = customAir ? t('mods.noteAir') : t('mods.note', { host: host ? I18N.unit(host) : '—' });
  let html = `<div class="cdk-note">${icon('bolt', 'ic-sm')}<div>${esc(note)}</div></div>`;
  let grid = [];
  const flush = () => { if (grid.length) { html += `<div class="mod-grid">${grid.join('')}</div>`; grid = []; } };
  for (const f of modFields(v, d)) {
    if (f.sec) { flush(); html += `<div class="opt-group-title">${esc(t(f.sec))}</div>`; continue; }
    grid.push(modInput(...f));
  }
  flush();
  if (v.c === 'air' || v.c === 'heli') html += aircraftPartsHTML(v, d);
  html += voicesHTML(v);
  // guns listed directly on the vehicle (tank main gun, ship guns, older aircraft guns)
  (d.am || []).forEach((g, gi) => {
    if (!g.wi) return;
    const base = `guns.${gi}`;
    html += `<div class="opt-group-title">${icon('ammo', 'ic-sm')} ${esc(I18N.weapon(g.w))}${g.n > 1 ? ` ×${g.n}` : ''}</div>`;
    const fields = [];
    if (g.yaw != null) fields.push(modInput(`${base}.yaw`, 'mods.yaw', g.yaw, '°/s', 1));
    if (g.pitch != null) fields.push(modInput(`${base}.pitch`, 'mods.pitch', g.pitch, '°/s', 1));
    if (g.cap) fields.push(modInput(`${base}.cap`, 'mods.cap', g.cap, t('mods.rounds'), 1));
    if (g.sf) fields.push(modInput(`${base}.reload`, v.c === 'ground' ? 'mods.reload' : 'mods.interval', +(1 / g.sf).toFixed(3), 's', 0.1));
    html += `<div class="mod-grid">${fields.join('')}</div>`;
    if (v.c !== 'air' && v.c !== 'heli') {  // the list fills when opened (swapList): a ship has many guns, the game a thousand weapons
      loadWeapons();
      const swap = getPath(S.cfg.mods, `${base}.swap`);
      html += `<div class="shell-pick"><label>${esc(t('mods.swap'))}</label><select data-modsel="${base}.swap" data-modswap><option value="">${esc(I18N.weapon(g.w))}</option>${swap ? `<option value="${esc(swap)}" selected>${esc(I18N.weapon(swap))}</option>` : ''}</select></div>`;
    }
    const shells = g.opts.filter(o => ['v', 'm', 'e', 'h', 'l'].some(k => o.s?.[k] != null) && (S.showUnofficial || !o.x));
    if (!shells.length) return;
    const sel = S.modShell?.[gi] ?? shells[0].id;
    const o = shells.find(x => x.id === sel) || shells[0];
    html += `<div class="shell-pick"><label>${esc(t('mods.shell'))}</label><select data-modshell="${gi}">${shells.map(x => {
      const n = countMods(getPath(S.cfg.mods, `${base}.shells.${x.id || '_'}`));
      return `<option value="${esc(x.id)}"${x.id === o.id ? ' selected' : ''}>${esc(ammoLabel(x, v.c !== 'ground'))}${n ? ` ● ${n}` : ''}</option>`;
    }).join('')}</select></div>`;
    const sp = `${base}.shells.${o.id || '_'}`;
    const sf = [];
    if (o.s.v != null) sf.push(modInput(`${sp}.v`, 'mods.speed', o.s.v, 'm/s', 10));
    if (o.s.m != null) sf.push(modInput(`${sp}.m`, 'mods.shellMass', o.s.m, 'kg', 0.1));
    if (o.s.e != null) sf.push(modInput(`${sp}.e`, 'mods.expl', o.s.e, 'kg', 0.05));
    if (o.s.h != null) sf.push(modInput(`${sp}.h`, 'mods.heat', o.s.h, 'mm', 10));
    if (o.s.l != null) sf.push(modInput(`${sp}.l`, 'mods.rod', o.s.l, 'mm', 10));
    html += `<div class="mod-grid">${sf.join('')}</div>`;
  });
  const n = countMods(S.cfg.mods);
  if (n) html += `<button class="btn btn-ghost btn-sm" data-act="reset-mods" style="margin-top:6px">${icon('refresh', 'ic-sm')}${esc(t('mods.resetAll'))}</button>`;
  return html;
}

// cfg.mods uses '_' for the default shell set; the server expects '' -> convert on send
const modRow = (label, path, list) => `<div class="shell-pick part"><label>${esc(label)}</label><select data-modsel="${path}">${list}</select></div>`;

// who speaks: the crew's country and, by kind of vehicle, the voices the game's files name
function voicesHTML(v) {
  const list = (path, first, values, name = x => x) => {
    const on = getPath(S.cfg.mods, path);
    return `<option value="">${esc(first)}</option>${values.map(x => `<option value="${esc(x)}"${x === on ? ' selected' : ''}>${esc(name(x))}</option>`).join('')}`;
  };
  const air = v.c === 'air' || v.c === 'heli';
  return `<div class="opt-group-title">${esc(t('mods.voices'))}</div>
    ${modRow(t('mods.crewCountry'), 'crewCountry', list('crewCountry', t('mods.asIs'), NATIONS, nationName))}
    ${air ? modRow(t('mods.warnVoice'), 'warningVoice', list('warningVoice', t('mods.asIs'), ['betty', 'rita', 'xiao906'], x => x[0].toUpperCase() + x.slice(1)))
    : modRow(t('mods.crewVoice'), 'crewVoice', list('crewVoice', t('mods.asIs'), ['SmKate', 'SmElsa', 'SmMaria', 'SmEmily', 'SmUsagi', 'SmLing'], x => x.slice(2)))}
    <small class="muted">${esc(t('mods.voiceHint'))}</small>`;
}

// a gun's Replace with: every ground and ship weapon, as cdk takes them
async function swapList(sel) {
  const w = await loadWeapons();
  if (sel.dataset.filled) return;
  sel.dataset.filled = '1';
  const on = sel.value, own = sel.options[0].textContent;
  const list = Object.keys(w).filter(k => /models_weapons/i.test(w[k].p || '')).map(k => [k, I18N.weapon(k)]).sort((a, b) => a[1].localeCompare(b[1]));
  sel.innerHTML = `<option value="">${esc(own)}</option>${list.map(([k, n]) => `<option value="${esc(k)}"${k === on ? ' selected' : ''}>${esc(n)}</option>`).join('')}`;
}
document.addEventListener('focusin', ev => { if (ev.target.matches?.('[data-modswap]')) swapList(ev.target); });

// what an aircraft is built from: its sensors, its engine, its avionics
function aircraftPartsHTML(v, d) {
  if (!S.sensors) {
    getData('sensors.json').then(list => { S.sensors = list; renderDrawer(); }).catch(() => { S.sensors = {}; });
    return '';
  }
  const opts = (kind, on, first) => `<option value="">${esc(first)}</option>` + Object.keys(S.sensors).filter(k => S.sensors[k] === kind)
    .map(k => [k, I18N.sensor(k)]).sort((a, b) => a[1].localeCompare(b[1])).map(([k, n]) => `<option value="${esc(k)}"${k === on ? ' selected' : ''}>${esc(n)}</option>`).join('');
  const row = modRow;
  const own = d.se || [], kinds = own.map(k => S.sensors[k]);
  const sensors = own.map((k, i) => (S.sensors[k] ? row(t('mods.sensor.' + S.sensors[k]), `sensors.${i}`, opts(S.sensors[k], getPath(S.cfg.mods, `sensors.${i}`), `${I18N.sensor(k)} · ${t('mods.asIs')}`)) : '')).join('');
  const extra = ['radar', 'rwr', 'mlws', 'lws'].filter(k => !kinds.includes(k)).map(k => row(t('mods.sensor.' + k), `sensorsAdd.${k}`, opts(k, getPath(S.cfg.mods, `sensorsAdd.${k}`), t('ov.redNone')))).join('');
  const engines = S.vehicles.filter(x => x.c === v.c && !x.h && x.id !== v.id && !x.j === !v.j).sort((a, b) => I18N.unit(a.id).localeCompare(I18N.unit(b.id)));
  const on = getPath(S.cfg.mods, 'engineFrom');
  const engine = row(t('mods.engineFrom'), 'engineFrom', `<option value="">${esc(t('mods.asIs'))}</option>${engines.map(x => `<option value="${esc(x.id)}"${x.id === on ? ' selected' : ''}>${esc(I18N.unit(x.id))}</option>`).join('')}`);
  const avionics = AVIONICS.map(k => {
    const state = getPath(S.cfg.mods, `avionics.${k}`) ?? (d.av || []).includes(k);
    return `<label class="switch"><input type="checkbox" data-modav="${k}"${state ? ' checked' : ''}><span class="sw"></span><span>${esc(t('mods.av.' + k))}</span></label>`;
  }).join('');
  return `<div class="opt-group-title">${esc(t('mods.sensors'))}</div>${sensors}${extra}
    <div class="opt-group-title">${esc(t('mods.engine'))}</div>${engine}
    <div class="opt-group-title">${esc(t('mods.avionics'))}</div><div class="mod-switches">${avionics}</div>`;
}

function modsPayload(m) {
  const out = JSON.parse(JSON.stringify(m || {}));
  delete out.nuke;  // old setups: nuclear bombs are now picked per pylon
  for (const g of Object.values(out.guns || {})) {
    if (g.shells && g.shells._) { g.shells[''] = g.shells._; delete g.shells._; }
  }
  return out;
}

function pylonBodyLegacy(v, d) {
  const c = S.cfg;
  const custom = !!c.pylons;
  let html = `<label class="switch" style="margin:10px 0 6px"><input type="checkbox" data-bind-cfg="customPylons" ${custom ? 'checked' : ''}><span class="sw"></span><span>${esc(t('loadout.custom'))}</span></label>`;
  if (!custom) return html;
  html += `<div class="pylons">${d.sl.map(s => {
    const cur = c.pylons[s.i] || '';
    const opt = s.o.find(o => o.n === cur);
    return `<div class="pylon"><span class="slot-n">${s.i}</span>
      <div class="pylon-main"><select data-pylon="${s.i}"><option value="">— ${esc(t('ammo.empty'))} —</option>${s.o.map(o => `<option value="${esc(o.n)}"${o.n === cur ? ' selected' : ''}>${esc(o.w.map(([k, n]) => `${n}× ${I18N.weapon(k)}`).join(', '))}</option>`).join('')}</select></div></div>`;
  }).join('')}</div>`;
  return html;
}

async function cdkCleanup() {
  try {
    const r = await api('cdk-cleanup', {});
    S.status = Object.assign(S.status, r);
    $('#cdkFiles').textContent = t('settings.cdkFiles', { n: r.cdk?.present || 0 });
    toast({ title: t('toast.cdkRemoved', { n: r.removed }) });
  } catch (e) { toastErr(e); }
}


// ------------------------------------------------------------------ uninstall (Settings): what WTFTD put on this PC
const UN_PARTS = ['cdk', 'missions', 'mods', 'cache', 'data', 'user', 'app'];
let unInfo = null, unArmed = false;
const fmtBytes = n => (n >= 1e9 ? (n / 1e9).toFixed(2) + ' GB' : n >= 1e6 ? (n / 1e6).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1e3)) + ' KB');

async function openUninstall() {
  $('#uninstallBody').innerHTML = `<p class="hint">${esc(t('uninstall.loading'))}</p>`;
  $('#uninstallFoot').classList.remove('hidden');
  $('#dlgUninstall').showModal();
  try { unInfo = await api('uninstall-info'); } catch (e) { toastErr(e); $('#dlgUninstall').close(); return; }
  unArmed = false;
  const i = unInfo;
  const hint = {
    cdk: t('uninstall.cdkHint', { n: i.cdk.files }), missions: t('uninstall.missionsHint', { n: i.missions.files }),
    mods: t(i.mods.config ? 'uninstall.modsConfigHint' : 'uninstall.modsHint', { skins: i.mods.skins, sounds: i.mods.sounds }),
    cache: t('uninstall.cacheHint', { size: fmtBytes(i.cache.bytes) }), data: t('uninstall.dataHint', { size: fmtBytes(i.data.bytes) }),
    user: t('uninstall.userHint', { size: fmtBytes(i.user.bytes) }),
    app: i.app.available ? t('uninstall.appHint', { path: i.app.path }) : t(i.app.translocated ? 'uninstall.appMac' : 'uninstall.appSource'),
  };
  $('#uninstallBody').innerHTML = `<p class="hint">${esc(t('uninstall.hint'))}</p>
    <div class="un-parts">
      <label class="un-part un-all"><input type="checkbox" data-un-all><span><b>${esc(t('uninstall.all'))}</b><small>${esc(t('uninstall.allHint'))}</small></span></label>
      ${UN_PARTS.map(p => `<label class="un-part${p === 'app' && !i.app.available ? ' off' : ''}"><input type="checkbox" data-un="${p}"${p === 'app' && !i.app.available ? ' disabled' : ''}>
        <span><b>${esc(t('uninstall.' + p))}</b><small>${esc(hint[p])}</small></span></label>`).join('')}
    </div>
    <p class="hint">${esc(t('uninstall.gameSafe'))}</p>`;
  renderUninstallState();
}
const unChosen = () => $$('#uninstallBody [data-un]').filter(c => c.checked).map(c => c.dataset.un);
function renderUninstallState(ev) {
  const all = $('#uninstallBody [data-un-all]');
  const boxes = $$('#uninstallBody [data-un]').filter(c => !c.disabled);
  if (ev?.target === all) boxes.forEach(c => { c.checked = all.checked; });
  else if (all) all.checked = boxes.length > 0 && boxes.every(c => c.checked);
  $$('#uninstallBody .un-part').forEach(l => l.classList.toggle('on', !!l.querySelector('input')?.checked));
  unArmed = false;
  const n = unChosen().length, go = $('#btnUninstallGo');
  go.disabled = !n;
  go.querySelector('span').textContent = t('uninstall.go');
}
async function onUninstallClick(ev) {
  if (ev.target.closest('[data-un-close]')) { $('#dlgUninstall').close(); return; }
  if (!ev.target.closest('#btnUninstallGo')) return;
  const parts = unChosen();
  if (!parts.length) return;
  if (!unArmed) {  // a second click confirms
    unArmed = true;
    $('#btnUninstallGo span').textContent = t('uninstall.confirm');
    return;
  }
  // removing can take a while (the cache holds thousands of files): show that WTFTD is at work, not frozen
  $('#uninstallFoot').classList.add('hidden');
  $('#uninstallBody').innerHTML = `<div class="un-busy"><span class="spin spin-lg"></span>
    <p><b>${esc(t('uninstall.working'))}</b></p><p class="muted">${esc(t('uninstall.workingHint'))}</p></div>`;
  let res;
  try { res = await api('uninstall', { parts }); } catch (e) { toastErr(e); openUninstall(); return; }
  if (res.quit) {  // the app goes once WTFTD has closed
    $('#uninstallFoot').classList.add('hidden');
    $('#uninstallBody').innerHTML = `<div class="un-bye">${icon('check')}<p><b>${esc(t('uninstall.bye'))}</b></p><p class="muted">${esc(t('uninstall.byeHint'))}</p></div>`;
    setTimeout(() => { try { window.close(); } catch { /* the window stays: the user closes it */ } }, 2500);
    return;
  }
  $('#dlgUninstall').close();
  toast({ title: t('uninstall.done'), sub: parts.map(p => t('uninstall.' + p)).join(' · '), ms: 6000 });
  if (res.removed?.mods?.kept) toast({ title: t('uninstall.modsKept'), err: true, ms: 0 });
  if (parts.includes('data') || parts.includes('user')) { setTimeout(() => location.reload(), 1500); return; }
  try { S.status = await api('status'); renderStatus(); refreshMissions(); } catch { /* keep the page */ }
}


// ------------------------------------------------------------------ automatic data updates
let updatePoll = null;
function renderUpdateBanner(st) {
  const el = $('#updateBanner');
  const stale = st.after !== S.status?.data?.version || st.source !== (S.status?.data?.source || 'datamine');  // the page still shows the old data
  if (st.running) {
    const last = (st.log || []).at(-1) || '';
    el.className = 'update-banner';
    el.innerHTML = `<span class="spin"></span><b>${esc(t('update.running', { v: st.remote || '' }))}</b><span class="muted">${esc(last)}</span>`;
  } else if (st.done && st.after && (stale || chBannerDue(st))) {
    el.className = 'update-banner done';
    el.innerHTML = `${icon('check', 'ic-sm')}<b>${esc(t('update.done', { v: st.after }))}</b>
      ${st.newVehicles ? `<span class="muted">${esc(t('update.newVehicles', { n: st.newVehicles }))}</span>` : ''}
      ${st.changes ? `<button class="btn btn-sm" data-act="changes">${esc(t('update.changes', { n: I18N.num(st.changes) }))}</button>` : ''}
      ${stale ? `<button class="btn btn-primary btn-sm" data-act="reload">${esc(t('update.reload'))}</button>` : `<button class="icon-btn" data-act="hide" title="${esc(t('action.close'))}">${icon('x', 'ic-sm')}</button>`}`;
    const reload = (view = 'vehicles') => { store.set('startView', view); location.reload(); };
    el.querySelectorAll('[data-act]').forEach(b => { b.onclick = { reload: () => reload(), changes: () => (stale ? reload('changes') : showView('changes')), hide: () => { CH.hidden = st.patch; el.className = 'update-banner hidden'; } }[b.dataset.act]; });
    if (stale && !S.sel) setTimeout(reload, 2500);
  } else if (st.error) {
    el.className = 'update-banner err';
    el.innerHTML = `${icon('x', 'ic-sm')}<b>${esc(t('update.error'))}</b><span class="muted">${esc(st.error)}</span>`;
  } else if (st.available) {  // automatic updates off: the game was patched, the player decides when
    el.className = 'update-banner';
    const patched = st.remote && st.remote !== S.status?.data?.version;  // else WTFTD reads more of the same game version now
    el.innerHTML = `<b>${esc(t(patched ? 'update.available' : 'update.rebuild', { v: st.remote || S.status?.data?.version || '' }))}</b>
      <button class="btn btn-primary btn-sm" data-act="update">${esc(t('update.now'))}</button>`;
    el.querySelector('[data-act]').onclick = async () => { try { await api('update', {}); watchUpdates(); } catch (e) { toastErr(e); } };
  } else if (S.status?.dataAhead && S.status.other?.source !== 'game') {  // the datamine runs ahead of the game: the dev server's
    // vehicles and BRs, not the game's. With the game's data kept too, it was picked on purpose and the Data button switches back
    el.className = 'update-banner warn';
    el.innerHTML = `<b>${esc(t('update.ahead', S.status.dataAhead))}</b><button class="btn btn-sm" data-act="settings">${esc(t('update.aheadFix'))}</button>`;
    el.querySelector('[data-act]').onclick = openSettings;
  } else {
    el.className = 'update-banner hidden';
  }
}

async function watchUpdates() {
  clearTimeout(updatePoll);
  try {
    const st = await api('update');
    renderUpdateBanner(st);
    updatePoll = setTimeout(watchUpdates, st.running ? 1500 : 60000);
  } catch { updatePoll = setTimeout(watchUpdates, 60000); }
}

// ------------------------------------------------------------------ settings & data update
async function openSettings(part) {
  const st = S.status;
  let locales = [{ code: 'en', name: 'English' }];
  try { locales = await (await fetch('locales/index.json')).json(); } catch { /* keep default */ }
  $('#setLang').innerHTML = locales.map(l => `<option value="${esc(l.code)}"${l.code === I18N.code ? ' selected' : ''}>${esc(l.name)}</option>`).join('');
  $('#setGameDir').value = st.settings?.gameDir || '';
  const mac = st.platform === 'darwin';
  $('#setGameDir').placeholder = mac ? '~/Library/Application Support/Steam/steamapps/common/War Thunder' : 'D:\\SteamLibrary\\steamapps\\common\\War Thunder';
  $('#setOodle').placeholder = mac ? '…/liboo2coremac64.2.9.dylib' : '…\\oo2core_9_win64.dll';
  $('#setGameDirHint').textContent = st.gameDir ? t('settings.detected', { path: st.gameDir }) : t('settings.gameDirHint');
  $('#setOodle').value = st.settings?.oodleDll || '';
  $('#setOodleFound').textContent = st.oodle ? t('settings.oodleFound', { path: st.oodle }) : t('settings.oodleNone');
  $('#setCdk').checked = st.cdk?.enabled !== false;
  const hosts = st.settings?.hosts || {};
  $('#setHosts').innerHTML = ['ground', 'air', 'heli', 'boat', 'ship'].map(cat => {
    const list = S.vehicles.filter(x => x.c === cat && !x.h).sort((a, b) => (a.r - b.r) || I18N.unit(a.id).localeCompare(I18N.unit(b.id)));
    const cur = hosts[cat] || st.cdk?.defaultHosts?.[cat] || '';
    const options = l => l.map(x => `<option value="${esc(x.id)}"${x.id === cur ? ' selected' : ''}>${esc(I18N.unit(x.id))} (${esc(nationName(x.n))}, ${ROMAN[x.r] || x.r})</option>`).join('');
    const owned = list.filter(hgOwns), group = (key, l) => `<optgroup label="${esc(t(key))}">${options(l)}</optgroup>`;
    return `<label class="host-row"><span>${icon(CAT_ICON[cat], 'ic-sm')}${esc(t('cat.' + cat))}</span>
      <select data-host="${cat}"><option value="">—</option>${owned.length ? group('hg.tab.owned', owned) + group('hg.others', list.filter(x => !hgOwns(x))) : options(list)}</select>
      <small class="host-warn hidden"></small></label>`;
  }).join('');
  hostWarnings();
  $('#cdkFiles').textContent = t('settings.cdkFiles', { n: st.cdk?.present || 0 });
  $('#setAirMethod').value = st.cdk?.airMethod || 'custom';
  $('#setAutoUpdate').checked = st.settings?.autoUpdate !== false;
  $('#setWindow').classList.toggle('hidden', !st.alarms);  // Windows only
  [['#setStartMinimized', 'startMinimized'], ['#setTray', 'trayMinimize'], ['#setCloseWithGame', 'closeWithGame']].forEach(([id, key]) => { $(id).checked = st.settings?.[key] === true; });
  $('#setTheme').value = themePref();
  $('#dataVersion').textContent = st.data?.version ? `${t('settings.version', { version: st.data.version, date: new Date(st.data.built * 1000).toLocaleDateString(I18N.code) })} · ${t('source.from.' + (st.data.source || 'datamine'))}` : '';
  renderSource($('#setSource'), st.dataSource);
  $('#rowDatamine').classList.toggle('hidden', !(st.datamineCopy && st.data?.source === 'game'));
  $('#dlgSettings').showModal();
  if (part === 'source') {  // the header's data button: straight to where the data comes from
    $('#setSource').scrollIntoView({ block: 'center' });
    $('#setSource').classList.add('flash');
    setTimeout(() => $('#setSource').classList.remove('flash'), 1600);
  }
}

// a host must be owned, and the hangar knows: with nothing marked there it has no opinion
function hostWarnings() {
  $$('#setHosts .host-row').forEach(row => {
    const id = row.querySelector('select').value, warn = row.querySelector('.host-warn'), v = S.byId.get(id), off = !HG.owned.size || !v || hgOwns(v);
    warn.classList.toggle('hidden', off);
    warn.textContent = off ? '' : t('hg.hostNotOwned');
  });
}

async function saveSettings() {
  const lang = $('#setLang').value;
  try {
    const hosts = {};
    $$('#setHosts select').forEach(s => { if (s.value) hosts[s.dataset.host] = s.value; });
    const source = $('#setSource').dataset.source;
    S.status = await api('settings', { gameDir: $('#setGameDir').value.trim(), lang, cdk: $('#setCdk').checked, hosts, airMethod: $('#setAirMethod').value, autoUpdate: $('#setAutoUpdate').checked, startMinimized: $('#setStartMinimized').checked, trayMinimize: $('#setTray').checked, closeWithGame: $('#setCloseWithGame').checked, theme: $('#setTheme').value, oodleDll: $('#setOodle').value.trim(), dataSource: source });
    // another source: switched to at once when its data is kept, else rebuilt now (the banner shows it). On the welcome screen,
    // nothing starts before its button
    if (S.status.dataReady && source !== (S.status.data?.source || 'datamine')) {
      if (S.status.other?.source === source) { await api('data-switch', {}); $('#dlgSettings').close(); return reloadOnPage(); }
      await api('update', {}); watchUpdates();
    }
    if (!S.status.dataReady) renderOnboardInfo();
    applyTheme($('#setTheme').value);
    if (S.sel) renderDrawer();
    store.set('lang', lang);
    $('#dlgSettings').close();
    if (lang !== I18N.code) { location.reload(); return; }
    renderStatus();
    refreshMissions();
  } catch (e) { toastErr(e); }
}

async function startUpdate(logEl, btn, barEl = null) {
  try {
    await api('update', {});
    if (!barEl) logEl.classList.remove('hidden');  // onboarding: translated step under the bar, raw log only on error
    if (btn) btn.disabled = true;
    const t0 = Date.now();
    const poll = async () => {
      const st = await api('update');
      logEl.textContent = st.log.join('\n');
      logEl.scrollTop = logEl.scrollHeight;
      if (barEl) {  // progress bar: percent, current step, time left
        const f = Math.max(0, Math.min(1, st.progress || 0)), s = (Date.now() - t0) / 1000;
        barEl.classList.remove('hidden');
        barEl.querySelector('i').style.width = (f * 100).toFixed(1) + '%';
        const left = f > 0.08 && f < 1 ? Math.max(5, Math.round(s / f - s)) : null;
        barEl.querySelector('span').textContent = t(f >= 0.45 ? 'onboard.stepBuild' : S.status.dataSource === 'game' ? 'onboard.stepUnpack' : 'onboard.stepDownload');
        barEl.querySelector('b').textContent = `${Math.round(f * 100)} %` + (left ? ` · ${t('onboard.left', { t: left > 90 ? Math.round(left / 60) + ' min' : left + ' s' })}` : '');
      }
      if (st.running) return setTimeout(poll, 700);
      if (btn) btn.disabled = false;
      if (st.error) { logEl.classList.remove('hidden'); toastErr(new Error(st.error)); }
      else if (st.done) { toast({ title: t('settings.updated') }); setTimeout(() => location.reload(), 800); }
    };
    poll();
  } catch (e) { toastErr(e); }
}

function showOnboarding() {
  $('#onboard').classList.remove('hidden');
  const sel = $('#onboardLang');
  sel.innerHTML = LOCALES.map(l => `<option value="${esc(l.code)}"${l.code === I18N.code ? ' selected' : ''}>${esc(l.name)}</option>`).join('');
  sel.addEventListener('change', async () => {  // switch language in place: the download keeps running
    store.set('lang', sel.value);
    api('settings', { lang: sel.value }).then(st => { S.status = st; }).catch(() => {});
    await I18N.init(sel.value, S.status.data?.langs || ['en']);
    I18N.apply();
    renderStatus();
    renderOnboardInfo();
  });
  renderOnboardInfo();
  // nothing is downloaded before the user agreed: where WTFTD keeps its files, what it writes in the game, what it fetches
  $('#btnOnboard').addEventListener('click', async () => {
    try { S.status = await api('settings', { dataSource: $('#onboardSource').dataset.source }); } catch (e) { toastErr(e); return; }
    $('#onboard .onboard-card').classList.add('busy');
    startUpdate($('#onboardLog'), $('#btnOnboard'), $('#onboardBar'));
  });
  $('#btnSettings').addEventListener('click', openSettings);
  $('#btnSaveSettings').addEventListener('click', saveSettings);
  // a download already under way (the page was reloaded): show its progress again
  api('update').then(up => {
    if (up.running) { $('#onboard .onboard-card').classList.add('busy'); startUpdate($('#onboardLog'), $('#btnOnboard'), $('#onboardBar')); }
  }).catch(() => {});
}
// where the game data comes from: the welcome screen and Settings. The choice stays in el.dataset.source
function renderSource(el, current, onPick) {
  const issue = S.status.gameSourceIssue;
  el.dataset.source = current;
  el.innerHTML = ['game', 'datamine'].map(src => {
    const off = src === 'game' && issue;
    return `<button type="button" class="opt${off ? ' disabled' : ''}${src === current ? ' active' : ''}" data-source="${src}"${off ? ' disabled' : ''}>
      <span class="opt-main"><span class="opt-title">${esc(t('source.' + src))}</span>
      <span class="opt-sub">${esc(t(off ? 'source.issue.' + issue : `source.${src}Hint`))}</span></span>
      <span class="opt-radio"></span></button>`;
  }).join('');
  el.onclick = e => {
    const b = e.target.closest('[data-source]');
    if (!b || b.disabled) return;
    renderSource(el, b.dataset.source, onPick);
    onPick?.();
  };
}
function renderOnboardInfo() {
  const st = S.status;
  const code = s => `<code>${esc(s)}</code>`;
  const pick = $('#onboardSource');
  // the game's own files when they can be read: no download, and the same version as the game
  const src = st.gameSourceIssue ? 'datamine' : (pick.dataset.source || st.settings?.dataSource || 'game');
  renderSource(pick, src, renderOnboardInfo);
  $('#btnOnboardText').textContent = t(src === 'game' ? 'onboard.buttonGame' : 'onboard.button');
  // every place WTFTD downloads from (builder.REPO, server.IMAGE_SOURCES / image_urls / REMOTE_VERSION_URL, app_version)
  $('#onboardInfo').innerHTML = `<b>${esc(t('onboard.where'))}</b><ul>
    <li>${t('onboard.whereApp', { path: code(st.home || '') })}</li>
    <li>${t('onboard.whereGame', { path: code(st.gameDir || t('onboard.gameNotFound')) })}</li>
    <li>${esc(t('onboard.whereRemove'))}</li></ul>
    <b>${esc(t('onboard.sources'))}</b><ul>
    ${src === 'game' ? `<li>${esc(t('onboard.srcDataGame'))}</li>` : `<li>${t('onboard.srcData', { url: code('github.com/gszabi99/War-Thunder-Datamine') })}</li>
    ${st.platform === 'win32' ? `<li>${t('onboard.srcGit', { url: code('github.com/git-for-windows/git') })}</li>` : ''}`}
    <li>${t('onboard.srcImages', { a: code('static.encyclopedia.warthunder.com'), b: code('wiki.warthunder.com') })}</li>
    <li>${t('onboard.srcApp', { url: code('github.com/StonewarP/WTFTD-War_Thunder_Full_Test_Drive') })}</li>
    <li>${esc(t('onboard.srcNone'))}</li></ul>`;
}

// after every script of the page has run: boot() calls functions of the scripts loaded after this one
document.addEventListener('DOMContentLoaded', () => boot().catch(e => { console.error(e); toastErr(e); }));
// app window: tells the local server the page is gone (macOS keeps the browser running, WTFTD quits with the window)
addEventListener('pagehide', () => navigator.sendBeacon('/api/bye'));
setInterval(() => fetch('/api/ping').catch(() => {}), 15000);  // alive: WTFTD keeps serving while this page is open
