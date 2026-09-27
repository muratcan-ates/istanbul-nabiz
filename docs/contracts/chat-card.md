Tek kaynak: nabiz-plan/2026-09-27/gpt-paketler/SOZLESME-sohbet-karti-v0.md (v0.1)

# ChatCard v1 · sohbet kartı sözleşmesi

Sunucu `final.cards` alanında en çok 6 düz veri kartı gönderir. Alan yoksa istemci boş liste kabul eder. Sunucudan çıkan kartta `conversation_id` ve `message_id` `null` olur; P01 çizimde mesaj kimliğini, P02 yerel kayıtta sohbet kimliğini ekler. P01'in `validate_card`, `from_v0`, `card` ve `cards_field` işlevleri bu sınırı uygular. Bilinmeyen üst alanlar atılır; bozuk kimlikli kart sunucuda atılır. İstemci bozuk veya bilinmeyen sürümü başlık ve kaynaklarla eylemsiz güvenli yedekte gösterir.

```json
{"v":1,"id":"card-route-7f3a","conversation_id":null,"message_id":null,
 "type":"route","status":"ready","title":"Kadıköy → Levent, merdivensiz",
 "body":{"from":"Kadıköy","to":"Levent","legs":[{"kind":"ride","title":"M4 Kadıköy yönü ...","detail":null,"minutes":null,"lift_text":null}],"unknown_segments":["Levent çıkışında asansör kaydı yok"]},
 "sources":[{"label":"Metro İstanbul asansör kaydı","url":null,"source_time":"2026-09-27T09:20:00+03:00","freshness":"kayitli"}],
 "source_time":"2026-09-27T09:20:00+03:00",
 "linked":{"event_id":null,"report_code":null,"operation_id":null},"linked_id":null,
 "actions":[{"id":"expand_map","label":"Haritayı büyüt","kind":"view","requires_consent":false,"operation_id":null},{"id":"share","label":"Paylaş","kind":"external","requires_consent":true,"operation_id":null}],"sensitive":false}
```

Bu yapı örneği doğrulanmış yolculuk önerisi değildir. `unknown_segments` doluysa “Bilinmeyen bölüm” her zaman gösterilir; bilinmeyen erişim erişilebilir sayılmaz. Kaynak görünümü: “Metro İstanbul asansör kaydı · kayıtlı · 27.09 09:20”. Kayıtlı veriye canlı denmez.

## Alanlar ve sınırlar

| Alan | Kural |
|---|---|
| `v` | Çıktı `1`; `v:0` girdi `from_v0()` ile dönüştürülür. |
| `id` | Aynı işlemde aynı kalır. Verilmezse temizlenmiş `type`, `title`, `linked_id` birleşiminin UTF-8 baytlarıyla FNV-1a 32 bit özeti `card-<type>-<8 hex>` olur. İşlem sahibi mümkünse kararlı `card_id` verir. |
| `type` | `route`, `map`, `event`, `calendar_draft`, `photo_report`, `status`, `info`, `memory`. |
| `status` | `preparing`, `needs_input`, `ready`, `awaiting_confirmation`, `done`, `unavailable`, `error`. Durum tek başına sonucu kanıtlamaz. |
| `title` | En çok 120 karakter düz metin. |
| `body` | Türe özgü JSON nesnesi; dize en çok 600, dizi en çok 20 öğe. HTML ve betik temizlenir. `result` aşağıdaki kapalı listededir. |
| `sources` | En çok 20 `{label,url,source_time,freshness}`; URL yalnız güvenli HTTPS veya `null`, zaman saat dilimli ISO 8601 veya `null`, tazelik `guncel`, `kayitli`, `tarife`, `dogrulanamadi`. |
| `source_time` | Üst alan ve kaynaklar arasındaki en eski geçerli zaman; yaş bununla gösterilir. |
| `linked`, `linked_id` | `linked` içinde `event_id`, `report_code`, `operation_id` anahtarlarından en çok biri dolu. `linked_id` bundan `event:<id>`, `report:<code>`, `op:<id>` biçiminde türetilir. Eski önekli `linked_id` girdisi kabul edilir. |
| `actions` | En çok 4 nesne; kapalı eylem listesinden. Eski dize girdisi kabul edilir, çıktı nesnedir. |
| `sensitive` | Sağlık veya refakat beyanı gibi hassas veri. Yalnız `view` eylemleri kalır; dışarı otomatik gönderilmez. Yeniden açılışta geri yükleme süzgeci de uygulanır. |

## Eylem, onay ve sonuç

`kind` yalnız `view`, `device`, `nabiz`, `external` olur. `view` görünümü değiştirir, `device` bu cihaza yazar, `nabiz` sunucuya yazar, `external` dışarı çıkar. `kind` tablodan alınır. Üretici `requires_consent` değerini `true` yapabilir; tablodaki `true` değerini düşüremez. `label` en çok 40 karakterdir. Bilinmeyen eylem düğme olmadan atılır; istemci kartta desteklenmeyen işlem durumunu gösterir. Tekrarlı kanonik eylem bir kez kalır.

| `id` | `kind` | Taban `requires_consent` |
|---|---|---|
| `use_location` | device | true |
| `type_place` | view | false |
| `expand_map` | view | false |
| `listen` | view | false |
| `remember_here` | device | true |
| `remember_always` | device | true |
| `change` | view | false |
| `forget` | device | false |
| `save_calendar` | nabiz | true |
| `export_ics` | device | false |
| `review_report` | view | false |
| `send` | nabiz | true |
| `open_official` | external | false |
| `add_outlook` | external | true |
| `confirm_resolved` | nabiz | true |
| `reopen` | nabiz | true |
| `cancel` | nabiz | true |
| `appeal` | nabiz | true |
| `share` | external | true |

| Girdi takma adı | Kanonik `id` |
|---|---|
| `add_calendar` | `save_calendar` |
| `download_ics` | `export_ics` |
| `open_map` | `expand_map` |
| `remember` | `remember_here` |

Çıktıda takma ad kalmaz. `open_official` yalnız geçerli HTTPS kaynak URL'si varsa kalır. Geri yüklenmiş kartın eylemleri yalnız `expand_map`, `listen`, `open_official` olur; `share` düşer. Hassas kartta yalnız `kind: view` kalır.

Onay isteyen eylemin ilk basışı işi başlatmaz. İstemci “neyi, nereye” açıklamasıyla `Onayla` ve `Vazgeç` gösterir; `nabiz:card-action` olayını ancak onaydan sonra `consented_at` ile yayınlar. `memory` kartında işaretsiz kutular ve `Hatırla` düğmesi bu adımın yerini alır. Sunucu `nabiz` veya `external` yazma ucunda `consent: true` ve işlem kimliğini yeniden denetler. `view` ve `device` eylemlerinde `operation_id: null`; `nabiz` ve `external` için üretici biliyorsa yazar, bilmiyorsa istemci çizimde `"op-" + sha256(card.id + "\0" + action.id + "\0" + message_id)` ilk 16 hex ile kararlı biçimde türetir. Sonuç kartındaki `linked.operation_id` aynı kimliği taşır. İkinci istek ilk sonucu döndürür; ikinci kayıt açmaz.

`body.result` kapalı listesi: `null`, `saved_nabiz`, `ics_downloaded`, `outlook_verifying`, `outlook_added`, `outlook_failed`, `report_sent`, `resolution_confirmed`, `reopened`, `cancelled`, `appeal_sent`. Bilinmeyen değer `null` olur. `done` sonucu kanıtlamaz: Outlook'a eklendi yalnız doğrulanmış `outlook_added`, dosya indirildi yalnız `ics_downloaded`, çözüldü yalnız vatandaş teyidi `resolution_confirmed` ile söylenir.

## v0 dönüşümü

`from_v0` ve istemcideki eşleniği `source` + `data.sources[]` girdisini `sources[]` alanına çevirir: `name → label`, `observed_at → source_time`; kart zamanı en eski geçerli gözlemdir. `data → body`. `linked` nesnesi korunur ve `linked_id` türetilir. Eylem nesnelerinin `label`, `requires_consent` ve `operation_id` bilgisi korunur; takma ad kanonikleştirilir, `kind` ve taban onay tabloya göre düzeltilir. `v:0` üreticilerinin `id` değeri korunur. Bilinmeyen üst alanlar atılır.

## Türe özgü `body` önerisi ve sahiplik

| Tür | Önerilen alanlar | Veri/çizici sahibi |
|---|---|---|
| `route` | `from`, `to`, `needs[]`, `legs[{kind,title,detail,minutes,lift_text}]`, `unknown_segments[]`, `street_geometry`, `provider`, `sample`, `disclaimer` | P03 rota ve harita |
| `map` | `points[{lat,lon,label,kind}]`, `bbox`, `layer`, `category`, `stale` | P03 harita; P01 küçük kart kabuğu |
| `event` | `event_id`, `date`, `starts_at`, `ends_at`, `all_day`, `time_known`, `place`, `district`, `free`, `url`, `captured_at` | P05 etkinlik |
| `calendar_draft` | `plan_id`, `title`, `date`, `starts_at`, `ends_at`, `all_day`, `tz`, `place`, `reminder_minutes`, `result`, `outlook_web_link` | P06 takvim taslağı |
| `photo_report` | `report_code`, `photo_code`, `category`, `place`, `state`, `waiting_on`, `timeline[]`, `has_photo`, `simulated` | P07 bildirim |
| `status` | `text`, `state`, `as_of`, `waiting_on` | P08 durum ve itiraz; P01 ortak çizici |
| `info` | `text`, `citations[{sentence,source_name,url}]`, `uncertainty[]` | İçerik sahibi; P01 ortak çizici |
| `memory` | `key`, `label`, `kind`, `scope_options`, `items[]` | P02 hafıza |

`map.layer` değerleri `stations`, `lifts`, `ibb_places`, `route`, `reports`; en çok 60 nokta. `route.unknown_segments` erişimi bilinmeyen bölümleri her zaman açıkça gösterir. `memory.kind: health` her zaman hassastır; sohbetten yalnız `change` görünüm eylemiyle Hesabım › Hafızam sağlık formuna götürülür, kayıt orada ayrı açık onayla yapılır. Kart metni DOM'a `textContent` ile yazılır. Bir türün çizicisi henüz yoksa başlık ve kaynaklar okunabilir kalır.
