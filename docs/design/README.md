# Web UI design: screenshots, gates and module layout

Working notes for the web redesign ("Nabız çizgisi"). **[`DESIGN.md`](DESIGN.md) is the design itself**:
colour theory, tokens, type, icons, the signature line, honesty and accessibility rules, budgets and the
plan. Section numbers below (§15, §18, §20) are the full spec's. This folder holds what the redesign
produces that is not code: screenshots, and later the annotated token file (§4, step 4).

| Path | What |
|---|---|
| `DESIGN.md` | the approved design, public and short |
| `screens/before-*.png` | the page on `main` at `d59b5a8`, before any redesign step (step 0) |
| `screens/after-*.png` | the page as the tree has it after the latest landed step (step 2 and the review's fixes today); not pictured in the README until step 5 |
| `../../eval/results/web-vitals.md` | bytes, requests and Web Vitals before and after each step |
| `../../scripts/check_web_budget.py` | the gate for §15 (FE-MOD, FE-OPT): `make web-budget`, and a CI step |
| `../../scripts/design/screens.mjs` | the screenshot driver described below |

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
  view) and `nomap-parking` (`?nomap=1`, then the parking chip, scrolled to the answer and the list
  that replaces the map). New states are one line each in the script's `STATES` table.
- **Start the app fresh before a first-view shot.** The "Veri tazeliği" strip shows what the server
  has fetched since it started, so a warm server's first view is not a first view.
- **Dark:** the script emulates `prefers-color-scheme: dark` over the DevTools protocol. The page's
  own switch is `localStorage["nabiz-theme"] = "dark"`, which sets `<html data-theme="dark">`; §20 asks
  for both once the redesign lands. From the command line, `--force-dark-mode` gives the same media
  query (checked 2026-09-23).
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

The after set so far is two first-view shots, `after-first-1440-light.png` and `after-first-390-dark.png`,
retaken on 2026-09-23 on a freshly started app with steps 0 to 2 and the same day's review fixes in the
tree. Step 2 alone changed nothing visible (its shots differed from the before set in 89 and 88 pixels, the
brand mark's animated dot, compared with Pillow's `ImageChops.difference`). The review fixes do show in a
first view: the light theme's secondary grey is darker (`#78849a` to `#5f6b7f`, for 4.5:1), the brand
mark's stroke uses the accent's ink in the dark theme, and the brand sub-line wraps on a phone instead of
being cut. The old look (crimson accent, gradient heading, uppercase labels) stays until steps 4 and 5, so
the README shows no screenshot until then. Each later step replaces these and adds its states.

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
`--strict` so that a new entry needs a visible CI edit too. One target is not a step's to meet: the JS
gzip budget (see `eval/results/web-vitals.md`), raised once on 2026-09-23 for the review's fixes.

## Module layout (step 2)

`static/app.js` became native ES modules under `static/js/`, moved verbatim: every line of the old
file is in exactly one module, and `route()` is byte-identical. The only new code is
`forceMapOff()` in `map.js`, because a module cannot assign another module's variable.

| Module | Holds | Pure |
|---|---|---|
| `main.js` | boot: theme, chips, form, polls | |
| `journeys.js` | question to endpoint to renderer, `run()`, the loading state | |
| `errors.js` | a failure rendered as an answer, with the last-known ages | |
| `api.js` | `api`, `apiPost`, `probe` | |
| `map.js` | MapLibre, markers, the list fallback | |
| `freshness.js`, `alerts.js`, `reliability.js`, `theme.js` | the strip and pill, the stored subscription, headway regularity, the theme | |
| `motion.js` | scripted motion (a smooth scroll, the map's easing) that stops under reduced motion; added with the review's fixes | |
| `router.js` | the keyword router | yes |
| `format.js`, `provenance.js`, `icons.js` | formatting, age stamps and source links, `icon(name)` | yes |
| `cards/{shell,parking,transit,metro,environment,route}.js` | the card renderers | yes |

Pure modules touch no DOM, network, storage or clock and import only pure modules, so node imports
them in tests (`tests/test_web.py` imports `js/router.js`). `static/js/package.json` holds only
`{ "type": "module" }`: it tells node these `.js` files are ES modules, so the tests do not depend on
a node version that detects module syntax by itself. Browsers ignore it.
