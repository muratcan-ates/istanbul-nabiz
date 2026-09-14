# İstanbul Nabız — Cloud Solution Architect Positioning

> Microsoft Customer Success dilinde konumlandırma. Üç mercek: **sürdürülebilirlik, finans, enerji**.
> Amaç süslemek değil, projenin gerçekten savunabileceği duruşu net cümlelere çevirmek. Savunulamayan
> her iddia §9'da açıkça reddedilmiştir. Sürüm v1 · 2026-09-14.

---

## 1. Tek paragraf (CSA dili)

İstanbul Nabız, bir belediyenin dağınık açık veri yüzeyini **tek bir tüketilebilir entegrasyon katmanına**
(MCP sunucusu) dönüştüren, üzerine güvenilirliği ölçülen bir ajan koyan bir referans mimaridir. Azure'da
tüketim tabanlı servislerle (Functions Flex, Container Apps `minReplicas: 0`, ADLS + Delta, Azure Data
Explorer) çalışır; talep şekillendirme (paylaşımlı önbellek) sayesinde **N kullanıcı, kaynak sisteme en fazla
1 istek** üretir. Her cevap kaynak ve veri yaşı taşır; ölçülemeyen metrik "n/a, sebebi şu" der. Haftalık
ölçülen bulut maliyeti **4–12 USD** bandındadır ve her mimari karar maliyet gerekçesiyle `DECISIONS.md`'de
kayıtlıdır.

**Müşteri:** İBB Bilgi İşlem Dairesi — Açık Veri ekibi. **Son kullanıcı:** İstanbullu vatandaş ve
entegrasyon yapan geliştirici.

---

## 2. Customer Business Outcomes

| Paydaş | Bugünkü durum | Hedeflenen sonuç | Nasıl ölçülür |
|---|---|---|---|
| İBB Açık Veri ekibi | 556 veri seti, 41 API; tüketim ölçülemiyor, her tüketici kendi entegrasyonunu yazıyor | Tek, sürümlenmiş, hız-sınırlı entegrasyon katmanı; tüketim gözlemlenebilir | Araç çağrısı telemetrisi, kaynak başına istek sayısı, ağ geçidi 503 oranı |
| İBB altyapısı (İETT/İSPARK ağ geçidi) | Her tüketici doğrudan çağırıyor; ~15 hızlı istekte tüm servisler 503 | Yukarı akış yükü tüketici sayısından **bağımsız** | Önbellek isabet oranı; pencere başına yukarı akış istek sayısı |
| Vatandaş | Aynı karar için 3–4 ayrı uygulama; "genelde ne olur" cevabı hiç yok | Tek soruda karar; her sayıda kaynak ve yaş | Görev başarı oranı (24 senaryo), cevap süresi |
| Erişilebilirlik ihtiyacı olan yolcu | Asansör bilgisi veride var ama hiçbir arayüzde sorulabilir değil | İstasyon erişilebilirliği birinci sınıf sorgu | Kapsama: 248 istasyonun tamamı |
| Geliştirici ekosistemi | Her proje sıfırdan SOAP/CKAN ayrıştırıyor | `uvx ibb-mcp` ile 5 dakikada entegrasyon | Entegrasyon süresi; MCP istemci çeşitliliği |

---

## 3. Mercek 1 — Sürdürülebilirlik

Sürdürülebilirliği iki ayrı katmanda ele alıyoruz ve ikisini **karıştırmıyoruz**: sistemin kendi ayak izi
(ölçülü), ve sistemin sağladığı davranış değişikliği (henüz hipotez).

### 3.1 Mimarinin kendi ayak izi — ölçülü, uygulanmış

Green Software Foundation'ın ilkeleriyle hizalı (enerji verimliliği, donanım verimliliği, talep şekillendirme,
ölçüm):

| İlke | Bu projede karşılığı | Kanıt |
|---|---|---|
| **Talep şekillendirme** | Tek-uçuş TTL önbellek: eşzamanlı N kullanıcı, pencere başına 1 yukarı akış çağrısı | `src/ibb_mcp/cache.py`; `city_freshness` aracı isabet/ıska sayaçlarını döner |
| **Donanım verimliliği** | Container Apps `minReplicas: 0` — boşta hiç hesaplama yok | `infra/modules/containerapps.bicep:268` |
| **Enerji verimliliği** | Her zaman açık servis yok: AI Search Basic (boşta bile ~2,4 USD/gün) ve Stream Analytics bilinçli olarak dışarıda | `DECISIONS.md` #1, #3 |
| **Veri minimizasyonu** | Plaka ayrıştırma sınırında düşürülüyor; sunucuda kişisel veri yok; gold katman Delta (sütunlu, sıkıştırılmış) | `models.py` `BusPosition.from_fleet_raw`; `NOTICE.md` |
| **Kenar/bulut esnekliği** | Aynı ajan yerelde (Foundry Local, Apple Silicon) veya Azure'da çalışır; kamu verisi için çıkarımı kenara taşıma seçeneği | `src/nabiz/agent/llm.py` |
| **Ölçüm** | Maliyet ve tazelik telemetrisi ürünün içinde, sonradan eklenen bir pano değil | `city_freshness`, `eval/results/` |

**Duruş:** Nezaket bir davranış kuralı değil, mimarinin kendisi. Kamu altyapısına saygılı davranan bir istemci,
hem o altyapının enerjisini hem kendi maliyetini düşürür.

### 3.2 Sağladığı davranış değişikliği — hipotez, ölçüm planı var

`plan_journey` aracı araba, metro, otobüs ve yürümeyi anlık trafik, metro arıza durumu ve canlı otopark
doluluğuyla karşılaştırıyor. **Modal kaymanın emisyon etkisi bu projede ölçülmemiştir.** Ölçmek için gereken:
kullanıcının hangi seçeneği gerçekten seçtiği (şu an toplanmıyor ve KVKK gereği toplanmayacak) veya bir A/B
pilotu. Dürüst çerçeve: *"Karşılaştırmayı mümkün kılıyoruz; kaymayı iddia etmiyoruz."*

Aynı şey otopark araması için geçerli: boş yer arayarak dolaşmanın şehir trafiğindeki payı literatürde
tartışmalıdır; bu projede ölçülmemiştir, bu yüzden **oran verilmez**.

---

## 4. Mercek 2 — Finans (FinOps)

### 4.1 Birim ekonomi

| Kalem | Ölçülen | Not |
|---|---|---|
| Haftalık bulut maliyeti | **4–12 USD** | ADLS + Functions Flex + Container Apps + App Insights + ACR |
| Boştaki maliyet | Container Apps ≈ 0 | `minReplicas: 0` |
| Kaçınılan maliyet | AI Search Basic ≈ 2,4 USD/gün, Stream Analytics ≈ 3,2 USD/gün | Hiç provizyonlanmadı; gerekçesi ADR'de |
| En büyük sabit kalem | ACR Basic ≈ 1,2 USD/hafta | `azd` uzaktan derleme; kaçınma yolu belgelendi |
| Yukarı akış maliyeti | Önbellek sayesinde kullanıcı sayısından bağımsız | Ölçekte birim maliyetin düşmesinin sebebi |

### 4.2 Bütçe bir kısıt değil, zorlayıcı bir tasarım girdisi

Azure for Students aboneliği **100 USD sert tavan**: kredi bitince abonelik komple devre dışı kalıyor.
Bu, "sonra optimize ederiz" seçeneğini ortadan kaldırdı ve mimariyi baştan tüketim tabanlı olmaya zorladı.
Kurumsal karşılığı: bir landing zone'da bütçe alarmı değil, **mimari kararın kendisi** maliyeti sınırlar.

### 4.3 Finansal yönetişim

Her pahalı servis reddi `DECISIONS.md`'de gerekçeli. Bir CSA'nın sorabileceği "neden Fabric değil, neden
AI Search yok" sorularının cevabı kodda değil, karar kaydında.

---

## 5. Mercek 3 — Enerji

**Bu bir enerji projesi değil ve öyleymiş gibi sunulmayacak.** Enerjiyle iki gerçek teması var:

1. **Ulaşım enerjisi talebi.** Trafik indeksi, otobüs hızı ve modal karşılaştırma, şehir ulaşımının enerji
   talebinin göstergeleridir. Proje bu talebi *gözlemlenebilir* kılıyor; azalttığını iddia etmiyor.
2. **Enerji kullanımının dışsallığı.** Hava kalitesi ölçümleri (28 istasyon, saatlik, 2023'ten bugüne)
   büyük ölçüde ulaşım ve ısınma kaynaklı yanmanın çıktısıdır. PM10 için yayınlanan indeks **24 saatlik
   hareketli ortalamadır**; bu yüzden kısa vadeli soru için saatlik derişim kullanılıyor — enerji/çevre
   verisini doğru okumanın teknik bir örneği.

**Genişletme yolu (yapılmadı, önerilir):** EPDK elektrikli şarj istasyonu verisi ve İBB'nin enerji tüketim
setleri aynı MCP katmanına takılabilir; toplayıcı ve önbellek deseni değişmeden yeni bir kaynak ekleniyor.
Bu, mimarinin genişleyebilirliğinin kanıtı olur — ama bugün yapılmamıştır.

---

## 6. Azure Well-Architected Framework hizalaması

| Sütun | Uygulama | Kanıt |
|---|---|---|
| **Güvenilirlik** | Bayat-veri yedeği: ağ geçidi düşerse cevap bozulmaz, yaşını söyler. Üstel geri çekilme. Kaynak hatası tüm cevabı değil yalnız o seçeneği düşürür | `cache.py`, `routing.py` |
| **Güvenlik** | Anahtarsız; yönetilen kimlik; public repoda sır yok; plaka ve konum hiç saklanmıyor; araçlar parametrik (serbest sorgu yüzeyi yok) | `guardrails.py`, `NOTICE.md` |
| **Maliyet optimizasyonu** | §4 | `DECISIONS.md` |
| **Operasyonel mükemmellik** | 508+ test, ruff, CI; senaryo tabanlı eval merge kapısı; OpenTelemetry → App Insights; toplayıcı süpervizörü | `.github/workflows/`, `eval/` |
| **Performans verimliliği** | Önbellek sıcakken 0 sn; soğukta gecikme bilinçli nezaket aralığından kaynaklanır ve raporda böyle yazılır | `eval/results/latest.md` |
| **Sürdürülebilirlik** | §3.1 | |

---

## 7. Duruş — Microsoft Sorumlu Yapay Zeka ilkeleriyle

Bu bölüm "sorumlulukları olan, duruşu belli" talebinin karşılığı. Her ilke bir **koda gömülü davranışa**
bağlı; slogan değil.

| İlke | Bu sistemde ne demek | Nerede zorlanıyor |
|---|---|---|
| **Şeffaflık** | Her sayı kaynak adresi ve yaşıyla döner. Varış tahmini hangi yöntemle (`stop_sequence`/`distance`/`schedule`) ve hangi güvenle üretildiğini söyler; oranın ölçülmüş mü varsayılan mı olduğunu bildirir | `ToolResult.provenance`, `rate_source` |
| **Güvenilirlik ve emniyet** | Bilmediğini bilir: hattın uğramadığı durağa tahmin **üretmez**, reddeder. Örneklemi ince olan profil `available: false` döner | `tools.py` on-route guard, `occupancy.py` min-samples |
| **Gizlilik ve güvenlik** | Otobüs plakası ayrıştırma sınırında düşer. Uyarı sisteminde konum istemcide kalır, sunucu durumsuzdur, log'a koordinat yazılmaz — testle kanıtlanır | `NOTICE.md`, `docs/privacy.md`, `tests/test_alerts.py` |
| **Kapsayıcılık** | Erişilebilirlik verisi birinci sınıf sorgu (§8). LLM kotası olmadan da çalışan deterministik mod: erişim, ödeme gücüne bağlı değil | `metro_station_info`, `agent/router.py` |
| **Hesap verebilirlik** | Değerlendirme harness'ı hakem; kötü çıkan sayı da yayımlanır (ETA 16,8 → kalibrasyonla 11,2) | `eval/results/eta.md`, README |
| **Adillik** | Açık veriye erişimi tek bir uygulamanın arkasından çıkarıp MIT lisanslı bir katmana taşır | repo |

**Ek duruş — kamu altyapısına saygı.** İETT'nin belgelenmiş saatte 100 istek sınırının altında (80) kendi
bütçemizi tutarız. Bir açık veri tüketicisinin ilk sorumluluğu, tükettiği kaynağı ayakta bırakmaktır.

---

## 8. Erişilebilirlik — iki anlamda da

**Engelli erişimi (a11y).** İBB'nin kendi verisi her metro istasyonu için asansör, yürüyen merdiven, WC ve
bebek bakım odası bilgisi taşıyor. Bu veriden çıkan ve hiçbir arayüzde sorulabilir olmayan gerçek:

> **248 istasyonun 85'inde (%34) asansör yok.**

Bu, tekerlekli sandalye kullanan, bebek arabası taşıyan veya ağır valizli bir yolcu için rota belirleyen
bilgidir ve şu an kimse soramıyor. `metro_station_info` bunu birinci sınıf bir soru hâline getiriyor.
Arayüz tarafında: klavye erişimi, görünür odak halkaları, `aria-live` sonuç bildirimi, koyu tema ve
`prefers-reduced-motion` desteği.

**Erişim (açıklık).** MIT lisanslı, public repo. `uvx ibb-mcp` ile herhangi bir MCP istemcisine takılır.
LLM kotası olmadan da cevap verir. Türkçe ve İngilizce. Bir vatandaşın ya da bir öğrencinin bu veriye
ulaşması için ne kurumsal lisans ne de ödeme gerekir.

---

## 9. İddia ETMEDİĞİMİZ şeyler

Bir CSA'nın güvenini kazandıran bölüm budur.

- **Karbon tasarrufu rakamı vermiyoruz.** Ölçmedik. Mimarinin düşük ayak izli olduğunu gösteririz, tonaj vermeyiz.
- **Modal kayma iddia etmiyoruz.** Karşılaştırmayı sunuyoruz; davranış değişikliği ölçülmedi.
- **Otopark aramasının trafikteki payı için oran vermiyoruz.** Literatürde tartışmalı, bizde ölçülmemiş.
- **Bu bir navigasyon ürünü değil.** Rota aracı karşılaştırmadır; dönüş dönüş yol tarifi vermez ve öyle sunulmaz.
- **Sağlık tavsiyesi vermiyoruz.** Hava kalitesi çıktısı ölçümdür.
- **İBB ile bir ortaklığımız yok.** Resmî değildir; veriler CC BY 4.0 ile kullanılır.
- **Henüz Azure'a dağıtılmadı.** Bicep ve `azd` hazır; Gün-0 kapıları (bölge politikası, ADX kimlik testi,
  LLM kotası) geçilmedi. Canlı URL yok.
- **Varış tahmini henüz iyi değil.** 11,2 dakika ortalama hata; hedef 5 dakika altı. Yol belli: daha çok
  gözlem, hat bazlı kalibrasyon genişletme.

---

## 10. Olgunluk ve ölçekleme yolu

| Aşama | Durum | Kapı |
|---|---|---|
| **Kanıt** (MVP) | ✅ 12+4 araç canlı veriyle çalışıyor, 508+ test, ölçülmüş eval | — |
| **Pilot** | ⏳ Azure'a dağıtım, canlı URL, App Insights telemetrisi | `az` kurulumu, bölge politikası, ADX kimlik testi |
| **Ölçek** | Fabric Eventhouse aynası, Event Hubs, Copilot Studio yüzeyi, PyPI yayını | Kapasite kararı; kurumsal tenant |
| **Kurumsal** | İBB iç sistemleriyle entegrasyon, saha ekipleri konsolu | Kurum ortaklığı — açık veriyle yapılamaz |

**Paylaşılan sorumluluk:** Veri doğruluğu ve servis sürekliliği İBB'nindir; ayrıştırma, önbellek, hız sınırı,
gizlilik ve cevabın dürüstlüğü bizimdir. Bu ayrım her araç yanıtında kaynak atfıyla görünür kılınır.

---

## 11. 30 saniyelik anlatım

**TR:** "İstanbul'da açık veri var ama tek bir soru sorabileceğiniz yer yok. Nabız, İBB'nin canlı verisini tek
bir MCP katmanına çeviriyor ve her cevabın yanında kaynağını ve kaç dakikalık olduğunu yazıyor. Mimari kamu
altyapısını koruyacak şekilde kurgulandı: yüz kullanıcı, kaynak sisteme bir istek. Bulut maliyeti haftada
4–12 dolar, çünkü boşta çalışan hiçbir servis yok. Ve İBB'nin kendi verisinden şunu çıkardık: 248 metro
istasyonunun 85'inde asansör yok — bu bilgi veride duruyordu, kimse soramıyordu."

**EN:** "İstanbul publishes open data but offers no single place to ask a question. Nabız turns it into one MCP
layer where every number carries its source and its age. The architecture protects the public gateway —
a hundred users cost it one request — and runs at four to twelve dollars a week because nothing is always on.
From the city's own data: 85 of 248 metro stations have no lift. That was in the data and nobody could ask it."
