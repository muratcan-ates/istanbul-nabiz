# Cihazdaki sohbet ve hafıza sözleşmesi

Sohbet geçmişi, kişinin onayladığı hafıza ve plan ya da işlem kayıtları ayrı yaşar. Bir sohbetin metni yeni sohbete taşınmaz. Hafıza kaydı sohbet geçmişine eklenmez. Takvim, bildirim, talep ve takip kayıtları kendi sahiplerinde kalır; sohbet onlara yalnız kimlikle bağlanır.

## Sohbet deposu

`conversations.js` IndexedDB `nabiz-conversations` sürüm 1 kullanır. Kullanılamazsa `nabiz.conversations.v1` localStorage, o da kullanılamazsa yalnız sekme belleği kullanılır. Kayıt biçimi `schema: 2`, `id`, `title`, `createdAt`, `updatedAt`, `turns`, `scoped`, `links`, `trimmed` alanlarını taşır. Eski kayıtlar okunurken eksik alanlara varsayılan verilir. Sohbet oluşturmadan 30 gün sonra silinir; 80 tur sınırında düşen mesaj sayısı `trimmed` ile görünür.

Tur biçimi `{role, content, at, mode?, message_id?, redacted?, cards?}`. Acil içerik `[acil yönlendirme]`, diğer hassas içerik `[hassas bilgi saklanmadı]` olarak saklanır. Maskeli soru sohbet başlığı olmaz. Kartlar en çok altı adettir ve `ChatCard` v1 alanlarıyla sınırlanır. `sensitive: true` kartın eylemleri boşaltılır. Kartın `conversation_id` alanı saklanırken doldurulur. Açılan sohbetin tüm turları ekranda gösterilir; modele giden `history` ayrı olarak son `HISTORY_TURNS * 2` turla sınırlanır.

`links` öğeleri `{kind: 'calendar'|'report'|'request'|'follow', id}` biçimindedir. Sohbet silindiğinde bu kayıtlar silinmez. Sohbet kapsamlı `scoped` hafıza ise sohbetle birlikte silinir.

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

İkinci kayıt yalnız örnek sohbette yaşar. O sohbet açıkken `requestNeeds` yalnız `slow_walk` anahtarını verebilir; beyan metnini vermez. Sohbet silinince kayıt da silinir. Bu örnekler sentetiktir.

## `createMemoryStore({storage, now, conversations})`

Depolama ve saat testte enjekte edilir; `conversations` isteğe bağlı depo uyarlayıcısıdır. `list({type, scope, conversationId})`, `add(record)`, `update(id, patch)`, `forget(id)`, `forgetAll()` asenkron; `isForgotten(type, key)`, `requestNeeds({profile, conversation})`, `shareable(purpose)`, `migrateV1()` senkrondur. `profile.js` eski dışa aktarımlarını ve v1 dönüş biçimini korur. `nabiz.memory.v1` ilk okumada bir kez v2'ye taşınır, başarılı yazımdan sonra eski anahtar silinir.

`requestNeeds` yalnız onaylı profil ihtiyaçlarını, profil kapsamlı `need` kayıtlarını, aktif sohbetin `scoped` `need` kayıtlarını ve kapsamı uygun sağlık kaydının ayrıca seçilen `need_key` alanını birleştirir. Çıktı yalnız kapalı ihtiyaç anahtarlarından ve en çok 16 öğeden oluşur. Profil kapsamı için profil onayı gerekir; sohbet kapsamlı onay yalnız o sohbet için geçerlidir. `shareable('model')` aynı anahtarları verir. `shareable('operator'|'calendar'|'outlook')` bugün boş dizi verir. Ham sağlık beyanı, ilgi ya da serbest yer metni bir isteğe girmez.

`forget` yalnız hedef kaydı siler ve anahtarını `nabiz.memory.forgotten.v1` içinde 30 gün işaretler. Eski sohbeti açmak, eski kartı çizmek, sunucu önerisi veya istemci önerisi bu tercihi otomatik geri getiremez. Kişi Hafızam'dan yeniden elle ekleyebilir.

## Silme sınırları

- **Sohbeti sil:** Mesajlar, kartlar ve o sohbette tutulan hafıza silinir. Ayrı duran profil hafızası yalnız kişinin işaretsiz “Bunları da unut” kutusunu seçmesiyle unutulur. Bağlı takvim ve bildirim kayıtları kendi bölümünde kalır.
- **Unut:** Tek hafıza kaydı silinir. Eski sohbet metni ve plan kayıtları kalır.
- **Tüm Nabız verimi sil:** Listelenen cihaz anahtarları, sohbet deposu ve önbellekteki şehir kartları silinir; görünüm ve dil tercihleri ayrı, işaretsiz seçimdir. Örnek hesap bağlıysa mevcut hesap silme yolu önce sunucudaki hesabı ve ona bağlı kayıtları kaldırır. Bu işlem başarısız olursa oturum anahtarları yeniden denemek için kalır ve sonuç başarısız görünür. Önceden indirilen takvim dosyaları ve Outlook'a eklenen kayıtlar bu işlemle silinemez.

Hafıza önerisi başlangıçta yalnız bu sohbet kapsamındadır. Hiçbir kutu önceden seçili değildir. Sağlık beyanı yalnız Hafızam'dan kişi tarafından eklenir; kart önerisi sağlık beyanı üretmez.
