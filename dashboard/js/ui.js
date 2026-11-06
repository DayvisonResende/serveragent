// Componentes de interface compartilhados. Todo texto entra via textContent
// (dados do servidor — nomes de processos, logs — não são confiáveis).

import * as fmt from "./format.js";

export function h(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) if (c != null) node.append(c instanceof Node ? c : String(c));
  return node;
}

export function card(title, ...body) {
  return h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: title })), ...body);
}

export function meter(value) {
  const fill = h("span");
  fill.style.setProperty("width", `${Math.max(0, Math.min(100, value || 0))}%`);
  return h("div", { class: "meter", role: "meter", "aria-valuemin": 0, "aria-valuemax": 100, "aria-valuenow": value ?? 0 }, fill);
}

export function setMeter(node, value) {
  node.setAttribute("aria-valuenow", value ?? 0);
  node.firstChild.style.setProperty("width", `${Math.max(0, Math.min(100, value || 0))}%`);
}

export function severityBadge(sev) {
  const s = fmt.SEVERITY[sev] || fmt.SEVERITY.info;
  return h("span", { class: `sev sev-${sev}` }, h("span", { class: "sev-icon", "aria-hidden": "true", text: s.icon }), s.label);
}

