"""Static and offline contracts for the citizen PWA."""

from __future__ import annotations

import json
import math
import re
import shutil
import struct
import subprocess
import zlib
from collections.abc import Iterable
from pathlib import Path

import httpx
import pytest
from conftest import offline_settings, refuse_network
from fastapi.testclient import TestClient

from ibb_mcp.cache import TTLCache
from ibb_mcp.http import PoliteClient
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz
from nabiz.agent import llm
from nabiz.console.app import build_console_app
from nabiz.console.budget import BudgetConfig, SpendGuard

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src/nabiz/console/static"
SW = STATIC / "sw.js"
PWA = STATIC / "js/pwa.js"
MANIFEST = STATIC / "manifest.webmanifest"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PATH_POINTS = ((3, 12), (7, 12), (10, 20), (14, 4), (17, 12), (21, 12))

def read(path: str) -> str:
    return (STATIC / path).read_text(encoding="utf-8")

def token_colour(name: str) -> str:
    value = re.search(rf"--{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}})", read("css/tokens.css"))
    assert value, f"missing colour token: {name}"
    return value.group(1)

def token_rgb(name: str) -> tuple[int, int, int]:
    colour = token_colour(name)
    return tuple(int(colour[index:index + 2], 16) for index in (1, 3, 5))

BG = token_rgb("primary-700")
FG = token_rgb("neutral-0")

def node() -> str:
    executable = shutil.which("node")
    if not executable:
        pytest.skip("node is not installed")
    return executable

def run_node(tmp_path: Path, source: str, *args: str) -> str:
    harness = tmp_path / "pwa-harness.mjs"
    harness.write_text(
        "import { createRequire } from 'node:module';\nconst require = createRequire(import.meta.url);\n" + source,
        encoding="utf-8",
    )
    result = subprocess.run([node(), str(harness), *args], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    return result.stdout

def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(high, max(low, value))

def segment_distance(px: float, py: float, start: tuple[float, float], end: tuple[float, float]) -> float:
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = dx * dx + dy * dy
    t = clamp(((px - start[0]) * dx + (py - start[1]) * dy) / length)
    return math.hypot(px - (start[0] + t * dx), py - (start[1] + t * dy))

def render_icon_rows(size: int, maskable: bool, rows: Iterable[int] | None = None) -> list[bytes]:
    """Rasterize the SVG mark with pixel-centred, one-pixel antialiasing."""
    scale = size / (42 if maskable else 30)
    offset = 9 if maskable else 3
    segments = [
        (((x1 + offset) * scale, (y1 + offset) * scale), ((x2 + offset) * scale, (y2 + offset) * scale))
        for (x1, y1), (x2, y2) in zip(PATH_POINTS, PATH_POINTS[1:], strict=False)
    ]
    selected = range(size) if rows is None else rows
    output: list[bytes] = []
    for y in selected:
        row = bytearray()
        for x in range(size):
            px, py = x + 0.5, y + 0.5
            if maskable:
                alpha = 1.0
            else:
                ux, uy = px / scale - 3, py / scale - 3
                qx, qy = abs(ux - 12) - 8, abs(uy - 12) - 8
                distance = (math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - 7) * scale
                alpha = clamp(0.5 - distance)
            distance = min(segment_distance(px, py, start, end) for start, end in segments)
            stroke = clamp(scale - distance + 0.5)
            row.extend(round(BG[channel] * (1 - stroke) + FG[channel] * stroke) for channel in range(3))
            row.append(round(alpha * 255))
        output.append(bytes(row))
    return output

def png_bytes(size: int, maskable: bool) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    raw = b"".join(b"\0" + row for row in render_icon_rows(size, maskable))
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return PNG_SIGNATURE + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")

def write_icons() -> None:
    folder = STATIC / "icons"
    folder.mkdir(parents=True, exist_ok=True)
    for name, size, maskable in (
        ("nabiz-192.png", 192, False),
        ("nabiz-512.png", 512, False),
        ("nabiz-maskable-512.png", 512, True),
    ):
        (folder / name).write_bytes(png_bytes(size, maskable))

def test_manifest_is_valid_json_and_names_the_product() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["name"] == "İstanbul Nabız"
    assert manifest["short_name"] == "Nabız"
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "/"
    assert manifest["display"] == "standalone"
    assert manifest["lang"] == "tr" and manifest["dir"] == "ltr"
    assert manifest["description"].endswith("resmî İBB hizmeti değildir.")

def test_manifest_colours_are_the_page_tokens() -> None:
    tokens = read("css/tokens.css")
    colour = re.search(r"--neutral-50:\s*(#[0-9a-fA-F]{6})", tokens)
    assert colour
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["theme_color"] == manifest["background_color"] == colour.group(1)

def test_manifest_icons_exist_and_carry_no_ibb_mark() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    svg = (STATIC / "icons/nabiz.svg").read_text(encoding="utf-8")
    assert len(manifest["icons"]) == 4
    for item in manifest["icons"]:
        assert (STATIC / item["src"].lstrip("/")).is_file()
        assert "ibb" not in item["src"].lower()
    assert "ibb" not in manifest["name"].lower()
    assert "ibb" not in manifest["short_name"].lower()
    assert "ibb" not in svg.lower()
    assert 'viewBox="-3 -3 30 30"' in svg
    assert f'fill="{token_colour("primary-700")}"' in svg
    assert f'stroke="{token_colour("neutral-0")}"' in svg

def png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data.startswith(PNG_SIGNATURE)
    chunks = []
    cursor = len(PNG_SIGNATURE)
    while cursor < len(data):
        length = struct.unpack_from(">I", data, cursor)[0]
        kind = data[cursor + 4:cursor + 8]
        payload = data[cursor + 8:cursor + 8 + length]
        crc = struct.unpack_from(">I", data, cursor + 8 + length)[0]
        assert crc == zlib.crc32(kind + payload) & 0xFFFFFFFF
        chunks.append((kind, payload))
        cursor += 12 + length
    return chunks

def test_png_icons_are_the_svg_mark() -> None:
    for name, size, maskable in (
        ("nabiz-192.png", 192, False),
        ("nabiz-512.png", 512, False),
        ("nabiz-maskable-512.png", 512, True),
    ):
        chunks = png_chunks((STATIC / "icons" / name).read_bytes())
        header = next(payload for kind, payload in chunks if kind == b"IHDR")
        width, height, depth, colour, *_ = struct.unpack(">IIBBBBB", header)
        assert (width, height, depth, colour) == (size, size, 8, 6)
        raw = zlib.decompress(b"".join(payload for kind, payload in chunks if kind == b"IDAT"))
        stride = 1 + size * 4
        selected = range(size) if size == 192 else range(0, size, 8)
        expected = render_icon_rows(size, maskable, selected)
        for y, expected_row in zip(selected, expected, strict=True):
            actual = raw[y * stride:(y + 1) * stride]
            assert actual[0] == 0
            assert all(abs(a - b) <= 2 for a, b in zip(actual[1:], expected_row, strict=True))

def test_sw_parses() -> None:
    subprocess.run([node(), "--check", str(SW)], cwd=ROOT, check=True, capture_output=True, text=True)

def test_sw_never_names_the_chat_or_the_operator_api() -> None:
    source = SW.read_text(encoding="utf-8")
    assert "/api/chat" not in source and "/api/console" not in source
    assert "'/console" not in source and '"/console' not in source

def test_sw_rules_by_path(tmp_path: Path) -> None:
    source = """
      const fs = require('node:fs'); const vm = require('node:vm');
      const listeners = {}; const self = {location:{origin:'https://nabiz.test'}, addEventListener:(n,f)=>listeners[n]=f};
      vm.runInNewContext(fs.readFileSync(process.argv[2], 'utf8'), {self, URL});
      const paths = [
        ['/','GET','navigate'], ['/index.html','GET','navigate'], ['/offline.html','GET','navigate'],
        ['/kvkk.html','GET','navigate'], ['/js/cards.js','GET','cors'], ['/js/home.js','GET','cors'],
        ['/vendor/leaflet/leaflet.js','GET','cors'], ['/css/tokens.css','GET','cors'], ['/icons.svg','GET','cors'],
        ['/icons/nabiz-192.png','GET','cors'], ['/manifest.webmanifest','GET','cors'],
        ['/api/brief?stations=Kartal','GET','cors'], ['/api/chat','POST','cors'], ['/api/console/queue','GET','cors'],
        ['/console','GET','navigate'], ['/console.html','GET','navigate'], ['/js/console.js','GET','cors'],
        ['/css/console.css','GET','cors'], ['/mock/brief.json','GET','cors'], ['/api/arrival?line=500T','GET','cors'],
        ['/healthz','GET','cors'], ['https://tile.openstreetmap.org/1/1/1.png','GET','cors'], ['/console/login','POST','cors'],
        ['/i18n/en.json','GET','cors']
      ];
      const result = paths.map(([path, method, mode]) =>
        self.nabizSw.ruleFor(new URL(path, 'https://nabiz.test').href, method, mode));
      process.stdout.write(JSON.stringify({result, shell:self.nabizSw.SHELL}));
    """
    result = json.loads(run_node(tmp_path, source, str(SW)))
    assert result["result"] == [
        "page", "page", "page", "page", "static", "static", "pass", "static", "static", "static", "static",
        "brief", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "pass", "static",
    ]

def test_shell_lists_only_files_that_exist(tmp_path: Path) -> None:
    source = (
        "const fs=require('node:fs'),vm=require('node:vm');"
        "const self={location:{origin:'https://x'},addEventListener(){}};"
        "vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});"
        "process.stdout.write(JSON.stringify(self.nabizSw.SHELL));"
    )
    shell = json.loads(run_node(tmp_path, source, str(SW)))
    missing = [path for path in shell if not (STATIC / ("index.html" if path == "/" else path.lstrip("/"))).is_file()]
    assert not missing, missing
    # DECISIONS #35: Arabic is gone, so its catalogue and the RTL sheet are no longer cached.
    assert "/i18n/ar.json" not in shell and "/css/rtl.css" not in shell
    assert {"/i18n/tr.json", "/i18n/en.json", "/js/i18n.js"} <= set(shell)

def test_shell_covers_everything_the_page_loads(tmp_path: Path) -> None:
    source = (
        "const fs=require('node:fs'),vm=require('node:vm');"
        "const self={location:{origin:'https://x'},addEventListener(){}};"
        "vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});"
        "process.stdout.write(JSON.stringify(self.nabizSw.SHELL));"
    )
    shell = set(json.loads(run_node(tmp_path, source, str(SW))))
    pages = [read("index.html"), read("offline.html")]
    required = set()
    for html in pages:
        required.update(re.findall(r'(?:href|src)="(/(?:css|js|fonts)/[^"#?]+)', html))
    pending = [path for path in shell if path.startswith("/js/") and path.endswith(".js")]
    visited = set()
    while pending:
        path = pending.pop()
        if path in visited:
            continue
        visited.add(path)
        text = read(path.lstrip("/"))
        imports = re.findall(r"from\s+['\"]\.\/([^'\"]+)['\"]", text)
        dynamic = re.findall(r"['\"](/(?:css|js)/[^'\"]+)['\"]", text)
        for relative in imports:
            child = str(Path(path).parent / relative)
            required.add(child)
            pending.append(child)
        required.update(dynamic)
    assert not (required - shell), sorted(required - shell)

def test_saved_brief_never_says_live(tmp_path: Path) -> None:
    source = """
      const fs=require('node:fs'),vm=require('node:vm');const self={location:{origin:'https://x'},addEventListener(){}};
      vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});
      const input=JSON.parse(fs.readFileSync(process.argv[3],'utf8'));const before=JSON.stringify(input);
      const output=self.nabizSw.markSaved(input,'2026-09-25T14:20:00.000Z');
      process.stdout.write(JSON.stringify({input,output,unchanged:before===JSON.stringify(input)}));
    """
    result = json.loads(run_node(tmp_path, source, str(SW), str(STATIC / "mock/brief.json")))
    body = result["output"]
    assert result["unchanged"]
    assert len(body["cards"]) == len(result["input"]["cards"])
    assert body["saved_at"] == "2026-09-25T14:20:00.000Z" and body["from_device"] is True
    assert all(card["status"] != "ok" for card in body["cards"])
    assert all(card["provenance"]["mode"] not in {"live", "schedule"} for card in body["cards"])
    unknown = next(card for card in body["cards"] if card["provenance"].get("observed_at") is None)
    assert unknown["provenance"]["mode"] == "unknown" and unknown["provenance"]["age_s"] is None
    assert [c["title"] for c in body["cards"]] == [c["title"] for c in result["input"]["cards"]]
    assert [c["body"] for c in body["cards"]] == [c["body"] for c in result["input"]["cards"]]

def test_saved_card_names_two_dates_with_two_words(tmp_path: Path) -> None:
    source = """
      const fs=require('node:fs'),vm=require('node:vm'),{pathToFileURL}=require('node:url');
      const self={location:{origin:'https://x'},addEventListener(){}};
      vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});
      (async()=>{
        const {savedLabel}=await import(pathToFileURL(process.argv[3]).href);
        const {cityCard}=await import(pathToFileURL(process.argv[4]).href);
        const body=self.nabizSw.markSaved(JSON.parse(fs.readFileSync(process.argv[5],'utf8')),'2026-09-25T14:20:00Z');
        const card=body.cards[0];const html=cityCard(card,0);const label=savedLabel(body.saved_at);
        process.stdout.write(JSON.stringify({html,label}));
      })();
    """
    result = json.loads(run_node(
        tmp_path, source, str(SW), str(PWA), str(STATIC / "js/cards.js"), str(STATIC / "mock/brief.json")
    ))
    assert result["html"].count("kayıtlı ·") == 1
    assert result["label"] == "cihaza kaydedildi · 25.09 17:20"
    assert "kayıtlı" not in result["label"]
    source_time = re.search(r"kayıtlı · <b>([^<]+)</b>", result["html"])
    assert source_time and result["label"].split(" · ", 1)[1] != source_time.group(1)

def test_slow_brief_is_not_cut_off(tmp_path: Path) -> None:
    source = """
      const fs=require('node:fs'),vm=require('node:vm');let timeoutCount=0,abortCount=0,resolveFetch,responsePromise;
      const listeners={};const cache={put:async()=>{},match:async()=>null};
      class AC{constructor(){this.signal={}}abort(){abortCount++}}
      const self={location:{origin:'https://x'},navigator:{onLine:true},clients:{get:async()=>null},addEventListener:(n,f)=>listeners[n]=f};
      const context={self,URL,Request,Response,Headers,AbortController:AC,caches:{open:async()=>cache},
        fetch:()=>new Promise(resolve=>resolveFetch=resolve),setTimeout:()=>{timeoutCount++;return 1},clearTimeout(){}};
      vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),context);
      const event={request:new Request('https://x/api/brief'),clientId:null,respondWith:p=>responsePromise=p};
      listeners.fetch(event);
      const before={timeoutCount,abortCount};
      resolveFetch(new Response(JSON.stringify({cards:[],generated_at:'now'}),{status:200}));
      responsePromise.then(async response=>process.stdout.write(JSON.stringify({
        before,status:response.status,header:response.headers.get('X-Nabiz-Saved-At')
      })));
    """
    result = json.loads(run_node(tmp_path, source, str(SW)))
    assert result["before"] == {"timeoutCount": 0, "abortCount": 0}
    assert result["status"] == 200 and result["header"] is None

def test_brief_missing_message_names_the_cause(tmp_path: Path) -> None:
    source = "const fs=require('node:fs'),vm=require('node:vm');const self={location:{origin:'https://x'},addEventListener(){}};"
    source += "vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});"
    source += "process.stdout.write(JSON.stringify([self.nabizSw.briefMissingMessage(false),"
    source += "self.nabizSw.briefMissingMessage(true)]));"
    result = json.loads(run_node(tmp_path, source, str(SW)))
    assert result == ["Bağlantı yok ve bu cihazda kayıtlı kart yok.", "Sunucuya ulaşılamıyor ve bu cihazda kayıtlı kart yok."]

def test_old_caches_are_deleted_on_a_new_version(tmp_path: Path) -> None:
    source = "const fs=require('node:fs'),vm=require('node:vm');const self={location:{origin:'https://x'},addEventListener(){}};"
    source += "vm.runInNewContext(fs.readFileSync(process.argv[2],'utf8'),{self,URL});"
    source += "const keys=['nabiz-shell-v1','nabiz-brief-v1','nabiz-shell-v2','nabiz-brief-v2',"
    source += "'nabiz-shell-v3','nabiz-brief-v3','nabiz-shell-v4','nabiz-brief-v4','nabiz-shell-v5','nabiz-brief-v5',"
    source += "'nabiz-shell-v6','nabiz-brief-v6','nabiz-shell-v7','nabiz-brief-v7','nabiz-shell-v8','nabiz-brief-v8',"
    source += "'nabiz-shell-v9','nabiz-brief-v9','nabiz-shell-v10','nabiz-brief-v10','nabiz-shell-v11','nabiz-brief-v11',"
    source += "'nabiz-shell-v12','nabiz-brief-v12','nabiz-shell-v13','nabiz-brief-v13','nabiz-shell-v14','nabiz-brief-v14',"
    source += "'nabiz-shell-v15','nabiz-brief-v15','nabiz-shell-v16','nabiz-brief-v16','nabiz-shell-v17','nabiz-brief-v17',"
    source += "'baska-site'];"
    source += "process.stdout.write(JSON.stringify({version:self.nabizSw.VERSION,stale:self.nabizSw.staleCaches(keys)}));"
    result = json.loads(run_node(tmp_path, source, str(SW)))
    stale = [
        "nabiz-shell-v1", "nabiz-brief-v1", "nabiz-shell-v2", "nabiz-brief-v2", "nabiz-shell-v3", "nabiz-brief-v3",
        "nabiz-shell-v4", "nabiz-brief-v4", "nabiz-shell-v5", "nabiz-brief-v5", "nabiz-shell-v6", "nabiz-brief-v6",
        "nabiz-shell-v7", "nabiz-brief-v7", "nabiz-shell-v8", "nabiz-brief-v8", "nabiz-shell-v9", "nabiz-brief-v9",
        "nabiz-shell-v10", "nabiz-brief-v10", "nabiz-shell-v11", "nabiz-brief-v11",
        "nabiz-shell-v12", "nabiz-brief-v12", "nabiz-shell-v13", "nabiz-brief-v13",
        "nabiz-shell-v14", "nabiz-brief-v14", "nabiz-shell-v15", "nabiz-brief-v15",
        "nabiz-shell-v16", "nabiz-brief-v16",
    ]
    # v7: the 26 Sep integration (DECISIONS #38-#41); v8: its second round; v9: E35's lazy map module (gun2);
    # v10: E40's i18n_text.js in the shell; v11: E27's voice report modules, E33's report list;
    # v12: E30's culture.js and culture.css; v13: E45's answer_actions.js and the new answer card.
    # v14: the redesigned citizen shell and its local Istanbul panorama; v15: E48's official-path source label.
    # v16: the home screen's category pills (quick_chips.js).
    # v17: the P00 wave (DECISIONS #67 on): the E5x-E7x catalogues in i18n/*.json and their kvkk paragraphs.
    assert result == {"version": "v17", "stale": stale}

def test_pwa_js_labels(tmp_path: Path) -> None:
    source = """
      const {pathToFileURL}=require('node:url');
      (async()=>{const p=await import(pathToFileURL(process.argv[2]).href);process.stdout.write(JSON.stringify({
        saved:p.savedLabel('2026-09-25T14:20:00Z'),invalid:p.savedLabel('bad'),
        offline:p.offlineText(12*60000),short:p.offlineText(20000),unknown:p.offlineText(null),
        online:p.backOnlineText(12*60000),ios:p.isIos('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)',5),
        mac:p.isIos('Mozilla/5.0 (Macintosh; Intel Mac OS X)',5),
        edge:p.isIos('Mozilla/5.0 (Windows NT 10.0; Win64; x64) Edg/140',0),
        strings:Object.keys(p.STRINGS).length}));})();
    """
    result = json.loads(run_node(tmp_path, source, str(PWA)))
    assert result["saved"] == "cihaza kaydedildi · 25.09 17:20"
    assert result["invalid"] == "cihaza kaydedildi · zaman bilinmiyor"
    assert result["offline"] == "12 dk çevrimdışısınız."
    assert result["short"] == "1 dk çevrimdışısınız."
    assert result["unknown"] == "Çevrimdışısınız."
    assert result["online"] == "Bağlantı geri geldi. 12 dk çevrimdışıydınız. Kartlar yenileniyor."
    assert result["ios"] and result["mac"] and not result["edge"] and result["strings"] > 0
    text = PWA.read_text(encoding="utf-8")
    assert "tel:" not in text and "beforeinstallprompt" in text and "appinstalled" in text
    assert "register('/sw.js'" in text and "isMock" in text and "const STRINGS" in text

def test_pwa_files_never_say_live() -> None:
    for path in (PWA, SW, STATIC / "offline.html"):
        text = path.read_text(encoding="utf-8").lower()
        assert "canlı" not in text and "güncel" not in text

def test_offline_page_bands_and_phones() -> None:
    html = read("offline.html")
    assert '<html lang="tr">' in html
    assert "Resmî İBB hizmeti değildir" in html
    assert 'href="tel:153"' in html and 'href="tel:112"' in html
    assert 'id="pwa-offline-band"' in html and 'id="offline-cards"' in html
    assert 'id="pwa-bar"' in html and 'id="pwa-band-detail"' in html
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert 'style="' not in html and "\u2013" not in html and "\u2014" not in html
    assert not re.search(r"\bETA\b", html, re.I)
    assert "Ben İstanbul şehir bilgi asistanıyım" not in html
    for path in re.findall(r'(?:href|src)="(/(?:css|js)/[^"#?]+)', html):
        assert (STATIC / path.lstrip("/")).is_file(), path

def test_the_app_serves_the_pwa_files() -> None:
    nabiz = Nabiz(SourceContext.create(
        client=PoliteClient(transport=httpx.MockTransport(refuse_network)),
        cache=TTLCache(),
        settings=offline_settings(),
    ))
    app = build_console_app(
        settings=offline_settings(),
        nabiz=nabiz,
        llm_config=llm.LlmConfig(),
        guard=SpendGuard(BudgetConfig(state_path=None)),
    )
    with TestClient(app) as client:
        responses = {
            "/manifest.webmanifest": ("application/manifest+json", None),
            "/sw.js": ("javascript", None),
            "/offline.html": ("text/html", "Resmî İBB hizmeti değildir"),
            "/icons/nabiz-192.png": ("image/png", None),
        }
        for path, (content_type, text) in responses.items():
            response = client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
            assert "content-security-policy" in response.headers
            if text:
                assert text in response.text
