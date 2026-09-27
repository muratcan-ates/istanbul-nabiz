"""Browser module contracts, bilingual fallbacks, and the self-installing surface rules."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/nabiz/console/static"
MODULE = STATIC / "js/journey_watch.js"
STYLE = STATIC / "css/journey_watch.css"

CATALOG = {
    "tr": {
        "ui.jw.unknown_time": "zaman bilinmiyor",
        "ui.jw.recorded_at": "kayıtlı · {when}",
        "ui.jw.step_free": "Adımsız yol",
        "ui.jw.slow_walk": "Az yürüme",
        "ui.jw.section_title": "Kayıtlı yolculuklarım",
        "ui.jw.section_note": "Yalnız bu cihazda, isteğe bağlı.",
        "ui.jw.start": "Başlangıç",
        "ui.jw.destination": "Varış",
        "ui.jw.time": "Saat (isteğe bağlı)",
        "ui.jw.needs_legend": "Yolculuk tercihleriniz",
        "ui.jw.consent": "Anladım, bu yolculuğu bu cihazda saklamak istiyorum.",
        "ui.jw.consent_hint": (
            "Sunucuya yalnız kontrol anında başlangıç, varış ve kısıt gider; orada saklanmaz. "
            "Kimlik, konum ya da sağlık bilgisi istenmez."
        ),
        "ui.jw.account_consent": "Hesabımda saklanmasını ve belirtilen toplu kullanımı ayrı açık rızayla kabul ediyorum.",
        "ui.jw.account_hint": (
            "Açık rızamla kayıtlı yolculuklarımın başlangıç, varış, saat ve kısıt bilgilerinin hesabıma bağlı olarak "
            "saklanmasını kabul ediyorum. İstediğim an silebilirim; 90 gün kullanılmazsa silinir. "
            "Yolculuklar adınız ve cihazınız olmadan yalnız toplam sayı olarak İBB operatörünün "
            "etki senaryolarında kullanılabilir."
        ),
        "ui.jw.storage_unavailable": "Bu tarayıcı kayıt tutamıyor. Bu bölümde yolculuk saklanamaz.",
        "ui.jw.save": "Kaydet",
        "ui.jw.check": "Şimdi kontrol et",
        "ui.jw.list_title": "Yolculuklarınız",
        "ui.jw.status_affected": "Etkileniyor",
        "ui.jw.status_unverified": "Doğrulanamadı",
        "ui.jw.status_clear": "Etkileyen kayıt yok",
        "ui.jw.status_waiting": "Henüz kontrol edilmedi",
        "ui.jw.remove": "Sil",
        "ui.jw.to": "ile",
        "ui.jw.empty": "Henüz kayıtlı yolculuk yok.",
        "ui.jw.card_affected": "Kayıtlı yolculuğunuz etkileniyor: {trip}.",
        "ui.jw.card_unverified": "Kayıtlı yolculuğunuz doğrulanamadı: {trip}.",
        "ui.jw.affected_need": "Etkilenen tercih: {need}",
        "ui.jw.source": "Kaynak",
        "ui.jw.unverified_detail": "Kaynak şu an doğrulanamadı; yola çıkmadan önce yeniden kontrol edin.",
        "ui.jw.new": "Yeni",
        "ui.jw.extra_minutes": "yaklaşık {minutes} dk ek",
        "ui.jw.alternative_text": "Önerilen: {station} ({line}), {extra}",
        "ui.jw.approved_badge": "Simüle operatör onayladı",
        "ui.jw.select_alternative": "Alternatifi seç",
        "ui.jw.later": "Şimdilik değil",
        "ui.jw.selected": "Alternatifi seçtiniz: {station}. Durum değişirse yeniden sorarız.",
        "ui.jw.deferred": "Şimdilik yeniden karar vermediniz. Durum değişirse kartı gösteririz.",
        "ui.jw.open_alternative": "Adımsız yol bölümüne git",
        "ui.jw.more": "Ayrıntı",
        "ui.jw.more_journeys": "+{count} yolculuk daha",
        "ui.jw.mock_unavailable": "Örnek modda yolculuk kontrolü yapılmaz.",
        "ui.jw.checked": "Yolculuk kayıtları kontrol edildi.",
        "ui.jw.check_error": "Kontrol tamamlanamadı. Yeniden deneyin.",
        "ui.jw.consent_required": "Kaydetmeden önce bu cihazda saklamaya izin verdiğinizi işaretleyin.",
        "ui.jw.invalid_form": "Başlangıç, varış ve yolculuk tercihlerinizi kontrol edin.",
        "ui.jw.device_limit": "Bu cihazda en çok 3 yolculuk saklayabilirsiniz.",
        "ui.jw.account_load_error": "Hesap yolculukları yüklenemedi.",
        "ui.jw.account_save_error": "Hesap yolculuğu saklanamadı.",
        "ui.jw.account_delete_error": "Hesap yolculuğu silinemedi.",
        "ui.jw.slow_walk_detour": (
            "Planlayıcı asansör durumuna göre {station} istasyonunu atladı; yolculuk yaklaşık {minutes} dk uzadı."
        ),
        "ui.jw.save_current": "Bu yolculuğu kaydet",
    },
    "en": {
        "ui.jw.unknown_time": "time unavailable",
        "ui.jw.recorded_at": "recorded · {when}",
        "ui.jw.step_free": "Step-free route",
        "ui.jw.slow_walk": "Less walking",
        "ui.jw.section_title": "My saved journeys",
        "ui.jw.section_note": "Optional, on this device only.",
        "ui.jw.start": "Starting point",
        "ui.jw.destination": "Destination",
        "ui.jw.time": "Time (optional)",
        "ui.jw.needs_legend": "Journey preferences",
        "ui.jw.consent": "I understand and want to save this journey on this device.",
        "ui.jw.consent_hint": (
            "Only the starting point, destination, and preference are sent for a check; they are not stored there. "
            "No identity, location coordinates, or health information is requested."
        ),
        "ui.jw.account_consent": "I separately consent to account storage and the aggregate use described below.",
        "ui.jw.account_hint": (
            "I consent to storing my saved journey's starting point, destination, time, and preference with my account. "
            "I can delete it at any time; it is deleted after 90 days without use. Journeys may be used only as aggregate "
            "counts, without my name or device, in operator impact scenarios."
        ),
        "ui.jw.storage_unavailable": "This browser cannot save data. Journeys cannot be saved in this section.",
        "ui.jw.save": "Save",
        "ui.jw.check": "Check now",
        "ui.jw.list_title": "Your journeys",
        "ui.jw.status_affected": "Affected",
        "ui.jw.status_unverified": "Unverified",
        "ui.jw.status_clear": "No matching record",
        "ui.jw.status_waiting": "Not checked yet",
        "ui.jw.remove": "Delete",
        "ui.jw.to": "to",
        "ui.jw.empty": "No saved journeys yet.",
        "ui.jw.card_affected": "Your saved journey is affected: {trip}.",
        "ui.jw.card_unverified": "Your saved journey could not be verified: {trip}.",
        "ui.jw.affected_need": "Affected preference: {need}",
        "ui.jw.source": "Source",
        "ui.jw.unverified_detail": "The source could not be verified. Check again before you travel.",
        "ui.jw.new": "New",
        "ui.jw.extra_minutes": "about {minutes} min extra",
        "ui.jw.alternative_text": "Suggested: {station} ({line}), {extra}",
        "ui.jw.approved_badge": "Simulated operator approved",
        "ui.jw.select_alternative": "Choose alternative",
        "ui.jw.later": "Not now",
        "ui.jw.selected": "You chose {station}. We will ask again if the status changes.",
        "ui.jw.deferred": "You chose to decide later. We will show the card if the status changes.",
        "ui.jw.open_alternative": "Go to the step-free journey section",
        "ui.jw.more": "Details",
        "ui.jw.more_journeys": "+{count} more journeys",
        "ui.jw.mock_unavailable": "Journey checks are unavailable in example mode.",
        "ui.jw.checked": "Saved journeys checked.",
        "ui.jw.check_error": "The check could not be completed. Try again.",
        "ui.jw.consent_required": "Confirm device storage before saving.",
        "ui.jw.invalid_form": "Check the starting point, destination, and preferences.",
        "ui.jw.device_limit": "You can save up to 3 journeys on this device.",
        "ui.jw.account_load_error": "Account journeys could not be loaded.",
        "ui.jw.account_save_error": "The account journey could not be saved.",
        "ui.jw.account_delete_error": "The account journey could not be deleted.",
        "ui.jw.slow_walk_detour": (
            "The planner skipped {station} based on lift status; the journey takes about {minutes} min longer."
        ),
        "ui.jw.save_current": "Save this journey",
    },
}

REQUIRED_KEYS = {
    "ui.jw.unknown_time",
    "ui.jw.recorded_at",
    "ui.jw.step_free",
    "ui.jw.slow_walk",
    "ui.jw.section_title",
    "ui.jw.section_note",
    "ui.jw.start",
    "ui.jw.destination",
    "ui.jw.time",
    "ui.jw.needs_legend",
    "ui.jw.consent",
    "ui.jw.consent_hint",
    "ui.jw.account_consent",
    "ui.jw.account_hint",
    "ui.jw.storage_unavailable",
    "ui.jw.save",
    "ui.jw.check",
    "ui.jw.list_title",
    "ui.jw.status_affected",
    "ui.jw.status_unverified",
    "ui.jw.status_clear",
    "ui.jw.status_waiting",
    "ui.jw.remove",
    "ui.jw.to",
    "ui.jw.empty",
    "ui.jw.card_affected",
    "ui.jw.card_unverified",
    "ui.jw.affected_need",
    "ui.jw.source",
    "ui.jw.unverified_detail",
    "ui.jw.new",
    "ui.jw.extra_minutes",
    "ui.jw.alternative_text",
    "ui.jw.approved_badge",
    "ui.jw.select_alternative",
    "ui.jw.later",
    "ui.jw.selected",
    "ui.jw.deferred",
    "ui.jw.open_alternative",
    "ui.jw.more",
    "ui.jw.more_journeys",
    "ui.jw.mock_unavailable",
    "ui.jw.checked",
    "ui.jw.check_error",
    "ui.jw.consent_required",
    "ui.jw.invalid_form",
    "ui.jw.device_limit",
    "ui.jw.account_load_error",
    "ui.jw.account_save_error",
    "ui.jw.account_delete_error",
    "ui.jw.slow_walk_detour",
    "ui.jw.save_current",
}


def test_catalog_pairs_have_identical_keys_and_placeholders() -> None:
    assert set(CATALOG["tr"]) == set(CATALOG["en"]) == REQUIRED_KEYS
    for key, turkish in CATALOG["tr"].items():
        english = CATALOG["en"][key]
        assert set(re.findall(r"\{(\w+)\}", turkish)) == set(re.findall(r"\{(\w+)\}", english)), key


def test_module_fallbacks_match_catalog_and_every_icon_exists() -> None:
    source = MODULE.read_text(encoding="utf-8")
    pairs = re.findall(r"fallback\('([a-z_]+)'\s*,\s*'([^']*)'", source)
    for short_key, value in pairs:
        assert CATALOG["tr"][f"ui.jw.{short_key}"] == value
    icons = re.findall(r"icon\('([a-z0-9-]+)'\)", source)
    sprite = (STATIC / "icons.svg").read_text(encoding="utf-8")
    assert icons and all(f'id="i-{name}"' in sprite for name in icons)


def test_browser_exports_work_without_a_document_and_bad_storage_is_empty() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    module_url = MODULE.resolve().as_uri()
    script = f"""
      globalThis.window = {{ location: {{ search: '' }} }};
      delete globalThis.document;
      const m = await import({json.dumps(module_url)});
      const broken = {{ getItem: () => '{{broken', setItem: () => {{ throw new Error('blocked'); }} }};
      const memory = new Map();
      const storage = {{ getItem: (key) => memory.get(key) || null, setItem: (key, value) => memory.set(key, value) }};
      const saved = {{ consent_at: 'now', journeys: [{{ id: 'j1', from: 'Kadıköy', to: 'Levent',
        needs: ['step_free'] }}], last: {{}}, choice: {{}} }};
      m.writeSaved(storage, saved);
      console.log(JSON.stringify({{
        clean: m.cleanJourney({{ id: 'j1', from: '  Kadıköy ', to: 'Levent', needs: ['step_free'] }}),
        corrupt: m.readSaved(broken), roundTrip: m.readSaved(storage).journeys.length,
        writeBlocked: m.writeSaved(broken, saved),
        hidden: m.shouldShowOnHome({{ level: 'clear' }}), shown: m.shouldShowOnHome({{ level: 'affected' }}),
        newCard: m.cardModel({{ level: 'affected', comparable: true,
          fingerprint: ['notice:m7:x'] }}, null, ['notice:m2:y']).isNew,
        newFromClear: m.cardModel({{ level: 'affected', comparable: true, fingerprint: ['notice:m7:x'] }}, null, []).isNew,
        firstCheck: m.cardModel({{ level: 'affected', comparable: true, fingerprint: ['notice:m7:x'] }}, null, null).isNew
      }}));
    """
    proc = subprocess.run(
        [node, "--experimental-default-type=module", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["clean"] == {"id": "j1", "from": "Kadıköy", "to": "Levent", "time": None, "needs": ["step_free"]}
    assert result["corrupt"] == [] and result["roundTrip"] == 1 and result["writeBlocked"] is False
    assert result["hidden"] is False and result["shown"] is True and result["newCard"] is True
    assert result["newFromClear"] is True and result["firstCheck"] is False


def test_static_rules_hold_for_motion_privacy_and_self_installation() -> None:
    source = MODULE.read_text(encoding="utf-8")
    style = STYLE.read_text(encoding="utf-8")
    assert "typeof document !== 'undefined'" in source
    assert "setInterval" not in source and not re.search(r"addEventListener\(['\"]scroll", source)
    assert "infinite" not in style
    assert not re.search(r"#[0-9a-fA-F]{3,8}|rgba?\s*\(", style)
    no_preference = style[style.index("@media (prefers-reduced-motion: no-preference)") :]
    assert "animation: jw-enter" in no_preference
    assert "@media (prefers-reduced-motion: reduce)" in style and "animation: none" in style
    assert 'aria-live="polite"' in source and "aria-busy" in source
    assert 'rel="noopener noreferrer"' in source
    assert "const STORAGE_KEY = 'nabiz.journey-watch.v1'" in source
    assert "'/css/journey_watch.css'" in source
    assert "index.html" not in source
    assert "#journey-section #journey-result" in source
    assert "observer.observe(main, { childList: true, subtree: true })" in source
    assert "#journey-from" in source and "#journey-to" in source
