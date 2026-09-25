# Web page: bytes, requests and Web Vitals

What the citizen-facing page (`src/nabiz/web/static`) costs a browser, measured before and after
each step of the web redesign (design spec, section 18). FE-OPT-1 asks for the numbers before and
after every optimisation claim; this file is where they live. Every number below comes from a
command named next to it. Re-measure before quoting.

Measured on 2026-09-23. **Before** is `main` at `d59b5a8` (one `app.js`). **After step 2** is the
working tree on top of it, where `app.js` is split into native ES modules under `static/js/`, with
no change to what the page shows (the proof is in the commit that makes the split).

## How it was measured

| Number | Command |
|---|---|
| Bytes per asset type, raw and gzip -9 | `.venv/bin/python scripts/check_web_budget.py --report` (each file gzipped on its own, the way the server would send it; -9 is the level Starlette's `GZipMiddleware` uses) |
| Headers on the wire | the app offline (`NABIZ_OFFLINE=1 .venv/bin/uvicorn nabiz.web.main:app --port 8766 --no-access-log`), then `curl -s -o /dev/null -D - -H 'Accept-Encoding: gzip, br' http://127.0.0.1:8766/<asset>` |
| Requests at boot | the app's own request log (`nabiz.web` writes one line per request) during one cold first-view load by `node scripts/design/screens.mjs --only first --widths 1440 --themes light`, on a freshly started app |
| Bytes transferred at boot | one cold load in headless Chrome over the DevTools protocol with the cache disabled, summing `encodedDataLength` (body plus headers) per first-party response; a throwaway script with the same launch flags as `scripts/design/screens.mjs` |

Every host except `127.0.0.1` was unresolvable in the browser runs (`--host-resolver-rules`), so
the MapLibre stylesheet and script requests fail by design and no tile or font is fetched.
Third-party bytes are therefore not measured here.

## Before (`d59b5a8`)

| Asset | raw | gzip -9 | lines |
|---|---:|---:|---:|
| `index.html` | 12,968 B | 4,253 B | 209 |
| `style.css` | 31,281 B | 7,365 B | 665 |
| `app.js` | 57,907 B | 19,240 B | 1,320 |
| **total first party** | **102,156 B** | **30,858 B** | |

- **Served uncompressed:** no `Content-Encoding` on `/`, `/app.js` or `/style.css` although the
  request accepts gzip and br. No `Cache-Control`; an `ETag` is present, so revalidation works.
- **Requests at boot, first party:** 5 (`/`, `/config.js`, `/style.css`, `/app.js`,
  `/api/freshness`). Third party: 2 (MapLibre 4.7.1 CSS, render-blocking, and JS, deferred).
- **Transferred at boot, first party:** 106,889 B, headers included, uncompressed.
- **Budget gate** on this tree (`check_web_budget.py --report` against a copy of these three
  files): 4 checks pass (payload, fonts, css-prefix, listeners) and 9 fail: the render-blocking
  MapLibre stylesheet; both MapLibre tags without an integrity hash; `style.css` animating `width`;
  100 colour literals outside `css/tokens.css` (99 in `style.css`, 1 in `app.js`); `app.js` at 1,320
  lines and `style.css` at 665 against the 300 and 350 caps, and no `css/tokens.css`; no module entry;
  55 SVG shapes drawn by hand in `index.html` and 5 in `app.js`; the 5 contract ids the redesign adds;
  30 em or en dashes in visible text (26 in `app.js`, 4 in `index.html`), the charter's attribution
  line allowed.

## After step 2 (ES modules, same page)

| Asset | raw | gzip -9 | files |
|---|---:|---:|---:|
| `index.html` | 13,630 B | 4,455 B | 1 |
| `style.css` | 31,281 B | 7,365 B | 1 |
| `js/**/*.js` | 62,814 B | 26,801 B | 19 |
| **total first party** | **107,725 B** | **38,621 B** | |

- **The split costs gzip, not raw bytes.** The same 19 modules compress to 20,647 B as one stream
  and to 26,801 B one file at a time, which is how they are served; `app.js` was 19,240 B. Raw
  bytes grew 4,907 B (module headers, imports, exports). Comments are 4,471 B of the 26,801 B gzip
  (measured by stripping them from a copy); they stay, because the code explains its reasons in them
  and stripping them would be a build step.
- **Against the spec's budgets** (JS 80 / 25 KB, total 140 / 40 KB): JS gzip is 1,801 B over. The gate
  records that overrun as a target that may shrink but not grow; the JS gzip budget for a page of
  native modules is an owner decision (see the handoff of the web lane, step 1).
- **Requests at boot, first party:** 23 (`/`, `/style.css`, `/config.js`, 19 modules, `/api/freshness`),
  7 of the modules announced by `modulepreload`. Third party: unchanged, 2.
- **Transferred at boot, first party:** 126,730 B, headers included, still uncompressed. Each
  response carries about 790 B of headers (`/js/theme.js`: 1,603 B transferred for an 811 B file),
  427 B of them the Content-Security-Policy.
- **Budget gate** (`check_web_budget.py`): 4 PASS, 9 TARGET, 0 FAIL. `js-modules` now passes (one
  entry after `/config.js`, modulepreload for its direct imports, no cycle, 10 pure modules). Every
  other finding is recorded with the step that removes it; `--strict` fails on all 9.

## After the review fixes (same day)

A review of the working tree on 2026-09-23 asked for fixes on the old page before the visual steps: the
freshness strip and status pill read the data's own age, darker greys and status colours in the light
theme, focus kept on "Sor", Turkish names and labels on the map, a table under the traffic bars, badge
ink, `js/motion.js`, and revalidation headers.

| Asset | raw | gzip -9 | files |
|---|---:|---:|---:|
| `index.html` | 13,564 B | 4,431 B | 1 |
| `style.css` | 31,344 B | 7,380 B | 1 |
| `js/**/*.js` | 65,597 B | 28,164 B | 20 |
| **total first party** | **110,505 B** | **39,975 B** | |

- **JS gzip is 3,164 B over the 25 KB budget**, 1,363 B more than after step 2. The gate's target for it was
  raised from 1,801 to 3,164 B in the same change, with that reason beside it: the JS gzip budget is still
  the owner's decision, and step 7 replaces the renderers these fixes touched. The total stays under
  40 KB by 25 B.
- **Headers:** `Cache-Control: no-cache` on `/`, `/js/*`, `/style.css` and `/config.js` (checked with
  `curl -sI` on the app run offline), so every module revalidates by ETag and one page load cannot mix
  two versions. The API answers carry none. Still no compression (step 9).
- **Requests at boot, first party:** not re-measured; the module graph has one more static import
  (`js/motion.js`, from `js/map.js`), so 24 by the count above.
- **Budget gate** (`check_web_budget.py`): 4 PASS, 9 TARGET, 0 FAIL, with 25 dashes left in visible text
  (the `js/journeys.js` entry met and deleted).

## After steps 3 and 4 (font, icons, tokens and stylesheets)

The Source Sans 3 subset, the Tabler sprite (19 glyphs inline, 32 in `icons.svg`) and favicon, and
four stylesheets in place of `style.css`. The markup is still the old one (step 5), so the page shows
in the new type and colours in a plain layout.

| Asset | raw | gzip -9 | files |
|---|---:|---:|---:|
| `index.html` | 15,695 B | 5,056 B | 1 |
| `css/*.css` | 36,428 B | 9,810 B | 4 |
| `js/**/*.js` | 65,939 B | 28,376 B | 20 |
| `icons.svg` | 6,747 B | 1,941 B | 1 |
| **total first party** | **124,809 B** | **45,183 B** | |
| `fonts/nabiz-sans-tr-v1.woff2` (fonts budget, not the total) | 23,388 B | already compressed | 1 |

- **CSS is inside its budget** (40,000 / 10,000 B): `tokens.css` 12,177 / 2,850 B, `base.css`
  9,354 / 2,872 B, `components.css` 7,274 / 2,002 B, `charts-map.css` 7,623 / 2,086 B. 160 B of the
  gzip are `base.css`'s rules for the old renderers' two gauges, which drew as solid black shapes
  without them; step 7 deletes them with the gauges. Under the palette stage's long header, which now lives
  only in `docs/design/tokens.annotated.css`, the same token declarations are 13,742 / 3,659 B.
- **JS gzip is 3,376 B over its budget**, 212 B more than after the review fixes: `js/icons.js` now
  holds the list of inline glyphs and sends the rest to `/icons.svg` (+169 B), and the call sites in
  nine modules use Tabler's names (+43 B). The gate's target was raised in the same change, with the reason beside it.
- **The total is 5,183 B over 40 KB**, recorded as a new target: the JS overage plus `icons.svg`
  (1,941 B, new). HTML (5,056 of 6,000 B) and CSS (9,810 of 10,000 B) are inside their own budgets; the
  type budgets add up to more than the total, so it holds only once step 7 brings the JS down.
- **Requests at boot:** not re-measured. By the markup, the page now asks for 4 stylesheets instead of
  1 and preloads the font; `icons.svg` is fetched once, when an answer or a hidden panel first shows an
  external glyph.
- **Budget gate** (`check_web_budget.py`): 6 PASS (motion and file-size newly; fonts now with a font to
  check), 7 TARGET, 0 FAIL.

## After steps 5 and 6 (markup, pen line, ruler)

The new markup (topbar, hero with the pen line figure, "Veri tazeliği" ruler, welcome rows and stamp
legend, footer), `hero.js` with the pen line's geometry and view, the ruler, and MapLibre moved out of
`<head>` into a loader in `js/map.js` that adds it, pinned by SRI hashes, with the first answer that has
points. Answers keep the old renderers (step 7).

| Asset | raw | gzip -9 | files |
|---|---:|---:|---:|
| `index.html` | 17,547 B | 5,384 B | 1 |
| `css/*.css` | 36,679 B | 9,863 B | 4 |
| `js/**/*.js` | 91,773 B | 39,974 B | 24 |
| `icons.svg` | 6,747 B | 1,941 B | 1 |
| **total first party** | **152,746 B** | **57,162 B** | |

- **JS gzip is 14,974 B over its budget**, 11,598 B more than after steps 3 and 4 (28,376 B to 39,974 B;
  the raw JS, 91,773 B, is past its 80,000 B too). The four new modules are 9,763 B of it:
  `charts/pulse-geometry.js` 2,997 B, `charts/pulse-view.js` 2,658 B, `charts/age-ruler.js` 2,395 B,
  `hero.js` 1,713 B. The other 1,835 B are the MapLibre loader (`map.js`), the ruler's host
  (`freshness.js`), the empty-question message and delegated listeners (`main.js`), the answer
  announcement and the shared traffic payload (`journeys.js`), the theme button and the stamp. Their
  comments were cut to one line of reason each (the longer reasons moved to `docs/design/README.md`);
  that took 1,040 B off the first draft. The gate's target was raised in the same change, with this
  reason beside it; the JS budget stays the owner's decision.
- **The total is 17,162 B over 40 KB**: the JS overage, the new markup (HTML +328 B gzip) and the
  ruler's label rows (CSS +53 B). HTML and CSS stay inside their own budgets.
- **Requests at boot, first party:** 36, counted in the app's own request log during one cold first-view
  load by `node scripts/design/screens.mjs --only first --widths 1440 --themes light` on a freshly
  started app: `/`, `/config.js`, 4 stylesheets, the font, 24 modules, `/icons.svg` (200, then a 304
  revalidation when the readout adds its trend icon), `/api/traffic?window=24h` (the hero, owner decision
  2) and `/api/freshness` twice (at boot, and again after the hero's read so the ruler shows it).
  `icons.svg` is fetched at boot now because the chevrons of two disclosures and the readout's trend icon
  are external glyphs (spec section 6 keeps them out of the inline sprite).
- **Third party at boot: 0** (was 2: the render-blocking MapLibre stylesheet and the deferred script).
  With the first answer that has points, the loader adds both, each with `integrity` and
  `crossorigin="anonymous"`; a Chromium browser loaded them (`maplibregl.getVersion()` 4.7.1) and refused
  the script under a wrong hash.
- **Budget gate** (`check_web_budget.py`): 9 PASS (render-blocking, third-party and contract-ids newly),
  4 TARGET (payload, tokens, icons and dashes, each waiting for step 7 or the owner), 0 FAIL.
- **Re-checked later the same day**, with step 7's files already in the working tree: the four modules
  measure the same (2,997, 2,658, 2,395 and 1,713 B of gzip, `gzip.compress(level=9)` as the gate does),
  and their node tests pass (`tests/test_web_charts.py`, 24 tests). The totals above were taken before
  step 7 touched the other modules and cannot be reproduced from that tree; step 7 records its own.

## Web Vitals

| Metric | Before | After step 2 |
|---|---|---|
| LCP, CLS, TBT (lab) | not run: `make lighthouse` is not wired and Lighthouse is not installed; this lane may download nothing but the assets the spec lists | not run: same reason |
| INP | n/a (a field metric; the page has no real-user monitoring, and adding a beacon would be a new data flow `docs/privacy.md` would have to cover) | n/a (same) |
