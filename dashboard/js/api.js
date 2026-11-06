// Comunicação com o agente: REST com cookie de sessão e WebSocket com reconexão automática.

export class UnauthorizedError extends Error {}

export async function getJSON(path) {
  const res = await fetch(path, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (res.status === 401) throw new UnauthorizedError("Sessão ausente ou expirada");
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} em ${path}`);
  return res.json();
}

export async function logout() {
  await fetch("/api/v1/auth/logout", { method: "POST", credentials: "same-origin" });
}

// Reconecta com espera crescente (1s → 30s). Código 1008 = sessão inválida: não insiste.
export class LiveChannel {
  constructor({ onMessage, onState }) {
    this.onMessage = onMessage;
    this.onState = onState;
    this.delay = 1000;
    this.stopped = false;
    this.connect();
  }

  connect() {
    if (this.stopped) return;
    this.onState("connecting");
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
    this.ws = ws;
    ws.onopen = () => { this.delay = 1000; this.onState("open"); };
    ws.onmessage = (e) => {
      try { this.onMessage(JSON.parse(e.data)); }
      catch (err) { console.error("Mensagem inválida do servidor", err); }
    };
    ws.onclose = (e) => {
      if (this.stopped) return;
      if (e.code === 1008) { this.onState("unauthorized"); return; }
      this.onState("closed");
      setTimeout(() => this.connect(), this.delay);
      this.delay = Math.min(this.delay * 2, 30000);
    };
  }

  stop() {
    this.stopped = true;
    if (this.ws) this.ws.close();
  }
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// Erros de validação do servidor viram uma mensagem legível em português.
function describeError(detail) {
  if (Array.isArray(detail)) {
    return detail.map((d) => {
      const field = (d.loc || []).filter((x) => x !== "body").join(".");
      const msg = String(d.msg || "").replace(/^Value error, /, "");
      return field ? `${field}: ${msg}` : msg;
    }).join("\n");
  }
  return typeof detail === "string" ? detail : JSON.stringify(detail);
}

export async function sendJSON(method, path, body) {
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: { Accept: "application/json", "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401) throw new UnauthorizedError("Sessão ausente ou expirada");
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, describeError(data?.detail ?? res.statusText));
  return data;
}
