// Formatação em pt-BR. Valores ausentes viram "—" (nunca um número inventado).

const nf1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const timeFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit" });
const timeSecFmt = new Intl.DateTimeFormat("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const dateTimeFmt = new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });

export const DASH = "—";
const missing = (v) => v === null || v === undefined || Number.isNaN(v);

export function percent(v) {
  return missing(v) ? DASH : `${nf1.format(v)}%`;
}

export function bytes(v) {
  if (missing(v)) return DASH;
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let n = v;
  while (Math.abs(n) >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${(i === 0 ? nf0 : nf1).format(n)} ${units[i]}`;
}

// Rede em bits por segundo — a unidade usada pelos provedores (ex.: "300 Mbps").
export function bitrate(bytesPerSecond) {
  if (missing(bytesPerSecond)) return DASH;
  let n = bytesPerSecond * 8;
  const units = ["bit/s", "kbit/s", "Mbit/s", "Gbit/s"];
  let i = 0;
  while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
  return `${(n >= 100 || i === 0 ? nf0 : nf1).format(n)} ${units[i]}`;
}

export function compactBitrate(bytesPerSecond) {
  return bitrate(bytesPerSecond).replace(/\/s$/, "");
}

export function duration(seconds) {
  if (missing(seconds)) return DASH;
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}min`;
  return `${m}min`;
}

export function ago(seconds) {
  if (missing(seconds)) return DASH;
  if (seconds < 60) return `há ${Math.round(seconds)}s`;
  return `há ${duration(seconds)}`;
}

export const time = (epochSeconds) => timeFmt.format(new Date(epochSeconds * 1000));
export const timeWithSeconds = (epochSeconds) => timeSecFmt.format(new Date(epochSeconds * 1000));
export const dateTime = (iso) => (iso ? dateTimeFmt.format(new Date(iso)) : DASH);
export const number = (v) => (missing(v) ? DASH : nf0.format(v));

export const SEVERITY = {
  info: { label: "Informativo", icon: "i" },
  warning: { label: "Atenção", icon: "!" },
  high: { label: "Alto", icon: "▲" },
  critical: { label: "Crítico", icon: "✕" },
};
