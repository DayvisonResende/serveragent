// Armazenamento (PRD 8.7): análise → recomendação → aprovação → execução.
// Executar, restaurar e excluir passam por /api/v1/actions (catálogo fechado, auditado).

import { getJSON, sendJSON, ApiError } from "./api.js";
import * as fmt from "./format.js";
import { h, card, meter } from "./ui.js";
import { pickPath } from "./filepicker.js";

const CATEGORY = {
  temp: ["Temporários antigos", "Arquivos na pasta de temporários sem uso há dias."],
  old_log: ["Logs antigos", "Registros (.log) que ninguém altera há semanas."],
  duplicate: ["Duplicados", "Conteúdo idêntico; a cópia mais antiga de cada grupo fica."],
  large: ["Arquivos grandes", "Os maiores arquivos encontrados. Fora das pastas autorizadas, só informativo."],
};
const REPORT_STATUS = {
  proposed: "Aguardando", completed: "Concluída", partial: "Concluída em parte", failed: "Nada movido", discarded: "Descartada",
};

const when = (epoch) => fmt.dateTime(new Date(epoch * 1000).toISOString());
const took = (s) => (s < 60 ? `${Math.max(1, Math.round(s))} s` : fmt.duration(s));

// Nome do arquivo em destaque e a pasta embaixo: o fim do caminho é o que importa.
function pathCell(path) {
  const cut = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return h("td", { class: "file-cell", title: path },
    h("div", { class: "file-name", text: path.slice(cut + 1) }),
    h("div", { class: "file-dir", text: path.slice(0, cut + 1) }));
}

function note(text, kind = "info") {
  return h("div", { class: `form-message form-message-${kind}`, role: kind === "error" ? "alert" : "status", text });
}

async function act(operation, targetId) {
  return sendJSON("POST", "/api/v1/actions", { operation, target_id: targetId });
}

export async function storagePage(view) {
  const feedback = h("div", { "aria-live": "polite" });
  const body = h("div", { class: "stack" });
  let category = "temp";
  let poll = null;

  const show = (text, kind) => feedback.replaceChildren(note(text, kind));
  const fail = (err) => show(err instanceof ApiError ? err.message : String(err), "error");

  async function load() {
    const [status, disks] = await Promise.all([getJSON("/api/v1/storage/status"), getJSON("/api/v1/system/disks")]);
    const [findings, quarantine, reports] = await Promise.all([
      getJSON(`/api/v1/storage/findings?category=${category}&limit=1000`),
      getJSON("/api/v1/storage/quarantine"),
      getJSON("/api/v1/storage/reports?limit=20"),
    ]);
    body.replaceChildren(
      analysisCard(status),
      disksCard(disks, status),
      findingsCard(status, findings),
      quarantineCard(status, quarantine.items),
      reportsCard(reports.reports),
      authorizedCard(status));
    clearInterval(poll);
    if (status.running) poll = setInterval(refreshProgress, 2000);
  }

  // ------------------------------------------------------------ análise

  function analysisCard(status) {
    const last = status.last_completed;
    const s = last?.summary;
    const fullDisk = h("input", { type: "checkbox", id: "full-disk", checked: true });
    const start = async () => {
      try {
        await sendJSON("POST", "/api/v1/storage/analyze", { full_disk: fullDisk.checked });
        show("Análise iniciada. Você pode sair desta página; ela continua em segundo plano.");
        await load();
      } catch (err) { fail(err); }
    };
    const cancel = async () => { await sendJSON("POST", "/api/v1/storage/analyze/cancel").catch(fail); };
    const failedLast = status.last && status.last.status !== "completed" && status.last.status !== "running";
    return card("Análise",
      status.running
        ? h("div", {}, h("p", { id: "progress", class: "secondary", text: progressText(status.progress) }),
          h("div", { class: "actions" }, h("button", { class: "btn", type: "button", text: "Cancelar análise", onclick: cancel })))
        : h("div", {},
          h("p", { class: "secondary", text: last
            ? `Última análise: ${fmt.dateTime(last.finished_at)} · ${fmt.number(s.files)} arquivos em ${took(s.seconds)}`
            : "Nenhuma análise ainda." }),
          failedLast ? h("p", { class: "muted small", text: `A análise de ${fmt.dateTime(status.last.started_at)} não terminou (${status.last.error || status.last.status}).` }) : null,
          h("div", { class: "actions" },
            h("button", { class: "btn btn-primary", type: "button", text: "Analisar agora", onclick: start }),
            h("label", { class: "check" }, fullDisk, "Medir também as pastas de todo o disco (só leitura, leva alguns minutos)"))),
      s ? summaryTiles(s) : null,
      s?.warnings?.length ? h("ul", { class: "muted small" }, ...s.warnings.map((w) => h("li", { text: w }))) : null);
  }

  function progressText(p) {
    if (!p) return "Analisando…";
    const tail = p.current ? ` · ${p.current}` : "";
    return `Analisando… ${fmt.number(p.files)} arquivos, ${fmt.bytes(p.bytes)} lidos${tail}`;
  }

  async function refreshProgress() {
    try {
      const status = await getJSON("/api/v1/storage/status");
      if (!status.running) { clearInterval(poll); await load(); show("Análise concluída.", "ok"); return; }
      const p = document.getElementById("progress");
      if (p) p.textContent = progressText(status.progress);
    } catch { /* tenta de novo no próximo ciclo */ }
  }

  function summaryTiles(s) {
    const cats = s.categories || {};
    const tile = (label, value, detail) => h("div", { class: "card tile" },
      h("div", { class: "muted small", text: label }), h("div", { class: "value num", text: value }), h("div", { class: "detail", text: detail }));
    return h("div", { class: "grid tiles section-gap" },
      tile("Pode ser limpo (estimativa)", fmt.bytes(s.recoverable_bytes), "nas pastas autorizadas; não é promessa"),
      ...["temp", "old_log", "duplicate"].map((k) => tile(CATEGORY[k][0], fmt.bytes(cats[k]?.cleanable_bytes || 0),
        `${fmt.number(cats[k]?.cleanable_files || 0)} arquivo(s)`)),
      tile(CATEGORY.large[0], fmt.number(cats.large?.files || 0), `${fmt.bytes(cats.large?.bytes || 0)} no total`));
  }

  // ------------------------------------------------------------ discos e pastas

  function disksCard(disks, status) {
    const s = status.last_completed?.summary;
    const top = (s?.top_dirs || []).slice(0, 15);
    const biggest = top[0]?.bytes || 1;
    const growth = s?.growth || [];
    return card("Discos e pastas que mais ocupam",
      h("div", { class: "grid tiles" }, ...(disks.disks || []).map((d) => h("div", {},
        h("div", { class: "title-row" }, h("strong", { text: d.mountpoint }), h("span", { class: "muted small", text: `${fmt.bytes(d.free)} livres de ${fmt.bytes(d.total)}` })),
        meter(d.percent)))),
      top.length
        ? h("div", { class: "table-wrap section-gap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", { text: "Pasta" }), h("th", { text: "Tamanho" }), h("th", { text: "" }))),
          h("tbody", {}, ...top.map((d) => h("tr", {},
            h("td", { class: "path", title: d.path, text: d.path }),
            h("td", { class: "num", text: fmt.bytes(d.bytes) }),
            h("td", { class: "bar-cell" }, meter((d.bytes / biggest) * 100)))))))
        : h("p", { class: "muted", text: "Rode uma análise com \"todo o disco\" marcado para ver as pastas que mais ocupam." }),
      growth.length ? h("div", { class: "section-gap" }, h("h3", { text: "Cresceram desde a análise anterior" }),
        h("ul", { class: "small" }, ...growth.map((g) => h("li", {}, h("span", { class: "mono", text: g.path }), ` +${fmt.bytes(g.delta_bytes)} desde ${fmt.dateTime(g.since)}`)))) : null);
  }

  // ------------------------------------------------------------ achados e limpeza

  function findingsCard(status, data) {
    const rows = data.findings;
    const selected = new Set();
    const total = () => rows.filter((r) => selected.has(r.id)).reduce((a, r) => a + r.size_bytes, 0);
    const go = h("button", { class: "btn btn-primary", type: "button", disabled: true });
    const paint = () => {
      go.disabled = !selected.size;
      go.textContent = selected.size ? `Mover ${selected.size} para a quarentena (${fmt.bytes(total())})` : "Selecione arquivos";
    };
    const cleanable = rows.filter((r) => r.cleanable);
    const all = h("input", { type: "checkbox", "aria-label": "Selecionar todos", disabled: !cleanable.length });
    const boxes = new Map();
    all.addEventListener("change", () => {
      for (const r of cleanable) { all.checked ? selected.add(r.id) : selected.delete(r.id); boxes.get(r.id).checked = all.checked; }
      paint();
    });
    const row = (r) => {
      const box = h("input", { type: "checkbox", "aria-label": `Selecionar ${r.path}`, disabled: !r.cleanable });
      boxes.set(r.id, box);
      box.addEventListener("change", () => { box.checked ? selected.add(r.id) : selected.delete(r.id); paint(); });
      return h("tr", { class: r.keep ? "row-keep" : null },
        h("td", {}, box),
        pathCell(r.path),
        h("td", { class: "num", text: fmt.bytes(r.size_bytes) }),
        h("td", { class: "num", text: when(r.modified_at) }),
        h("td", { class: "muted small", text: r.note || (r.cleanable ? "" : "não limpável") }));
    };
    go.addEventListener("click", async () => {
      const ids = [...selected];
      try {
        const plan = await sendJSON("POST", "/api/v1/storage/plans", { finding_ids: ids });
        const ok = window.confirm(`Mover ${plan.files_found} arquivo(s) (${fmt.bytes(plan.bytes_recoverable)}) para a quarentena?\n\n`
          + "Eles podem ser restaurados depois. No mesmo disco, o espaço só é liberado quando você excluir definitivamente da quarentena "
          + `(ou automaticamente após ${status.quarantine.retention_days} dias).`);
        if (!ok) { await sendJSON("POST", `/api/v1/storage/plans/${plan.id}/discard`); return; }
        show("Movendo…");
        const r = await act("cleanup_quarantine", plan.id);
        await load();
        show(r.result?.message || r.error_message || r.status, r.status === "failed" ? "error" : "ok");
      } catch (err) { fail(err); }
    });
    paint();
    const tabs = h("div", { class: "segmented", role: "group", "aria-label": "Categoria" },
      ...Object.entries(CATEGORY).map(([k, [label]]) => h("button", { type: "button", "aria-pressed": String(k === category), text: label,
        onclick: () => { category = k; load().catch(fail); } })));
    return card("Arquivos encontrados",
      h("div", { class: "actions" }, tabs),
      h("p", { class: "muted small", text: CATEGORY[category][1] }),
      rows.length
        ? h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, all), h("th", { text: "Arquivo" }), h("th", { text: "Tamanho" }), h("th", { text: "Modificado" }), h("th", { text: "" }))),
          h("tbody", {}, ...rows.map(row))))
        : h("p", { class: "muted", text: data.analysis_id ? "Nada nesta categoria." : "Rode uma análise para ver sugestões." }),
      data.gone ? h("p", { class: "muted small", text: `${data.gone} arquivo(s) desta análise já não estão no lugar (movidos ou apagados) e foram omitidos.` }) : null,
      h("div", { class: "actions" }, go));
  }

  // ------------------------------------------------------------ quarentena e relatórios

  function quarantineCard(status, items) {
    const q = status.quarantine;
    const groups = new Map();
    for (const it of items) { if (!groups.has(it.report_id)) groups.set(it.report_id, []); groups.get(it.report_id).push(it); }
    const restore = async (it) => {
      if (!window.confirm(`Restaurar para ${it.original_path}?`)) return;
      try { const r = await act("quarantine_restore", it.id); await load(); show(r.result?.message || r.status, r.status === "failed" ? "error" : "ok"); }
      catch (err) { fail(err); }
    };
    const purge = async (reportId, list) => {
      const name = `limpeza #${reportId}`;
      const size = fmt.bytes(list.reduce((a, i) => a + i.size_bytes, 0));
      const typed = window.prompt(`Excluir DEFINITIVAMENTE ${list.length} arquivo(s) (${size})? Não há como desfazer.\n\nPara confirmar, digite: ${name}`);
      if (typed === null) return;
      if (typed.trim() !== name) { show(`Confirmação diferente de "${name}". Nada foi excluído.`, "error"); return; }
      try {
        const pending = await act("quarantine_delete", reportId);
        const r = await sendJSON("POST", `/api/v1/approvals/${pending.id}/approve`, { confirmation: typed });
        await load();
        show(r.result?.message || r.status, r.status === "failed" ? "error" : "ok");
      } catch (err) { fail(err); await load().catch(() => {}); }
    };
    return card("Quarentena",
      h("p", { class: "secondary", text: `${fmt.number(q.items)} arquivo(s), ${fmt.bytes(q.bytes)} de ${fmt.bytes(q.max_bytes)}. `
        + `Itens com mais de ${q.retention_days} dias são excluídos automaticamente.` }),
      meter((q.bytes / q.max_bytes) * 100),
      groups.size ? h("div", { class: "section-gap" }, ...[...groups].map(([rid, list]) => h("details", { class: "quarantine-group" },
        h("summary", {}, `Limpeza #${rid} — ${list.length} arquivo(s), ${fmt.bytes(list.reduce((a, i) => a + i.size_bytes, 0))}`),
        h("div", { class: "table-wrap" }, h("table", {}, h("tbody", {}, ...list.map((it) => h("tr", {},
          pathCell(it.original_path),
          h("td", { class: "num", text: fmt.bytes(it.size_bytes) }),
          h("td", { class: "num", text: fmt.dateTime(it.quarantined_at) }),
          h("td", {}, h("button", { class: "btn btn-small", type: "button", text: "Restaurar", onclick: () => restore(it) }))))))),
        h("div", { class: "actions" }, h("button", { class: "btn btn-small btn-danger", type: "button", text: "Excluir definitivamente", onclick: () => purge(rid, list) })))))
        : h("p", { class: "muted", text: "A quarentena está vazia." }));
  }

  function reportsCard(reports) {
    return card("Relatórios de limpeza", reports.length
      ? h("div", { class: "table-wrap" }, h("table", {},
        h("thead", {}, h("tr", {}, ...["#", "Data", "Pedido por", "Arquivos", "Tamanho", "Movidos", "Excluídos", "Situação"].map((t) => h("th", { text: t })))),
        h("tbody", {}, ...reports.map((r) => h("tr", {},
          h("td", { class: "num", text: r.id }), h("td", { class: "num", text: fmt.dateTime(r.created_at) }),
          h("td", { text: r.requested_by }), h("td", { class: "num", text: fmt.number(r.files_found) }),
          h("td", { class: "num", text: fmt.bytes(r.bytes_recoverable) }), h("td", { class: "num", text: fmt.number(r.files_moved) }),
          h("td", { class: "num", text: fmt.number(r.files_deleted) }), h("td", { text: REPORT_STATUS[r.status] || r.status }))))))
      : h("p", { class: "muted", text: "Nenhuma limpeza ainda." }));
  }

  // ------------------------------------------------------------ pastas autorizadas

  function authorizedCard(status) {
    let folders = status.authorized.map((a) => a.path);
    const list = h("ul", { class: "server-list" });
    const paint = () => list.replaceChildren(...folders.map((f) => h("li", {},
      h("span", { class: "mono", text: f }),
      h("button", { class: "btn btn-small", type: "button", text: "Remover", onclick: () => { folders = folders.filter((x) => x !== f); paint(); } }))));
    paint();
    const add = async () => {
      const path = await pickPath({ kind: "directory" });
      if (path && !folders.includes(path)) { folders = [...folders, path]; paint(); }
    };
    const save = async () => {
      try { await sendJSON("PUT", "/api/v1/storage/authorized", { folders }); await load(); show("Pastas autorizadas salvas.", "ok"); }
      catch (err) { fail(err); }
    };
    return card("Pastas autorizadas para limpeza",
      h("p", { class: "muted small", text: "Só arquivos destas pastas podem ir para a quarentena. Mesmo aqui dentro, nunca são tocados: "
        + "Windows, programas instalados, pastas Inicializar, o próprio Sentinel, pastas dos servidores cadastrados, arquivos de sistema e bancos de dados."
        + (status.authorized_is_default ? " (Lista padrão: temporários e Downloads.)" : "") }),
      list,
      h("div", { class: "actions" },
        h("button", { class: "btn", type: "button", text: "Adicionar pasta", onclick: add }),
        h("button", { class: "btn btn-primary", type: "button", text: "Salvar", onclick: save })));
  }

  view.replaceChildren(h("div", { class: "page-head" }, h("h1", { text: "Armazenamento" })), feedback, body);
  await load();
  return { destroy: () => clearInterval(poll) };
}
