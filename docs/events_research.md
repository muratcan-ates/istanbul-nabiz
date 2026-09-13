# Epic E3 — Can Nabız recommend İBB events?

**Verdict: no. İBB publishes no machine-readable, forward-looking events feed under an open licence.**
E3 is not buildable as specified. What shipped instead is an honest refusal plus a documented plug point:
`src/ibb_mcp/sources/events.py` returns `available: false` with the evidence below attached, and
`EventsFeedAdapter` is the one class a future feed would need.

| | |
|---|---|
| Researched | **2026-09-13** (single session) |
| Researcher | feature chat `feat/events` |
| Budget spent | 8 web requests; **1** call to `api.ibb.gov.tr`, made through `PoliteClient` (6 s/host spacing honoured) |
| Confidence in the verdict | **High** for "no open, machine-readable feed exists". **Medium** for "no undocumented API exists" — see §5 |
| Re-check trigger | §7 |

---

## 1. What was checked

| # | Candidate | URL | Format | Licence | Freshness | Key needed | Verdict |
|---|---|---|---|---|---|---|---|
| 1 | Metro İstanbul **Event List** (`GetActivities`) | `https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetActivities` | JSON API | İBB Açık Veri Lisansı (CC BY 4.0) | **stale — newest record 2026-02-05** | no | ❌ **press-release archive, not a calendar** |
| 2 | Portal search `q=etkinlik` | `https://data.ibb.gov.tr/api/3/action/package_search?q=etkinlik` | 8×XLSX + 1×API | İBB Açık Veri Lisansı | annual | no | ❌ aggregate past counts |
| 3 | Portal search `q=kültür sanat takvim` | same host | — | — | — | — | ❌ **0 results** |
| 4 | Every API-format dataset on the portal | `.../package_search?fq=res_format:API` | 41 datasets | İBB Açık Veri Lisansı | live | no | ❌ all transport / traffic / air quality |
| 5 | **kultur.istanbul** | `https://kultur.istanbul/etkinlikler/` | HTML (WordPress) | © 2026, *all rights reserved* | live, real calendar | no | ❌ no feed, closed licence |
| 6 | **kultursanat.istanbul** (İBB Kültür Sanat) | `https://kultursanat.istanbul/etkinliklerimiz` | HTML | © İBB, *tüm hakları saklıdır* | empty when checked | no | ❌ no feed, closed licence |
| 7 | **İstanbul Senin** super-app (İBB Etkinlik mini-app) | `https://istanbulsenin.istanbul/` | mobile app | app ToS | live | app login | ❌ no published developer API |

The brief named `ibbkultursanat.istanbul`; that name does not resolve to a separate service — the İBB
Kültür Sanat site is `kultursanat.istanbul` (row 6), which is what was checked.

---

## 2. The one real candidate, and exactly why it fails

`GetActivities` is the single result on the whole open-data portal that is (a) an API, (b) about
*etkinlik*, and (c) under the İBB Açık Veri Lisansı. It is registered as dataset
`ab12b2fd-d2d0-469f-b88e-177fcba10a34`, titled "Metro Istanbul Event List", described as *"This web
service returns the Metro Istanbul event list."* On the strength of that description it looks like the
feed E3 needs. It is not.

It was called once, live, on 2026-09-13 through `PoliteClient`. `HTTP 200`, 632 303 bytes,
`{Success: true, Error: null, Data: [...]}`, **168 records**. Every record has exactly seven fields:

```
Id · Title · Content (HTML) · Photo · StartDate · Language · Media{Video,Images}
```

Four independent reasons this cannot back an event recommendation, in descending order of severity:

1. **`StartDate` is a publication date, not an event date.** Record 141 is stamped `2025-11-20` and is
   titled *"29 Mayıs'ta Edirnekapı'dan Saraçhane'ye Yürüyoruz"*. Several other records share that same
   `2025-11-20` stamp while describing events on 30 Ağustos and 29 Ekim. No date filter over this field
   could ever be truthful — which is disqualifying on its own, because "bu akşam ne var" *is* a date filter.
2. **Nothing is forward-looking.** Dates run 2017-05-14 → 2026-02-05; **zero** records are dated after
   today. The distribution by year is 2017:1, 2018:6, 2019:28, 2020:31, 2021:35, 2022:31, 2023:21,
   2024:7, 2025:7, 2026:1 — a feed that was maintained until ~2022 and has since been abandoned. The
   newest record is **seven months old**.
3. **No place.** No venue, district, coordinate, station, end time, category, price or ticket field.
   "Yakınımda ne var" and "Kadıköy'de bu hafta" are unanswerable; the E3 requirement for
   nearest-to-a-place cannot be met from these fields at any quality.
4. **It is corporate PR, not programming.** The content is awards, ridership milestones and executive
   visits (e.g. a SODEV award for the women train-driver programme). 120 records are `TR` and 48 are
   `EN` translations of the same items. Only 3 of 168 titles contain any event keyword at all
   (*konser / sergi / festival / tiyatro / söyleşi / atölye / gösteri*), and two of those are metaphors.

Reproduce the probe (this is one gateway request — do not loop it):

```bash
cd ~/code/istanbul-nabiz && .venv/bin/python - <<'PY'
import asyncio, sys; sys.path.insert(0, "src")
from ibb_mcp.http import PoliteClient
async def main():
    async with PoliteClient() as c:
        d = await c.get_json("https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetActivities",
                             source="metro_activities")
        rows = d["Data"]
        print(len(rows), sorted({k for r in rows for k in r}),
              max(r["StartDate"] for r in rows))
asyncio.run(main())
PY
```

A three-record slice of the capture is pinned in `tests/test_events.py` as `GETACTIVITIES_SAMPLE`, with
tests asserting each of points 1–3. The finding is therefore reproducible from the repository without a
network call, and if anyone later proposes wiring this endpoint up, the test says why not.

---

## 3. The events data that *does* exist, and who owns it

İstanbul's municipal event calendar is real and rich — it is simply not open data.

* **kultur.istanbul** is the live calendar (filters by event type, venue and category). It runs on
  WordPress. Its `robots.txt` is permissive (`Disallow: /wp-admin/` only, no sitemap) so `/etkinlikler/`
  is crawlable in the robots sense. But the operator is **İstanbul Kültür ve Sanat Ürünleri Ticaret A.Ş.**
  — a *commercial* İBB subsidiary, not the municipality — and the footer reads `© 2026 KÜLTÜR.İSTANBUL
  – All rights reserved`. It is outside the İBB Açık Veri Lisansı entirely.
* **kultursanat.istanbul** is the İBB-operated sibling. `© ... tüm hakları İstanbul Büyükşehir
  Belediyesi'nde saklıdır`, with a membership agreement and a KVKK notice. It showed
  *"Toplam 0 etkinlik gösteriliyor"* when checked on 2026-09-13, which may be a seasonal or transient
  state — it does not change the licence answer either way.
* **İstanbul Senin** carries the "İBB Etkinlik" and "İBB Kültür" mini-apps, where registration and free
  tickets actually happen. This is the authoritative surface, and it is exactly the thing NABIZ.md §4
  warns about: İBB's own super-app already owns this journey. No developer API or documentation was
  found; app traffic was **not** inspected, because reverse-engineering an app's private endpoints
  breaches its terms and is not something this project will ship.

---

## 4. What it would take to build E3 for real

Three routes, ranked by whether this project may actually take them.

| Route | What is needed | Permitted? | Cost | Recommendation |
|---|---|---|---|---|
| **A. Partnership / data share** | İBB Kültür A.Ş. or the Açık Veri team publishing a JSON or iCal feed, ideally as a new portal dataset | Yes — the correct route | Weeks of correspondence; not a sprint item | **Ask for it.** A concrete request for "an `etkinlik` dataset with title, start, end, venue, district, lat/lon, category, URL" is a legitimate and useful outcome of this project, and worth a slide in the demo |
| **B. Key / registered API** | An İstanbul Senin or Kültür A.Ş. developer credential | No such programme found | — | Blocked; revisit only if one is announced |
| **C. Scraping kultur.istanbul** | An HTML parser behind `PoliteClient` | **No — do not do this** | Low technical cost, high legal and reputational cost | **Rejected**, see below |

### Why scraping is rejected, specifically

`robots.txt` permits crawling. That is not the question. Three things say no:

1. **Licence.** The pages are `All rights reserved` and belong to a commercial company. This repo is
   public, MIT, and ships an attribution line claiming İBB Açık Veri Lisansı (CC BY 4.0) on its data.
   Republishing a closed-licence calendar through an MCP server, under that attribution, would make the
   project's single most important claim — *every number is sourced and licensed* — false.
2. **Positioning.** Nabız's pitch to İBB Bilgi İşlem is that it is a well-behaved citizen of their
   infrastructure: one rate-limited client, under their budget, stopping before they do. A scraper of a
   sister company's website contradicts that pitch in the same breath as it is made.
3. **Fragility.** An unversioned HTML scrape breaks silently on a theme change and would produce
   *wrong event times*, which is worse than no events at all — the ETA epic already taught this project
   what an unfalsifiable number costs.

If the owner ever decides to scrape anyway, the adapter interface is the place it goes, and
`EventsFeedAdapter.license` must carry the true string (`"© KÜLTÜR.İSTANBUL — all rights reserved"`),
so the false-attribution problem surfaces in the provenance stamp rather than hiding.

---

## 5. Confidence and limits of this research

* **High confidence** that no open, machine-readable, forward-looking events feed exists: the portal's
  *complete* list of 41 API datasets was enumerated, not sampled, and the only event-titled entry in it
  was pulled and inspected record by record.
* **Medium confidence** that no *undocumented* endpoint exists. Three things were deliberately not done:
  the İstanbul Senin app's traffic was not intercepted (§3), `api.ibb.gov.tr` was not probed for
  unlisted paths (that is exactly the request burst that 503s the gateway for every consumer), and the
  portal was not searched in every possible synonym — `etkinlik`, `kültür sanat takvim` and the full
  API-format list were the three queries the budget allowed.
* `kultursanat.istanbul` returning zero events on the day of the check is a **low-confidence
  observation** about that site's state, and nothing is concluded from it.
* Everything above was read on **2026-09-13**. Portal contents change; the code prints this date beside
  the refusal so a user can see how old the "no" is.

---

## 6. What was built instead

`src/ibb_mcp/sources/events.py`:

* `EventsSource(ctx)` — with no adapter, `search()`, `near()` and `availability()` all return
  `available: false`, a Turkish reason, an English reason, an **empty** event list, the check date, and
  the `evidence` table from §1 as structured records. Its provenance carries `license="n/a — veri
  döndürülmedi"`: stamping İBB's open-data licence on a payload that contains no İBB data would be a
  false citation, which is the specific failure this whole epic was about avoiding.
* `Event` — the model a feed must fill: `start` is UTC-aware, and a feed that cannot supply `start` plus
  either `district` or `lat`/`lon` is not good enough to recommend from.
* `EventsFeedAdapter` — the plug point (`name`, `source_url`, `license`, `async fetch()`), with the
  house rules written into its contract: go through `PoliteClient`, raise `UpstreamUnavailable` rather
  than returning `[]` for a failure (an outage must never render as "bugün etkinlik yok"), and declare
  the feed's *true* licence.
* Filtering, Turkish-folded district/category/title matching, İstanbul-calendar-day date ranges, and
  nearest-to-a-place ranking are implemented and tested against a fake adapter, so plugging in a real
  feed is one class, not an epic. Events with no coordinate are excluded from `near()` and counted in
  `without_coordinates` rather than being placed at a district centroid.

**`src/` contains no event records, and a test enforces that.**

---

## 7. When to re-check

Re-run §1 if any of these happen:

* the portal gains a dataset matching `etkinlik`/`kültür` with `res_format` `API`, `JSON` or `ICS`
  (a one-request check: `package_search?q=etkinlik&fq=res_format:API`);
* İBB announces a developer programme for İstanbul Senin;
* `GetActivities` starts returning future-dated records **with a venue field** — the endpoint is real
  and maintained infrastructure, so a schema change is the most likely way this verdict flips.

Until one of those is true, the honest answer to "bu akşam ne var?" is a pointer to
kultur.istanbul — which is what the tool now returns.
