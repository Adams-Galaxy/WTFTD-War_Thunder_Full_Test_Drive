/* WTFTD — draws the fighter HUD's shapes (wtftd/hud.py) into an SVG: My overlay's preview and the cockpit window. */
'use strict';

const HUD_ANCHOR = { w: 'start', m: 'middle', e: 'end' };

// shapes: ["l", x1, y1, x2, y2, width, alert], ["t", x, y, text, size, anchor, alert], ["p", points, filled, alert], ["c", x, y, r, alert]
function hudDraw(svg, shapes, color, alert, lit = true) {
  const el = (name, attrs) => {
    const e = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    return e;
  };
  svg.replaceChildren(...shapes.map(s => {
    const tint = s[s.length - 1] && lit ? alert : color;
    if (s[0] === 'l') return el('line', { x1: s[1], y1: s[2], x2: s[3], y2: s[4], stroke: tint, 'stroke-width': s[5] });
    if (s[0] === 'p') return el('polygon', { points: s[1].join(' '), stroke: tint, 'stroke-width': 1.6, fill: s[2] ? tint : 'none' });
    if (s[0] === 'c') return el('circle', { cx: s[1], cy: s[2], r: s[3], stroke: tint, 'stroke-width': 1.8, fill: 'none' });
    const text = el('text', { x: s[1], y: s[2], fill: tint, 'font-size': s[4], 'text-anchor': HUD_ANCHOR[s[5]], 'dominant-baseline': 'central' });
    text.textContent = s[3];
    return text;
  }));
}
