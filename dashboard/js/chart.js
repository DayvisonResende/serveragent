// Gráfico de linhas em SVG: um único eixo Y, linhas de 2px, grade discreta,
// rótulo de valor no fim de cada linha, linha-guia com tooltip e lacunas reais
// quando faltam dados (nunca interpolamos valores que não foram medidos).

import { DASH } from "./format.js";

const NS = "http://www.w3.org/2000/svg";
const M = { top: 10, right: 78, bottom: 24, left: 52 };

function el(name, attrs = {}, parent = null) {
  const node = document.createElementNS(NS, name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  if (parent) parent.appendChild(node);
  return node;
}

function niceMax(value) {
  if (!(value > 0)) return 1;
  const exp = 10 ** Math.floor(Math.log10(value));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * exp >= value) return m * exp;
  return 10 * exp;
}

export class LineChart {
  /**
   * @param {HTMLElement} container
   * @param {{series: {key: string, label: string, slot: 1|2}[], height?: number, yMax?: number,
   *          formatValue: (v:number)=>string, formatTick?: (v:number)=>string,
   *          formatTime: (t:number)=>string, minYMax?: number}} options
   */
  constructor(container, options) {
    this.container = container;
    this.o = { height: 220, formatTick: options.formatValue, minYMax: 1, ...options };
    this.points = [];
    this.domain = null;
    this.tooltip = document.getElementById("tooltip");
    container.classList.add("chart");
    this.svg = el("svg", { role: "img", "aria-label": options.ariaLabel || "Gráfico" }, container);
    this.observer = new ResizeObserver(() => this.render());
    this.observer.observe(container);
  }

  /** @param {object[]} points ordenados por t (segundos); @param {[number, number]=} domain */
  setData(points, domain) {
    this.points = points;
    this.domain = domain || null;
    this.render();
  }

  destroy() {
    this.observer.disconnect();
    this.hideTooltip();
  }

  render() {
    const width = this.container.clientWidth;
    if (!width) return;
    const { height, series, yMax, formatTick, formatTime, minYMax } = this.o;
    const svg = this.svg;
    svg.replaceChildren();
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.setAttribute("height", height);
    const pw = Math.max(width - M.left - M.right, 10);
    const ph = height - M.top - M.bottom;

    const pts = this.points;
    if (!pts.length) {
      el("text", { x: M.left + pw / 2, y: M.top + ph / 2, "text-anchor": "middle", class: "empty" }, svg).textContent = "Aguardando dados…";
      return;
    }

    const [t0, t1] = this.domain || [pts[0].t, pts[pts.length - 1].t];
    const span = Math.max(t1 - t0, 1);
    let top = yMax;
    if (top === undefined) {
      let max = 0;
      for (const p of pts) for (const s of series) if (p[s.key] != null && p[s.key] > max) max = p[s.key];
      top = niceMax(Math.max(max, minYMax));
    }
    const x = (t) => M.left + ((t - t0) / span) * pw;
    const y = (v) => M.top + ph - (v / top) * ph;

    // grade e eixo Y
    for (let i = 0; i <= 4; i++) {
      const v = (top / 4) * i;
      const yy = Math.round(y(v)) + 0.5;
      el("line", { x1: M.left, x2: M.left + pw, y1: yy, y2: yy, class: i === 0 ? "baseline" : "grid-line" }, svg);
      el("text", { x: M.left - 8, y: yy + 4, "text-anchor": "end", class: "tick" }, svg).textContent = formatTick(v);
    }
    // eixo X
    const ticks = Math.max(2, Math.min(6, Math.floor(pw / 110)));
    for (let i = 0; i <= ticks; i++) {
      const t = t0 + (span / ticks) * i;
      el("text", { x: x(t), y: height - 6, "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle", class: "tick" }, svg)
        .textContent = formatTime(t);
    }

    // séries, com lacunas quando o intervalo entre pontos excede 3x o típico
    const gap = this.typicalStep() * 3;
    const ends = [];
    for (const s of series) {
      let d = "";
      let prev = null;
      let last = null;
      for (const p of pts) {
        const v = p[s.key];
        if (v == null) { prev = null; continue; }
        const cmd = prev && p.t - prev.t <= gap ? "L" : "M";
        d += `${cmd}${x(p.t).toFixed(1)},${y(v).toFixed(1)}`;
        prev = p;
        last = p;
      }
      if (d) el("path", { d, class: `series stroke-${s.slot}` }, svg);
      if (last) ends.push({ s, y: y(last[s.key]), v: last[s.key] });
    }
    // rótulos no fim das linhas; se colidirem, legenda e tooltip assumem
    const collide = ends.length > 1 && ends.some((a, i) => ends.some((b, j) => i < j && Math.abs(a.y - b.y) < 14));
    if (!collide) {
      for (const e of ends) {
        el("text", { x: M.left + pw + 8, y: e.y + 4, class: "end-label" }, svg).textContent = this.o.formatValue(e.v);
      }
    }

    // camada de interação: linha-guia que segue o ponteiro
    this.hover = el("g", {}, svg);
    const hit = el("rect", { x: M.left, y: M.top, width: pw, height: ph, fill: "transparent" }, svg);
    hit.addEventListener("pointermove", (ev) => this.onHover(ev, x, y));
    hit.addEventListener("pointerleave", () => this.hideTooltip());
  }

  typicalStep() {
    const p = this.points;
    if (p.length < 2) return Infinity;
    const steps = [];
    for (let i = 1; i < p.length; i++) steps.push(p[i].t - p[i - 1].t);
    steps.sort((a, b) => a - b);
    return steps[Math.floor(steps.length / 2)];
  }

  onHover(ev, x, y) {
    const rect = this.svg.getBoundingClientRect();
    const scale = rect.width / this.container.clientWidth || 1;
    const px = (ev.clientX - rect.left) / scale;
    // ponto mais próximo no eixo X (busca binária)
    const pts = this.points;
    let lo = 0;
    let hi = pts.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (x(pts[mid].t) < px) lo = mid; else hi = mid;
    }
    const p = Math.abs(x(pts[lo].t) - px) <= Math.abs(x(pts[hi].t) - px) ? pts[lo] : pts[hi];
    const g = this.hover;
    g.replaceChildren();
    const xx = Math.round(x(p.t)) + 0.5;
    el("line", { x1: xx, x2: xx, y1: M.top, y2: this.o.height - M.bottom, class: "crosshair" }, g);
    for (const s of this.o.series) {
      if (p[s.key] != null) el("circle", { cx: x(p.t), cy: y(p[s.key]), r: 4, class: `dot fill-${s.slot}` }, g);
    }
    this.showTooltip(ev, p);
  }

  showTooltip(ev, p) {
    const tip = this.tooltip;
    tip.replaceChildren();
    const head = document.createElement("div");
    head.className = "t-time";
    head.textContent = this.o.formatTime(p.t, true);
    tip.appendChild(head);
    for (const s of this.o.series) {
      const row = document.createElement("div");
      row.className = "t-row";
      const key = document.createElement("span");
      key.className = `key key-${s.slot}`;
      const label = document.createElement("span");
      label.textContent = s.label;
      const value = document.createElement("strong");
      value.textContent = p[s.key] == null ? DASH : this.o.formatValue(p[s.key]);
      row.append(key, label, value);
      tip.appendChild(row);
    }
    tip.hidden = false;
    const w = tip.offsetWidth;
    const left = ev.clientX + 14 + w > window.innerWidth ? ev.clientX - w - 14 : ev.clientX + 14;
    tip.style.setProperty("left", `${left}px`);
    tip.style.setProperty("top", `${ev.clientY + 14}px`);
  }

  hideTooltip() {
    if (this.tooltip) this.tooltip.hidden = true;
    if (this.hover) this.hover.replaceChildren();
  }
}

/** Legenda (sempre presente com 2+ séries): chave de linha + rótulo em cor de texto. */
export function legend(series) {
  const box = document.createElement("div");
  box.className = "legend";
  for (const s of series) {
    const item = document.createElement("span");
    const key = document.createElement("span");
    key.className = `key key-${s.slot}`;
    item.append(key, document.createTextNode(s.label));
    box.appendChild(item);
  }
  return box;
}

/** Visão em tabela dos dados do gráfico (acessibilidade). Mostra os pontos mais recentes. */
export function dataTable(points, series, formatValue, formatTime, max = 30) {
  const details = document.createElement("details");
  details.className = "data-table";
  const summary = document.createElement("summary");
  summary.textContent = "Ver dados em tabela";
  details.appendChild(summary);
  details.addEventListener("toggle", () => {
    if (!details.open || details.querySelector("table")) return;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const label of ["Horário", ...series.map((s) => s.label)]) {
      const th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    }
    const body = table.createTBody();
    for (const p of points.slice(-max).reverse()) {
      const row = body.insertRow();
      row.insertCell().textContent = formatTime(p.t, true);
      for (const s of series) {
        const cell = row.insertCell();
        cell.className = "num";
        cell.textContent = p[s.key] == null ? DASH : formatValue(p[s.key]);
      }
    }
    wrap.appendChild(table);
    details.appendChild(wrap);
  });
  return details;
}
