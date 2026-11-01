// Read-only API client: GET only. There is deliberately no code path here that sends any other HTTP method.
export class ApiFailure extends Error {
  constructor(kind, code, message, status) { super(message); this.kind = kind; this.code = code; this.status = status; }
}

export function makeApi(fetchFn = globalThis.fetch.bind(globalThis)) {
  async function get(path, params = {}) {
    const qs = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&");
    let res;
    try {
      res = await fetchFn(`/api${path}${qs ? "?" + qs : ""}`, { method: "GET", headers: { Accept: "application/json" } });
    } catch (e) {
      throw new ApiFailure("network", "SERVER_UNREACHABLE", "The console server could not be reached.", 0);
    }
    let body = null;
    try { body = await res.json(); } catch { /* non-JSON error body */ }
    if (!res.ok) {
      const err = body && body.error ? body.error : { code: "HTTP_" + res.status, message: "Request failed" };
      throw new ApiFailure("api", err.code, err.message, res.status);
    }
    return body;
  }
  return { get, exportUrl: (kind, params) => `/api/export/${encodeURIComponent(kind)}?` + Object.entries(params).filter(([, v]) => v).map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`).join("&") };
}
