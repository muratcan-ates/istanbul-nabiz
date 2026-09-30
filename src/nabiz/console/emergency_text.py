"""The emergency card's fixed text in every card language: the one source, with no model behind it.

The page speaks Turkish and English (DECISIONS #35); only the emergency card speaks the languages of
the visitors İstanbul receives most (DECISIONS #40). ``static/js/emergency_text.js`` is a copy of these
values, held equal by ``tests/test_emergency_multilingual.py``: change both or the test fails.

Every translation except Turkish and English is the project's own and unchecked by a native reader, so
the card shows :data:`UNVERIFIED_LABEL` beside it. The Turkish block (:data:`TR_BLOCK`) is on every card:
the person can show it to anyone nearby. The card names one number, İBB's 153 (owner's decision, 30 Sep
2026): Nabız cannot help in an emergency and sends no one to an emergency line. The Turkish and English
text is :data:`nabiz.agent.templates_i18n.FIXED` ``["EMERGENCY"]``.
"""

from __future__ import annotations

from nabiz.agent.templates_i18n import FIXED

#: Languages whose text a native reader has checked: no "unverified" label.
REVIEWED_LANGS = ("tr", "en")
#: Right-to-left card languages: the card (not the page) gets ``dir="rtl"``.
RTL_LANGS = ("ar", "fa")
UNVERIFIED_LABEL = "otomatik çeviri · doğrulanmadı"
#: The large Turkish block under every card: the Turkish text in capitals.
TR_BLOCK = {"plea": "NABIZ ACİL DURUMLARDA YARDIMCI OLAMAZ. İBB'YE 153'TEN ULAŞABİLİRSİNİZ."}

CARD_TEXT: dict[str, dict[str, str]] = {
    "tr": {
        "title": "Nabız acil durumlarda yardımcı olamaz",
        "show": "Bu ekranı yanınızdaki birine gösterin.",
        "note": "Sohbeti durdurdum. İBB'ye 153'ten ulaşabilirsiniz.",
        "live": FIXED["EMERGENCY"]["tr"],
        "call": "153'ü ara",
        "locate": "Konumumu göster",
        "copy": "Kopyala",
        "grow": "Türkçe yazıyı büyüt",
        "back": "Acil değil, geri dön",
        "foot": "Resmî İBB hizmeti değildir. Nabız bağımsız bir projedir. Konumunuz yalnız bu cihazda kalır.",
        "waiting": "Konum alınıyor.",
        "shown": "Konumunuz: {coords}.",
        "copied": "Panoya kopyalandı: {coords}.",
        "copyfail": "Kopyalanamadı. Sayıları ekrandan okuyun: {coords}.",
        "denied": "Konum alınamadı.",
    },
    "en": {
        "title": "Nabız cannot help in an emergency",
        "show": "Show this screen to someone near you.",
        "note": "I stopped the chat. You can reach İBB on 153.",
        "live": FIXED["EMERGENCY"]["en"],
        "call": "Call 153",
        "locate": "Show my location",
        "copy": "Copy",
        "grow": "Show the Turkish text larger",
        "back": "Not an emergency, go back",
        "foot": "Not an official İBB service. Nabız is an independent project. Your location stays on this device only.",
        "waiting": "Getting your location.",
        "shown": "Your location: {coords}.",
        "copied": "Copied to the clipboard: {coords}.",
        "copyfail": "Could not copy. Read the numbers from the screen: {coords}.",
        "denied": "Could not get your location.",
    },
    "ar": {
        "title": "لا يستطيع Nabız المساعدة في حالات الطوارئ",
        "show": "أظهر هذه الشاشة لشخص قريب منك.",
        "note": "أوقفت المحادثة. يمكنك التواصل مع İBB على الرقم 153.",
        "live": "لا يستطيع Nabız المساعدة في حالات الطوارئ. يمكنك التواصل مع İBB على الرقم 153.",
        "call": "اتصل بالرقم 153",
        "locate": "أظهر موقعي",
        "copy": "نسخ",
        "grow": "كبّر النص التركي",
        "back": "ليست حالة طارئة، رجوع",
        "foot": "ليست خدمة رسمية من İBB. Nabız مشروع مستقل. يبقى موقعك على هذا الجهاز فقط.",
        "waiting": "جار تحديد موقعك.",
        "shown": "موقعك: {coords}.",
        "copied": "تم النسخ: {coords}.",
        "copyfail": "تعذر النسخ. اقرأ الأرقام من الشاشة: {coords}.",
        "denied": "تعذر تحديد الموقع.",
    },
    "ru": {
        "title": "Nabız не может помочь в экстренной ситуации",
        "show": "Покажите этот экран человеку рядом.",
        "note": "Чат остановлен. Вы можете связаться с İBB по номеру 153.",
        "live": "Nabız не может помочь в экстренной ситуации. Вы можете связаться с İBB по номеру 153.",
        "call": "Позвонить 153",
        "locate": "Показать моё местоположение",
        "copy": "Копировать",
        "grow": "Увеличить текст на турецком",
        "back": "Не экстренно, назад",
        "foot": "Это не официальная служба İBB. Nabız является независимым проектом. "
        "Ваше местоположение остаётся только на этом устройстве.",
        "waiting": "Определяем местоположение.",
        "shown": "Ваше местоположение: {coords}.",
        "copied": "Скопировано: {coords}.",
        "copyfail": "Не удалось скопировать. Прочитайте цифры с экрана: {coords}.",
        "denied": "Не удалось определить местоположение.",
    },
    "de": {
        "title": "Nabız kann in einem Notfall nicht helfen",
        "show": "Zeigen Sie diesen Bildschirm einer Person in Ihrer Nähe.",
        "note": "Der Chat ist gestoppt. Sie erreichen die İBB unter 153.",
        "live": "Nabız kann in einem Notfall nicht helfen. Sie erreichen die İBB unter 153.",
        "call": "153 anrufen",
        "locate": "Meinen Standort zeigen",
        "copy": "Kopieren",
        "grow": "Türkischen Text groß zeigen",
        "back": "Kein Notfall, zurück",
        "foot": "Kein offizieller Dienst der İBB. Nabız ist ein unabhängiges Projekt. Ihr Standort bleibt nur auf diesem Gerät.",
        "waiting": "Standort wird ermittelt.",
        "shown": "Ihr Standort: {coords}.",
        "copied": "In die Zwischenablage kopiert: {coords}.",
        "copyfail": "Kopieren nicht möglich. Lesen Sie die Zahlen vom Bildschirm ab: {coords}.",
        "denied": "Standort nicht verfügbar.",
    },
    "fa": {
        "title": "Nabız در شرایط اضطراری نمی‌تواند کمک کند",
        "show": "این صفحه را به یک نفر در نزدیکی خود نشان دهید.",
        "note": "گفتگو را متوقف کردم. می‌توانید با شماره 153 با İBB تماس بگیرید.",
        "live": "Nabız در شرایط اضطراری نمی‌تواند کمک کند. می‌توانید با شماره 153 با İBB تماس بگیرید.",
        "call": "تماس با 153",
        "locate": "نمایش موقعیت من",
        "copy": "کپی",
        "grow": "بزرگ کردن متن ترکی",
        "back": "اضطراری نیست، بازگشت",
        "foot": "این خدمت رسمی İBB نیست. Nabız یک پروژه مستقل است. موقعیت شما فقط روی همین دستگاه می‌ماند.",
        "waiting": "در حال یافتن موقعیت شما.",
        "shown": "موقعیت شما: {coords}.",
        "copied": "کپی شد: {coords}.",
        "copyfail": "کپی نشد. اعداد را از روی صفحه بخوانید: {coords}.",
        "denied": "موقعیت پیدا نشد.",
    },
    "es": {
        "title": "Nabız no puede ayudar en una emergencia",
        "show": "Muestre esta pantalla a alguien cerca de usted.",
        "note": "He detenido el chat. Puede comunicarse con İBB en el 153.",
        "live": "Nabız no puede ayudar en una emergencia. Puede comunicarse con İBB en el 153.",
        "call": "Llamar al 153",
        "locate": "Mostrar mi ubicación",
        "copy": "Copiar",
        "grow": "Ampliar el texto en turco",
        "back": "No es una emergencia, volver",
        "foot": "No es un servicio oficial de İBB. Nabız es un proyecto independiente. "
        "Su ubicación se queda en este dispositivo.",
        "waiting": "Obteniendo su ubicación.",
        "shown": "Su ubicación: {coords}.",
        "copied": "Copiado: {coords}.",
        "copyfail": "No se pudo copiar. Lea los números en la pantalla: {coords}.",
        "denied": "No se pudo obtener la ubicación.",
    },
    "fr": {
        "title": "Nabız ne peut pas aider en cas d'urgence",
        "show": "Montrez cet écran à une personne près de vous.",
        "note": "J'ai arrêté la conversation. Vous pouvez joindre l'İBB au 153.",
        "live": "Nabız ne peut pas aider en cas d'urgence. Vous pouvez joindre l'İBB au 153.",
        "call": "Appeler le 153",
        "locate": "Afficher ma position",
        "copy": "Copier",
        "grow": "Agrandir le texte turc",
        "back": "Pas une urgence, retour",
        "foot": "Service non officiel de l'İBB. Nabız est un projet indépendant. Votre position reste sur cet appareil.",
        "waiting": "Recherche de votre position.",
        "shown": "Votre position : {coords}.",
        "copied": "Copié : {coords}.",
        "copyfail": "Copie impossible. Lisez les chiffres à l'écran : {coords}.",
        "denied": "Position introuvable.",
    },
    "it": {
        "title": "Nabız non può aiutare in caso di emergenza",
        "show": "Mostri questo schermo a una persona vicina.",
        "note": "Ho fermato la chat. Può contattare İBB al 153.",
        "live": "Nabız non può aiutare in caso di emergenza. Può contattare İBB al 153.",
        "call": "Chiama il 153",
        "locate": "Mostra la mia posizione",
        "copy": "Copia",
        "grow": "Ingrandisci il testo turco",
        "back": "Non è un'emergenza, torna indietro",
        "foot": "Non è un servizio ufficiale İBB. Nabız è un progetto indipendente. "
        "La sua posizione resta su questo dispositivo.",
        "waiting": "Ricerca della posizione.",
        "shown": "La sua posizione: {coords}.",
        "copied": "Copiato: {coords}.",
        "copyfail": "Impossibile copiare. Legga i numeri sullo schermo: {coords}.",
        "denied": "Posizione non disponibile.",
    },
    "uk": {
        "title": "Nabız не може допомогти в екстреній ситуації",
        "show": "Покажіть цей екран людині поруч.",
        "note": "Чат зупинено. Ви можете зв'язатися з İBB за номером 153.",
        "live": "Nabız не може допомогти в екстреній ситуації. Ви можете зв'язатися з İBB за номером 153.",
        "call": "Зателефонувати 153",
        "locate": "Показати моє місцезнаходження",
        "copy": "Копіювати",
        "grow": "Збільшити текст турецькою",
        "back": "Не екстрено, назад",
        "foot": "Це не офіційна служба İBB. Nabız є незалежним проєктом. "
        "Ваше місцезнаходження залишається лише на цьому пристрої.",
        "waiting": "Визначаємо місцезнаходження.",
        "shown": "Ваше місцезнаходження: {coords}.",
        "copied": "Скопійовано: {coords}.",
        "copyfail": "Не вдалося скопіювати. Прочитайте цифри з екрана: {coords}.",
        "denied": "Не вдалося визначити місцезнаходження.",
    },
}
#: The card languages, Turkish first; any other code falls back to Turkish on the page.
CARD_LANGS = tuple(CARD_TEXT)
