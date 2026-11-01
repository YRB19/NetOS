// Pure formatting helpers. No DOM access. Unknown values are NEVER rendered as zero.
export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const unknown = (word = "Unknown") => `<span class="unknown" title="Not recorded in the persisted artifacts">${esc(word)}</span>`;

/** Render a possibly-missing scalar. null/undefined/"" => Unknown (never 0). */
export function val(v, { word = "Unknown", code = false } = {}) {
  if (v === null || v === undefined || v === "") return unknown(word);
  if (typeof v === "object") return `<code>${esc(JSON.stringify(v))}</code>`;
  return code ? `<code>${esc(v)}</code>` : esc(v);
}

export const ts = (v) => (v ? `<time datetime="${esc(v)}">${esc(String(v).replace("T", " ").replace("+00:00", "Z"))}</time>` : unknown());

export function badge(text, kind = "neutral") {
  return `<span class="badge badge-${esc(kind)}">${esc(text)}</span>`;
}

export function evidenceBadge(ev) {
  if (!ev) return badge("Evidence unknown", "warn");
  const kind = ev.synthetic === true ? "synthetic" : ev.raw ? "neutral" : "warn";
  return badge(`${ev.synthetic ? "SYNTHETIC \u2014 " : ""}${ev.label}`, kind);
}

const STATUS_KIND = { FINALIZED: "ok", COMPLETED: "ok", VERIFIED: "ok", OK: "ok", INCOMPLETE: "bad", FAILED: "bad", BLOCKED: "bad",
  UNCERTAIN_SUBMISSION: "bad", RECONCILIATION_BLOCKED: "bad", RISK_VETO: "warn", HOLD: "neutral", NO_TRADE: "neutral",
  NOT_RECORDED: "warn", UNAVAILABLE: "warn", UNKNOWN: "warn" };
export const statusBadge = (s) => (s === null || s === undefined ? badge("Unknown", "warn") : badge(s, STATUS_KIND[s] || "neutral"));

export const warnings = (list) => !list || !list.length ? "" :
  `<ul class="warnlist" aria-label="Warnings">${list.map((w) => `<li>${badge(w.code, "warn")} ${esc(w.message)}</li>`).join("")}</ul>`;

export function table({ caption, columns, rows, empty = "No records.", cls = "" }) {
  if (!rows || rows.length === 0) return `<p class="empty" role="status">${esc(empty)}</p>`;
  const head = columns.map((c) => `<th scope="col">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr>${columns.map((c) => `<td data-label="${esc(c.label)}">${c.render(r)}</td>`).join("")}</tr>`).join("");
  return `<table class="${esc(cls)}"><caption>${esc(caption)}</caption><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

export function kv(pairs) {
  return `<dl class="kv">${pairs.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${v}</dd></div>`).join("")}</dl>`;
}

/** Build a hash route: buildHash("/decisions", {run:"x", page:2}) => "#/decisions?page=2&run=x" (sorted, empties dropped). */
export function buildHash(path, params = {}) {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
    .sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
  return `#${path}${q ? "?" + q : ""}`;
}

export function parseHash(hash) {
  const raw = (hash || "#/").replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  const params = {};
  for (const part of query.split("&").filter(Boolean)) {
    const [k, v = ""] = part.split("=");
    params[decodeURIComponent(k)] = decodeURIComponent(v);
  }
  return { path: path || "/", segments: path.split("/").filter(Boolean).map(decodeURIComponent), params };
}

// ---- command-centre helpers (additive). Unknown values are never converted to zero.
/** Finite number or null. null/undefined/"" and non-numeric strings => null (never 0). */
export function toNum(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}
/** Group-formatted fixed-decimal string, or null when the value is not a recorded finite number. */
export function num(v, { dp = 2 } = {}) {
  const n = toNum(v);
  return n === null ? null : n.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
}
/** HTML for a numeric value; unknown => an explicit "Unavailable" marker (never 0). */
export function fmtNum(v, { dp = 2, word = "Unavailable", suffix = "" } = {}) {
  const s = num(v, { dp });
  return s === null ? unknown(word) : esc(s + suffix);
}
/** Direction of a recorded value: "up" | "down" | "flat" | null (unknown). Used for green/red only when established. */
export function dir(v) {
  const n = toNum(v);
  return n === null ? null : n > 0 ? "up" : n < 0 ? "down" : "flat";
}
