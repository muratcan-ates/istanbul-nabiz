# Bu tarayıcıdaki sohbet ve hafıza sözleşmesi

Sohbet geçmişi, kişinin onayladığı hafıza ve plan ya da işlem kayıtları ayrı yaşar. Bir sohbetin metni yeni sohbete taşınmaz. Hafıza kaydı sohbet geçmişine eklenmez. Takvim, bildirim, talep ve takip kayıtları kendi sahiplerinde kalır; sohbet onlara yalnız kimlikle bağlanır.

## Sohbet deposu

`conversations.js` IndexedDB `nabiz-conversations` sürüm 1 kullanır. Kullanılamazsa `nabiz.conversations.v1` localStorage, o da kullanılamazsa yalnız sekme belleği kullanılır. Kayıt biçimi `schema: 2`, `id`, `title`, `createdAt`, `updatedAt`, `turns`, `scoped`, `links`, `full`, `continued_from` alanlarını taşır. Eski kayıtlar okunurken eksik alanlara varsayılan verilir. Sohbet son kullanımdan 30 gün sonra silinir. 80 tur dolunca eski mesajlar saklanır; sonraki tur yeni sohbet kaydına `continued_from` bağıyla yazılır.

Tur biçimi `{role, content, at, mode?, message_id?, redacted?, cards?}`. Acil içerik `[acil yönlendirme]`, diğer hassas içerik `[hassas bilgi saklanmadı]` olarak saklanır. Maskeli soru sohbet başlığı olmaz. Kartlar en çok altı adettir ve `ChatCard` v1 alanlarıyla sınırlanır. `sensitive: true` kartın eylemleri boşaltılır. Kartın `conversation_id` alanı saklanırken doldurulur. Açılan sohbetin tüm turları ekranda gösterilir; modele giden `history` ayrı olarak son `HISTORY_TURNS * 2` turla sınırlanır.

`SOZLESME-sohbet-karti-v0.md` v0.1 kartları `linked: {event_id, report_code, operation_id}` ve `actions: [{id, label, kind, requires_consent, operation_id}]` biçiminde saklanır. Kapalı eylem listesindeki takma adlar kanonik ada çevrilir; eylemin `kind`, `requires_consent`, `operation_id` alanları saklama ve yeniden açmada korunur. Eski dize eylemler okunurken nesneye çevrilir. Hassas kart yeniden açıldığında eylemsizdir.

`links` öğeleri `{kind: 'calendar'|'report'|'operation', id}` biçimindedir ve kartın `linked.event_id`, `linked.report_code`, `linked.operation_id` alanlarından türetilir. Sohbet silindiğinde bu kayıtlar silinmez. Sohbet kapsamlı `scoped` hafıza ise sohbetle birlikte silinir.

## Hafıza kaydı

```text
MemoryRecord { id, type: 'interest'|'place'|'need'|'health', label, key|null,
  scope: 'profile'|'conversation', conversation_id|null,
  source: 'chat_suggestion'|'user_typed'|'profile_form'|'migrated_v1',
  consent_at, updated_at, reviewed_at|null, sensitive: bool, need_key|null, related_ids: [],
  owner: 'browser' }
```

`owner` bu sürümde sabit `'browser'` değeridir: kayıt yalnız bu tarayıcıda yaşar, hesaba bağlı değildir. Eksik olan eski kayıtlar okunurken `'browser'` alır; hesaba bağlı hafıza (P02b) `'account:<id>'` ekleyecektir.

Profil kapsamı `nabiz.memory.v2` içinde; sohbet kapsamı ilgili sohbetin `scoped` dizisindedir. Profildeki onaylı ihtiyaçlar `nabiz.profile.v1` içinde ayrı durur. `need.key` yalnız `step_free`, `stroller`, `slow_walk`, `low_vision`, `hearing`, `plain_language`, `answer_en` olabilir. `interest.key` yalnız `culture`, `museum`, `theatre`, `concert`, `cinema`, `library`, `sport`, `nature`, `children`, `course` olabilir. `place.key` `station:<ad>`, `line:<kod>` ya da serbest etiket için `null` olur. `health.key` daima `null`, `health.sensitive` daima `true` olur.

```json
[
  {"id":"mem-1","type":"need","label":"Uzun yürümek istemiyorum","key":"slow_walk","scope":"profile","conversation_id":null,"source":"chat_suggestion","consent_at":"2026-09-27T14:05:00+03:00","updated_at":"2026-09-27T14:05:00+03:00","reviewed_at":null,"sensitive":false,"need_key":null,"related_ids":["<sohbet id>"],"owner":"browser"},
  {"id":"mem-2","type":"health","label":"Diz ameliyatı sonrası dönemdeyim (örnek)","key":null,"scope":"conversation","conversation_id":"<sohbet id>","source":"user_typed","consent_at":"2026-09-27T14:07:00+03:00","updated_at":"2026-09-27T14:07:00+03:00","reviewed_at":null,"sensitive":true,"need_key":"slow_walk","related_ids":[],"owner":"browser"}
]
```

İkinci kayıt yalnız örnek sohbette yaşar. `add` çağrısındaki `explicit_health_consent: true` açık onay girdisidir, saklanan kaydın alanı değildir. O sohbet açıkken `requestNeeds` yalnız `slow_walk` anahtarını verebilir; beyan metnini vermez. Sohbet silinince kayıt da silinir. Bu örnekler sentetiktir.

## `createMemoryStore({storage, now, conversations})`

Depolama ve saat testte enjekte edilir; `conversations` isteğe bağlı depo uyarlayıcısıdır. `list({type, scope, conversationId})`, `add(record)`, `update(id, patch)`, `forget(id)`, `forgetAll()` asenkron; `isForgotten(type, key)`, `requestNeeds({profile, conversation})`, `shareable(purpose)`, `migrateV1()` senkrondur. `profile.js` eski dışa aktarımlarını ve v1 dönüş biçimini korur. `nabiz.memory.v1` ilk okumada bir kez v2'ye taşınır, başarılı yazımdan sonra eski anahtar silinir.

`requestNeeds` yalnız onaylı profil ihtiyaçlarını, profil kapsamlı `need` kayıtlarını, aktif sohbetin `scoped` `need` kayıtlarını ve kapsamı uygun sağlık kaydının ayrıca seçilen `need_key` alanını birleştirir. Çıktı yalnız kapalı ihtiyaç anahtarlarından ve en çok 16 öğeden oluşur. Profil kapsamı için profil onayı gerekir; sohbet kapsamlı onay yalnız o sohbet için geçerlidir. `shareable('model')` aynı anahtarları verir. `shareable('operator'|'calendar'|'outlook')` bugün boş dizi verir. Ham sağlık beyanı, ilgi ya da serbest yer metni bir isteğe girmez.

`forget` yalnız hedef kaydı siler ve anahtarını `nabiz.memory.forgotten.v1` içinde 30 gün işaretler. Profilim'de aynı ihtiyaç ya da yer seçimi duruyorsa sonuç bunu söyler ve ayrı "Profilimden de kaldır" seçeneği sunar. Eski sohbeti açmak, eski kartı çizmek, sunucu önerisi veya istemci önerisi bu tercihi otomatik geri getiremez. Kişi Hafızam'dan yeniden elle ekleyebilir.

## Silme sınırları

- **Sohbeti sil:** Mesajlar, kartlar ve o sohbette tutulan hafıza silinir. Ayrı duran profil hafızası yalnız kişinin işaretsiz “Bunları da unut” kutusunu seçmesiyle unutulur. Bağlı takvim ve bildirim kayıtları kendi bölümünde kalır.
- **Unut:** Tek hafıza kaydı silinir. Eski sohbet metni ve plan kayıtları kalır.
- **Tüm Nabız verimi sil:** Listelenen tarayıcı anahtarları, sohbet deposu ve önbellekteki şehir kartları silinir; görünüm ve dil tercihleri ayrı, işaretsiz seçimdir. Örnek hesap bağlıysa mevcut hesap silme yolu önce sunucudaki hesabı ve ona bağlı kayıtları kaldırır. Bu işlem başarısız olursa oturum anahtarları yeniden denemek için kalır ve sonuç başarısız görünür. Önceden indirilen takvim dosyaları ve Outlook'a eklenen kayıtlar bu işlemle silinemez.

Hafıza önerisi başlangıçta yalnız bu sohbet kapsamındadır. Hiçbir kutu önceden seçili değildir. Aynı sohbette aynı beyanın ikinci kez söylenmesi öneri eşiğidir; sayaç sohbet geçmişine yazılmaz. Sağlık beyanı yalnız Hafızam'dan ayrı açık onayla eklenir; sohbetten gelen hassas kart yalnız Hafızam sağlık formunu açar.

## Sonraki paket: P02b / P13 kabul koşulları

Hesaba bağlı hafıza P02b'dir (P13 oturumu birleştikten sonra, D2). Aşağıdaki her cümle P02b/P13'ün kabul testidir; P02 yalnız belgeye yazar ve kayıt biçimini (`owner`, kararlı `id`, `nabiz.memory.forgotten.v1`) bunlara hazır tutar.
1. **Hesap ayrımı:** A hesabıyla kaydedilen `owner: 'account:A'` hafıza kaydı, aynı tarayıcıda B hesabıyla girilince Hafızam'da, `requestNeeds`'te ve sunucu yanıtında görünmez; B'nin oturumuyla A'nın kaydına yapılan her okuma/yazma/silme isteği P13 `ownership` denetiminde reddedilir (uç başına ret testi).
2. **Hesap değiştirince yerel hafıza:** A'dan çıkıp B'ye girince A'nın hesap kayıtlarının tarayıcıdaki önbelleği silinmiş olur (depoda `account:A` kaydı sayısı 0); `owner: 'browser'` kayıtlar hiçbir hesaba kendiliğinden geçmez, "Bu tarayıcıda" etiketiyle ayrı grupta durur ve B'nin hesap hafızasına yazılmaz.
3. **Misafirden hesaba taşıma yalnız açık izinle:** girişten sonra önizleme penceresi "Bu tarayıcıdaki N hafıza kaydını hesabınıza taşıyalım mı?" her kaydı değeri, türü ve kapsamıyla listeler; kutular işaretsizdir, hiçbir kayıt işaretlenmeden taşınmaz; `health` kayıtları ayrı açık onay olmadan taşınmaz; reddedilen ya da işaretlenmeyen kayıt tarayıcıda kalır; taşınan kaydın tarayıcı kopyası silinir ve sonuç cümlesi hangi kaydın taşındığını, hangisinin kaldığını söyler. Otomatik taşıma yok (test: girişten sonra onaysız bekleyişte hesap kaydı sayısı 0).
4. **Taşıma geri alınabilir:** sonuç satırındaki "Taşımayı geri al" aynı taşımanın (tek `operation_id`) hesap kopyalarını siler ve tarayıcı kopyalarını ilk hâlleriyle (`id`, kapsam, tarih) geri yazar; iki kez basmak ikinci kez işlem yapmaz (idempotent).
5. **Unutulanlar da taşınır:** taşıma `forgotten` listesini hesaba geçirir; taşıma unutulmuş bir tercihi geri getirmez ve 30 gün sayacı sıfırlanmaz.
6. **Paylaşılan cihazda çıkış:** "Çıkış yap" sonrası bu tarayıcıda hesap hafızası, hesap sohbet kayıtları ve oturum belirteci okunamaz (depo taraması boş); çıkış ekranı tek cümleyle "Bu tarayıcıdaki hafıza (N kayıt) bu tarayıcıda kaldı" der ve yanında işaretsiz "Bu tarayıcıdaki hafızayı da sil" seçeneği sunar.
7. **Silme zinciri:** hesap silme (`DELETE /api/account`, P13 `erasure`) hesap hafızasını, hesaba taşınmış `forgotten` listesini ve hesaba bağlı sohbet kayıtlarını siler; sonra aynı uç 404/boş döner; tarayıcıdaki `owner: 'browser'` kayıtlar ayrı kalır ve sonuç bunu söyler. "Tüm Nabız verimi sil" hesap hafızasını ayrı, sayılı bir grupta gösterir; takvim/bildirim gibi plan kayıtları kendi sahiplerinin silme kuralıyla gider ve kalanlar listelenir.
8. **Arayüz dili:** tarayıcıdaki kayıt "Bu tarayıcıda", hesaptaki kayıt "Hesabınızda" etiketiyle; "her yerden silindi" hiçbir yerde geçmez.
