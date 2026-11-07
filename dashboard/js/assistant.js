// Assistente (PRD 9, 14.9): conversa com a IA local.
// As respostas entram como texto puro (textContent): o modelo pode repetir nomes de
// processos ou linhas de log, que não são confiáveis.

import { getJSON, sendJSON, ApiError } from "./api.js";
import { h } from "./ui.js";

const STORAGE_KEY = "sentinel.conversation";

const TOOL_LABEL = {
  get_system_status: "estado do computador",
  get_processes: "processos",
  get_servers: "servidores",
  get_server_details: "detalhes do servidor",
  get_server_logs: "log do servidor",
  get_recent_events: "eventos recentes",
  get_performance_history: "histórico de desempenho",
  request_server_action: "pedido de aprovação",
};

const SUGGESTIONS = [
  "Como está o computador agora?",
  "Algum servidor está com problema?",
  "Quais processos estão usando mais CPU?",
  "Como foi o uso de CPU nas últimas 24 horas?",
  "O que aconteceu de importante hoje?",
];

function loadConversation() {
  try { return localStorage.getItem(STORAGE_KEY); } catch { return null; }
}

function saveConversation(id) {
  try { id ? localStorage.setItem(STORAGE_KEY, id) : localStorage.removeItem(STORAGE_KEY); } catch { /* sem armazenamento: a conversa vale só nesta aba */ }
}

export function aiPill(status) {
  if (!status || status.available == null) return h("span", { class: "pill pill-muted", text: "Verificando" });
  if (status.busy) return h("span", { class: "pill pill-warning", text: "Respondendo" });
  return status.available
    ? h("span", { class: "pill pill-good", text: "Disponível" })
    : h("span", { class: "pill pill-critical", text: "Indisponível" });
}

function seconds(v) {
  return `${Number(v).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s`;
}

function messageNode(m) {
  const mine = m.role === "user";
  const ctx = m.context || {};
  const tools = ctx.ferramentas || [];
  const asked = tools.some((t) => t.ferramenta === "request_server_action" && t.ok);
  return h("li", { class: `msg ${mine ? "msg-user" : "msg-ai"}` },
    h("div", { class: "msg-who", text: mine ? "Você" : "Sentinel (IA)" }),
    h("div", { class: "msg-text", text: m.message }),
    !mine && tools.length ? h("div", { class: "chips", "aria-label": "Dados consultados" },
      h("span", { class: "muted small", text: "Consultou:" }),
      ...tools.map((t) => h("span", { class: `chip ${t.ok ? "" : "chip-error"}`, title: t.ok ? "consulta feita" : "a consulta falhou",
        text: TOOL_LABEL[t.ferramenta] || t.ferramenta }))) : null,
    !mine && !tools.length && ctx.modelo ? h("div", { class: "muted small", text: "Sem consulta a dados: trate números desta resposta com cautela." }) : null,
    asked ? h("div", {}, h("a", { class: "btn btn-small", href: "#/aprovacoes", text: "Ver o pedido em Aprovações" })) : null,
    !mine && ctx.segundos != null ? h("div", { class: "msg-meta", text: `${seconds(ctx.segundos)} · ${ctx.tokens_gerados ?? 0} tokens` }) : null);
}

export async function assistantPage(view) {
  let conversation = loadConversation();
  let status = await getJSON("/api/v1/ai/status").catch(() => null);
  let waiting = false;
  let timer = null;

  const statusBox = h("div", { class: "actions" });
  const list = h("ol", { class: "chat", "aria-live": "polite" });
  const feedback = h("div", { "aria-live": "assertive" });
  const input = h("textarea", { id: "chat-input", rows: 2, maxlength: 2000, placeholder: "Pergunte sobre o computador ou os servidores…  (Enter envia, Shift+Enter quebra a linha)" });
  const send = h("button", { class: "btn btn-primary", type: "submit", text: "Enviar" });
  const suggestions = h("div", { class: "actions" },
    ...SUGGESTIONS.map((q) => h("button", { class: "btn btn-small", type: "button", text: q, onclick: () => ask(q) })));

  const paintStatus = () => {
    statusBox.replaceChildren(aiPill(status), h("span", { class: "muted small", text: status?.message || "estado desconhecido" }),
      status?.model ? h("span", { class: "muted small mono", text: status.model }) : null);
  };

  const setWaiting = (on) => {
    waiting = on;
    send.disabled = on;
    input.disabled = on;
    clearInterval(timer);
    if (!on) { feedback.replaceChildren(); return; }
    const started = Date.now();
    const tick = () => feedback.replaceChildren(h("div", { class: "form-message", role: "status",
      text: `Pensando… ${Math.round((Date.now() - started) / 1000)} s (no processador deste PC, uma resposta leva de 10 s a 1 min)` }));
    tick();
    timer = setInterval(tick, 1000);
  };

  const showEmpty = () => {
    if (!list.children.length) list.append(h("li", { class: "muted chat-empty", text: "Nenhuma mensagem ainda. Escolha uma sugestão ou escreva sua pergunta." }));
  };

  async function loadHistory() {
    list.replaceChildren();
    if (conversation) {
      try {
        const data = await getJSON(`/api/v1/chat/history?conversation_id=${encodeURIComponent(conversation)}`);
        list.append(...data.messages.map(messageNode));
      } catch { conversation = null; saveConversation(null); }
    }
    showEmpty();
    list.lastElementChild?.scrollIntoView({ block: "end" });
  }

  async function ask(text) {
    const question = text.trim();
    if (!question || waiting) return;
    list.querySelector(".chat-empty")?.remove();
    list.append(messageNode({ role: "user", message: question }));
    input.value = "";
    setWaiting(true);
    try {
      const r = await sendJSON("POST", "/api/v1/chat", { message: question, conversation_id: conversation });
      conversation = r.conversation_id;
      saveConversation(conversation);
      setWaiting(false);
      list.append(messageNode({ role: "assistant", message: r.answer, context: r }));
    } catch (err) {
      setWaiting(false);
      const msg = err instanceof ApiError ? err.message : String(err);
      feedback.replaceChildren(h("div", { class: "form-message form-message-error", role: "alert", text: msg }));
      if (err instanceof ApiError && err.status === 503) {
        status = await getJSON("/api/v1/ai/status?refresh=true").catch(() => status);
        paintStatus();
      }
    }
    list.lastElementChild?.scrollIntoView({ block: "end", behavior: "smooth" });
    input.focus();
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); ask(input.value); }
  });
  const form = h("form", { class: "chat-form", onsubmit: (e) => { e.preventDefault(); ask(input.value); } },
    h("label", { for: "chat-input", class: "visually-hidden", text: "Mensagem" }), input, send);

  view.replaceChildren(
    h("div", { class: "page-head" },
      h("h1", { text: "Assistente" }),
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", text: "Nova conversa",
          onclick: () => { if (waiting) return; conversation = null; saveConversation(null); loadHistory(); input.focus(); } }))),
    h("section", { class: "card" },
      statusBox,
      h("p", { class: "muted small", text: "A IA roda neste computador e só lê dados do Sentinel. Ela não executa nada: pedidos para iniciar, parar ou reiniciar servidores aparecem em Aprovações e só acontecem se você aprovar." }),
      list, suggestions, feedback, form));
  paintStatus();
  await loadHistory();
  input.focus();

  const poll = setInterval(async () => {
    if (waiting) return;
    status = await getJSON("/api/v1/ai/status").catch(() => status);
    paintStatus();
  }, 30000);
  return { destroy: () => { clearInterval(poll); clearInterval(timer); } };
}
