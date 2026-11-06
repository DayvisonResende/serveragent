// Janela para escolher arquivos/pastas do computador. O seletor nativo do navegador
// não revela o caminho completo, então navegamos pelas pastas via API (somente leitura).

import { getJSON } from "./api.js";
import * as fmt from "./format.js";
import { h } from "./ui.js";

const TITLES = {
  executable: "Escolher executável ou script (.exe, .bat, .cmd)",
  directory: "Escolher pasta",
  log: "Escolher arquivo de log",
};

/** Abre o seletor. Resolve com o caminho escolhido ou null se cancelado. */
export function pickPath({ kind = "executable", start = null } = {}) {
  return new Promise((resolve) => {
    const list = h("ul", { class: "picker-list", role: "listbox", "aria-label": "Conteúdo da pasta" });
    const crumb = h("div", { class: "picker-path" });
    const status = h("p", { class: "muted small" });
    const hidden = h("input", { type: "checkbox" });
    const chooseFolder = h("button", { type: "button", class: "btn btn-primary", hidden: kind !== "directory", text: "Selecionar esta pasta" });
    let current = null;

    const dialog = h("dialog", { class: "picker" },
      h("div", { class: "card-head" }, h("h2", { text: TITLES[kind] }),
        h("button", { type: "button", class: "btn btn-small", text: "Fechar", onclick: () => finish(null) })),
      crumb, list, status,
      h("div", { class: "actions" },
        h("label", { class: "check small" }, hidden, " Mostrar ocultos"),
        h("span", { class: "spacer" }),
        chooseFolder));

    function finish(value) {
      dialog.close();
      dialog.remove();
      resolve(value);
    }

    function row(label, detail, onOpen, icon, selectable = false) {
      const li = h("li", { role: "option", tabindex: 0, class: selectable ? "file" : "dir" },
        h("span", { class: "picker-icon", "aria-hidden": "true", text: icon }),
        h("span", { class: "picker-name", text: label }),
        h("span", { class: "muted small", text: detail || "" }));
      li.addEventListener("click", onOpen);
      li.addEventListener("keydown", (e) => { if (e.key === "Enter") onOpen(); });
      return li;
    }

    async function load(path) {
      status.textContent = "Carregando…";
      try {
        const q = new URLSearchParams({ kind, show_hidden: hidden.checked });
        if (path) q.set("path", path);
        const data = await getJSON(`/api/v1/files/browse?${q}`);
        current = data.path;
        chooseFolder.disabled = !current;
        crumb.textContent = current || "Unidades e atalhos";
        const items = [];
        if (!current) {
          for (const r of data.roots) items.push(row(r.label, "unidade", () => load(r.path), "▣"));
          for (const s of data.shortcuts) items.push(row(s.label, s.path, () => load(s.path), "★"));
        } else {
          items.push(row("..", "voltar", () => load(data.parent), "↑"));
          for (const e of data.entries) {
            if (e.type === "directory") items.push(row(e.name, "", () => load(e.path), "▸"));
            else items.push(row(e.name, `${fmt.bytes(e.size)} · ${fmt.dateTime(e.modified)}`, () => finish(e.path), "•", true));
          }
        }
        list.replaceChildren(...items);
        const files = data.entries.filter((e) => e.type === "file").length;
        status.textContent = current
          ? `${files} arquivo(s) compatível(is)${data.truncated ? " · lista cortada (pasta muito grande)" : ""}`
          : "Escolha uma unidade ou atalho.";
      } catch (err) {
        status.textContent = `Não foi possível abrir: ${err.message}`;
      }
    }

    hidden.addEventListener("change", () => load(current));
    chooseFolder.addEventListener("click", () => current && finish(current));
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); finish(null); });
    document.body.append(dialog);
    dialog.showModal();
    load(start);
  });
}

/** Pasta que contém o arquivo (Windows ou POSIX). */
export function dirname(path) {
  const i = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return i > 0 ? path.slice(0, i) : path;
}

export function basename(path) {
  const i = Math.max(path.lastIndexOf("\\"), path.lastIndexOf("/"));
  return path.slice(i + 1);
}
