# Hikâye 1 · Erişilebilir yolculuk ve ses

29 Eylül gösteriminin ilk hikâyesi. Kişi tekerlekli sandalye kullanıyor; Kadıköy'den Levent'e merdivensiz
gitmek istiyor, konum iznini vermiyor, yerini yazıyor, adımları sesle dinleyip durduruyor.

Otomatik testler: [`tests/acceptance/test_story_1.py`](../../tests/acceptance/test_story_1.py). Tabanda
(`73b798c`) olmayan uçların testleri P00 G1 ve G3 birleşince kendiliğinden açılır; o zamana kadar
`P00 G<n> bağlanınca açılır` nedeniyle atlanır. Ölçüt numaraları [`DEMO-KABUL.md`](DEMO-KABUL.md) §1'dekilerdir.

Kanıt türleri: **test** (çevrimdışı otomatik test, adıyla), **Claude tarayıcı** (yerel Claude, Playwright ile
375 px ve 1280 px ekran görüntüsü ve DOM kontrolü), **Murat telefon** (gerçek cihazda elle).

| # | Kullanıcı eylemi (telefon 375 px / masaüstü 1280 px) | Beklenen görünür sonuç | Kanıt türü | Ölçüt |
|---|---|---|---|---|
| 1 | Sayfayı açar (375 px ve 1280 px). | Sohbet kabuğu açılır; alt satırda "Resmi İBB hizmeti değildir" ve İBB Açık Veri atfı görünür; İBB logosu yok. | Claude tarayıcı (iki genişlikte ekran görüntüsü, satırın DOM'da görünür olduğu) | 11, 12 |
| 2 | Konum izni sorulur, **reddeder**; yer alanına "Kadıköy" yazar. | Konum yerine yazılan yer kullanılır; tanınmayan bir yer yazarsa ("Zzyzx") örnek adlarla yeniden sorulur, tahmin yapılmaz. Sunucuya koordinat gitmez. | test `test_nearby_needs_a_position_the_person_chose_to_share`, `test_a_typed_place_it_does_not_know_gets_examples_not_a_guess`; Murat telefon (izin reddi gerçek tarayıcıda) | 4 |
| 3 | "Kadıköy'den Levent'e merdivensiz" yolculuğu ister. | Yol kartı ya da gerekçe: "Sirkeci istasyonundaki asansör durumu doğrulanamadı…"; kaydın yaşı, "kayıtlı" etiketi ve "Bu bir tahmindir" uyarısı görünür. Doğrulanamayan asansör "çalışıyor" diye gösterilmez. | test `test_step_free_journey_says_why_it_cannot_route_and_how_old_its_record_is` | 4 |
| 4 | Sohbette sorar: "Kartal metrosunda asansör var mı? Merdivensiz gitmem lazım". | "İBB kaydında Kartal istasyonu için asansör arızası yok" ve "listede olmayan ekipman doğrulanmış değildir" notu; kaynak ve kayıt yaşı kartta. "Çalışıyor" denmez. | test `test_the_lift_answer_quotes_the_record_and_offers_to_remember_without_saving` | 4, 9 |
| 5 | Aynı ihtiyacı ikinci kez yazar; "Hatırlayayım mı?" önerisine önce yanıt vermez, sonra "Evet" der. | Öneri çıkar; "Evet" denmeden hiçbir şey kalıcı olmaz (sunucu saklamaz, sonraki turda öneri yine gelir). "Evet" sonrası tercih yalnız bu cihazın profilindedir. | test aynı; Claude tarayıcı ("Evet" öncesi ve sonrası `localStorage`) | 3 |
| 6 | **Düzeltme:** "Kadıköy değil Kartal" yazar (tabanda eşdeğeri: "Peki Kartal'da?"). | Cevap Kartal içindir; Kadıköy tekrar edilmez, kaynaklı otopark kartı gelir. | test `test_a_follow_up_with_another_place_answers_for_that_place` (taban), `test_kadikoy_degil_kartal_moves_the_question_to_kartal` (P00 G1 sonrası) | 1 |
| 7 | "Adım adım ve sesli" açar, "Adımları getir"e basar. | Sesle okunabilir adım kartları; kartlar gerçek kayıttan gelir (`sample: false`), tazelik satırı ve uyarı görünür; yol yoksa gerekçe. | test `test_route_steps_are_the_journey_cards_and_never_a_sample` (P00 G3 sonrası) | 4 |
| 8 | "Sesli oku"ya basar, ikinci adımda "Sesi kapat"a basar (telefonda dokunarak, masaüstünde klavyeyle). | Okuma başlar; "Sesi kapat" okumayı hemen keser; düğme klavyeyle odaklanır ve ekran okuyucu adını okur. Çevrim içi seste "okunan metin tarayıcının ses sağlayıcısına gidebilir" notu görünür. | Murat telefon (gerçek ses, iOS ya da Android); Claude tarayıcı (düğmenin rolü ve adı) | 4, 11 |
| 9 | **Kesinti (ses):** sesi desteklemeyen bir tarayıcıda aynı sayfayı açar. | "Bu tarayıcıda Türkçe ses yok; adımları ekrandan okuyabilirsiniz." cümlesi; yazılı adımlar yerinde kalır, sayfa kırılmaz. | Claude tarayıcı (`speechSynthesis` kaldırılmış sayfa) | 11 |
| 10 | **Kesinti (model):** model yanıt vermezken asansör sorusunu yeniden sorar. | Cevap kurallarla gelir ve yazarı "kural" diye görünür; bekleme yok, kaynak ve yaş yine kartta. | test `test_a_model_that_does_not_answer_leaves_the_rules_answer_labelled` | 9, 11 |
| 11 | Üsküdar'da ücretsiz Wi-Fi noktalarını ister. | Kayıtlı liste "eski" (`stale: true`) etiketiyle, ya da kayıt dosyası yoksa dürüst boş cevap; "canlı" denmez. | test `test_wifi_places_are_recorded_and_marked_stale` (P00 G3 sonrası) | 4 |
| 12 | Yolculuğu kaydetmek ister; ayrı rıza kutusunu işaretlemeden, sonra işaretleyerek dener; sonra hesabı siler. | Rızasız kayıt reddedilir; rızayla kaydedilir; hesap silinince aynı e-postayla yeniden girişte kayıtlı yolculuk yoktur. | test `test_a_journey_is_kept_only_with_its_own_consent`, `test_deleting_the_account_leaves_no_saved_journey` (P00 G3 sonrası) | 3, 12 |
| 13 | Aynı akışı 1280 px'te yalnız klavyeyle ve ekran okuyucuyla yürütür; sistemde "hareketi azalt" açık. | Odak sırası mantıklı, cevaplar `aria-live` ile okunur, kontrast yeterli, animasyon yok. | Claude tarayıcı (axe taraması, odak sırası); Murat telefon (VoiceOver ya da TalkBack) | 11 |

## Bu hikâyede bilinen açıklar

- "Kadıköy değil Kartal" tabanda yanlış yere gider (`places_resolve`, Kadıköy İskele listesi). Düzeltme P00 G1'de;
  o zamana kadar gösterimde "Peki Kartal'da?" kalıbı çalışır.
- Ses (adım 8 ve 9) sunucu testi olmayan, tarayıcıda koşan bir özelliktir; kanıtı elle ve tarayıcıda alınır.
  Düğme ve uyarı metinleri `gun3/sesli-adim-rota` dalındaki `static/js/step_voice.js`'ten alındı; P00 G3 onları
  değiştirirse bu tablo da değişir.
