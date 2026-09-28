"""Rendered screens, catalog pairs and page-module boundaries for E59."""

from __future__ import annotations

import json
import re

from test_static_a11y import STATIC, node_json

from nabiz.console.case_file import BAND, water_route

VIEW = {"view": "js/case_file_view.js"}
COMMON = {
    "ui.case.example": ("Örnek", "Example"),
    "ui.case.title": ("İş dosyam", "My work file"),
    "ui.case.intro": (
        "Bir yaşam olayını resmî sayfalara bağlı adımlara çevirir; kaldığınız yeri hatırlar.",
        "Turn a life event into steps linked to official pages and pick up where you left off.",
    ),
    "ui.case.plan.tasinma": ("İstanbul'a taşındım", "I moved to Istanbul"),
    "ui.case.choose_plan": ("Plan seçin", "Choose a plan"),
    "ui.case.privacy": ("Gizlilik bilgisi", "Privacy information"),
    "ui.case.consent_error": ("Devam etmek için açık rıza kutusunu işaretleyin.", "Check the consent box to continue."),
    "ui.case.start": ("Planı başlat", "Start plan"),
    "ui.case.device_hint": (
        "Hesapsız da çalışır: iş dosyanız bu tarayıcıya bağlı bir anahtarla açılır. "
        "Tarayıcı verilerini silerseniz dosyaya ulaşamazsınız.",
        "It also works without an account. Your file opens with a key kept in this browser. "
        "Clearing browser data removes access.",
    ),
    "ui.case.how": ("Bu nasıl çalışır?", "How does this work?"),
    "ui.case.how_text": (
        "Her adım ilgili kurumun sayfasına dayanır. Resmî işlem bağlantıları kurumların kendi sayfalarıdır.",
        "Each step is tied to a relevant institution page. Official process links lead to the institutions' own pages.",
    ),
    "ui.case.open_source": ("Resmî sayfayı aç", "Open official page"),
    "ui.case.open_official": ("Resmî sayfayı aç", "Open official page"),
    "ui.case.documents": ("Gerekli belgeler", "Required documents"),
    "ui.case.recorded": ("kayıtlı", "recorded"),
    "ui.case.water_question": ("Bu evde su aboneliği ne durumda?", "What is the water subscription status at this home?"),
    "ui.case.choice.iptal": (
        "İstanbul'daki eski evimdeki aboneliği kapatacağım",
        "I want to close the subscription at my former home in Istanbul",
    ),
    "ui.case.choice.yenileme": (
        "Bu evdeki önceki abonelik kapatılmış (iptal edilmiş)",
        "The previous subscription at this home has been closed",
    ),
    "ui.case.choice.yeni": ("Bu binada hiç su aboneliği yok (yeni bina)", "This building has no water subscription"),
    "ui.case.choice.bilmiyorum": (
        "Önceki oturanın aboneliği hâlâ açık ya da bilmiyorum",
        "The previous resident's subscription may still be open, or I do not know",
    ),
    "ui.case.route_iptal": (
        "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir.",
        "Based on the situation you selected, this is the relevant İSKİ page. İSKİ makes the decision.",
    ),
    "ui.case.route_yenileme": (
        "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir.",
        "Based on the situation you selected, this is the relevant İSKİ page. İSKİ makes the decision.",
    ),
    "ui.case.route_yeni": (
        "Seçtiğiniz duruma göre ilgili İSKİ sayfası bu. Karar İSKİ'nindir.",
        "Based on the situation you selected, this is the relevant İSKİ page. İSKİ makes the decision.",
    ),
    "ui.case.route_bilmiyorum": (
        "Bu durum kaynakta açıkça anlatılmıyor. İSKİ'ye ya da 153'e sorun.",
        "This situation is not clearly covered by the source. Ask İSKİ or 153.",
    ),
    "ui.case.channel_missing": (
        "Başvuru kanalı bu sayfada yazmıyor; resmî sayfayı açın.",
        "The application channel is not stated on this page. Open the official page.",
    ),
    "ui.case.source_missing": (
        "Bu konuda dizinde kaynak henüz yok; resmî siteyi açın.",
        "There is no indexed source for this yet. Open the official site.",
    ),
    "ui.case.points_unavailable": (
        "Noktalar listelenemedi; resmî sayfayı açın.",
        "The points could not be listed. Open the official page.",
    ),
    "ui.case.district": ("İlçe seçin", "Choose a district"),
    "ui.case.choose_district": ("İlçenizi seçin", "Choose your district"),
    "ui.case.select_district_first": ("İlçenizi seçin.", "Choose your district."),
    "ui.case.no_district_points": ("Bu ilçe için listede nokta yok.", "There are no listed points for this district."),
    "ui.case.district_office_hint": ("ilçe belediyenizin resmî sitesi", "your district municipality's official site"),
    "ui.case.step.su": ("Su aboneliği", "Water subscription"),
    "ui.case.step.dogalgaz": ("Doğal gaz", "Natural gas"),
    "ui.case.step.istanbulkart": ("İstanbulkart", "Istanbulkart"),
    "ui.case.step.sosyal-nokta": ("Yakınınızdaki sosyal hizmet noktası", "A social service point near you"),
    "ui.case.step.ilce": ("İlçe belediyeniz", "Your district municipality"),
    "ui.case.step.153": ("153 Çözüm Merkezi", "153 Solution Center"),
    "ui.case.completed": ("Tamamlandı", "Completed"),
    "ui.case.progress": ("{done}/{total} adım tamam", "{done}/{total} steps complete"),
    "ui.case.reminder_today": ("Bugün hatırlatma: {step}", "Reminder today: {step}"),
    "ui.case.all_done": ("Tüm adımlar tamam", "All steps complete"),
    "ui.case.note_ref": ("Not ve referans kodu", "Note and reference code"),
    "ui.case.note": ("Not", "Note"),
    "ui.case.no_pii": ("Kimlik, kart, telefon yazmayın.", "Do not enter identity, card, or phone details."),
    "ui.case.reference": (
        "Referans kodu (kurumdan aldığınız başvuru numarası)",
        "Reference code (application number from the institution)",
    ),
    "ui.case.save": ("Kaydet", "Save"),
    "ui.case.added_by_user": ("Siz eklediniz", "You added"),
    "ui.case.not_verified": ("Kurum doğrulaması yok", "Not verified by the institution"),
    "ui.case.reminder": ("Hatırlatma", "Reminder"),
    "ui.case.remind_on": ("Hatırlatma tarihi", "Reminder date"),
    "ui.case.reminder_hint": (
        "Hatırlatma yalnız bu sayfayı açtığınızda görünür; bildirim gönderilmez.",
        "The reminder appears only when you open this page. No notification is sent.",
    ),
    "ui.case.remove_reminder": ("Hatırlatmayı kaldır", "Remove reminder"),
    "ui.case.delete_file": ("İş dosyasını sil", "Delete work file"),
    "ui.case.delete_explain": (
        "Adımlarınız, notlarınız ve referans kodlarınız silinir.",
        "Your steps, notes, and reference codes will be deleted.",
    ),
    "ui.case.delete": ("Sil", "Delete"),
    "ui.case.loading": ("Yükleniyor", "Loading"),
    "ui.case.error": ("İş dosyası açılamadı. Yeniden deneyin.", "The work file could not be opened. Try again."),
    "ui.case.retry": ("Yeniden dene", "Try again"),
    "ui.case.saved_at": ("Kaydedildi · {time}", "Saved · {time}"),
    "ui.case.saving": ("Kaydediliyor", "Saving"),
    "ui.case.reminder_count": ("Bugün {count} hatırlatma", "{count} reminders today"),
    "ui.case.storage_error": (
        "Tarayıcı bu iş dosyasını saklayamadı. Hesapla yeniden deneyin.",
        "This browser could not store the work file. Try again with an account.",
    ),
}
CATALOG = {
    "tr": {key: pair[0] for key, pair in COMMON.items()},
    "en": {key: pair[1] for key, pair in COMMON.items()},
}


def _sample() -> tuple[dict, dict]:
    agency = {"id": "iski", "name": "İSKİ", "possessive": "İSKİ'nin", "url": "https://iski.istanbul/"}
    source = {
        "indexed": True,
        "title": "İSKİ",
        "institution": "İSKİ",
        "fetched_at": "2026-09-26T12:44:57+00:00",
        "url": "https://iski.istanbul/abone-hizmetleri/abone-rehberi/yenileme-abonelik-islemleri/",
        "quotes": [
            "Şahsen veya mesafeli sözleşme hükümleri çerçevesinde; sözleşmesi iptal durumunda olan "
            "birimlere yeni abonelik talebinde bulunulması halinde ise yenileme işlemi tesis edilir."
        ],
        "documents": ["Mal sahibi veya kiracı olduğunu belgelemesi veya yazılı beyan etmesi."],
    }
    missing = {
        "indexed": False,
        "title": None,
        "institution": None,
        "fetched_at": None,
        "url": None,
        "quotes": [],
        "documents": [],
    }
    plan = {
        "id": "tasinma",
        "title": "İstanbul'a taşındım",
        "title_en": "I moved to Istanbul",
        "steps": [
            {
                "id": "su",
                "title": "Su aboneliği",
                "title_en": "Water subscription",
                "agency": "iski",
                "agency_info": agency,
                "kind": "choice",
                "choices": [
                    {
                        "id": "iptal",
                        "label": "İstanbul'daki eski evimdeki aboneliği kapatacağım",
                        "label_en": "I want to close the subscription at my former home in Istanbul",
                        "source": 0,
                    },
                    {
                        "id": "yenileme",
                        "label": "Bu evdeki önceki abonelik kapatılmış (iptal edilmiş)",
                        "label_en": "The previous subscription at this home has been closed",
                        "source": 1,
                    },
                    {
                        "id": "yeni",
                        "label": "Bu binada hiç su aboneliği yok (yeni bina)",
                        "label_en": "This building has no water subscription",
                        "source": 2,
                    },
                    {
                        "id": "bilmiyorum",
                        "label": "Önceki oturanın aboneliği hâlâ açık ya da bilmiyorum",
                        "label_en": "The previous resident's subscription may still be open, or I do not know",
                        "source": None,
                    },
                ],
                "sources": [missing, source, missing],
            },
            {
                "id": "dogalgaz",
                "title": "Doğal gaz",
                "agency": "igdas",
                "agency_info": {"id": "igdas", "name": "İGDAŞ", "url": "https://www.igdas.istanbul/"},
                "kind": "link",
                "sources": [],
            },
            {
                "id": "istanbulkart",
                "title": "İstanbulkart",
                "agency": "istanbulkart",
                "agency_info": {
                    "id": "istanbulkart",
                    "name": "BELBİM (İstanbulkart)",
                    "url": "https://www.istanbulkart.istanbul/",
                },
                "kind": "task",
                "sources": [missing],
            },
            {
                "id": "sosyal-nokta",
                "title": "Yakınınızdaki sosyal hizmet noktası",
                "agency": "ibb",
                "agency_info": {"id": "ibb", "name": "İBB", "url": "https://ibb.istanbul/"},
                "kind": "points",
                "sources": [missing],
                "districts": ["Kartal"],
                "points": [],
            },
            {
                "id": "ilce",
                "title": "İlçe belediyeniz",
                "agency": "district_office",
                "agency_info": {"name": "İlçe belediyesi", "url": None, "hint": "ilçe belediyenizin resmî sitesi"},
                "kind": "link",
                "sources": [],
            },
            {
                "id": "153",
                "title": "153 Çözüm Merkezi",
                "agency": "cozum_153",
                "agency_info": {"name": "153 Çözüm Merkezi", "url": "https://cozummerkezi.ibb.istanbul/"},
                "kind": "link",
                "sources": [],
            },
        ],
    }
    file = {
        "id": "f" * 32,
        "plan_id": "tasinma",
        "answers": {"su": "yenileme"},
        "steps": [
            {
                "step_id": "su",
                "done_at": None,
                "note": "<img src=x>",
                "ref_code": "R-42",
                "remind_on": "2026-09-27",
                "added_by": "user",
                "verified": False,
            },
            {
                "step_id": "dogalgaz",
                "done_at": "2026-09-27T10:00:00+00:00",
                "note": None,
                "ref_code": None,
                "remind_on": None,
                "added_by": "user",
                "verified": False,
            },
        ],
        "progress": {"done": 1, "total": 6},
        "reminders": [{"title": "Su aboneliği"}],
    }
    return plan, file


def _rendered(tmp_path):
    plan, file = _sample()
    payload = {"plan": plan, "file": file, "plans": [plan], "consent": {"text": "Açık rıza metni."}}
    script = (
        f"view.setCatalogs('en', {json.dumps(CATALOG['en'], ensure_ascii=False)}, "
        f"{json.dumps(CATALOG['tr'], ensure_ascii=False)});"
        f"const start = view.startView({json.dumps(payload['plans'], ensure_ascii=False)}, "
        f"{json.dumps(payload['consent'], ensure_ascii=False)});"
        f"const file = view.fileView({json.dumps(file, ensure_ascii=False)}, "
        f"{json.dumps(plan, ensure_ascii=False)}, '2026-09-27');"
        f"const rawFile={json.dumps(file, ensure_ascii=False)}, rawPlan={json.dumps(plan, ensure_ascii=False)};"
        "const onlyDone={...rawFile,steps:[{...rawFile.steps[1],step_id:'su',done_at:'2026-09-27',"
        "note:null,ref_code:null,remind_on:null}],progress:{done:1,total:1},reminders:[]};"
        "const doneOnly=view.fileView(onlyDone,{...rawPlan,steps:[rawPlan.steps[0]]},'2026-09-27');"
        "const onlyReminder={...rawFile,steps:[{...rawFile.steps[0],done_at:null,note:null,"
        "ref_code:null,remind_on:'2026-09-27'}],progress:{done:0,total:1},reminders:[]};"
        "const reminderOnly=view.fileView(onlyReminder,{...rawPlan,steps:[rawPlan.steps[0]]},'2026-09-27');"
        "const fallbackPlan=JSON.parse(JSON.stringify(rawPlan));"
        "fallbackPlan.steps[3]={...fallbackPlan.steps[3],kind:'link',sources:[{indexed:true,url:'https://sosyalhizmetler.ibb.gov.tr/iletisimnoktalari.aspx',institution:'İBB',fetched_at:'2026-09-27'}]};"
        "const pointsFallback=view.fileView({...rawFile,progress:{done:0,total:1}}, "
        "{...fallbackPlan,steps:[fallbackPlan.steps[3]]},'2026-09-27');"
        "const error = view.errorView('Plan yüklenemedi.');"
        "console.log(JSON.stringify({start, file, doneOnly, reminderOnly, pointsFallback, error}));"
    )
    return node_json(tmp_path, VIEW, script)


def _buttons(markup: str) -> list[str]:
    return re.findall(r"<button\b[^>]*>", markup, flags=re.IGNORECASE)


def test_catalog_pairs_and_english_markup(tmp_path) -> None:
    assert set(CATALOG["tr"]) == set(CATALOG["en"])
    rendered = _rendered(tmp_path)
    assert "Start plan" in rendered["start"]
    assert "Water subscription" in rendered["file"]
    assert "Try again" in rendered["error"]
    assert "Şahsen veya mesafeli" in rendered["file"]
    assert 'lang="tr"' in rendered["file"]


def test_screen_primary_button_order_band_and_source_gating(tmp_path) -> None:
    rendered = _rendered(tmp_path)
    assert rendered["start"].count("btn-primary") == 1
    assert "btn-primary" in _buttons(rendered["start"])[0]
    assert "btn-primary" not in rendered["file"]
    assert rendered["error"].count("btn-primary") == 1
    assert "btn-primary" in _buttons(rendered["error"])[0]
    for markup in rendered.values():
        assert BAND in markup
        assert '<span class="tag is-warn">' in markup
    assert "Open official page" in rendered["file"]
    assert "/yenileme-abonelik-islemleri/" in rendered["file"]
    assert 'href="https://www.istanbulkart.istanbul/"' not in rendered["file"]
    assert 'href="https://www.igdas.istanbul/"' in rendered["file"]
    assert 'href="None"' not in rendered["file"]


def test_user_text_is_escaped_and_attribution_is_clear(tmp_path) -> None:
    rendered = _rendered(tmp_path)["file"]
    assert "&lt;img src=x&gt;" in rendered
    assert "<img src=x>" not in rendered
    assert "You added" in rendered and "Not verified by the institution" in rendered
    assert "aria-label" not in rendered or 'role="status"' in rendered


def test_completion_and_reminder_alone_are_attributed_and_points_fallback_links(tmp_path) -> None:
    rendered = _rendered(tmp_path)
    for screen in (rendered["doneOnly"], rendered["reminderOnly"]):
        assert "You added" in screen and "Not verified by the institution" in screen
    assert "The points could not be listed." in rendered["pointsFallback"]
    assert 'href="https://sosyalhizmetler.ibb.gov.tr/iletisimnoktalari.aspx"' in rendered["pointsFallback"]


def test_progress_reminder_and_recorded_source_date(tmp_path) -> None:
    rendered = _rendered(tmp_path)["file"]
    assert "1/6 steps complete" in rendered and "<progress" in rendered
    assert "Reminder today: Su aboneliği" in rendered
    assert "recorded · 26.09.2026" in rendered
    assert 'min="2026-09-27"' in rendered and 'max="2027-09-27"' in rendered


def test_javascript_and_python_water_routes_match(tmp_path) -> None:
    ids = ["iptal", "yenileme", "yeni", "bilmiyorum"]
    values = node_json(tmp_path, VIEW, f"console.log(JSON.stringify({json.dumps(ids)}.map(view.waterRoute))); ")
    assert values == [water_route(choice) for choice in ids]


def test_controller_and_pure_view_boundaries() -> None:
    controller = (STATIC / "js" / "case_file.js").read_text(encoding="utf-8")
    view = (STATIC / "js" / "case_file_view.js").read_text(encoding="utf-8")
    styles = (STATIC / "css" / "case_file.css").read_text(encoding="utf-8")
    assert controller.rfind("if (typeof document !== 'undefined')") > controller.rfind("export {")
    assert len(controller.splitlines()) <= 350
    assert "setInterval" not in controller and "addEventListener('scroll'" not in controller
    for path in re.findall(r"request\((?:`|['\"])(/api/[^'\"`]+)", controller):
        assert path.startswith("/api/case-file"), path
    assert controller.count("X-Nabiz-Case") == 1
    assert "const key = readAccount() ? ''" in controller
    assert "ownerRevision += 1; state.file = null" in controller
    assert "const revision = ownerRevision" in controller and "if (revision !== ownerRevision) return;" in controller
    assert re.search(r"\bdocument\b", view) is None
    assert re.search(r"\bwindow\b|\bfetch\b|\blocalStorage\b|\bDate\.now\b|new Date\(\)", view) is None
    assert "#" not in re.sub(r"https?://[^\s\"']+", "", styles)
    assert ".btn-danger" not in styles and "infinite" not in styles
    assert re.search(r"\border\s*:", styles) is None
    animation_at = styles.index("animation:")
    media_at = styles.rfind("@media (prefers-reduced-motion: no-preference)", 0, animation_at)
    assert media_at > styles.rfind("}", 0, animation_at)
    for body in re.findall(r"body: \{[^}]*\}", controller):
        assert "district" not in body, body
    # The district only flows between the select, localStorage and the pure view; never into a request.
    local_only = r"district: local\(\)\.district|local\(\)\.district|district: input\.value|data-case-district"
    assert "district" not in re.sub(local_only, "", controller)
    for path in (STATIC / "console.html", STATIC / "kolay.html"):
        assert "case_file" not in path.read_text(encoding="utf-8")
