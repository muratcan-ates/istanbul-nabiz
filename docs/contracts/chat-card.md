# ChatCard v1 · sohbet kartı sözleşmesi

Bir yetenek, yanıtın altında düz veri taşıyan bir kart üretir. Sunucu `final.cards` alanını bir liste olarak gönderir; alan yoksa istemci boş liste kabul eder. Bir yanıtta en çok **6** kart bulunur. Kart, sohbet veya mesaj kimliği olmadan sunucudan çıkar; istemci çizerken `message_id` ekler, P02 yerel geçmişe kaydederken `conversation_id` ekler. Kartın kimliği aynı işlem boyunca aynı kalır. Kart HTML, komut veya çalıştırılabilir adres taşımaz.

```json
{"v": 1, "id": "card-route-7f3a", "conversation_id": null, "message_id": null,
 "type": "route", "status": "ready", "title": "Kadıköy → Levent, merdivensiz",
 "body": {"from": "Kadıköy", "to": "Levent",
          "steps": ["M4 Kadıköy yönü ...", "Ayrılık Çeşmesi'nde Marmaray ..."],
          "unknown_segments": ["Levent çıkışında asansör kaydı yok"]},
 "sources": [{"label": "Metro İstanbul asansör kaydı", "url": null,
              "source_time": "2026-09-27T09:20:00+03:00", "freshness": "kayitli"}],
 "source_time": "2026-09-27T09:20:00+03:00", "linked_id": null,
 "actions": ["expand_map", "listen"], "sensitive": false}
```

Bu bir **yapı örneğidir**, doğrulanmış bir yolculuk önerisi değildir. `unknown_segments` doluysa “Bilinmeyen bölüm” başlığı altında her zaman görünür; bilinmeyen erişim erişilebilir sayılmaz. Örnek kaynak satırının görünümü: “Metro İstanbul asansör kaydı · kayıtlı · 27.09 09:20”. Kayıtlı veriye “canlı” denmez.

## Alanlar ve sınırlar

| Alan | Kural |
|---|---|
| `v` | Şimdilik `1`. İstemci başka sürümü eylemsiz yedek görünümde ele alır. |
| `id` | Kararlı kart kimliği. Sunucuda verilmezse temizlenmiş `type`, `title`, `linked_id` birleşiminin UTF-8 baytlarından FNV-1a 32 bit ile `card-<type>-<8 hex>` üretilir. İşlem kimliği olan yetenekler `card_id` vermelidir. |
| `conversation_id`, `message_id` | Sunucuda `null`; yerel sohbet kaydı ve çizim sırasında doldurulur. |
| `type` | `route`, `map`, `event`, `calendar_draft`, `photo_report`, `status`, `info`, `memory`. Bilinmeyen tür yalnız başlık ve kaynaklarla güvenli yedeğe düşer. |
| `status` | `preparing`, `needs_input`, `ready`, `awaiting_confirmation`, `done`, `unavailable`, `error`. Durum bir işlem sonucunu kendi başına kanıtlamaz. |
| `title` | En çok 120 karakter düz metin. |
| `body` | Türe özgü düz JSON nesnesi. Diziler en çok 20 öğe, dizeler en çok 600 karakter; iç içe veri sınırlanır. HTML etiketleri ve çalıştırılabilir içerik temizlenir. |
| `sources` | En çok 20 kaynak: `{label, url, source_time, freshness}`. `url` yalnız geçerli `https://` adresi veya `null`; `source_time` zaman dilimli ISO 8601 veya `null`; `freshness` `guncel`, `kayitli`, `tarife`, `dogrulanamadi` değerlerinden biri. |
| `source_time` | Kartın en eski geçerli kaynak zamanı; yaş bununla gösterilir. Kaynaklar ve üst alan arasında daha eski geçerli zaman seçilir. |
| `linked_id` | Bağlı olay veya işlem kimliği ya da `null`. |
| `actions` | Aşağıdaki kapalı listeden eylemler. Uygun olmayan eylem düğmesi hiç çizilmez. |
| `sensitive` | Hassas kart işareti. Yeniden açılışta eylemsizdir; operatöre, takvime veya Outlook'a otomatik gönderilmez. |

Sunucu `nabiz.console.chat_cards.card(...)` ile üretir, `validate_card(raw)` ile sınırlar ve `cards_field(items)` ile en çok altı farklı kimliği `final.cards` alanına koyar. Doğrulanamayan sunucu kartı atılır. İstemci, dışarıdan gelen bozuk veya bilinmeyen kartı sohbeti durdurmadan güvenli yedekte gösterir. Bilinmeyen üst alanlar atılır. Kaynak adresi güvenli değilse bağlantı kaldırılır; `open_official` için en az bir geçerli HTTPS kaynak adresi gerekir.

## Eylemler ve sonuç

Kapalı eylem listesi: `use_location`, `type_place`, `expand_map`, `listen`, `remember_here`, `remember_always`, `change`, `forget`, `save_calendar`, `export_ics`, `review_report`, `send`, `open_official`. İstemci kart düğmesinden `nabiz:card-action` olayını `{card_id, type, action, message_id, conversation_id}` verisiyle yayınlar. Aynı `card_id` ve eylem işlenirken ikinci basış yok sayılır. Kaydedilmiş tur açıldığında yalnız `expand_map`, `listen`, `open_official` eylemleri kalır. Hassas kartta düğme çizilmez.

`done` yalnız işlem durumudur; kesin sonuç `body.result` alanında belirtilir. Bilinen sonuçlar `saved_nabiz`, `ics_downloaded`, `outlook_added`, `report_sent`. “Takvim dosyası indirildi” ve “Outlook'a eklendi” ayrı sonuçlardır. Eylem hiçbir zaman model metnindeki HTML veya komuttan türetilmez.

## Türe özgü `body` önerisi ve sahiplik

| Tür | Önerilen alanlar | Veri/çizici sahibi |
|---|---|---|
| `route` | `from`, `to`, `steps[]`, `unknown_segments[]` | P03 rota verisi ve çizicisi |
| `map` | `points[{lat,lon,label}]`, `bbox` | P03 harita verisi; P01 küçük harita kabuğu |
| `event` | `starts_at`, `ends_at`, `all_day`, `place`, `district` | P05 etkinlik |
| `calendar_draft` | `event_id`, `starts_at`, `ends_at`, `all_day`, `place`, `result` | P06 takvim |
| `photo_report` | `report_id`, `state`, `result` | P07 bildirim |
| `status` | `text` | P01 ortak çizici; alan sahibi gerçek durumu sağlar |
| `info` | `text` | P01 ortak çizici; alan sahibi içeriği sağlar |
| `memory` | `key`, `label`, `kind` | P02 hafıza önerisi |

Bir türün çizicisi henüz kayıtlı değilse başlık ve kaynaklar okunabilir kalır. Kart metni DOM'a `textContent` olarak yazılır. Tür eklemek veya alan kaldırmak için `v` artırılır; aynı sürümde alan silinmez. Yeni isteğe bağlı alanlar eski istemci tarafından yok sayılabilir.
