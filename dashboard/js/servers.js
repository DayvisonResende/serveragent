// Páginas de servidores (PRD 14.5): lista com cartões, cadastro/edição e detalhes.

import { getJSON, sendJSON, ApiError } from "./api.js";
import * as fmt from "./format.js";
import { h, card } from "./ui.js";
import { pickPath, dirname, basename } from "./filepicker.js";

const STATES = {
  online: ["Online", "pill-good"],
  offline: ["Offline", "pill-critical"],
  degraded: ["Com problemas", "pill-warning"],
  unresponsive: ["Sem resposta", "pill-serious"],
  starting: ["Inicializando", "pill-muted"],
  restarting: ["Reiniciando", "pill-muted"],
  unknown: ["Desconhecido", "pill-muted"],
  disabled: ["Desativado", "pill-muted"],
};
const TYPES = { game: "Jogo", node: "Node.js", python: "Python", database: "Banco de dados", tunnel: "Túnel", web: "Web", service: "Serviço", other: "Outro" };
const CRITICALITY = { low: "Baixa", medium: "Média", high: "Alta", critical: "Crítica" };
const HEALTH = { none: "Somente processo", port: "Porta escutando", tcp: "Conexão TCP", http: "Requisição HTTP" };

export function statePill(state) {
  const [label, cls] = STATES[state] || [state, "pill-muted"];
  return h("span", { class: `pill ${cls}`, text: label });
}

function field(label, value) {
  return [h("dt", { text: label }), h("dd", {}, value ?? fmt.DASH)];
}

function message(text, kind = "info") {
  return h("div", { class: `form-message form-message-${kind}`, role: kind === "error" ? "alert" : "status", text });
}

// ------------------------------------------------------------- operações

async function runAction(server, action, onDone) {
  const labels = { start: "iniciar", stop: "parar", restart: "reiniciar" };
  const warning = action === "start" ? "" : "\n\nNo Windows o encerramento é imediato (o processo não recebe aviso prévio).";
  if (!window.confirm(`Confirma ${labels[action]} o servidor "${server.name}"?${warning}`)) return null;
  try {
    const result = await sendJSON("POST", `/api/v1/servers/${server.id}/actions/${action}`, { reason: "dashboard" });
    onDone?.(result);
    return result;
  } catch (err) {
    onDone?.({ ok: false, message: err.message });
    return null;
  }
}

function actionButtons(server, status, onDone) {
  if (server.management !== "managed") {
    return h("p", { class: "muted small", text: "Somente observado — o Sentinel não inicia nem encerra este servidor." });
  }
  const busy = Boolean(status.operation);
  const running = status.pids.length > 0;
  const result = h("div", { class: "op-result", "aria-live": "polite" });
  const done = (r) => {
    result.replaceChildren(message(r.message + (r.warning ? ` — Atenção: ${r.warning}` : ""), r.ok ? "ok" : "error"));
    onDone?.();
  };
  const btn = (action, label, enabled, danger = false) => h("button", {
    type: "button", class: `btn${danger ? " btn-danger" : ""}`, disabled: !enabled || busy,
    onclick: async (e) => {
      e.currentTarget.disabled = true;
      result.replaceChildren(message(`${label}…`));
      await runAction(server, action, done);
    },
  }, label);
  return h("div", {},
    h("div", { class: "actions" },
      btn("start", "Iniciar", !running),
      btn("restart", "Reiniciar", true),
      btn("stop", "Parar", running, true)),
    result);
}

// ---------------------------------------------------------------- lista

function serverCard(item, refresh) {
  const { server: s, status: st } = item;
  const checkAge = st.last_check ? fmt.ago(Date.now() / 1000 - st.last_check.ts_epoch) : "ainda não verificado";
  return h("section", { class: "card server-card" },
    h("div", { class: "card-head" },
      h("h2", {}, h("a", { href: `#/servidores/${s.id}`, text: s.name })),
      statePill(st.state)),
    h("dl", { class: "dl" },
      ...field("Tipo", `${TYPES[s.server_type] || s.server_type} · ${s.management === "managed" ? "gerenciado" : "observado"}`),
      ...field("Porta", s.port ? String(s.port) : null),
      ...field("PID", st.main_pid ? `${st.main_pid}${st.pids.length > 1 ? ` (+${st.pids.length - 1})` : ""}` : null),
      ...field("CPU", fmt.percent(st.cpu_percent)),
      ...field("Memória", fmt.bytes(st.memory_bytes)),
      ...field("Ativo há", st.uptime_seconds != null ? fmt.duration(st.uptime_seconds) : null),
      ...field("Verificado", checkAge)),
    st.state === "online" && !st.health_verified
      ? h("p", { class: "muted small", text: "Processo ativo, mas a saúde não é verificada (configure porta, TCP ou HTTP)." })
      : null,
    st.last_check?.error && st.state !== "online" ? h("p", { class: "secondary small", text: st.last_check.error }) : null,
    st.warning ? h("p", { class: "secondary small", text: `Atenção: ${st.warning}` }) : null,
    actionButtons(s, st, refresh));
}

export async function serversPage(view) {
  const grid = h("div", { class: "grid servers-grid" });
  const counts = h("span", { class: "muted" });
  const render = (data) => {
    const c = data.counts;
    counts.textContent = `${c.total} cadastrado(s) · ${c.online} online · ${c.offline} offline · ${c.problems} com problemas`;
    grid.replaceChildren(...(data.servers.length
      ? data.servers.map((item) => serverCard(item, load))
      : [card("Nenhum servidor cadastrado",
          h("p", { class: "secondary", text: "Cadastre um servidor manualmente ou, na página Processos, use “Monitorar” em um processo em execução (ex.: postgres.exe, mysqld.exe)." }))]));
  };
  const load = async () => render(await getJSON("/api/v1/servers"));
  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: "Servidores" }), counts,
      h("a", { class: "btn btn-primary", href: "#/servidores/novo", text: "Cadastrar servidor" })),
    grid);
  await load();
  return { onServers: (servers) => render({ servers, counts: summarize(servers) }) };
}

export function summarize(servers) {
  const states = servers.map((i) => i.status.state);
  return {
    total: states.length,
    online: states.filter((s) => s === "online").length,
    offline: states.filter((s) => s === "offline").length,
    problems: states.filter((s) => s === "degraded" || s === "unresponsive").length,
  };
}

// --------------------------------------------------------- formulário

function input(name, label, value, attrs = {}, hint = null, browse = null) {
  const id = `f-${name}`;
  const el = h("input", { id, name, value: value ?? "", ...attrs });
  const control = browse
    ? h("div", { class: "input-row" }, el, h("button", { type: "button", class: "btn", text: "Procurar…", onclick: async () => {
        const start = el.value ? (browse.kind === "directory" ? el.value : dirname(el.value)) : null;
        const chosen = await pickPath({ kind: browse.kind, start });
        if (chosen) { el.value = chosen; browse.onPick?.(chosen); }
      } }))
    : el;
  return h("div", { class: "form-field" },
    h("label", { for: id, text: label }),
    control,
    hint ? h("small", { class: "muted", text: hint }) : null);
}

function select(name, label, options, value) {
  const id = `f-${name}`;
  const el = h("select", { id, name }, ...Object.entries(options).map(([k, v]) => h("option", { value: k, text: v })));
  el.value = value;
  return h("div", { class: "form-field" }, h("label", { for: id, text: label }), el);
}

export async function serverFormPage(view, { id, pid } = {}) {
  let spec = { name: "", server_type: "other", management: "observed", arguments: [], health_check: { type: "none" }, criticality: "medium", startup_grace_seconds: 30, enabled: true, process_match: {} };
  let hint = null;
  if (id) spec = (await getJSON(`/api/v1/servers/${id}`)).server;
  else if (pid) {
    const cand = await getJSON(`/api/v1/system/processes/${pid}/candidate`);
    spec = { ...spec, ...cand.suggestion };
    hint = `Sugestão a partir do processo ${pid}${cand.listening_ports.length ? ` (portas: ${cand.listening_ports.join(", ")})` : " (nenhuma porta escutando)"}. Confira antes de salvar.`;
  }
  const hc = spec.health_check || {};
  const pm = spec.process_match || {};
  const feedback = h("div");
  const scriptHint = h("p", { class: "form-message form-wide small", hidden: !/\.(bat|cmd)$/i.test(spec.executable || ""),
    text: "Script .bat/.cmd: executado pelo cmd.exe num formato fixo. Argumentos só com letras, números e . _ - : \\ / = + , @ (sem espaços nem & | % ^ < > !). Para parar, o Sentinel encerra o script e os programas que ele iniciou." });
  const form = h("form", { class: "form-grid", novalidate: true },
    input("name", "Nome", spec.name, { required: true, maxlength: 80 }),
    select("server_type", "Tipo", TYPES, spec.server_type),
    input("description", "Descrição", spec.description, { maxlength: 500 }),
    select("management", "Gerenciamento", { observed: "Observado (só monitorar)", managed: "Gerenciado (iniciar/parar/reiniciar)" }, spec.management),
    input("executable", "Executável ou script", spec.executable, { maxlength: 500 },
      "Arquivo .exe, .bat ou .cmd. Obrigatório para servidores gerenciados. Interpretadores de comandos (cmd, PowerShell) não são aceitos.",
      { kind: "executable", onPick: (path) => {
        const wd = form.elements.namedItem("working_directory");
        const nm = form.elements.namedItem("name");
        if (!wd.value) wd.value = dirname(path);
        if (!nm.value) nm.value = basename(path).replace(/\.(exe|bat|cmd|com)$/i, "");
        scriptHint.hidden = !/\.(bat|cmd)$/i.test(path);
      } }),
    scriptHint,
    h("div", { class: "form-field" },
      h("label", { for: "f-arguments", text: "Argumentos (um por linha)" }),
      h("textarea", { id: "f-arguments", name: "arguments", rows: 3, text: (spec.arguments || []).join("\n") })),
    input("working_directory", "Diretório de trabalho", spec.working_directory, { maxlength: 500 }, "Vazio: a pasta do executável.", { kind: "directory" }),
    input("port", "Porta", spec.port, { type: "number", min: 1, max: 65535 }),
    select("protocol", "Protocolo", { tcp: "TCP", udp: "UDP", http: "HTTP", https: "HTTPS" }, spec.protocol || "tcp"),
    select("health_type", "Verificação de saúde", HEALTH, hc.type || "none"),
    input("health_path", "Caminho HTTP", hc.path || "/", { maxlength: 300 }, "Usado na verificação HTTP, ex.: /health"),
    input("health_expected", "Status HTTP esperado", hc.expected_status, { type: "number", min: 100, max: 599 }, "Vazio: qualquer status abaixo de 400"),
    input("log_path", "Arquivo de log da aplicação", spec.log_path, { maxlength: 500 }, null, { kind: "log" }),
    select("criticality", "Criticidade", CRITICALITY, spec.criticality),
    input("startup_grace_seconds", "Tempo para iniciar (s)", spec.startup_grace_seconds, { type: "number", min: 3, max: 600 }),
    h("details", { class: "form-field form-wide" },
      h("summary", { text: "Como reconhecer o processo (avançado)" }),
      h("p", { class: "muted small", text: "Vazio: o Sentinel usa o executável e os argumentos (ou a porta). Todos os critérios preenchidos precisam bater." }),
      input("match_exe", "Caminho do executável", pm.exe_path),
      input("match_name", "Nome do processo", pm.name),
      input("match_cmd", "Linha de comando contém (separe por ;)", (pm.cmdline_contains || []).join(";")),
      h("label", { class: "check" }, h("input", { type: "checkbox", name: "match_port", checked: pm.port_owner || null }), " Exigir que o processo seja o dono da porta")),
    h("label", { class: "check form-wide" }, h("input", { type: "checkbox", name: "enabled", checked: spec.enabled !== false || null }), " Monitoramento ativado"),
    h("div", { class: "actions form-wide" },
      h("button", { type: "submit", class: "btn btn-primary", text: id ? "Salvar alterações" : "Cadastrar" }),
      h("a", { class: "btn", href: id ? `#/servidores/${id}` : "#/servidores", text: "Cancelar" })),
    feedback);

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(form);
    const text = (k) => (f.get(k) || "").toString().trim();
    const num = (k) => (text(k) === "" ? null : Number(text(k)));
    const payload = {
      name: text("name"),
      description: text("description"),
      server_type: text("server_type"),
      management: text("management"),
      executable: text("executable") || null,
      arguments: text("arguments") ? text("arguments").split(/\r?\n/).map((a) => a.trim()).filter(Boolean) : [],
      working_directory: text("working_directory") || null,
      port: num("port"),
      protocol: text("protocol"),
      health_check: { type: text("health_type"), path: text("health_path") || "/", expected_status: num("health_expected") },
      process_match: {
        exe_path: text("match_exe") || null,
        name: text("match_name") || null,
        cmdline_contains: text("match_cmd") ? text("match_cmd").split(";").map((x) => x.trim()).filter(Boolean) : [],
        port_owner: f.get("match_port") === "on",
      },
      log_path: text("log_path") || null,
      criticality: text("criticality"),
      startup_grace_seconds: num("startup_grace_seconds") ?? 30,
      enabled: f.get("enabled") === "on",
    };
    try {
      const saved = await sendJSON(id ? "PUT" : "POST", id ? `/api/v1/servers/${id}` : "/api/v1/servers", payload);
      location.hash = `#/servidores/${saved.server.id}`;
    } catch (err) {
      feedback.replaceChildren(message(err instanceof ApiError ? err.message : String(err), "error"));
    }
  });

  view.replaceChildren(...[
    h("div", { class: "page-head" }, h("h1", { text: id ? `Editar ${spec.name}` : "Cadastrar servidor" })),
    hint ? message(hint) : null,
    h("section", { class: "card" }, form),
  ].filter(Boolean));
  return {};
}

// ------------------------------------------------------------- detalhes

export async function serverDetailPage(view, id) {
  const head = h("div", { class: "page-head" });
  const info = h("div");
  const checksBody = h("tbody");
  const incidentsList = h("ul", { class: "events" });
  const logBox = h("pre", { class: "log-view", tabindex: 0 });
  const logInfo = h("span", { class: "muted small" });
  let logSource = null;  // definido após carregar o cadastro

  const loadLogs = async () => {
    const data = await getJSON(`/api/v1/servers/${id}/logs?source=${logSource}&lines=300`);
    logBox.textContent = data.available ? data.lines.join("\n") || "(vazio)" : `Indisponível: ${data.reason}`;
    logInfo.textContent = data.available ? `${data.path} · ${fmt.bytes(data.size_bytes)}${data.truncated ? " · últimas linhas" : ""}` : "";
    logBox.scrollTop = logBox.scrollHeight;
  };

  const load = async () => {
    const [item, checks, incidents] = await Promise.all([
      getJSON(`/api/v1/servers/${id}`),
      getJSON(`/api/v1/servers/${id}/health?limit=30`),
      getJSON(`/api/v1/servers/${id}/incidents?limit=20`),
    ]);
    const { server: s, status: st } = item;
    if (logSource === null) {
      // Gerenciado sem log próprio: mostra a saída capturada pelo Sentinel.
      logSource = !s.log_path && s.management === "managed" ? "sentinel" : "app";
      sourceSelect.value = logSource;
    }
    head.replaceChildren(h("div", { class: "title-row" }, h("h1", { text: s.name }), statePill(st.state)),
      h("div", { class: "actions" },
        h("a", { class: "btn", href: `#/servidores/${id}/editar`, text: "Editar" }),
        h("button", { type: "button", class: "btn btn-danger", text: "Excluir cadastro", onclick: async () => {
          if (!window.confirm(`Excluir o cadastro de "${s.name}"?\n\nO processo do servidor NÃO será encerrado; o Sentinel apenas deixa de monitorá-lo.`)) return;
          await sendJSON("DELETE", `/api/v1/servers/${id}`);
          location.hash = "#/servidores";
        } })));
    info.replaceChildren(h("div", { class: "grid two" },
      card("Configuração", h("dl", { class: "dl" },
        ...field("Tipo", TYPES[s.server_type] || s.server_type),
        ...field("Gerenciamento", s.management === "managed" ? "Gerenciado" : "Observado"),
        ...field("Executável", s.executable),
        ...field("Argumentos", s.arguments.length ? s.arguments.join(" ") : null),
        ...field("Diretório", s.working_directory),
        ...field("Porta", s.port ? `${s.port} (${s.protocol.toUpperCase()})` : null),
        ...field("Saúde", `${HEALTH[s.health_check.type]}${s.health_check.type === "http" ? ` ${s.health_check.path}` : ""}`),
        ...field("Criticidade", CRITICALITY[s.criticality]),
        ...field("Monitoramento", s.enabled ? "Ativo" : "Desativado"))),
      card("Estado atual", h("dl", { class: "dl" },
        ...field("Estado", statePill(st.state)),
        ...field("Desde", fmt.dateTime(st.since)),
        ...field("PID", st.main_pid ? String(st.main_pid) : null),
        ...field("CPU", fmt.percent(st.cpu_percent)),
        ...field("Memória", fmt.bytes(st.memory_bytes)),
        ...field("Ativo há", st.uptime_seconds != null ? fmt.duration(st.uptime_seconds) : null),
        ...field("Última operação", st.last_operation ? `${st.last_operation.message} (${fmt.dateTime(st.last_operation.at)})` : null)),
        actionButtons(s, st, load))));
    checksBody.replaceChildren(...(checks.checks.length ? checks.checks.map((c) => h("tr", {},
      h("td", { class: "num", text: fmt.dateTime(c.timestamp) }),
      h("td", {}, statePill(c.state)),
      h("td", { text: { ok: "OK", fail: "Falhou", timeout: "Sem resposta", skipped: "Não verificada" }[c.health_status] || c.health_status }),
      h("td", { class: "num", text: c.response_time_ms != null ? `${fmt.number(c.response_time_ms)} ms` : fmt.DASH }),
      h("td", { class: "secondary", text: c.error_message || "" }))) : [h("tr", {}, h("td", { colspan: 5, class: "muted", text: "Nenhuma verificação ainda." }))]));
    incidentsList.replaceChildren(...(incidents.incidents.length ? incidents.incidents.map((i) => h("li", {},
      h("time", { text: fmt.dateTime(i.opened_at) }),
      h("div", {},
        h("div", { class: "title", text: i.title }),
        h("div", { class: "desc", text: i.closed_at ? `Resolvido (${i.resolution}) após ${fmt.duration(i.duration_seconds)}` : `Em aberto há ${fmt.duration(i.duration_seconds)}` })))) : [h("li", { class: "muted", text: "Nenhum incidente registrado." })]));
  };

  const sourceSelect = h("select", { "aria-label": "Origem do log", onchange: (e) => { logSource = e.target.value; loadLogs(); } },
    h("option", { value: "app", text: "Log da aplicação" }), h("option", { value: "sentinel", text: "Saída capturada pelo Sentinel" }));
  view.replaceChildren(head, info,
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Verificações recentes" })),
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ...["Horário", "Estado", "Saúde", "Resposta", "Detalhe"].map((x) => h("th", { text: x })))), checksBody))),
    h("section", { class: "card" }, h("div", { class: "card-head" }, h("h2", { text: "Incidentes" })), incidentsList),
    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "Logs" }), h("div", { class: "actions" }, sourceSelect,
        h("button", { type: "button", class: "btn", text: "Atualizar", onclick: loadLogs }))),
      logInfo, logBox,
      h("p", { class: "muted small", text: "Conteúdo exibido como texto. Logs podem conter dados sensíveis da aplicação." })));
  await load();
  await loadLogs();
  const timer = setInterval(() => load().catch((err) => console.error(err)), 15_000);
  return { destroy: () => clearInterval(timer) };
}
