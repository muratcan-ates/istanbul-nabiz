# E26 — Kaynak Envanteri

- Yeni, doğrulanmış ve sources.txt içinde bulunmayan URL: **257**; aday listesinde taban dosyada zaten bulunan ve bu dosyaya yinelenmeyen URL: **0**.
- 150 sorudan **66** soruya kaynak eşlendi; 42 doğrudan, 24 sınırlı/tarihli eşleme; **84** soru kapsanamıyor.
- Her yeni satır web’de açılıp içerik kontrolü yapılmış HTML sayfadır; PDF, giriş duvarı, yalnız arama sonucu ve açılmayan URL dahil edilmedi. İnceleme tarihi 26.09.2026.

## Kategori hedefi ve bulunan sayfa sayısı

| Kategori | Hedef | Bulunan | Fark / not |
|---|---:|---:|---|
| Ulaşım ve İstanbulkart | 30 | 53 | hedef karşılandı |
| İSKİ | 20 | 0 | 20 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| İGDAŞ | 10 | 0 | 10 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Sosyal destek ve yardımlar | 25 | 27 | hedef karşılandı |
| Engelli hizmetleri | 25 | 4 | 21 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Sağlık ve evde bakım | 10 | 6 | 4 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Kültür, kütüphane ve müze | 15 | 106 | hedef karşılandı |
| Spor tesisleri ve kurslar | 10 | 16 | hedef karşılandı |
| Eğitim | 15 | 2 | 13 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Afet ve deprem | 10 | 3 | 7 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Çevre, park, temizlik ve geri dönüşüm | 10 | 8 | 2 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Ruhsat, imar ve e-belediye | 10 | 8 | 2 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| Mezarlık ve cenaze | 5 | 0 | 5 eksik; resmî ve açılabilen uygun sayfa bulunamadı |
| İletişim ve 153 | 5 | 9 | hedef karşılandı |
| İtfaiye ve acil hizmet (ek kategori) | — | 15 | Kategori hedefi briefte ayrı tanımlanmamış |
## Hostlar ve robots.txt durumu

| Host | robots.txt |
|---|---|
| `ataturkkitapligi.ibb.gov.tr` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `binatespiti.ibb.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `cevre.ibb.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `depremzemin.ibb.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `iett.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `imarmudurlugu.ibb.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `itfaiye.ibb.gov.tr` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `saglik.ibb.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `sehirhatlari.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `sosyalhizmetler.ibb.gov.tr` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `spor.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `www.istanbulkart.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |
| `www.metro.istanbul` | Bilinmiyor: robots.txt yolu web aracında açılmadı; izinli/yasaklı olduğu doğrulanamadı. |

Robots nedeniyle alınmayan URL: **doğrulanmış yasaklı yol yok**; robots.txt erişilemediği için yasak/izin sonucu çıkarılmadı. Bu, hostun robots.txt dosyası olmadığı anlamına gelmez.

## Entegratörün allowlist kontrolü

Kodda literal exact olarak bulunmayan ve yeni kaynaklarda kullanılan hostlar: `binatespiti.ibb.istanbul`, `cevre.ibb.istanbul`, `depremzemin.ibb.istanbul`, `imarmudurlugu.ibb.istanbul`, `saglik.ibb.istanbul`, `www.istanbulkart.istanbul`. `ibb.gov.tr` alt alanları guardrails.py içindeki suffix kuralıyla kabul ediliyor; `.ibb.istanbul` alt alan adları ile `www.istanbulkart.istanbul` ayrıca exact olarak eklenmeli.

## Soru kapsamı

Eşleme listesi taban `sources.txt` içindeki mevcut ve bu ek dosyadaki yeni kaynakları birlikte kullanır; mevcut URL’ler ek dosyada kopyalanmamıştır. Durum: `doğrudan` kaynak sorunun temel işlemini/hizmetini anlatır; `tarihli` değişken koşul veya tarih içerdiğinden sadece o dönem için geçerlidir; `sınırlı` yalnız yönlendirme/kanal sunar.

| Soru kimlikleri | Durum | URL | Sınırlama / içerik notu |
|---|---|---|---|
| Q001–Q004, Q006–Q010, Q023 | doğrudan | `https://istanbulsenin.istanbul/sikca-sorulan-sorular/` | Mevcut tohum kaynağı: SSS başvuru, hesap ve işlem bilgisi verir; bazı değişken değerler güncel kabul edilmemeli. |
| Q005, Q049, Q061 | tarihli | `https://sosyalhizmetler.ibb.gov.tr/haberdetay.aspx?ID=9142` | Mevcut kaynak 12.06.2025 tarihli: destek kanalları ve o tarihteki nakdi destek bilgisi; koşul ve tutarları güncel teyit et. |
| Q011–Q012 | tarihli | `https://www.istanbulkart.istanbul/duyurular/detay?id=2768` | 01.09.2026 duyurusu öğrenci kartı çevrim içi sürecini anlatıyor; dönemsel koşullar yeniden teyit edilmeli. |
| Q013 | tarihli | `https://www.istanbulkart.istanbul/duyurular/detay?id=2780` | 04.04.2026 ürün duyurusu; ürün özellik ve başvuru koşulları değişebilir. |
| Q016 | süresi-geçmiş | `https://www.istanbulkart.istanbul/duyurular/detay?id=2762` | 29.06.2026 duyurusu 30.06.2026 vize tarihini anlatır; yalnız tarihsel bağlam sağlar, bugünkü hakkı yanıtlamaz. |
| Q045, Q048 | doğrudan | `https://sosyalhizmetler.ibb.gov.tr/sayfadetay.aspx?ID=1` | Ayni/nakdi destek sayfası resmi hizmet ve başvuru çerçevesini açıklar; bireysel uygunluk kararı vermez. |
| Q051 | doğrudan | `https://sosyalhizmetler.ibb.gov.tr/sayfadetay.aspx?ID=3` | Halk Süt hizmet sayfası hedef kitleyi ve erişim bilgisini verir; güncel uygunluk teyidi gerekir. |
| Q052 | doğrudan | `https://sosyalhizmetler.ibb.gov.tr/sayfadetay.aspx?ID=11` | İstanbul Bebek hizmet sayfası başvuru yönlendirmesi ve kapsam bilgisi sağlar. |
| Q056–Q057 | sınırlı | `https://istanbulsenin.istanbul/` | Mevcut ana sayfa Askıda Fatura modülüne yönlendirir; işlem akışı bu sayfada doğrulanmıyor. |
| Q059–Q060 | tarihli | `https://istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi` | Mevcut 27.10.2025 tarihli haber o dönemki destek kapsamını verir; başvuru ve tutar bilgisi güncel değildir. |
| Q072–Q073 | doğrudan | `https://sosyalhizmetler.ibb.gov.tr/sayfadetay.aspx?ID=2` | Yuvamız İstanbul sayfası 3–6 yaş grubunu ve güncel başvuru uygulamasına yönlendirmeyi veriyor; ücret ve şartlar başka güncel başvuru ekranından teyit edilmeli. |
| Q080–Q082, Q084 | doğrudan | `https://sosyalhizmetler.ibb.gov.tr/mudurlukdetay.aspx?ID=9` | Mevcut engelli hizmet sayfası merkez türleri, erişim ve destek kapsamını listeliyor; bireysel uygunluk için doğrudan başvuru teyidi gerekir. |
| Q083 | doğrudan | `https://spor.istanbul/engelli-bireylere-ozel-hizmetlerimiz/` | Spor İstanbul engelli bireylere yönelik hizmet ve katılım yönlendirmesini açıklıyor. |
| Q085–Q086 | doğrudan | `https://saglik.ibb.istanbul/evde-saglik-hizmeti-2-2/` | Evde sağlık sayfası başvuru yolunu ve hedef kitleyi açıklıyor; tıbbi uygunluk değerlendirmesi İBB tarafından yapılır. |
| Q088 | doğrudan | `https://saglik.ibb.istanbul/yasli-hizmetleri/` | Yaşlı hizmetleri sayfası yaşlılara yönelik sosyal destek ve bakım hizmetlerini anlatıyor. |
| Q089 | tarihli | `https://saglik.ibb.istanbul/darulaceze-tum-hizmetlerini-ucretsiz-sunuyor/` | 10.01.2025 tarihli kurumsal yazı; kabul yaşları ve ücretsiz hizmet koşulları için güncel teyit gerekir. |
| Q097 | doğrudan | `https://sehirhatlari.istanbul/tr/seferler/ic-hatlar` | Resmi iç hat sefer sayfası; sefer günü canlı değişiklikleri yeniden kontrol edilmeli. |
| Q098 | sınırlı | `https://sehirhatlari.istanbul/` | Mevcut ana sayfada sefer iptal duyuruları bulunuyor; canlı ve güncel bilgi sayfa tekrar açıldığında doğrulanmalı. |
| Q099 | doğrudan | `https://sehirhatlari.istanbul/tr/ucret-tarifeleri` | Ücret sayfasında geçerlilik tarihi yok; işlem öncesi yeniden teyit edilmeli. |
| Q100 | doğrudan | `https://sehirhatlari.istanbul/tr/ucret-tarifeleri` | Tarife sayfası ücret bilgisini veriyor ancak güncellik tarihi görünmüyor. |
| Q101 | doğrudan | `https://sehirhatlari.istanbul/tr/seferler/bogaz-turlari` | Boğaz turu sayfası resmi sefer ve ziyaretçi bilgisini veriyor; saat ve fiyat değişebilir. |
| Q102 | doğrudan | `https://sehirhatlari.istanbul/tr/bilgiler/engelli-yolcularimiz-icin-186` | Engelli yolcu erişilebilirlik sayfası vapur imkânlarını açıklar; sefer koşulları ayrıca kontrol edilmeli. |
| Q103 | doğrudan | `https://sehirhatlari.istanbul/tr/sik-sorulan-sorular` | Resmi SSS yolculuk kurallarını yanıtlıyor; taşıma kuralları güncel sayfada kontrol edilmeli. |
| Q104 | doğrudan | `https://sehirhatlari.istanbul/tr/sik-sorulan-sorular` | Resmi SSS yolcu işlemleri/kayıp eşya yönlendirmesini verir. |
| Q105 | doğrudan | `https://sehirhatlari.istanbul/tr/basvuru-kanallari` | Resmi başvuru kanalları sayfası şikâyet/öneri gönderme yolunu verir. |
| Q106 | doğrudan | `https://spor.istanbul/tesislerimiz/uyelik-bilgileri/` | Üyelik bilgileri sayfası kayıt adımlarını verir; güncel koşul ve ücretler değişebilir. |
| Q107 | doğrudan | `https://spor.istanbul/tesislerimiz/size-en-yakin-tesis/` | Resmi tesis bulma sayfası yakındaki tesisleri bulmaya yönlendirir. |
| Q108 | doğrudan | `https://spor.istanbul/paket-uyelikleri/` | Üyelik paketlerini açıklar; fiyat satın alma öncesi tekrar kontrol edilmelidir. |
| Q112 | doğrudan | `https://spor.istanbul/spor-okullari/` | Spor okulları sayfası çocuk kayıt yönlendirmesini verir; dönem ve kontenjan değişebilir. |
| Q113–Q114 | tarihli | `https://istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle` | Mevcut 28.12.2025 tarihli haber İstanbul Senin etkinlik modüllerini listeler; güncel etkinlik/bilet erişimi uygulamada teyit edilmeli. |
| Q115 | doğrudan | `https://ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Hakkinda/Kutuphane-Yonergesi/104` | Kütüphane yönergesi üyelik ve kullanım kurallarının resmi temelini verir; başvuru öncesi güncel sürüm kontrol edilmeli. |
| Q118 | doğrudan | `https://binatespiti.ibb.istanbul/sikcasorulansorular/` | Bina tespiti SSS başvuru ve sonuç sınırlarını açıklar; hızlı tarama kesin performans raporu değildir. |
| Q122 | doğrudan | `https://itfaiye.ibb.gov.tr/tr/egitim.html` | İtfaiyenin resmi eğitim sayfası vatandaş eğitimi ve başvuru yönlendirmesini verir. |
| Q123 | tarihli | `https://itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html` | 01.08–31.12.2026 tarife ve başvuru belgeleri sayfada; dönem sonrası koşullar yeniden doğrulanmalı. |
| Q124 | doğrudan | `https://itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html` | İtfai olay raporu talebinin resmi işlem ve başvuru adımlarını açıklar. |
| Q125–Q129, Q131, Q133–Q134 | sınırlı | `https://cozummerkezi.ibb.istanbul/` | Mevcut Çözüm Merkezi resmi ihbar/şikâyet kanalıdır; bu konu başlıkları için ayrı süreç ve yanıt süresi bu sayfada doğrulanmadı. |
| Q135–Q136 | doğrudan | `https://application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx` | Mevcut İBB okul servisi ücret hesaplama ekranı rota ve tarife hesabına yönlendirir; ücretler dönemsel değişebilir. |

### Kapsanamayan sorular

| Soru kimlikleri | Neden |
|---|---|
| Q014–Q015, Q017–Q022, Q024 | İstanbulkart kayıp kart, vize, Anne Kart, 60 yaş ve abonman için bu araştırmada açılıp konuya özgü doğrulanabilen resmi işlem sayfası bulunamadı. |
| Q025–Q036 | İSKİ sayfaları web aracında zaman aşımına uğradı; arama sonuçlarındaki PDF’ler açılmadı ve eklenmedi. |
| Q037–Q044 | İGDAŞ sayfaları erişilebilir hizmet HTML’i vermedi; gaz kaçağı gibi acil içerik tahmin edilmedi. |
| Q046–Q047, Q050, Q053–Q055, Q058 | Başvuru sonucu, planlama havuzu, sosyal bakiye, itiraz ve bazı destek türleri için sayfa başvuru sonucunu/uygunluğu açıklamıyor. |
| Q062–Q071 | Genç Üniversiteli, Sen Oku Diye, İSMEK ve yurt başvurularında kullanılabilir güncel HTML hizmet sayfası açılamadı. |
| Q074–Q079 | Yuvamız İstanbul detay sayfası yaş aralığı ve uygulamaya yönlendiriyor; ücret, belge, kontenjan, sonuç, merkez yakınlığı ve saat bilgisi doğrulanmıyor. |
| Q087 | Tıp merkezi randevu alma akışını açıklayan açılabilir resmi sayfa bulunamadı. |
| Q090–Q096 | İSPARK sayfası zaman aşımına uğradı; borç, doluluk, ücret, engelli hakkı ve kayıp eşya HTML’i doğrulanamadı. |
| Q109–Q111 | 1 TL kadın/emekli ve öğrenci kampanyaları geçici; güncel kampanya ve şartları doğrulanmadığından alınmadı. |
| Q116–Q117, Q119–Q120 | Kişiye/mahalleye göre toplanma, risk, barınma ve canlı afet kanalı bilgisi açılabilen sayfalarda doğrulanmadı. |
| Q121 | İtfaiyenin SSS sayfasındaki acil iletişim içeriği 2015–2023 tarihli arşiv; güncel acil numara için güvenilir güncel kaynak doğrulanmadığından yanıtlanmadı. |
| Q130 | Tarım haritası tesisleri listeliyor ancak hayvan acil ihbar sürecini doğrulamıyor. |
| Q132 | Yol çalışması bitiş saati dinamik veridir; açılabilir statik kaynakla doğrulanamadı. |
| Q137–Q145 | Mezarlıklar sayfası erişim zaman aşımına uğradı; defin/nakil/ücret/ruhsat bilgisi eklenmedi. |
| Q146–Q148 | Halk Ekmek sitesi zaman aşımına uğradı; büfe, fiyat ve bayi başvurusu doğrulanamadı. |
| Q149–Q150 | Kent Lokantası için açılıp hizmet bilgisi veren özgül resmi sayfa doğrulanamadı. |

## Araştırma sınırı

Araç her final host için robots.txt adresini açmayı denedi; isteklere hata/zaman aşımı döndüğü için robots politikası okunamadı. Bu nedenle robots nedeniyle URL atılmadı; atılmış gibi de gösterilmedi. Tüm aday sayfalar resmi hostlarda açıldı; robots durumunun entegrasyon öncesi yeniden kontrolü gerekir.
