"""Static and pure-renderer checks for E52's self-installing citizen module."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, template_literals, ui_calls
from test_static_a11y import STATIC, node_json

JS_DIR = STATIC / "js"
CSS_DIR = STATIC / "css"

_CATALOG_ROWS = [
    ("title", "Aile", "Family"),
    ("retry", "Yeniden dene", "Try again"),
    ("loading", "Aile bilgisi yükleniyor.", "Loading family information."),
    ("copied", "Aile kodu kopyalandı.", "Family code copied."),
    ("copy_failed", "Kopyalanamadı; kodu elle seçip kopyalayın.", "Could not copy. Select and copy the code."),
    (
        "example_band",
        "Örnek aile · örnek hesaplarla çalışır · gerçek İBB ya da e-Devlet aile bağı kurulmaz · "
        "konum paylaşılmaz",
        "Example family. Works with example accounts. No real family link or location is shared.",
    ),
    ("unknown", "bilinmiyor", "unknown"),
    ("example_tag", "Örnek", "Example"),
    (
        "intro",
        "Aile kodu, onayladığınız en çok 5 kişiyle yalnız seçtiğiniz takip konularını ve durakları "
        "paylaşmanızı sağlar. Konum paylaşılmaz.",
        "A family code lets you share only the topics and stops you choose with up to 5 people "
        "you approve. Location is not shared.",
    ),
    ("display_name_label", "Ailede görünecek adınız", "Name shown to family"),
    (
        "display_name_hint",
        "Örnek: Anne, Can. E-posta ya da telefon yazmayın.",
        "Example: Alex, Sam. Do not enter an email or phone number.",
    ),
    ("consent_label", "Açık rıza veriyorum.", "I give my explicit consent."),
    ("consent_version", "metin sürümü", "text version"),
    ("kvkk_link", "Ayrıntı: KVKK", "Details: privacy"),
    (
        "consent_error",
        "Açık rıza vermeden aile kodu oluşturulamaz. Hiçbir şey kaydedilmedi.",
        "Give explicit consent to create a family code. Nothing was saved.",
    ),
    ("create_code", "Aile kodu oluştur", "Create family code"),
    ("join_summary", "Aile koduyla katıl", "Join with a family code"),
    ("join_code_label", "Aile kodu", "Family code"),
    ("join_code_hint", "6 karakter; boşluk ve küçük harf sorun değil.", "6 characters. Spaces and lowercase letters are fine."),
    ("code_format_error", "Kod 6 geçerli harf ya da rakamdan oluşmalı.", "Enter 6 valid letters or digits."),
    (
        "join_consent_error",
        "Açık rıza vermeden katılma isteği gönderilemez. Hiçbir şey kaydedilmedi.",
        "Give explicit consent to send a join request. Nothing was saved.",
    ),
    ("request_join", "Katılma isteği gönder", "Send join request"),
    (
        "demo_hint",
        "Denemek için ikinci bir örnek hesabı başka bir tarayıcıda ya da gizli pencerede açabilirsiniz.",
        "For a demo, open a second example account in another browser or a private window.",
    ),
    ("pending_title", "Katılma isteğiniz bekliyor", "Your join request is pending"),
    ("pending_intro", "Katılma isteğiniz kod sahibinin onayını bekliyor.", "The code owner must approve your request."),
    ("match_number", "Eşleşme sayısı: {check}", "Matching number: {check}"),
    (
        "match_hint",
        "Kod sahibine bu sayıyı söyleyin; ekrandaki sayı aynıysa onaylasın.",
        "Tell the code owner this number. They should approve only if it matches.",
    ),
    (
        "request_date",
        "İstek: {date} · 7 gün içinde onaylanmazsa silinir.",
        "Requested: {date}. Removed if not approved within 7 days.",
    ),
    ("cancel_request", "İsteği geri al", "Cancel request"),
    ("more_requests", "{count} istek daha bekliyor", "{count} more requests are waiting"),
    ("request_title", "Katılma isteği", "Join request"),
    ("match_number_inline", "eşleşme sayısı {check}", "matching number {check}"),
    (
        "request_hint",
        "İsteyen kişiye eşleşme sayısını sorun; aynıysa onaylayın.",
        "Ask the person for the matching number and approve only if it matches.",
    ),
    ("approve", "Onayla", "Approve"),
    ("reject", "Reddet", "Reject"),
    (
        "family_full",
        "Aile dolu (6/6). Yeni üye için birini çıkarın.",
        "Family is full (6/6). Remove a member before adding someone.",
    ),
    ("code_expired", "Kodun süresi doldu.", "The code has expired."),
    ("renew_code", "Kodu yenile", "Renew code"),
    ("expires", "Son geçerlilik: {date}", "Expires: {date}"),
    ("copy_code", "Kodu kopyala", "Copy code"),
    (
        "renew_hint",
        "Yenileyince eski kod geçersiz olur; bekleyen istekler kalır.",
        "Renewing makes the old code invalid. Pending requests stay.",
    ),
    ("code_owner", "kod sahibi", "code owner"),
    ("you", "siz", "you"),
    ("follows_label", "Takip:", "Follows:"),
    ("stops_label", "Duraklar:", "Stops:"),
    ("shares_empty", "Henüz bir şey paylaşmadı.", "Nothing shared yet."),
    ("remove_summary", "Çıkar", "Remove"),
    (
        "remove_warning",
        "{name} aileden çıkarılır; paylaşımları silinir.",
        "{name} will leave the family and their shares will be removed.",
    ),
    ("remove_member", "Aileden çıkar", "Remove from family"),
    ("members_title", "Üyeler ({count}/6)", "Members ({count}/6)"),
    (
        "owner_alone",
        "Henüz üye yok. Kodu paylaşın; gelen istekler burada görünür.",
        "No members yet. Share the code to receive requests.",
    ),
    ("follows_empty", "Takip ettiğiniz konu yok.", "You do not follow any topics yet."),
    ("go_follows", "Takiplerinize gidin", "Go to your follows"),
    ("stops_empty", "Bu cihazda kayıtlı durak yok.", "No stops are saved on this device."),
    ("shares_summary", "Ailemle paylaştıklarım", "What I share with family"),
    ("follows_legend", "Takip ettiğim konular", "Topics I follow"),
    ("stops_legend", "Duraklarım", "My stops"),
    (
        "stop_privacy_hint",
        "Durak adı sık gittiğiniz yeri gösterebilir; yalnız paylaşmak istediklerinizi seçin.",
        "A stop name can reveal places you visit often. Select only what you want to share.",
    ),
    ("save_shares", "Paylaşımı kaydet", "Save sharing choices"),
    ("dissolve_summary", "Aileyi dağıt", "Dissolve family"),
    ("leave_summary", "Aileden ayrıl", "Leave family"),
    (
        "dissolve_warning",
        "Tüm üyeler çıkarılır, paylaşımlar silinir, kodunuz geçersiz olur.",
        "All members and shares are removed, and your code becomes invalid.",
    ),
    (
        "leave_warning",
        "Paylaşımlarınız silinir; yeniden katılmak için yeni istek gerekir.",
        "Your shares are removed. Joining again requires a new request.",
    ),
    ("dissolve", "Aileyi dağıt", "Dissolve family"),
    ("leave", "Ayrıl", "Leave"),
]
CATALOG = {
    "tr": {"ui.family." + key: turkish for key, turkish, _ in _CATALOG_ROWS},
    "en": {"ui.family." + key: english for key, _, english in _CATALOG_ROWS},
}


def _button_tags(markup: str) -> list[str]:
    return re.findall(r"<button\b[^>]*>", markup)


def _primary_count(markup: str) -> int:
    return sum('class="btn btn-primary"' in tag or 'class="btn-primary btn"' in tag for tag in _button_tags(markup))


def _states() -> dict[str, object]:
    member = {
        "id": "membership-1",
        "display_name": "<img src=x>",
        "role": "owner",
        "is_me": True,
        "joined_at": "2026-09-26T12:00:00+00:00",
        "shares": {"follows": [], "stops": []},
    }
    code = {"code": "7KM4TP", "display": "7KM 4TP", "expires_at": "2026-09-27T12:00:00+00:00", "expired": False}
    return {
        "none": {"state": "none", "consent": {"text": "Örnek rıza metni.", "version": "2026-09-26"}},
        "pending": {"state": "pending", "pending": {"check": "482", "requested_at": "2026-09-26T12:00:00+00:00"}},
        "owner": {
            "state": "owner",
            "family": {"count": 1, "limit": 6, "members": [member], "code": code, "requests": []},
            "mine": {"follows": [], "stops": []},
        },
        "owner_request": {
            "state": "owner",
            "family": {
                "count": 1,
                "limit": 6,
                "members": [member],
                "code": {**code, "expired": True},
                "requests": [
                    {
                        "id": "request-1",
                        "display_name": "<img src=x>",
                        "check": "482",
                        "requested_at": "2026-09-26T12:00:00+00:00",
                    }
                ],
            },
            "mine": {"follows": [], "stops": []},
        },
        "owner_expired": {
            "state": "owner",
            "family": {"count": 1, "limit": 6, "members": [member], "code": {**code, "expired": True}, "requests": []},
            "mine": {"follows": [], "stops": []},
        },
        "full": {
            "state": "owner",
            "family": {"count": 6, "limit": 6, "members": [member] * 6, "code": None, "requests": []},
            "mine": {"follows": [], "stops": []},
        },
        "member": {
            "state": "member",
            "family": {
                "count": 2,
                "limit": 6,
                "members": [member, {**member, "id": "membership-2", "role": "member", "is_me": False}],
            },
            "mine": {"follows": [], "stops": []},
        },
    }


def test_every_family_ui_key_has_matching_turkish_fallback_and_catalog_entry() -> None:
    sources = {name: (JS_DIR / name).read_text(encoding="utf-8") for name in ("family.js", "family_view.js")}
    fallbacks = {key: value for source in sources.values() for key, value in ui_calls(source).items()}
    keys = {key for source in sources.values() for _, key in re.findall(r"t\(\s*(['\"])(ui\.family\.[^'\"]+)\1", source)}
    assert keys <= set(fallbacks)
    assert set(fallbacks) == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert all(CATALOG["tr"][key] == fallbacks[key] for key in fallbacks)
    for key in CATALOG["tr"]:
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))


def test_family_view_states_have_one_primary_first_and_escape_names(tmp_path) -> None:
    import_json = json.dumps(CATALOG["en"], ensure_ascii=False)
    fallback_json = json.dumps(CATALOG["tr"], ensure_ascii=False)
    states = json.dumps(_states(), ensure_ascii=False)
    body = (
        "i18n.setCatalogs('en'," + import_json + "," + fallback_json + ");"
        "const states=" + states + ";"
        "const output=Object.fromEntries(Object.entries(states).map(([key,value])=>[key,view.familyMarkup(value)]));"
        "console.log(JSON.stringify({output,alphabet:view.CODE_ALPHABET,"
        "normalized:[view.normalizeCode('7km 4tp'),view.normalizeCode('7KM-4TP'),view.normalizeCode('0OI1LS')],"
        "formatted:view.formatCode('7KM4TP')}));"
    )
    result = node_json(tmp_path, {"i18n": "js/i18n_text.js", "view": "js/family_view.js"}, body)
    views = result["output"]
    assert result["alphabet"] == "23456789ADEFHJKMNPRTY"
    assert result["normalized"] == ["7KM4TP", "7KM4TP", None]
    assert result["formatted"] == "7KM 4TP"
    expected_primary = {"none": 1, "pending": 0, "owner": 1, "owner_request": 1, "owner_expired": 1, "full": 0, "member": 0}
    for state, markup in views.items():
        buttons = _button_tags(markup)
        assert _primary_count(markup) == expected_primary[state], state
        if expected_primary[state]:
            assert "btn-primary" in buttons[0], state
        assert '<span class="tag is-warn">Example</span>' in markup
        assert "Example family." in markup
        assert "btn-danger" not in markup and "live" not in markup.lower()
        assert "—" not in markup and "–" not in markup
    assert "Approve" in views["owner_request"]
    assert "Copy code" not in views["owner_expired"]
    assert "Renew code" in views["owner_expired"]
    assert "7KM 4TP" not in views["full"]
    assert "&lt;img src=x&gt;" in views["member"]
    assert views["none"].count('href="/kvkk.html#kvkk-hesap"') == 2


def test_family_view_is_pure_and_family_js_is_lazy_self_installing() -> None:
    view = (JS_DIR / "family_view.js").read_text(encoding="utf-8")
    module = (JS_DIR / "family.js").read_text(encoding="utf-8")
    assert not re.search(r"\b(document|window|fetch|localStorage|Date\.now|new Date\s*\()", view)
    assert "if (typeof document !== 'undefined')" in module[-900:]
    assert "setInterval" not in module and "localStorage.setItem" not in module
    assert not re.search(r"addEventListener\s*\(\s*['\"]scroll['\"]", module)
    assert not re.search(r"['\"]\/api\/(?!account/family)", module)
    assert "readStore" in module
    assert "nabiz:account-changed" in module and "nabiz:family-changed" in module
    assert "/css/family.css" in module and "#takip" in module
    assert "family" not in (STATIC / "console.html").read_text(encoding="utf-8").lower()
    assert "family" not in (STATIC / "kolay.html").read_text(encoding="utf-8").lower()


def test_family_css_uses_tokens_and_respects_reduced_motion() -> None:
    css = (CSS_DIR / "family.css").read_text(encoding="utf-8")
    selectors = re.findall(r"(?<![\w-])\.([A-Za-z_][\w-]*)", css)
    allowed = {"btn", "btn-primary", "btn-quiet", "btn-row", "check", "status-line", "tag", "is-warn", "sr-only"}
    assert selectors and all(name.startswith("fam-") or name.startswith("field-") or name in allowed for name in selectors)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(", css)
    assert "infinite" not in css
    for prop in ("animation:", "transition:"):
        for match in re.finditer(re.escape(prop), css):
            assert css.rfind("@media (prefers-reduced-motion: no-preference)", 0, match.start()) >= 0
    assert "flex-wrap: wrap" in css and "overflow-wrap: anywhere" in css


def test_family_fallbacks_hold_all_turkish_copy_and_use_no_forbidden_dashes() -> None:
    for name in ("family.js", "family_view.js"):
        source = (JS_DIR / name).read_text(encoding="utf-8")
        clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
        fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
        literal_source = list(clean)
        for start, end, chunks in template_literals(clean):
            for chunk in chunks:
                assert not TURKISH_CHARS.search(chunk), (name, chunk)
            literal_source[start:end] = [" "] * (end - start)
        for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", "".join(literal_source), re.S):
            group = next(index for index, part in enumerate(match.groups(), start=1) if part is not None)
            value = match.group(group)
            if TURKISH_CHARS.search(value):
                start, end = match.span(group)
                assert any(left <= start and end <= right for left, right in fallback_spans), (name, value)
        assert "—" not in source and "–" not in source and "canlı" not in source.lower()
    for lang in ("tr", "en"):  # P00 G5: the keys moved into the page catalogues, unchanged
        surface = json.loads((STATIC / "i18n" / f"{lang}.json").read_text(encoding="utf-8"))
        assert all(surface[k] == v for k, v in CATALOG[lang].items())


def test_family_modules_parse_when_node_is_available(tmp_path) -> None:
    node = shutil.which("node")
    if node is None:
        return
    for name in ("family.js", "family_view.js"):
        result = subprocess.run([node, "--check", str(JS_DIR / name)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stderr
