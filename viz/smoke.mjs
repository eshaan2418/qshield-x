// Headless-Chrome smoke test of the M9 browser view: loads /viz/, decodes shots, runs the signed-result verifier,
// fails on any page error, and writes screenshots (light + dark) to the given directory.
//   node viz/smoke.mjs <port> <outdir>
import { createRequire } from 'module';
const require = createRequire(import.meta.url + '/../../wasm/');
const puppeteer = require('puppeteer-core');
const [port, outdir] = process.argv.slice(2);
const browser = await puppeteer.launch({
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  args: ['--headless=new', '--no-first-run', '--no-default-browser-check'], headless: 'new'});
const page = await browser.newPage();
await page.setViewport({width: 1400, height: 1100, deviceScaleFactor: 1});
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await page.goto(`http://127.0.0.1:${port}/viz/`, {waitUntil: 'networkidle0'});
await page.waitForFunction(() => document.getElementById('tShots').textContent !== '0');
await page.click('#play');
await page.waitForFunction(() => Number(document.getElementById('tShots').textContent.replace(/\D/g, '')) >= 600,
                           {timeout: 60000});
await page.click('#play');
await page.click('#nextFail');
await page.click('#verifyBtn');
await page.waitForFunction(() => /replay reproduces/.test(document.getElementById('verifyOut').textContent),
                           {timeout: 60000});
const verify = await page.$eval('#verifyOut', (e) => e.innerText);
const shots = await page.$eval('#tShots', (e) => e.textContent);
await page.screenshot({path: `${outdir}/viz_light.png`, fullPage: true});
await page.click('#themeBtn');
await page.screenshot({path: `${outdir}/viz_dark.png`, fullPage: true});
const ok = /signature valid/.test(verify) && !/MISMATCH|INVALID/.test(verify) &&
  /reproduces (\d+) \/ \1 /.test(verify) && errors.length === 0;
console.log(JSON.stringify({ok, shots, verify, errors}));
await browser.close();
process.exit(ok ? 0 : 1);
