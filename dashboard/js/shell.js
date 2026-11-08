// Moldura do dashboard: barra lateral com seções, menu móvel e paleta de comandos (Ctrl+K).

import { sendJSON } from "./api.js";
import { h } from "./ui.js";
import { icon, logo } from "./icons.js";

export const NAV = [
  { group: "Monitorar", items: [
    { route: "/", label: "Visão geral", icon: "overview" },
    { route: "/sistema", label: "Sistema", icon: "system" },
    { route: "/processos", label: "Processos", icon: "processes" },
    { route: "/armazenamento", label: "Armazenamento", icon: "storage" },
  ] },
  { group: "Operar", items: [
    { route: "/servidores", label: "Servidores", icon: "servers" },
    { route: "/aprovacoes", label: "Aprovações", icon: "approvals", badge: "approvals-badge" },
    { route: "/seguranca", label: "Segurança", icon: "security" },
  ] },
  { group: "Inteligência", items: [
    { route: "/assistente", label: "Assistente", icon: "assistant" },
  ] },
  { group: "Registro", items: [
    { route: "/historico", label: "Histórico", icon: "history" },
    { route: "/configuracoes", label: "Configurações", icon: "settings" },
  ] },
];

const isMac = /Mac|iPhone|iPad/.test(navigator.platform);

export function buildShell() {
  document.getElementById("brand").replaceChildren(
    logo(30), h("div", {}, h("div", { class: "brand-name", text: "Sentinel" }), h("div", { class: "brand-tag", text: "vigia deste computador" })));
  document.getElementById("palette-open").prepend(icon("search", 16));
  document.getElementById("palette-hint").textContent = isMac ? "⌘K" : "Ctrl K";
  document.getElementById("logout").prepend(icon("logout", 16));
  document.getElementById("menu-toggle").append(icon("menu", 22));
  document.getElementById("mobile-brand").prepend(logo(22));

  const nav = document.getElementById("nav");
  nav.replaceChildren(...NAV.map((section) => h("div", { class: "nav-group" },
    h("div", { class: "nav-heading", text: section.group }),
    ...section.items.map((item) => h("a", { href: `#${item.route}`, "data-route": item.route },
      icon(item.icon), h("span", { class: "nav-label", text: item.label }),
      item.badge ? h("span", { id: item.badge, class: "badge", hidden: true, text: "0" }) : null)))));

  // Menu móvel: a barra lateral vira gaveta.
  const sidebar = document.getElementById("sidebar");
  const scrim = document.getElementById("scrim");
  const toggle = document.getElementById("menu-toggle");
  const setOpen = (open) => {
    sidebar.classList.toggle("open", open);
    scrim.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  };
  toggle.addEventListener("click", () => setOpen(!sidebar.classList.contains("open")));
  scrim.addEventListener("click", () => setOpen(false));
  nav.addEventListener("click", (e) => { if (e.target.closest("a")) setOpen(false); });
}

// ---------------------------------------------------------------- paleta de comandos

const plain = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

function commands() {
  const pages = NAV.flatMap((s) => s.items.map((i) => ({
    title: i.label, hint: s.group, icon: i.icon, run: () => { location.hash = `#${i.route}`; },
  })));
  const actions = [
    { title: "Analisar o armazenamento agora", hint: "Ação", icon: "storage",
      run: async () => { await sendJSON("POST", "/api/v1/storage/analyze", {}).catch(() => null); location.hash = "#/armazenamento"; } },
    { title: "Nova conversa com o assistente", hint: "Ação", icon: "assistant",
      run: () => {
        try { localStorage.removeItem("sentinel.conversation"); } catch { /* sem armazenamento */ }
        if (location.hash === "#/assistente") window.dispatchEvent(new HashChangeEvent("hashchange"));  // recarrega a página
        else location.hash = "#/assistente";
      } },
    { title: "Cadastrar servidor", hint: "Ação", icon: "servers", run: () => { location.hash = "#/servidores/novo"; } },
    { title: "Ver aprovações pendentes", hint: "Ação", icon: "approvals", run: () => { location.hash = "#/aprovacoes"; } },
    { title: "Sair do dashboard", hint: "Sessão", icon: "logout", run: () => document.getElementById("logout").click() },
  ];
  return [...pages, ...actions];
}

export function setupPalette() {
  const dialog = document.getElementById("palette");
  const input = h("input", { type: "search", class: "palette-input", placeholder: "Ir para uma página ou executar uma ação…",
    "aria-label": "Buscar", autocomplete: "off", spellcheck: "false" });
  const list = h("ul", { class: "palette-list", role: "listbox", "aria-label": "Resultados" });
  dialog.replaceChildren(
    h("div", { class: "palette-search" }, icon("search", 18), input, h("kbd", { text: "Esc" })),
    list,
    h("div", { class: "palette-foot" }, h("span", {}, h("kbd", { text: "↑" }), h("kbd", { text: "↓" }), " navegar"),
      h("span", {}, h("kbd", { text: "Enter" }), " abrir")));

  let items = [];
  let active = 0;
  const all = commands();
  const paint = () => {
    const q = plain(input.value.trim());
    items = all.filter((c) => !q || plain(`${c.title} ${c.hint}`).includes(q));
    active = Math.min(active, Math.max(items.length - 1, 0));
    list.replaceChildren(...(items.length ? items.map((c, i) => h("li", {
      role: "option", "aria-selected": String(i === active), class: i === active ? "active" : null,
      onmousemove: () => { if (active !== i) { active = i; paint(); } },
      onclick: () => choose(i),
    }, h("span", { class: "palette-icon" }, icon(c.icon, 16)), h("span", { class: "palette-title", text: c.title }),
      h("span", { class: "palette-hint", text: c.hint }))) : [h("li", { class: "palette-empty", text: "Nada encontrado." })]));
    list.querySelector(".active")?.scrollIntoView({ block: "nearest" });
  };
  const close = () => { if (dialog.open) dialog.close(); };
  const open = () => { input.value = ""; active = 0; paint(); dialog.showModal(); input.focus(); };
  const choose = (i) => { const c = items[i]; if (!c) return; close(); c.run(); };

  input.addEventListener("input", () => { active = 0; paint(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); active = (active + 1) % Math.max(items.length, 1); paint(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); active = (active - 1 + items.length) % Math.max(items.length, 1); paint(); }
    else if (e.key === "Enter") { e.preventDefault(); choose(active); }
  });
  dialog.addEventListener("click", (e) => { if (e.target === dialog) close(); });  // clique fora fecha
  document.getElementById("palette-open").addEventListener("click", open);
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); dialog.open ? close() : open(); }
  });
}
