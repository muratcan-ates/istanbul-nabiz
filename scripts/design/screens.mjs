#!/usr/bin/env node
/* Screenshots of the web UI for docs/design/screens, taken by headless Chrome over the
 * DevTools protocol.
 *
 * Why a script and not `chrome --screenshot`: the CLI flag can only photograph a first view
 * (it cannot click a chip, so no answer state and no ?nomap=1 fallback list), it fires before
 * the boot fetches have settled, and the Chrome build used on 2026-09-23 never exits after
 * writing the file. Here every shot waits for the network to go quiet, runs one optional
 * action, and closes the browser. Node 22 or later (global WebSocket and fetch), no npm.
 *
 * Hermetic on purpose: every host except 127.0.0.1 resolves to nothing, so the page gets
 * no MapLibre, no tiles and no font from anywhere else, and the app must run with
 * NABIZ_OFFLINE=1 so its answers come from tests/fixtures. A screenshot shows the app with
 * offline fixture data and nothing more (docs/design/README.md).
 *
 *   NABIZ_OFFLINE=1 .venv/bin/uvicorn nabiz.web.main:app --port 8766 &
 *   node scripts/design/screens.mjs --base http://127.0.0.1:8766 --prefix before
 *   node scripts/design/screens.mjs --only first --widths 390 --themes dark
 *
 * Output: <out>/<prefix>-<state>-<width>-<theme>.png, viewport-sized, device pixel ratio 1.
 */
import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const HEIGHT = { 1440: 900, 390: 844 };

/* Each state: the path to open and, optionally, one element to click and one to bring
 * into view before the capture. Selectors are the contract classes and ids of spec §17. */
const STATES = {
  first: { path: '/' },
  'nomap-parking': {
    path: '/?nomap=1',
    click: '.chip[data-journey="parking"]',
    view: { 1440: '.workspace', 390: '#map-panel' },
  },
  // The pen line at answer size, drawn from the same module as the hero's.
  traffic: { path: '/', click: '.chip[data-journey="traffic"]', view: { 1440: '.workspace', 390: '#results' } },
  // The ruler with every source the app has read since it started: shot last, so it holds them all.
  freshness: { path: '/', click: '.journey-tile[data-example="veri tazeliği"]', view: { 1440: '#freshness-strip' } },
};

function parseArgs(argv) {
  const opts = {
    base: 'http://127.0.0.1:8766',
    out: 'docs/design/screens',
    prefix: 'shot',
    only: Object.keys(STATES),
    widths: [1440, 390],
    themes: ['light', 'dark'],
    chrome: process.env.CHROME || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  };
  for (let i = 2; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, '');
    const value = argv[i + 1];
    if (!(key in opts) || value === undefined) throw new Error(`unknown or empty option ${argv[i]}`);
    opts[key] = ['only', 'themes'].includes(key) ? value.split(',')
      : key === 'widths' ? value.split(',').map(Number) : value;
  }
  return opts;
}

const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });

async function waitFor(check, timeoutMs, what) {
  const until = Date.now() + timeoutMs;
  while (Date.now() < until) {
    const value = await check();
    if (value) return value;
    await sleep(100);
  }
  throw new Error(`timed out waiting for ${what}`);
}

/** Start Chrome on a throwaway profile and return its first page's DevTools socket URL. */
async function launch(chrome) {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'nabiz-screens-'));
  const child = spawn(chrome, [
    '--headless=new', '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
    '--disable-extensions', '--remote-debugging-port=0', `--user-data-dir=${profile}`,
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1', 'about:blank',
  ], { stdio: 'ignore' });
  const portFile = path.join(profile, 'DevToolsActivePort');
  const port = await waitFor(() => fs.existsSync(portFile) && fs.readFileSync(portFile, 'utf8').split('\n')[0], 15000, 'Chrome');
  const targets = await waitFor(async () => {
    const list = await fetch(`http://127.0.0.1:${port}/json/list`).then((r) => r.json()).catch(() => []);
    return list.find((t) => t.type === 'page');
  }, 15000, 'a page target');
  // Chrome keeps writing its profile while it shuts down, so remove it only after the exit.
  const exited = new Promise((resolve) => { child.once('exit', resolve); });
  const stop = async () => {
    if (child.exitCode === null && child.signalCode === null) { child.kill(); await exited; }
    fs.rmSync(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  };
  return { url: targets.webSocketDebuggerUrl, stop };
}

/** A minimal DevTools client: send() resolves with the result, and in-flight requests are
 * counted so a shot can wait for the network to go quiet. */
async function connect(url) {
  const ws = new WebSocket(url);
  await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
  let seq = 0;
  const pending = new Map();
  const inflight = new Set();
  let lastActivity = Date.now();
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) reject(new Error(msg.error.message)); else resolve(msg.result);
    } else if (msg.method === 'Network.requestWillBeSent') {
      inflight.add(msg.params.requestId); lastActivity = Date.now();
    } else if (msg.method === 'Network.loadingFinished' || msg.method === 'Network.loadingFailed') {
      inflight.delete(msg.params.requestId); lastActivity = Date.now();
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    seq += 1;
    pending.set(seq, { resolve, reject });
    ws.send(JSON.stringify({ id: seq, method, params }));
  });
  const quiet = (ms = 500) => waitFor(() => inflight.size === 0 && Date.now() - lastActivity > ms, 20000, 'a quiet network');
  const evaluate = async (expression) => (await send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true })).result.value;
  return { send, quiet, evaluate, close: () => ws.close() };
}

async function shoot(cdp, opts, name, state, width, theme) {
  const height = HEIGHT[width] || Math.round(width * 0.625);
  await cdp.send('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 768 });
  // A screenshot is a still: under reduced motion every drawing is in its final state, never
  // caught halfway through the pen line's 1.4 s draw-on.
  await cdp.send('Emulation.setEmulatedMedia', {
    features: [{ name: 'prefers-color-scheme', value: theme }, { name: 'prefers-reduced-motion', value: 'reduce' }],
  });
  await cdp.send('Page.navigate', { url: new URL(state.path, opts.base).href });
  await waitFor(() => cdp.evaluate('document.readyState === "complete"'), 20000, 'the load event');
  await cdp.quiet();
  if (state.click) {
    const found = await cdp.evaluate(`(() => { const el = document.querySelector(${JSON.stringify(state.click)}); if (el) el.click(); return !!el; })()`);
    if (!found) throw new Error(`${name}: nothing matches ${state.click}`);
    await cdp.quiet();
  }
  const view = state.view && (state.view[width] || state.view[1440]);
  if (view) await cdp.evaluate(`document.querySelector(${JSON.stringify(view)})?.scrollIntoView({ block: 'start' })`);
  await cdp.evaluate('document.fonts.ready.then(() => true)');
  await sleep(300);
  const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
  const file = path.join(opts.out, `${opts.prefix}-${name}-${width}-${theme}.png`);
  fs.writeFileSync(file, Buffer.from(shot.data, 'base64'));
  console.log(`${file}  ${fs.statSync(file).size.toLocaleString('en')} B`);
}

async function main() {
  const opts = parseArgs(process.argv);
  fs.mkdirSync(opts.out, { recursive: true });
  const chrome = await launch(opts.chrome);
  try {
    const cdp = await connect(chrome.url);
    await cdp.send('Page.enable');
    await cdp.send('Network.enable');
    for (const name of opts.only) {
      if (!STATES[name]) throw new Error(`unknown state ${name}; known: ${Object.keys(STATES).join(', ')}`);
      for (const width of opts.widths) {
        for (const theme of opts.themes) await shoot(cdp, opts, name, STATES[name], width, theme);
      }
    }
    cdp.close();
  } finally {
    await chrome.stop();
  }
}

main().catch((err) => { console.error(err.message); process.exitCode = 1; });
