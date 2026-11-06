// Configurações (PRD 21): notificações no Telegram.
// O token só é enviado ao Sentinel — ele nunca volta para o navegador.

import { getJSON, sendJSON, ApiError } from "./api.js";
import * as fmt from "./format.js";
import { h } from "./ui.js";

function note(text, kind = "info") {
  return h("div", { class: `form-message form-message-${kind}`, role: kind === "error" ? "alert" : "status", text });
}

export async function settingsPage(view) {
  let data = await getJSON("/api/v1/settings/notifications");
  const feedback = h("div", { "aria-live": "polite" });
  const statusLine = h("p", { class: "small" });

  const token = h("input", { id: "n-token", type: "password", autocomplete: "off", maxlength: 200 });
  const chatSelect = h("select", { id: "n-chat" });
  const minSeverity = h("select", { id: "n-sev" },
    ...Object.entries({ info: "Tudo (inclusive informativos)", warning: "Atenção ou mais grave", high: "Alto ou crítico", critical: "Somente crítico" })
      .map(([v, t]) => h("option", { value: v, text: t })));
  const recoveries = h("input", { type: "checkbox", id: "n-rec" });
  const enabled = h("input", { type: "checkbox", id: "n-enabled" });

  const setChats = (chats, selected) => {
    const opts = chats.map((c) => h("option", { value: c.id, text: `${c.name} (${c.type === "private" ? "conversa" : c.type})` }));
    if (selected != null && !chats.some((c) => c.id === selected)) opts.unshift(h("option", { value: selected, text: `Chat ${selected}` }));
    chatSelect.replaceChildren(h("option", { value: "", text: "— escolha —" }), ...opts);
    chatSelect.value = selected ?? "";
  };

  const paint = () => {
    const c = data.config;
    token.value = "";
    token.placeholder = data.token.configured ? "Token configurado — deixe vazio para manter" : "123456789:ABC…";
    setChats([], c.telegram_chat_id);
    minSeverity.value = c.min_severity;
    recoveries.checked = c.include_recoveries;
    enabled.checked = c.enabled;
    const st = data.status;
    const protection = { dpapi: "cifrado com a proteção do Windows (DPAPI)", none: "SEM proteção (ambiente de desenvolvimento)" }[data.token.protection];
    statusLine.replaceChildren(
      h("span", { class: `pill ${st.active ? "pill-good" : "pill-muted"}`, text: st.active ? "Ativo" : "Desativado" }), " ",
      h("span", { class: "muted", text: [
        data.token.configured ? `Token ${protection}` : "Nenhum token configurado",
        `${st.sent} enviada(s)`,
        st.last_sent_at ? `última ${fmt.dateTime(st.last_sent_at)}` : null,
        st.last_error ? `último erro: ${st.last_error}` : null,
      ].filter(Boolean).join(" · ") }));
  };

  const run = async (label, fn) => {
    feedback.replaceChildren(note(`${label}…`));
    try { await fn(); } catch (err) { feedback.replaceChildren(note(err instanceof ApiError ? err.message : String(err), "error")); }
  };

  const detect = () => run("Procurando conversas", async () => {
    const r = await sendJSON("POST", "/api/v1/settings/notifications/detect-chats", { telegram_token: token.value.trim() || null });
    setChats(r.chats, r.chats[0]?.id ?? null);
    feedback.replaceChildren(note(r.chats.length
      ? `Bot ${r.bot}: ${r.chats.length} conversa(s) encontrada(s). Escolha a sua e salve.`
      : `Bot ${r.bot} encontrado, mas ninguém escreveu para ele ainda. Abra o bot no Telegram, envie "oi" e tente de novo.`, r.chats.length ? "ok" : "info"));
  });

  const save = (extra = {}) => run("Salvando", async () => {
    const body = {
      enabled: enabled.checked,
      telegram_chat_id: chatSelect.value ? Number(chatSelect.value) : null,
      min_severity: minSeverity.value,
      include_recoveries: recoveries.checked,
      telegram_token: token.value.trim() || null,
      ...extra,
    };
    data = await sendJSON("PUT", "/api/v1/settings/notifications", body);
    paint();
    feedback.replaceChildren(note("Configuração salva.", "ok"));
  });

  const test = () => run("Enviando teste", async () => {
    const r = await sendJSON("POST", "/api/v1/settings/notifications/test");
    feedback.replaceChildren(note(r.message, r.ok ? "ok" : "error"));
  });

  view.replaceChildren(
    h("div", { class: "page-head" }, h("h1", { text: "Configurações" })),
    h("section", { class: "card" },
      h("div", { class: "card-head" }, h("h2", { text: "Notificações no Telegram" }), statusLine),
      h("p", { class: "secondary", text: "Receba no celular quando um servidor cair, voltar, ou quando algo exigir atenção — sem precisar abrir o dashboard." }),
      h("ol", { class: "steps" },
        h("li", {}, "No Telegram, abra ", h("strong", { text: "@BotFather" }), ", envie ", h("code", { text: "/newbot" }), " e siga as instruções. Ele mostra um token parecido com ", h("code", { text: "123456789:ABC…" }), "."),
        h("li", { text: "Cole o token abaixo." }),
        h("li", { text: "Abra o seu bot no Telegram e envie qualquer mensagem (por exemplo, “oi”)." }),
        h("li", { text: "Clique em “Procurar conversas”, escolha o seu nome, marque “Ativar” e salve." }),
        h("li", { text: "Use “Enviar teste” para conferir." })),
      h("div", { class: "form-grid" },
        h("div", { class: "form-field form-wide" },
          h("label", { for: "n-token", text: "Token do bot" }),
          h("div", { class: "input-row" }, token,
            h("button", { type: "button", class: "btn", text: "Procurar conversas", onclick: detect })),
          h("small", { class: "muted", text: "Guardado cifrado no computador. Nunca é exibido de volta nem registrado em logs." })),
        h("div", { class: "form-field" }, h("label", { for: "n-chat", text: "Enviar para" }), chatSelect),
        h("div", { class: "form-field" }, h("label", { for: "n-sev", text: "Avisar a partir de" }), minSeverity),
        h("label", { class: "check form-wide" }, recoveries, " Avisar também quando um servidor voltar a funcionar"),
        h("label", { class: "check form-wide" }, enabled, " Ativar notificações"),
        h("div", { class: "actions form-wide" },
          h("button", { type: "button", class: "btn btn-primary", text: "Salvar", onclick: () => save() }),
          h("button", { type: "button", class: "btn", text: "Enviar teste", onclick: test }),
          h("button", { type: "button", class: "btn btn-danger", text: "Remover token", onclick: () => {
            if (window.confirm("Remover o token do bot? As notificações serão desativadas.")) save({ telegram_token: "", enabled: false });
          } }))),
      feedback,
      h("p", { class: "muted small", text: "As mensagens passam pelos servidores do Telegram: contêm nomes de servidores e descrições de alertas — nunca senhas ou conteúdo de logs." })),
  );
  paint();
  return {};
}
