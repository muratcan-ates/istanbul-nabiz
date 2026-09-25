# NOTICE — Kaynak, lisans ve sorumluluk reddi

## Bu proje resmi değildir

İstanbul Nabız bağımsız bir **öğrenci projesidir**. İstanbul Büyükşehir Belediyesi (İBB),
İETT, İSPARK, Metro İstanbul veya bunların herhangi bir iştiraki tarafından
geliştirilmemiş, desteklenmemiş, onaylanmamış ve denetlenmemiştir. Bu kurumlarla hiçbir
resmi bağlantısı yoktur.

Kurum adları yalnızca verinin kaynağını doğru biçimde belirtmek için kullanılmaktadır.
Projede İBB, İETT, İSPARK veya Metro İstanbul logoları, amblemleri ya da diğer marka
öğeleri kullanılmaz.

> **This is not an official service.** İstanbul Nabız is an independent student project.
> It is not affiliated with, endorsed by, or operated by the İstanbul Metropolitan
> Municipality (İBB) or its subsidiaries. Organisation names are used only to attribute
> the source of the data.

## Veri kaynağı ve lisans

Bu proje verilerini İBB Açık Veri Portalı ve İBB açık web servisleri üzerinden alır.

> Kamu sektörü bilgilerini içerir — İBB Açık Veri Portalı, İBB Açık Veri Lisansı
> (CC BY 4.0). Lisans metni: <https://data.ibb.gov.tr/license>

> Contains public sector information from the İstanbul Metropolitan Municipality Open
> Data Portal, licensed under the İBB Open Data Licence (CC BY 4.0).

İBB Açık Veri Lisansı; verinin kopyalanmasına, yayımlanmasına, işlenmesine, başka
verilerle birleştirilmesine ve ticari ya da ticari olmayan amaçlarla kullanılmasına
atıf şartıyla izin verir. Veri "olduğu gibi" sağlanır.

Kullanılan kaynaklar:

| Kaynak | Sağlayıcı | Erişim |
|---|---|---|
| Otopark doluluk ve tarife | İSPARK | `api.ibb.gov.tr/ispark` |
| Otobüs konumları ve planlanan seferler | İETT | `api.ibb.gov.tr/iett` |
| Durak, hat ve güzergâh (GTFS) | İETT | `data.ibb.gov.tr` |
| Metro hat durumu ve istasyon bilgisi | Metro İstanbul | `api.ibb.gov.tr/MetroIstanbul` |
| Trafik yoğunluk indeksi | İBB Trafik Kontrol Merkezi | `api.ibb.gov.tr/tkmservices` |
| Hava kalitesi ölçümleri | İBB Çevre Koruma ve Kontrol Dairesi | `api.ibb.gov.tr/havakalitesi` |

Bu uçların hiçbiri kayıt, API anahtarı veya kimlik doğrulaması gerektirmez; hiçbir erişim
kısıtlaması aşılmamıştır.

## Üçüncü taraf bileşenler

Depoda üç üçüncü taraf dosya grubu vardır; her biri lisans metniyle birlikte sunulur:

| Bileşen | Kaynak | Lisans | Depodaki dosyalar |
|---|---|---|---|
| Source Sans 3 (Adobe), yazı tipi | google/fonts `ofl/sourcesans3/SourceSans3[wght].ttf`, commit `4591e3457ab8be6d70167aa6818922b91e78ab2d`, sürüm 3.052; üst kaynak <https://github.com/adobe-fonts/source-sans> | SIL Open Font License 1.1 | `src/nabiz/web/static/fonts/nabiz-sans-tr-v1.woff2` (Türkçe alt küme, 400-700 ağırlık ekseni) ve lisans metni `src/nabiz/web/static/fonts/OFL.txt` |
| Tabler Icons 3.48.0, çizgi (outline) seti | npm `@tabler/icons@3.48.0`, npm'in yayımladığı `dist.integrity` ile doğrulanmış paket; <https://github.com/tabler/tabler-icons> | MIT, Copyright (c) 2020-2026 Paweł Kuna | `src/nabiz/web/static/index.html` içindeki üretilmiş simge bloğu ve favicon, `src/nabiz/web/static/icons.svg`; lisans metni `src/nabiz/web/static/icons.LICENSE.txt` |
| DOU-Synapse retrieval patterns | <https://github.com/muratcan-ates/DOU-Synapse>, commit `2cbe1eab8ab46c5958f4d529cb9a32c0b6bb2169` | MIT, Copyright (c) 2026 Muratcan Ates | `src/ibb_mcp/knowledge/` adapted retrieval, chunking and guardrail modules |
| DOU-Synapse, arayüz kalıpları | <https://github.com/muratcan-ates/DOU-Synapse> commit `2cbe1ea`; `apps/web/lib/accessibility.ts`, `apps/web/components/accessibility-provider.tsx`, `apps/web/public/accessibility-boot.js`, `apps/web/components/chat-feedback.tsx`, `apps/web/components/chat/transcript-parts.tsx`, `apps/web/app/kvkk/page.tsx` | MIT, Copyright (c) 2026 Muratcan Ates | `src/nabiz/console/static/js/a11y.js`, `feedback.js`, `transcript.js`, `src/nabiz/console/static/css/a11y.css`, `src/nabiz/console/static/kvkk.html` (React'ten vanilla JS'e uyarlandı) |
| Leaflet 1.9.4 | npm `leaflet@1.9.4`, dağıtım dosyaları değiştirilmeden kopyalandı; <https://github.com/Leaflet/Leaflet/tree/v1.9.4> | BSD-2-Clause, <https://github.com/Leaflet/Leaflet/blob/v1.9.4/LICENSE> | `src/nabiz/console/static/vendor/leaflet/` |

Yazı tipi alt kümesi OFL'in "Değiştirilmiş Sürüm" koşulu gereği yeniden adlandırılmıştır: "Source"
lisansta Ayrılmış Yazı Tipi Adı'dır, bu yüzden alt küme kendini "Nabiz Sans TR" olarak tanıtır; telif, marka
ve lisans kayıtları korunur. Simgeler paketteki çizimlerin aynısıdır; yalnızca her birinin dış `<svg>` sarmalı
ve görünmez sınır çizgisi çıkarılmıştır. Bu dosyaları `scripts/design/build_font_subset.py` ve
`scripts/design/build_icon_sprite.py` üretir; kaynak dosyalar indirilmiş haliyle depoda tutulmaz.

Web sayfası iki bileşeni çalışma anında, ziyaretçinin tarayıcısında yükler:

| Bileşen | Kaynak | Lisans | Kullanım |
|---|---|---|---|
| MapLibre GL JS 4.7.1 | `https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/` (`maplibre-gl.min.js`, `maplibre-gl.min.css`) | BSD-3-Clause, <https://github.com/maplibre/maplibre-gl-js/blob/v4.7.1/LICENSE.txt> | harita; konumu olan ilk yanıtla, SRI özetleriyle sabitlenmiş olarak yüklenir; yüklenemezse konumlar liste olarak gösterilir |
| OpenStreetMap harita karoları | `https://tile.openstreetmap.org/` | veri ODbL 1.0, © OpenStreetMap katkıcıları; karo kullanım politikası: <https://operations.osmfoundation.org/policies/tiles/> | web ve vatandaş konsolu harita altlığı; atıf harita üzerinde |

## Sorumluluk reddi

- **Otobüs varış saatleri tahmindir.** Canlı araç konumu, durak sırası ve ilan edilen
  tarifeden hesaplanır; gerçek varış saatinden sapabilir. Yolculuk planlarken resmi
  İETT ve Metro İstanbul kaynaklarını esas alın.
- **Otopark doluluk bilgisi anlık değildir.** İSPARK verisi yaklaşık 10 dakikada bir
  güncellenir; her cevapta verinin yaşı belirtilir.
- **Hava kalitesi çıktıları sağlık tavsiyesi değildir.** Tıbbi karar için hekiminize
  ve resmi sağlık otoritelerine başvurun.
- Proje "olduğu gibi", hiçbir garanti verilmeden sunulur (bkz. `LICENSE`).

## Kişisel veri

Proje kişisel veri toplamaz, işlemez ve saklamaz.

İETT filo servisi yanıtında otobüs **plakası** yer alır. Bu alan istemci katmanında
ayrıştırma sırasında düşürülür; veri gölüne, veritabanına ve API yanıtlarına hiçbir
zaman yazılmaz. Araç kimliği olarak yalnızca kapı numarası kullanılır. İlgili kod:
`src/ibb_mcp/models.py` içindeki `BusPosition.from_fleet_raw`.

`tests/fixtures/` altındaki kayıtlı İBB yanıtlarında da gerçek plaka yoktur: yakalama betiği
(`scripts/capture_fixtures.py`) her plakayı dosyaya yazmadan önce `00 XX 001`, `00 XX 002`, …
biçiminde sentetik bir değerle değiştirir. `00` il kodu yoktur, dolayısıyla bu değerler hiçbir
gerçek araca ait olamaz.

Azure Data Explorer ücretsiz küme koşulları da kişisel veri saklanmasına izin vermez;
bu tasarım o şartla da uyumludur.

## Servislere saygılı kullanım

İBB ağ geçidi kısa sürede çok sayıda isteğe HTTP 503 ile yanıt verir; İETT sefer
gerçekleşme servisi ise belgelenmiş şekilde saatte en fazla 100 istek kabul eder.

Bu proje kaynakları korumak için:

- ana bilgisayar başına en az 6 saniyelik istek aralığı uygular,
- İETT için saatlik 80 istekle kendi bütçesini resmi sınırın altında tutar,
- tüm okumaları paylaşımlı önbellekten servis eder; eşzamanlı N kullanıcı en fazla bir
  yukarı akış isteği üretir,
- hata durumunda üstel geri çekilme uygular ve bayat veriyi yaşını belirterek sunar.

İlgili kod: `src/ibb_mcp/http.py`, `src/ibb_mcp/cache.py`.

## İletişim

Bu depoda bir sorun görürseniz veya bir hak sahibi olarak içeriğin kaldırılmasını
isterseniz lütfen GitHub Issues üzerinden bildirin; talep üzerine kaldırılır.
