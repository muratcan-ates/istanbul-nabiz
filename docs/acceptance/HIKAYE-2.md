# Hikâye 2 · Hafızadan etkinlik ve takvim

29 Eylül gösteriminin ikinci hikâyesi. Kişi Kadıköy'de yaşıyor, bebek arabasıyla geziyor; Nabız bunu kendi
sözlerinden hatırlamayı öneriyor, kişi onaylıyor. Hafta sonu için kaynaklı bir etkinlik seçip takvimine ekliyor.

Otomatik testler: [`tests/acceptance/test_story_2.py`](../../tests/acceptance/test_story_2.py). Tarihli etkinlik
listesi, takvim dosyası ve hesap silmede rezervasyon temizliği P00 G4 ile gelir; sohbetin kendi hafıza kartı
P02 ile (başka dalda, bu şeridin testleri onu kapsamaz). Etkinlik dosyası `data/reference/etkinlik/` altındaki
referans veridir; bulut kopyasında yoktur, bu yüzden G4 testleri veri yokken dürüst boş cevabı, veri varken
tarihli ve kaynaklı listeyi iddia eder. Ölçüt numaraları [`DEMO-KABUL.md`](DEMO-KABUL.md) §1'dekilerdir.

| # | Kullanıcı eylemi (telefon 375 px / masaüstü 1280 px) | Beklenen görünür sonuç | Kanıt türü | Ölçüt |
|---|---|---|---|---|
| 1 | Masaüstünde (1280 px) sayfayı açar, yeni bir sohbet başlatır. | Boş sohbet; "Resmi İBB hizmeti değildir" satırı görünür. Başka bir sohbetin geçmişi bu sohbete taşınmaz. | test `test_two_conversations_share_nothing_on_the_server` (sunucu tarafı); Claude tarayıcı (P01 sohbet kabuğu: sohbet listesi, yeniden açma) | 2, 12 |
| 2 | "Kadıköy'de bugün açık kütüphane var mı?" diye ilçe kartından sorar. | Kütüphane ve müzeler, "Kayda göre şu an açık · kapanış 21.00" gibi kayda dayalı durumla; saat kayıtta yoksa "Çalışma saati kayıtta yok". "Canlı" denmez. | test `test_venue_hours_are_read_from_the_record_never_called_live` | 5 |
| 3 | **Kaynak yokluğu:** kayıtta olmayan bir ilçe adı yazar ("Atlantis"). | "Bu ilçe adı kayıtlarda yok." En yakın ilçe tahmin edilmez. | test `test_an_unknown_district_is_refused_not_guessed` | 5 |
| 4 | İki ayrı mesajda bebek arabasıyla gezdiğini yazar. | İlk mesajda öneri yok; ikincide "Hatırlayayım mı? · Bebek arabası". Kişi "Evet" demeden sunucu da cihaz da saklamaz; yeni sohbette öneri kendiliğinden gelmez. | test `test_memory_is_offered_after_two_asks_and_never_kept_by_the_server`; Claude tarayıcı ("Evet" sonrası yalnız bu cihazın profili) | 3 |
| 5 | Profilinde bir sağlık ifadesi varmış gibi sayfa bir "diyabet" anahtarı gönderir. | Modele yalnız işlevsel kısıt ("bebek arabasıyla yolculuk") gider; sağlık sözcüğü hiçbir model çağrısında yoktur. | test `test_a_health_word_in_the_profile_never_reaches_the_model` | 3 |
| 6 | Bugün için etkinlikleri ister (G4 gün planı). | Kaynaklı liste: her kartta kultur.istanbul bağlantısı ve tarih metni, listenin yakalanma zamanı ve "eski" etiketi; veri yoksa "Etkinlik verisi henüz yok." Geçmiş etkinlik sayılır ama listelenmez. | test `test_events_for_a_day_are_dated_sourced_and_never_past` (P00 G4 sonrası) | 5 |
| 7 | **Düzeltme:** "Cumartesi olsun" der; sayfa tarihi cumartesiye çevirir. | Liste cumartesinin listesidir; başlıktaki tarih değişir. | test `test_cumartesi_olsun_moves_the_list_to_that_day` (P00 G4 sonrası); Claude tarayıcı (tarih seçici) | 5, 6 |
| 8 | Dünün tarihini seçmeye çalışır. | "Bugünden 30 gün sonrasına kadar bir tarih seçin."; geçmiş bir etkinlik gelecek gibi listelenmez. | test `test_a_past_day_never_lists_events_as_coming` (P00 G4 sonrası) | 5 |
| 9 | **Kaynak yokluğu (tutar):** "Konserin bilet fiyatı kaç lira?" diye sorar. | Sayı yok; 153 ve ilgili kurumun resmî sayfası önerilir. | test `test_a_fee_question_about_an_event_is_not_answered_with_a_number` | 9 |
| 10 | Bir etkinlikte "Takvime ekle"ye basar, telefonunda dosyayı açar. | `nabiz-gun-plani.ics` iner: başlangıç UTC olarak (İstanbul saatinden çevrilmiş) ya da tüm gün; dosyada e-posta, telefon, konum yok; yanıt önbelleğe alınmaz. Nabız'ın planı ile telefonun takvimi (Outlook, iOS) ayrı kalır: biri silinince öteki silinmez. | test `test_the_calendar_file_is_istanbul_time_personal_data_free_and_not_cached` (P00 G4 sonrası; bulutta "not run: veri yerelde"); Murat telefon (Outlook ya da iOS takvimi) | 6 |
| 11 | "Takvime ekle"ye art arda iki kez basar. | Aynı `UID` ile aynı etkinlik: takvimde çift kayıt oluşmaz. | test aynı (iki yanıtın `UID` satırları eşit) | 6 |
| 12 | **Kesinti (ağ):** ağ kesikken "Takvime ekle"ye basar, ağ gelince yeniden dener. | Önce "Takvim dosyası indirilemedi."; yeniden denemede dosya iner, tek etkinlik olarak. | Claude tarayıcı (Playwright çevrimdışı modu, sonra yeniden deneme) | 6, 11 |
| 13 | "Unut" der; profilinden bebek arabasını kaldırır. | Sonraki turlarda öneri kendiliğinden gelmez, cevaplar kısıt olmadan kurulur; sunucuda silinecek bir şey yoktur. | test `test_s9_forgetting_is_the_device_dropping_the_need_and_the_server_follows`; P02 hafıza kartı için Claude tarayıcı | 3 |
| 14 | Örnek hesabını siler. | Silme yanıtı neyi sildiğini sayar: hesap, takip konuları, e-posta önizlemeleri ve `bookings_deleted`. | test `test_deleting_the_account_reports_its_bookings_deleted` (P00 G4 sonrası) | 3, 12 |

## Bu hikâyede bilinen açıklar

- `bookings_deleted` alanı bugün hiçbir dalda yok (`gun3/*` dallarında aranıp bulunamadı). P00 G4 bu alanı
  eklemezse adım 14'ün testi G4 birleştiği anda kırmızıya döner; bu bilerek böyle bırakıldı.
- Sohbetin kendi hafıza kartı (P02) ve sohbet listesi (P01) bu şeridin kapsamı dışında; adım 1, 4 ve 13'ün
  arayüz kısmı tarayıcıda doğrulanır.
- "Takvime ekle", "Takvim dosyası indirilemedi." metinleri `gun3/etkinlik-planlayici` dalındaki
  `static/js/day_plan*.js` dosyalarından alındı.
