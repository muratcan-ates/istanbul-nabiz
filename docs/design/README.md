# Web UI design: screenshots, gates and module layout

Working notes for the web redesign ("Nabız çizgisi"). **[`DESIGN.md`](DESIGN.md) is the design itself**:
colour theory, tokens, type, icons, the signature line, honesty and accessibility rules, budgets and the
plan. Section numbers below (§15, §18, §20) are the full spec's. This folder holds what the redesign
produces that is not code: screenshots and the annotated token file.

| Path | What |
|---|---|
| `DESIGN.md` | the approved design, public and short |
| `tokens.annotated.css` | `static/css/tokens.css` with the OKLCH source of every value and the rules, for review |
| `screens/before-*.png` | the page on `main` at `d59b5a8`, before any redesign step (step 0) |
| `screens/after-*.png` | the page as the tree has it after the latest landed step (steps 5 and 6: the new markup, the pen line and the ruler) |
| `../../eval/results/web-vitals.md` | bytes, requests and Web Vitals before and after each step |
| `../../scripts/check_web_budget.py` | the gate for §15 (FE-MOD, FE-OPT): `make web-budget`, and a CI step |
| `../../scripts/design/screens.mjs` | the screenshot driver described below |
| `../../scripts/design/{colorlib,build_palette,build_final_tokens,verify_tokens}.py` | the token scripts (step 4), below |
| `../../scripts/design/{build_font_subset,check_font,build_icon_sprite}.py` | the font subset and the icon sprite (step 3), below |

## Screenshots

Every screenshot shows the app and nothing else, running offline on recorded fixtures: no İBB host
is called, and the browser resolves no host but `127.0.0.1`, so no map library, tile or font comes
from anywhere else. A map answer therefore shows its list fallback.

```bash
NABIZ_OFFLINE=1 .venv/bin/uvicorn nabiz.web.main:app --port 8766 --no-access-log &   # a free port
node scripts/design/screens.mjs --base http://127.0.0.1:8766 --prefix after            # Node 22+
kill %1
```

- **Output:** `docs/design/screens/<prefix>-<state>-<width>-<theme>.png`, viewport-sized at device
  pixel ratio 1. Widths 1440 x 900 and 390 x 844; themes light and dark. States: `first` (the first
  view), `nomap-parking` (`?nomap=1`, then the parking chip, scrolled to the answer and the list
  that replaces the map), `traffic` (the traffic chip: the pen line at answer size) and `freshness`
  (the "veri tazeliği" welcome row, scrolled to the ruler, which by then holds every source the app has
  read since it started). New states are one line each in the script's `STATES` table; `--only` picks
  states, and the committed after set is the first view only until step 12 shoots every state.
- **Start the app fresh before a first-view shot.** The "Veri tazeliği" strip shows what the server
  has fetched since it started, so a warm server's first view is not a first view.
- **Dark:** the script emulates `prefers-color-scheme: dark` over the DevTools protocol. The page's
  own switch is `localStorage["nabiz-theme"] = "dark"`, which sets `<html data-theme="dark">`; §20 asks
  for both once the redesign lands. From the command line, `--force-dark-mode` gives the same media
  query (checked 2026-09-23).
- **Motion:** the script also emulates `prefers-reduced-motion: reduce`, so a drawing is shot in its
  final state: without it the pen line was caught partway through its 1.4 s draw-on.
- **Size:** the before set came out at 79 to 139 KB per file, under the 300 KB limit, so nothing was
  downscaled. Chrome writes no text chunks into these PNGs (checked: `IHDR`, `IDAT`, `IEND` only).
- **Why a script and not the one-liner.** `chrome --headless=new --screenshot=out.png
  --window-size=1440,900 http://127.0.0.1:8766/` works for a first view, with three catches found on
  2026-09-23: it cannot click, so no answer state and no `?nomap=1` list; it can shoot before the
  boot fetches settle; and the Chrome build used (153) wrote the file and never exited, so it had to
  be killed. `--host-resolver-rules="MAP * ~NOTFOUND"` without `EXCLUDE 127.0.0.1` also blocks the
  app itself.

The before set, taken on a freshly started app at `d59b5a8`:

| State | 1440 light | 1440 dark | 390 light | 390 dark |
|---|---|---|---|---|
| first view | `before-first-1440-light.png` | `before-first-1440-dark.png` | `before-first-390-light.png` | `before-first-390-dark.png` |
| `?nomap=1`, parking answer | `before-nomap-parking-1440-light.png` | `before-nomap-parking-1440-dark.png` | `before-nomap-parking-390-light.png` | `before-nomap-parking-390-dark.png` |

The after set is two first-view shots, `after-first-1440-light.png` (102,008 B) and
`after-first-390-dark.png` (68,286 B), retaken on 2026-09-23 on a freshly started app with steps 0 to 6 in
the tree: the new topbar, the hero with the pen line drawn from the recorded day (the archive state: grey,
dated, not breathing, because the fixture is two weeks old), and the "Veri tazeliği" ruler holding the
hero's own traffic read. Answers keep the old renderers until step 7, so no answer state is in the set yet.
The step-2 shots these replace differed from the before set only in the brand mark's animated dot (89
and 88 pixels, Pillow's `ImageChops.difference`). Each later step replaces these and adds its states.

## The budget gate and its targets

`scripts/check_web_budget.py` runs 13 checks (its docstring gives each one's reason). The page did
not pass all of them on the day they landed, so the findings it had are listed in `TARGETS_BY_CHECK`,
each with the §18 step that removes it and, for a count, the count it may not exceed:

| Mode | Command | Fails on |
|---|---|---|
| default (CI, `make web-budget`) | `.venv/bin/python scripts/check_web_budget.py` | any finding that is not a target, a count above its target, and a target that has been met but is still listed |
| strict | `... --strict` | everything, targets included |
| report | `... --report` | nothing; prints the same table (for measurements) |

So each step deletes the entries it meets, in the same change, or the gate goes red. Nothing compares
the table with the committed one, so raising or adding an entry is a review matter, with its reason in
the commit and beside the entry. When the table is empty the two modes agree, and CI switches to
`--strict` so that a new entry needs a visible CI edit too. Two targets are not a step's to meet: the JS
gzip budget (see `eval/results/web-vitals.md`), raised on 2026-09-23 for the review's fixes, for step 3's
icon routing and for steps 5 and 6 (the pen line, the ruler and `hero.js`, +11,598 B), and the page total,
which follows it until step 7 brings the JS down.

## Module layout (steps 2, 5 and 6)

`static/app.js` became native ES modules under `static/js/`, moved verbatim: every line of the old
file is in exactly one module, and `route()` is byte-identical. The only new code is
`forceMapOff()` in `map.js`, because a module cannot assign another module's variable.

| Module | Holds | Pure |
|---|---|---|
| `main.js` | boot: theme, one delegated listener each for the chips and the welcome rows, the form, polls | |
| `journeys.js` | question to endpoint to renderer, `run()`, the loading state | |
| `errors.js` | a failure rendered as an answer, with the last-known ages | |
| `api.js` | `api`, `apiPost`, `probe` | |
| `map.js` | MapLibre, loaded with the first answer that has points (below), markers, the list fallback | |
| `hero.js` | the pen line's host: its reads of `/api/traffic?window=24h`, the plot's measured size, the payload it lends the traffic answer | |
| `freshness.js`, `alerts.js`, `reliability.js`, `theme.js` | the ruler's host and the pill, the stored subscription, headway regularity, the theme | |
| `motion.js` | scripted motion (a smooth scroll, the map's easing) that stops under reduced motion; added with the review's fixes | |
| `router.js` | the keyword router | yes |
| `format.js`, `provenance.js`, `icons.js` | formatting, age stamps and source links, `icon(name)` | yes |
| `cards/{shell,parking,transit,metro,environment,route}.js` | the card renderers | yes |
| `charts/{pulse-geometry,pulse-view,age-ruler}.js` | the pen line's geometry and its SVG, readout and table; the ruler | yes |

Pure modules touch no DOM, network, storage or clock and import only pure modules, so node imports
them in tests (`tests/test_web.py` imports `js/router.js`). `static/js/package.json` holds only
`{ "type": "module" }`: it tells node these `.js` files are ES modules, so the tests do not depend on
a node version that detects module syntax by itself. Browsers ignore it.

## Tokens (step 4)

`static/css/tokens.css` is generated; nothing in it is typed by hand. Colours come from OKLCH values in
`build_palette.py`, the role aliases and the non-colour tokens from `build_final_tokens.py`, and
`verify_tokens.py` re-measures the files that were written, not the scripts' variables. Standard library
only, no network:

```bash
.venv/bin/python scripts/design/colorlib.py                    # self-checks against published values
.venv/bin/python scripts/design/build_palette.py               # the palette's 178 required pairs; exit 1 on a failure
.venv/bin/python scripts/design/build_final_tokens.py          # writes tokens.css and tokens.annotated.css
.venv/bin/python scripts/design/verify_tokens.py               # 178/178 palette pairs, 76/76 added pairs
.venv/bin/python scripts/design/build_final_tokens.py --check  # the committed files equal the scripts' output
```

`tests/test_web_design_tokens.py` runs the last three and shows each going red on a pale grey, on dark
blocks that drift apart and on a hand edit. The served file carries a three-line header; the long one
(colour theory, rules) is in `tokens.annotated.css`, because every phone downloads the served file and
that header was about a fifth of its gzip bytes (the same declarations: 13,742 B raw and 3,659 B gzip -9
under the long header, 12,177 B and 2,850 B under the short one).

## Font and icons (step 3)

Both are vendored, built by a script from a verified download, and shipped with their licence. The
downloads are the only network steps; the builds are reproducible (both re-run on 2026-09-23 wrote
byte-identical files).

**Font.** Source Sans 3 (owner decision, 2026-09-23), google/fonts `ofl/sourcesans3/SourceSans3[wght].ttf`
at commit `4591e3457ab8be6d70167aa6818922b91e78ab2d`, checked by git blob hash
(`d259aa494fe7117141a2752a998a52c172bbd42b`, 646,340 B). fontTools and brotli are build tools, not project
dependencies, so they go into a throwaway venv that is deleted afterwards:

```bash
python3 -m venv /tmp/fontenv && /tmp/fontenv/bin/pip install fonttools brotli
/tmp/fontenv/bin/python scripts/design/build_font_subset.py 'SourceSans3[wght].ttf' \
    --fallback Arial.ttf --fallback-bold 'Arial Bold.ttf'    # macOS: /System/Library/Fonts/Supplemental/
/tmp/fontenv/bin/python scripts/design/check_font.py
```

`check_font.py` on the shipped file (fontTools 4.65.0): 23,388 B, 259 glyphs, 218 characters, weight axis
400 to 700, every Turkish letter and `₺ µ ³ ₂ ₃ °` present, and the ten digits share one advance at each
weight (497, 513 and 528 units at 400, 600 and 700). The font has no `tnum` feature and needs none: its
figures are tabular by default. The subset is renamed "Nabiz Sans TR" because "Source" is a Reserved Font
Name in `static/fonts/OFL.txt`. The fallback face's overrides in `css/base.css` are computed from Arial's
advance widths; Android has no Arial, so there the fallback is the system face without overrides and the
swap can still move text (not measured; Lighthouse on a phone profile, step 12, would show it).

**Icons.** Tabler Icons 3.48.0 from the npm tarball, checked against `npm view @tabler/icons@3.48.0
dist.integrity` before anything is read from it:

```bash
curl -sSfLO https://registry.npmjs.org/@tabler/icons/-/icons-3.48.0.tgz
.venv/bin/python scripts/design/build_icon_sprite.py icons-3.48.0.tgz
```

It writes the 19 inline glyphs and the favicon between the `icons:start` and `icons:end` markers of
`index.html`, the other 32 into `static/icons.svg`, and the package licence into
`static/icons.LICENSE.txt`. `js/icons.js` holds the same inline list (`tests/test_web_assets.py` checks
both). Until steps 5, 7 and 8 use them, 32 of the 51 symbols are listed as unused targets in the gate.

## Stylesheets (step 4)

Four files, loaded in this order: `tokens.css` (generated), `base.css`, `components.css`,
`charts-map.css`. They share a byte budget of 40,000 B raw and 10,000 B gzip (each file gzipped on its
own); on 2026-09-23 they are 36,428 B and 9,810 B, which leaves 190 B of gzip for steps 5 to 8, and
160 B more once step 7 deletes the old gauges' rules (below). Every phone downloads the comments of a
served stylesheet, so the files keep only a header and the reasons a reader would otherwise undo; the
reasons live here.

**Rules for the old markup.** Until step 5 the page kept its old markup, which these stylesheets were
not written for. Two groups of rules existed only for it, and the step that removes the markup deletes
them: `.brand` and `.brand-mark` (gone with step 5), and `base.css`'s rules for the two gauges the old
renderers draw, `.gauge` and `.aqi-dial` (step 7). Without
those, each gauge drew as a solid black shape the width of the column (an unstyled SVG shape is
filled black), and an inline stroke that names a token only `style.css` defined (`--band-*`,
`--ink-soft`, `--ink-faint`) now falls back to the SVG's own stroke, because `stroke` inherits.

**Class vocabulary.** Component stylesheets use one prefix per component, checked by `css-prefix`:
`hero-`, `ask-`, `chip`, `sheet-`, `row-`, `stamp`, `badge`, `callout`, `skeleton` (components.css);
`pulse-`, `ruler-`, `scale-`, `ribbon-`, `map-`, `marker` (charts-map.css). State classes start with
`is-`. The markup steps use these names:

| Component | Markup it expects | Why it is built this way |
|---|---|---|
| Topbar (base) | `.topbar > .wrap.topbar-inner`: `.topbar-brand`, `.topbar-actions` with `a#live-pill` (`<i class="dot">`, `#live-pill-text`), `#theme-toggle.icon-btn`, `a.topbar-unofficial` | the dot takes the accent only with `.ok`, the "data is current" state; under 480 px the status text is visually hidden; `.topbar-unofficial::after` grows the target to 44 px without a heavier box; `#live-pill`'s only class is its state (`ok`, `warn`, `bad`), which `freshness.js` sets |
| Hero | `section.hero > .hero-text` (h1 with `.hero-em`, `.hero-sub`, the form, `.chips`) and `figure.pulse.hero-pulse` (`figcaption#hero-readout`, then one `.pulse-body` holding the plot and the "Saatlik değerler" table) | the plot and the table share one wrapper because every child of the figure but its caption takes the full-width row; from 1024 px the figure spans the hero's 12 columns on a subgrid: its caption (the readout) takes columns 8 to 12 of row 1 beside the text, its plot row 2 at full width, so caption and drawing stay one `<figure>`; `.hero-text` sits above the figure's empty half (z-index) so the form stays clickable |
| Ask form | `form#ask-form.ask`: `label.ask-label`, `.ask-row` (search `.icon`, `#q`, `#ask-submit.btn.btn-primary`), `#ask-hint`, `.ask-error` | styled by the contract ids where the old and new markup share them |
| Chips | `.chips > button.chip` (`.icon`, `.chip-label`, `aria-pressed`) | one scroll-snap row under 768 px (the next chip visibly cut), 44 px on coarse pointers |
| Answer | `.sheet-head` (`h2.sheet-title`, `.sheet-count`, `.stamp`, `.callout`), `.sheet` of `article.card.row`, `.sheet-disclaimer` | one raised surface; rows split by a hairline between rows only; `.card.is-focused` takes `--selected-row` at once and fades out over 1,200 ms; `.sheet-in` with `style="--i:N"` enters top first, 40 ms apart |
| Row | `.row-kind` icon, `.row-head` (h3, `button.btn.row-map` with `.row-map-word`), `.row-sub`, `.row-metric` (`.row-value`, `.row-unit`), `dl.row-facts`, `.row-grid`, `.row-foot` (`.stamp`, source link) | "Haritada göster" keeps its word from 768 px and is icon-only, 44 px, below |
| Stamp | `.stamp` (`.icon`, text, the age in `<b>`), `.stamp.is-cached` | warn colour only for "served from cache after a failure", never for age alone |
| Badges | `.badge` with `style="--line:var(--line-M4);--line-ink:var(--line-M4-ink)"`, `.badge-bus`, `.badge-aqi` with `--band`, `--band-ink`, `--band-text` | 19 px bold is WCAG large text, so every operator ink passes 3:1; the renderer names the tokens inline instead of 25 attribute rules (about 370 B of gzip), and `data-line` already means a journey argument on the chips |
| Callout | `.callout` (`.icon`, then text), `.callout-warn`, `.callout-ok`, `.callout-error` with `.callout-title` | a flex row, so a bare `<p class="callout">` still reads; the error card sits on the sheet's surface |
| Pen line | `figure.pulse` with `.is-live`, `.is-delayed`, `.is-archive`, `.is-drawing`, `.is-paused`; `figcaption.pulse-readout` (`.pulse-label`, `.pulse-reading` with `.pulse-value` and `.pulse-band`, `.pulse-note`); `.pulse-plot > svg` with `.pulse-guide`, `.pulse-tick`, `.pulse-ref` (yesterday), `.pulse-gap` (age), `.pulse-axis`, `.pulse-line` (`pathLength="1"`, stroke from a gradient whose stops are `.pulse-ink-low` and `.pulse-ink-high`), `g.pulse-now` (`.pulse-halo`, `.pulse-dot`, `.pulse-ring`), `.pulse-paper`; `.pulse-card` for the answer size | draw-on once, the now mark after it, breathing only while live and not paused; archive ink flat grey; the plot reserves its height (128 to 200 px, 120 on phones, 180 in an answer) so drawing causes no shift |
| Age ruler | `section.ruler#freshness-strip`: `.ruler-head` (h2, `.ruler-meta`, refresh `.icon-btn`), `.ruler-track` (`svg.ruler-axis` with `.ruler-line`, `.ruler-label`; `ol.ruler-marks#strip-rail` of `li.ruler-mark` with `style="--x:0.31;--row:1"`, a `.ruler-pin` and the sentence), `.is-now`, `.is-unhealthy`, `.is-end`, `.is-start`; `details#ruler-table` | tick labels sit above the axis line and marks hang below it, their pin 16 px longer per label row, so three rows of labels never cross; `.is-end` and `.is-start` keep a label at either end inside the track; an unhealthy mark's label is in `--warn` beside an alert icon; marks move with `translate`, never `left`; under 768 px the pins stay on the axis and the sentences become list lines |
| Scales | `.scale` of six `.scale-seg` (each with `--band`, `--band-text`) and a `.scale-tick` with `--x`, then `.scale-marks`; `.scale-occ` with `--share` | the occupancy stroke grows with `scaleX`, never `width` |
| Route ribbons | `.ribbon-leg` with `.ribbon-foot`, `.ribbon-transit`, `.ribbon-drive` | legs differ by dash pattern first, colour second |
| Map | `aside.map-panel#map-panel > .map-frame > #map` and `.map-fallback`; `ul.map-legend` with `span.map-swatch[data-kind]` | sticky beside the results from 1024 px, flat `--map-wash` under the tiles; MapLibre's own popup and font are overridden in base.css because its classes have no prefix of ours |
| Markers | `button.marker` with `data-kind` (park, bus, station, place or air) holding one `.icon`, `.is-active`; a station marker takes `style="--line:..."` and `data-line` | a 44 px target around a 28 px disc with a light ring and a dark edge, visible on light and dark tiles; `[data-kind]` also colours the legend swatches |

## Markup (step 5)

`static/index.html` follows spec §7 and §17: every contract id of §17.1 is in it (`check_web_budget.py`,
`contract-ids`), with the five the redesign adds (`#hero-pulse`, `#hero-readout`, `#answer-status`,
`#hakkinda`, `#ruler-table`). What changed for a reader or a script:

- **Topbar:** the wordmark alone (no drawn mark, no sub-line), the status link to the ruler, the theme
  button whose icon shows the current mode and whose label says the next one ("Tema: sistem. Açık temaya
  geçmek için basın."), and "resmî değildir" as a link to the statement in the footer (`#hakkinda`).
- **Announcements:** `#results` is no longer a live region; `journeys.js` writes one line into the
  visually hidden `#answer-status` (`role="status"`): "Yükleniyor." while an answer loads, then the
  answer's heading and its stamp ("Taksim Meydanı (Beyoğlu) çevresinde otopark 3 sonuç · 1,5 km. ölçüm
  15 gün önce"). Step 7 replaces that line with the spec's sentence per journey.
- **Welcome:** "Yazarak da sorabilirsiniz" rows and a "Her sayının bir yaşı var" legend of the stamp in its
  five forms. The rows with `data-example` put their wording into the box and ask it through the router
  (owner decision 5); "500T Şifa Sondurak" keeps its `data-journey` for the contract. The legend shows no
  ages: an example age in UI copy is an illustrative number, which the honesty rules forbid (DESIGN.md
  section 9), so it names what each stamp means instead.
- **An empty question** shows "Bir soru yazın, örneğin: Taksim'de otopark var mı?" under the input and
  adds it to the input's `aria-describedby`; the focus stays in the box.
- **Workspace:** results and the reliability panel share the left column (`.workspace-main`), the map the
  right, so the panel sits under the answer it belongs to.
- **Footer:** the charter's attribution line verbatim (the one allowed dash), the statement, and the
  colophon on separate lines; the version line stays empty until `/config.js` names one.
- **No third party in `<head>`:** MapLibre moved to `js/map.js` (below), and the two `preconnect`s went
  with it, because a visit that never shows a map should open no connection to a CDN or a tile server.

## Pen line (step 6)

`charts/pulse-geometry.js` turns `/api/traffic?window=24h` into pixels; `charts/pulse-view.js` turns those
into one SVG string, the readout and the "Saatlik değerler" table; `hero.js` hosts them. The rules, from
DESIGN.md section 7, and the reason each one exists:

- **Readings:** the history plus `now`, sorted, one per time; an index outside 1 to 99 is dropped, because
  İBB's 0 means "no reading", never "akıcı".
- **State from the data's own age** (`provenance.age_seconds`): under 7,200 s `live`, under a day
  `delayed`, otherwise or unknown `archive`, fewer than two readings in the window `insufficient`. An age
  nobody knows is archive because a line that cannot be dated must never look live.
- **X is true time.** A live or delayed window ends at the clock, so the dotted stretch after the last
  reading is the data's age (40 minutes of a 24-hour window is 22 px of a 795 px plot, checked in
  `tests/test_web_charts.py`). A reading almost a day old therefore leaves one reading in the window and
  the line says "Çizgi için yeterli ölçüm yok. Veri ... ölçüldü." An archive window ends at its last
  reading and says the date.
- **Y is İBB's fixed 1 to 99**, never auto-scaled, so a calm day looks calm; guides only at the server's
  band thresholds (20, 40, 60, 80), named at the right margin from 640 px.
- **The curve** is monotone cubic with d3's `curveMonotoneX` tangents. An inner tangent is at most twice
  the neighbouring slope, so the end tangents stay between half and one and a half times the end slope,
  and no segment leaves the band between its two readings: 0.000 px on the recorded day (5.7e-14 px,
  floating-point noise; the test allows 0.001). A gap over 90 minutes starts a new sub-path; nothing is
  bridged.
- **Ink:** a vertical gradient from `--pulse-ink-low` (index 1) to `--pulse-ink-high` (99), redundant with
  position; archive ink is flat grey. The now mark is the accent only while the data is live, and its
  ring breathes only while live, fresh from İBB (not served from cache) and the tab is visible.
- **Words:** the `<title>` is "Trafik indeksi, son 24 saat" only while live; the `<desc>` states the data's
  age in every other state, and only a live line may begin "Son 24 saatte". Delayed: "Çizgideki
  ölçümlerde ... Veri X önce ölçüldü." Archive: the sentence DESIGN.md gives, and the readout says
  "Önceki gün bu saatte 50" rather than "Dün", because the day before the reading is not yesterday.
- **Drawing:** only when the plot's measured width is above 0 (the design sketch drew the whole line at
  x near 0 when it measured before layout), again after a `ResizeObserver` change (debounced 100 ms, not
  animated), with ids unique per figure (the sketch's second figure turned grey sharing `id="ink"`), and at
  most 150 SVG nodes. The readout and table are rewritten only when the data changes, never on a resize,
  so a keyboard user's focus on the source link or "Tekrar dene" survives it.
- **Requests:** once the page is idle (`requestIdleCallback`, 1 s at most), then every 10 minutes, or 30
  while the reading is archive, and only while the tab is visible. A failed read keeps the last payload
  and ages it on screen; with none, the frame, "Trafik verisi şu an alınamadı." and "Tekrar dene". The
  traffic answer reuses a payload under 60 s old instead of asking again, and each read refreshes the
  ruler so the first view already shows it.
- **Not built yet:** the "paper advance" when a new hour arrives (spec motion 4) redraws in place, the
  reduced-motion behaviour; the pen line at card size in the traffic answer is step 7's.

## Age ruler (step 6)

`charts/age-ruler.js`, hosted by `freshness.js`, places each source of `/api/freshness` on one log axis:
`f(a) = (log10(clamp(a, 10 s, 60 days)) - 1) / (log10(60 days) - 1)`, "şimdi" at the right. The ticks fall
at 0.136 (1 dk), 0.311 (10 dk), 0.447 (1 sa), 0.689 (1 gün), 0.837 (1 hafta) and 0.947 (30 gün), checked in
`tests/test_web_charts.py`.

- **It plots `data_age_seconds`**, the data's own age, the one every answer's stamp shows.
  `age_seconds` (when Nabız last read the source) is only a fact in the sentence: plotting it would put a
  14-day-old reading at "4 dk" beside an answer stamped "14 gün önce".
- **Marks within 14 px merge** on the desktop axis into one labelled with the family ("İETT (2)") or
  "Kaynak (N)" and the newest member's age; each member keeps its own sentence for screen readers. A
  phone lists every source on its own line, so nothing merges there.
- **Labels** take the first of three rows where they fit (a greedy pass from the left, 6.5 px per
  character); one that fits none is left to screen readers rather than overlapping.
- **Unhealthy** (the last read failed): dashed pin, warn label, alert icon. A source that has never been
  read is not drawn; one that failed every time sits at the far left as "hiç alınamadı". Older than 60
  days reads "60 gün+".
- **The accent** marks only the newest mark, and only while its data is healthy and under 7,200 s, the
  same rule as the pill's "veri akıyor". "N kaynakta hata" counts sources whose last read failed, not
  every source that ever failed once.
- **Refresh:** at boot, every 60 s while visible, after every answer, after each hero read and on the
  button. A failed refresh keeps the marks at half opacity and says how old they are. The marks are
  rewritten on each refresh, so they jump rather than slide (spec motion 6): on a log axis a minute moves a
  mark by less than a pixel for anything older than an hour.

## Lazy map (step 5)

`js/map.js` adds MapLibre 4.7.1's stylesheet and script to `<head>` with the first answer that has points,
with `integrity`, `crossorigin="anonymous"` and `referrerpolicy="no-referrer"`. The two SHA-384 hashes were
computed on 2026-09-23 with `curl -sSfL <file> | openssl dgst -sha384 -binary | openssl base64 -A` over
the files cdnjs serves, twice with the same result; the same bytes' SHA-512 equals the SRI cdnjs publishes
(`https://api.cdnjs.com/libraries/maplibre-gl/4.7.1?fields=sri`), and a Chromium browser loaded both files
with them (`maplibregl.getVersion()` 4.7.1) and refused the script under a wrong hash. A blocked, failed or changed file sets `window.NABIZ_MAP_BLOCKED` and the
answer keeps its location list; `?nomap=1` still takes that path on purpose without loading anything. The
gate's `third-party` check reads the loader as well as `index.html`: a script string naming a cdnjs file
must be allowlisted, and the script must hold one integrity hash per file and set `crossOrigin`
(`tests/test_check_web_budget.py`, "the map loader without its hashes").
