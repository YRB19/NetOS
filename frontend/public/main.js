import { makeApi } from "./api.js";
import { createApp } from "./app.js";
import { buildHash, parseHash } from "./format.js";

const root = document.getElementById("app");
const app = createApp({ root, api: makeApi(), setTitle: (t) => { document.title = t; } });

async function render(moveFocus) {
  await app.go(location.hash || "#/");
  if (moveFocus) document.getElementById("main")?.focus({ preventScroll: false }); // keyboard users land on new content
}
window.addEventListener("hashchange", () => render(true));

// Delegated UI glue (no inline handlers: CSP forbids them).
document.addEventListener("change", (e) => {
  const sel = e.target.closest("[data-run-select]");
  if (sel) location.hash = buildHash("/", { run: sel.value });
});
document.addEventListener("submit", (e) => {
  const f = e.target.closest("[data-filter-form]");
  if (!f) return;
  e.preventDefault();
  const params = Object.fromEntries(new FormData(f).entries());
  location.hash = buildHash(f.dataset.filterForm, params);
});
document.addEventListener("click", (e) => {
  const a = e.target.closest("[data-allow-unverified]");
  if (!a) return;
  e.preventDefault();
  const { path, params } = parseHash(location.hash);
  location.hash = buildHash(path, { ...params, allow_unverified: 1 });
});
// Command centre display-only controls. They show/hide already-loaded content; they never call the API or change data.
document.addEventListener("click", (e) => {
  const st = e.target.closest("[data-stage]");
  if (st) {
    e.preventDefault();
    const key = st.dataset.stage;
    document.querySelectorAll("[data-stage-panel]").forEach((p) => { p.hidden = p.dataset.stagePanel !== key; });
    document.querySelectorAll("[data-stage]").forEach((n) => {
      const on = n.dataset.stage === key; n.classList.toggle("is-selected", on);
      if (on) n.setAttribute("aria-current", "true"); else n.removeAttribute("aria-current");
    });
    return;
  }
  const fb = e.target.closest("[data-stream-filter]");
  if (fb) {
    const term = document.querySelector(".term"); if (!term) return;
    term.dataset.filter = fb.dataset.streamFilter;
    document.querySelectorAll("[data-stream-filter]").forEach((b) => b.setAttribute("aria-pressed", String(b === fb)));
  }
});
render(false);
