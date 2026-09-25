# Video senaryosu — 2:30

Microsoft AI Innovators teslimi. Ana dil Türkçe, altyazı İngilizce.

**Neden bu yapı:** değerlendirmenin bir kısmı transkript üzerinden yapılıyor, bu yüzden ürün adları
**sesli söylenir**, sadece ekranda gösterilmez. İlk 30 saniye müşteriyi, kararı ve üç sayıyı içerir;
son 40 saniye iddiaları kanıtlar.

**Kayıttan önce (bu adımı atlama):**

```bash
make collect-status                  # toplayıcı çalışıyor mu, kaç satır birikti
```

Isıtma: dört soruyu kaydedilecek sunucuda (web arayüzünde ya da kaydedilecek MCP istemcisinde) bir kez sor.
`scripts/warmup.py` yalnız kendi sürecinin önbelleğini ısıtır, kaydedilen sunucuyu değil; kaydedilen sunucuyu
ısıtan sürüm D4'te geliyor ([`SPRINT.md`](SPRINT.md) D4). Soğuk bir otopark sorusu ‹canlı: 18 sn›, sıcak
‹canlı: 0 sn› sürer. <!-- canlı: kayıt günü ekrandan okunur -->

## Hangi çekim nerede çalışıyor

| Çekim | Nerede çalışıyor | Ekranda ne söylenir |
|---|---|---|
| 0:00 başlık ve URL | dağıtılmış MCP sunucusu (`/healthz`) | "canlı", yalnız `/healthz` o gün 200 döndüyse |
| 0:30 web arayüzü, telefon genişliği | yerel web arayüzü (dağıtılmadı) | "yerelde çalışıyor" |
| 1:20 VS Code Copilot | dağıtılmış URL ya da yerel stdio, provada hangisi cevap verdiyse | hangisiyse o |
| yedek yol | kayıtlı veri (`--offline`) | "kayıtlı veri" |

Kural: kayıt günü `/healthz` 200 dönmediyse hiçbir şeye "canlı" ya da "deploy edildi" denmez; "henüz deploy
edilmedi" denir ve stdio gösterilir.

‹canlı: …› içindeki değer yalnız bir örnektir: kayıt günü ekrandan okunur ve ekranda ne varsa o söylenir.
Sayı taşıyan her anlatım satırının sonunda kaynağı bir HTML yorumu olarak yazılı; kaynağı olmayan sayı söylenmez.

---

## 0:00–0:30 · Problem ve sonuç

**Ekranda:** başlık kartı, dağıtılmış URL (yalnız `/healthz` o gün 200 döndüyse "canlı" denir),
`docs/architecture.svg`.

> "İstanbul'da açık veri var; portalda API olarak yayınlanan 41 veri seti. Ama otopark için İSPARK
> uygulaması, otobüs için Mobiett, hava için CepHava, metro için ayrı bir uygulama açıyorsunuz. Tek bir
> soru soracağınız yer yok, geliştiricinin bağlanacağı tek bir katman yok, ve 'bu saatte genelde ne kadar
> doluydu' sorusunun cevabı hiç yok, çünkü İBB geçmişi yayınlamıyor." <!-- kaynak: docs/events_research.md §5 (41 API veri seti) -->
>
> "İstanbul Nabız bunu **tek bir MCP server**'a çeviriyor. **Müşterim İBB Bilgi İşlem, Açık Veri ekibi.**
> Kullanıcı **[T] saniyede** cevap alıyor, canlı koşuda görev başarısı **%[S]**, otobüs varış tahmini
> ortalama **[E] dakika** hatayla, ve **her sayının yanında kaynağı ve verinin yaşı** var." <!-- kaynak: eval/results/latest.md, eval/results/eta.md -->

**Söylenecek kelimeler:** Customer Business Outcome · İBB Açık Veri · Microsoft Azure · Model Context Protocol.

> Sayılar `eval/results/latest.md` ve `eval/results/eta.md` dosyalarından **okunarak** yazılır. Ölçülmemiş
> hiçbir sayı söylenmez; bir metrik yoksa "henüz ölçemiyorum, sebebi şu" demek daha iyidir.

---

## 0:30–1:20 · Dört soru, canlı

**Ekranda:** telefon genişliğinde arayüz. Her kartın altındaki **veri yaşı** rozetini işaret et.

1. **"Taksim'e 20 dakikaya varıyorum, hangi otoparkta yer var?"**
   Boş yer, kapasite, tarife, yürüme mesafesi. → "Bu tarife İSPARK'ın yayınladığı metnin aynısı, ben
   yorumlamıyorum. Veri ‹canlı: 17 saniye› önceki." <!-- canlı: kayıt günü ekrandan okunur -->
2. **"500T 4. Levent'e ne zaman gelir?"**
   → "‹canlı: İki durak uzakta, yaklaşık 4 dakika›. Ve şunu söylüyor: bu tahmin **durak sırasından** üretildi,
   düz mesafeden değil. Yöntemi saklamıyorum çünkü güven ölçülebilir olmalı." <!-- canlı: kayıt günü ekrandan okunur -->
3. **"M4'te arıza var mı? Kartal'da asansör var mı?"**
   → "‹canlı: M4'te bildirilmiş bir aksaklık yok›. Kartal'da ‹canlı: 5 asansör, 20 yürüyen merdiven› var.
   Erişilebilirlik verisi zaten açık veride duruyordu, kimse sormuyordu." <!-- canlı: kayıt günü ekrandan okunur -->
4. **"Beşiktaş'ta koşu için hava nasıl?"**
   → "‹canlı: PM10 10,4, indeks 21, iyi›. Bu bir sağlık tavsiyesi değil, ölçüm." <!-- canlı: kayıt günü ekrandan okunur -->

**Başarısızlık ve düzeltme anı (bunu kesme, en değerli 15 saniye):**

> "500T'nin Kadıköy'e ne zaman geldiğini sorayım." → sistem **reddediyor**:
> *"500T hattı 'KADIKÖY' durağına uğramıyor."*
>
> "Bu hattın güzergâhında Kadıköy yok. İlk sürüm burada güvenle bir varış dakikası uyduruyordu, çünkü düz
> mesafe güzergâhı bilmez. Bir asistanın en kötü hatası, bilmediğini bilmemesidir." <!-- kaynak: tests/test_web.py (test_arrivals_refuse_a_stop_the_line_does_not_serve), senaryo j2-tr-2; ilk sürüm: `3d35602` commit mesajı -->

**Söylenecek kelimeler:** Azure Container Apps · Azure Container Apps Jobs · Azure Data Explorer · KQL · Azure Maps.

---

## 1:20–1:45 · Aynı server, Copilot'un içinde

**Ekranda:** VS Code, Copilot agent modu, `.vscode/mcp.json` bir saniye görünür.

> "Ürün arayüz değil, bu katman. Aynı MCP server'ı VS Code'da GitHub Copilot'a bağladım, tek bir
> yapılandırma dosyasıyla. Aynı 15 araç, aynı kaynak atıfları. Bir geliştirici kendi ajanını aynı dosyayla
> İstanbul verisine bağlayabilir." <!-- kaynak: make smoke (.github/scripts/mcp_smoke.py), .vscode/mcp.json -->

Copilot'a canlı sor: *"Kartal metro istasyonunda asansör var mı?"*

**Söylenecek kelimeler:** Model Context Protocol · GitHub Copilot · Microsoft Foundry.

---

## 1:45–2:15 · Kanıt

**Ekranda:** README'nin Sonuçlar tablosu, App Insights izi, CI rozeti, `eval/results/eta.md`.

> "Üç şeyi ölçüyorum, tahmin etmiyorum."
>
> - **Görev başarısı:** 30 iki dilli senaryo, `eval/journeys.jsonl`. D4 canlı koşusunda **[N] / 30**
>   senaryo canlı koştu, görev başarısı **%[S]**. <!-- kaynak: eval/journeys.jsonl, eval/results/latest.md -->
> - **Varış tahmini hatası:** tahminleri kaydediyorum, otobüsün o durağa gerçekten vardığı anı gözlüyorum,
>   farkı raporluyorum. **[E] dakika**, ve ölçüm yönteminin üç sınırını da yazıyorum, çünkü ölçüm penceresi
>   olmadan verilen bir hata değeri ölçüm değildir. <!-- kaynak: eval/results/eta.md -->
> - **Sayısal sadakat:** Model yolunda, cevaptaki sayıları araç çıktısıyla karşılaştıran bir kontrol var. Bu
>   kontrol yalnız sahte bir modelle test edildi; gerçek bir modelle henüz ölçülmedi.
>
> "Ve bir mühendislik notu: İBB'nin GTFS `stop_times` dosyası tam **1.048.575** satırda kesilmiş, yani
> Excel'in satır sınırında. Seferlerin sadece %14'ü, 500T hiç yok. ZIP'teki tam sürümle **2.876**
> güzergâhın durak sırası kuruluyor. Gerçek kamu verisi böyle görünüyor." <!-- kaynak: docs/NABIZ.md §2, docs/ENGINEERING.md OPT-6 -->

**Söylenecek kelimeler:** Application Insights · OpenTelemetry · GitHub Actions · Bicep · Azure Developer CLI.

---

## 2:15–2:30 · Sonraki adımlar

> "Sırada: paketi PyPI'ya yayınlamak, Copilot Studio bağlantısı, ve tarihçe büyüdükçe otopark doluluğunun
> gerçek modele dönüşmesi. Toplayıcı ‹canlı: Azure Container Apps Jobs'ta› çalışıyor, veri her saat
> artıyor." <!-- canlı: kayıt günü ekrandan okunur; D3'ten önce toplayıcı dizüstündeydi, çalıştığı yer o gün doğrulanır -->
>
> "Kod açık: github.com/muratcan-ates/istanbul-nabiz. Veri İBB Açık Veri Portalı'ndan, CC BY 4.0.
> Bu resmî bir İBB servisi değil." <!-- kaynak: NOTICE.md -->

**Söylenecek kelimeler:** Microsoft Fabric · Real-Time Intelligence · Event Hubs.

---

## Çekim listesi

- [ ] Toplayıcı en az 24 saattir çalışıyor (otopark profili ve ETA hatası için veri gerekli); nerede çalıştığı doğrulandı
- [ ] Dört soru kaydedilecek sunucuda bir kez soruldu, önbellek sıcak
- [ ] Dağıtılmış URL'nin `/healthz`'i 200 dönüyor; dönmüyorsa videoda "canlı" ya da "deploy edildi" denmiyor
- [ ] `eval/results/latest.md` ve `eta.md` güncel; `[T] [S] [E] [N]` README'ye ve bu metne yazıldı
- [ ] App Insights'ta bir iz ekran görüntüsü (agent → tool; model adımı yalnız D2'de bir model seçildiyse)
- [ ] VS Code Copilot bağlantısı önceden test edildi
- [ ] Altyazı dosyası hazır (transkript tabanlı değerlendirme için)
- [ ] Ekranda hiçbir yerde abonelik kimliği, anahtar veya e-posta görünmüyor

---

## Kanıt

Söylenen her iddianın ve her ürün adının kanıtı. Koşulu tutmayan satırdaki ad videoda söylenmez.

| Söylenen iddia ya da ürün adı | Kanıt (test, eval dosyası ya da repo yolu) |
|---|---|
| Customer Business Outcome, müşteri İBB Açık Veri ekibi | PLAN.md §2 |
| İBB Açık Veri, CC BY 4.0, resmî bir İBB servisi değil | `NOTICE.md` |
| Microsoft Azure | `infra/`, [`deploy.md`](deploy.md) |
| Hattın uğramadığı durak için tahmin reddedilir | `test_arrivals_refuse_a_stop_the_line_does_not_serve`; senaryo `j2-tr-2` |
| Her araç cevabı kaynak ve zaman bilgisi taşır | `test_tools_return_data_with_provenance_over_the_wire` |
| Azure Container Apps Jobs | `infra/modules/collectorjobs.bicep` |
| Azure Container Apps, tek MCP sunucusu | `infra/modules/containerapps.bicep`, `azure.yaml` (tek servis: `mcp`); "deploy edildi" yalnız `/healthz` 200 ise |
| Model Context Protocol, 15 araç | `make smoke` (`.github/scripts/mcp_smoke.py`), `tests/test_mcp_integration.py` |
| GitHub Copilot | `.vscode/mcp.json`, [`mcp-usage.md`](mcp-usage.md) |
| Sayısal sadakat kontrolü, yalnız sahte modelle | `test_an_unsupported_number_triggers_exactly_one_repair` (`tests/test_faithfulness.py`) |
| GTFS `stop_times` kesik, 500T yok | guardrail `csv-truncation` (`scripts/guardrails.py`), [`NABIZ.md`](NABIZ.md) §2 |
| Application Insights, OpenTelemetry | `infra/modules/monitoring.bicep`, `src/ibb_mcp/telemetry.py`; iz ekran görüntüsü yalnız deploy edildiyse |
| GitHub Actions | `.github/workflows/ci.yml` |
| Bicep, Azure Developer CLI | `infra/main.bicep`, `azure.yaml` |
| Azure Data Explorer, KQL | `kql/schema.kql`, `kql/dq.kql`; küme isteğe bağlı ([`SPRINT.md`](SPRINT.md) D3 görev 2): kurulmadıysa söylenmez |
| Azure Maps | `infra/modules/maps.bicep`, `deployMaps` varsayılan olarak kapalı; harita Azure Maps'ten gelmiyorsa söylenmez |
| Microsoft Foundry | `src/nabiz/agent/llm.py` (Foundry Local); yalnız D2'de yerel bir model seçildiyse, yoksa söylenmez |
| Microsoft Fabric, Real-Time Intelligence, Event Hubs | kodda yok; yalnız "sırada" diye söylenir (PLAN.md §11) |
| (her yeni iddia bir satır; kanıtı olmayan iddia videodan çıkar ya da sınırıyla söylenir) | |
