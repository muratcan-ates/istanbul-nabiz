# Video senaryosu — 2:30

Microsoft AI Innovators teslimi. Ana dil Türkçe, altyazı İngilizce.

**Neden bu yapı:** değerlendirmenin bir kısmı transkript üzerinden yapılıyor, bu yüzden ürün adları
**sesli söylenir**, sadece ekranda gösterilmez. İlk 30 saniye müşteriyi, kararı ve üç sayıyı içerir;
son 40 saniye iddiaları kanıtlar.

**Kayıttan önce (bu adımı atlama):**

```bash
make collect-status                  # toplayıcı çalışıyor mu, kaç satır birikti
.venv/bin/python scripts/warmup.py   # önbelleği ısıt: soğuk otopark sorgusu 18 sn sürer, sıcak 0 sn
```

---

## 0:00–0:30 · Problem ve sonuç

**Ekranda:** başlık kartı, canlı URL, `docs/architecture.svg`.

> "İstanbul'da açık veri var: 556 veri seti, 41 API. Ama otopark için İSPARK uygulaması, otobüs için
> Mobiett, hava için CepHava, metro için ayrı bir uygulama açıyorsunuz. Tek bir soru soracağınız yer yok,
> geliştiricinin bağlanacağı tek bir katman yok, ve 'bu saatte genelde ne kadar doluydu' sorusunun cevabı
> hiç yok, çünkü İBB geçmişi yayınlamıyor."
>
> "İstanbul Nabız bunu **tek bir MCP server**'a çeviriyor. **Müşterim İBB Bilgi İşlem, Açık Veri ekibi.**
> Kullanıcı **[T] saniyede** cevap alıyor, 24 senaryoda görev başarısı **%[S]**, otobüs varış tahmini
> ortalama **[E] dakika** hatayla, ve **her sayının yanında kaynağı ve verinin yaşı** var."

**Söylenecek kelimeler:** Customer Business Outcome · İBB Açık Veri · Microsoft Azure · Model Context Protocol.

> Sayılar `eval/results/latest.md` ve `eval/results/eta.md` dosyalarından **okunarak** yazılır. Ölçülmemiş
> hiçbir sayı söylenmez; bir metrik yoksa "henüz ölçemiyorum, sebebi şu" demek daha iyidir.

---

## 0:30–1:20 · Dört soru, canlı

**Ekranda:** telefon genişliğinde arayüz. Her kartın altındaki **veri yaşı** rozetini işaret et.

1. **"Taksim'e 20 dakikaya varıyorum, hangi otoparkta yer var?"**
   Boş yer, kapasite, tarife, yürüme mesafesi. → "Bu tarife İSPARK'ın yayınladığı metnin aynısı, ben
   yorumlamıyorum. Veri 17 saniye önceki."
2. **"500T 4. Levent'e ne zaman gelir?"**
   → "İki durak uzakta, yaklaşık 4 dakika. Ve şunu söylüyor: bu tahmin **durak sırasından** üretildi,
   düz mesafeden değil. Yöntemi saklamıyorum çünkü güven ölçülebilir olmalı."
3. **"M4'te arıza var mı? Kartal'da asansör var mı?"**
   → "M4'te bildirilmiş bir aksaklık yok. Kartal'da 5 asansör, 20 yürüyen merdiven var. Erişilebilirlik
   verisi zaten açık veride duruyordu, kimse sormuyordu."
4. **"Beşiktaş'ta koşu için hava nasıl?"**
   → "PM10 10,4, indeks 21, iyi. Bu bir sağlık tavsiyesi değil, ölçüm."

**Başarısızlık ve düzeltme anı (bunu kesme, en değerli 15 saniye):**

> "500T'nin Kadıköy'e ne zaman geldiğini sorayım." → sistem **reddediyor**:
> *"500T hattı 'KADIKÖY' durağına uğramıyor."*
>
> "Bu hattın güzergâhında Kadıköy yok. İlk sürüm burada güvenle **185 dakika** diyordu, çünkü düz mesafe
> güzergâhı bilmez. Bir asistanın en kötü hatası, bilmediğini bilmemesidir."

**Söylenecek kelimeler:** Azure Container Apps · Azure Data Explorer · KQL · Azure Functions · Azure Maps.

---

## 1:20–1:45 · Aynı server, Copilot'un içinde

**Ekranda:** VS Code, Copilot agent modu, `.vscode/mcp.json` bir saniye görünür.

> "Ürün arayüz değil, bu katman. Aynı MCP server'ı VS Code'da GitHub Copilot'a bağladım, tek satır
> yapılandırmayla. Aynı 12 araç, aynı kaynak atıfları. Bir geliştirici kendi ajanını beş dakikada
> İstanbul verisine bağlayabilir."

Copilot'a canlı sor: *"Kartal metro istasyonunda asansör var mı?"*

**Söylenecek kelimeler:** Model Context Protocol · GitHub Copilot · Microsoft Foundry.

---

## 1:45–2:15 · Kanıt

**Ekranda:** README'nin Sonuçlar tablosu, App Insights izi, CI rozeti, `eval/results/eta.md`.

> "Üç şeyi ölçüyorum, tahmin etmiyorum."
>
> - **Görev başarısı:** 24 iki dilli senaryo, `eval/journeys.jsonl`. Canlı koşuda **%[S]**.
> - **Varış tahmini hatası:** tahminleri kaydediyorum, otobüsün o durağa gerçekten vardığı anı gözlüyorum,
>   farkı raporluyorum. **[E] dakika**, ve ölçüm yönteminin üç sınırını da yazıyorum, çünkü ölçüm penceresi
>   olmadan verilen bir hata değeri ölçüm değildir.
> - **Sayısal sadakat:** cevaptaki her sayı bir araç çıktısında var mı? Yoksa cevap reddedilip yeniden
>   üretiliyor.
>
> "Ve bir mühendislik notu: İBB'nin GTFS `stop_times` dosyası tam **1.048.575** satırda kesilmiş, yani
> Excel'in satır sınırında. Seferlerin sadece %14'ü, 500T hiç yok. ZIP'teki tam sürüme geçince güzergâh
> sayısı 515'ten **2.876**'ya çıktı. Gerçek kamu verisi böyle görünüyor."

**Söylenecek kelimeler:** Azure AI Evaluation · Application Insights · OpenTelemetry · GitHub Actions · Bicep · Azure Developer CLI.

---

## 2:15–2:30 · Sonraki adımlar

> "Sırada: paketi PyPI'ya yayınlamak, Copilot Studio bağlantısı, ve tarihçe büyüdükçe otopark doluluğunun
> gerçek modele dönüşmesi. Toplayıcı şu anda çalışıyor, veri her saat artıyor."
>
> "Kod açık: github.com/muratcan-ates/istanbul-nabiz. Veri İBB Açık Veri Portalı'ndan, CC BY 4.0.
> Bu resmî bir İBB servisi değil."

**Söylenecek kelimeler:** Microsoft Fabric · Real-Time Intelligence · Event Hubs.

---

## Çekim listesi

- [ ] Toplayıcı en az 24 saattir çalışıyor (otopark profili ve ETA hatası için veri gerekli)
- [ ] `scripts/warmup.py` çalıştırıldı, önbellek sıcak
- [ ] Canlı URL açık ve yanıt veriyor
- [ ] `eval/results/latest.md` ve `eta.md` güncel; `[T] [S] [E]` README'ye yazıldı
- [ ] App Insights'ta bir iz ekran görüntüsü (agent → tool → model)
- [ ] VS Code Copilot bağlantısı önceden test edildi
- [ ] Altyazı dosyası hazır (transkript tabanlı değerlendirme için)
- [ ] Ekranda hiçbir yerde abonelik kimliği, anahtar veya e-posta görünmüyor
