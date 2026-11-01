import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { ApiFailure } from "../public/api.js";

export const SNAP = JSON.parse(readFileSync(fileURLToPath(new URL("./fixtures/snapshot.json", import.meta.url)), "utf8"));
export const META = SNAP._meta;
const k = (path, params = {}) => {
  const q = Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "").sort(([a], [b]) => (a < b ? -1 : 1)).map(([a, v]) => `${a}=${v}`).join("&");
  return q ? `${path}?${q}` : path;
};
/** Fake read-only API backed by recorded real responses. Records every call so tests can assert GET-only reads. */
export function snapApi(overrides = {}) {
  const calls = [];
  return { calls, async get(path, params = {}) {
    calls.push(k(path, params));
    if (overrides[path]) { const r = overrides[path]; if (r instanceof Error) throw r; return r; }
    const hit = SNAP[k(path, params)];
    if (!hit) throw new ApiFailure("api", "NOT_FOUND", `no snapshot for ${k(path, params)}`, 404);
    return hit;
  } };
}
export const fakeRoot = () => ({ innerHTML: "" });
export const text = (html) => html.replace(/<[^>]+>/g, " ").replace(/&[a-z#0-9]+;/g, " ").replace(/\s+/g, " ");
