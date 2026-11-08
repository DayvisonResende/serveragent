// Ícones de traço (24×24), desenhados aqui: o dashboard não carrega nada de fora (CSP).
// Decorativos: sempre acompanham um texto visível, por isso aria-hidden.

const PATHS = {
  overview: ["M4 4h7v7H4z", "M13 4h7v4h-7z", "M13 10h7v10h-7z", "M4 13h7v7H4z"],
  servers: ["M4 5h16v5H4z", "M4 14h16v5H4z", "M8 7.5h.01", "M8 16.5h.01", "M12 7.5h5", "M12 16.5h5"],
  system: ["M7 7h10v10H7z", "M10 10h4v4h-4z", "M9 3v4", "M15 3v4", "M9 17v4", "M15 17v4", "M3 9h4", "M3 15h4", "M17 9h4", "M17 15h4"],
  processes: ["M4 6h16", "M4 12h16", "M4 18h10", "M18 16l2 2-2 2"],
  storage: ["M4 7c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3z", "M4 7v10c0 1.7 3.6 3 8 3s8-1.3 8-3V7", "M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"],
  assistant: ["M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z", "M18.5 15l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"],
  approvals: ["M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z", "M9 12l2 2 4-4"],
  security: ["M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6z", "M12 8v4", "M12 15.5h.01"],
  history: ["M12 7v5l3 2", "M3.5 12a8.5 8.5 0 1 0 2.5-6", "M3 4v4h4"],
  settings: ["M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6z", "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"],
  search: ["M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14z", "M20 20l-4-4"],
  logout: ["M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3", "M10 16l-4-4 4-4", "M6 12h10"],
  menu: ["M4 7h16", "M4 12h16", "M4 17h16"],
  arrow: ["M5 12h14", "M13 6l6 6-6 6"],
  check: ["M5 12.5l4.5 4.5L19 7.5"],
  alert: ["M12 8v5", "M12 16.5h.01", "M10.3 4.3L2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.3a2 2 0 0 0-3.4 0z"],
  bolt: ["M13 3L5 13.5h6L10 21l8-10.5h-6z"],
};

const NS = "http://www.w3.org/2000/svg";

export function icon(name, size = 18) {
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": 1.7, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: "icon" })) {
    svg.setAttribute(k, String(v));
  }
  for (const d of PATHS[name] || []) {
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", d);
    svg.append(p);
  }
  return svg;
}

// Marca do Sentinel: escudo com um "olho" de radar — vigia e protege.
export function logo(size = 28) {
  const svg = document.createElementNS(NS, "svg");
  for (const [k, v] of Object.entries({ viewBox: "0 0 32 32", width: size, height: size, "aria-hidden": "true", class: "logo" })) {
    svg.setAttribute(k, String(v));
  }
  const parts = [
    ["path", { d: "M16 2.5l11 4.2v8.1c0 7-4.6 12.6-11 14.7C9.6 27.4 5 21.8 5 14.8V6.7z", class: "logo-shield" }],
    ["path", { d: "M9.5 15.5c1.8-3 4-4.5 6.5-4.5s4.7 1.5 6.5 4.5c-1.8 3-4 4.5-6.5 4.5s-4.7-1.5-6.5-4.5z", class: "logo-eye" }],
    ["circle", { cx: 16, cy: 15.5, r: 2.3, class: "logo-pupil" }],
  ];
  for (const [tag, attrs] of parts) {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
    svg.append(el);
  }
  return svg;
}
