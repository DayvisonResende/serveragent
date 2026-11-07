// Dashboard do Sentinel. Todo texto vindo do servidor é inserido com textContent
// (nomes de processos e caminhos são dados não confiáveis).

import { getJSON, logout, LiveChannel, UnauthorizedError } from "./api.js";
import { LineChart, legend, dataTable } from "./chart.js";
import * as fmt from "./format.js";
import { h, card, meter, setMeter, severityBadge } from "./ui.js";
import { serversPage, serverFormPage, serverDetailPage, statePill, summarize } from "./servers.js";
import { settingsPage } from "./settings.js";
import { approvalsPage, securityPage, actionsTable, auditTable } from "./security.js";

const view = document.getElementById("view");
const banner = document.getElementById("banner");
const livePill = document.getElementById("live-status");

const LIVE_WINDOW = 15 * 60; // segundos exibidos nos gráficos em tempo real
const CPU_RAM = [
  { key: "cpu", label: "CPU", slot: 1 },
  { key: "ram", label: "Memória", slot: 2 },
];
const NET = [
  { key: "down", label: "Download", slot: 1 },
  { key: "up", label: "Upload", slot: 2 },
];

const state = { live: [], latest: null, alerts: [], resources: null, servers: null };
let page = null;
let channel = null;

// ---------------------------------------------------------------- utilidades

function chartTime(longRange) {
  return (t, detailed) => {
    if (longRange) return fmt.dateTime(new Date(t * 1000).toISOString());
    return detailed ? fmt.timeWithSeconds(t) : fmt.time(t);
  };
}

function showError(err) {
  view.replaceChildren(card("Não foi possível carregar", h("p", { class: "secondary", text: String(err.message || err) })));
}

function showUnauthorized() {
  channel?.stop();
  document.body.replaceChildren(
    h("main", { class: "standalone" },
      h("div", { class: "notice" },
        h("h1", { text: "Sessão não iniciada" }),
        h("p", { text: "Por segurança, o dashboard só abre com um link de acesso de uso único." }),
        h("p", {}, "Execute ", h("strong", { text: "abrir-dashboard.bat" }), " na pasta do Sentinel."))));
}

function onLiveState(s) {
  const labels = {
    open: ["Tempo real", "pill-good"],
    connecting: ["Conectando…", "pill-muted"],
    closed: ["Reconectando…", "pill-warning"],
  };
  if (s === "unauthorized") { checkSession(); return; }
  const [text, cls] = labels[s] || labels.connecting;
  livePill.textContent = text;
  livePill.className = `pill ${cls}`;
  banner.hidden = s !== "closed";
  if (s === "closed") banner.textContent = "Conexão em tempo real perdida. Tentando reconectar — o agente continua monitorando normalmente.";
}

async function checkSession() {
  try { await getJSON("/api/v1/auth/session"); return true; }
  catch (err) { if (err instanceof UnauthorizedError) showUnauthorized(); return false; }
}

async function refreshApprovalBadge() {
  const badge = document.getElementById("approvals-badge");
  try {
    const n = (await getJSON("/api/v1/approvals?status=pending&limit=1")).pending;
    badge.textContent = String(n);
    badge.hidden = n === 0;
    state.pendingApprovals = n;
    page?.onApprovals?.();
  } catch (err) {
    if (err instanceof UnauthorizedError) showUnauthorized();
  }
}

function onLiveMessage(msg) {
  if (msg.type === "metrics") {
    const d = msg.data;
    state.latest = d;
    state.alerts = msg.alerts || [];
    state.resources = msg.resources || null;
    state.live.push({ t: d.ts_epoch, cpu: d.cpu.percent, ram: d.memory.percent, up: d.network.upload_bps, down: d.network.download_bps });
    const cutoff = d.ts_epoch - LIVE_WINDOW;
    while (state.live.length && state.live[0].t < cutoff) state.live.shift();
    page?.onMetrics?.(d);
    if (msg.servers) { state.servers = msg.servers; page?.onServers?.(msg.servers); }
  } else if (msg.type === "event") {
    if (msg.data.event_type.startsWith("approval.")) refreshApprovalBadge();
    page?.onEvent?.(msg.data);
  }
}

// ---------------------------------------------------------------- componentes

function alertsBox() {
  const box = h("div", { class: "alerts", "aria-live": "polite" });
  const render = (alerts, resources) => {
    box.replaceChildren();
    for (const a of alerts) {
      box.append(h("div", { class: `alert alert-${a.severity}` }, severityBadge(a.severity), h("span", { text: a.title }),
        a.since ? h("span", { class: "muted", text: `desde ${fmt.dateTime(a.since)}` }) : null));
    }
    if (state.pendingApprovals) {
      box.append(h("div", { class: "alert alert-warning" }, severityBadge("warning"),
        h("span", { text: `${state.pendingApprovals} aprovação(ões) aguardando sua decisão.` }),
        h("a", { href: "#/aprovacoes", class: "btn btn-small", text: "Ver aprovações" })));
    }
    if (resources && resources.level !== "normal") {
      const severe = resources.level === "severe";
      box.append(h("div", { class: `alert alert-${severe ? "high" : "warning"}` }, severityBadge(severe ? "high" : "warning"),
        h("span", { text: `Computador ${severe ? "sob pressão severa" : "sob pressão"}: o Sentinel reduziu suas tarefas não essenciais (${resources.load_factor}x mais lentas).` })));
    }
  };
  return { node: box, render };
}

const LOAD_EVENTS = new Set(["resources.pressure_changed", "system.cpu_high", "system.memory_high"]);

function eventItem(e) {
  const extra = h("div");
  const button = LOAD_EVENTS.has(e.event_type)
    ? h("button", { type: "button", class: "btn btn-small", text: "Processos neste horário", onclick: async (ev) => {
        ev.currentTarget.remove();
        extra.replaceChildren(h("p", { class: "muted small", text: "Carregando…" }));
        try { extra.replaceChildren(processesAt(await getJSON(`/api/v1/system/processes/at?ts=${new Date(e.timestamp).getTime() / 1000}`))); }
        catch (err) { extra.replaceChildren(h("p", { class: "secondary small", text: err.message })); }
      } })
    : null;
  return h("li", {},
    h("time", { datetime: e.timestamp, text: fmt.dateTime(e.timestamp) }),
    h("div", {},
      h("div", {}, severityBadge(e.severity), " ", h("span", { class: "title", text: e.title })),
      e.description ? h("div", { class: "desc", text: e.description }) : null,
      button, extra));
}

// "O que estava rodando naquele momento": instantâneo mais próximo dos processos mais pesados.
function processesAt(data) {
  if (!data.snapshot_epoch) {
    return h("p", { class: "muted small", text: "Não há instantâneo de processos perto desse horário (são gravados a cada 5 minutos)." });
  }
  const sys = data.system;
  return h("div", { class: "snapshot" },
    h("p", { class: "muted small", text: `Instantâneo de ${fmt.dateTime(data.snapshot_at)}${sys ? ` · CPU média ${fmt.percent(sys.cpu_percent)} (pico ${fmt.percent(sys.cpu_percent_max)}), memória ${fmt.percent(sys.ram_percent)}` : ""}` }),
    h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ...["Processo", "PID", "CPU", "Memória", "Caminho"].map((x, i) => h("th", { class: i >= 1 && i <= 3 ? "num" : null, text: x })))),
      h("tbody", {}, ...data.processes.map((p) => h("tr", {},
        h("td", { text: p.process_name }), h("td", { class: "num", text: p.pid }),
        h("td", { class: "num", text: p.cpu_percent == null ? fmt.DASH : fmt.percent(p.cpu_percent) }),
        h("td", { class: "num", text: fmt.bytes(p.memory_bytes) }),
        h("td", { class: "path", title: p.executable_path || "", text: p.executable_path || "sem acesso" })))))));
}

function chartCard(title, series, opts) {
  const holder = h("div");
  const summary = h("div", { class: "summary" });
  const tableSlot = h("div");
  const chart = new LineChart(holder, { series, ariaLabel: title, ...opts });
  const node = h("section", { class: "card" },
    h("div", { class: "card-head" }, h("h2", { text: title }), legend(series)), holder, summary, tableSlot);
  const setTable = (points) => tableSlot.replaceChildren(dataTable(points, series, opts.formatValue, opts.formatTime));
  return { node, chart, summary, setTable };
}

function percentChart(title, longRange = false) {
  return chartCard(title, CPU_RAM, {
    yMax: 100, formatValue: fmt.percent, formatTick: (v) => `${Math.round(v)}%`, formatTime: chartTime(longRange),
  });
}

function networkChart(title, longRange = false) {
  return chartCard(title, NET, {
    minYMax: 125_000, // 1 Mbit/s: evita um eixo exagerado com tráfego quase nulo
    formatValue: fmt.bitrate, formatTick: fmt.compactBitrate, formatTime: chartTime(longRange),
  });
}

function summaryLine(node, items) {
  node.replaceChildren(...items.map(([label, value]) => h("span", {}, `${label}: `, h("strong", { text: value }))));
}

// ---------------------------------------------------------------- páginas

async function overviewPage() {
  const [status, metrics, events, servers] = await Promise.all([
    getJSON("/api/v1/system/status"),
    getJSON("/api/v1/system/metrics?range=15m"),
    getJSON("/api/v1/events?limit=12"),
    getJSON("/api/v1/servers").catch(() => null),
  ]);
  if (!state.live.length) state.live = metrics.points;
  state.alerts = status.alerts;
  state.resources = status.resources;

  const alerts = alertsBox();
  const t = {
    cpu: tile("CPU"), mem: tile("Memória"), disk: tile("Disco"), net: tile("Rede"), up: tile("Ligado há"), temp: tile("Temperatura"),
  };
  const cpuRam = percentChart("CPU e memória — últimos 15 min");
  const net = networkChart("Rede — últimos 15 min");
  const agentBox = h("div");
  const serversBox = h("div");
  const paintServers = (list) => {
    if (!list) { serversBox.replaceChildren(h("p", { class: "muted", text: "Módulo de servidores indisponível." })); return; }
    const c = summarize(list);
    serversBox.replaceChildren(
      h("div", { class: "server-counts" },
        ...[["Total", c.total], ["Online", c.online], ["Offline", c.offline], ["Com problemas", c.problems]].map(([label, n]) =>
          h("div", {}, h("div", { class: "value num", text: String(n) }), h("div", { class: "muted small", text: label })))),
      list.length
        ? h("ul", { class: "server-list" }, ...list.map((i) => h("li", {}, h("a", { href: `#/servidores/${i.server.id}`, text: i.server.name }), statePill(i.status.state))))
        : h("p", { class: "muted", text: "Nenhum servidor cadastrado." }, " ", h("a", { href: "#/servidores/novo", text: "Cadastrar" })));
  };
  paintServers(servers ? servers.servers : null);
  const activity = h("ul", { class: "events" });
  for (const e of events.events) activity.append(eventItem(e));
  if (!events.events.length) activity.append(h("li", { class: "muted", text: "Nenhum evento registrado." }));

  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: status.machine?.hostname || "Visão geral" }),
      h("span", { class: "muted", text: status.machine?.cpu_model || "" })),
    alerts.node,
    h("div", { class: "grid tiles" }, ...Object.values(t).map((x) => x.node)),
    h("div", { class: "grid two" }, card("Servidores", serversBox), card("Atividade recente", activity)),
    h("div", { class: "grid two" }, cpuRam.node, net.node),
    card("Estado do Sentinel", agentBox),
  );

  let current = status;
  const paintStatic = (s) => {
    const m = s.machine;
    t.up.set(m ? fmt.duration(m.uptime_seconds) : fmt.DASH, m ? `desde ${fmt.dateTime(m.boot_time)}` : "");
    const disks = s.disks?.disks || [];
    if (disks.length) {
      const worst = disks.reduce((a, b) => (b.free / b.total < a.free / a.total ? b : a));
      t.disk.set(fmt.percent(worst.percent), `${worst.mountpoint}: ${fmt.bytes(worst.free)} livres de ${fmt.bytes(worst.total)}${disks.length > 1 ? ` · +${disks.length - 1} partição(ões)` : ""}`, worst.percent);
    } else t.disk.set(fmt.DASH, "Coletando…");
    const temp = s.temperature;
    if (temp?.available) {
      const max = Math.max(...temp.sensors.map((x) => x.current));
      t.temp.set(`${Math.round(max)} °C`, `${temp.sensors.length} sensor(es)`);
    } else t.temp.set("Indisponível", temp?.message || "Coletando…");
    renderAgent(agentBox, s);
  };
  const paintLive = (d) => {
    const cores = current.machine?.cpu_cores_logical;
    t.cpu.set(fmt.percent(d.cpu.percent), [cores ? `${cores} núcleos lógicos` : null, d.cpu.frequency_mhz ? `${fmt.number(d.cpu.frequency_mhz)} MHz` : null].filter(Boolean).join(" · "), d.cpu.percent);
    t.mem.set(fmt.percent(d.memory.percent), `${fmt.bytes(d.memory.used)} de ${fmt.bytes(d.memory.total)}`, d.memory.percent);
    if (d.network.download_bps == null) t.net.set("Medindo…", "aguardando a segunda leitura");
    else t.net.set(`↓ ${fmt.bitrate(d.network.download_bps)}`, `↑ ${fmt.bitrate(d.network.upload_bps)}`);
    const now = d.ts_epoch;
    cpuRam.chart.setData(state.live, [now - LIVE_WINDOW, now]);
    net.chart.setData(state.live, [now - LIVE_WINDOW, now]);
    cpuRam.setTable(state.live);
    net.setTable(state.live);
    alerts.render(state.alerts, state.resources);
  };

  paintStatic(status);
  if (status.current) paintLive(status.current);
  else alerts.render(state.alerts, state.resources);

  const refresh = setInterval(async () => {
    try { current = await getJSON("/api/v1/system/status"); paintStatic(current); }
    catch (err) { if (err instanceof UnauthorizedError) showUnauthorized(); }
  }, 30_000);

  return {
    onMetrics: paintLive,
    onServers: paintServers,
    onApprovals: () => alerts.render(state.alerts, state.resources),
    onEvent: (e) => {
      if (activity.firstChild?.classList?.contains("muted")) activity.replaceChildren();
      activity.prepend(eventItem(e));
      while (activity.children.length > 12) activity.lastChild.remove();
    },
    destroy: () => { clearInterval(refresh); cpuRam.chart.destroy(); net.chart.destroy(); },
  };
}

function tile(label) {
  const value = h("div", { class: "value num", text: fmt.DASH });
  const detail = h("div", { class: "detail" });
  const bar = meter(0);
  bar.hidden = true;
  const node = h("section", { class: "card tile" }, h("h3", { text: label }), value, detail, bar);
  return {
    node,
    set(v, d, pct) {
      value.textContent = v;
      detail.textContent = d || "";
      bar.hidden = pct == null;
      if (pct != null) setMeter(bar, pct);
    },
  };
}

function renderAgent(box, s) {
  const a = s.agent;
  const stateLabel = { running: ["Em execução", "pill-good"], degraded: ["Degradado", "pill-warning"] }[a.state] || [a.state, "pill-muted"];
  const modules = h("ul", { class: "events" });
  for (const m of a.modules) {
    const ok = m.status === "running" && m.health?.healthy !== false;
    modules.append(h("li", {},
      h("span", { class: `pill ${ok ? "pill-good" : "pill-critical"}`, text: ok ? "OK" : "Falha" }),
      h("div", {}, h("div", { class: "title", text: m.name }), h("div", { class: "desc", text: m.error || m.health?.detail || m.status }))));
  }
  const level = { normal: "Normal", pressure: "Sob pressão", severe: "Sob pressão severa" }[s.resources.level] || s.resources.level;
  box.replaceChildren(
    h("dl", { class: "dl" },
      h("dt", { text: "Agente" }), h("dd", {}, h("span", { class: `pill ${stateLabel[1]}`, text: stateLabel[0] })),
      h("dt", { text: "Versão" }), h("dd", { text: a.version }),
      h("dt", { text: "Última coleta" }), h("dd", { text: s.current ? fmt.ago(s.current.age_seconds) : "nenhuma ainda" }),
      h("dt", { text: "Modo de recursos" }), h("dd", { text: `${level} (fator ${s.resources.load_factor}x)` }),
      h("dt", { text: "IA local" }), h("dd", {}, h("span", { class: "pill pill-muted", text: "Indisponível" }), " ", h("span", { class: "muted", text: s.ai.message })),
      h("dt", { text: "Tarefas com falha" }), h("dd", { text: a.failing_jobs.length ? a.failing_jobs.join(", ") : "nenhuma" })),
    h("h3", { class: "section-gap", text: "Módulos" }),
    modules);
}

async function systemPage() {
  const [status, network, disks] = await Promise.all([
    getJSON("/api/v1/system/status"), getJSON("/api/v1/system/network"), getJSON("/api/v1/system/disks"),
  ]);
  const m = status.machine || {};
  const ranges = ["15m", "1h", "6h", "24h", "7d", "30d"];
  const rangeLabels = { "15m": "15 min", "1h": "1 h", "6h": "6 h", "24h": "24 h", "7d": "7 dias", "30d": "30 dias" };
  let range = "1h";
  const charts = h("div");
  const selector = h("div", { class: "segmented", role: "group", "aria-label": "Período" });
  const coreBox = h("div", { class: "cores" });
  let active = [];

  const loadRange = async () => {
    for (const b of selector.children) b.setAttribute("aria-pressed", String(b.dataset.range === range));
    active.forEach((c) => c.chart.destroy());
    const data = await getJSON(`/api/v1/system/metrics?range=${range}`);
    const long = ["24h", "7d", "30d"].includes(range);
    const pr = percentChart("CPU e memória", long);
    const nt = networkChart("Rede", long);
    const now = Date.now() / 1000;
    const secs = { "15m": 900, "1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800, "30d": 2592000 }[range];
    pr.chart.setData(data.points, [now - secs, now]);
    nt.chart.setData(data.points, [now - secs, now]);
    pr.setTable(data.points);
    nt.setTable(data.points);
    const s = data.summary;
    const src = data.source === "live" ? "resolução de 5 s" : "médias gravadas a cada minuto";
    summaryLine(pr.summary, [["CPU média", fmt.percent(s.cpu_avg)], ["Pico de CPU", fmt.percent(s.cpu_peak)], ["Memória média", fmt.percent(s.ram_avg)], ["Pico de memória", fmt.percent(s.ram_peak)], ["Fonte", src]]);
    summaryLine(nt.summary, [["Download médio", fmt.bitrate(s.download_avg)], ["Upload médio", fmt.bitrate(s.upload_avg)]]);
    if (!data.points.length) summaryLine(pr.summary, [["Sem dados no período", "o histórico começa quando o agente passa a coletar"]]);
    active = [pr, nt];
    charts.replaceChildren(h("div", { class: "grid two" }, pr.node, nt.node));
  };
  for (const r of ranges) {
    selector.append(h("button", { type: "button", "data-range": r, text: rangeLabels[r], onclick: () => { range = r; loadRange().catch(showError); } }));
  }

  const paintCores = (d) => {
    coreBox.replaceChildren(...d.cpu.per_core.map((v, i) =>
      h("div", { class: "core" }, h("div", { class: "label" }, h("span", { text: `Núcleo ${i + 1}` }), h("span", { class: "num", text: fmt.percent(v) })), meter(v))));
  };

  const growth = disks.growth_7d || {};
  const diskRows = (disks.disks || []).map((d) => {
    const g = growth[d.mountpoint];
    const trend = g && g.bytes_per_day != null ? `${g.bytes_per_day >= 0 ? "+" : "−"}${fmt.bytes(Math.abs(g.bytes_per_day))}/dia` : "histórico insuficiente";
    return h("tr", {},
      h("td", { text: d.mountpoint }), h("td", { class: "secondary", text: d.fstype }),
      h("td", { class: "num", text: fmt.bytes(d.total) }), h("td", { class: "num", text: fmt.bytes(d.free) }),
      h("td", { class: "num", text: fmt.percent(d.percent) }), h("td", {}, meter(d.percent)), h("td", { class: "secondary", text: trend }));
  });
  const ifaces = (network.network?.interfaces || []).filter((i) => !i.is_loopback).map((i) =>
    h("tr", {},
      h("td", { text: i.name }), h("td", {}, h("span", { class: `pill ${i.is_up ? "pill-good" : "pill-muted"}`, text: i.is_up ? "Ativa" : "Inativa" })),
      h("td", { class: "secondary", text: i.ipv4.join(", ") || fmt.DASH }),
      h("td", { class: "num", text: i.speed_mbps ? `${i.speed_mbps} Mbps` : fmt.DASH }),
      h("td", { class: "num", text: fmt.bitrate(i.download_bps) }), h("td", { class: "num", text: fmt.bitrate(i.upload_bps) }),
      h("td", { class: "num", text: fmt.number(i.errors_in + i.errors_out) })));

  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: "Sistema" }), selector),
    charts,
    h("div", { class: "grid two" },
      card("Computador", h("dl", { class: "dl" },
        h("dt", { text: "Nome" }), h("dd", { text: m.hostname || fmt.DASH }),
        h("dt", { text: "Sistema" }), h("dd", { text: m.os || fmt.DASH }),
        h("dt", { text: "Processador" }), h("dd", { text: m.cpu_model || "Não identificado" }),
        h("dt", { text: "Núcleos" }), h("dd", { text: `${m.cpu_cores_physical ?? fmt.DASH} físicos · ${m.cpu_cores_logical ?? fmt.DASH} lógicos` }),
        h("dt", { text: "Memória" }), h("dd", { text: fmt.bytes(m.memory_total) }),
        h("dt", { text: "Ligado desde" }), h("dd", { text: fmt.dateTime(m.boot_time) }),
        h("dt", { text: "Temperatura" }), h("dd", { text: status.temperature?.available
          ? status.temperature.sensors.map((x) => `${x.label}: ${Math.round(x.current)} °C`).join(" · ")
          : (status.temperature?.message || fmt.DASH) }))),
      card("Uso por núcleo", coreBox)),
    card("Armazenamento", h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ...["Unidade", "Sistema de arquivos", "Total", "Livre", "Uso", "", "Tendência (7 dias)"].map((x, i) => h("th", { class: i >= 2 && i <= 4 ? "num" : null, text: x })))),
      h("tbody", {}, diskRows.length ? diskRows : h("tr", {}, h("td", { colspan: 7, class: "muted", text: "Coletando…" })))))),
    card("Interfaces de rede", h("div", { class: "table-wrap" }, h("table", {},
      h("thead", {}, h("tr", {}, ...["Interface", "Estado", "IPv4", "Velocidade", "Download", "Upload", "Erros"].map((x, i) => h("th", { class: i >= 3 ? "num" : null, text: x })))),
      h("tbody", {}, ifaces.length ? ifaces : h("tr", {}, h("td", { colspan: 7, class: "muted", text: "Nenhuma interface encontrada." })))))),
  );
  if (status.current) paintCores(status.current);
  await loadRange();
  return { onMetrics: paintCores, destroy: () => active.forEach((c) => c.chart.destroy()) };
}

async function processesPage() {
  let sort = "cpu";
  let filter = "";
  const body = h("tbody");
  const info = h("span", { class: "muted" });
  const headers = [["name", "Nome"], ["pid", "PID"], ["cpu", "CPU"], ["memory", "Memória"], ["runtime", "Iniciado em"], [null, "Usuário"], [null, "Caminho"], [null, ""]];
  const headRow = h("tr");
  const load = async () => {
    const data = await getJSON(`/api/v1/system/processes?sort=${sort}&limit=1000`);
    info.textContent = data.collected_at ? `${data.count} processos · coletado ${fmt.dateTime(data.collected_at)} · atualiza a cada 15 s` : "Coletando…";
    const q = filter.toLowerCase();
    const rows = data.processes.filter((p) => !q || p.name.toLowerCase().includes(q) || (p.exe || "").toLowerCase().includes(q));
    body.replaceChildren(...rows.slice(0, 300).map((p) => h("tr", {},
      h("td", { text: p.name }), h("td", { class: "num", text: p.pid }),
      h("td", { class: "num", text: p.cpu_percent == null ? "medindo" : fmt.percent(p.cpu_percent) }),
      h("td", { class: "num", text: fmt.bytes(p.memory_bytes) }),
      h("td", { class: "num", text: fmt.dateTime(p.started_at) }),
      h("td", { class: "secondary", text: p.username || "sem acesso" }),
      h("td", { class: "path", title: p.exe || "", text: p.exe || "sem acesso" }),
      h("td", {}, h("a", { class: "btn btn-small", href: `#/servidores/novo?pid=${p.pid}`, title: "Cadastrar como servidor monitorado", text: "Monitorar" })))));
    if (!rows.length) body.replaceChildren(h("tr", {}, h("td", { colspan: 8, class: "muted", text: "Nenhum processo encontrado." })));
  };
  const paintHead = () => headRow.replaceChildren(...headers.map(([key, label]) => {
    const numeric = ["pid", "cpu", "memory", "runtime"].includes(key);
    if (!key || key === "pid") return h("th", { class: numeric ? "num" : null, text: label });
    return h("th", { class: numeric ? "num" : null }, h("button", { type: "button", "aria-pressed": String(sort === key), text: label,
      onclick: () => { sort = key; paintHead(); load().catch(showError); } }));
  }));
  paintHead();
  const search = h("input", { type: "search", placeholder: "Filtrar por nome ou caminho", "aria-label": "Filtrar processos",
    oninput: (e) => { filter = e.target.value; load().catch(showError); } });
  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: "Processos" }), search),
    h("section", { class: "card" }, h("div", { class: "card-head" }, info, h("span", { class: "muted", text: "Somente observação — nenhuma ação é executada nesta versão." })),
      h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, headRow), body))));
  await load();
  const timer = setInterval(() => load().catch((err) => { if (err instanceof UnauthorizedError) showUnauthorized(); }), 15_000);
  return { destroy: () => clearInterval(timer) };
}

async function historyPage() {
  const tabs = { eventos: "Eventos", acoes: "Ações", auditoria: "Auditoria" };
  let tab = "eventos";
  const content = h("section", { class: "card" });
  const bar = h("div", { class: "segmented", role: "tablist" });
  let events = null;
  let severity = "";
  const select = h("select", { "aria-label": "Filtrar por severidade", onchange: (e) => { severity = e.target.value; render(); } },
    h("option", { value: "", text: "Todas as severidades" }),
    ...Object.entries(fmt.SEVERITY).map(([k, v]) => h("option", { value: k, text: v.label })));

  const render = async () => {
    for (const b of bar.children) b.setAttribute("aria-pressed", String(b.dataset.tab === tab));
    select.hidden = tab !== "eventos";
    if (tab === "eventos") {
      events ??= (await getJSON("/api/v1/events?limit=500")).events;
      const items = events.filter((e) => !severity || e.severity === severity);
      content.replaceChildren(h("ul", { class: "events" }, ...(items.length ? items.map(eventItem) : [h("li", { class: "muted", text: "Nenhum evento." })])));
    } else if (tab === "acoes") {
      content.replaceChildren(actionsTable((await getJSON("/api/v1/actions?limit=200")).actions));
    } else {
      content.replaceChildren(
        h("p", { class: "muted small", text: "Registro somente leitura: nem o dashboard nem a IA conseguem alterar ou apagar estas linhas." }),
        auditTable((await getJSON("/api/v1/audit?limit=500")).entries));
    }
  };
  for (const [key, label] of Object.entries(tabs)) {
    bar.append(h("button", { type: "button", role: "tab", "data-tab": key, text: label, onclick: () => { tab = key; render().catch(showError); } }));
  }
  view.replaceChildren(h("div", { class: "page-head" }, h("h1", { text: "Histórico" }), bar, select), content);
  await render();
  return { onEvent: (e) => { if (events) { events.unshift(e); if (tab === "eventos") render().catch(console.error); } } };
}

// ---------------------------------------------------------------- roteamento

const routes = {
  "/": overviewPage,
  "/sistema": systemPage,
  "/processos": processesPage,
  "/historico": historyPage,
  "/servidores": () => serversPage(view),
  "/configuracoes": () => settingsPage(view),
  "/aprovacoes": () => approvalsPage(view),
  "/seguranca": () => securityPage(view),
};

// Rotas com parâmetro: #/servidores/novo?pid=N, #/servidores/ID, #/servidores/ID/editar
function resolve(hash) {
  const [path, query] = hash.split("?");
  const params = new URLSearchParams(query || "");
  if (routes[path]) return { section: path, run: routes[path] };
  let m;
  if (path === "/servidores/novo") return { section: "/servidores", run: () => serverFormPage(view, { pid: params.get("pid") }) };
  if ((m = path.match(/^\/servidores\/(\d+)\/editar$/))) return { section: "/servidores", run: () => serverFormPage(view, { id: Number(m[1]) }) };
  if ((m = path.match(/^\/servidores\/(\d+)$/))) return { section: "/servidores", run: () => serverDetailPage(view, Number(m[1])) };
  return { section: "/", run: routes["/"] };
}

async function navigate() {
  const { section, run } = resolve(location.hash.slice(1) || "/");
  for (const a of document.querySelectorAll(".nav a")) a.classList.toggle("active", a.dataset.route === section);
  page?.destroy?.();
  page = null;
  try {
    page = await run();
  } catch (err) {
    if (err instanceof UnauthorizedError) showUnauthorized();
    else { console.error(err); showError(err); }
  }
}

async function main() {
  if (!(await checkSession())) return;
  document.getElementById("logout").addEventListener("click", async () => { await logout(); showUnauthorized(); });
  window.addEventListener("hashchange", navigate);
  channel = new LiveChannel({ onMessage: onLiveMessage, onState: onLiveState });
  refreshApprovalBadge();
  await navigate();
}

main();
