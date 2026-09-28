# Web UI design: "Nabız çizgisi"

The design of the citizen-facing page (`src/nabiz/web/static`), approved by the owner on 2026-09-23. It is the
public, short form of the full design spec, which is kept outside the repository together with the audit,
the palette study and the three competing directions it was chosen from. Section numbers in the code and in
[`README.md`](README.md) ("spec §15", "step 5") refer to that spec; this file carries every rule a
contributor needs.

**Status on 2026-09-23.** Steps 0 to 6 of the plan (§12) are in the tree: the before measurements and
screenshots, the budget gate, the old `app.js` split into ES modules with no visible change, the font
subset, the Tabler sprite and favicon with their licences (step 3), the generated `tokens.css` with
three hand-written stylesheets in place of `style.css` (step 4), the new markup with MapLibre loaded only
with the first map (step 5), and the pen line, the "Veri tazeliği" ruler and `hero.js` (step 6). A review
the same day added fixes that the design keeps: the data-age strip and the status pill read the data's own
age (§7), darker greys and status colours so small text passes 4.5:1, focus kept on "Sor" while an answer
loads, Turkish names for the map's controls and markers, a table under the traffic bars, `Cache-Control:
no-cache` on the page's files (step 9, half), and `js/motion.js` for scripted motion. Answers keep the old
renderers until step 7. How each piece is built, and why: [`README.md`](README.md).

---

## 1. Design read and dials

A citizen asks a question or picks a place and gets live answers from İBB's open data, each with its data
age, beside a map. The page is also what a reviewer sees first. The language is calm and corporate, white
and İstanbul-municipal blue, with **one** living element: a line drawn from real traffic readings.

| Dial | Value | Why |
|---|---:|---|
| Design variance | 5 | Public-sector base (3), raised by 2 for an overhaul. Asymmetry only in the hero and in the results-and-map split, which has a working reason. |
| Motion intensity | 4 | Base 2, raised by 2 because the brief asks for "akıcı ve canlı". Every animation has a one-sentence reason and a reduced-motion path (§8). |
| Visual density | 4 | The old page measured about 6 (29 font sizes, pills on every value, cards in cards). The drop comes from removing boxes and sizes, not data. |

It is product UI, not a landing page: no hero illustration, no stock photos (a city photo would read as an
official city page), no three equal feature cards. The visuals are drawings computed from API payloads and
a real map.

**Foundation.** A native-CSS token system, labelled as Nabız's own. No design-system package: the page is
vanilla HTML, CSS and ES modules with no build step and no npm, and a package would add a runtime, a second
CDN and somebody else's identity (Fluent reads Microsoft, Carbon IBM, GOV.UK another state).

## 2. Colour theory

**Measured, not chosen by taste.** In OKLCH, the blues on İBB's and İETT's websites sit between hue 259.3
and 263.4, and İBB pairs them with a cyan about 38 degrees away. The base hue is therefore **260**.

| Principle | Decision |
|---|---|
| Base hue | OKLCH 260. Primary-700 `#2457aa` is 0.37 ΔE2000 from ibb.istanbul's blue-600, below what a person can see, so the page reads "İstanbul municipal blue" without copying any asset. |
| Harmony | **Analogous, cool:** one accent at hue 222, the same step and direction İBB uses. Complementary (80), split-complementary (50, 110), triadic (20, 140) and İBB's own pink (340) were tested and rejected: each collides with warn, bad, an AQI band or a Metro line colour. |
| Lightness | Ramps step evenly in OKLab L (0.075 per step), so steps look equal. Hierarchy is carried by lightness, which is also what contrast and colour-blind vision depend on. Gamut mapping reduces chroma at fixed L and h, never L. |
| Neutrals | Hue 260 at chroma 0.003 to 0.040: greys that read as blue ink. The light end reproduces İBB's own slates (`#fbfcfe`, `#f4f7fc`). The dark end carries more chroma, so dark mode is deep navy (`#0b1628`), never black. |
| Quantity vs category | **Lightness encodes quantity** (the pen line is darker where traffic is heavier in light mode, brighter in dark). **Hue encodes only categories a source defines** (Metro line colours, AQI bands). |
| Temperature | Warm hues are reserved for warn, bad and polluted air, so the cool accent can mean "live" without ever looking like a problem. |
| Status | ok is a bluish green (hue 162 to 165), which colour-blind viewers still tell apart from red and amber (the Okabe-Ito choice). Warn and bad are staggered in lightness. Status is always icon, word and colour together. |
| Proportion | About 85 % cool neutrals, 12 % primary blue (actions, data ink), under 1 % accent. Line and AQI colours appear only as data. |

**The accent lock.** The cyan accent means "şimdi / canlı / odak" and nothing else: the latest reading of a
drawing while it is current, the status pill's live dot only while some source's data is current (its
`data_age_seconds` under 7,200 s, §7), the focus ring and the selected map marker. Never a button, a
large fill, body text or a gradient. HSL saturation 58.7 % light and 54.0 % dark, under the 80 % ceiling.

Moment colour (tulip, h 352.8 light / 348.9 dark): only the four locations listed in `NABIZ-DILI.md` §3.5;
never a button, text colour, large area or status meaning.

**Identity boundary.** Nabız borrows the web palette family, never the mark: no İBB logo, emblem or
emblem-like shape, no Pantone 200 C red (the one official İBB brand colour), no sign panels. Metro line
colours are the operator's published values, never tuned, and always carry their code.

**Sources.**

| What | Source |
|---|---|
| İBB's one official brand colour (the logo red, avoided on purpose) | İBB Kurumsal Kimlik Kılavuzu, 09.06.2020, section "Logonun rengi" |
| İBB web blues and slates | ibb.istanbul production stylesheet, sampled 2026-09-23 (a sample, not a published guideline) |
| İETT and Metro İstanbul web colours | iett.istanbul and metro.istanbul stylesheets, sampled 2026-09-23 |
| Metro line colours | metro.istanbul line pages (operator), cross-checked with the `GetServiceStatuses` colour fields in `tests/fixtures/`; M11 from Wikipedia's Istanbul Metro module because Metro İstanbul does not operate it |
| AQI band meaning | US EPA AQI colours via the AirNow Technical Assistance Document; only İBB's "İyi" colour appears in a recorded payload, so the other bands are re-derived with the EPA meaning |
| OKLab / OKLCH | Björn Ottosson, "A perceptual color space for image processing" (2020); the same matrices CSS Color 4 uses |
| Contrast | WCAG 2.2 relative luminance and contrast ratio (4.5:1 text, 3:1 large text and graphics) |
| Colour-vision simulation | Machado, Oliveira and Fernandes (2009), severity 1.0, in linear RGB |
| Colour difference | CIEDE2000 (CIE 142-2001) on CIELAB D65 |

## 3. Tokens

One generated file, `static/css/tokens.css` (step 4), and a review copy `docs/design/tokens.annotated.css`
that keeps every OKLCH source. It is the **only** file in `static/` allowed a colour literal; scripts read
tokens through classes, or through `getComputedStyle` for MapLibre paint.

| Group | Tokens |
|---|---|
| Ramps | `--primary-50..950`, `--accent-50..950`, `--neutral-0..1000` |
| Metro lines | `--line-<code>` and `--line-<code>-ink` for M1A to T5, TF1, TF2, F1, F4, M11, plus `--line-unknown` |
| Semantic | `--surface`, `--surface-raised`, `--surface-sunken`, `--border(-strong)`, `--text(-muted, -subtle)`, `--primary*`, `--link*`, `--accent*`, `--focus-ring`, `--moment` and `--moment-subtle` (generated tulip event colour), `--ok/warn/bad/info` with washes, `--aqi-*`, `--kind-*`, `--marker-ring`, `--shadow-1..3` |
| Dark | the same names under `prefers-color-scheme: dark` (unless `data-theme="light"`) and under `data-theme="dark"`, generated from one list so the two blocks cannot drift |
| Non-colour | 8 type sizes and a display clamp, 3 weights, 3 leadings, a 4 px spacing scale, two radii, layout widths, 2 easings and 7 durations, drawing strokes, a z-index scale |
| Role aliases (no new colour) | `--pulse-ink-low/high/archive`, `--chart-guide/ref/now/halo/best`, `--live-dot`, `--occupancy-ink`, `--route-foot/transit/drive`, `--badge-bus`, `--line-casing`, `--marker-edge`, `--map-wash`, `--sheet-bg`, `--skeleton`, `--selected-row`, `--topbar-bg` |

**Verified.** `scripts/design/verify_tokens.py` on the files in the tree: the palette's
required pairs **178/178** and the pairs this design adds **80/80** pass in both themes, including four
3:1 moment-colour graphic pairs; the served
and annotated copies resolve identically, and so do the two dark blocks. The served file keeps a
three-line header (the long one stays in the annotated copy) and is 12,331 B raw and 2,895 B gzip -9
(budget 16 KB / 4 KB). An excerpt, light / dark:

| Pair | Light | Dark | Needs |
|---|---:|---:|---:|
| pen ink, low end, on the page | 4.69 | 8.70 | 3.0 |
| pen ink, high end, on the page | 12.01 | 14.25 | 3.0 |
| archive ink on the page | 3.39 | 7.55 | 3.0 |
| now mark on the page | 3.30 | 6.86 | 3.0 |
| axis labels and stamps (`--text-subtle`) on the page | 5.02 | 7.55 | 4.5 |
| cached stamp (`--warn`) on the answer sheet | 5.27 | 9.71 | 4.5 |

Line badges set their code at 19 px bold (WCAG large text): every ink passes 3:1, and M4, M8, T3, T5 and
M11 do not reach 4.5:1 with any ink, which is why there is no small badge. The verifier and the palette
scripts are in `scripts/design/` (commands in [`README.md`](README.md)); `verify_tokens.py` exits 1 on any
failed pair, and `tests/test_web_design_tokens.py` holds the served file to what the scripts write.

## 4. Type

| | |
|---|---|
| Family | **Source Sans 3** (Adobe; SIL Open Font License 1.1), variable weight 400 to 700, upright only |
| Why | Of the two faces the spec weighed, the one with every glyph the page prints (`₺`, `µ`, `³`, `₂`, `₃` beside the Turkish letters) and tabular lining figures by default, so riders can line up codes and times (`M1A`, `500T`, door `C-338`, `18:00`). Nobody's identity here (İBB, İETT and Metro İstanbul use other faces), and not one of the faces generated pages default to (Inter, Geist). |
| Delivery | One self-hosted subset, `static/fonts/nabiz-sans-tr-v1.woff2` (23,388 B), `font-display: swap`, preloaded; a metric-matched fallback face whose overrides are computed from the subset's tables with fontTools, never guessed; `OFL.txt` beside it and a line in `NOTICE.md`. Renamed "Nabiz Sans TR" inside the file, because "Source" is a Reserved Font Name |
| Scale | A display clamp (32 to 48 px, h1 only) and 8 sizes: 48, 36, 28 (the one metric per row), 22, 19, 16 (body), 14, 12 (axis labels only). Weights 400, 600, 700. Hierarchy by weight and ink, not size jumps. |
| Rules | Sentence case; **no `text-transform: uppercase`** (it is the eyebrow tell and breaks Turkish casing on ASCII data such as `YENIKAPI`); tabular lining numbers; Turkish decimal comma via `toLocaleString('tr-TR')`; body measure 65ch |

**Why not Atkinson Hyperlegible Next**, the face the spec first chose. A coverage check run on 2026-09-23
with fontTools on google/fonts' `AtkinsonHyperlegibleNext[wght].ttf` (version 2.001, 114,552 B) found **no
glyph** for `₺` (U+20BA), `µ` (U+00B5), `₂` (U+2082) or `₃` (U+2083), which the page prints (tariffs,
µg/m³, NO₂, O₃). The rule is never to mix faces and never to fall back to "TL" or "NO2", so the owner chose
Source Sans 3 the same day. The coverage gate of step 3, `scripts/design/check_font.py`, reads the shipped
subset: 259 glyphs, 218 characters, every Turkish letter and `₺ µ ³ ₂ ₃ °`, and **tabular figures, by
default or through `tnum`**, measured from the `hmtx` advances. Source Sans 3 has no `tnum` because it
needs none: the ten digits share one advance at each weight (497, 513 and 528 units at 400, 600 and 700).

## 5. Icons

**Tabler Icons 3.48.0**, outline set, MIT. Stroke icons on a 24-unit grid, so one CSS rule sets every
stroke and it matches the data pen (2 at 20 px is 1.67 px; the pen is 1.75 px). One family; nothing
hand-drawn; no Unicode glyph used as an icon (`↗ ▲ ▼ → ▸`).

- Built from the official npm tarball, verified against `npm view @tabler/icons@3.48.0 dist.integrity`, by a
  stdlib script (`scripts/design/build_icon_sprite.py`) into two outputs: an inline sprite block in
  `index.html` for the 19 glyphs the static markup uses, and a same-origin `static/icons.svg` for the rest
  (answers only), with the MIT text in `static/icons.LICENSE.txt`.
- `js/icons.js` keeps the `icon(name)` indirection; every icon is `aria-hidden` and the word beside it
  carries the meaning. The favicon is Tabler's `activity` glyph on a primary-700 square.
- 52 names in total (19 inline, 32 external, 1 favicon), each checked by the design stage to exist in 3.48.0.

## 6. Layout and components

- **Container** 1280 px, gutter 24 px (16 under 768). Breakpoints 640, 768, 1024, 1280. Single-column grids
  use `minmax(0, 1fr)` so a scrolling chip row cannot widen the page.
- **Shape lock, one rule:** surfaces (answer sheet, map frame, callouts, panels) 12 px; controls and labels
  8 px; round only for dots, markers and the live dot. Drawings use round caps only.
- **One elevation:** the answer sheet is the page's primary object (raised, 1 px border, one shadow). Inside
  it, rows are separated by hairlines. No card in a card, no border above the first row or below the last.
- **Hero:** h1 "Şehrin verisi, **yaşıyla birlikte.**" (second half in primary, same family and weight), a
  one-sentence subtext, the form with a visible label and the "dil modeli yoktur" helper, five example chips.
  The pen line figure spans the content width under it, with the live readout as its caption.
- **Workspace** from 1024 px: results 7 columns, map 5 columns, sticky. With no points the grid is one column.
  On phones the map sits behind "Haritada göster" and MapLibre loads only when it is pressed.
- **Answer anatomy:** a result head (h2, count, stamp, the server's note as a callout), one sheet of rows
  (kind icon, title, one metric, facts in at most two lines, disclosures, "Haritada göster", stamp and source
  link), and the server's disclaimer verbatim under it.
- **The stamp:** İBB readings say "ölçüm X önce", Nabız computations (forecast, reliability, routing) say
  "hesaplama X önce". Clock icon under an hour, history icon after. Warn colour only for "served from cache
  after a failure"; never a verdict word for age alone, because a day-old station record is normal.

## 7. The signature: Nabız çizgisi

A pen line under the hero records the last 24 hours of İBB's city-wide traffic index, like a chart recorder.
The data is the seed: the same readings always draw the same line.

**Data.** One existing call, `GET /api/traffic?window=24h` (hourly history, now, same hour yesterday, delta,
provenance). Requested once after first paint, then every 10 minutes while the tab is visible (every 30 in
the archive state), paused when hidden. The server's 300 s cache bounds it to at most 12 upstream calls an
hour, none from the İETT budget (owner decision 2).

**Algorithm** (`static/js/charts/pulse-geometry.js`, pure: the clock is an argument):

1. Readings are the history plus now, sorted and de-duplicated; an index outside 1 to 99 is dropped (İBB's 0
   means "no reading", never "akıcı").
2. State from `provenance.age_seconds`: under 2 h `live`, under a day `delayed`, otherwise or unknown
   `archive`; fewer than 2 readings `insufficient`.
3. X is true time. Live and delayed: the window ends at the clock, so the gap between the last reading and
   the right edge **is** the data's age. Archive: the window ends at the last reading and the caption says
   "Son ölçüm 8 Eylül 09:00. Çizgi o güne ait, canlı değil."
4. Y is İBB's fixed 1 to 99 scale, never auto-scaled: a calm day must look calm.
5. The curve is monotone cubic (Fritsch-Carlson), so it never overshoots a reading; a gap over 90 minutes
   starts a new sub-path and is never bridged.
6. Guides only at the server's own band thresholds (20, 40, 60, 80), named in words.
7. Pen pressure: a vertical gradient from `--pulse-ink-low` (index 1) to `--pulse-ink-high` (99), redundant
   with position; archive ink is flat grey.
8. Yesterday is a dashed rule at the same hour's value; one peak label; the now mark is a 5 px accent disc
   with a halo, and only while the data is live does it breathe.
9. `describe(points, data, state, provenance)` returns the sentence for the SVG's `<desc>` and the phone
   caption, and says the data's age in every state but `live`: only a live line may start "Son 24 saatte".
   On the recorded offline payload (state `archive`): "Son ölçüm 8 Eylül 09:00; çizgi o güne ait, canlı
   değil. O güne kadarki 24 saatte trafik indeksi en düşük 1 (01:00), en yüksek 74 (18:00). Son ölçüm 60,
   yoğun. Önceki gün aynı saatte 50." In `delayed` the sentence ends "Veri X önce ölçüldü." with
   `provenance.age`. The SVG `<title>` is "Trafik indeksi, son 24 saat" only while live, otherwise "Trafik
   indeksi, 24 saatlik kayıt". The node tests of step 6 run one case per state (live, delayed, archive,
   insufficient); the archive sentence carries the date and never "Son 24 saatte".

The view renders only when its width is above 0 and re-renders on `ResizeObserver` (the design sketch drew
the path at x near 0 after a viewport change). At most 150 SVG nodes, unique ids per instance, colour only
through classes. Checked on 2026-09-23 on the captured offline payload with the design stage's geometry check:
state `archive`, 0.000 px overshoot, and a 25 px age gap when the clock is simulated 40 minutes after the
last reading.

**Veri tazeliği ruler.** Between the hero and the answers, the data age of every source on one log axis
from "şimdi" (right) to 60 days (left), from `/api/freshness`, which reads cache statistics and never
touches İBB. The ruler plots `data_age_seconds`: the data's own age, from the source's timestamp
(`reported_at_utc`) when it states one, otherwise from the read, the rule every answer's stamp uses.
`age_seconds` is only when Nabız last read the source, a secondary fact in the mark's sentence ("son okuma
4 dk önce"): plotting it would put a 14-day-old reading at "4 dk" beside an answer stamped "14 gün önce".
Marks within 14 px merge ("İETT (3)"), an unhealthy source is dashed with a warning icon, a source that never
succeeded says "hiç alınamadı". The marks are an `<ol>` of full sentences for screen readers. The status pill
reads the same field: the accent live dot and "veri akıyor" only while some source's data age is under
7,200 s (the pen line's `live`), otherwise neutral ink and "bağlı, en yeni veri 14 gün önce". Both refresh
after every answer as well as on the 60 s poll, so the empty sentence "İlk soru bu cetveli doldurur." is
true.

**One pen for every drawing** ("tek kalem"): one stroke weight; measured is solid, estimated dashed, assumed
dotted; exactly one accent mark per drawing, and only while current; fixed domains from the source's own
scale (traffic 1 to 99, AQI breakpoints, occupancy 0 to 100 %); gaps never interpolated; every drawing has a
sentence and a table or rows with the same numbers.

## 8. Motion

Only `transform`, `opacity` and `stroke-dashoffset` animate. No scroll listeners, parallax, marquee or
count-up numbers (an intermediate value is a number nobody measured). Each motion has a reason:

| What moves | Why |
|---|---|
| Pen line draws on once, left to right (1,400 ms) | reads the line as time |
| Now mark breathes, only while live and the tab is visible | "this reading is current"; its absence is information |
| Ruler marks slide on each poll | data gets older in real time |
| Previous answer dims and becomes `inert` while the next loads (focus inside it moves to `#results` first) | acknowledges the question without wiping the page |
| New answer enters top first, 40 ms stagger | reading order |
| Press, hover, focus, disclosure, map `fitBounds` | feedback and spatial continuity |

Under `prefers-reduced-motion: reduce` nothing moves, the map jumps and scrolling is instant; one CSS block
zeroes transitions and `js/motion.js` skips every scripted animation. The budget gate checks both by
structure: every animation sits inside `(prefers-reduced-motion: no-preference)` or a `reduce` rule on `*`
stops them all, and a smooth scroll, `element.animate` or a map camera easing outside `js/motion.js` fails
(`fitBounds` only with `duration: 0`). A focused control inside an `inert` subtree drops focus to `<body>`,
so before the previous answer goes inert, focus inside it moves to `#results` (`tabindex=-1`); "Sor" is
`aria-disabled` while loading, never `disabled`, for the same reason.

## 9. Honesty rules (hard)

1. Never look like an official İBB, İETT, İSPARK or Metro İstanbul product (§2, identity boundary).
2. "resmî değildir" is visible at every width and links to the full statement in the footer.
3. Every number carries its data age: rows, popups, the map's list fallback, the readout, the ruler, error
   lists. The only exception is a count of the rows directly below it.
4. Drawings are computed from payloads: no invented point, no count-up, no interpolated gap, no illustrative
   number in UI copy.
5. Computations say "hesaplama", estimates say "tahmin" and are dashed; server disclaimers ship verbatim.
6. No personal data: plates never shown (the KVKK note stays), the alert subscription stays in the browser,
   nothing new is sent or stored.
7. No em or en dash in any visible string (a period, comma, colon or parentheses instead; ranges take a
   hyphen). The one allowed exception is the charter's attribution line, verbatim, by owner decision.

## 10. Accessibility (WCAG 2.2 AA)

- Keyboard order follows the reading order; a skip link "İçeriğe atla"; a 2 px focus ring in `--focus-ring`
  with a 2 px offset everywhere, never removed.
- Targets of at least 44 x 44 px for the theme toggle, refresh, "Haritada göster", markers and touch chips.
  The accessibility review of 2026-09-23 found markers of the offline answers closer than 24 px on a phone,
  some exactly on top of each other, so size alone cannot meet WCAG 2.5.8: markers closer than 24 px merge
  into one marker that names them all, and each row's "Haritada göster" is the full-size equivalent control
  for its marker. Until step 8 the old markers are 24 px (1.5rem) instead of 16.8 px.
- Map markers are `<button>`s whose Turkish `aria-label` is set **after** `addTo`, because MapLibre 4.7.1
  writes its own ("Map marker"). MapLibre's own names come from its `locale` option in Turkish ("Harita",
  "Yakınlaştır", "Uzaklaştır", "Harita kaynaklarını göster"), and `#map` is not a second region around its
  canvas.
- `#results` stops being a live region; a visually hidden `#answer-status` says one sentence per answer
  ("Taksim çevresinde 4 otopark bulundu. Veri 2 dakika önce ölçüldü.").
- Drawings: the pen line is a `<figure>` with its readout as caption, an SVG with its own title and generated
  description, and a "Saatlik değerler" table; the ruler's marks are a list; the AQI scale and occupancy
  have sentence labels. Colour is never the only cue (icon and word on stamps, confidence, status; dash
  patterns on route legs; shape on the now mark).
- Forced colours switch drawing strokes to `CanvasText`. `lang="tr"`; no English switch in v1, because the
  server's age, note and disclaimer strings are Turkish and a UI-only switch would be half translated.

## 11. Rules and budgets, enforced

`scripts/check_web_budget.py` holds 14 checks: 13 on this page and `citizen-page`, the byte budget of the product
app's citizen page (DECISIONS #110; `make web-budget`, CI step "Web budget"; each shown red on a
broken copy in `tests/test_check_web_budget.py`). Findings the page still had when the gate landed are listed
as targets with the step that removes them; a count may not grow past its target, and one that is met but
still listed fails the build. Nothing compares the table with the committed one, so raising an entry is a
review matter with its reason beside it. Two rules have no static check: `esc()` on every API string
(review, then the renderer tests of step 7) and teardown of listeners and timers (review). The no-dash rule
has two halves: the gate reads the page's own files (HTML, script strings with their escapes and HTML
entities, CSS `content`), and `tests/test_answer_text.py` reads every string of every offline `/api/*`
answer, because route, traffic and occupancy sentences come from the server.

**Modular code (FE-MOD).** Native ES modules, one entry `/js/main.js`, no build step. Pure modules (format,
router, provenance, icons, charts, cards) never touch `document`, `window`, `fetch`, storage or the clock, so
node imports them in tests. 300 lines per JS module, 350 per hand-written CSS file; colours only in
`css/tokens.css`; one CSS prefix per component; one delegated listener per region; every API string through
`esc()`; icons only through `icon(name)`; the contract ids of the page present; no dash in visible text.

**Performance (FE-OPT).** Budgets, raw / gzip -9 (each file gzipped on its own, the way it is served, then
summed per type):

| Item | Budget | Today (`check_web_budget.py --report`, 2026-09-23, after steps 5 and 6) |
|---|---:|---:|
| HTML | 20 / 6 KB | 17.5 / 5.4 KB (17,547 / 5,384 B) |
| CSS, at most 4 files | 40 / 10 KB | 36.7 / 9.9 KB (4 files, 9,863 B gzip; 160 B come back when step 7 deletes the rules for the old gauges) |
| First-party JS | 80 / 25 KB | 91.8 / 40.0 KB: over by 14,974 B gzip and 11,773 B raw. 1,801 B after step 2, raised for the review fixes, step 3's icon routing and steps 5 and 6 (+11,598 B, of which the pen line, the ruler and `hero.js` are 9,763 B); a listed target the owner decides (§12) |
| Icons (`icons.svg`, in the total) | none of its own | 6.7 / 1.9 KB |
| Total | 140 / 40 KB | 152.7 / 57.2 KB: over by 17,162 B gzip, a listed target that follows the JS one |
| Fonts | at most 4 files, 60 KB | 1 file, 23,388 B |
| Third-party render-blocking | 0 | 0 (MapLibre loads with the first answer that has points, pinned by SRI hashes) |
| Layout-property animations | 0 | 0 |

The rules also require, from the steps that build them: MapLibre 4.7.1 loaded lazily with a
subresource-integrity hash; `air` and `traffic` firing their two calls in parallel and a superseded answer
aborted; text assets gzip-compressed and revalidated by ETag, the versioned font cached for a year; and no new
request at boot except the hero's cached traffic read. Core Web Vitals (LCP 2.5 s, INP 200 ms, CLS 0.1) are
measured by hand with Lighthouse, never gated in CI; before and after numbers go to
[`eval/results/web-vitals.md`](../../eval/results/web-vitals.md).

## 12. Decisions and the plan

**Approved by the owner on 2026-09-23:** keep the charter's attribution line verbatim as the one allowlisted
dash; allow the one cached boot request `/api/traffic?window=24h`; Source Sans 3 as the one face (§4); the copy
changes (page title, 404 title, the version placeholder, the brand sub-line, the welcome rows, the cached
stamp wording); the behaviour changes (`aria-live` moves to `#answer-status`, welcome rows submit through the
router, the map loads lazily and on phones behind a button). Never the İBB logo; "resmî değildir" always
visible; every number keeps its data age.

**Open:** the JS gzip budget for native modules (the split costs gzip, not bytes; the review fixes added
1,363 B, step 3's icon routing 212 B and steps 5 and 6 11,598 B: `eval/results/web-vitals.md`), and with it
the page total, which
the type budgets cannot all meet at once (6 + 10 + 25 KB of gzip is more than the 40 KB total); the
OpenStreetMap tile policy for the deployed app.

| Step | What | State |
|---:|---|---|
| 0 | Before measurements and screenshots | done ([`screens/`](screens/), `eval/results/web-vitals.md`) |
| 1 | The budget gate, its tests, `make web-budget`, the CI step | done |
| 2 | `app.js` split into ES modules, no visible change | done |
| 3 | Font subset and coverage check, Tabler sprite, favicon, notices | done (Source Sans 3; 51 glyphs, 32 waiting for steps 5, 7 and 8) |
| 4 | `tokens.css` and three stylesheets replace `style.css`; token scripts | done |
| 5 | Markup: topbar, hero with the pen figure, ruler, workspace, footer | done; MapLibre moved out of `<head>` into a loader with SRI hashes (step 8 keeps the rest) |
| 6 | The pen line, the ruler, `hero.js` | done, without the "paper advance" (redraws in place) and the ruler's slide (marks jump) |
| 7 | Answers: sheet, rows, stamps, per-kind renderers, loading states | not in the tree |
| 8 | Lazy map with SRI, calm tiles, double-edged markers | not in the tree |
| 9 | Server: gzip and cache headers | half: `Cache-Control: no-cache` on the page's own files is in the tree (with the review fixes); gzip is not |
| 10, 11 | Route ribbons, the air forecast line | not in the tree |
| 12 | Verification: every state in both themes and widths, Lighthouse, screen readers | not in the tree |
| 13 | Arrivals line strip | optional |
