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

Depoda üçüncü taraf kod, yazı tipi ya da simge dosyası yoktur. Web sayfası iki bileşeni çalışma anında,
ziyaretçinin tarayıcısında yükler:

| Bileşen | Kaynak | Lisans | Kullanım |
|---|---|---|---|
| MapLibre GL JS 4.7.1 | `https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/4.7.1/` (`maplibre-gl.min.js`, `maplibre-gl.min.css`) | BSD-3-Clause | harita; yüklenemezse konumlar liste olarak gösterilir |
| OpenStreetMap harita karoları | `https://tile.openstreetmap.org/` | veri ODbL 1.0, © OpenStreetMap katkıcıları; karo kullanım politikası: <https://operations.osmfoundation.org/policies/tiles/> | harita altlığı; atıf haritada ve sayfanın altında |

Web tasarımının sonraki adımları (`docs/design/DESIGN.md` §12) depoya bir yazı tipi alt kümesi ve bir
simge dosyası ekleyecek. Her biri eklendiği değişiklikte kaynak adresi, sürümü ve lisans metniyle bu tabloya
yazılır.

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
