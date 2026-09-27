"""E72 prerequisite: capture Enstitü İstanbul İSMEK's public catalog; check the BİO job site.

Standard library only, at most four GET requests, run once by the owner (the coding agent has
no network). Robots rules: enstitu.ibb.istanbul from the main checkout's snapshot in
data/knowledge/robots/ (NABIZ_ROBOTS_DIR), bio.ibb.istanbul from its robots.txt (no snapshot yet).
A page that renders with JavaScript is recorded as "veri_alinamadi"; its script bundle is never
read. Output: data/reference/ismek_bio/{ismek,bio}.json.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
import urllib.robotparser
from urllib.parse import urlsplit

UA = "istanbul-nabiz-ogrenci-projesi/1"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(os.environ.get("NABIZ_E72_OUT") or ROOT / "data" / "reference" / "ismek_bio")
#: The robots snapshots are not in git; point this at the main checkout's copy (read only).
ROBOTS = pathlib.Path(os.environ.get("NABIZ_ROBOTS_DIR") or ROOT / "data" / "knowledge" / "robots")
ISMEK = "https://enstitu.ibb.istanbul/portal/"
URLS = {
    "bio_robots": "https://bio.ibb.istanbul/robots.txt",
    "bio_home": "https://bio.ibb.istanbul/",
    "ismek_programs": ISMEK + "enstitu_egitimler.aspx",
    "ismek_centers": ISMEK + "kursmerkezleri.aspx",
}
MAX_REQUESTS = 4
MAX_BYTES = 3_000_000
LICENSE = "Lisans belirtilmemiş (İBB kamu sayfası). Yalnız ad, kod, sayı ve resmî bağlantı saklanır."
LOGIN_SENTENCE = "Üye girişi ve başvuru işlemleriniz için"
_requests = 0


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def fetch(url: str) -> tuple[int, str, str]:
    global _requests
    _requests += 1
    if _requests > MAX_REQUESTS or "igdas" in (urlsplit(url).hostname or ""):
        sys.exit(f"DUR: izin verilmeyen istek ({_requests}. istek, {url}).")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "tr"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read(MAX_BYTES + 1)[:MAX_BYTES]
            return resp.status, resp.headers.get("Content-Type", ""), body.decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", ""
    except (urllib.error.URLError, TimeoutError) as exc:
        sys.exit(f"DUR: {url} okunamadı ({exc}). Sertifika hatasıysa .venv/bin/python ile koşun.")


def check_allowlist() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from ibb_mcp.knowledge.guardrails import host_allowed

    for url in URLS.values():
        host = urlsplit(url).hostname or ""
        if not host_allowed(host):
            sys.exit(f"DUR: {host} allowlist'te değil; eklemek entegratör kararı.")


def ismek_robots_allows() -> bool:
    host = "enstitu.ibb.istanbul"
    snap_path = ROBOTS / f"{host}.json"
    if not snap_path.is_file():
        sys.exit(f"DUR: {snap_path} yok; robots anlık görüntüsü olmadan istek atılmaz.")
    status = json.loads(snap_path.read_text(encoding="utf-8")).get("status")
    if status == "robots-unavailable":
        return True
    if status != "ok":
        return False
    body = ROBOTS / f"{hashlib.sha256(host.encode()).hexdigest()}.txt"
    parser = urllib.robotparser.RobotFileParser()
    parser.parse(body.read_text(encoding="utf-8", errors="replace").splitlines())
    return all(parser.can_fetch(UA, URLS[key]) for key in ("ismek_programs", "ismek_centers"))


def options(page: str, select_id: str) -> list[tuple[str, str]]:
    match = re.search(rf'<select[^>]*id="{select_id}"[^>]*>(.*?)</select>', page, re.S)
    if not match:
        return []
    pairs = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', match.group(1), re.S)
    return [(html.unescape(v).strip(), text(n)) for v, n in pairs if v.strip() != "-1"]


def featured(page: str) -> list[dict]:
    items = []
    for block in page.split('<div class="ebox">')[1:]:
        block = block[:4000]
        link = re.search(r"<div class=\"detay\">\s*<a href='([^']+)'>(.*?)</a>", block, re.S)
        if not link:
            continue
        info1 = re.search(r'<div class="info1">(.*?)</div>', block, re.S)
        info2 = re.search(r'<div class="info2">(.*?)</div>', block, re.S)
        parts = [text(p) for p in re.findall(r"<span>(.*?)</span>", info2.group(1), re.S)] if info2 else []
        items.append({
            "name": text(link.group(2)),
            "url": ISMEK + html.unescape(link.group(1)),
            "modes": [html.unescape(m) for m in re.findall(r"<a title='([^']+)' class='[^']*active'", block)],
            "field": text(info1.group(1)) if info1 else None,
            "hours_text": next((p for p in parts if p.endswith("Saat")), None),
            "kind": next((p for p in parts if not p.endswith("Saat")), None),
        })
    return items


#: The catalog's four tab panels, named by the page's own branch filter (egitim_dali_combo).
TAB_BRANCH = {
    "meslekiEgitimler-tab": "Mesleki ve Teknik Eğitimler",
    "kisiselEgitimler-tab": "Kişisel Gelişim",
    "guzelSanatlar-tab": "Güzel Sanatlar",
    "elsanatlariZanaat-tab": "El Sanatları ve Zanaat",
}


def areas(page: str) -> list[dict]:
    panels = [(m.start(), TAB_BRANCH.get(m.group(1))) for m in re.finditer(r'role="tabpanel" aria-labelledby="([^"]+)"', page)]
    pattern = r'<a href="egitim_alanlari\.aspx\?alanId=(\d+)">([^<]+)<span>.*?(\d[\d.]*) Eğitim</span>'
    seen, out = set(), []
    for match in re.finditer(pattern, page, re.S):
        area_id, name, count = match.groups()
        if area_id in seen:
            continue
        seen.add(area_id)
        branch = next((b for start, b in reversed(panels) if start < match.start()), None)
        out.append({"id": area_id, "name": text(name), "branch": branch, "programs": int(count.replace(".", "")),
                    "url": f"{ISMEK}egitim_alanlari.aspx?alanId={area_id}"})
    return out


def _count(visible: str, word: str) -> int | None:
    found = re.search(r"(\d[\d.]*)\s*" + word, visible)
    return int(found.group(1).replace(".", "")) if found else None


def centers(page: str) -> list[dict]:
    out = []
    for block in re.findall(r'<div class="post-thumbnail-content">(.*?)<div class="info2">', page, re.S):
        link = re.search(r'<a title="([^"]+)" href="([^"]+)"', block)
        if not link:
            continue
        district = re.search(r'icon-location"></span>([^<]+)</span>', block)
        visible = text(block)
        out.append({"name": html.unescape(link.group(1)), "url": ISMEK + html.unescape(link.group(2)),
                    "district": text(district.group(1)) if district else None,
                    "classrooms": _count(visible, "Derslik"), "programs": _count(visible, "Program")})
    return out


def login_sentence(page: str) -> str | None:
    visible = text(re.sub(r"<(script|style)\b.*?</\1>", " ", page, flags=re.S))
    match = re.search(re.escape(LOGIN_SENTENCE) + r"[^.]*\.", visible)
    return match.group(0) if match else None


def capture_bio() -> dict:
    record = {"source": "İBB Bölgesel İstihdam Ofisleri", "url": URLS["bio_home"], "license": LICENSE}
    status, ctype, body = fetch(URLS["bio_robots"])
    record["robots"] = {"status": status, "checked_at": now()}
    if status == 200 and not body.lstrip().startswith("<"):
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(body.splitlines())
        if not parser.can_fetch(UA, URLS["bio_home"]):
            return record | {"status": "robots_yasak", "retrieved_at": now()}
    elif status not in (404, 410):
        return record | {"status": "robots_okunamadi", "retrieved_at": now()}
    status, ctype, body = fetch(URLS["bio_home"])
    title = re.search(r"<title>(.*?)</title>", body, re.S)
    dynamic = 'id="root"></div>' in body or "enable JavaScript" in body
    return record | {
        "http_status": status,
        "title": text(title.group(1)) if title else None,
        "status": "veri_alinamadi" if dynamic or status != 200 else "html_var",
        "reason": "Sayfa içeriği JavaScript ile yükleniyor; ilanlar HTML'de yok." if dynamic else None,
        "retrieved_at": now(),
    }


def capture_ismek() -> dict:
    record = {"source": "Enstitü İstanbul İSMEK", "license": LICENSE, "robots": "data/knowledge/robots/enstitu.ibb.istanbul.json"}
    if not ismek_robots_allows():
        return record | {"status": "robots_yasak", "retrieved_at": now()}
    status, _, page = fetch(URLS["ismek_programs"])
    status2, _, centers_page = fetch(URLS["ismek_centers"])
    if status != 200 or status2 != 200:
        return record | {"status": "veri_alinamadi", "reason": f"HTTP {status}/{status2}", "retrieved_at": now()}
    programs = [{"code": c, "name": n, "url": f"{ISMEK}egitim_detay.aspx?detayliArama=true&BransCode={c}"}
                for c, n in options(page, "MainContent_programlar_combo") if c.isdigit()]
    data = {
        "programs_url": URLS["ismek_programs"],
        "centers_url": URLS["ismek_centers"],
        "apply_url": "https://enstitukayit.ibb.istanbul/" if "enstitukayit.ibb.istanbul" in page else None,
        "login_sentence": login_sentence(page),
        "areas": areas(page),
        "branches": [n for _, n in options(page, "MainContent_egitim_dali_combo")],
        "modes": [n for _, n in options(page, "MainContent_egitim_tipi_combo")],
        "times": [n for _, n in options(page, "MainContent_zaman_liste_combo")],
        "certificates": [n for _, n in options(page, "MainContent_belge_combo")],
        "languages": [n for _, n in options(page, "MainContent_egitim_dili_combo")],
        "districts": [n for _, n in options(page, "MainContent_lokasyon_combo")],
        "programs": programs,
        "featured": featured(page),
        "centers": centers(centers_page),
    }
    ok = len(programs) >= 100 and len(data["centers"]) >= 50
    return record | data | {"status": "alindi" if ok else "veri_alinamadi",
                            "reason": None if ok else "Beklenen liste HTML'de bulunamadı.", "retrieved_at": now()}


def main() -> None:
    check_allowlist()
    OUT.mkdir(parents=True, exist_ok=True)
    bio = capture_bio()
    ismek = capture_ismek()
    for name, record in (("bio.json", bio), ("ismek.json", ismek)):
        (OUT / name).write_text(json.dumps(record, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"istek: {_requests}/{MAX_REQUESTS}")
    print(f"BİO: {bio['status']} ({bio.get('reason') or bio.get('title')})")
    print(f"İSMEK: {ismek['status']}; program {len(ismek.get('programs', []))}, alan {len(ismek.get('areas', []))}, "
          f"merkez {len(ismek.get('centers', []))}, öne çıkan {len(ismek.get('featured', []))}, "
          f"giriş cümlesi {'var' if ismek.get('login_sentence') else 'yok'}")


if __name__ == "__main__":
    main()
