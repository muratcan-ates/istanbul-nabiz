# Acil kart: sekiz dille örtüşme ve insan incelemesi

Bu belge acil kartın metinlerini **değiştirmez**. P14 acil metinlere dokunmaz; 10 dilli kart
(DECISIONS #40) aynen kalır. Amaç, sayfa sekiz dile çıkarken kartın hangi dillerinin sayfayla örtüştüğünü ve
bir anadil konuşurunun her dili nasıl inceleyeceğini yazmak.

Kaynak: [`src/nabiz/console/emergency_text.py`](../../src/nabiz/console/emergency_text.py) (73b798c). Sayfadaki
kopyası [`static/js/emergency_text.js`](../../src/nabiz/console/static/js/emergency_text.js); ikisinin eşitliğini
[`tests/test_emergency_multilingual.py`](../../tests/test_emergency_multilingual.py) tutar.

## Bugünkü durum

- Kart dilleri (`CARD_TEXT`, 10): tr, en, ar, ru, de, fa, es, fr, it, uk.
- İncelenmiş diller: `REVIEWED_LANGS = ("tr", "en")`. Diğer sekiz kart dili `UNVERIFIED_LABEL`
  ("otomatik çeviri · doğrulanmadı") etiketiyle görünür.
- Sağdan sola kart dilleri: `RTL_LANGS = ("ar", "fa")`; kart (sayfa değil) `dir="rtl"` alır.
- Her kartın altında Türkçe blok (`TR_BLOCK`): "LÜTFEN YARDIM EDİN · 112'Yİ ARAYIN"; gaz kaçağında
  "GAZ KAÇAĞI · 187" (DECISIONS #36).

## Sayfanın sekiz diliyle örtüşme

| Dil | Kartta | Sayfa hedefinde (P14) | İncelenmiş | Kartta etiket |
|---|---|---|---|---|
| tr | var | var | evet | yok |
| en | var | var | evet | yok |
| de | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| ru | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| ar | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| fa | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| fr | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| es | var | var | hayır | "otomatik çeviri · doğrulanmadı" |
| it | var | yok | hayır | "otomatik çeviri · doğrulanmadı" |
| uk | var | yok | hayır | "otomatik çeviri · doğrulanmadı" |

Sekiz sayfa dilinin sekizi de kartta var. it ve uk yalnız kartta: sayfa bu dillerde açılmaz, kart açılır.
Sayfa kataloglarındaki ([`README.md`](README.md)) 153 adı kartın `line153` karşılıklarıyla aynı çizgide.

## Bir dil incelendiğinde

1. İnceleyen aşağıdaki listeyi o dil için doldurur; düzeltme önerisini anahtar anahtar yazar.
2. Owner düzeltmeyi `emergency_text.py` ve `static/js/emergency_text.js`'e birlikte işler (test eşitliği
   bekler) ve dili `REVIEWED_LANGS`'e iki dosyada birden ekler; etiket o dilde kalkar.
3. İnceleyenin adı ya da takma adı yalnız kendi izniyle, e-posta olmadan yazılır.

## Her dil için ortak kontrol listesi

- [ ] **112 önce.** `title` ilk sözcüklerinde 112'yi arama emrini verir; `live` (ekran okuyucu duyurusu,
  "canlı veri" değil) de 112 der. 153 yalnız `line153`'te ve acil olmadığı yazılı olarak geçer.
- [ ] **"Yardım çağırdım" denmez.** `note` sitenin yardım çağıramadığını ve aramayı kişinin yapacağını söyler.
  Hiçbir satır yardımın çağrıldığını, yolda olduğunu ya da asistanın aradığını ima etmez.
- [ ] **Kısa cümle.** Her satır tek kısa cümle ya da iki kısa cümle; yan cümle yok; panik anında okunur.
  `show` satırını yoldan geçen biri anlar.
- [ ] **Numaralar rakamla.** 112, 153 ve 187 rakam olarak (Batı rakamı) yazılı; sözcükle değil.
- [ ] **187 yalnız gazda.** 187 yalnız `gas` satırında ve İGDAŞ doğal gaz acil hattı olarak geçer.
- [ ] **Yer tutucu.** `shown`, `copied`, `copyfail` satırlarında `{coords}` aynen duruyor.
- [ ] **Resmî değil.** `foot` "Resmî İBB hizmeti değildir" anlamını ve konumun cihazda kaldığını söyler.
- [ ] **Hitap tutarlı.** Kartın bütün satırları aynı hitap kipinde (de "Sie", fr "vous", es "usted",
  ru "Вы", it "Lei", uk "Ви").
- [ ] **Adlar çevrilmemiş.** İBB, İGDAŞ, Nabız olduğu gibi.
- [ ] **Buton metni.** `call`, `locate`, `copy`, `grow`, `back` kısa ve eylem bildiren buton metni.

## Dil başına

Her dil için ortak listeye ek olarak okurken gözüme takılanlar. Bunlar öneri değil, inceleyene soru;
metin değişmedi.

### de · Deutsch
- [ ] ortak liste
- `call` "112 anrufen" mastar; `title` "Rufen Sie sofort 112 an" emir. Buton için mastar olağan mı?

### ru · Русский
- [ ] ortak liste
- `foot` iki parça halinde birleştiriliyor (Python'da satır bölme); ekranda tek cümle akışı doğru mu?

### ar · العربية (RTL)
- [ ] ortak liste
- [ ] RTL: kart sağdan sola okunuyor; `{coords}` ve 112 soldan sağa parça olarak doğru görünüyor; Türkçe blok
  soldan sağa kalıyor.
- `shown` "لموظف 112" (112 görevlisine) diyor; öteki satırlar "بالرقم 112". İkisi de doğal mı?

### fa · فارسی (RTL)
- [ ] ortak liste
- [ ] RTL: ar ile aynı kontrol.
- `note` "کمک خبر کند" deyişi doğal mı, yoksa "درخواست کمک کند" gibi bir ifade mi daha açık?

### fr · Français
- [ ] ortak liste
- `note` iki cümleye bölünmüş ("... les secours. Appelez vous-même."); öteki dillerde noktalı virgül var. Sorun
  değil, yalnız kısa cümle kuralına uygun mu diye bakılmalı.

### es · Español
- [ ] ortak liste
- `note` "llame usted": usted kipi tutarlı.

### it · Italiano (yalnız kart)
- [ ] ortak liste
- `title` "Chiami" (Lei) ama `call` "Chiama il 112" (tu emir kipi). Hitap tutarlılığı maddesine takılıyor.

### uk · Українська (yalnız kart)
- [ ] ortak liste
- `call` "Зателефонувати 112" mastar; `title` "Негайно телефонуйте 112" emir.
