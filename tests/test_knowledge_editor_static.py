"""DOM-free rendering, translation, accessibility and size checks for E74."""

from __future__ import annotations

import json
import re
import subprocess

from conftest import REPO_ROOT

JS_PATH = REPO_ROOT / "src/nabiz/console/static/js/console_knowledge_editor.js"
CSS_PATH = REPO_ROOT / "src/nabiz/console/static/css/console_knowledge_editor.css"
CATALOG = {
    "tr": {
        "ui.ked.active_version": "dizinde etkin",
        "ui.ked.approve": "Onayla",
        "ui.ked.cancel": "Vazgeç",
        "ui.ked.candidate_not_indexed": "Bu sayfa dizinde yok; dizine alındıktan sonra aynı deneme yeniden koşulur.",
        "ui.ked.candidate_rank": "Aday sırası",
        "ui.ked.candidates": "Kaynak adayları",
        "ui.ked.character_count": "{count} / 280",
        "ui.ked.check_fail": "geçmedi",
        "ui.ked.check_pass": "geçti",
        "ui.ked.check_unknown": "bilinmiyor",
        "ui.ked.confirm_approve": "Onayı kaydet",
        "ui.ked.confirm_reject": "Red kararını kaydet",
        "ui.ked.confirm_undo": "Geri almayı kaydet",
        "ui.ked.content_changed": "içerik değişti",
        "ui.ked.event_approved": "Onaylandı",
        "ui.ked.event_proposed": "Önerildi",
        "ui.ked.event_rejected": "Reddedildi",
        "ui.ked.event_tried": "Denendi",
        "ui.ked.event_undone": "Geri alındı",
        "ui.ked.feedback_line": (
            "Bu oturumda: {down} olumsuz oy · {stale} eski bilgi · "
            "{wrong} yanlış yönlendirme · soruya bağlı değildir"
        ),
        "ui.ked.first_source": "İlk kaynak",
        "ui.ked.gold_sources": "Altın kaynaklar",
        "ui.ked.history": "Geçmiş",
        "ui.ked.in_index": "dizinde var",
        "ui.ked.index_line": "Dizin: {documents} belge · kuruldu {time}",
        "ui.ked.index_missing": "Dizin kurulmadı.",
        "ui.ked.last_scan": "Son ölçüm {time} · {documents} belge",
        "ui.ked.ledger_line": "defter satırı {id}",
        "ui.ked.linked_count": "{count} bağlı aday",
        "ui.ked.linked_questions": "Bağlanacak sorular",
        "ui.ked.measuring": "Ölçülüyor",
        "ui.ked.mode": "Cevap modu",
        "ui.ked.mode_label": "Cevap modu: {mode} · kanıt: {level}",
        "ui.ked.no_candidates": "Henüz kaynak adayı yok.",
        "ui.ked.no_gaps": "Cevaplanamayan soru yok.",
        "ui.ked.no_source": "kaynak yok",
        "ui.ked.not_available": "bilinmiyor",
        "ui.ked.not_in_index": "dizinde yok",
        "ui.ked.not_top_eight": "ilk 8 içinde yok",
        "ui.ked.note_label": "Kısa not · 5-280 karakter",
        "ui.ked.old_version": "önceki sürüm",
        "ui.ked.open_candidate": "Adayı aç",
        "ui.ked.operator_tag": "Operatör etiketi",
        "ui.ked.page_not_in_index": "Bu sayfa dizinde yok.",
        "ui.ked.privacy_note": (
            "Sohbet soruları sunucuda saklanmaz; bu liste yalnızca operatöre aktarılan talepler "
            "ve değerlendirme sorularından oluşur."
        ),
        "ui.ked.propose": "Aday öner",
        "ui.ked.propose_source": "Kaynak aday öner",
        "ui.ked.propose_title": "Kaynak aday öner",
        "ui.ked.question": "Soru",
        "ui.ked.question_count": "{count} soru",
        "ui.ked.reason_label": "Neden etiketi",
        "ui.ked.reason_required": "Gerekçe · 5-280 karakter",
        "ui.ked.reject": "Reddet",
        "ui.ked.request_error": "İstek tamamlanamadı.",
        "ui.ked.request_retention": "30 gün saklanır",
        "ui.ked.required_refusal_note": "Doğru reddedilmiş sorular açık sayılmaz.",
        "ui.ked.required_refusals": "Gerekli ret: {count}",
        "ui.ked.saved": "Kaydedildi",
        "ui.ked.scan": "Değerlendirme sorularını ölç",
        "ui.ked.scan_first": "Değerlendirme sorularını görmek için ölçün.",
        "ui.ked.scan_never": "Değerlendirme soruları henüz ölçülmedi.",
        "ui.ked.select_gap": "Bir soru seçin.",
        "ui.ked.source_eval": "Değerlendirme sorusu",
        "ui.ked.source_request": "Operatöre aktarılan talep · maskeli",
        "ui.ked.stale_fetched": "Sayfanın güncelleme tarihi bilinmiyor; bu tarih dizine alındığı gün.",
        "ui.ked.stale_hint": "Kaynak eski olabilir.",
        "ui.ked.status_approved": "Onaylandı · dizine alınmayı bekliyor",
        "ui.ked.status_proposed": "Önerildi",
        "ui.ked.status_rejected": "Reddedildi",
        "ui.ked.status_tried": "Denendi",
        "ui.ked.suggestion": "Öneri",
        "ui.ked.tag_missing": "kaynak yok",
        "ui.ked.tag_not_gap": "açık değil",
        "ui.ked.tag_stale": "eski bilgi",
        "ui.ked.tag_wrong": "yanlış yönlendirme",
        "ui.ked.title": "Bilgi açıkları",
        "ui.ked.today_empty": "Dizin bugün: cevap yok",
        "ui.ked.today_source": "Dizin bugün: {title} · {institution}",
        "ui.ked.trial_diff": (
            "Dizin değişti ({before_documents} → {after_documents} belge): ilk sırada "
            "{before_rank}/{before_questions} → {after_rank}/{after_questions}"
        ),
        "ui.ked.trial_summary": (
            "Bugünkü dizinle: {questions} sorunun {top1} tanesinde aday ilk sırada; "
            "{absent} tanesinde ilk 8 içinde yok."
        ),
        "ui.ked.trial_table": "Bugünkü dizinle deneme sonuçları",
        "ui.ked.try_today": "Bugünkü dizinle dene",
        "ui.ked.undo": "Geri al",
        "ui.ked.undo_reason": "Geri alma gerekçesi · 5-280 karakter",
        "ui.ked.updated_unknown": "sayfa güncelleme tarihi bilinmiyor",
        "ui.ked.url_label": "Kaynak URL",
        "ui.ked.versions": "Sürümler",
    },
    "en": {
        "ui.ked.active_version": "active in index",
        "ui.ked.approve": "Approve",
        "ui.ked.cancel": "Cancel",
        "ui.ked.candidate_not_indexed": "This page is not in the index; run the same trial again after it is indexed.",
        "ui.ked.candidate_rank": "Candidate rank",
        "ui.ked.candidates": "Source candidates",
        "ui.ked.character_count": "{count} / 280",
        "ui.ked.check_fail": "did not pass",
        "ui.ked.check_pass": "passed",
        "ui.ked.check_unknown": "unknown",
        "ui.ked.confirm_approve": "Save approval",
        "ui.ked.confirm_reject": "Save rejection",
        "ui.ked.confirm_undo": "Save undo",
        "ui.ked.content_changed": "content changed",
        "ui.ked.event_approved": "Approved",
        "ui.ked.event_proposed": "Proposed",
        "ui.ked.event_rejected": "Rejected",
        "ui.ked.event_tried": "Trial run",
        "ui.ked.event_undone": "Undone",
        "ui.ked.feedback_line": (
            "This session: {down} negative votes · {stale} outdated · "
            "{wrong} misrouted · not linked to a question"
        ),
        "ui.ked.first_source": "First source",
        "ui.ked.gold_sources": "Reference sources",
        "ui.ked.history": "History",
        "ui.ked.in_index": "in index",
        "ui.ked.index_line": "Index: {documents} pages · built {time}",
        "ui.ked.index_missing": "Index is not built.",
        "ui.ked.last_scan": "Last scan {time} · {documents} pages",
        "ui.ked.ledger_line": "ledger entry {id}",
        "ui.ked.linked_count": "{count} linked candidates",
        "ui.ked.linked_questions": "Questions to link",
        "ui.ked.measuring": "Measuring",
        "ui.ked.mode": "Answer mode",
        "ui.ked.mode_label": "Answer mode: {mode} · evidence: {level}",
        "ui.ked.no_candidates": "No source candidates yet.",
        "ui.ked.no_gaps": "No unanswered questions.",
        "ui.ked.no_source": "no source",
        "ui.ked.not_available": "unknown",
        "ui.ked.not_in_index": "not in index",
        "ui.ked.not_top_eight": "not in the top 8",
        "ui.ked.note_label": "Short note · 5-280 characters",
        "ui.ked.old_version": "previous version",
        "ui.ked.open_candidate": "Open candidate",
        "ui.ked.operator_tag": "Operator label",
        "ui.ked.page_not_in_index": "This page is not in the index.",
        "ui.ked.privacy_note": (
            "Chat questions are not stored on the server; this list contains only forwarded requests "
            "and evaluation questions."
        ),
        "ui.ked.propose": "Propose candidate",
        "ui.ked.propose_source": "Propose a source candidate",
        "ui.ked.propose_title": "Propose a source candidate",
        "ui.ked.question": "Question",
        "ui.ked.question_count": "{count} questions",
        "ui.ked.reason_label": "Reason label",
        "ui.ked.reason_required": "Reason · 5-280 characters",
        "ui.ked.reject": "Reject",
        "ui.ked.request_error": "The request could not be completed.",
        "ui.ked.request_retention": "kept for 30 days",
        "ui.ked.required_refusal_note": "Correctly refused questions are not counted as gaps.",
        "ui.ked.required_refusals": "Required refusals: {count}",
        "ui.ked.saved": "Saved",
        "ui.ked.scan": "Measure evaluation questions",
        "ui.ked.scan_first": "Measure to see evaluation questions.",
        "ui.ked.scan_never": "Evaluation questions have not been measured yet.",
        "ui.ked.select_gap": "Select a question.",
        "ui.ked.source_eval": "Evaluation question",
        "ui.ked.source_request": "Forwarded operator request · masked",
        "ui.ked.stale_fetched": "The page update date is unknown; this date is when it entered the index.",
        "ui.ked.stale_hint": "The source may be outdated.",
        "ui.ked.status_approved": "Approved · awaiting indexing",
        "ui.ked.status_proposed": "Proposed",
        "ui.ked.status_rejected": "Rejected",
        "ui.ked.status_tried": "Trial run",
        "ui.ked.suggestion": "Suggestion",
        "ui.ked.tag_missing": "no source",
        "ui.ked.tag_not_gap": "not a gap",
        "ui.ked.tag_stale": "outdated information",
        "ui.ked.tag_wrong": "misrouted",
        "ui.ked.title": "Knowledge gaps",
        "ui.ked.today_empty": "Index today: no answer",
        "ui.ked.today_source": "Index today: {title} · {institution}",
        "ui.ked.trial_diff": (
            "Index changed ({before_documents} → {after_documents} pages): ranked first in "
            "{before_rank}/{before_questions} → {after_rank}/{after_questions}"
        ),
        "ui.ked.trial_summary": (
            "With today's index: candidate ranked first in {top1} of {questions} questions; "
            "absent from the top 8 in {absent}."
        ),
        "ui.ked.trial_table": "Trial results with today's index",
        "ui.ked.try_today": "Try with today's index",
        "ui.ked.undo": "Undo",
        "ui.ked.undo_reason": "Undo reason · 5-280 characters",
        "ui.ked.updated_unknown": "page update date unknown",
        "ui.ked.url_label": "Source URL",
        "ui.ked.versions": "Versions",
    },
}


def test_dom_free_rendering_catalog_and_escape() -> None:
    specs = {
        "group": {"category": "Test", "count": 2, "items": [
            {"ref": "eval:kc:x", "kind": "eval", "lang": "tr", "excerpt": "Soru",
             "tag": "missing_source", "tag_by": "suggestion", "candidates": 0},
            {"ref": "eval:kq:y", "kind": "eval", "lang": "tr", "excerpt": "Soru iki",
             "tag": "wrong_route", "tag_by": "operator", "candidates": 0},
        ]},
        "request": {"source": "request", "question": "<b>masked</b>", "lang": "tr", "tag": "missing_source",
                    "tag_by": "suggestion", "gold_urls": [], "measurement": {"mode": "unknown", "level": "weak"}},
        "evaluation": {"source": "eval", "question": "Evaluation question", "lang": "en", "tag": "wrong_route",
                       "tag_by": "operator", "gold_urls": [], "measurement": {"mode": "answer", "level": "sufficient"}},
    }
    script = f"""
      const m = await import({json.dumps(JS_PATH.as_uri())});
      const specs = JSON.parse({json.dumps(json.dumps(specs))});
      const candidate = (status) => ({{
        id: 1, url: 'https://example.gov/page', host: 'example.gov', status, note: 'Reviewed note',
        checks: [], events: [],
        trials: [{{ rows: [{{ ref: 'eval:kc:a', mode: 'answer', candidate_rank: 1 }}],
          summary: {{ questions: 3, top1: 1, in_top_k: 2, not_indexed: false }} }}],
        gap_questions: {{ 'eval:kc:a': {{ question: 'Question text', lang: 'en' }} }},
        diff: {{ before: {{ top1: 0, questions: 3 }}, after: {{ top1: 1, questions: 3 }},
          before_fingerprint: {{ documents: 3 }}, after_fingerprint: {{ documents: 4 }} }},
        versions: [{{ active: true, sha256: 'a1', updated_at_method: 'fetched', fetched_at: '2026-09-27' }},
          {{ active: false, sha256: 'b2', updated_at_method: 'fetched', fetched_at: '2025-09-27' }}]
      }});
      const outputs = {{ empty: m.groupMarkup([]), groups: m.groupMarkup([specs.group], 2),
        request: m.gapMarkup(specs.request), evaluation: m.gapMarkup(specs.evaluation), escaped: m.esc('<b>text</b>&'),
        candidates: ['proposed', 'tried', 'approved', 'rejected'].map((s) => m.candidateMarkup(candidate(s))),
        decisionForm: m.candidateMarkup(candidate('tried'), {{ form: 'approve' }}),
        undoForm: m.candidateMarkup(candidate('approved'), {{ form: 'undo' }}) }};
      console.log(JSON.stringify(outputs));
    """
    result = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    outputs = json.loads(result.stdout)
    js = JS_PATH.read_text(encoding="utf-8")
    keys = set(re.findall(r"t\('(ui\.ked\.[^']+)'", js))
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    fallbacks = re.findall(r"t\('(ui\.ked\.[^']+)',\s*'([^']*)'", js)
    assert all(CATALOG["tr"][key] == fallback for key, fallback in fallbacks)
    for key in keys:
        def placeholders(value: str) -> set[str]:
            return set(re.findall(r"\{(\w+)\}", value))

        assert placeholders(CATALOG["tr"][key]) == placeholders(CATALOG["en"][key])
    assert "Cevaplanamayan soru yok." in outputs["empty"]
    assert "Operatör etiketi" in outputs["groups"] and "Öneri" in outputs["groups"]
    assert "Operatöre aktarılan talep" in outputs["request"]
    assert "Değerlendirme sorusu" in outputs["evaluation"]
    assert outputs["escaped"] == "&lt;b&gt;text&lt;/b&gt;&amp;"
    assert "&lt;b&gt;masked&lt;/b&gt;" in outputs["request"]
    assert "Onaylandı · dizine alınmayı bekliyor" in outputs["candidates"][2]
    assert "Dizin değişti (3 → 4 belge): ilk sırada 0/3 → 1/3" in outputs["candidates"][1]
    assert "içerik değişti" in outputs["candidates"][1]
    assert "sayfa güncelleme tarihi bilinmiyor" in outputs["candidates"][1]
    assert "Question text" in outputs["candidates"][1] and "Reviewed note" in outputs["candidates"][1]
    assert "yayında" not in outputs["candidates"][2].lower()
    assert "düzeltildi" not in outputs["candidates"][2].lower()
    assert "canlı" not in outputs["candidates"][2].lower()
    for markup in [*outputs["candidates"], outputs["decisionForm"], outputs["undoForm"]]:
        assert markup.count('class="btn btn-primary"') <= 1


def test_assets_follow_offline_and_accessible_surface_rules() -> None:
    js = JS_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    assert len(js.splitlines()) <= 300 and len(css.splitlines()) <= 350
    assert subprocess.run(["node", "--check", str(JS_PATH)], capture_output=True).returncode == 0
    assert "setInterval" not in js and "addEventListener('scroll'" not in js
    assert not re.search(r"fetch\([^)]*https?://", js)
    assert "—" not in js and "–" not in js and "…" not in js
    assert re.search(r"\bt\('(?!ui\.ked\.)", js) is None
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\s*\(|\binfinite\b|\bis-bad\b", css)
    transitions = re.findall(r"\b(?:transition|animation)\s*:", css)
    motion_blocks = re.findall(r"@media\s*\(prefers-reduced-motion:\s*no-preference\)\s*\{([^}]*)\}", css)
    contained = sum(block.count("transition:") + block.count("animation:") for block in motion_blocks)
    assert transitions and contained == len(transitions)
    assert "prefers-reduced-motion" in css and "forced-colors" in css
    static = REPO_ROOT / "src/nabiz/console/static"
    assert 'id="citizen-requests"' in (static / "console.html").read_text(encoding="utf-8")
    for path in (static / "console.html", static / "index.html", static / "kolay.html", static / "sw.js"):
        if path.exists():
            assert "console_knowledge_editor" not in path.read_text(encoding="utf-8")
