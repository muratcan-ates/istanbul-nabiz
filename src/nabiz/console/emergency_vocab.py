"""Emergency words in the card languages other than Turkish: data only, read by :mod:`emergency_lang`.

Turkish keeps its own, older rules in :mod:`nabiz.console.policy` (DECISIONS #36). Each entry below is
written the way a person types it; :func:`nabiz.console.emergency_lang.fold_for_emergency` folds the
entry and the message the same way (case, accents, Arabic and Persian letter forms), so "brûle", "brule"
and "BRÛLE" are one word. A word ending in ``*`` matches as a prefix; any other word matches whole.

- ``terms``: an emergency on their own ("пожар", "Herzinfarkt", "حريق").
- ``gas``: the same, and the card also shows İGDAŞ's 187 line.
- ``pleas``: "help" words. They count alone ("Hilfe!"), shouted ("ayuda!") or next to a person, a call
  or another emergency word (``company``); "necesito ayuda con el billete" is not an emergency.
- ``gated``: "urgent", "emergency", "earthquake", "fell": only with company or shouted, the same rule
  Turkish has for "acil" and "düştü".
- ``masks``: phrases that take their words out before matching ("fire sale", "Feuerwerk" is already
  another word, "пожарная лестница", "feu rouge", "salida de emergencia").
- ``negations``: words right before a match that cancel it ("no fire", "kein Feuer", "нет пожара").
- ``clitics``: Arabic writes "and", "the", "with" onto the word ("والحريق", "بالإسعاف").

A missed emergency costs more than a false alarm, so the lists lean wide; the masks and negations are
the narrow part, each one from a question a visitor may really ask.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Vocab:
    terms: tuple[str, ...]
    gas: tuple[str, ...]
    pleas: tuple[str, ...]
    gated: tuple[str, ...]
    company: tuple[str, ...]
    masks: tuple[str, ...] = ()
    negations: tuple[str, ...] = ()
    clitics: bool = False


VOCAB: dict[str, Vocab] = {
    "en": Vocab(
        terms=(
            "fire", "on fire", "is burning", "firefighters", "fire brigade", "ambulance*", "paramedic*", "police",
            "sos", "mayday", "accident", "car crash", "hit by a car", "heart attack", "cardiac arrest", "having a stroke",
            "not breathing", "stopped breathing", "can t breathe", "cannot breathe", "can not breathe", "trouble breathing",
            "choking", "drowning", "bleeding", "unconscious", "fainted", "passed out", "collapsed", "seizure", "injured",
            "badly hurt", "stabbed", "overdose", "trapped", "rubble", "under the debris",
        ),
        gas=(
            "gas leak*", "leaking gas", "gas is leaking", "smell gas", "smell of gas", "smells of gas", "smells like gas",
            "gas smell",
        ),
        pleas=("help", "help me", "help us", "please help", "somebody help", "someone help"),
        gated=("emergency", "urgent", "earthquake", "fell", "fallen", "hurt"),
        company=(
            "doctor", "someone", "somebody", "man", "woman", "child", "kid", "baby", "father", "mother", "dad", "mom",
            "mum", "son", "daughter", "husband", "wife", "friend", "grandma", "grandpa", "brother", "sister", "boy", "girl",
            "person", "people", "now", "call", "injured", "tracks",
        ),
        masks=(
            "fire sale*", "fire exit*", "fire escape*", "fire extinguisher*", "fire station*", "fire drill*", "fire alarm test*",
            "fire safety", "fire door*", "fire insurance", "fire hazard*", "emergency exit*", "emergency room*",
            "emergency assembly", "emergency number*", "emergency phone*", "not an emergency", "help desk", "help center",
            "help centre", "help of", "by accident",
        ),
        negations=("no", "not", "without", "isn t", "wasn t", "nobody is", "no one is", "never"),
    ),
    "de": Vocab(
        terms=(
            "feuer", "es brennt", "brennt", "feuerwehr", "krankenwagen", "rettungswagen", "notarzt",
            "rettungsdienst", "polizei", "zu hilfe", "unfall", "autounfall", "verkehrsunfall", "herzinfarkt",
            "herzstillstand", "schlaganfall", "atmet nicht", "kann nicht atmen", "bekommt keine luft", "blutet", "blutung",
            "ertrinkt", "erstickt", "bewusstlos", "ohnmächtig", "verletzt", "verschüttet", "eingestürzt", "trümmer*",
            "überfallen",
        ),
        gas=("gasleck", "gasgeruch", "riecht nach gas", "gas riecht", "gas tritt aus", "gasaustritt"),
        pleas=("hilfe", "helfen sie mir", "helft mir", "hilf mir", "helfen sie"),
        gated=("notfall", "dringend", "erdbeben", "gestürzt", "hingefallen", "umgefallen"),
        company=(
            "arzt", "ärztin", "jemand", "mann", "frau", "kind", "baby", "vater", "mutter", "mama", "papa", "sohn",
            "tochter", "freund", "freundin", "oma", "opa", "bruder", "schwester", "person", "jetzt", "gerade", "ruf*",
            "verletzt",
        ),
        masks=("im notfall", "für den notfall", "notfall nummer*", "notfallnummer*"),
        negations=("kein", "keine", "keinen", "nicht", "ohne"),
    ),
    "fr": Vocab(
        terms=(
            "feu", "incendie", "ça brûle", "brûle", "pompiers", "ambulance", "samu", "police", "gendarmerie",
            "au secours", "à l aide", "accident", "crise cardiaque", "arrêt cardiaque", "infarctus", "avc",
            "ne respire pas", "ne respire plus", "n arrive pas à respirer", "n arrive plus à respirer", "s étouffe",
            "saigne", "saignement", "hémorragie", "se noie", "noyade", "inconscient*", "évanoui*", "perdu connaissance",
            "blessé*", "sous les décombres", "décombres", "effondré*", "agressé*",
        ),
        gas=("fuite de gaz", "fuite du gaz", "odeur de gaz", "sent le gaz"),
        pleas=("aidez moi", "aidez nous", "aide moi", "aide"),
        gated=("urgence", "urgent", "urgente", "séisme", "tremblement de terre", "tombé", "tombée"),
        company=(
            "médecin", "docteur", "quelqu un", "homme", "femme", "enfant", "bébé", "père", "mère", "papa", "maman",
            "fils", "fille", "ami", "amie", "mari", "maintenant", "appel*", "blessé*",
        ),
        masks=(
            "feu rouge", "feu vert", "feu orange", "feu d artifice", "au coin du feu", "à feu doux", "à l aide de",
            "à l aide d", "sortie de secours", "issue de secours", "service des urgences", "numéro d urgence",
            "pas une urgence",
        ),
        negations=("pas", "pas de", "pas d", "aucun", "aucune", "sans", "ni"),
    ),
    "es": Vocab(
        terms=(
            "fuego", "incendio", "se quema", "quemando", "bomberos", "ambulancia", "policía", "socorro", "auxilio",
            "accidente", "ataque al corazón", "ataque cardiaco", "infarto", "paro cardiaco", "no respira",
            "no puede respirar", "no puedo respirar", "se ahoga", "ahogando", "sangra", "sangrando", "hemorragia",
            "inconsciente", "desmay*", "perdió el conocimiento", "herid*", "escombros", "derrumb*", "atrapado*",
            "apuñal*",
        ),
        gas=("fuga de gas", "olor a gas", "huele a gas", "escape de gas"),
        pleas=("ayuda", "ayúdame", "ayúdenme", "ayúdeme", "ayúdanos"),
        gated=("urgente", "emergencia", "terremoto", "sismo", "se cayó", "cayó"),
        company=(
            "médico", "doctor", "alguien", "hombre", "mujer", "niño", "niña", "bebé", "padre", "madre", "papá", "mamá",
            "hijo", "hija", "amigo", "amiga", "esposo", "esposa", "marido", "abuelo", "abuela", "ahora", "llam*",
            "herid*",
        ),
        masks=("fuegos artificiales", "salida de emergencia", "sala de emergencia*", "número de emergencia*", "ayuda con"),
        negations=("no", "no hay", "sin", "ningún", "ninguna", "nadie", "nadie está", "ni"),
    ),
    "it": Vocab(
        terms=(
            "fuoco", "incendio", "brucia", "sta bruciando", "vigili del fuoco", "pompieri", "ambulanza", "polizia",
            "carabinieri", "incidente", "infarto", "attacco di cuore", "attacco cardiaco", "arresto cardiaco",
            "ictus", "non respira", "non riesce a respirare", "non riesco a respirare", "soffoca", "sta soffocando",
            "sanguina", "sanguinando", "emorragia", "annega", "sta annegando", "svenut*", "incosciente", "privo di sensi",
            "priva di sensi", "ferito", "ferita", "feriti", "macerie", "crollat*", "crollo", "intrappolat*",
        ),
        gas=("fuga di gas", "odore di gas", "puzza di gas", "perdita di gas"),
        pleas=("aiuto", "aiutatemi", "aiutami", "aiutateci"),
        gated=("emergenza", "urgente", "terremoto", "scossa", "caduto", "caduta"),
        company=(
            "medico", "dottore", "qualcuno", "uomo", "donna", "bambino", "bambina", "neonato", "padre", "madre", "papà",
            "mamma", "figlio", "figlia", "amico", "amica", "marito", "moglie", "nonno", "nonna", "adesso", "ora",
            "chiam*", "ferito", "ferita",
        ),
        masks=(
            "fuochi d artificio", "fuoco d artificio", "pronto soccorso", "uscita di emergenza", "numero di emergenza",
            "non è un emergenza", "a fuoco lento",
        ),
        negations=("non", "non c è", "nessun", "nessuna", "nessuno", "senza"),
    ),
    "ru": Vocab(
        terms=(
            "пожар*", "горит", "горим", "огонь", "скорая", "скорую", "скорой", "полиция", "полицию", "полиции",
            "спасите", "авария", "аварию", "аварии", "дтп", "несчастный случай", "сердечный приступ", "инфаркт*",
            "инсульт*", "не дышит", "не могу дышать", "не может дышать", "задыхается", "задыхаюсь", "кровотечение",
            "истекает кровью", "тонет", "тону", "тонут", "утонул*", "без сознания", "потерял* сознание",
            "упал* в обморок", "ранен*", "ранили", "обрушил*", "под завалами", "завалило",
        ),
        gas=("утечк* газа", "запах газа", "пахнет газом", "газ утекает"),
        pleas=("помогите", "помоги", "помогите пожалуйста"),
        gated=("срочно", "экстренн*", "чрезвычайн*", "землетрясени*", "упал", "упала", "упали"),
        company=(
            "врач*", "доктор*", "кто", "человек*", "мужчин*", "женщин*", "ребёнок", "ребенка", "дети", "мама", "папа",
            "мать", "отец", "сын", "дочь", "муж", "жена", "друг", "подруга", "бабушк*", "дедушк*", "сейчас", "вызов*",
            "звони*", "ранен*",
        ),
        masks=(
            "пожарн* лестниц*", "пожарн* выход*", "пожарн* безопасност*", "пожарн* сигнализац*", "пожарн* извещател*",
            "пожарн* кран*", "пожарн* инспекц*", "пожарн* эвакуац*", "пожарн* част*", "аварийн* выход*",
        ),
        negations=("нет", "не", "без", "никакого", "никакой", "никаких"),
    ),
    "uk": Vocab(
        terms=(
            "пожеж*", "горить", "вогонь", "швидк* допомог*", "швидку", "поліці*", "рятуйте", "аварі*", "дтп",
            "нещасн* випад*", "серцев* напад*", "інфаркт*", "інсульт*", "не дихає", "не можу дихати", "не може дихати",
            "задихає*", "кровотеч*", "стікає кров*", "тоне", "тону", "тонуть", "потону*", "втопи*", "непритомн*",
            "знепритомні*", "втрати* свідом*", "поранен*", "під завал*", "обвали*", "завалило",
        ),
        gas=("вит* газу", "запах газу", "пахне газом"),
        pleas=("допоможіть", "допоможи", "допоможіть будь ласка"),
        gated=("терміново", "екстрен*", "надзвичайн*", "землетрус*", "впав", "впала", "впали"),
        company=(
            "лікар*", "хтось", "людин*", "чоловік*", "жінк*", "дитин*", "діти", "мама", "тато", "мати", "батько", "син",
            "донька", "дочка", "дружина", "друг", "подруга", "бабус*", "дідус*", "зараз", "виклич*", "телефон*",
            "поранен*",
        ),
        masks=(
            "пожежн* драбин*", "пожежн* вихід*", "пожежн* виход*", "пожежн* безпек*", "пожежн* сигналізац*",
            "пожежн* евакуац*", "пожежн* частин*", "аварійн* вихід*", "аварійн* виход*",
        ),
        negations=("немає", "нема", "не", "без", "жодної", "жодного"),
    ),
    "ar": Vocab(
        terms=(
            "حريق", "نار", "إسعاف", "شرطة", "بوليس", "نجدة", "أنقذوني", "أنقذونا", "الحقوني", "حادث", "حادثة",
            "نوبة قلبية", "أزمة قلبية", "سكتة قلبية", "جلطة", "لا يتنفس", "لا تتنفس", "لا أستطيع التنفس",
            "لا يستطيع التنفس", "يختنق", "اختناق", "نزيف", "ينزف", "تنزف", "غرق", "يغرق", "أغمي", "مغمى عليه",
            "فاقد الوعي", "فقد الوعي", "مصاب", "مصابين", "جريح", "جرحى", "تحت الأنقاض", "أنقاض",
        ),
        gas=("تسرب غاز", "تسريب غاز", "رائحة غاز", "ريحة غاز"),
        pleas=("ساعدوني", "ساعدونا", "ساعدني"),
        gated=("طوارئ", "عاجل", "زلزال", "هزة أرضية", "انهار", "سقط", "وقع"),
        company=(
            "طبيب", "دكتور", "أحد", "شخص", "رجل", "امرأة", "طفل", "ولد", "بنت", "أبي", "أمي", "ابني", "بنتي", "زوجي",
            "زوجتي", "صديقي", "جدي", "جدتي", "مبنى", "بناء", "بناية", "عمارة", "سقف", "بيت", "الآن", "اتصل*",
        ),
        masks=("مخرج طوارئ", "قسم طوارئ", "رقم طوارئ"),
        negations=("لا", "ليس", "ليست", "لم", "بدون", "لا يوجد", "ليس هناك", "ما في", "مافي"),
        clitics=True,
    ),
    "fa": Vocab(
        terms=(
            "آتش سوزی", "آتشسوزی", "آتش", "آتش گرفت*", "حریق", "آمبولانس", "پلیس", "تصادف*", "سکته*", "حمله قلبی",
            "ایست قلبی", "نفس نمی کشد", "نفس نمیکشد", "نمی تواند نفس", "نمیتواند نفس", "نمی تونه نفس", "نمیتونه نفس",
            "خونریزی", "خون ریزی", "غرق", "بیهوش", "زخمی", "مجروح", "زیر آوار", "آوار", "به دادم برسید", "نجاتم بد*",
        ),
        gas=("نشت گاز", "بوی گاز", "گاز نشت"),
        pleas=("کمک", "کمک کنید", "کمکم کنید", "کمک کن"),
        gated=("اورژانس", "فوری", "اضطراری", "زلزله", "افتاد", "زمین خورد"),
        company=(
            "دکتر", "پزشک", "کسی", "یکی", "مرد", "زن", "بچه", "کودک", "پدر", "مادر", "بابا", "مامان", "پسر", "دختر",
            "شوهر", "همسر", "دوست", "مادربزرگ", "پدربزرگ", "الان", "زنگ", "تماس", "خبر",
        ),
        masks=("آتش بازی", "آتش بس", "ایستگاه آتش نشانی", "خروج اضطراری", "شماره اضطراری"),
        negations=("نه", "بدون", "هیچ"),
    ),
}  # fmt: skip


# -- a stated condition next to an everyday question (KARAR 5), read by emergency_lang ------------------
# Written the way a person types; folded like the health mask (nabiz.console.health_mask), case and
# accents away, one character for one. A word ending in ``!`` matches whole; any other entry matches at a
# word's start ("agri" is "ağrıyor", "ağrım"). A missed emergency costs more than a false alarm, so the
# acute list leans wide: a condition is set aside only when none of it is in the message.

#: Acute signs: pain, breath, consciousness, bleeding, a fall, a plea, a sudden change.
ACUTE_SIGNS: tuple[str, ...] = (
    # Turkish
    "ağrı", "sancı", "nefes", "soluk", "soluy", "boğul", "bilinc", "bayıl", "baygın", "kanam", "kanıyor",
    "kan geliyor", "kan kus", "düştü", "düştüm", "düşme", "düşecek", "yığıl", "acil", "yardım", "imdat", "kriz",
    "nöbet", "fenalaş", "kötüleş", "kötüyüm", "titri", "morar", "konuşamıy", "kusuy", "felç", "inme geçir",
    "inme indi", "göğsüm", "göğüs", "kalbim", "kalbi dur", "şekerim düş", "şekerim çık", "tansiyonum çık",
    "tansiyonum düş", "tansiyonum yüksel", "uyuşu", "ateş", "zehirlen", "ayılmıy", "hareket etmiyor",
    "cevap vermiyor", "duman", "alev", "yanıyor", "112!",
    # English
    "pain", "hurt", "chest", "breath", "faint", "dizzy", "unconscious", "collaps", "bleed", "fell!", "falling",
    "emergency", "help", "attack", "seizure", "vomit", "numb", "poison",
    # German
    "schmerz", "atem", "luft", "bewusstlos", "ohnmacht", "ohnmächtig", "blut", "gestürzt", "notfall", "hilfe",
    "anfall", "schwindel",
    # Russian
    "болит", "боль!", "боли!", "дыш", "сознан", "обморок", "кров", "упал", "срочно", "помог", "приступ", "плохо",
    # Arabic
    "ألم", "يتنفس", "تنفس", "الوعي", "إغماء", "نزيف", "سقط", "طوارئ", "مساعدة", "ساعد", "نوبة",
)  # fmt: skip
#: A request for medical advice stays refused (R-06) even after a stated condition.
MEDICAL_ADVICE: tuple[str, ...] = (
    "ilaç", "doz", "teşhis", "tanı!", "tanısı", "tedavi", "reçete", "yan etki", "ne yapmalıyım", "ne yapayım",
    "yiyebilir", "içebilir", "kullanabilir", "zararlı", "insülin", "mg!", "dose", "medication", "medicine",
    "diagnos", "treatment", "should i take", "side effect", "can i eat",
)  # fmt: skip
#: What makes the rest of the question an everyday one: travel, a stop, a lift, a service. Without one of
#: these a stated condition still refuses ("Kalp hastasıyım, bugün yürüyebilir miyim?" asks health advice).
SERVICE_CUES: tuple[str, ...] = (
    # Turkish
    "asansör", "yürüyen merdiven", "rampa", "metro", "otobüs", "tramvay", "vapur", "marmaray", "teleferik",
    "füniküler", "dolmuş", "minibüs", "durak", "istasyon", "iskele", "hat!", "hatt", "sefer", "aktarma",
    "nasıl gider", "nasıl gidebilir", "nasıl ulaş", "yol tarifi", "rota", "istanbulkart", "otopark", "ispark",
    "adımsız", "tekerlekli", "tuvalet", "kütüphane", "müze", "hastaneye", "hastanesine", "sağlık ocağına",
    # English
    "lift", "elevator", "escalator", "ramp", "bus", "tram", "ferry", "station", "stop!", "line!",
    "how do i get", "how can i get", "route", "step free", "wheelchair", "parking", "toilet",
)  # fmt: skip
#: Turkish phrases that name fire equipment or a drill, not a fire: "Yangın tüpü nereden alınır?", "yangın
#: merdiveni nerede?". Taken out before the Turkish rules read "yangın", unless the message carries an acute
#: sign ("yangın merdiveninde duman var", "yangın çıkışında yardım edin").
TURKISH_MASKS: tuple[str, ...] = (
    "yangın merdiven", "yangın çıkış", "yangın kapı", "yangın tüp", "yangın söndür", "yangın dolab", "yangın alarm",
    "yangın tatbikat", "yangın sigorta", "yangın yönetmeliğ", "yangın güvenliğ", "yangın ihbar hattı",
)  # fmt: skip
