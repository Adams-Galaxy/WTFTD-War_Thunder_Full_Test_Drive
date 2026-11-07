// Translation layer.
// UI strings: web/locales/<code>.json (en.json is the reference + fallback).
// Game names (vehicles, weapons, ammo, maps): data/lang/<code>.json, generated from the game's own files.
// To add a language: copy locales/en.json to locales/<code>.json, translate the values,
// and add { "code": "<code>", "name": "<Native name>" } to locales/index.json.

const I18N = (() => {
  let ui = {}, uiFallback = {}, game = {}, gameFallback = {};
  let code = 'en';

  async function getJSON(url) {
    try {
      const r = await fetch(url, { cache: 'no-cache' });
      return r.ok ? await r.json() : null;
    } catch { return null; }
  }

  async function init(lang, gameLangs = ['en']) {
    code = lang || 'en';
    uiFallback = (await getJSON('locales/en.json')) || {};
    ui = code === 'en' ? uiFallback : ((await getJSON(`locales/${code}.json`)) || {});
    gameFallback = (await getJSON('data/lang/en.json')) || {};
    game = code !== 'en' && gameLangs.includes(code) ? ((await getJSON(`data/lang/${code}.json`)) || {}) : gameFallback;
    document.documentElement.lang = code;
  }

  function t(key, vars) {
    let s = ui[key] ?? uiFallback[key];
    if (s == null) return key;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] ?? m));
    return s;
  }

  // t() with a fallback when the key is missing (for open-ended game values)
  function tOr(key, fallback, vars) {
    const s = t(key, vars);
    return s === key ? fallback : s;
  }

  function g(section, key, fallback) {
    return (game[section] && game[section][key]) || (gameFallback[section] && gameFallback[section][key]) || fallback || key;
  }

  function apply(root = document) {
    root.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    root.querySelectorAll('[data-i18n-ph]').forEach(el => { el.placeholder = t(el.dataset.i18nPh); });
    root.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); el.setAttribute('aria-label', el.title); });
  }

  const num = n => new Intl.NumberFormat(code).format(n);

  return {
    init, t, tOr, apply, num,
    get code() { return code; },
    unit: id => g('units', id, id),
    unitFull: id => g('unitsFull', id, g('units', id, id)),
    weapon: k => g('weapons', k, k),
    sensor: k => g('sensors', k, k),
    diff: k => g('difficulty', k, k),
    bullet: k => g('bullets', k, k),
    btype: k => g('btypes', k, k.toUpperCase()),
    mod: k => g('mods', k, ''),
    map: k => g('maps', k, k),
    role: k => g('roles', k, k.replace(/_/g, ' ')),
    arm: k => g('arm', k, g('weapons', k, k)),
  };
})();
