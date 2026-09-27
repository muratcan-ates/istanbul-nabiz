"""E67's translated, escaped, reduced-motion console module contract."""

from __future__ import annotations

import json
import re
import subprocess

from conftest import REPO_ROOT

JS = REPO_ROOT / "src/nabiz/console/static/js/console_incidents.js"
CSS = REPO_ROOT / "src/nabiz/console/static/css/console_incidents.css"

CATALOG = {
    "tr": {
        "ui.inc.title": "Olay dosyaları",
        "ui.inc.description": (
            "Aynı istasyondaki vatandaş bildirimleri, fotoğraflar ve İBB kaydı bir arada. Öncelik bir öneridir; karar sizindir."
        ),
        "ui.inc.empty": "Bu pencerede olay dosyası yok. Vatandaş bildirimi gelince burada görünür.",
        "ui.inc.mock": "Örnek veri modunda olay dosyaları gösterilmez.",
        "ui.inc.loading": "Olay dosyaları yükleniyor.",
        "ui.inc.loadError": "Olay dosyaları şu an yüklenemedi.",
        "ui.inc.count": "{count} olay dosyası",
        "ui.inc.priorityHigh": "Yüksek",
        "ui.inc.priorityMedium": "Orta",
        "ui.inc.priorityNormal": "Olağan",
        "ui.inc.suggestion": "Öneri: {level}",
        "ui.inc.operatorDecision": "Operatör kararı: {level}",
        "ui.inc.reportsPhotos": "{reports} bildirim · {photos} fotoğraf · {record}",
        "ui.inc.recordYes": "İBB kaydı var",
        "ui.inc.recordNo": "İBB kaydı yok",
        "ui.inc.people": "{count} kişi bildirdi",
        "ui.inc.reportGroup": "Vatandaş bildirimleri (doğrulanmamış)",
        "ui.inc.photoGroup": "Fotoğraflar (vatandaş ekledi)",
        "ui.inc.equipmentGroup": "Resmî kayıt (kurum kaydı)",
        "ui.inc.noPhotos": "Fotoğraf modülü bu sunucuda yok.",
        "ui.inc.photoNoProof": "Fotoğraf tek başına kanıt değildir.",
        "ui.inc.sourceLedger": "defter",
        "ui.inc.sourceRecord": "kurum kaydı",
        "ui.inc.equipmentLift": "asansör",
        "ui.inc.sourceCitizen": "vatandaş (doğrulanmamış)",
        "ui.inc.repeatFactor": "{people} kişi, {cards} kart. Tekrar kodu: {repeat}. Pencere: {days} gün.",
        "ui.inc.waitingFactor": "En eski açık kart {hours} saattir bekliyor; eşik {threshold} saat.",
        "ui.inc.accessVerified": "Kurum kaydında {equipment} için {status}.",
        "ui.inc.accessUnverified": "Erişim etkisi vatandaş bildirimiyle sınırlı; kurum kaydı yok.",
        "ui.inc.interchange": "Aktarma istasyonu ({line}).",
        "ui.inc.conflictFactor": "Bildirim ile kurum kaydı çelişiyor: {text}. Yerinde kontrol gerekebilir.",
        "ui.inc.noConflict": "Kaynak çelişkisi yok.",
        "ui.inc.statusAwaiting": "onay bekliyor",
        "ui.inc.statusApproved": "onaylandı",
        "ui.inc.statusRejected": "reddedildi",
        "ui.inc.statusDeferred": "ertelendi",
        "ui.inc.statusExpired": "süresi doldu",
        "ui.inc.statusReceived": "alındı",
        "ui.inc.openCard": "Kartı aç",
        "ui.inc.split": "Ayır",
        "ui.inc.merge": "Başka olayla birleştir",
        "ui.inc.changePriority": "Önceliği değiştir",
        "ui.inc.returnSuggestion": "Öneriye dön",
        "ui.inc.undo": "Geri al",
        "ui.inc.history": "Geçmiş",
        "ui.inc.howCalculated": "Nasıl hesaplandı?",
        "ui.inc.calculationNote": (
            "Eşikler tasarım kararıdır: bekleme {wait} saat, tekrar eşiği {support} kişi. "
            "Doğrulanmış erişim etkisi yalnız İBB kaydından gelir."
        ),
        "ui.inc.agency": "Önerilen kurum: {name}",
        "ui.inc.agencyFallback": "153 Çözüm Merkezi",
        "ui.inc.agencyNote": "Öneri. Nabız hiçbir ekibe iş atamaz; karar ve iletme İBB çalışanınındır.",
        "ui.inc.noRecord": "Bu istasyon için İBB arıza kaydında satır yok. Kayıtta olmamak çalıştığını kanıtlamaz.",
        "ui.inc.multiStation": "Bu olay birden çok istasyonu içeriyor.",
        "ui.inc.reasonLabel": "Gerekçe",
        "ui.inc.reasonHelp": "5 ile 280 karakter. Kişisel bilgi yazmayın.",
        "ui.inc.reasonInvalid": "Gerekçe 5 ile 280 karakter olmalı ve kişisel bilgi içermemelidir.",
        "ui.inc.save": "Kaydet",
        "ui.inc.cancel": "Vazgeç",
        "ui.inc.targetLabel": "Hedef olay",
        "ui.inc.levelLabel": "Öncelik düzeyi",
        "ui.inc.prioritySaved": "Öncelik kaydedildi. Defter #{entry}.",
        "ui.inc.splitSaved": "Üye ayrıldı. Defter #{entry}.",
        "ui.inc.mergeSaved": "Olaylar birleştirildi. Defter #{entry}.",
        "ui.inc.undoSaved": "Eylem geri alındı. Defter #{entry}.",
        "ui.inc.saveError": "İşlem kaydedilemedi: {message}",
        "ui.inc.actionSplit": "Üye ayrıldı",
        "ui.inc.actionMerge": "Olay birleştirildi",
        "ui.inc.actionUndo": "Eylem geri alındı",
        "ui.inc.ledgerRow": "defter #{entry}",
        "ui.inc.undone": "geri alındı",
        "ui.inc.reasonHistory": "Gerekçe: {reason}",
        "ui.inc.at": "kayıtlı · {time}",
        "ui.inc.photoAlt": "Vatandaşın gönderdiği fotoğraf: {category}, {station}",
        "ui.inc.repeatCode": "var",
        "ui.inc.repeatNoCode": "yok",
        "ui.inc.waitOver": "bekleme eşiği {threshold} saat aşıldı",
        "ui.inc.waitUnder": "bekleme eşiği {threshold} saat aşılmadı",
        "ui.inc.waitNone": "Açık kart yok; bekleme eşiği {threshold} saat.",
        "ui.inc.thresholds": "Önerinin dayanakları",
        "ui.inc.incidentLink": "Bu bildirim {station} olay dosyasında: {reports} bildirim, {photos} fotoğraf.",
        "ui.inc.openIncident": "Olay dosyasını aç",
        "ui.inc.noReports": "Bu olay dosyasına bağlı vatandaş bildirimi yok.",
        "ui.inc.noPhotosAttached": "Bu olay dosyasına bağlı fotoğraf yok.",
        "ui.inc.escalatorContext": "Yürüyen merdiven kaydı erişilebilir güzergâhı doğrulamaz.",
        "ui.inc.agencyLink": "resmî sayfa",
    },
    "en": {
        "ui.inc.title": "Incident files",
        "ui.inc.description": (
            "Citizen reports, photos and İBB records for one station are grouped here. Priority is a suggestion; you decide."
        ),
        "ui.inc.empty": "There are no incident files in this window. One will appear when a citizen report arrives.",
        "ui.inc.mock": "Incident files are hidden in example data mode.",
        "ui.inc.loading": "Loading incident files.",
        "ui.inc.loadError": "Incident files could not be loaded.",
        "ui.inc.count": "{count} incident files",
        "ui.inc.priorityHigh": "High",
        "ui.inc.priorityMedium": "Medium",
        "ui.inc.priorityNormal": "Routine",
        "ui.inc.suggestion": "Suggestion: {level}",
        "ui.inc.operatorDecision": "Operator decision: {level}",
        "ui.inc.reportsPhotos": "{reports} reports · {photos} photos · {record}",
        "ui.inc.recordYes": "İBB record available",
        "ui.inc.recordNo": "No İBB record",
        "ui.inc.people": "Reported by {count} people",
        "ui.inc.reportGroup": "Citizen reports (unverified)",
        "ui.inc.photoGroup": "Photos (added by citizens)",
        "ui.inc.equipmentGroup": "Official record (institution data)",
        "ui.inc.noPhotos": "The photo module is not available on this server.",
        "ui.inc.photoNoProof": "A photo alone is not evidence.",
        "ui.inc.sourceLedger": "ledger",
        "ui.inc.sourceRecord": "institution record",
        "ui.inc.equipmentLift": "lift",
        "ui.inc.sourceCitizen": "citizen (unverified)",
        "ui.inc.repeatFactor": "{people} people, {cards} cards. Repeat code: {repeat}. Window: {days} days.",
        "ui.inc.waitingFactor": "The oldest open card has waited {hours} hours; the threshold is {threshold} hours.",
        "ui.inc.accessVerified": "The institution record lists {status} for {equipment}.",
        "ui.inc.accessUnverified": "Access impact is based on a citizen report; there is no institution record.",
        "ui.inc.interchange": "Transfer station ({line}).",
        "ui.inc.conflictFactor": "The report conflicts with the institution record: {text}. An on-site check may help.",
        "ui.inc.noConflict": "No source conflict is recorded.",
        "ui.inc.statusAwaiting": "awaiting approval",
        "ui.inc.statusApproved": "approved",
        "ui.inc.statusRejected": "rejected",
        "ui.inc.statusDeferred": "deferred",
        "ui.inc.statusExpired": "expired",
        "ui.inc.statusReceived": "received",
        "ui.inc.openCard": "Open card",
        "ui.inc.split": "Separate",
        "ui.inc.merge": "Merge with another incident",
        "ui.inc.changePriority": "Change priority",
        "ui.inc.returnSuggestion": "Return to suggestion",
        "ui.inc.undo": "Undo",
        "ui.inc.history": "History",
        "ui.inc.howCalculated": "How it is calculated",
        "ui.inc.calculationNote": (
            "Thresholds are design choices: wait {wait} hours, repeat {support} people. "
            "Verified access impact comes only from an İBB record."
        ),
        "ui.inc.agency": "Suggested institution: {name}",
        "ui.inc.agencyFallback": "153 Solution Center",
        "ui.inc.agencyNote": "Suggestion only. Nabız does not assign work; İBB staff decide and forward it.",
        "ui.inc.noRecord": (
            "There is no row in the İBB equipment record for this station. Absence from the record does not prove it works."
        ),
        "ui.inc.multiStation": "This incident includes more than one station.",
        "ui.inc.reasonLabel": "Reason",
        "ui.inc.reasonHelp": "5 to 280 characters. Do not include personal information.",
        "ui.inc.reasonInvalid": "Reason must be 5 to 280 characters and contain no personal information.",
        "ui.inc.save": "Save",
        "ui.inc.cancel": "Cancel",
        "ui.inc.targetLabel": "Target incident",
        "ui.inc.levelLabel": "Priority level",
        "ui.inc.prioritySaved": "Priority saved. Ledger #{entry}.",
        "ui.inc.splitSaved": "Member separated. Ledger #{entry}.",
        "ui.inc.mergeSaved": "Incidents merged. Ledger #{entry}.",
        "ui.inc.undoSaved": "Action undone. Ledger #{entry}.",
        "ui.inc.saveError": "Could not save: {message}",
        "ui.inc.actionSplit": "Member separated",
        "ui.inc.actionMerge": "Incidents merged",
        "ui.inc.actionUndo": "Action undone",
        "ui.inc.ledgerRow": "ledger #{entry}",
        "ui.inc.undone": "undone",
        "ui.inc.reasonHistory": "Reason: {reason}",
        "ui.inc.at": "recorded · {time}",
        "ui.inc.photoAlt": "Photo sent by a citizen: {category}, {station}",
        "ui.inc.repeatCode": "yes",
        "ui.inc.repeatNoCode": "no",
        "ui.inc.waitOver": "wait threshold of {threshold} hours exceeded",
        "ui.inc.waitUnder": "wait threshold of {threshold} hours not reached",
        "ui.inc.waitNone": "No open card; wait threshold is {threshold} hours.",
        "ui.inc.thresholds": "Suggestion factors",
        "ui.inc.incidentLink": "This report is in the {station} incident file: {reports} reports, {photos} photos.",
        "ui.inc.openIncident": "Open incident file",
        "ui.inc.noReports": "No citizen reports are linked to this incident.",
        "ui.inc.noPhotosAttached": "No photos are linked to this incident.",
        "ui.inc.escalatorContext": "An escalator record does not verify a step-free route.",
        "ui.inc.agencyLink": "official page",
    },
}


def _node_result() -> dict:
    module_url = JS.as_uri()
    incident = {
        "id": "inc-1",
        "title_station": "<b>Sanayi</b>",
        "multi_station": False,
        "photos_available": True,
        "record_note": None,
        "priority": {
            "level": "medium",
            "by": "operator",
            "suggested_level": "high",
            "reason": "İnsan önceliği yeniden değerlendirdi",
            "at": "2026-09-25T09:00:00Z",
            "actor": "simüle operatör",
        },
        "suggestion": {
            "factors": [
                {
                    "key": "repeat",
                    "values": {
                        "people": 3,
                        "cards": 2,
                        "repeat_code": True,
                        "window_hours": 168,
                        "threshold_people": 3,
                    },
                    "source": "ledger",
                },
                {
                    "key": "waiting",
                    "values": {"hours": 4, "threshold_hours": 4, "over": True},
                    "source": "ledger",
                    "observed_at": "2026-09-25T05:00:00Z",
                },
                {
                    "key": "access",
                    "values": {
                        "equipment_type": "elevator",
                        "status_type": "Arıza",
                        "interchange": True,
                        "line": "M2",
                    },
                    "source": "ibb_record",
                    "observed_at": "2026-09-25T09:00:00Z",
                    "verified": True,
                },
                {
                    "key": "conflict",
                    "values": {"text": "İBB kaydında arıza var"},
                    "source": "ibb_record",
                    "needs_check": True,
                },
            ]
        },
        "members": {
            "reports": [
                {
                    "ref": "report:sig-1",
                    "signal_id": "sig-1",
                    "station": "<b>Sanayi</b>",
                    "kind_text": "asansör kapalıydı",
                    "status": "awaiting_approval",
                    "support": 2,
                    "received_at": "2026-09-25T05:00:00Z",
                }
            ],
            "photos": [
                {
                    "ref": "photo:abcdef123456",
                    "photo_code": "SYNTHETIC1",
                    "station": "Sanayi",
                    "category": "lift",
                    "status": "new",
                    "created_at": "2026-09-25T08:00:00Z",
                    "photo_url": "/api/console/photo-reports/SYNTHETIC1/photo",
                }
            ],
            "equipment": [
                {
                    "ref": "equipment:sig-2",
                    "station": "Sanayi",
                    "equipment_type": "elevator",
                    "status_type": "Arıza",
                    "source": "Metro İstanbul",
                    "observed_at": "2026-09-25T09:00:00Z",
                }
            ],
        },
        "agency": {"name": "Ulaşım", "url": "https://example.invalid"},
        "actions": [
            {
                "id": 7,
                "kind": "split",
                "at": "2026-09-25T09:00:00Z",
                "actor": "simüle operatör",
                "ledger_entry": 20,
                "reason": "Kayıtları ayrı incele",
            }
        ],
    }
    list_data = {
        "items": [
            {
                "id": "inc-1",
                "title_station": "Sanayi",
                "priority": incident["priority"],
                "members": {"reports": 2, "photos": 1, "equipment": 1},
            }
        ]
    }
    detail_data = {"items": [{"id": "inc-1", "title_station": "Sanayi"}]}
    form_data = {
        "items": [
            {"id": "inc-1", "title_station": "Sanayi"},
            {"id": "inc-2", "title_station": "Üsküdar"},
        ]
    }
    citizen = json.loads(json.dumps(incident))
    citizen_access = next(item for item in citizen["suggestion"]["factors"] if item["key"] == "access")
    citizen_access["source"] = "citizen"
    citizen_access["verified"] = False
    program = f"""
globalThis.window = JSON.parse({json.dumps(json.dumps({"location": {"search": "", "origin": "http://127.0.0.1"}}))});
const m = await import({json.dumps(module_url)});
const incident = JSON.parse({json.dumps(json.dumps(incident))});
const citizen = JSON.parse({json.dumps(json.dumps(citizen))});
const listData = JSON.parse({json.dumps(json.dumps(list_data))});
const detailData = JSON.parse({json.dumps(json.dumps(detail_data))});
const formData = JSON.parse({json.dumps(json.dumps(form_data))});
const form = {{kind: 'priority', level: 'normal'}};
const output = {{
  keys: m.I18N_KEYS,
  empty: m.listMarkup({{items: []}}),
  list: m.listMarkup(listData, {{selectedId: 'inc-1'}}),
  detail: m.detailMarkup(incident, {{data: detailData, form: null}}),
  citizenDetail: m.detailMarkup(citizen, {{data: detailData, form: null}}),
  form: m.detailMarkup(incident, {{data: formData, form}}),
  lines: m.factorLines(incident.suggestion),
  badge: m.priorityBadge(incident.priority),
  valid: [
    m.validReason('Kayıtla yeniden karşılaştırıldı'),
    m.validReason('x'),
    m.validReason('operator'+'@example.invalid'),
    m.validReason('0'+'532'+'000'+'00'+'00')
  ]
}};
process.stdout.write(JSON.stringify(output));
"""
    result = subprocess.run(["node", "--input-type=module", "-e", program], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_markup_escapes_and_keeps_sources_and_operator_choice_distinct() -> None:
    result = _node_result()
    assert "olay dosyası yok." in result["empty"]
    assert 'aria-current="true"' in result["list"]
    assert "&lt;b&gt;Sanayi&lt;/b&gt;" in result["detail"] and "<b>Sanayi</b>" not in result["detail"]
    assert "kurum kaydı" in result["detail"] and "vatandaş (doğrulanmamış)" in result["citizenDetail"]
    assert "Operatör kararı: Orta" in result["detail"] and "Öneri: Yüksek" in result["detail"]
    assert "Kayıtla ayrı" not in result["detail"] and "İnsan önceliği yeniden değerlendirdi" in result["detail"]
    assert 'alt="Vatandaşın gönderdiği fotoğraf: lift, Sanayi"' in result["detail"]
    assert "Fotoğraf tek başına kanıt değildir." in result["detail"]
    assert result["detail"].count('class="btn btn-primary"') == 0
    assert result["form"].count('class="btn btn-primary"') == 1
    assert result["badge"]["tone"] == "accent"
    assert result["valid"] == [True, False, False, False]
    assert {line["source"] for line in result["lines"]} == {"ledger", "ibb_record"}


def test_catalogs_match_module_fallbacks_and_have_identical_placeholders() -> None:
    result = _node_result()
    # P00 D2a: each text is a literal t('ui.inc.key', 'Türkçe', v) call now, read from the source.
    source = JS.read_text(encoding="utf-8")
    calls = re.finditer(r"t\('(ui\.inc\.\w+)', ('|\")((?:\\.|(?!\2).)*)\2", source)
    expected = {match.group(1): match.group(3).replace("\\'", "'").replace('\\"', '"') for match in calls}
    assert {f"ui.inc.{key}" for key in result["keys"]} == set(expected)
    assert CATALOG["tr"] == expected
    assert set(CATALOG["tr"]) == set(CATALOG["en"])
    for key in CATALOG["tr"]:
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))
        assert CATALOG["tr"][key]
        assert CATALOG["en"][key]


def test_static_module_is_bounded_safe_and_anchored() -> None:
    source = JS.read_text(encoding="utf-8")
    styles = CSS.read_text(encoding="utf-8")
    console = (REPO_ROOT / "src/nabiz/console/static/console.html").read_text(encoding="utf-8")
    assert len(source.splitlines()) <= 300
    assert len(styles.splitlines()) <= 350
    assert 'id="report-map"' in console
    assert re.search(r"if \(typeof document !== 'undefined'\) mount\(\)", source)
    subprocess.run(["node", "--check", str(JS)], check=True, capture_output=True, text=True)
    assert "setInterval" not in source
    assert not re.search(r"addEventListener\s*\(\s*['\"]scroll", source)
    for forbidden in ("canlı", "doğrulandı", "çözüldü", "ekip gönderildi", "\u2014", "\u2013"):
        assert forbidden not in source.lower()
    assert not re.search(r"#[0-9a-f]{3,8}\b|\b(?:rgb|hsl)a?\s*\(", styles, re.IGNORECASE)
    assert "infinite" not in styles and "is-bad" not in styles
    assert not re.search(r"\b(?:transition|animation)\s*:", styles)
    for path in ("src/nabiz/console/static/sw.js", "src/nabiz/console/static/index.html", "src/nabiz/console/static/kolay.html"):
        assert "console_incidents" not in (REPO_ROOT / path).read_text(encoding="utf-8")
    console = (REPO_ROOT / "src/nabiz/console/static/console.html").read_text(encoding="utf-8")
    assert 'id="report-map"' in console
    checked = subprocess.run(["node", "--check", str(JS)], capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
