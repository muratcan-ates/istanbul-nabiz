# Derin Araştırma Promptu v2 — İstanbul Nabız

> **NASIL KULLANILIR:** Aşağıdaki `---` çizgisinin altındaki her şeyi kopyala ve araştırma aracının **mesaj
> kutusuna yapıştır.** Dosya olarak ekleme: araçlar eki bağlam, mesajı görev sayar; ek + kısa mesaj
> gönderince araç "derin araştırma nasıl yapılır"ı araştırıyor.
>
> **Rapor gelince ilk kontrol:** §0'daki dört "repo kanıtı" maddesini doğru doldurmuş mu? Doldurmadıysa
> repoyu açmamış demektir; raporu atıp tekrar gönder. (v1 turunda model CloudSentinel README'sinin eski
> Sprint-1 bölümünü okuyup 314 commit'lik projeyi "10 commit'lik MVP" sandı.)

---

# GÖREV

Metodoloji anlatma. Aşağıdaki soruları araştır ve §7'deki formatta rapor ver. Netleştirme gerekiyorsa en
fazla 3 soru sor; cevap gelmezse varsayımını açıkça yazıp devam et. Bugün **22 Eylül 2026**.

**Araştırmanın konusu TEK bir proje: İstanbul Nabız.**
Repo: **https://github.com/muratcan-ates/istanbul-nabiz** (public, `main`).

CloudSentinel ve NEXUS bu araştırmanın konusu **değildir**. Yalnızca "hangi kanıtlanmış kalıbı ödünç
alabiliriz" referansıdır. CloudSentinel için sprint, mimari veya yol haritası **önerme.**

## 0. Önce kanıtla: repoyu gerçekten açtığını göster

Raporun ilk bölümü bu dört maddeyi içermeli; içermiyorsa rapor geçersizdir:

1. `src/ibb_mcp/` klasöründeki en az 8 dosya adı.
2. `src/ibb_mcp/server.py` içinde kayıtlı MCP araç sayısı ve 3 araç adı.
3. `docs/NABIZ.md` §1 "Hard rules" altındaki alt başlıklardan 3'ü.
4. `README.md` "Results" tablosunda "Bus ETA mean absolute error" satırındaki değer.

Bunları yazmadan hiçbir öneri yapma. Önerilerin repoda **gerçekten var olan** kodun üstüne kurulmalı.

## 1. Bağlam — oku, varsayma

**Ben:** Bilgisayar mühendisliği öğrencisiyim. İstanbul Nabız'ı **Microsoft Türkiye AI Innovators**
programı için geliştiriyorum (mentor: Barbaros Günay, CSA Manager). Hedefim AI Engineer → Cloud Solution
Architect. Proje Customer Success / CSA dilinde anlatılabilmeli ve 1–2 yıl portföyde durmalı.

**İstanbul Nabız nedir:** İBB'nin (İstanbul Büyükşehir Belediyesi) kayıt istemeyen canlı açık verisini
(İSPARK otopark doluluğu, İETT otobüs konumları, GTFS, Metro İstanbul arıza/erişilebilirlik, trafik
indeksi, hava kalitesi) **tek bir MCP sunucusuna** (`ibb-mcp`) çeviren, üzerine bir şehir ajanı koyan açık
kaynak proje. Her cevap kaynak adresi ve verinin yaşını taşır. Resmî bir İBB servisi değildir; veri
CC BY 4.0 ile kullanılır.

**Önce şu dosyaları oku (hepsi repoda):** `docs/NABIZ.md` (proje anayasası: kurallar, doğrulanmış İBB
gerçekleri, epikler, çoklu sohbet protokolü) · `docs/positioning.md` (CSA/Customer Success
konumlandırması) · `DECISIONS.md` (mimari kararlar) · `README.md` · `PLAN.md` · `src/ibb_mcp/`.

**Doğrulanmış mevcut durum (22 Eyl 2026):**

| Alan | Durum |
|---|---|
| Kod | Python 3.12, ~12.900 satır `src/`, ~20 commit, ~500 test (pytest), ruff temiz, CI workflow var |
| MCP | MCP Python SDK 2.x. `server.py`'de 12 araç kayıtlı; `tools.py`'de 4 araç daha yazılı ama henüz MCP'ye bağlanmadı (rota karşılaştırma, hat düzenliliği, otopark geçmiş profili, uyarılar) |
| Veri | Toplayıcı lokal çalıştı: ~33.900 otopark, ~10.700 otobüs konumu, ~6.600 varış tahmini birikti. İBB bu geçmişi yayınlamıyor |
| Ölçüm | Otobüs varış tahmini: ilk ölçüm 16,6 dk hata; kendi gözlenen varışlarımızdan kalibrasyonla ~11,2 dk. Hedef < 5 dk |
| Azure | Bicep + `azure.yaml` yazılı, **hiçbir şey deploy edilmedi**, `az`/`azd` kurulu değil, canlı URL yok |
| LLM | Değiştirilebilir (env); LLM yokken çalışan deterministik mod var |
| Zayıf yan | Toplayıcı lokal ve iki kez sessizce öldü; ajan-modu eval LLM kotası yokluğundan koşulamadı |

## 2. Referans 1 — CloudSentinel'den ödünç alınacak kalıplar

CloudSentinel benim önceki projem (YZTA Bootcamp, bulut maliyet/güvenlik anomali tespiti + insan onaylı
ajan karar sistemi). Repo: https://github.com/muratcan-ates/cloudsentinel — **314 commit, ~1.000 test
fonksiyonu.** Dikkat: README'nin Sprint-1 retrospektif bölümü eskidir ("Gemini is planned" gibi cümleler
Temmuz başına aittir). Durumu README'den değil **koddan** (`app/`, `tests/`, `.github/workflows/`) oku.

CloudSentinel'de kanıtlanmış kalıplar:
- **detect → decide → act + human-in-the-loop** döngüsü, karar defteri (ledger)
- **Reflex yol vs bilinçli yol:** deterministik hızlı kural (~400 ms) ile LLM destekli tartışma yolunun ayrımı
- **Fake-provider disiplini:** tüm ajan katmanını sıfır LLM harcamasıyla geliştirip demolamak
- **Readonly public demo:** canlıda yazma uçlarını kapatıp jüriye güvenli vitrin
- **Missions (YAML), pulse/watchdog, debate, runbook RAG-lite, backtest metrikleri, scorecard**
- Test disiplini: 27 → 446 → ~1.000 test, her commit ruff temiz

**Soru:** Bu kalıplardan hangisi İstanbul Nabız'a taşınmalı, hangisi taşınmamalı ve neden? Nabız zaten
bazılarını içeriyor olabilir — önce kontrol et.

## 3. Referans 2 — NEXUS vizyonu ve "Nabız = Pulse"

NEXUS, hiç başlamadığım uzun vadeli vizyonum: bir kurumun "karar beyni". Organları: Reflex Engine,
Decision Router, Arena (rol tabanlı tartışma), Confidence scoring, Nerve Center, Learning loop, Time
Machine / Lens, Radar, **Pulse (MCP + A2A)**, Governance Layer.

**Gözlem:** NEXUS'un Pulse organı MCP + A2A katmanıdır. "Nabız" pulse'ın Türkçesidir ve İstanbul Nabız
bir MCP sunucusudur. Yani Nabız, NEXUS'un gerçekleşen ilk organı olarak konumlanabilir.

Benim tahmini eşleşmem — **doğrula, genişlet veya çürüt:**

| NEXUS organı | Nabız'da karşılığı (tahmin) |
|---|---|
| Pulse | MCP sunucusunun kendisi |
| Reflex Engine / Decision Router | `src/nabiz/agent/router.py` deterministik yönlendirici, LLM'siz mod |
| Confidence scoring | Varış tahmininde `method` + `confidence` + `rate_source` alanları |
| Learning loop | `scripts/calibrate_eta.py`: tahminleri gözlenen varışlarla eşleyip oranı yeniden kalibre ediyor |
| Time Machine / Lens | `occupancy.py` ve `reliability.py` — İBB'nin yayınlamadığı tarihçeden profiller |
| Nerve Center | `city_freshness` aracı, önbellek sayaçları, (hedef) App Insights |
| Radar | `scripts/guardrails.py`, veri tazeliği ve İBB servis sağlığı |
| Governance | Plakanın ayrıştırmada düşmesi, sunucuda kişisel veri olmaması (KVKK), resmî değil bildirimi |
| Arena | Yok |

**Soru:** 7 günde hangi organ(lar)ı Nabız içinde bir adım olgunlaştırmak en yüksek getiriyi verir?
NEXUS'u yeniden yaratma; yalnız 7 güne sığan sınırlı artımlar öner.

## 4. Araştırma soruları

### A. Otonom geliştirme — EN ÖNEMLİ SORU
Ben araya girmeden, günde en fazla 30 dakika PR incelemesiyle projenin gelişmesini istiyorum.

- **GitHub Copilot cloud agent** (öğrenci planı): Eylül 2026 itibarıyla gerçek aylık limit (kaynaklar
  "200 AI credit" ile "300 premium request" arasında çelişiyor), issue → PR akışı, kısıtlar.
- **KRİTİK PROJE KURALI:** Commit'lerde ve PR açıklamalarında **yapay zeka co-author'u / imzası
  olmamalı.** Copilot cloud agent commit'lere co-author ekliyor mu? Squash-merge ile temizlenebiliyor mu?
  Engellenemiyorsa hangi alternatif bu kuralı çiğnemeden çalışır?
- **Claude Code GitHub Action** (`anthropics/claude-code-action`) ve headless kullanım: Claude Max
  aboneliğimle Actions'ta çalışabiliyor mu, yoksa ayrı API faturası mı gerekiyor? Gerçek maliyet?
- Karşılaştır: Copilot cloud agent · Claude Code Action · Gemini CLI Action · Google Jules. Bu repoda
  günde ≤30 dk insan zamanıyla hangisi en güvenilir çalışır?
- Gereken dosyalar: `AGENTS.md`, `.github/copilot-instructions.md`, `copilot-setup-steps.yml`. Repoda
  zaten `docs/NABIZ.md` var — tek kaynak nasıl korunur, kopya çoğalmadan?
- Ajanın güncel doküman okuması için **Microsoft Learn MCP** ve **Azure MCP Server** — kurulum ve fayda.

### B. Azure'da en ucuz ve en hızlı canlı yol
Kısıt: Azure for Students, 100 USD kredi, kredi bitince abonelik tamamen kapanır, gizli "izinli bölgeler"
politikası var.

- **Toplayıcı:** Azure Functions Flex Consumption mı, **Container Apps Jobs (cron)** mı? MCP sunucusu ve
  web de Container Apps'te olacağı için aynı ortamda Jobs daha basit olabilir. Free grant paylaşımı,
  kurulum süresi, öğrenci aboneliğinde bilinen sorunlar?
- **Depolama:** Azure Data Explorer free cluster (fonksiyonun managed identity'si ile headless ingest
  doğrulanmadı) · Azure SQL Database free offer · sadece ADLS + Delta Lake. 7 günde hangisi gerçekçi?
- **Azure Verified Modules (AVM):** mevcut Bicep'i sadeleştirmek için.
- **GitHub Actions → Azure OIDC:** üniversite tenant'ında app registration izni yoksa plan B?
- İsteğe bağlı: Entra Easy Auth (Container Apps) — Nabız kamu verisi sunuyor; gerçekten gerekli mi?

### C. LLM kotası yokken
- Foundry Local'ın Apple Silicon'da **tool-calling** durumu (Eylül 2026).
- Microsoft Foundry'de "sold by Azure" serverless modeller öğrenci aboneliğine açık mı?
- Kullanıcı sorusu LLM'e gittiği için **Azure AI Content Safety Prompt Shields** F0 katmanı: limit, kurulum.

### D. Gözlemlenebilirlik
OpenTelemetry GenAI semantik konvansiyonları → Application Insights; MCP araç çağrılarını span olarak izleme.
Ücretsiz ingest sınırı.

### E. Genişleme — yeni veri kaynakları
Kayıt istemeden erişilebilen İBB / Türkiye açık verilerinden Nabız'a eklenebilecekler. Her biri için
**doğrulanmış** endpoint, format, lisans, tazelik: EPDK şarj istasyonları · İBB etkinlik feed'i (var mı?) ·
deprem · İSKİ · vapur/Şehir Hatları · diğer. Var olmayanı var sayma.

### F. Customer Success / CSA
`docs/positioning.md`'yi oku. Tekrar yazma; **eksik olanı** söyle: success plan KPI'ları, WAF sütunları,
Sorumlu YZ, varsa Sustainability rehberi, Cloud Adoption Framework'ün hangi aşaması.

## 5. Doğrulanmış gerçekler — bunlarla çelişme

- **GitHub Models 30 Temmuz 2026'da tamamen emekli oldu** (docs.github.com). Önerme.
- Azure for Students'ta Azure OpenAI model deploy'u Microsoft personeline göre desteklenmiyor (Microsoft
  Q&A, Temmuz 2026); resmî kota tablosunda öğrenci satırı "N/A".
- İBB ağ geçidi `api.ibb.gov.tr` ~15 hızlı istekte tüm servislere 503 döner. İETT belgelenmiş sınırı
  saatte 100 istek. Proje saatte 80 ile kendini sınırlıyor.
- İBB GTFS `stop_times.csv` Excel satır sınırında (1.048.575) kesik; ZIP sürümü tam.
- Container Apps ücretsiz kotası: ayda 180.000 vCPU-s + 360.000 GiB-s + 2M istek.
- AI Search Basic boşta bile ~2,4 USD/gün; FinOps hubs ~120 USD/ay. İkisini de önerme.
- MCP Python SDK 2.x (`MCPServer`, `FastMCP` değil). Microsoft Agent Framework 1.0 GA, 3 Nisan 2026.

## 6. Kısıtlar

- **7 gün:** D1 = 23 Eylül Çarşamba, D7 = 29 Eylül Salı.
- **İnsan zamanı:** D1 kurulumu en fazla 2 saat; sonra günde en fazla 30 dakika (PR inceleme/merge).
- **Ücretsiz önce.** Ücretli her kalem için haftalık maliyet ve neden kaçınılmaz olduğu.
- **Microsoft-native tercih** — ama ücretsiz ve açıkça daha iyi bir alternatif varsa söyle.
- Sunucuda kişisel veri yok (KVKK). Otobüs plakası asla saklanmaz.
- Commit'lerde ve PR'larda yapay zeka imzası yok.
- Resmî İBB servisi değil; bu duruş korunur.

## 7. Çıktı formatı

0. **Repo kanıtı** (§0'daki 4 madde)
1. **Türkçe yönetici özeti** (≤ 12 satır): en yüksek getirili 5 karar, en riskli 3 varsayım, D1'in ilk 3 saati.
2. **Teknoloji tablosu:** yetenek · seçim · bu projede neden zaman kazandırır · ücretsiz limit (tarihli) ·
   yedek · risk.
3. **NEXUS organ eşleşmesi:** §3 tablosunun doğrulanmış/düzeltilmiş hâli + 7 günde olgunlaşacak organ(lar).
4. **CloudSentinel'den taşınacak / taşınmayacak kalıplar** ve gerekçesi.
5. **Otonom geliştirme işletim modeli:** seçilen ajan, kurulum adımları, gereken dosyalar (içerik taslağıyla),
   AI-imzası kuralının nasıl korunacağı, koruma rayları, hata modları.
6. **7 günlük sprint:** her gün için Hedef · Customer Success sonucu · iş paketleri. Her iş paketi:
   başlık · dosyalar · kabul kriteri · test · `agent-executable: evet/hayır` · bağımlılık. Yalnız insanın
   yapabileceği işler ayrı işaretli.
7. **İnsan zaman bütçesi:** kötü / gerçekçi / iyi senaryo.
8. **Riskler, blocker'lar, bilinmeyenler** (en fazla 3 soru).
9. **Kaynaklar:** her iddia için URL · okuma tarihi · güven (`verified` sayfada okudun / `likely` güçlü
   ikincil kaynak / `unverified`).

**Kurallar:** Uydurma repo, API, fiyat veya endpoint yok. Doğrulayamadığını "bilinmiyor" yaz. 12 aydan eski
kaynakları işaretle. Önerilerin repodaki mevcut kodla çelişiyorsa, önce çelişkiyi söyle.
