# Hikâye 3 · Fotoğraf, örnek operatör, vatandaşta sonuç

29 Eylül gösteriminin üçüncü hikâyesi. Kişi kırık bir kaldırımın fotoğrafını çekip rızasıyla bildiriyor; örnek
(simüle) operatör bildirimi görüp yanıtlıyor; kişi sonucu aynı koddan okuyor.

Otomatik testler: [`tests/acceptance/test_story_3.py`](../../tests/acceptance/test_story_3.py). Taban (`73b798c`)
döngüyü metinle zaten kapatıyor (`/api/requests`); fotoğraflı bildirim, zaman çizgisi ve operatör kapısının
önbelleğe alınmayan 401'leri P00 G2 ile gelir. Asansör bildirimi ile sonuç kodu akışı ayrıca
[`tests/test_report_outcome.py`](../../tests/test_report_outcome.py) içinde uçtan uca test ediliyor. Ölçüt
numaraları [`DEMO-KABUL.md`](DEMO-KABUL.md) §1'dekilerdir.

| # | Kullanıcı eylemi (telefon 375 px / masaüstü 1280 px) | Beklenen görünür sonuç | Kanıt türü | Ölçüt |
|---|---|---|---|---|
| 1 | Telefonda (375 px) "Bildir"i açar. | Kategori, yer (ilçe ya da istasyon), açıklama, fotoğraf ve rıza kutusu; "Resmi İBB hizmeti değildir" ve operatörün simüle olduğu yazar. | Claude tarayıcı (375 px ekran görüntüsü) | 7, 12 |
| 2 | **İzin reddi:** rıza kutusunu işaretlemeden gönderir. | Gönderim reddedilir; "Talebi iletmek için onay kutusunu işaretleyin."; kod verilmez, operatör kuyruğunda hiçbir şey yoktur. | test `test_no_consent_no_record` (taban), `test_a_photo_report_needs_consent_and_gets_one_code_without_the_photo` (P00 G2 sonrası) | 7 |
| 3 | Telefonun galerisinden desteklenmeyen biçimde bir dosya seçer (GIF, HEIC). | "Yalnız JPEG, PNG ya da WebP fotoğraf seçin."; hiçbir şey kaydedilmez. | test `test_an_unsupported_file_is_refused_with_a_plain_reason` (P00 G2 sonrası); Murat telefon (gerçek HEIC dosyası) | 7 |
| 4 | Gerçek bir JPEG ile, açıklamaya telefon numarasını da yazarak rızayla gönderir. | Tek bir kod; açıklamadaki numara `[TELEFON]` olarak maskelenmiş; vatandaşın kartında fotoğraf baytı ya da fotoğraf adresi yok; saklama bitişi (`expires_at`, 30 gün) kartta. | test `test_a_photo_report_needs_consent_and_gets_one_code_without_the_photo` (G2), `test_one_code_carries_the_request_to_the_operator_and_the_reply_back` (taban, metinle); Murat telefon (gerçek telefon fotoğrafı) | 7, 8 |
| 5 | **Düzeltme (yanlış konum):** yeri yanlış yazar ("Atlantis"), sonra "kadıköy" diye düzeltir. | Önce "İlçe bulunamadı; listeden seçin ya da istasyon seçin."; düzeltmede kabul edilir ve yer "Kadıköy" olarak yazılır. | test `test_a_wrong_place_is_refused_then_the_corrected_one_is_taken` (P00 G2 sonrası) | 7 |
| 6 | Konum bilgisi (GPS) gömülü bir fotoğraf gönderir. | Saklanan fotoğrafta EXIF ve konum yoktur; operatörün gördüğü görüntüde de yoktur. | `gun3/fotografli-bildirim` dalının `tests/test_photo_image.py::test_magic_dimensions_and_cleaned_metadata` testi (G2 ile gelir); Murat telefon (GPS'li fotoğraf) | 7 |
| 7 | Masaüstünde (1280 px) operatör konsolunu anahtar olmadan açmaya çalışır, sonra anahtarla girer. | Anahtarsız 401 "Konsol için operatör girişi gerekli." ve yanıt önbelleğe alınmaz; anahtarla kuyruk açılır. | test `test_the_operator_door_is_shut_without_the_token` (taban), `test_s8_the_operator_side_is_shut_without_the_token`, `test_operator_refusals_are_not_cached` (P00 G2 sonrası) | 8 |
| 8 | Operatör bildirimi açar, yanıt taslağını düzenler ve gönderir. | Kuyrukta maskeli metin; gönderilen yanıt kayda geçer. İnsan taslağı düzenler ve onaylar; model yanıtı kendisi göndermez. | test `test_one_code_carries_the_request_to_the_operator_and_the_reply_back` | 8 |
| 9 | Vatandaş telefonda aynı kodu açar. | Durum yanıtlanmış (`answered`); "Bu yanıt bir İBB çalışanı tarafından yazıldı." ve "Prototip: operatör rolü simüledir; resmî İBB hizmeti değildir." birlikte görünür. Zaman çizgisi yalnız gerçek bir kodu açar. | test aynı; `test_the_timeline_opens_only_a_real_code` (P00 G2 sonrası) | 8 |
| 10 | Rastgele bir kod dener (başkasının bildirimi). | "Talep bulunamadı ya da 30 günlük saklama süresi doldu."; hiçbir içerik görünmez. | test `test_a_guessed_code_opens_nothing` | 7, 8 |
| 11 | Açıklamaya "Yangın var, binada duman" yazar. | Bildirim kuyruğa girmez; "lütfen hemen 112'yi arayın" ve 112 bağlantısı gelir. | test `test_an_emergency_goes_to_112_and_never_waits_in_the_queue` | 10, 11 |
| 12 | **Kesinti (model):** Almanca bir talep gönderir, çeviri modeli yanıt vermez. | Talep yine iletilir; "Çeviri şu an yok · orijinal metin (model yanıt vermedi)" etiketiyle, operatör orijinal metni görür. | test `test_a_model_outage_keeps_the_original_text_and_says_there_is_no_translation` | 9, 11 |
| 13 | Açıklamada gereksiz bir sağlık ayrıntısı yazar ("Diyabetim var…"). | Sağlık ayrıntısı operatöre geçmez. **Bugün geçiyor:** strict xfail. | test `test_a_health_detail_the_operator_does_not_need_is_not_passed_on` (strict xfail) | 3 |
| 14 | Gösteri makinesi yeniden başlatılır, vatandaş kodunu yeniden açar. | Aynı kart, aynı yanıt; kayıtlar yeniden başlatmada korunur. | test `test_a_restart_keeps_the_request_and_its_reply` | 12 |
| 15 | Vatandaş fotoğraflı bildirimini siler. | Silme onayı (`{"deleted": true}`); aynı kod artık açılmaz (404). | test `test_a_photo_report_needs_consent_and_gets_one_code_without_the_photo` (G2, silme sonrası 404) | 7 |

## Bu hikâyede bilinen açıklar

- Adım 13: talep maskesi (`pii_guard`) kimlik numarası, telefon ve e-postayı gizliyor, sağlık durumunu
  gizlemiyor. Ölçüt 3'ün "operatöre gereksiz sağlık ayrıntısı geçmez" kısmı bugün karşılanmıyor.
- Adım 7: belirteçsiz 401'lerde `Cache-Control: no-store` başlığı tabanda da `gun3/fotografli-bildirim` dalında
  da yok; P00 G2 kapıya (`app.py` `_gate` ya da `access.py`) eklemezse test G2 birleşince kırmızıya döner.
- Fotoğrafın kendisi ve metadata temizliği bu şeridin testlerinde değil, G2 dalının kendi testlerinde.
