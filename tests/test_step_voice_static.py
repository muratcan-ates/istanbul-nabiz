"""Pure-core and static accessibility checks for the self-mounting route voice module."""

from __future__ import annotations

import json
import re
from pathlib import Path

from test_i18n_surfaces import TURKISH_CHARS, UI_CALL, template_literals, ui_calls
from test_static_a11y import STATIC, node_json

CORE = STATIC / "js" / "step_voice_core.js"
MODULE = STATIC / "js" / "step_voice.js"
CSS = STATIC / "css" / "step_voice.css"
CATALOG = {
    "tr": {
        "ui.steps.offer": "Buraya adım adım yön tarifi ister misiniz?",
        "ui.steps.toLabel": "Varış: {place}",
        "ui.steps.title": "Adım adım rota",
        "ui.steps.close": "Kapat",
        "ui.steps.from": "Nereden?",
        "ui.steps.to": "Nereye?",
        "ui.steps.getSteps": "Adımları getir",
        "ui.steps.loading": "Adımlar hazırlanıyor.",
        "ui.steps.unavailable": "Bu rota doğrulanamadı.",
        "ui.steps.error": "Adımlar alınamadı.",
        "ui.steps.tryAnother": "Başka bir yer deneyin",
        "ui.steps.emptyPlaces": "İki yeri de yazın.",
        "ui.steps.noVoice": "Bu tarayıcıda {lang} ses yok; adımları ekrandan okuyabilirsiniz.",
        "ui.steps.languageTr": "Türkçe",
        "ui.steps.languageEn": "English",
        "ui.steps.onlineVoice": (
            "Bu ses çevrim içi; okunan metin tarayıcının ses sağlayıcısına gidebilir. "
            "Nabız sunucusuna gitmez."
        ),
        "ui.steps.readAloud": "Sesli oku",
        "ui.steps.readAgain": "Tekrar oku",
        "ui.steps.stopReading": "Sesi kapat",
        "ui.steps.scope": "İstasyon içi ve kayıtlı rota adımları; sokak navigasyonu değildir.",
        "ui.steps.source": "Kaynak",
        "ui.steps.sourceName": "İBB Açık Veri Portalı",
        "ui.steps.sample": "Örnek",
        "ui.steps.sampleRoute": "Örnek rota: {route}",
        "ui.steps.official": "Resmî İBB hizmeti değildir.",
        "ui.steps.next": "Sonraki adım",
        "ui.steps.finish": "Bitir",
        "ui.steps.previous": "Önceki adım",
        "ui.steps.stopsBetween": "Aradaki duraklar ({count})",
        "ui.steps.stepPosition": "Adım {n} / {total}",
        "ui.steps.stepTitle": "Adım {n}: {title}",
        "ui.steps.minutes": "yaklaşık {count} dk",
        "ui.steps.allSteps": "Tüm adımlar",
        "ui.steps.journeyLaunch": "Adım adım ve sesli",
        "ui.steps.mapOpen": "Harita uygulamasında aç",
        "ui.steps.mapNotice": "Sokak yolunu harita uygulamanız çizer; Nabız çizmez.",
    },
    "en": {
        "ui.steps.offer": "Would you like step-by-step directions here?",
        "ui.steps.toLabel": "To: {place}",
        "ui.steps.title": "Step-by-step route",
        "ui.steps.close": "Close",
        "ui.steps.from": "From",
        "ui.steps.to": "To",
        "ui.steps.getSteps": "Get the steps",
        "ui.steps.loading": "Preparing steps.",
        "ui.steps.unavailable": "This route could not be verified.",
        "ui.steps.error": "Steps could not be retrieved.",
        "ui.steps.tryAnother": "Try another place",
        "ui.steps.emptyPlaces": "Enter both places.",
        "ui.steps.noVoice": "This browser has no {lang} voice; you can read the steps on screen.",
        "ui.steps.languageTr": "Turkish",
        "ui.steps.languageEn": "English",
        "ui.steps.onlineVoice": (
            "This voice is online; the spoken text may go to the browser's speech provider. "
            "It does not go to Nabız's server."
        ),
        "ui.steps.readAloud": "Read aloud",
        "ui.steps.readAgain": "Read again",
        "ui.steps.stopReading": "Stop reading",
        "ui.steps.scope": "Station and recorded route steps; not street navigation.",
        "ui.steps.source": "Source",
        "ui.steps.sourceName": "İBB Open Data Portal",
        "ui.steps.sample": "Sample",
        "ui.steps.sampleRoute": "Sample route: {route}",
        "ui.steps.official": "Not an official İBB service.",
        "ui.steps.next": "Next step",
        "ui.steps.finish": "Finish",
        "ui.steps.previous": "Previous step",
        "ui.steps.stopsBetween": "Stops in between ({count})",
        "ui.steps.stepPosition": "Step {n} of {total}",
        "ui.steps.stepTitle": "Step {n}: {title}",
        "ui.steps.minutes": "about {count} min",
        "ui.steps.allSteps": "All steps",
        "ui.steps.journeyLaunch": "Step-by-step with audio",
        "ui.steps.mapOpen": "Open in a map app",
        "ui.steps.mapNotice": "Your map app draws the street route; Nabız does not.",
    },
}


def test_route_hint_recognises_only_supported_route_contexts(tmp_path: Path) -> None:
    values = node_json(
        tmp_path,
        {"core": "js/step_voice_core.js"},
        "const cases=["
        "core.routeHint({question:\"Kadıköy'den Levent'e nasıl giderim?\"}),"
        "core.routeHint({question:\"Zeytinburnu’ndan Bağcılar’a adımsız nasıl giderim?\"}),"
        "core.routeHint({question:\"Ayrılık Çeşmesi'nden 4. Levent'e yol tarifi\"}),"
        "core.routeHint({question:\"Levent'e nasıl gidilir?\"}),"
        "core.routeHint({question:\"Taksim istasyonunda asansör çalışıyor mu?\",tools:['metro_equipment_status']}),"
        "core.routeHint({question:'How do I get from Kadıköy to Levent?',lang:'en'}),"
        "core.routeHint({question:\"Bugün Taksim'e nasıl giderim?\"}),"
        "core.routeHint({question:\"M2'de arıza var mı?\",tools:['metro_status']}),"
        "core.routeHint({question:\"Kadıköy'de otopark var mı?\"}),"
        "core.routeHint({question:'Merhaba'}),"
        "core.routeHint({question:\"Kadıköy'den Levent'e nasıl giderim?\",emergency:true}),"
        "core.routeHint({question:\"Kadıköy'den Levent'e nasıl giderim?\",refused:true})];"
        "console.log(JSON.stringify(cases));",
    )
    assert values == [
        {"from": "Kadıköy", "to": "Levent"},
        {"from": "Zeytinburnu", "to": "Bağcılar"},
        {"from": "Ayrılık Çeşmesi", "to": "4. Levent"},
        {"from": None, "to": "Levent"},
        {"from": None, "to": "Taksim"},
        {"from": "Kadıköy", "to": "Levent"},
        {"from": None, "to": "Taksim"},
        None, None, None, None, None,
    ]


def test_voice_selection_speech_generation_and_step_bounds(tmp_path: Path) -> None:
    values = node_json(
        tmp_path,
        {"core": "js/step_voice_core.js"},
        "const voices=[{lang:'tr-TR',localService:false},{lang:'tr-TR',localService:true},"
        "{lang:'en-US',localService:false},{lang:'fr-FR',localService:true}];"
        "class Utterance{text;constructor(text){this.text=text;}}"
        "const calls=[];const spoken=[];"
        "const synth={cancel(){calls.push('cancel');},speak(u){calls.push('speak');spoken.push(u);}};"
        "const speaker=core.createSpeaker({synth,Utterance});const idle=speaker.speaking;"
        "speaker.say('first',voices[2],'en');speaker.say('second',voices[2],'en');spoken[0].onend();"
        "const afterOldEnd=speaker.speaking;const lang=spoken[1].lang;speaker.stop();"
        "console.log(JSON.stringify({idle,afterOldEnd,lang,calls,picked:[core.pickVoiceFor(voices,'tr')===voices[1],"
        "core.pickVoiceFor(voices,'en')===voices[2],core.pickVoiceFor(voices,'ar')],notes:[core.voiceNote(voices[1]),"
        "core.voiceNote(voices[2]),core.voiceNote(null)],positions:[core.stepPosition(-2,4),core.stepPosition(9,4),core.stepPosition(0,0)]}));",
    )
    assert values["idle"] is False and values["afterOldEnd"] is True
    assert values["lang"] == "en-US" and values["calls"] == ["cancel", "speak", "cancel", "speak", "cancel"]
    assert values["picked"] == [True, True, None]
    assert values["notes"] == ["none", "online", None]
    assert values["positions"] == [
        {"index": 0, "n": 1, "total": 4, "first": True, "last": False},
        {"index": 3, "n": 4, "total": 4, "first": False, "last": True},
        {"index": 0, "n": 0, "total": 0, "first": True, "last": True},
    ]


def test_core_and_dom_module_have_no_persistence_or_gps_and_mount_safely() -> None:
    core = CORE.read_text(encoding="utf-8")
    module = MODULE.read_text(encoding="utf-8")
    assert not re.search(r"\b(document|window|navigator|localStorage|sessionStorage|indexedDB|fetch|geolocation)\b", core)
    for source in (core, module):
        assert not re.search(r"\b(geolocation|localStorage|sessionStorage|indexedDB|setInterval|autoplay)\b", source)
    assert "speechSynthesis.speak" not in module
    assert 'href="/css/step_voice.css"' in module or "'/css/step_voice.css'" in module
    assert re.search(
        r"if \(typeof document !== 'undefined'\) mountStepVoice\(document\.querySelector\('#chat-log'\)\);\s*$",
        module,
    )


def test_css_guards_motion_transparency_contrast_and_external_links() -> None:
    css = CSS.read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: no-preference)" in css
    assert ':root:not([data-motion="reduce"]):not([data-simple="on"])' in css
    assert "infinite" not in css
    assert "forced-colors: active" in css and "CanvasText" in css
    assert "prefers-reduced-transparency: reduce" in css and "prefers-contrast: more" in css
    assert "backdrop-filter" not in css
    assert "color-mix(in srgb, var(--text) 42%, transparent)" in css
    assert re.search(r"\.sv-sheet[\s\S]*?max-height: 90dvh", css)
    assert "@media (max-width: 767px)" in css and "grid-template-columns: minmax(0, 1fr)" in css
    motion = css[css.index("@media (prefers-reduced-motion: no-preference)"):]
    assert "animation:" in motion and "transition:" in motion
    assert not re.search(r"(?m)^\s*order\s*:", css)


def test_catalog_matches_ui_fallbacks_and_english_is_complete(tmp_path: Path) -> None:
    source = MODULE.read_text(encoding="utf-8")
    calls = ui_calls(source)
    assert set(calls) == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert calls == CATALOG["tr"]
    def placeholders(value: str) -> list[str]:
        return sorted(re.findall(r"\{(\w+)\}", value))

    for key in CATALOG["tr"]:
        assert placeholders(CATALOG["tr"][key]) == placeholders(CATALOG["en"][key])
        assert CATALOG["tr"][key] and CATALOG["en"][key]
        assert not any(mark in CATALOG["tr"][key] + CATALOG["en"][key] for mark in ("\u2014", "\u2013", "canlı", "live", "ETA"))
    values = node_json(
        tmp_path,
        {"i18n": "js/i18n_text.js"},
        f"const catalog={json.dumps(CATALOG['en'], ensure_ascii=False)};"
        f"const tr={json.dumps(CATALOG['tr'], ensure_ascii=False)};"
        "i18n.setCatalogs('en',catalog,tr);console.log(JSON.stringify(Object.keys(catalog).map(k=>i18n.t(k,tr[k]))));",
    )
    assert values == list(CATALOG["en"].values())
    for language in ("tr", "en"):
        surface = json.loads((STATIC / "i18n" / f"{language}.json").read_text(encoding="utf-8"))
        assert all(surface[k] == v for k, v in CATALOG[language].items())  # P00 G3: moved into the page catalogues


def test_step_voice_ui_copy_has_no_bare_turkish_literals() -> None:
    source = MODULE.read_text(encoding="utf-8")
    clean = re.sub(r"/\*.*?\*/|^\s*//.*$", "", source, flags=re.S | re.M)
    fallback_spans = [match.span(4) for match in UI_CALL.finditer(clean)]
    literal_source = list(clean)
    for start, end, chunks in template_literals(clean):
        for chunk in chunks:
            assert not TURKISH_CHARS.search(chunk), chunk
        literal_source[start:end] = [" "] * (end - start)
    clean_literals = "".join(literal_source)
    for match in re.finditer(r"'((?:\\.|[^'\\])*)'|\"((?:\\.|[^\"\\])*)\"", clean_literals, re.S):
        value = next(part for part in match.groups() if part is not None)
        start, end = match.span(1 if match.group(1) is not None else 2)
        if TURKISH_CHARS.search(value):
            assert any(left <= start and end <= right for left, right in fallback_spans), value
