# Bilgi dizini eşik ölçümü: önce / sonra

`scripts/knowledge_calibration.py` çıktısından üretildi; elle sayı yazılmadı. Dizin: yerel
`data/knowledge/knowledge.db`. Arama modelsiz ve gömmesiz (`embedder=None`): çevrimdışı sohbet sorgu
gömmesi yapmaz, bu yüzden kosinüs sütunu yok. Hassaslık `policy.refuses` ile, sohbetin kararıyla aynı
(`hassas` sütunu); `seed-hassas` kümesi araştırma tohumunun kendi `sensitive` işaretidir. `seed` ve
`seed-hassas` araştırma tohumunun 150 sorusu (depo dışında); öteki kümeler `eval/knowledge_calibration.jsonl`.
Altın dışı kaynak her zaman yanlış değildir (ör. aynı kurumun başka sayfası); negatif kümedeki her cevap yanlıştır.

Önce eşikler: `{"min_cosine": 0.35, "fts_min": 16.0, "min_coverage": 0.5, "coverage_ceiling": 0.27}` · Sonra eşikler: `{"min_cosine": 0.35, "fts_min": 16.0, "min_coverage": 0.5, "coverage_ceiling": 0.27}`
Etkin belge sayısı (yerel SQLite): önce 258, sonra 326.

## Özet

| Küme | n | önce answer | önce quote_only | önce unknown | sonra answer | sonra quote_only | sonra unknown |
|---|---:|---:|---:|---:|---:|---:|---:|
| demo | 6 | 0 | 0 | 6 | 0 | 0 | 6 |
| hafifletiyor | 20 | 6 | 0 | 14 | 6 | 0 | 14 |
| kurum-sayfasi | 17 | 1 | 0 | 16 | 2 | 0 | 15 |
| negatif | 24 | 0 | 0 | 24 | 0 | 0 | 24 |
| seed | 41 | 7 | 0 | 34 | 10 | 0 | 31 |
| seed-hassas | 109 | 9 | 4 | 96 | 13 | 6 | 90 |
| **toplam** | 217 | 23 | 4 | 190 | 31 | 6 | 180 |

| Ölçü | önce | sonra |
|---|---:|---:|
| Altın URL'si olan soru | 184 | 184 |
| İlk sonuç altın URL | 28 | 33 |
| Altın URL ilk 8'de | 56 | 66 |
| Cevaplanan (answer/quote_only) ve altını olan | 27 | 37 |
| … ilk kaynağı altın URL | 13 | 15 |
| … ilk kaynağı altın dışı | 14 | 22 |
| Negatif kümede cevap (yanlış pozitif) | 0 | 0 |

Sohbet (`/api/chat`, çevrimdışı, model yok) modları, aynı 217 soru:

| Sohbet modu | önce | sonra |
|---|---:|---:|
| answer | 39 | 46 |
| handoff | 1 | 1 |
| quote_only | 4 | 6 |
| redirect | 6 | 6 |
| refused | 30 | 28 |
| unknown | 137 | 130 |

## Soru başına

`bm25` ilk sonucun FTS5 puanının mutlak değeri (büyük = daha iyi eşleşme); `kapsam` sorunun ayırt edici
kelimelerinden ilk alıntıda geçenlerin oranı (sonra koşusu); `altın` ilk sonucun sorunun altın URL'lerinden biri olup
olmadığı (`·` altın yok). Sohbet sütunu `--chat` koşusunda `/api/chat`'in modu ve kuralıdır.

| id | soru | hassas | önce ilk kaynak | sonra ilk kaynak | bm25 | kapsam | altın | önce seviye/mod | sonra seviye/mod | sohbet (sonra) |
|---|---|:-:|---|---|---:|---:|:-:|---|---|---|
| Q001 | 153’e nasıl başvuru yaparım? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 12.40 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q002 | 153 başvurumu nereden takip ederim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.83 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q003 | İstanbul Senin’den şikâyet oluşturabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 24.63 | 0.83 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q004 | Canlı desteğe nasıl ulaşırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.87 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q005 | 153’e WhatsApp’tan yazabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 13.37 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q006 | İstanbul Senin ücretsiz mi? | E | istanbulsenin.istanbul | istanbulsenin.istanbul | 11.29 | 1.00 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q007 | İstanbul Senin’e T.C. kimlik numarası olmadan girebilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 33.76 | 0.60 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q008 | Yabancı uyruklular İstanbul Senin’e kayıt olabilir mi? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 18.72 | 0.57 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q009 | İstanbul Senin’de hangi faturaları ödeyebilirim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 17.79 | 1.00 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q010 | İBB Wi‑Fi’ye İstanbul Senin’den nasıl bağlanırım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 26.81 | 0.62 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q011 | Öğrenci İstanbulkart’a nasıl başvururum? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | istanbulkart.istanbul/duyurular/detay?id=2768 | 19.55 | 0.50 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q012 | Öğrenci kartı başvurusu artık sadece internetten mi yapılıyor? |  | metro.istanbul/Home/SikcaSorulanSorular | spor.istanbul/spor-okullari | 12.77 | 0.33 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q013 | İstanbulkart Plus nedir, nasıl başvurulur? |  | istanbulkart.istanbul/duyurular/detay?id=2780 | istanbulkart.istanbul/duyurular/detay?id=2780 | 18.96 | 0.67 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q014 | Kaybolan İstanbulkart’ımı nasıl kapatırım ve yenisini alırım? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | istanbulkart.istanbul/duyurular/detay?id=2768 | 11.45 | 0.17 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q015 | İndirimli kartımın vizesini nasıl yaparım? | E | metro.istanbul/icerik/seyahatkartlari | sehirhatlari.istanbul/tr/sikca-sorulan-sorular | 9.18 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q016 | Engelli İstanbulkart vizeleme neden başarısız oluyor, ne yapmalıyım? |  | istanbulkart.istanbul/duyurular/detay?id=2762 | istanbulkart.istanbul/duyurular/detay?id=2762 | 16.80 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q017 | Anne Kart’a kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.10 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q018 | Anne Kartım iptal olduysa ne yapmalıyım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 10.78 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q019 | 60 yaş indirimli İstanbulkart şartları nedir? | E | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Muzelerimiz/Cumhuriyet-Muzesi/41 | sehirhatlari.istanbul/tr/sikca-sorulan-sorular | 18.69 | 0.60 | hayır | out_of_scope/unknown | sufficient/quote_only | quote_only / knowledge |
| Q020 | Öğrenci abonmanı nasıl yüklenir? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 12.13 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q021 | Abonmanım neden tanımlanmıyor veya kullanım limiti hatası veriyor? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 11.85 | 0.17 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q022 | İstanbulkart’ıma bakiye nasıl yüklerim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.78 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q023 | QR ile ulaşımda nasıl ödeme yaparım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 14.26 | 0.50 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q024 | Dijital İstanbulkart indirimli/ücretsiz kart hakkımı taşır mı? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sehirhatlari.istanbul/tr/sikca-sorulan-sorular | 21.02 | 0.29 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q025 | Yeni su aboneliği nasıl açılır? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | esube.iski.gov.tr/files/mesafeliSozlesmeMetni.pdf | 11.46 | 1.00 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q026 | Su aboneliğini üzerime nasıl devralırım? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 8.85 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q027 | Su aboneliğini nasıl kapatırım? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 8.85 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q028 | İSKİ faturamı nereden sorgular ve öderim? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 6.27 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | answer / places_resolve |
| Q029 | Su faturama nasıl itiraz ederim? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.71 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q030 | Su kesintisi ne zaman bitecek? |  | itfaiye.ibb.gov.tr/tr/mudahale.html | iski.istanbul/iletisim/alo-185 | 11.30 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q031 | Bulunduğum mahallede su arızası var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.16 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q032 | Su sayacım arızalıysa ne yapmalıyım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 7.97 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q033 | Yüksek gelen su faturası için nereye başvurmalıyım? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | 9.52 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q034 | İSKİ borcu yüzünden kesilen su nasıl açılır? |  | tarim.ibb.istanbul/anadolu-yakasi-hal-mudurlugu/hizmet-standartlari.html | tarim.ibb.istanbul/anadolu-yakasi-hal-mudurlugu/hizmet-standartlari.html | 11.69 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q035 | Kanalizasyon tıkanıklığı veya taşması için nereye bildirim yaparım? |  | metro.istanbul/icerik/yolculuk_kurallari | metro.istanbul/icerik/yolculuk_kurallari | 9.69 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q036 | Yağmur suyu/rögar taşması ihbarını nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.25 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q037 | Yeni doğal gaz aboneliği nasıl açılır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.39 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q038 | Doğal gaz aboneliği için hangi belgeler gerekir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.39 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q039 | Abonelik başvurumdan sonra gaz ne zaman açılır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | cdn.iski.istanbul/uploads/ISKI_ABONE_HIZMETLERI_TARIFE_VE_UYGULAMA_Y_Oe_NETMELIGI_2024_150ea718d2.pdf | 11.63 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q040 | Doğal gaz faturamı nereden sorgular ve öderim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.39 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q041 | Doğal gaz aboneliğini nasıl kapatırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.39 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q042 | Gaz kaçağı şüphesinde kimi aramalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.80 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | redirect / · |
| Q043 | İGDAŞ randevum gecikirse ne yapmalıyım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 7.97 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q044 | Doğal gaz faturasına nasıl itiraz ederim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.39 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q045 | İBB sosyal yardımına nasıl başvururum? |  | istanbulsenin.istanbul | istanbulsenin.istanbul | 8.17 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q046 | Sosyal yardım başvurumun sonucunu nereden öğrenirim? |  | saglik.ibb.istanbul/sosyal-hizmetler-mudurlugu | saglik.ibb.istanbul/sosyal-hizmetler-mudurlugu | 9.28 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q047 | Başvurum neden planlama havuzunda bekliyor? |  | spor.istanbul/istanbul-kosu-rotalari | spor.istanbul/spor-okullari | 7.93 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q048 | Sosyal yardım için gelir şartı var mı? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 12.28 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q049 | Düzenli nakdi destek kimlere veriliyor? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/haberdetay.aspx?ID=9142 | 16.75 | 0.60 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q050 | İstanbulkart sosyal destek bakiyesi ne zaman yüklenir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 18.56 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q051 | Halk Süt’ten kimler yararlanabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/halksutnoktalari.aspx | 13.69 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q052 | Yenidoğan desteğine nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.71 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q053 | Geçim Sofra Desteği nedir, kimler alabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | 17.33 | 0.60 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| Q054 | Evlilik desteğine kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.38 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q055 | Emekli desteğine kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.71 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q056 | Askıda Fatura’ya faturamı nasıl bırakırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | iski.istanbul | 16.74 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / places_resolve |
| Q057 | Askıda Fatura’dan nasıl destek olurum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr | 18.32 | 0.60 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q058 | Sosyal yardım başvurum reddedildi; itiraz veya yeniden başvuru yolu var mı? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | 14.46 | 0.12 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q059 | Kızlar Okusun Diye desteğine kimler başvurabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | 22.04 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q060 | Kızlar Okusun Diye desteği ne kadar? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 24.73 | 1.00 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q061 | Sosyal yardım için 153 dışında hangi kanallar var? |  | metro.istanbul/icerik/sikayet_yonetim_sistemi | cdn.iski.istanbul/uploads/2023_SK_Hizmet_Envanteri_1e2db8b36d.pdf | 13.06 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q062 | Genç Üniversiteli eğitim desteğine nasıl başvururum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 19.48 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q063 | Genç Üniversiteli desteğinin şartları neler? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.63 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q064 | Genç Üniversiteli başvuru sonucumu nasıl öğrenirim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.63 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q065 | Sen Oku Diye desteğine kimler başvurabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | 17.98 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q066 | Sen Oku Diye başvurusu nasıl yapılır? |  | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | 17.97 | 0.67 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q067 | Enstitü İstanbul İSMEK kurslarına nasıl kayıt olurum? |  | ibb.istanbul | ibb.istanbul | 19.77 | 0.50 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q068 | İSMEK kursları ücretsiz mi? | E | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 14.36 | 0.33 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q069 | İSMEK’te hangi eğitim merkezleri var? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 16.37 | 0.75 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q070 | İSMEK’te uygun kursu nasıl bulurum? |  | ibb.istanbul | ibb.istanbul | 13.00 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q071 | İBB öğrenci yurtlarına nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.44 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q072 | Yuvamız İstanbul’a çocuk kaydı nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/tesislerimiz/uyelik-bilgileri | 13.99 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q073 | Yuvamız İstanbul’a kaç yaşındaki çocuklar alınır? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 9.61 | 0.14 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q074 | Yuvamız İstanbul başvuru şartları nelerdir? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.74 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q075 | Yuvamız İstanbul ücretli mi, ücreti ne kadar? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.56 | 0.50 | hayır | out_of_scope/unknown | weak/unknown | refused / refusal |
| Q076 | Başvuru için hangi belgeler gerekir? |  | imarmudurlugu.ibb.istanbul/dokumanlar | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.28 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q077 | Kreş kontenjanı ve sonuçları nereden öğrenilir? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 9.09 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q078 | Bana en yakın Yuvamız İstanbul merkezi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.21 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q079 | Kreşte yemek ve eğitim saatleri nedir? |  | spor.istanbul/doga-kampi | spor.istanbul/doga-kampi | 12.09 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q080 | İBB engelli merkezlerinden hangi hizmetleri alabilirim? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 7.41 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q081 | Bana en yakın engelli merkezi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/mudurlukdetay.aspx?ID=9 | 7.10 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q082 | Engelli bireyler için ulaşım veya refakat desteği var mı? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/mudurlukdetay.aspx?ID=9 | 17.67 | 0.40 | evet | weak/unknown | weak/unknown | refused / refusal |
| Q083 | Engelli bireyler için spor hizmetlerine nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/mudurlukdetay.aspx?ID=9 | 15.13 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q084 | Kısa Mola hizmeti nedir ve kimler yararlanabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sosyalhizmetler.ibb.gov.tr/mudurlukdetay.aspx?ID=9 | 24.34 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q085 | Evde sağlık hizmetine nasıl başvurulur? | E | saglik.ibb.istanbul/evde-saglik-hizmeti-2-2 | ibb.istanbul | 17.08 | 0.50 | hayır | sufficient/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q086 | Evde sağlık hizmeti kimlere verilir? | E | saglik.ibb.istanbul/evde-saglik-hizmeti-2-2 | saglik.ibb.istanbul/evde-saglik-hizmeti-2-2 | 16.29 | 0.60 | hayır | weak/unknown | sufficient/quote_only | quote_only / knowledge |
| Q087 | Tıp merkezlerinden nasıl randevu alırım? |  | istanbulsenin.istanbul | istanbulsenin.istanbul | 17.36 | 0.75 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q088 | Yaşlılar için evde destek veya bakım hizmeti var mı? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 15.50 | 0.60 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q089 | Darülaceze hizmetlerine kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.49 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q090 | İSPARK’ta aracımın borcu var mı, nasıl sorgularım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 10.02 | 0.20 | evet | out_of_scope/unknown | out_of_scope/unknown | answer / · |
| Q091 | İSPARK borcumu nasıl öderim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 16.30 | 0.67 | evet | sufficient/answer | sufficient/answer | answer / · |
| Q092 | Bana en yakın İSPARK nerede? |  | spor.istanbul/istanbul-yuzme-rotalari | spor.istanbul/istanbul-yuzme-rotalari | 12.58 | 0.67 | hayır | weak/unknown | weak/unknown | answer / · |
| Q093 | Otoparkta boş yer var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.49 | 0.33 | hayır | weak/unknown | weak/unknown | answer / · |
| Q094 | İSPARK ücret tarifesi ne kadar? | E | itfaiye.ibb.gov.tr/tr/baca-temizleme-yetki-belgesi.html | sehirhatlari.istanbul/tr/ibb-deniz-taksi-sikca-sorulan-sorular | 12.55 | 0.67 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q095 | Engelli araçları için İSPARK’ta ücretsiz/indirimli kullanım var mı? | E | metro.istanbul/icerik/seyahatkartlari | sehirhatlari.istanbul/tr/sikca-sorulan-sorular | 19.92 | 0.29 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q096 | İSPARK’ta kayıp eşya veya araç hasarı için nereye başvururum? |  | metro.istanbul/icerik/kayip-esya | metro.istanbul/icerik/kayip-esya | 16.96 | 0.29 | hayır | weak/unknown | weak/unknown | answer / · |
| Q097 | Vapur sefer saatlerini nereden öğrenirim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 13.04 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q098 | Bugün iptal edilen vapur seferi var mı? |  | metro.istanbul/Home/SikcaSorulanSorular | sehirhatlari.istanbul/tr/duyurular/kis-tarifesinde-yapilan-yeni-duzenlemeler-2278 | 12.99 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q099 | Vapur ücretleri ne kadar? | E | itfaiye.ibb.gov.tr/tr/t-madde-tasimaciliginda-refakat.html | spor.istanbul/hizmetlerimiz/acik-hava-egzersizleri | 8.05 | 0.50 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q100 | Adalar vapur tarifesi nedir? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | sehirhatlari.istanbul/tr/ucret-tarifeleri | 10.84 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q101 | Boğaz Turu saatleri ve ücreti nedir? | E | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 12.16 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q102 | Engelli yolcular için vapurlarda hangi imkânlar var? |  | metro.istanbul/icerik/erişilebilirlik-hizmetleri | sehirhatlari.istanbul/tr/bilgiler/engelli-yolcularimiz-icin-186 | 17.94 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q103 | Evcil hayvanla vapura binebilir miyim? |  | metro.istanbul/Home/SikcaSorulanSorular | sehirhatlari.istanbul/tr/ibb-deniz-taksi-sikca-sorulan-sorular | 23.70 | 0.60 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q104 | Vapurda kayıp eşya için nereye başvururum? |  | metro.istanbul/icerik/kayip-esya | metro.istanbul/icerik/kayip-esya | 16.96 | 0.50 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q105 | Şehir Hatları’na şikâyet veya öneri nasıl iletilir? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | sehirhatlari.istanbul/tr/basvuru-kanallari | 21.45 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q106 | Spor İstanbul tesislerine nasıl üye olurum? |  | ibb.istanbul | ibb.istanbul | 9.78 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q107 | Bana en yakın Spor İstanbul tesisi nerede? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/spor-okullari | 11.90 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q108 | Spor tesisi üyelik ücretleri ne kadar? | E | spor.istanbul/paket-uyelikleri | spor.istanbul/spor-okullari | 11.90 | 0.50 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q109 | Kadınlara 1 TL spor hizmeti nasıl kullanılır? | E | spor.istanbul/paket-uyelikleri | spor.istanbul/spor-okullari | 12.61 | 0.17 | hayır | weak/unknown | out_of_scope/unknown | refused / refusal |
| Q110 | Emeklilere 1 TL spor hizmeti nasıl kullanılır? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.17 | 0.50 | hayır | weak/unknown | weak/unknown | refused / refusal |
| Q111 | Öğrenci spor indirimi nasıl uygulanır? | E | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/spor-okullari | 12.60 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q112 | İBB Spor Okulları’na çocuk kaydı nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/tesislerimiz/uyelik-bilgileri | 17.93 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q113 | İBB etkinlik biletini nereden alırım? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 6.57 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q114 | Ücretsiz konser ve etkinliklere nasıl kayıt olurum? | E | istanbulsenin.istanbul | istanbulsenin.istanbul | 23.12 | 0.60 | hayır | sufficient/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q115 | İBB kütüphanelerine nasıl üye olurum? |  | istanbulsenin.istanbul | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Kutuphanelerimiz/IBB-Suat-Dervis-Kutuphanesi/59 | 11.13 | 0.50 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q116 | Evime en yakın afet toplanma alanı nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.34 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q117 | Mahallemin deprem riskini nereden görebilirim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.47 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q118 | Binamın hızlı tarama/bina analizi sonucu var mı? |  | binatespiti.ibb.istanbul/sikcasorulansorular | binatespiti.ibb.istanbul/sikcasorulansorular | 19.45 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q119 | Deprem sonrası geçici barınma alanları nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 20.75 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q120 | Afet anında İBB’den hangi kanallardan bilgi almalıyım? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 12.52 | 0.29 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q121 | Yangın için hangi numarayı aramalıyım? |  | itfaiye.ibb.gov.tr/tr/sik-sorulan-sorular.html | itfaiye.ibb.gov.tr/tr/sik-sorulan-sorular.html | 11.48 | 0.67 | hayır | weak/unknown | weak/unknown | redirect / · |
| Q122 | İtfaiyeden yangın güvenliği eğitimi alınabilir mi? |  | itfaiye.ibb.gov.tr/tr/egitim.html | itfaiye.ibb.gov.tr/tr/egitim.html | 16.41 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | redirect / · |
| Q123 | İş yeri için itfaiye raporu nasıl alınır? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 17.42 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q124 | İtfaiye olay raporuna nasıl ulaşırım? |  | itfaiye.ibb.gov.tr | itfaiye.ibb.gov.tr | 14.90 | 0.50 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q125 | Sel ve su baskını ihbarını nereye yapmalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.25 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q126 | Seyyar satıcı veya işgal şikâyetini nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.98 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q127 | Gürültü şikâyetini nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.46 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q128 | Çöp veya çevre kirliliği şikâyetini nereye yaparım? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 11.21 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q129 | Kaçak döküm veya moloz ihbarını nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.43 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q130 | Sokak hayvanı için acil yardım nereye bildirilir? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | 13.08 | 0.40 | hayır | weak/unknown | weak/unknown | redirect / · |
| Q131 | Bozuk yol veya kaldırım için nereye başvururum? |  | spor.istanbul/istanbul-kosu-rotalari | spor.istanbul/istanbul-kosu-rotalari | 12.88 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q132 | Yol çalışmasının ne zaman biteceğini nereden öğrenirim? |  | spor.istanbul/istanbul-bisiklet-rotalari | spor.istanbul/istanbul-bisiklet-rotalari | 9.61 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q133 | Taksi şoförü/araç hakkında nasıl şikâyet oluştururum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.42 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q134 | Taksi ücret uyuşmazlığını nereye bildiririm? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sehirhatlari.istanbul/tr/ibb-deniz-taksi-sikca-sorulan-sorular | 13.73 | 0.50 | hayır | out_of_scope/unknown | weak/unknown | refused / refusal |
| Q135 | Okul servisi için azami ücret ne kadar? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | 19.96 | 0.50 | evet | sufficient/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q136 | Okul servis ücretini rota üzerinden nasıl hesaplarım? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | 19.87 | 0.33 | evet | weak/unknown | weak/unknown | refused / refusal |
| Q137 | Cenaze olduğunda ilk kimi aramalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.22 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q138 | İBB cenaze nakil hizmeti nasıl alınır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 18.95 | 0.60 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| Q139 | Mezarlık yeri tahsisi nasıl yapılır? |  | ibb.istanbul | ibb.istanbul | 11.69 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q140 | Mezar yeri ücretleri ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.59 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q141 | Mezar yeri sorgulaması yapılabilir mi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.59 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q142 | Şehir dışına cenaze nakli nasıl yapılır? |  | ibb.istanbul | ibb.istanbul | 18.59 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q143 | Defin ruhsatı için hangi belgeler gerekir? |  | imarmudurlugu.ibb.istanbul/dokumanlar | imarmudurlugu.ibb.istanbul/dokumanlar | 14.97 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q144 | İBB’de nikâh işlemleri için nereye başvurulur? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Hakkinda/Kutuphane-Yonergesi/104 | sosyalhizmetler.ibb.gov.tr/haberdetay.aspx?ID=9142 | 9.35 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q145 | Nikâh için hangi belgeler gerekir? |  | imarmudurlugu.ibb.istanbul/dokumanlar | spor.istanbul/istanbul-yuzme-rotalari | 8.22 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q146 | En yakın Halk Ekmek büfesi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.22 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q147 | Halk Ekmek ürün fiyatları ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 19.28 | 0.50 | hayır | sufficient/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q148 | Halk Ekmek büfesi açmak için nasıl başvurulur? |  | ihe.istanbul | ihe.istanbul | 13.74 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q149 | En yakın Kent Lokantası nerede? |  | ibb.istanbul | ibb.istanbul | 13.14 | 0.67 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q150 | Kent Lokantası menüsü ve ücreti ne kadar? | E | ibb.istanbul | ibb.istanbul | 13.14 | 0.50 | evet | weak/unknown | weak/unknown | refused / refusal |
| h-01 | Gece metrosu hangi günler çalışıyor? |  | metro.istanbul/icerik/Gece-Metrosu | metro.istanbul/icerik/Gece-Metrosu | 18.10 | 0.50 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| h-02 | Gece otobüsleri hangi hatlarda çalışıyor? |  | metro.istanbul/icerik/Gece-Metrosu | sehirhatlari.istanbul/tr/ucret-tarifeleri | 14.88 | 0.50 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| h-03 | Gece metrosu seferleri saat kaçta başlıyor? |  | metro.istanbul/icerik/Gece-Metrosu | metro.istanbul/icerik/Gece-Metrosu | 26.43 | 0.50 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| h-04 | Hızlı bina taraması nedir? |  | binatespiti.ibb.istanbul/projebilgisi | binatespiti.ibb.istanbul/projebilgisi | 11.22 | 0.67 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-05 | Hızlı tarama raporu ne zaman çıkar? |  | binatespiti.ibb.istanbul/projebilgisi | binatespiti.ibb.istanbul/projebilgisi | 13.39 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-06 | Hızlı taramada neden karot alınmıyor? |  | binatespiti.ibb.istanbul/sikcasorulansorular | binatespiti.ibb.istanbul/sikcasorulansorular | 13.81 | 0.25 | evet | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| h-07 | 153 Çözüm Merkezi'ne nasıl ulaşırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 14.01 | 0.75 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| h-08 | Metroda yolcu hakları nelerdir? | E | metro.istanbul/icerik/yolcu_haklari_bildirgesi | metro.istanbul/icerik/yolcu_haklari_bildirgesi | 11.47 | 0.50 | evet | weak/unknown | weak/unknown | refused / refusal |
| h-09 | İETT yolcu hakları bildirgesinde ne yazıyor? | E | iett.istanbul/passengerapplication | iett.istanbul/passengerapplication | 13.81 | 0.40 | hayır | weak/unknown | weak/unknown | refused / refusal |
| h-10 | İETT'ye şikâyet başvurusu nasıl yapılır? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 15.33 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| h-11 | Metro İstanbul'a şikâyet ya da öneri nasıl iletilir? |  | metro.istanbul/icerik/sikayet_yonetim_sistemi | metro.istanbul/icerik/sikayet_yonetim_sistemi | 16.88 | 0.67 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| h-12 | İstanbul Senin uygulamasından şikâyet oluşturabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 35.50 | 0.83 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| h-13 | İstanbul Senin uygulamasına nasıl giriş yapılır? |  | istanbulsenin.istanbul | istanbulsenin.istanbul | 21.70 | 0.75 | hayır | sufficient/answer | sufficient/answer | answer / knowledge |
| h-14 | Metro istasyonlarında erişilebilirlik hizmetleri neler? |  | metro.istanbul/icerik/erişilebilirlik-hizmetleri | metro.istanbul/icerik/erişilebilirlik-hizmetleri | 17.56 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-15 | İBB Açık Veri Portalı'ndan veri isteği nasıl yapılır? |  | data.ibb.gov.tr/datarequest | data.ibb.gov.tr/datarequest | 26.80 | 0.67 | evet | sufficient/answer | sufficient/answer | answer / knowledge |
| h-16 | İSPARK otopark ücretleri ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | ispark.istanbul | 14.07 | 0.33 | evet | weak/unknown | weak/unknown | refused / refusal |
| h-17 | 500T otobüsü Kadıköy'e ne zaman gelir? |  | data.ibb.gov.tr/license | data.ibb.gov.tr/license | 10.90 | 0.17 | · | out_of_scope/unknown | out_of_scope/unknown | answer / iett_next_arrivals |
| h-18 | M2 metro hattında arıza var mı? |  | metro.istanbul/Home/SikcaSorulanSorular | metro.istanbul/Home/SikcaSorulanSorular | 14.22 | 0.75 | · | weak/unknown | weak/unknown | answer / metro_status |
| h-19 | Kartal metro istasyonunda asansör var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.46 | 0.50 | · | weak/unknown | weak/unknown | answer / metro_equipment_status |
| h-20 | Kadıköy'de boş otopark var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.99 | 0.67 | · | weak/unknown | weak/unknown | answer / ispark_find_parking |
| d-01 | Öğrenci kartı vizesi nasıl yapılır? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | spor.istanbul/spor-okullari | 14.88 | 0.67 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| d-02 | İSKİ su kesintisi nereden öğrenilir? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | iski.istanbul/iletisim/alo-185 | 16.16 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| d-03 | Doğalgaz açma randevusu nasıl alınır? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 12.51 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| d-04 | insanla görüşmek istiyorum |  | metro.istanbul/Home/SikcaSorulanSorular | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 7.78 | 0.00 | · | weak/unknown | out_of_scope/unknown | handoff / layer:handoff |
| d-05 | gaz kaçağı var |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.80 | 0.50 | · | weak/unknown | weak/unknown | redirect / · |
| d-06 | Doğalgaz kaçağı var galiba, koku geliyor |  | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | 7.34 | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | redirect / · |
| n-15 | Doğalgaz faturası nereden ödenir? |  | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | cdn.iski.istanbul/uploads/2023_SK_Hizmet_Envanteri_1e2db8b36d.pdf | 7.90 | 0.33 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-16 | Doğalgaz aboneliği nasıl yapılır? |  | ibb.istanbul | cdn.iski.istanbul/uploads/2023_SK_Hizmet_Envanteri_1e2db8b36d.pdf | 14.41 | 0.50 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| k-01 | İSKİ su aboneliğini iptal etmek için hangi belgeler gerekir? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | iski.istanbul/abone-hizmetleri/abone-rehberi/abonelik-iptal-islemleri | 16.28 | 0.17 | evet | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| k-02 | İSKİ'de abonelik isim değişikliği nasıl yapılır? |  | ibb.istanbul | cdn.iski.istanbul/uploads/ISKI_ABONE_HIZMETLERI_TARIFE_VE_UYGULAMA_Y_Oe_NETMELIGI_2024_150ea718d2.pdf | 16.31 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| k-03 | Yabancı uyruklu biri İSKİ su aboneliğini nasıl açar? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 18.05 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| k-04 | ALO 185'e hangi kanallardan ulaşabilirim? |  | metro.istanbul/icerik/sikayet_yonetim_sistemi | iski.istanbul/iletisim/alo-185 | 15.09 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| k-05 | İSKİ veznelerinin adresleri ve çalışma saatleri nedir? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Muzelerimiz/Belgradkapi-Ziyaretci-Merkezi/26 | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Muzelerimiz/Belgradkapi-Ziyaretci-Merkezi/26 | 9.55 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| k-06 | İstanbul'da içme suyu nasıl arıtılıyor? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 14.27 | 0.75 | hayır | sufficient/answer | weak/unknown | unknown / knowledge |
| k-07 | İGDAŞ güvence bedeli iadesini nereden alabilirim? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.65 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| k-08 | Doğalgaz faturasındaki kalemler ne anlama geliyor? |  | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | 7.34 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| k-09 | Doğalgazımı geçici olarak kapattırmak istiyorum, ne yapmalıyım? |  | metro.istanbul/Home/SikcaSorulanSorular | metro.istanbul/Home/SikcaSorulanSorular | 12.66 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| k-10 | Doğalgaz sabit ödeme sistemi nedir? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 11.88 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| k-11 | Haliç vapur hattının sefer saatleri nedir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.48 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | answer / places_resolve |
| k-12 | Şehir Hatları vapurunda kaybettiğim eşyayı nasıl bulurum? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | istanbulsenin.istanbul/sikca-sorulan-sorular | 9.53 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| k-13 | Deniz taksi nasıl çağrılır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sehirhatlari.istanbul/tr/ibb-deniz-taksi-sikca-sorulan-sorular | 17.66 | 0.67 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| k-14 | Şehir Hatları vapurlarında engelli yolcular için hangi hizmetler var? |  | metro.istanbul/icerik/erişilebilirlik-hizmetleri | sehirhatlari.istanbul/tr/bilgiler/engelli-yolcularimiz-icin-186 | 27.41 | 0.67 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| k-15 | Kış tarifesinde vapur seferlerinde ne değişti? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sehirhatlari.istanbul/tr/duyurular/kis-tarifesinde-yapilan-yeni-duzenlemeler-2278 | 16.33 | 0.40 | evet | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-01 | yarın hava nasıl |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.81 | 0.50 | · | weak/unknown | weak/unknown | answer / · |
| n-02 | en iyi kebapçı nerede |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 5.53 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-03 | Galatasaray maçı kaçta başlıyor? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | spor.istanbul/engelli-bireylere-ozel-hizmetlerimiz | 8.33 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-04 | Bana kısa bir şiir yazar mısın? |  | kultur.istanbul | kultur.istanbul | 8.13 | 0.20 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-05 | Python'da bir liste nasıl sıralanır? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Kutuphanelerimiz | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Kutuphanelerimiz | 10.60 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-06 | Bu akşam hangi dizi izlenir? |  | itfaiye.ibb.gov.tr/tr/egitim.html | itfaiye.ibb.gov.tr/tr/egitim.html | 9.55 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-07 | Tatilde nereye gitsem? |  | · | · | · | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-08 | Kedim yemek yemiyor, ne yapmalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.97 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-09 | Yarın okullar tatil mi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | sehirhatlari.istanbul/tr/seferler/ic-hatlar/istanbul-ici-hatlar/halic-hatti-37 | 9.54 | 0.33 | · | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-10 | En güzel börek tarifi nedir? |  | cevre.ibb.istanbul/cevre-koruma-sube-mudurlugu/avrupa-yakasi-cevre-laboratuvari | cevre.ibb.istanbul/cevre-koruma-sube-mudurlugu/avrupa-yakasi-cevre-laboratuvari | 9.68 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-11 | Ehliyet sınavı ne zaman yapılıyor? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 7.33 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-12 | Pasaport başvurusu nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/tesislerimiz/uyelik-bilgileri | 13.13 | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-13 | Askerlik yoklaması nereden yapılır? |  | ibb.istanbul | cdn.iski.istanbul/uploads/2023_SK_Hizmet_Envanteri_1e2db8b36d.pdf | 8.00 | 0.50 | · | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-14 | Elektrik faturası neden bu kadar yüksek geldi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.71 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-17 | Dolar bugün kaç TL? | E | data.ibb.gov.tr/datarequest | data.ibb.gov.tr/datarequest | 7.66 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| n-18 | Ev kirası bu yıl ne kadar artar? | E | spor.istanbul/tesislerimiz/uyelik-bilgileri | spor.istanbul/spor-okullari | 10.33 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| n-19 | Baş ağrısına hangi ilaç iyi gelir? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.50 | 0.40 | · | weak/unknown | weak/unknown | refused / refusal |
| n-20 | Kredi kartı borcumu nasıl yapılandırırım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | sehirhatlari.istanbul/tr/ibb-deniz-taksi-sikca-sorulan-sorular | 15.45 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-21 | Yapay zekâ işimi elimden alır mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.21 | 0.40 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-22 | Ankara'ya en ucuz uçak bileti hangi gün? | E | iett.istanbul/icerik/yuksek-hizli-trene-ulasim | iett.istanbul/icerik/yuksek-hizli-trene-ulasim | 6.26 | 0.20 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| n-23 | Elektrik aboneliği nasıl yapılır? |  | ibb.istanbul | cdn.iski.istanbul/uploads/ISKI_ABONE_HIZMETLERI_TARIFE_VE_UYGULAMA_Y_Oe_NETMELIGI_2024_150ea718d2.pdf | 13.59 | 0.50 | · | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-24 | Elektrik kesintisi ne zaman bitecek? |  | itfaiye.ibb.gov.tr/tr/mudahale.html | itfaiye.ibb.gov.tr/tr/mudahale.html | 9.38 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-25 | Cep telefonu faturası nasıl ödenir? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Hakkinda/Kutuphane-Yonergesi/104 | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Hakkinda/Kutuphane-Yonergesi/104 | 9.20 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-26 | Uçak bileti iptali nasıl yapılır? | E | ibb.istanbul | ibb.istanbul | 11.69 | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |

## Yeni dizinde etkin olmayan altın URL'ler

| id | altın URL |
|---|---|
| Q037 | https://www.igdas.istanbul/ |
| Q038 | https://www.igdas.istanbul/ |
| Q039 | https://www.igdas.istanbul/ |
| Q040 | https://www.igdas.istanbul/ |
| Q041 | https://www.igdas.istanbul/ |
| Q042 | https://www.igdas.istanbul/ |
| Q043 | https://www.igdas.istanbul/ |
| Q044 | https://www.igdas.istanbul/ |
| Q072 | https://yuvamiz.ibb.istanbul/ |
| Q073 | https://yuvamiz.ibb.istanbul/ |
| Q074 | https://yuvamiz.ibb.istanbul/ |
| Q075 | https://yuvamiz.ibb.istanbul/ |
| Q076 | https://yuvamiz.ibb.istanbul/ |
| Q077 | https://yuvamiz.ibb.istanbul/ |
| Q078 | https://yuvamiz.ibb.istanbul/ |
| Q079 | https://yuvamiz.ibb.istanbul/ |
| Q137 | https://mezarliklar.ibb.istanbul/ |
| Q138 | https://mezarliklar.ibb.istanbul/ |
| Q139 | https://mezarliklar.ibb.istanbul/ |
| Q140 | https://mezarliklar.ibb.istanbul/ |
| Q141 | https://mezarliklar.ibb.istanbul/ |
| Q142 | https://mezarliklar.ibb.istanbul/ |
| Q143 | https://mezarliklar.ibb.istanbul/ |
| Q144 | https://www.turkiye.gov.tr/istanbul-buyuksehir-belediyesi |
| Q145 | https://www.turkiye.gov.tr/istanbul-buyuksehir-belediyesi |
| d-03 | https://igdas.istanbul/gaz-acma-randevusu |
| n-15 | https://igdas.istanbul/veznelerimiz/ |
| n-15 | https://igdas.istanbul/sabit-odeme-sistemi |
| n-16 | https://www.igdas.istanbul/abonelik-sozlesmesi |
| k-02 | https://iski.istanbul/abone-hizmetleri/abone-rehberi/abonelik-isim-degisikligi/ |
| k-03 | https://iski.istanbul/abone-hizmetleri/abone-rehberi/yabanci-uyruklu-kisilerin-abonelik-islemleri |
| k-05 | https://iski.istanbul/abone-hizmetleri/oedeme-kanallari/vezneler/tum-vezneler |
| k-06 | https://iski.istanbul/kurumsal/hakkimizda/icme-suyu-kalitesi/icilebilir-su-seruveni |
| k-07 | https://www.igdas.istanbul/para-iade-noktalari/ |
| k-08 | https://www.igdas.istanbul/faturada-ne-nedir |
| k-09 | https://www.igdas.istanbul/gecici-dogal-gaz-acmakapama/ |
| k-10 | https://igdas.istanbul/sabit-odeme-sistemi |

## Eşik taraması

Seçim: negatif cevap 0; negatiflerin kapsamı eşik üstü en yüksek BM25 değeri yoksa null, varsa `fts_min - 2` veya altı; ardından altın ilk kaynak sayısı yüksek, altın dışı ilk kaynak sayısı düşük, eşitlikte yüksek eşikler.

| fts_min | min_coverage | answer | quote_only | unknown | altın ilk kaynak | altın dışı ilk kaynak | negatif cevap | negatiflerin en yüksek bm25'i (kapsam geçen) |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8.00 | 0.34 | 91 | 18 | 108 | 28 | 70 | 7 | 15.45 |
| 8.00 | 0.40 | 91 | 18 | 108 | 28 | 70 | 7 | 15.45 |
| 8.00 | 0.50 | 59 | 15 | 143 | 21 | 44 | 5 | 15.45 |
| 8.00 | 0.60 | 32 | 5 | 180 | 13 | 22 | 0 | · |
| 10.00 | 0.34 | 83 | 15 | 119 | 28 | 64 | 3 | 15.45 |
| 10.00 | 0.40 | 83 | 15 | 119 | 28 | 64 | 3 | 15.45 |
| 10.00 | 0.50 | 55 | 13 | 149 | 21 | 42 | 2 | 15.45 |
| **kural** 10.00 | 0.60 | 32 | 5 | 180 | 13 | 22 | 0 | · |
| 12.00 | 0.34 | 75 | 12 | 130 | 26 | 56 | 3 | 15.45 |
| 12.00 | 0.40 | 75 | 12 | 130 | 26 | 56 | 3 | 15.45 |
| 12.00 | 0.50 | 49 | 10 | 158 | 19 | 36 | 2 | 15.45 |
| 12.00 | 0.60 | 28 | 4 | 185 | 12 | 19 | 0 | · |
| 14.00 | 0.34 | 62 | 7 | 148 | 22 | 45 | 1 | 15.45 |
| 14.00 | 0.40 | 62 | 7 | 148 | 22 | 45 | 1 | 15.45 |
| 14.00 | 0.50 | 43 | 6 | 168 | 17 | 30 | 1 | 15.45 |
| 14.00 | 0.60 | 26 | 3 | 188 | 11 | 17 | 0 | · |
| 16.00 | 0.34 | 45 | 7 | 165 | 19 | 33 | 0 | 15.45 |
| 16.00 | 0.40 | 45 | 7 | 165 | 19 | 33 | 0 | 15.45 |
| **seçildi** 16.00 | 0.50 | 31 | 6 | 180 | 15 | 22 | 0 | 15.45 |
| 16.00 | 0.60 | 21 | 3 | 193 | 11 | 13 | 0 | · |
| 18.00 | 0.34 | 23 | 4 | 190 | 10 | 17 | 0 | 15.45 |
| 18.00 | 0.40 | 23 | 4 | 190 | 10 | 17 | 0 | 15.45 |
| 18.00 | 0.50 | 18 | 4 | 195 | 9 | 13 | 0 | 15.45 |
| 18.00 | 0.60 | 12 | 2 | 203 | 5 | 9 | 0 | · |
| 20.00 | 0.34 | 14 | 1 | 202 | 7 | 8 | 0 | 15.45 |
| 20.00 | 0.40 | 14 | 1 | 202 | 7 | 8 | 0 | 15.45 |
| 20.00 | 0.50 | 11 | 1 | 205 | 6 | 6 | 0 | 15.45 |
| 20.00 | 0.60 | 9 | 1 | 207 | 5 | 5 | 0 | · |
| 22.00 | 0.34 | 11 | 1 | 205 | 7 | 5 | 0 | 15.45 |
| 22.00 | 0.40 | 11 | 1 | 205 | 7 | 5 | 0 | 15.45 |
| 22.00 | 0.50 | 9 | 1 | 207 | 6 | 4 | 0 | 15.45 |
| 22.00 | 0.60 | 8 | 1 | 208 | 5 | 4 | 0 | · |
| 24.00 | 0.34 | 9 | 0 | 208 | 6 | 3 | 0 | 15.45 |
| 24.00 | 0.40 | 9 | 0 | 208 | 6 | 3 | 0 | 15.45 |
| 24.00 | 0.50 | 8 | 0 | 209 | 6 | 2 | 0 | 15.45 |
| 24.00 | 0.60 | 7 | 0 | 210 | 5 | 2 | 0 | · |
| 26.00 | 0.34 | 6 | 0 | 211 | 5 | 1 | 0 | 15.45 |
| 26.00 | 0.40 | 6 | 0 | 211 | 5 | 1 | 0 | 15.45 |
| 26.00 | 0.50 | 6 | 0 | 211 | 5 | 1 | 0 | 15.45 |
| 26.00 | 0.60 | 5 | 0 | 212 | 4 | 1 | 0 | · |
| 28.00 | 0.34 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 28.00 | 0.40 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 28.00 | 0.50 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 28.00 | 0.60 | 2 | 0 | 215 | 2 | 0 | 0 | · |
| 30.00 | 0.34 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 30.00 | 0.40 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 30.00 | 0.50 | 2 | 0 | 215 | 2 | 0 | 0 | 15.45 |
| 30.00 | 0.60 | 2 | 0 | 215 | 2 | 0 | 0 | · |

Kuralın seçtiği satır (`**kural**`) sonra koşusunun eşikleri değil; neden reddedildiği DECISIONS.md'de.
