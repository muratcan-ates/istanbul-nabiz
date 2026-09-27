"""Pure classification and source-review rules for E74."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

from nabiz.console.knowledge_editor import (
    apply_events,
    canonical,
    check_candidate,
    compare_trials,
    gap_from_measure,
    group_gaps,
    summarize_trial,
)
from nabiz.console.knowledge_editor_api import robots_for


def calibration_module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "knowledge_calibration.py"
    spec = importlib.util.spec_from_file_location("knowledge_calibration_for_editor_test", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_matches_calibration_for_ten_urls() -> None:
    urls = [
        "https://www.metro.istanbul/icerik/eri%C5%9Filebilirlik-hizmetleri/",
        "http://WWW.ISPARK.istanbul/",
        "https://www.iett.istanbul/icerik/seferler/?a=1",
        "https://istanbulkart.istanbul/",
        "  https://www.iski.istanbul/Abonelik/  ",
        "https://www.ibb.istanbul/duyurular#top",
        "https://spor.istanbul/hizmetler%2F",
        "https://example.org/a%20b///?x=1&y=2",
        "http://WWW.METRO.ISTANBUL/",
        "https://data.ibb.gov.tr/dataset/abc/",
    ]
    reference = calibration_module().canonical
    assert len(urls) == 10
    assert [canonical(url) for url in urls] == [reference(url) for url in urls]


def test_gap_classification_required_answered_missing_wrong_and_stale() -> None:
    required = gap_from_measure({"ref": "eval:kc:sensitive", "sensitive": True, "mode": "refused"})
    assert required and required["why"] == "required_refusal" and required["tag_suggested"] == "not_a_gap"
    assert gap_from_measure({"mode": "answer", "gold_urls": ["https://x.gov/a"], "top_url": "https://x.gov/a"}) is None
    missing = gap_from_measure({"mode": "unknown", "gold_urls": ["https://x.gov/a"], "active_urls": []})
    assert missing and missing["tag_suggested"] == "missing_source"
    wrong = gap_from_measure({"mode": "unknown", "gold_urls": ["https://x.gov/a"],
                              "active_urls": ["https://x.gov/a"], "top_url": "https://x.gov/b", "gold_rank": 5})
    assert wrong and wrong["tag_suggested"] == "wrong_route" and wrong["gold_rank"] == 5
    stale = gap_from_measure({"mode": "unknown", "as_of": "2026-09-27T00:00:00+00:00",
                              "top_fetched_at": "2024-01-01T00:00:00+00:00",
                              "top_updated_at_method": "fetched"})
    assert stale and stale["stale_hint"] and stale["updated_at_method"] == "fetched"
    request = gap_from_measure({"kind": "request", "ref": "request:abc", "mode": "answer"})
    assert request and request["tag_suggested"] == "wrong_route" and request["why"] == "answers_now"
    no_gold = gap_from_measure({"mode": "unknown", "gold_urls": []})
    assert no_gold and no_gold["tag_suggested"] == "missing_source"


def test_groups_sort_by_count_and_operator_tag_wins() -> None:
    rows = [
        {"ref": "a", "category": "Zeta", "excerpt": "one", "tag_suggested": "missing_source"},
        {"ref": "b", "category": "Alfa", "excerpt": "two", "tag_suggested": "wrong_route"},
        {"ref": "c", "category": "Alfa", "excerpt": "three", "tag_suggested": "missing_source"},
    ]
    groups = group_gaps(rows, {"b": {"tag": "stale"}})
    assert [group["category"] for group in groups] == ["Alfa", "Zeta"]
    item = groups[0]["items"][0]
    assert item["tag"] == "stale" and item["tag_by"] == "operator"
    assert group_gaps(rows, {"b": {"tag": "not_a_gap"}})[0]["count"] == 1


def test_candidate_checks_are_offline_and_unknown_robots_do_not_reject() -> None:
    denied = check_candidate("http://service.example.gov/page", allowlist={"service.example.gov"},
                             robots={"status": "missing"}, active_versions=[])
    assert not denied["accepted"] and next(row for row in denied["checks"] if row["key"] == "https")["state"] == "fail"
    off_list = check_candidate("https://elsewhere.example/page", allowlist={"service.example.gov"},
                               robots={"status": "missing"}, active_versions=[])
    assert not off_list["accepted"]
    igdas = check_candidate("https://igdas.istanbul/page", robots={"status": "missing"}, active_versions=[])
    assert not igdas["accepted"] and next(row for row in igdas["checks"] if row["key"] == "not_igdas")["state"] == "fail"
    blocked = check_candidate("https://service.example.gov/page", allowlist={"service.example.gov"},
                              robots={"status": "parsed", "allowed": False}, active_versions=[])
    assert not blocked["accepted"]
    unknown = check_candidate("https://service.example.gov/page", allowlist={"service.example.gov"},
                              robots={"status": "missing"}, active_versions=[])
    assert unknown["accepted"] and next(row for row in unknown["checks"] if row["key"] == "robots")["state"] == "unknown"
    allowed_all = check_candidate("https://service.example.gov/page", allowlist={"service.example.gov"},
                                  robots={"status": "allows_all", "allowed": True}, active_versions=[{"active": True}])
    assert allowed_all["accepted"] and next(row for row in allowed_all["checks"] if row["key"] == "in_index")["state"] == "pass"


def test_robots_snapshots_are_local_and_preserve_unknown_states(tmp_path: Path) -> None:
    host = "service.example.gov"
    robots_dir = tmp_path / "robots"
    robots_dir.mkdir()
    (robots_dir / f"{hashlib.sha256(host.encode()).hexdigest()}.txt").write_text(
        "User-agent: NabizKnowledgeBot\nDisallow: /private", encoding="utf-8"
    )
    assert robots_for(host, "https://service.example.gov/public", robots_dir) == {
        "status": "parsed", "allowed": True,
    }
    assert robots_for(host, "https://service.example.gov/private", robots_dir) == {
        "status": "parsed", "allowed": False,
    }
    (robots_dir / f"{hashlib.sha256(host.encode()).hexdigest()}.txt").unlink()
    (robots_dir / f"{host}.json").write_text(
        '{"status":"robots-unavailable","robots_snapshot":{"status":404}}', encoding="utf-8"
    )
    assert robots_for(host, "https://service.example.gov/page", robots_dir)["status"] == "allows_all"
    (robots_dir / f"{host}.json").unlink()
    assert robots_for("missing.example.gov", "https://missing.example.gov/page", robots_dir) == {
        "status": "missing", "allowed": None,
    }


def test_trial_summary_and_fingerprint_comparison() -> None:
    rows = [
        {"candidate_rank": 1, "candidate_indexed": True},
        {"candidate_rank": 9, "candidate_indexed": True},
        {"candidate_rank": None, "candidate_indexed": True},
    ]
    summary = summarize_trial(rows, "https://service.example.gov/page")
    assert summary == {"questions": 3, "top1": 1, "in_top_k": 1, "absent": 2, "not_indexed": False}
    before = {"fingerprint": {"documents": 3}, "summary": {"top1": 0}}
    assert compare_trials(before, {**before}) is None
    assert compare_trials(before, {"fingerprint": {"documents": 4}, "summary": {"top1": 1}})["after"]["top1"] == 1


def test_approval_requires_a_trial_and_undo_restores_prior_status() -> None:
    candidate = {"id": 1}
    events = [{"id": 1, "kind": "proposed"}, {"id": 2, "kind": "approved"}]
    with pytest.raises(ValueError, match="trial"):
        apply_events(candidate, events)
    active = [{"id": 1, "kind": "proposed"}, {"id": 2, "kind": "tried"}, {"id": 3, "kind": "approved"}]
    approved = apply_events(candidate, active)
    assert approved["status"] == "approved"
    undone = apply_events(candidate, [*active, {"id": 4, "kind": "undone", "undoes": 3}])
    assert undone["status"] == "tried"
