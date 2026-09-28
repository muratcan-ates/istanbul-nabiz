# Sayfa kataloğu: altı yeni dil (P14 hazırlık)

Bu klasör vatandaş sayfasının arayüz kataloğunu altı yeni dile hazırlar: Almanca, Rusça, Arapça, Farsça,
Fransızca, İspanyolca. Dosyalar **sayfaya bağlı değil**: `static/` dışında durdukları için sunucu servis etmez,
`js/i18n.js` onları tanımaz. Bağlamayı P00 yapar (aşağıda). 10 dilli acil kart bu işin dışında ve aynen kalır
([acil-inceleme.md](acil-inceleme.md)).

Kaynak metin [`tr.json`](../../src/nabiz/console/static/i18n/tr.json), anlam kontrolü
[`en.json`](../../src/nabiz/console/static/i18n/en.json); ikisi de 73b798c'de 381 düz anahtar (sayım:
`python -c "import json; print(len(json.load(open('src/nabiz/console/static/i18n/tr.json'))))"`).

## Durum

| Dil | Dosya | Yön | Durum |
|---|---|---|---|
| Deutsch | [de.json](de.json) | ltr | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |
| Русский | [ru.json](ru.json) | ltr | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |
| العربية | [ar.json](ar.json) | rtl | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |
| فارسی | [fa.json](fa.json) | rtl | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |
| Français | [fr.json](fr.json) | ltr | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |
| Español | [es.json](es.json) | ltr | makine çevirisi · insan incelemesi bekliyor · inceleyen: ___ |

İnceleyen alanına yalnız kişinin izin verdiği ad ya da takma ad yazılır; e-posta yazılmaz (depo herkese açık).

## Kurallar ve onları tutan kontrol

[`tests/test_lang_staging.py`](../../tests/test_lang_staging.py) her dosya için şunları sınar:

- geçerli JSON; anahtar kümesi ve sırası `tr.json` ile birebir aynı; `meta.lang` dosya adı, `meta.dir` ar ve fa
  için `rtl`, diğerleri için `ltr`;
- boş değer yok; liste değerleri kaynakla aynı uzunlukta (`page.chat_hint` 8, `page.attribution` 3,
  `page.about` 10, `privacy.band` 3): `i18n.js` bunları `segments` kipinde metin düğümü metin düğümü yazar;
- `tr.json`'daki her yer tutucu (`{count}`, `{lang}` ...) ve HTML etiketi hedefte de var, fazlası yok;
  İBB, İETT, Metro İstanbul, İSKİ, İGDAŞ, Nabız, 153 ve 112 kaynakta geçtiği her değerde korunuyor;
- U+2014 ve U+2013 yok;
- [`rtl.css`](../../src/nabiz/console/static/css/rtl.css) yalnız `[dir="rtl"]` ya da `:dir(rtl)` kapsamlı
  kurallar içeriyor ve 300 satırı aşmıyor.

Makine kontrolü olmayan kurallar (inceleme): resmî hitap (de "Sie", fr "vous", es "usted", ru "Вы"; ar ve fa'da
acil kartla aynı kip); "canlı/live" karşılığı yok; kurum adları çevrilmez.

## Bilinçli sapmalar

İnceleyen geri alabilir; her biri kaynaktan farklı yazıldı ve nedeni burada.

1. **`dynp.live`**: "canlı" karşılığı kullanılmadı; altı dilde "güncel veri" yazıyor (Aktuelle Daten, Текущие
   данные, بيانات حالية, داده‌های جاری, Données actuelles, Datos actuales). `tr.json` ve `en.json` "Canlı veri" /
   "Live data" diyor; önek yalnız kaynak modu `live` olan alıntıda çıkıyor (`js/answer_actions.js`). Bu
   dillerde de "canlı" denmesi owner kararı.
2. **`page.arrival_hint`**: kart metni Türkçe kalıyor (`i18n.js` `#arrival`'ı `EXCLUDED` listesinde tutar ve
   `lang="tr"` verir), bu yüzden etiketler Türkçe tırnakta, çevirisi parantezde: «tarifeye göre» (…),
   «doğrulanamadı» (…).
3. **`page.follow_hint`**: takip isteği yalnız Türkçe ve İngilizce anlaşılıyor (`src/nabiz/console/follow.py`,
   `_CUES`). Örnek komutlar bu yüzden «M2 hattını takip et» ve «Follow the M2 line»; metin "Türkçe ya da
   İngilizce isteyin" diyor.
4. **`page.open_data_placeholder`, `ui.od.hint`**: katalog araması İBB'nin Türkçe başlıklarında sözcük eşler
   (`src/ibb_mcp/catalog.py`, çeviri ya da eşanlamlı yok). Örnek sözcükler Türkçe kaldı (otopark, baraj, wifi) ve
   ipucu "katalog Türkçe" diyor. `en.json`'daki "parking, dam, wifi" örneğinin eşleşip eşleşmediği denenmedi
   (not run: sapma bu klasörle sınırlı, `en.json` P14'ün dosyası değil).
5. **`page.places_legend`**: `tr.json` değeri "Kayıtlı yerlerim İstasyon Ekle Hat Ekle" (legend'in iç metni
   birleşmiş görünüyor); `en.json` gibi yalnız "Kayıtlı yerlerim" çevrildi. Anahtar `BINDINGS`'te yok.
6. **153 Çözüm Merkezi**: acil kartın `line153` karşılıklarıyla aynı çizgide betimleyici ad ve numara (de
   "Bürgerservice 153 der İBB", fr "centre de services 153 de l'İBB" ...).
7. **Segment sınırları**: `writeText` özgün metin düğümünün baş ve son boşluğunu korur, değere boşluk eklenmez.
   Fransızca ve Farsçada cümle bu sınırlara göre kuruldu: fr'de segment başında ";" yerine "." (Fransızca ";"
   öncesi boşluk ister); fa'da fiil sonda olduğu için "برای گفتگو با یک انسان: شماره 153" etiket kalıbı. TİD
   bağlantısını taşıyan `span[data-pending]` gizliyken de cümle tamamlanıyor.
8. **Rusça sayı-isim uyumu**: sayılı cümleler "ad: {n}" kalıbında (`ui.follow.moved`, `ui.opq.queue_status`,
   `ui.od.matches` ...), çünkü Rusçada ismin hâli sayıya göre değişir.
9. **Arapça**: Modern Standart Arapça, eril tekil emir kipi (acil kartla aynı), Batı rakamları.

## Nasıl bağlanır (P00 notu)

1. Katalogları taşı: `git mv docs/i18n/<dil>.json src/nabiz/console/static/i18n/<dil>.json` (altısı için).
2. `src/nabiz/console/static/js/i18n.js`:
   - `export const LANGS = Object.freeze(['tr', 'en']);` →
     `export const LANGS = Object.freeze(['tr', 'en', 'de', 'ru', 'ar', 'fa', 'fr', 'es']);`
   - hemen altına: `export const RTL_LANGS = Object.freeze(['ar', 'fa']);`
   - `setDirection` içinde `root.lang = language; root.dir = 'ltr';` →
     `root.lang = language; root.dir = RTL_LANGS.includes(language) ? 'rtl' : 'ltr';`
   - `mountLanguageGroup` içinde, "·" ayırıcısını ekleyen `if` bloğundan sonra:
     `for (const [lang, name] of [['de', 'Deutsch'], ['ru', 'Русский'], ['ar', 'العربية'], ['fa', 'فارسی'], ['fr', 'Français'], ['es', 'Español']]) addLanguageButton(group, lang, name);`
3. `src/nabiz/console/static/js/i18n_text.js` (yoksa dinamik metinler Türkçe kalır):
   - `activeLanguage = language === 'en' ? 'en' : 'tr';` →
     `activeLanguage = typeof language === 'string' && language ? language : 'tr';`
   - `const translated = activeLanguage === 'en' ? activeCatalog[key] : null;` →
     `const translated = activeLanguage === 'tr' ? null : activeCatalog[key];`
   - `callback(event.detail && event.detail.lang === 'en' ? 'en' : 'tr')` →
     `callback((event.detail && event.detail.lang) || 'tr')`
4. `src/nabiz/console/static/index.html`: `<link rel="stylesheet" href="/css/workspace.css">` satırının altına
   `<link rel="stylesheet" href="/css/rtl.css">` (her kural RTL kapsamlı, LTR'de etkisiz). `kolay.html`'e de
   `kolay.css` satırının altına aynı satır.
5. `src/nabiz/console/static/sw.js`: `VERSION` `'v17'`; SHELL'deki
   `'/js/i18n.js', '/js/i18n_text.js', '/i18n/tr.json', '/i18n/en.json',` satırının altına
   `'/i18n/de.json', '/i18n/ru.json', '/i18n/ar.json', '/i18n/fa.json', '/i18n/fr.json', '/i18n/es.json', '/css/rtl.css',`
6. DECISIONS #35'in çitlerini tutan testler bağlama ile kırmızıya döner ve #35'i güncelleyen yeni maddeyle
   birlikte değişmeli: `tests/test_i18n.py` (`test_arabic_is_not_supported_and_falls_back_to_turkish`'te
   `ar.json`, `rtl.css` ve Arapça harf yasağı; `LANGS` regex'i ve `"rtl" not in source`; `ar.json` ve
   `rtl.css` için 404; `pickLang`'de `ar` ve `fr`'nin "desteklenmeyen" örneği; `test_i18n_js_holds_no_copy`
   "Français"taki ç'yi Türkçe harf sayar) ve `tests/test_pwa_static.py` (SHELL'de `ar.json` ve `rtl.css`
   yasağı). **Bugün bile**: `rtl.css`'in var olması `test_arabic_is_not_supported_and_falls_back_to_turkish`
   ve `test_catalogs_and_modules_are_served`'ı kırmızı yapar (bkz. P14 teslim notu).

## RTL notları

- `<html dir>`'i `setDirection` ayarlar; `rtl.css`'in her kuralı `[dir="rtl"]` ya da `:dir(rtl)` kapsamlı, sayfa
  LTR iken hiçbir kural eşleşmez.
- Betikle sonradan eklenen sayfalar (`service_status.css`, `operator_requests.css`, `easy_read.css`,
  `emergency.css`) `rtl.css`'ten sonra gelir; her ters çevirme kaynak seçiciyi yön kapsamıyla tekrar eder ve
  sıradan değil özgüllükten kazanır.
- Oklar (`chevron-right`, `arrow-right`, `arrow-narrow-right`) `scale: -1 1` ile aynalanır; `scale` `transform`'dan
  önce uygulandığı için açık bölümün oku yine aşağı bakar, hover itmesi okuma yönüne gider. Seçici ikonun
  ebeveyninde `:dir(rtl)` kullanır: `dir="ltr"` işaretli Türkçe bir blok içindeki ok dönmez. `:dir()`'i
  desteklemeyen tarayıcıda oklar dönmez, düzen yine RTL olur (not run: tarayıcı matrisi denenmedi).
- Arapça ve Farsça harfler bitişik yazılır: eksi `letter-spacing` taşıyan başlıklar RTL'de 0'a çekilir.
- Türkçe kalan bölgeler: `i18n.js` `#cards`, `#arrival`, `#alternative`, `#compare-result`'a `lang="tr"` verir
  ama `dir` vermez; RTL sayfada bu Türkçe metinler sağa yaslanır. Alıntılara `frameQuotes` zaten `dir="ltr"`
  veriyor; bu dört bölgeye de RTL dilde `dir="ltr"` verilip verilmeyeceği P00 kararı.
- Kullanıcının yazdığı metin (`#chat-input`, `.chat-text`) zaten `dir="auto"`.
- Rakamlar bütün dillerde Batı rakamı (0-9), acil kartla aynı. Yer tutucuya giren hat adı, kod ve sayılar
  Arapça ve Farsça cümle içinde LTR parça olarak kalır.
- fa: yarım boşluk (ZWNJ, U+200C) kullanıldı; Farsça ی ve ک harfleri. ar: Arapça ي ve ك harfleri. (Harf
  karışması teslimde betikle denetlendi, testte değil.)
- Sayfa yazı tipi `system-ui` (`css/tokens.css` `--font-sans`); Kiril, Arapça ve Farsça glifler sistem
  fontundan gelir.
- Harita (Leaflet) RTL sayfada denenmedi (not run: tarayıcıda görsel kontrol yapılmadı).
