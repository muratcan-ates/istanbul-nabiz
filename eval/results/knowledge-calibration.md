# Bilgi dizini eşik ölçümü: önce / sonra

`scripts/knowledge_calibration.py` çıktısından üretildi; elle sayı yazılmadı. Dizin: yerel
`data/knowledge/knowledge.db`. Arama modelsiz ve gömmesiz (`embedder=None`): çevrimdışı sohbet sorgu
gömmesi yapmaz, bu yüzden kosinüs sütunu yok. Hassaslık `policy.refuses` ile, sohbetin kararıyla aynı
(`hassas` sütunu); `seed-hassas` kümesi araştırma tohumunun kendi `sensitive` işaretidir. `seed` ve
`seed-hassas` araştırma tohumunun 150 sorusu (depo dışında); öteki kümeler `eval/knowledge_calibration.jsonl`.
Altın dışı kaynak her zaman yanlış değildir (ör. aynı kurumun başka sayfası); negatif kümedeki her cevap yanlıştır.

Önce eşikler: `{"min_cosine": 0.35, "fts_ceiling": 1.0, "coverage_ceiling": 0.27}` · Sonra eşikler: `{"min_cosine": 0.35, "fts_min": 16.0, "min_coverage": 0.5, "coverage_ceiling": 0.27}`

## Özet

| Küme | n | önce answer | önce quote_only | önce unknown | sonra answer | sonra quote_only | sonra unknown |
|---|---:|---:|---:|---:|---:|---:|---:|
| demo | 6 | 0 | 0 | 6 | 0 | 0 | 6 |
| hafifletiyor | 20 | 0 | 3 | 17 | 6 | 0 | 14 |
| negatif | 22 | 0 | 1 | 21 | 0 | 0 | 22 |
| seed | 41 | 0 | 2 | 39 | 7 | 0 | 34 |
| seed-hassas | 109 | 0 | 22 | 87 | 9 | 4 | 96 |
| **toplam** | 198 | 0 | 28 | 170 | 22 | 4 | 172 |

| Ölçü | önce | sonra |
|---|---:|---:|
| Altın URL'si olan soru | 166 | 166 |
| İlk sonuç altın URL | 29 | 29 |
| Altın URL ilk 8'de | 56 | 56 |
| Cevaplanan (answer/quote_only) ve altını olan | 27 | 26 |
| … ilk kaynağı altın URL | 4 | 13 |
| … ilk kaynağı altın dışı | 23 | 13 |
| Negatif kümede cevap (yanlış pozitif) | 1 | 0 |

Sohbet (`/api/chat`, çevrimdışı, model yok) modları, aynı 198 soru:

| Sohbet modu | önce | sonra |
|---|---:|---:|
| answer | 20 | 37 |
| handoff | 0 | 1 |
| quote_only | 28 | 4 |
| redirect | 3 | 6 |
| refused | 3 | 27 |
| unknown | 144 | 123 |

## Soru başına

`bm25` ilk sonucun FTS5 puanının mutlak değeri (büyük = daha iyi eşleşme); `kapsam` sorunun ayırt edici
kelimelerinden ilk alıntıda geçenlerin oranı (sonra koşusu); `altın` ilk sonucun sorunun altın URL'lerinden biri olup
olmadığı (`·` altın yok). Sohbet sütunu `--chat` koşusunda `/api/chat`'in modu ve kuralıdır.

| id | soru | hassas | ilk sonuç | bm25 | kapsam | altın | önce seviye/mod | sonra seviye/mod | sohbet (sonra) |
|---|---|:-:|---|---:|---:|:-:|---|---|---|
| Q001 | 153’e nasıl başvuru yaparım? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 12.28 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q002 | 153 başvurumu nereden takip ederim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.76 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q003 | İstanbul Senin’den şikâyet oluşturabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 24.48 | 0.83 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q004 | Canlı desteğe nasıl ulaşırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.76 | 0.33 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q005 | 153’e WhatsApp’tan yazabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 13.58 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q006 | İstanbul Senin ücretsiz mi? | E | istanbulsenin.istanbul | 10.86 | 1.00 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q007 | İstanbul Senin’e T.C. kimlik numarası olmadan girebilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 34.33 | 0.60 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q008 | Yabancı uyruklular İstanbul Senin’e kayıt olabilir mi? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 18.16 | 0.57 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q009 | İstanbul Senin’de hangi faturaları ödeyebilirim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 17.20 | 1.00 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q010 | İBB Wi‑Fi’ye İstanbul Senin’den nasıl bağlanırım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 25.29 | 0.62 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q011 | Öğrenci İstanbulkart’a nasıl başvururum? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | 19.72 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q012 | Öğrenci kartı başvurusu artık sadece internetten mi yapılıyor? |  | metro.istanbul/Home/SikcaSorulanSorular | 11.65 | 0.17 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q013 | İstanbulkart Plus nedir, nasıl başvurulur? |  | istanbulkart.istanbul/duyurular/detay?id=2780 | 18.27 | 0.67 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q014 | Kaybolan İstanbulkart’ımı nasıl kapatırım ve yenisini alırım? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | 11.18 | 0.17 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q015 | İndirimli kartımın vizesini nasıl yaparım? | E | metro.istanbul/icerik/seyahatkartlari | 8.53 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| Q016 | Engelli İstanbulkart vizeleme neden başarısız oluyor, ne yapmalıyım? |  | istanbulkart.istanbul/duyurular/detay?id=2762 | 17.06 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q017 | Anne Kart’a kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.04 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q018 | Anne Kartım iptal olduysa ne yapmalıyım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 10.56 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q019 | 60 yaş indirimli İstanbulkart şartları nedir? | E | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Muzelerimiz/Cumhuriyet-Muzesi/41 | 12.56 | 0.20 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q020 | Öğrenci abonmanı nasıl yüklenir? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 11.95 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q021 | Abonmanım neden tanımlanmıyor veya kullanım limiti hatası veriyor? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 11.48 | 0.17 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q022 | İstanbulkart’ıma bakiye nasıl yüklerim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.48 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q023 | QR ile ulaşımda nasıl ödeme yaparım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 14.38 | 0.50 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q024 | Dijital İstanbulkart indirimli/ücretsiz kart hakkımı taşır mı? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 19.95 | 0.29 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q025 | Yeni su aboneliği nasıl açılır? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 9.34 | 0.00 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q026 | Su aboneliğini üzerime nasıl devralırım? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 9.34 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q027 | Su aboneliğini nasıl kapatırım? |  | itfaiye.ibb.gov.tr/tr/itfai-olay-raporu.html | 9.34 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q028 | İSKİ faturamı nereden sorgular ve öderim? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | 8.38 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | answer / places_resolve |
| Q029 | Su faturama nasıl itiraz ederim? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.68 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q030 | Su kesintisi ne zaman bitecek? |  | itfaiye.ibb.gov.tr/tr/mudahale.html | 10.81 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q031 | Bulunduğum mahallede su arızası var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.56 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q032 | Su sayacım arızalıysa ne yapmalıyım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 7.72 | 0.33 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q033 | Yüksek gelen su faturası için nereye başvurmalıyım? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | 10.18 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q034 | İSKİ borcu yüzünden kesilen su nasıl açılır? |  | tarim.ibb.istanbul/anadolu-yakasi-hal-mudurlugu/hizmet-standartlari.html | 13.63 | 0.00 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q035 | Kanalizasyon tıkanıklığı veya taşması için nereye bildirim yaparım? |  | metro.istanbul/icerik/yolculuk_kurallari | 9.44 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q036 | Yağmur suyu/rögar taşması ihbarını nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.85 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q037 | Yeni doğal gaz aboneliği nasıl açılır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.91 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q038 | Doğal gaz aboneliği için hangi belgeler gerekir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.91 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q039 | Abonelik başvurumdan sonra gaz ne zaman açılır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.42 | 0.20 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q040 | Doğal gaz faturamı nereden sorgular ve öderim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.91 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q041 | Doğal gaz aboneliğini nasıl kapatırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.91 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q042 | Gaz kaçağı şüphesinde kimi aramalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.42 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | redirect / · |
| Q043 | İGDAŞ randevum gecikirse ne yapmalıyım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 7.72 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q044 | Doğal gaz faturasına nasıl itiraz ederim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.91 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q045 | İBB sosyal yardımına nasıl başvururum? |  | istanbulsenin.istanbul | 7.78 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q046 | Sosyal yardım başvurumun sonucunu nereden öğrenirim? |  | saglik.ibb.istanbul/sosyal-hizmetler-mudurlugu | 9.15 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q047 | Başvurum neden planlama havuzunda bekliyor? |  | istanbulsenin.istanbul | 5.89 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q048 | Sosyal yardım için gelir şartı var mı? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 12.23 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q049 | Düzenli nakdi destek kimlere veriliyor? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.50 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q050 | İstanbulkart sosyal destek bakiyesi ne zaman yüklenir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 18.08 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q051 | Halk Süt’ten kimler yararlanabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 14.29 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q052 | Yenidoğan desteğine nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.49 | 0.33 | hayır | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| Q053 | Geçim Sofra Desteği nedir, kimler alabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | 17.50 | 0.60 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| Q054 | Evlilik desteğine kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.27 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q055 | Emekli desteğine kimler başvurabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.45 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q056 | Askıda Fatura’ya faturamı nasıl bırakırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 14.48 | 0.50 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q057 | Askıda Fatura’dan nasıl destek olurum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 17.98 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q058 | Sosyal yardım başvurum reddedildi; itiraz veya yeniden başvuru yolu var mı? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | 14.26 | 0.12 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q059 | Kızlar Okusun Diye desteğine kimler başvurabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | 21.97 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q060 | Kızlar Okusun Diye desteği ne kadar? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 24.49 | 1.00 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q061 | Sosyal yardım için 153 dışında hangi kanallar var? |  | metro.istanbul/icerik/sikayet_yonetim_sistemi | 12.99 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q062 | Genç Üniversiteli eğitim desteğine nasıl başvururum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 18.73 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q063 | Genç Üniversiteli desteğinin şartları neler? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.03 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q064 | Genç Üniversiteli başvuru sonucumu nasıl öğrenirim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.03 | 0.40 | hayır | weak/unknown | weak/unknown | answer / places_resolve |
| Q065 | Sen Oku Diye desteğine kimler başvurabilir? |  | istanbulseninhaber.ibb.istanbul/haber-detay/ibbden-30-bin-haneye-egitim-destegi | 17.90 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q066 | Sen Oku Diye başvurusu nasıl yapılır? |  | istanbulseninhaber.ibb.istanbul/haber-detay/2026da-da-istanbul-seninle | 17.89 | 0.67 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q067 | Enstitü İstanbul İSMEK kurslarına nasıl kayıt olurum? |  | ibb.istanbul | 18.82 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q068 | İSMEK kursları ücretsiz mi? | E | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 14.05 | 0.33 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q069 | İSMEK’te hangi eğitim merkezleri var? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 15.42 | 0.75 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q070 | İSMEK’te uygun kursu nasıl bulurum? |  | ibb.istanbul | 12.44 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q071 | İBB öğrenci yurtlarına nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.42 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q072 | Yuvamız İstanbul’a çocuk kaydı nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 14.59 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q073 | Yuvamız İstanbul’a kaç yaşındaki çocuklar alınır? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | 10.73 | 0.29 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q074 | Yuvamız İstanbul başvuru şartları nelerdir? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 12.26 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q075 | Yuvamız İstanbul ücretli mi, ücreti ne kadar? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | 9.12 | 0.25 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q076 | Başvuru için hangi belgeler gerekir? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.67 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q077 | Kreş kontenjanı ve sonuçları nereden öğrenilir? |  | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 8.80 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q078 | Bana en yakın Yuvamız İstanbul merkezi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.72 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q079 | Kreşte yemek ve eğitim saatleri nedir? |  | spor.istanbul/doga-kampi | 12.29 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q080 | İBB engelli merkezlerinden hangi hizmetleri alabilirim? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 7.21 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q081 | Bana en yakın engelli merkezi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 7.20 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q082 | Engelli bireyler için ulaşım veya refakat desteği var mı? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.63 | 0.40 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q083 | Engelli bireyler için spor hizmetlerine nasıl başvurulur? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.00 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q084 | Kısa Mola hizmeti nedir ve kimler yararlanabilir? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 19.40 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q085 | Evde sağlık hizmetine nasıl başvurulur? | E | saglik.ibb.istanbul/evde-saglik-hizmeti-2-2 | 16.41 | 0.50 | hayır | weak/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q086 | Evde sağlık hizmeti kimlere verilir? | E | saglik.ibb.istanbul/evde-saglik-hizmeti-2-2 | 15.63 | 0.60 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q087 | Tıp merkezlerinden nasıl randevu alırım? |  | istanbulsenin.istanbul | 16.86 | 0.75 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q088 | Yaşlılar için evde destek veya bakım hizmeti var mı? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 14.77 | 0.60 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q089 | Darülaceze hizmetlerine kimler başvurabilir? |  | spor.istanbul/grup-derslerimiz | 8.07 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q090 | İSPARK’ta aracımın borcu var mı, nasıl sorgularım? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 9.83 | 0.20 | evet | weak/unknown | out_of_scope/unknown | answer / · |
| Q091 | İSPARK borcumu nasıl öderim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 16.06 | 0.67 | evet | weak/unknown | sufficient/answer | answer / · |
| Q092 | Bana en yakın İSPARK nerede? |  | ispark.istanbul | 8.07 | 0.33 | evet | weak/unknown | weak/unknown | answer / · |
| Q093 | Otoparkta boş yer var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.33 | 0.33 | hayır | weak/unknown | weak/unknown | answer / · |
| Q094 | İSPARK ücret tarifesi ne kadar? | E | itfaiye.ibb.gov.tr/tr/baca-temizleme-yetki-belgesi.html | 12.92 | 0.67 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q095 | Engelli araçları için İSPARK’ta ücretsiz/indirimli kullanım var mı? | E | metro.istanbul/icerik/seyahatkartlari | 14.68 | 0.29 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q096 | İSPARK’ta kayıp eşya veya araç hasarı için nereye başvururum? |  | metro.istanbul/icerik/kayip-esya | 16.05 | 0.29 | hayır | weak/unknown | weak/unknown | answer / · |
| Q097 | Vapur sefer saatlerini nereden öğrenirim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 14.15 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q098 | Bugün iptal edilen vapur seferi var mı? |  | metro.istanbul/Home/SikcaSorulanSorular | 8.99 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q099 | Vapur ücretleri ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 7.57 | 0.50 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q100 | Adalar vapur tarifesi nedir? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 7.92 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q101 | Boğaz Turu saatleri ve ücreti nedir? | E | itfaiye.ibb.gov.tr/tr/ilkyardim-egitimleri.html | 13.06 | 0.25 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q102 | Engelli yolcular için vapurlarda hangi imkânlar var? |  | metro.istanbul/icerik/erişilebilirlik-hizmetleri | 14.20 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q103 | Evcil hayvanla vapura binebilir miyim? |  | metro.istanbul/Home/SikcaSorulanSorular | 18.24 | 0.60 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q104 | Vapurda kayıp eşya için nereye başvururum? |  | metro.istanbul/icerik/kayip-esya | 16.05 | 0.50 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q105 | Şehir Hatları’na şikâyet veya öneri nasıl iletilir? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 19.43 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q106 | Spor İstanbul tesislerine nasıl üye olurum? |  | ibb.istanbul | 9.48 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q107 | Bana en yakın Spor İstanbul tesisi nerede? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.08 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q108 | Spor tesisi üyelik ücretleri ne kadar? | E | spor.istanbul/paket-uyelikleri | 11.40 | 0.50 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q109 | Kadınlara 1 TL spor hizmeti nasıl kullanılır? | E | spor.istanbul/paket-uyelikleri | 11.54 | 0.33 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q110 | Emeklilere 1 TL spor hizmeti nasıl kullanılır? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.89 | 0.50 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| Q111 | Öğrenci spor indirimi nasıl uygulanır? | E | spor.istanbul/tesislerimiz/uyelik-bilgileri | 11.04 | 0.25 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q112 | İBB Spor Okulları’na çocuk kaydı nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 18.32 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q113 | İBB etkinlik biletini nereden alırım? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 6.13 | 0.25 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q114 | Ücretsiz konser ve etkinliklere nasıl kayıt olurum? | E | istanbulsenin.istanbul | 22.60 | 0.60 | hayır | weak/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q115 | İBB kütüphanelerine nasıl üye olurum? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Kutuphanelerimiz/IBB-Suat-Dervis-Kutuphanesi/59 | 10.57 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q116 | Evime en yakın afet toplanma alanı nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 14.96 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q117 | Mahallemin deprem riskini nereden görebilirim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.98 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q118 | Binamın hızlı tarama/bina analizi sonucu var mı? |  | binatespiti.ibb.istanbul/sikcasorulansorular | 19.14 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q119 | Deprem sonrası geçici barınma alanları nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 20.47 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q120 | Afet anında İBB’den hangi kanallardan bilgi almalıyım? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 11.81 | 0.29 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q121 | Yangın için hangi numarayı aramalıyım? |  | itfaiye.ibb.gov.tr/tr/sik-sorulan-sorular.html | 11.28 | 0.67 | hayır | weak/unknown | weak/unknown | redirect / · |
| Q122 | İtfaiyeden yangın güvenliği eğitimi alınabilir mi? |  | itfaiye.ibb.gov.tr/tr/egitim.html | 15.78 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | redirect / · |
| Q123 | İş yeri için itfaiye raporu nasıl alınır? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 16.82 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q124 | İtfaiye olay raporuna nasıl ulaşırım? |  | itfaiye.ibb.gov.tr | 14.15 | 0.50 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q125 | Sel ve su baskını ihbarını nereye yapmalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 16.02 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q126 | Seyyar satıcı veya işgal şikâyetini nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.27 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q127 | Gürültü şikâyetini nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.99 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q128 | Çöp veya çevre kirliliği şikâyetini nereye yaparım? |  | finansman.ibb.istanbul/wp-content/uploads/2025/12/2026PERFORMANSPROGRAMI-1.pdf | 11.09 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q129 | Kaçak döküm veya moloz ihbarını nereye yaparım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.49 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q130 | Sokak hayvanı için acil yardım nereye bildirilir? |  | itfaiye.ibb.gov.tr/tr/ambulans-hizmetleri.html | 12.31 | 0.40 | hayır | weak/unknown | weak/unknown | redirect / · |
| Q131 | Bozuk yol veya kaldırım için nereye başvururum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.12 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q132 | Yol çalışmasının ne zaman biteceğini nereden öğrenirim? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.09 | 0.20 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q133 | Taksi şoförü/araç hakkında nasıl şikâyet oluştururum? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 15.25 | 0.40 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q134 | Taksi ücret uyuşmazlığını nereye bildiririm? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.40 | 0.25 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q135 | Okul servisi için azami ücret ne kadar? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | 19.78 | 0.50 | evet | weak/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q136 | Okul servis ücretini rota üzerinden nasıl hesaplarım? | E | application2.ibb.gov.tr/tulasim/ucrethesaplama.aspx | 20.94 | 0.33 | evet | weak/quote_only | weak/unknown | refused / refusal |
| Q137 | Cenaze olduğunda ilk kimi aramalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.35 | 0.25 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q138 | İBB cenaze nakil hizmeti nasıl alınır? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 18.40 | 0.60 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| Q139 | Mezarlık yeri tahsisi nasıl yapılır? |  | ibb.istanbul | 12.18 | 0.00 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q140 | Mezar yeri ücretleri ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.51 | 0.00 | hayır | weak/quote_only | out_of_scope/unknown | refused / refusal |
| Q141 | Mezar yeri sorgulaması yapılabilir mi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.51 | 0.00 | hayır | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| Q142 | Şehir dışına cenaze nakli nasıl yapılır? |  | ibb.istanbul | 18.70 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q143 | Defin ruhsatı için hangi belgeler gerekir? |  | imarmudurlugu.ibb.istanbul/dokumanlar | 15.77 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q144 | İBB’de nikâh işlemleri için nereye başvurulur? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Hakkinda/Kutuphane-Yonergesi/104 | 6.54 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| Q145 | Nikâh için hangi belgeler gerekir? |  | imarmudurlugu.ibb.istanbul/dokumanlar | 8.77 | 0.33 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q146 | En yakın Halk Ekmek büfesi nerede? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.47 | 0.50 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| Q147 | Halk Ekmek ürün fiyatları ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 19.48 | 0.50 | hayır | weak/quote_only | sufficient/quote_only | quote_only / knowledge |
| Q148 | Halk Ekmek büfesi açmak için nasıl başvurulur? |  | ihe.istanbul | 13.83 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q149 | En yakın Kent Lokantası nerede? |  | ibb.istanbul | 12.31 | 0.67 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| Q150 | Kent Lokantası menüsü ve ücreti ne kadar? | E | ibb.istanbul | 12.31 | 0.50 | evet | weak/quote_only | weak/unknown | refused / refusal |
| h-01 | Gece metrosu hangi günler çalışıyor? |  | metro.istanbul/icerik/Gece-Metrosu | 17.22 | 0.50 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| h-02 | Gece otobüsleri hangi hatlarda çalışıyor? |  | metro.istanbul/icerik/Gece-Metrosu | 13.22 | 0.25 | evet | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| h-03 | Gece metrosu seferleri saat kaçta başlıyor? |  | metro.istanbul/icerik/Gece-Metrosu | 26.86 | 0.50 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| h-04 | Hızlı bina taraması nedir? |  | binatespiti.ibb.istanbul/projebilgisi | 10.70 | 0.67 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-05 | Hızlı tarama raporu ne zaman çıkar? |  | binatespiti.ibb.istanbul/projebilgisi | 12.90 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-06 | Hızlı taramada neden karot alınmıyor? |  | binatespiti.ibb.istanbul/sikcasorulansorular | 13.33 | 0.25 | evet | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| h-07 | 153 Çözüm Merkezi'ne nasıl ulaşırım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.23 | 0.75 | hayır | weak/unknown | weak/unknown | unknown / knowledge |
| h-08 | Metroda yolcu hakları nelerdir? | E | metro.istanbul/icerik/yolcu_haklari_bildirgesi | 11.07 | 0.50 | evet | weak/quote_only | weak/unknown | refused / refusal |
| h-09 | İETT yolcu hakları bildirgesinde ne yazıyor? | E | iett.istanbul/passengerapplication | 13.22 | 0.40 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| h-10 | İETT'ye şikâyet başvurusu nasıl yapılır? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 15.69 | 0.25 | hayır | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| h-11 | Metro İstanbul'a şikâyet ya da öneri nasıl iletilir? |  | metro.istanbul/icerik/sikayet_yonetim_sistemi | 16.18 | 0.67 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| h-12 | İstanbul Senin uygulamasından şikâyet oluşturabilir miyim? |  | istanbulsenin.istanbul/sikca-sorulan-sorular | 35.34 | 0.83 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| h-13 | İstanbul Senin uygulamasına nasıl giriş yapılır? |  | istanbulsenin.istanbul | 21.58 | 0.75 | hayır | weak/unknown | sufficient/answer | answer / knowledge |
| h-14 | Metro istasyonlarında erişilebilirlik hizmetleri neler? |  | metro.istanbul/icerik/erişilebilirlik-hizmetleri | 16.73 | 0.40 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| h-15 | İBB Açık Veri Portalı'ndan veri isteği nasıl yapılır? |  | data.ibb.gov.tr/datarequest | 26.03 | 0.67 | evet | weak/unknown | sufficient/answer | answer / knowledge |
| h-16 | İSPARK otopark ücretleri ne kadar? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 13.50 | 0.67 | hayır | weak/quote_only | weak/unknown | refused / refusal |
| h-17 | 500T otobüsü Kadıköy'e ne zaman gelir? |  | data.ibb.gov.tr/license | 10.68 | 0.17 | · | out_of_scope/unknown | out_of_scope/unknown | answer / iett_next_arrivals |
| h-18 | M2 metro hattında arıza var mı? |  | metro.istanbul/Home/SikcaSorulanSorular | 13.62 | 0.75 | · | weak/unknown | weak/unknown | answer / metro_status |
| h-19 | Kartal metro istasyonunda asansör var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 12.84 | 0.50 | · | weak/unknown | weak/unknown | answer / metro_equipment_status |
| h-20 | Kadıköy'de boş otopark var mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.40 | 0.67 | · | weak/unknown | weak/unknown | answer / ispark_find_parking |
| d-01 | Öğrenci kartı vizesi nasıl yapılır? |  | istanbulkart.istanbul/duyurular/detay?id=2768 | 15.60 | 0.33 | evet | weak/unknown | weak/unknown | unknown / knowledge |
| d-02 | İSKİ su kesintisi nereden öğrenilir? |  | data.ibb.gov.tr/dataset/iski-ilce-ve-mahalle-bazli-gelen-ve-cevaplanan-su-ariza-sayisi | 13.04 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| d-03 | Doğalgaz açma randevusu nasıl alınır? |  | imarmudurlugu.ibb.istanbul/sikcasorulansorular | 13.17 | 0.25 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| d-04 | insanla görüşmek istiyorum |  | metro.istanbul/Home/SikcaSorulanSorular | 8.24 | 0.33 | · | weak/unknown | weak/unknown | handoff / layer:handoff |
| d-05 | gaz kaçağı var |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.42 | 0.50 | · | weak/unknown | weak/unknown | redirect / · |
| d-06 | Doğalgaz kaçağı var galiba, koku geliyor |  | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | 8.21 | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | redirect / · |
| n-01 | yarın hava nasıl |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.80 | 0.50 | · | weak/unknown | weak/unknown | answer / · |
| n-02 | en iyi kebapçı nerede |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 5.77 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-03 | Galatasaray maçı kaçta başlıyor? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.31 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-04 | Bana kısa bir şiir yazar mısın? |  | kultur.istanbul | 7.83 | 0.20 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-05 | Python'da bir liste nasıl sıralanır? |  | ataturkkitapligi.ibb.gov.tr/tr/Kitaplik/Kutuphanelerimiz | 10.50 | 0.33 | · | out_of_scope/unknown | weak/unknown | unknown / knowledge |
| n-06 | Bu akşam hangi dizi izlenir? |  | itfaiye.ibb.gov.tr/tr/egitim.html | 9.34 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-07 | Tatilde nereye gitsem? |  | · | · | 0.00 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-08 | Kedim yemek yemiyor, ne yapmalıyım? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.43 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-09 | Yarın okullar tatil mi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 10.06 | 0.00 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| n-10 | En güzel börek tarifi nedir? |  | cevre.ibb.istanbul/cevre-koruma-sube-mudurlugu/avrupa-yakasi-cevre-laboratuvari | 10.65 | 0.33 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-11 | Ehliyet sınavı ne zaman yapılıyor? |  | metro.istanbul/Home/SikcaSorulanSorular | 7.46 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-12 | Pasaport başvurusu nasıl yapılır? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 13.36 | 0.00 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| n-13 | Askerlik yoklaması nereden yapılır? |  | ibb.istanbul | 6.27 | 0.00 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| n-14 | Elektrik faturası neden bu kadar yüksek geldi? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 8.45 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-15 | Doğalgaz faturası nereden ödenir? |  | uploads.ibb.istanbul/uploads/Park_Bahce_ve_Yesil_Alanlar_DB_Kamu_Hizmet_Envanteri_132c7c7419.pdf | 8.21 | 0.00 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| n-16 | Doğalgaz aboneliği nasıl yapılır? |  | ibb.istanbul | 12.18 | 0.00 | · | weak/unknown | out_of_scope/unknown | unknown / knowledge |
| n-17 | Dolar bugün kaç TL? | E | data.ibb.gov.tr/datarequest | 8.42 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
| n-18 | Ev kirası bu yıl ne kadar artar? |  | spor.istanbul/tesislerimiz/uyelik-bilgileri | 7.46 | 0.25 | · | out_of_scope/unknown | out_of_scope/unknown | unknown / knowledge |
| n-19 | Baş ağrısına hangi ilaç iyi gelir? | E | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 9.54 | 0.40 | · | weak/quote_only | weak/unknown | refused / refusal |
| n-20 | Kredi kartı borcumu nasıl yapılandırırım? |  | itfaiye.ibb.gov.tr/tr/yangin-onlem-itfaiye-raporu-islemleri.html | 13.06 | 0.50 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-21 | Yapay zekâ işimi elimden alır mı? |  | uploads.ibb.istanbul/uploads/2025_Faaliyet_Raporu_68f4b037e0.pdf | 11.58 | 0.40 | · | weak/unknown | weak/unknown | unknown / knowledge |
| n-22 | Ankara'ya en ucuz uçak bileti hangi gün? | E | iett.istanbul/icerik/yuksek-hizli-trene-ulasim | 6.19 | 0.20 | · | out_of_scope/unknown | out_of_scope/unknown | refused / refusal |
