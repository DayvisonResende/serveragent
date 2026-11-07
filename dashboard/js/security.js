// Aprovações (PRD 14.8), segurança (inicialização automática) e tabelas de ações/auditoria.

import { getJSON, sendJSON, ApiError } from "./api.js";
import * as fmt from "./format.js";
import { h, card, severityBadge } from "./ui.js";

const ACTORS = {
  "usuario:dashboard": "Você (dashboard)",
  "usuario:cli": "Você (linha de comando)",
  "sentinel:servidores": "Sentinel (servidores)",
  "sentinel:politica-reinicio": "Reinício automático",
  "politica-autorizada": "Política autorizada por você",
  sentinel: "Sentinel",
};
const STATUS = {
  pending: ["Pendente", "pill-warning"],
  approved: ["Aprovada", "pill-good"],
  executing: ["Executando", "pill-muted"],
  completed: ["Concluída", "pill-good"],
  failed: ["Falhou", "pill-critical"],
  rejected: ["Rejeitada", "pill-muted"],
  expired: ["Expirada", "pill-muted"],
  cancelled: ["Cancelada", "pill-muted"],
};
const RISK = { 0: "Observação", 1: "Leve", 2: "Exige aprovação", 3: "Crítica" };

export const actorLabel = (a) => ACTORS[a] || a || fmt.DASH;

function statusPill(status) {
  const [label, cls] = STATUS[status] || [status, "pill-muted"];
  return h("span", { class: `pill ${cls}`, text: label });
}

function note(text, kind = "info") {
  return h("div", { class: `form-message form-message-${kind}`, role: kind === "error" ? "alert" : "status", text });
}

function expiresIn(epoch) {
  const s = epoch - Date.now() / 1000;
  return s <= 0 ? "expirando" : `expira em ${fmt.duration(Math.max(s, 60))}`;
}

// ---------------------------------------------------------------- aprovações

function approvalCard(a, onDone) {
  const feedback = h("div", { "aria-live": "polite" });
  const decide = async (kind) => {
    let body = {};
    if (kind === "approve") {
      if (a.requires_confirmation) {
        const typed = window.prompt(`Operação crítica. Digite o nome do alvo para confirmar:\n${a.target}`);
        if (typed === null) return;
        body = { confirmation: typed };
      } else if (!window.confirm(`Aprovar: ${a.label} "${a.target}"?\n\nImpacto: ${a.impact}\nRiscos: ${a.risks}`)) {
        return;
      }
    } else {
      const reason = window.prompt("Motivo da rejeição (opcional):", "");
      if (reason === null) return;
      body = { note: reason || null };
    }
    feedback.replaceChildren(note(kind === "approve" ? "Executando…" : "Registrando…"));
    try {
      const r = await sendJSON("POST", `/api/v1/approvals/${a.id}/${kind}`, body);
      const msg = r.result?.message || (r.status === "rejected" ? "Rejeitada." : STATUS[r.status]?.[0] || r.status);
      feedback.replaceChildren(note(msg, r.status === "failed" ? "error" : "ok"));
      setTimeout(onDone, 1500);
    } catch (err) {
      feedback.replaceChildren(note(err instanceof ApiError ? err.message : String(err), "error"));
    }
  };
  return h("section", { class: "card approval" },
    h("div", { class: "card-head" },
      h("h2", { text: `${a.label}: ${a.target}` }),
      h("span", { class: `pill ${a.risk_level >= 3 ? "pill-critical" : "pill-warning"}`, text: `Nível ${a.risk_level} · ${RISK[a.risk_level]}` })),
    h("p", { text: a.reason }),
    h("dl", { class: "dl" },
      h("dt", { text: "Pedido por" }), h("dd", { text: actorLabel(a.requested_by) }),
      h("dt", { text: "Quando" }), h("dd", { text: `${fmt.dateTime(a.created_at)} · ${expiresIn(a.expires_epoch)}` }),
      h("dt", { text: "O que será feito" }), h("dd", { text: a.impact }),
      h("dt", { text: "Riscos" }), h("dd", { text: a.risks })),
    h("div", { class: "actions" },
      h("button", { type: "button", class: "btn btn-primary", text: "Aprovar", onclick: () => decide("approve") }),
      h("button", { type: "button", class: "btn", text: "Rejeitar", onclick: () => decide("reject") })),
    feedback,
    h("p", { class: "muted small", text: "A aprovação vale só para este pedido: se o cadastro do servidor mudar, ela é anulada e nada é executado." }));
}

export function actionsTable(actions) {
  if (!actions.length) return h("p", { class: "muted", text: "Nenhuma ação registrada." });
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ...["Quando", "Operação", "Alvo", "Pedido por", "Situação", "Decidido por", "Resultado"].map((x) => h("th", { text: x })))),
    h("tbody", {}, ...actions.map((a) => h("tr", {},
      h("td", { class: "num", text: fmt.dateTime(a.created_at) }),
      h("td", { text: a.label }),
      h("td", { text: a.target }),
      h("td", { text: actorLabel(a.requested_by) }),
      h("td", {}, statusPill(a.status)),
      h("td", { text: actorLabel(a.decided_by) }),
      h("td", { class: "secondary wrap", text: a.result?.message || a.error_message || a.note || "" }))))));
}

export async function approvalsPage(view) {
  const list = h("div", { class: "grid" });
  const history = h("div");
  const load = async () => {
    const [pending, recent] = await Promise.all([getJSON("/api/v1/approvals?status=pending"), getJSON("/api/v1/actions?limit=30")]);
    list.replaceChildren(...(pending.approvals.length ? pending.approvals.map((a) => approvalCard(a, load))
      : [h("p", { class: "muted", text: "Nenhuma aprovação pendente. Quando o Sentinel (ou, no futuro, a IA) precisar fazer algo que exige autorização, o pedido aparece aqui — e no Telegram, se configurado." })]));
    history.replaceChildren(actionsTable(recent.actions));
  };
  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: "Aprovações" })),
    list,
    card("Ações recentes", history));
  await load();
  return { onEvent: (e) => { if (e.event_type.startsWith("approval.") || e.event_type === "server.operation") load().catch(console.error); } };
}

// ------------------------------------------------------------------ segurança

export async function securityPage(view) {
  const body = h("div");
  const head = h("div", { class: "card-head" });
  const feedback = h("div");
  const load = async () => {
    const data = await getJSON("/api/v1/security/autostart");
    const st = data.status;
    head.replaceChildren(h("h2", { text: "Inicialização automática" }),
      h("button", { type: "button", class: "btn", text: "Verificar agora", onclick: async () => {
        feedback.replaceChildren(note("Verificando registro, tarefas agendadas e serviços…"));
        try { await sendJSON("POST", "/api/v1/security/autostart/scan"); feedback.replaceChildren(); await load(); }
        catch (err) { feedback.replaceChildren(note(err.message, "error")); }
      } }));
    const suspicious = data.entries.filter((e) => e.suspicious);
    const tbody = h("tbody");
    const paintRows = (q) => {
      const query = q.trim().toLowerCase();
      const rows = data.entries.filter((e) => !query || `${e.location} ${e.name} ${e.value}`.toLowerCase().includes(query));
      tbody.replaceChildren(...rows.map((e) => h("tr", { class: e.suspicious ? "row-alert" : null },
        h("td", { text: e.location }), h("td", { text: e.name }),
        h("td", { class: "path", title: e.value, text: e.value }),
        h("td", { class: "num", text: fmt.dateTime(e.first_seen) }))));
    };
    const filter = h("input", { type: "search", placeholder: "Filtrar (ex.: Run, Tarefa, AppData)", "aria-label": "Filtrar itens", oninput: (e) => paintRows(e.target.value) });
    body.replaceChildren(...[
      h("p", { class: "secondary", text: "Programas que iniciam sozinhos com o Windows (registro, Winlogon, pastas Inicializar, tarefas agendadas e serviços). O Sentinel compara com a última verificação e avisa quando algo aparece ou muda — é onde malware costuma se esconder." }),
      h("p", { class: "muted small", text: [
        st.last_scan ? `Última verificação: ${fmt.dateTime(new Date(st.last_scan * 1000).toISOString())}` : "Ainda não verificado",
        `${st.entries} itens`, `${st.suspicious} suspeito(s)`,
        st.errors.length ? `fontes com erro: ${st.errors.join("; ")}` : null,
      ].filter(Boolean).join(" · ") }),
      suspicious.length ? h("div", { class: "alerts" }, ...suspicious.map((e) =>
        h("div", { class: "alert alert-critical" }, severityBadge("critical"),
          h("div", {}, h("div", { class: "title", text: `${e.location} → ${e.name}` }),
            h("div", { class: "desc mono", text: e.value }),
            h("div", { class: "desc", text: e.reasons.join("; ") }))))) : null,
      filter,
      h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ...["Local", "Nome", "Comando / caminho", "Visto desde"].map((x) => h("th", { text: x })))),
        tbody)),
    ].filter(Boolean));
    paintRows("");
  };
  view.replaceChildren(h("div", { class: "page-head" }, h("h1", { text: "Segurança" })),
    h("section", { class: "card" }, head, feedback, body));
  await load();
  return {};
}

// ------------------------------------------------------------------ auditoria

export function auditTable(entries) {
  if (!entries.length) return h("p", { class: "muted", text: "Nenhum registro." });
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, ...["Quando", "Quem", "Operação", "Alvo", "Resultado", "Motivo"].map((x) => h("th", { text: x })))),
    h("tbody", {}, ...entries.map((e) => h("tr", {},
      h("td", { class: "num", text: fmt.dateTime(e.timestamp) }),
      h("td", { text: actorLabel(e.actor) }),
      h("td", { class: "mono", text: e.operation }),
      h("td", { text: e.target || fmt.DASH }),
      h("td", { text: e.result }),
      h("td", { class: "secondary wrap", text: e.reason || "" }))))));
}
