// Headless Chrome runner for wasm/harness.js (puppeteer-core + system Chrome).
//   node bench/m4_chrome.mjs <port> <variant scalar|simd> <graph> <dets> <obs> [js-flags]
// Pages are served by bench/m4_runtime.py with COOP/COEP headers (cross-origin isolated -> finer timer).
import { createRequire } from 'module';
const require = createRequire(import.meta.url + '/../../wasm/');
const puppeteer = require('puppeteer-core');
const [port, variant, graph, dets, obs, jsflags] = process.argv.slice(2);
const args = ['--headless=new', '--no-first-run', '--no-default-browser-check', '--disable-extensions'];
if (jsflags) args.push(`--js-flags=${jsflags}`);
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', args, headless: 'new'});
const page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error') console.error('page:', m.text()); });
await page.goto(`http://127.0.0.1:${port}/bench/m4_page.html`);
const res = await page.evaluate(async (variant, graph, dets, obs) => {
  const load = (src) => new Promise((ok, err) => { const s = document.createElement('script'); s.src = src;
    s.onload = ok; s.onerror = err; document.head.appendChild(s); });
  await load('/wasm/harness.js');
  await load(`/wasm/dist/qsx_${variant}.js`);
  const get = async (u) => new Uint8Array(await (await fetch(u)).arrayBuffer());
  const r = await globalThis.qsxRun({factory: globalThis.QSXModule, wasmBytes: await get(`/wasm/dist/qsx_${variant}.wasm`),
    graphText: await (await fetch(graph)).text(), dets: await get(dets), obs: await get(obs),
    label: `chrome-${variant}`, variant: variant === 'simd' ? 2 : 1});
  r.crossOriginIsolated = globalThis.crossOriginIsolated;
  r.userAgent = navigator.userAgent;
  return r;
}, variant, graph, dets, obs);
console.log(JSON.stringify(res));
await browser.close();
