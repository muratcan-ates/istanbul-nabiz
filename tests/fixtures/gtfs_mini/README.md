# `tests/fixtures/gtfs_mini/` — a 38 KB cut of İETT's GTFS export

The full export lives in `data/reference/gtfs/`. It is about 180 MB and gitignored, so CI
never has it. Every test that quietly relied on it passed locally and failed on every push.
This folder holds a few hundred real rows from that export, enough for the stop search, the
arrival estimate and the off-route refusal to run the same code paths they run in production.

| File | Rows | What it holds |
|---|---|---|
| `routes.csv` | 31 | all 27 variants of 500T, plus `8A_G_D0`, `14ŞB_G_D0`, `153_G_D0` and `25S1_G_D0` |
| `trips.csv` | 6 | the longest trip of each of those last four and of `500T_G_D0` / `500T_D_D0` |
| `stop_times.txt` | 273 | every call of those six trips (64 + 66 + 38 + 62 + 24 + 19) |
| `stops.csv` | 291 | every stop those trips call at, every stop the recorded 500T vehicles report as nearest, every stop whose name contains "Kadıköy" (27) or "Şifa" (17), two extra stops with no `stop_code` and one whose coordinate cannot be repaired |

Row counts are from `extract.py`'s own output on 2026-09-23.

## What this fixture covers

- **500T runs Şifa Sondurak ↔ 4.Levent Metro and does not serve Kadıköy.** Of the 27 stops
  whose name contains "Kadıköy", none is on either 500T sequence. So "500T at Kadıköy" is a
  real off-route question, not one staged for the test, and the tool has to refuse it.
- **"Kadıköy", "Şifa" and "Şifa Sondurak" get the same top five stops as they do against the
  full index.** That is why every name match is kept. For "Kadıköy" the first hit is
  `202951`, a `KADIKÖY` stop signed "direction: HACIKÖY" that no trip in the export serves.
  For "Şifa" it is `116301`, a stop in Sarıyer that 500T never reaches. Only the full name
  "Şifa Sondurak" finds 500T's terminus `401351`.
- **Other lines call at two of the stops 500T skips**, so a refusal has something honest to
  suggest: 8A and 14ŞB at the pier platform `406031`, and 153 and 25S1 at `116301`. `14ŞB` is
  stored mojibaked in `routes.csv` (`14ÅžB_G_D0`), so the suggestion only reads correctly if
  the route-code repair works.
- **`build_stop_sequences` on this folder returns the same six sequences the full export
  returns.** `extract.py` checks this every time it writes the fixture.

## İBB quirks kept on purpose

Rows are copied byte for byte and never re-serialised, because the loaders exist to repair
these quirks and a cleaned-up fixture would not test them:

- `stops.csv`, `routes.csv` and `trips.csv` are `;`-separated UTF-8 with a BOM and CRLF line
  endings.
- Coordinates carry thousands separators: `410.191.700.005.564` means `41.0191700005564`.
- Route codes and names are double-encoded (mojibake), including bytes cp1252 cannot hold.
- Three stops have an empty `stop_code` (`stats()["stops_without_code"] == 3`), and one
  stop's coordinate cannot be repaired, so the loader drops it (`stats()["stops_dropped"] == 1`).
- `stop_times.txt` is the complete ZIP variant: comma-separated, no BOM. The truncated
  `stop_times.csv` is left out. It stops at Excel's 1,048,575-row limit and has no 500T rows.

## Regenerating

```bash
.venv/bin/python tests/fixtures/gtfs_mini/extract.py          # rewrite from data/reference/gtfs
.venv/bin/python tests/fixtures/gtfs_mini/extract.py --check  # exit 1 if the committed files differ
```

`extract.py` reads local files only and never calls the network. It needs the full export
in `data/reference/gtfs/` (`stops.csv`, `routes.csv`, `trips.csv` and the ZIP's
`stop_times.txt`). To keep a new stop name searchable, add its folded form to
`STOP_NAME_TOKENS`. To keep a new line's sequence, add its route code to
`SEQUENCE_ROUTE_CODES`.

The tests never read this folder in place. `tests/conftest.py` copies it into a temporary
directory once per session. `load_stop_sequences` writes its `route_sequences.json.gz`
cache next to the tables, and that cache must not appear in the repository.

## Source and licence

- **Source:** İETT GTFS data, İBB Açık Veri Portalı —
  <https://data.ibb.gov.tr/dataset/iett-gtfs-verisi>. The CSV resources were downloaded on
  2026-09-08, the date the loaders' join keys were verified. This subset was cut on 2026-09-23.
- **Licence:** İBB Açık Veri Lisansı ([CC BY 4.0](https://data.ibb.gov.tr/license)).
  Contains public sector information from the İstanbul Metropolitan Municipality Open Data
  Portal. / Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı.
- **Changes from the source:** rows were selected as described above. No values were edited.
