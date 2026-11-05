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
