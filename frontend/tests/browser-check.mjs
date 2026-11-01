// Optional real-browser check (needs Playwright + Chromium). Usage: node tests/browser-check.mjs <artifact-root> [port]
// Starts the read-only server, loads real pages at 1440/768/360px, and asserts: no console errors, no horizontal
// scroll, keyboard reachability, filter + navigation work, and that no non-GET request is ever issued.
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { setTimeout as sleep } from "node:timers/promises";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const root = process.argv[2], port = Number(process.argv[3] || 8791);
const srv = spawn("python3", ["-m", "console_api", "--root", root, "--port", String(port)], { stdio: "ignore", cwd: new URL("../..", import.meta.url).pathname });
let failures = 0; const ok = (c, m) => { console.log(`${c ? "PASS" : "FAIL"} ${m}`); if (!c) failures++; };
try {
  await sleep(1500);
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const base = `http://127.0.0.1:${port}/`;
  for (const [w, h] of [[1440, 900], [768, 1024], [360, 740]]) {
    const ctx = await browser.newContext({ viewport: { width: w, height: h } }); const page = await ctx.newPage();
    const errors = [], methods = new Set();
    page.on("console", (m) => m.type() === "error" && errors.push(m.text())); page.on("pageerror", (e) => errors.push(String(e)));
    page.on("request", (r) => methods.add(r.method()));
    await page.goto(base); await page.waitForSelector("h2");
    const runs = await (await page.request.get(base + "api/runs?limit=50")).json();
    const pick = (t) => runs.items.find((r) => r.run_type === t) || runs.items[0];
    const pipe = runs.items.find((r) => r.evidence.synthetic && r.journal.present && r.journal.decisions > 100);
    const routes = ["#/", "#/runs", `#/run/${pipe.run_id}`, `#/decisions?run=${pipe.run_id}`, `#/risk?run=${pipe.run_id}`, `#/orders?run=${pipe.run_id}`, "#/research", `#/health?run=${pipe.run_id}`];
    for (const r of routes) {
      await page.goto(base + r); await page.waitForSelector("main h2"); await page.waitForFunction(() => !document.querySelector(".state[role=status]") || document.querySelector("main h2"));
      const m = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth, demo: !!document.querySelector(".banner-demo") }));
      ok(m.sw <= m.iw + 1, `${w}px no horizontal scroll ${r.slice(0, 28)} (scrollWidth ${m.sw})`); ok(m.demo, `${w}px demo banner ${r.slice(0, 20)}`);
    }
    // navigation: pick a decision from the list and open it
    await page.goto(base + `#/decisions?run=${pipe.run_id}&tag=NO_TRADE`); await page.waitForSelector("table td a");
    await page.locator("table td a").first().click(); await page.waitForSelector(".timeline");
    ok((await page.locator(".stage").count()) === 11, `${w}px decision timeline has 11 stages`);
    // filter form
    await page.goto(base + `#/decisions?run=${pipe.run_id}`); await page.waitForSelector("form.filters");
    await page.selectOption("select[name=tag]", "HOLD"); await page.click("form.filters button");
    await page.waitForFunction(() => location.hash.includes("tag=HOLD")); ok(true, `${w}px filter updates route`);
    // keyboard: Tab reaches skip link then nav
    await page.goto(base); await page.waitForSelector("h2"); await page.keyboard.press("Tab");
    ok((await page.evaluate(() => document.activeElement?.className)) === "skip", `${w}px first Tab focuses skip link`);
    ok(errors.length === 0, `${w}px no console errors ${errors.slice(0, 2).join("|")}`);
    ok([...methods].every((m) => m === "GET"), `${w}px only GET requests issued (${[...methods]})`);
    if (w === 360) await page.screenshot({ path: "/tmp/console-360.png", fullPage: false });
    if (w === 1440) await page.screenshot({ path: "/tmp/console-1440.png", fullPage: false });
    await ctx.close();
  }
  await browser.close();
} finally { srv.kill(); }
console.log(failures ? `${failures} FAILURE(S)` : "ALL BROWSER CHECKS PASSED"); process.exit(failures ? 1 : 0);
