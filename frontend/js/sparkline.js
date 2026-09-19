// sparkline.js — 轻量 SVG 火花线（KPI / 卡片指标）
// 纯 transform/透明度动画友好，无外部依赖。

const HISTORY = new Map(); // key -> number[]

export function pushSeries(key, value, max = 40) {
  const arr = HISTORY.get(key) || [];
  arr.push(value);
  if (arr.length > max) arr.shift();
  HISTORY.set(key, arr);
  return arr;
}

/**
 * 渲染火花线到指定 <svg> 元素。
 * @param {SVGElement} svg 目标 svg（需有 viewBox）
 * @param {number[]} data 数据点
 * @param {object} opts { color, fill }
 */
export function renderSparkline(svg, data, opts = {}) {
  if (!svg) return;
  const color = opts.color || getComputedStyle(svg).color || "#38bdf8";
  const w = svg.viewBox.baseVal.width || 120;
  const h = svg.viewBox.baseVal.height || 32;
  const n = data.length;
  if (n < 2) { svg.innerHTML = ""; return; }

  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  const stepX = w / (n - 1);
  const pad = 3;
  const pts = data.map((v, i) => {
    const x = i * stepX;
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return [x, y];
  });

  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${w} ${h} L0 ${h} Z`;

  svg.innerHTML = `
    <path d="${area}" fill="${color}" opacity="0.14" />
    <path d="${line}" fill="none" stroke="${color}" stroke-width="1.8"
      stroke-linejoin="round" stroke-linecap="round"
      vector-effect="non-scaling-stroke" />
    <circle cx="${pts[n - 1][0].toFixed(1)}" cy="${pts[n - 1][1].toFixed(1)}"
      r="2.4" fill="${color}" />
  `;
}

/** 便捷：压入并渲染 */
export function updateSparkline(svg, key, value, opts) {
  const data = pushSeries(key, value);
  renderSparkline(svg, data, opts);
}
