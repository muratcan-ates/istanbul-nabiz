# Hat düzenliliği / Per-line reliability

Derived entirely from vehicle positions this project archived; İETT publishes no headway or
bunching data. Built by `scripts/reliability_report.py`, no network access.

- Observation span: **2026-09-08 20:30 (TRT) → 2026-09-13 18:23 (TRT)** (117.9 h wall-clock, 2 calendar day(s): 2026-09-08, 2026-09-13)
- Vehicle snapshots read: **6,358** across lines 15F, 34, 500T
- Cells published: **15** of 39; **24** refused for want of observations
- Cells whose cv exceeds its own sampling floor (i.e. irregularity that missed passages alone cannot explain): **3** of 15
- Arrival resolution: **~3.2 min** (one collector tick)

Hours are İstanbul local time (UTC+3).

## Measured cells

| Hat | Saat | Ortanca aralık | cv | cv tabanı | Taban üstü | Kümelenme | Filo | Durak | Aralık gözlemi | Yakalama | Durak/sa | km/sa |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 34 | 12:00 | 9.6 dk | 0.727 | 0.705 | evet | kümelenme var | 23 | 27 | 102 | %50 | 37.1 | 37.7 |
| 34 | 13:00 | 12.9 dk | 0.721 | 0.698 | evet | kümelenme var | 15 | 37 | 102 | %51 | 32.8 | 39.4 |
| 34 | 21:00 | 16.1 dk | 0.478 | 0.676 | hayır | biraz düzensiz | 8 | 22 | 51 | %54 | 34.2 | 38.1 |
| 500T | 10:00 | 9.6 dk | 0.442 | 0.809 | hayır | biraz düzensiz | 30 | 76 | 155 | %35 | 38.3 | 30.9 |
| 500T | 11:00 | 12.8 dk | 0.505 | 0.802 | hayır | biraz düzensiz | 33 | 107 | 291 | %36 | 35.8 | 31.0 |
| 500T | 12:00 | 12.9 dk | 0.585 | 0.799 | hayır | biraz düzensiz | 32 | 116 | 335 | %36 | 35.6 | 32.3 |
| 500T | 13:00 | 12.9 dk | 0.519 | 0.777 | hayır | biraz düzensiz | 32 | 111 | 317 | %40 | 32.9 | 25.8 |
| 500T | 14:00 | 16.0 dk | 0.584 | 0.76 | hayır | biraz düzensiz | 31 | 109 | 294 | %42 | 30.3 | 25.1 |
| 500T | 15:00 | 16.0 dk | 0.59 | 0.767 | hayır | biraz düzensiz | 33 | 108 | 306 | %41 | 31.5 | 24.7 |
| 500T | 16:00 | 12.9 dk | 0.588 | 0.764 | hayır | biraz düzensiz | 34 | 110 | 313 | %42 | 30.9 | 25.6 |
| 500T | 18:00 | 9.8 dk | 0.571 | 0.776 | hayır | biraz düzensiz | 33 | 54 | 102 | %40 | 36.8 | 24.9 |
| 500T | 20:00 | 6.4 dk | 0.888 | 0.796 | evet | kümelenme var | 35 | 47 | 99 | %37 | 34.1 | 26.9 |
| 500T | 21:00 | 12.8 dk | 0.647 | 0.787 | hayır | kümelenme var | 33 | 91 | 308 | %38 | 40.3 | 28.4 |
| 500T | 22:00 | 15.5 dk | 0.644 | 0.797 | hayır | kümelenme var | 27 | 95 | 261 | %36 | 42.6 | 30.3 |
| 500T | 23:00 | 22.0 dk | 0.403 | 0.815 | hayır | biraz düzensiz | 16 | 72 | 117 | %34 | 48.7 | 31.1 |

## Refused cells — what the archive cannot support yet

| Hat | Saat | Aralık gözlemi | Filo | cv'li durak | Yakalama | Neden |
|---|---|---|---|---|---|---|
| 15F | 10:00 | 3 | 5 | 0 | %36 | Yeterli gözlem yok: 3 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 15F | 11:00 | 33 | 5 | 0 | %38 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 12:00 | 42 | 5 | 0 | %44 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 13:00 | 43 | 5 | 0 | %46 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 14:00 | 50 | 5 | 0 | %50 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 15:00 | 49 | 7 | 1 | %54 | Düzenlilik ölçülemedi: yalnızca 1 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 16:00 | 45 | 5 | 0 | %56 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 17:00 | 4 | 5 | 0 | %48 | Yeterli gözlem yok: 4 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 15F | 18:00 | 0 | 5 | 0 | %55 | Yeterli gözlem yok: 0 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 15F | 20:00 | 1 | 5 | 0 | %36 | Yeterli gözlem yok: 1 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 15F | 21:00 | 20 | 5 | 0 | %40 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 22:00 | 15 | 3 | 0 | %36 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 15F | 23:00 | 10 | 2 | 0 | %30 | Yeterli gözlem yok: 10 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 34 | 10:00 | 0 | 1 | 0 | %53 | Bu saatte yalnızca 1 araç gözlendi; iki ardışık aracın aynı durağa varışı olmadan sefer aralığı hesaplanamaz. |
| 34 | 11:00 | 10 | 7 | 1 | %50 | Yeterli gözlem yok: 10 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 34 | 14:00 | 16 | 3 | 0 | %58 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 34 | 15:00 | 0 | 2 | 0 | %55 | Yeterli gözlem yok: 0 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 34 | 16:00 | 12 | 6 | 0 | %57 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 34 | 17:00 | 4 | 10 | 0 | %38 | Yeterli gözlem yok: 4 sefer aralığı ölçülebildi, en az 12 gerekiyor. Toplayıcı bu hattı bu saatte daha uzun süre izlediğinde dolacak. |
| 34 | 18:00 | 31 | 11 | 3 | %52 | Düzenlilik ölçülemedi: yalnızca 3 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 34 | 20:00 | 13 | 7 | 0 | %50 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 34 | 22:00 | 26 | 5 | 0 | %52 | Düzenlilik ölçülemedi: yalnızca 0 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |
| 34 | 23:00 | 0 | 1 | 0 | n/a | Bu saatte yalnızca 1 araç gözlendi; iki ardışık aracın aynı durağa varışı olmadan sefer aralığı hesaplanamaz. |
| 500T | 17:00 | 61 | 36 | 2 | %36 | Düzenlilik ölçülemedi: yalnızca 2 durakta en az 3 ardışık varış görüldü, en az 5 durak gerekiyor. |

## How to read this

- **cv** is the coefficient of variation of the headways at a stop, `std/mean`, taken per stop (minimum 3 gaps) and then medianed across at least 5 stops. 0 is a perfectly even service; 1 is the cv of a Poisson process, i.e. arrivals that carry no information about each other.
- Bands: `< 0.3` düzenli · `0.3–0.6` biraz düzensiz · `≥ 0.6` kümelenme var.
- A cell needs at least 12 headway observations, 5 stops with a cv, two distinct vehicles and a capture rate of 25%. Below any of those it reports no number at all.
- **Yakalama** (capture) is measured, not assumed: when a bus advances three stop positions between two ticks it passed three stops and we witnessed one, so `steps / stops advanced` is the share of stop passages this sampling rate can see.
- **cv tabanı** is the cv a *perfectly regular* line would still show at that capture rate, `sqrt(1 - capture)`. Compare it with the measured cv before believing a bunching verdict.

## What this measurement can and cannot say

1. **Quantisation.** Arrivals are located to one collector tick (~3.2 min), so headways come out as multiples of it. Read a median of 12.9 min as "about 13", never as 12.9.
2. **The cv is an upper bound, and the bound is wide.** A bus that passes a stop between two ticks is never seen there and its two headways merge into one double gap, which raises both the median headway and the cv. The capture column says how often that happens — line-wide it is under half — so treat the headway as an over-estimate and the cv as an over-estimate. The `cv tabanı` column is the floor this produces on a perfectly regular line. Measured cvs sitting *below* their floor are not a contradiction: a stop only enters the cv when it yielded three witnessed arrivals in the hour, which selects exactly the stops where buses dwell and are easy to catch, so their local capture is much better than the line average. It does mean that comparing one line's cv against another's is not yet safe — comparing hours within one line is.
3. **Samples are correlated.** Two buses running nose-to-tail generate a short headway at every stop they pass, so `Aralık gözlemi` is not an independent sample count — `Araç` and `Durak` are the honest bound on how much was really seen.
4. **This is not a typical week.** 2 calendar day(s) of partial collection covering the hours in the table above. A cell says what happened on those days at that hour, not what happens every Tuesday. Hours nobody collected simply do not appear.
5. **Direction matters and is kept.** Headways are computed per (line, direction, stop); the two directions of a line are never mixed.

Not affiliated with İBB or İETT. Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı, İBB Açık Veri Lisansı (CC BY 4.0).
