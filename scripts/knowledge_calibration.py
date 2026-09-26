#!/usr/bin/env python3
"""Measure the service-page index offline: which page each question finds, its scores, the evidence
level and the answer mode, on the local ``data/knowledge/knowledge.db``. No network, no model.

    ./.venv/bin/python scripts/knowledge_calibration.py --seed SEED.jsonl --json run.json [--chat]
    ./.venv/bin/python scripts/knowledge_calibration.py --report before.json after.json --md out.md

Two question sets are read: the research seed (``--seed``, 150 questions with ``gold_urls`` and a
``sensitive`` flag; kept outside the repository) and ``eval/knowledge_calibration.jsonl`` (20 rows
from the problem map's HAFİFLETİYOR lines, the demo questions and a negative set that no İBB page
answers). Sensitivity is decided the way the chat decides it, by :func:`nabiz.console.policy.refuses`;
the seed's own flag is kept beside it.

The search runs with ``embedder=None``: the offline chat never embeds a query (``ChatService`` passes
no embedder when ``NABIZ_OFFLINE=1``), so this measures what the offline product does, and no
cosine score exists here. ``--chat`` also sends every question to ``/api/chat`` in-process, offline
and with no model rung, and records the mode, the rule and the cited URLs the page would show.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

REPO = Path(__file__).resolve().parents[1]
SET_PATH = REPO / "eval" / "knowledge_calibration.jsonl"
ANSWERED = ("answer", "quote_only")


def canonical(url: str) -> str:
    """A URL compared loosely: scheme, ``www.``, case of the host, escapes and a trailing slash ignored."""
    parts = urlsplit(unquote(url.strip()))
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/")
    return f"{host}{path}" + (f"?{parts.query}" if parts.query else "")


def read_rows(path: Path, source: str) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            rows.append(
                {
                    "id": row["id"],
                    "set": source,
                    "group": row.get("group") or ("seed-hassas" if row.get("sensitive") else "seed"),
                    "question": row["question"],
                    "gold_urls": row.get("gold_urls") or [],
                    "seed_sensitive": row.get("sensitive"),
                    "expect": row.get("expect"),
                    "row": row.get("row"),
                }
            )
    return rows


async def measure(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from ibb_mcp.knowledge import answer as knowledge_answer
    from ibb_mcp.knowledge import open_from_env, search
    from ibb_mcp.knowledge.answer import assess_evidence, evidence_thresholds
    from ibb_mcp.text import looks_like_instruction
    from nabiz.console.policy import refuses

    store, _ = open_from_env()
    if store is None:
        raise SystemExit("no knowledge index at NABIZ_KNOWLEDGE_DB (default data/knowledge/knowledge.db)")
    thresholds = evidence_thresholds()
    out = []
    for row in rows:
        question = row["question"]
        sensitive = refuses(question)
        hits = [hit for hit in await search(store, question, embedder=None, limit=8) if not looks_like_instruction(hit.quote)]
        verdict = assess_evidence(hits, query=question, **thresholds)
        found = await knowledge_answer(question, store=store, embedder=None, sensitive=sensitive)
        gold = {canonical(url) for url in row["gold_urls"]}
        ranks = [index for index, hit in enumerate(hits, start=1) if canonical(hit.url) in gold]
        cited = [hit.url for hit in found.citations]
        out.append(
            {
                **row,
                "sensitive": sensitive,
                "top_url": hits[0].url if hits else None,
                "top_quote": hits[0].quote[:160] if hits else None,
                "top_bm25": round(hits[0].bm25, 3) if hits and hits[0].bm25 is not None else None,
                "gold_rank": ranks[0] if ranks else None,
                "top_is_gold": bool(gold) and bool(hits) and canonical(hits[0].url) in gold,
                "best_cosine": verdict.best_cosine,
                "best_bm25": None if verdict.best_bm25 is None else round(verdict.best_bm25, 3),
                "coverage": round(verdict.coverage, 3),
                "level": verdict.level,
                "mode": found.mode,
                "cited_urls": cited,
                "cited_is_gold": bool(gold) and bool(cited) and all(canonical(url) in gold for url in cited[:1]),
            }
        )
    return out


def chat_modes(rows: list[dict[str, Any]]) -> None:
    """Add what ``/api/chat`` answers, offline, with no model rung (the rule path)."""
    from fastapi.testclient import TestClient

    from nabiz.agent import llm
    from nabiz.console.app import build_console_app
    from nabiz.console.budget import BudgetConfig, SpendGuard

    app = build_console_app(llm_config=llm.LlmConfig(), guard=SpendGuard(BudgetConfig(state_path=None)))
    with TestClient(app) as client:
        for row in rows:
            response = client.post("/api/chat", json={"message": row["question"], "needs": [], "history": []})
            final: dict[str, Any] = {}
            tools: list[str] = []
            for block in response.text.strip().split("\n\n"):
                head, _, body = block.partition("\n")
                data = json.loads(body.removeprefix("data: ")) if body.startswith("data: ") else {}
                if head == "event: final":
                    final = data
                elif head == "event: tool" and data.get("status") == "start":
                    tools.append(data.get("name", ""))
            how = final.get("how") or {}
            row["chat"] = {
                "mode": final.get("mode"),
                "emergency": final.get("emergency"),
                "rule_id": how.get("rule_id"),
                "tools": tools,
                "urls": [item.get("url") for item in final.get("citations") or [] if item.get("url")],
            }


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def count(selected: list[dict[str, Any]]) -> dict[str, int]:
        modes = Counter(row["mode"] for row in selected)
        return {mode: modes.get(mode, 0) for mode in ("answer", "quote_only", "unknown")}

    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["group"], []).append(row)
    answered = [row for row in rows if row["mode"] in ANSWERED]
    with_gold = [row for row in answered if row["gold_urls"]]
    return {
        "total": len(rows),
        "modes": count(rows),
        "by_group": {name: {"n": len(items), **count(items)} for name, items in sorted(groups.items())},
        "top_is_gold": sum(row["top_is_gold"] for row in rows if row["gold_urls"]),
        "gold_in_top8": sum(row["gold_rank"] is not None for row in rows if row["gold_urls"]),
        "with_gold": sum(bool(row["gold_urls"]) for row in rows),
        "answered_with_gold": len(with_gold),
        "answered_cites_gold": sum(row["cited_is_gold"] for row in with_gold),
        "answered_cites_other": sum(not row["cited_is_gold"] for row in with_gold),
        "negative_answered": sum(row["mode"] in ANSWERED for row in groups.get("negatif", [])),
    }


def run(args: argparse.Namespace) -> int:
    rows = read_rows(SET_PATH, "calibration")
    if args.seed:
        rows = read_rows(Path(args.seed), "seed") + rows
    measured = asyncio.run(measure(rows))
    if args.chat:
        chat_modes(measured)
    from ibb_mcp.knowledge.answer import evidence_thresholds

    result = {"label": args.label, "thresholds": evidence_thresholds(), "summary": summary(measured), "rows": measured}
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.json:
        Path(args.json).write_text(text + "\n", encoding="utf-8")
    brief = {"label": args.label, "thresholds": result["thresholds"], "summary": result["summary"]}
    print(json.dumps(brief, ensure_ascii=False, indent=1))
    return 0


def _cell(value: Any) -> str:
    if value is None:
        return "·"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value).replace("|", "\\|")


def _short(url: str | None) -> str:
    return canonical(url) if url else "·"


def _chat_lines(before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    """The ``/api/chat`` modes of both runs, when both were run with ``--chat``."""
    if not all(row.get("chat") for run in (before, after) for row in run["rows"]):
        return []
    counts = [Counter(row["chat"]["mode"] for row in run["rows"]) for run in (before, after)]
    modes = sorted(set(counts[0]) | set(counts[1]))
    return [
        "",
        "Sohbet (`/api/chat`, çevrimdışı, model yok) modları, aynı 198 soru:",
        "",
        "| Sohbet modu | önce | sonra |",
        "|---|---:|---:|",
        *(f"| {mode} | {counts[0].get(mode, 0)} | {counts[1].get(mode, 0)} |" for mode in modes),
    ]


def report(before_path: str, after_path: str, md_path: str) -> int:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    old = {row["id"]: row for row in before["rows"]}
    lines = [
        "# Bilgi dizini eşik ölçümü: önce / sonra",
        "",
        "`scripts/knowledge_calibration.py` çıktısından üretildi; elle sayı yazılmadı. Dizin: yerel",
        "`data/knowledge/knowledge.db`. Arama modelsiz ve gömmesiz (`embedder=None`): çevrimdışı sohbet sorgu",
        "gömmesi yapmaz, bu yüzden kosinüs sütunu yok. Hassaslık `policy.refuses` ile, sohbetin kararıyla aynı",
        "(`hassas` sütunu); `seed-hassas` kümesi araştırma tohumunun kendi `sensitive` işaretidir. `seed` ve",
        "`seed-hassas` araştırma tohumunun 150 sorusu (depo dışında); öteki kümeler `eval/knowledge_calibration.jsonl`.",
        "Altın dışı kaynak her zaman yanlış değildir (ör. aynı kurumun başka sayfası); negatif kümedeki her cevap yanlıştır.",
        "",
        f"Önce eşikler: `{json.dumps(before['thresholds'])}` · Sonra eşikler: `{json.dumps(after['thresholds'])}`",
        "",
        "## Özet",
        "",
        "| Küme | n | önce answer | önce quote_only | önce unknown | sonra answer | sonra quote_only | sonra unknown |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, item in after["summary"]["by_group"].items():
        prev = before["summary"]["by_group"].get(name, {})
        lines.append(
            f"| {name} | {item['n']} | {prev.get('answer', 0)} | {prev.get('quote_only', 0)} | {prev.get('unknown', 0)}"
            f" | {item['answer']} | {item['quote_only']} | {item['unknown']} |"
        )
    total_b, total_a = before["summary"], after["summary"]
    lines += [
        f"| **toplam** | {total_a['total']} | {total_b['modes']['answer']} | {total_b['modes']['quote_only']}"
        f" | {total_b['modes']['unknown']} | {total_a['modes']['answer']} | {total_a['modes']['quote_only']}"
        f" | {total_a['modes']['unknown']} |",
        "",
        "| Ölçü | önce | sonra |",
        "|---|---:|---:|",
        f"| Altın URL'si olan soru | {total_b['with_gold']} | {total_a['with_gold']} |",
        f"| İlk sonuç altın URL | {total_b['top_is_gold']} | {total_a['top_is_gold']} |",
        f"| Altın URL ilk 8'de | {total_b['gold_in_top8']} | {total_a['gold_in_top8']} |",
        f"| Cevaplanan (answer/quote_only) ve altını olan | {total_b['answered_with_gold']} | {total_a['answered_with_gold']} |",
        f"| … ilk kaynağı altın URL | {total_b['answered_cites_gold']} | {total_a['answered_cites_gold']} |",
        f"| … ilk kaynağı altın dışı | {total_b['answered_cites_other']} | {total_a['answered_cites_other']} |",
        f"| Negatif kümede cevap (yanlış pozitif) | {total_b['negative_answered']} | {total_a['negative_answered']} |",
        *_chat_lines(before, after),
        "",
        "## Soru başına",
        "",
        "`bm25` ilk sonucun FTS5 puanının mutlak değeri (büyük = daha iyi eşleşme); `kapsam` sorunun ayırt edici",
        "kelimelerinden ilk alıntıda geçenlerin oranı (sonra koşusu); `altın` ilk sonucun sorunun altın URL'lerinden biri olup",
        "olmadığı (`·` altın yok). Sohbet sütunu `--chat` koşusunda `/api/chat`'in modu ve kuralıdır.",
        "",
        "| id | soru | hassas | ilk sonuç | bm25 | kapsam | altın | önce seviye/mod | sonra seviye/mod | sohbet (sonra) |",
        "|---|---|:-:|---|---:|---:|:-:|---|---|---|",
    ]
    for row in after["rows"]:
        prev = old.get(row["id"], {})
        gold = "·" if not row["gold_urls"] else ("evet" if row["top_is_gold"] else "hayır")
        chat = row.get("chat") or {}
        chat_text = "·" if not chat else f"{chat.get('mode')} / {chat.get('rule_id') or ','.join(chat.get('tools') or []) or '·'}"
        lines.append(
            f"| {row['id']} | {_cell(row['question'])} | {'E' if row['sensitive'] else ''} | {_short(row['top_url'])}"
            f" | {_cell(row['top_bm25'])} | {_cell(row['coverage'])} | {gold}"
            f" | {prev.get('level', '·')}/{prev.get('mode', '·')} | {row['level']}/{row['mode']} | {_cell(chat_text)} |"
        )
    Path(md_path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md_path)
    return 0


def _offline_environment() -> None:
    """No İBB call, no model probe, no ``.env``; the chat's per-minute turn limit out of the way."""
    for key, value in (
        ("NABIZ_OFFLINE", "1"),
        ("NABIZ_LLM_NO_PROBE", "1"),
        ("NABIZ_ENV_FILE", os.devnull),
        ("NABIZ_CHAT_TURNS_PER_MIN", "100000"),
    ):
        os.environ.setdefault(key, value)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seed", help="research seed JSONL (id, question, gold_urls, sensitive)")
    parser.add_argument("--json", help="write the run here")
    parser.add_argument("--label", default="run")
    parser.add_argument("--chat", action="store_true", help="also ask /api/chat in-process, offline, rules only")
    parser.add_argument("--report", nargs=2, metavar=("BEFORE", "AFTER"), help="render two runs as a Markdown table")
    parser.add_argument("--md", help="Markdown output for --report")
    args = parser.parse_args(argv)
    if args.report:
        if not args.md:
            parser.error("--report needs --md")
        return report(args.report[0], args.report[1], args.md)
    _offline_environment()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
