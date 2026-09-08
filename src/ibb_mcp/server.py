"""``ibb-mcp`` — an unofficial Model Context Protocol server over İstanbul open data.

Run it over stdio (for VS Code Copilot, Claude Desktop, Claude Code)::

    ibb-mcp

or over streamable HTTP (the deployment shape used on Azure Container Apps)::

    ibb-mcp --transport http --host 0.0.0.0 --port 8000

Design notes worth knowing before adding a tool:

* Tools are parametric. No tool accepts a free-form query that reaches a database.
* Every response is a :class:`ToolResult` rendered as JSON, always carrying provenance,
  so a client can cite the source and the age of every number.
* The whole server shares one rate-limited HTTP client and one cache, so a hundred
  clients still produce at most one upstream request per cache window. This is not an
  optimisation, it is what keeps us inside İETT's documented 100 requests per hour.
"""

from __future__ import annotations

import argparse
import asyncio
import functools
import json
import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from ibb_mcp.config import ATTRIBUTION, ATTRIBUTION_EN, Settings
from ibb_mcp.http import RateLimitExceeded, UpstreamUnavailable
from ibb_mcp.models import ToolResult
from ibb_mcp.sources.base import SourceContext
from ibb_mcp.tools import Nabiz

log = logging.getLogger("ibb_mcp.server")

INSTRUCTIONS = f"""
İstanbul Nabız — live İstanbul (İBB) open data: parking, buses, metro, traffic, air quality.

Unofficial. Not affiliated with or endorsed by İBB, İETT, İSPARK or Metro İstanbul.
{ATTRIBUTION_EN}

How to use these tools well:
* Start with `places_resolve` when the user names a place; pass the coordinates onward.
* Every result carries `provenance` with `reported_at` and `source_url`. Quote the age of
  the data ("10 dakika önceki veriye göre") whenever you state a live number.
* Bus arrival times from `iett_next_arrivals` are ESTIMATES. Each one reports the `method`
  used ("stop_sequence", "distance" or "schedule") and a `confidence`. Say so.
* Air-quality output is not health advice.
* If a tool returns `note`, relay it. If data is missing, say it is missing. Never invent
  a number that does not appear in a tool result.
* `city_freshness` tells you how stale each source is and how much request budget is left.
""".strip()

_app: Nabiz | None = None


def get_app() -> Nabiz:
    global _app
    if _app is None:
        _app = Nabiz(SourceContext.create(settings=Settings.from_env()))
    return _app


def _render(result: ToolResult) -> str:
    """Serialise a tool result for the model, provenance first-class."""
    payload: dict[str, Any] = {
        "data": result.data,
        "provenance": {
            "source": result.provenance.source,
            "source_url": result.provenance.source_url,
            "reported_at": result.provenance.reported_at.isoformat() if result.provenance.reported_at else None,
            "observed_at": result.provenance.observed_at.isoformat(),
            "age": result.provenance.describe_age(),
            "age_seconds": round(result.provenance.age_seconds, 1),
            "stale": result.provenance.cached,
            "license": result.provenance.license,
        },
    }
    if result.note:
        payload["note"] = result.note
    return json.dumps(payload, ensure_ascii=False, indent=1, default=str)


def _error(exc: Exception) -> str:
    """Turn a failure into something the model can relay honestly."""
    if isinstance(exc, RateLimitExceeded):
        kind, message = "rate_limited", str(exc)
    elif isinstance(exc, UpstreamUnavailable):
        kind, message = "upstream_unavailable", f"İBB servisi şu anda yanıt vermiyor: {exc}"
    elif isinstance(exc, ValueError):
        kind, message = "bad_request", str(exc)
    else:  # pragma: no cover - unexpected
        log.exception("unhandled tool error")
        kind, message = "internal_error", f"Beklenmeyen hata: {type(exc).__name__}"
    return json.dumps(
        {"error": kind, "message": message, "advice": "Bu bilgiyi uydurma; kullanıcıya erişilemediğini söyle."},
        ensure_ascii=False,
    )


def build_server(settings: Settings | None = None) -> MCPServer:
    mcp = MCPServer("istanbul-nabiz", instructions=INSTRUCTIONS, version="0.1.0")
    app = get_app() if settings is None else Nabiz(SourceContext.create(settings=settings))

    def tool(fn):
        """Wrap a coroutine so every tool renders results and errors the same way.

        ``functools.wraps`` matters more than it looks: the MCP SDK derives each tool's
        JSON schema from the wrapped function's signature via ``inspect.signature``, which
        follows ``__wrapped__``. Without it every tool would advertise ``(*args, **kwargs)``
        and reject real calls.
        """

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return _render(await fn(*args, **kwargs))
            except Exception as exc:  # noqa: BLE001 - a tool must never crash the server
                return _error(exc)

        return wrapper

    @mcp.tool()
    @tool
    async def places_resolve(query: str, limit: int = 5) -> str:
        """İstanbul'da bir yer adını koordinata çevirir (semt, ilçe, metro istasyonu, simge yer).

        Kullanıcı bir yer adı söylediğinde önce bunu çağır, sonra koordinatları diğer araçlara ver.
        """
        return await app.places_resolve(query=query, limit=limit)

    @mcp.tool()
    @tool
    async def ispark_find_parking(
        place: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_km: float = 1.5,
        min_free: int = 1,
        open_now: bool = True,
    ) -> str:
        """Bir yerin yakınındaki İSPARK otoparklarını canlı boş yer sayısıyla listeler.

        `place` (ör. "Taksim") ya da `lat`/`lon` ver. Sonuçta kapasite, boş yer, otopark tipi,
        yürüme mesafesi ve ilk üç otopark için tarife bilgisi döner. Veri ~10 dakikada bir güncellenir.
        """
        return await app.ispark_find_parking(
            place=place, lat=lat, lon=lon, radius_km=radius_km, min_free=min_free, open_now=open_now
        )

    @mcp.tool()
    @tool
    async def ispark_typical_occupancy(park_id: int, weekday: int | None = None, hour: int | None = None) -> str:
        """Bir otoparkın belirli gün ve saatteki tipik doluluğunu döner.

        İBB otopark geçmişi yayınlamadığı için bu profil projenin kendi topladığı anlık
        görüntülerden üretilir; yeterli gözlem yoksa `available: false` döner ve tahmin üretilmez.
        """
        return await app.ispark_typical_occupancy(park_id=park_id, weekday=weekday, hour=hour)

    @mcp.tool()
    @tool
    async def iett_stops_search(query: str, limit: int = 8) -> str:
        """İETT otobüs duraklarını ada göre arar; durak kodu, adı ve koordinatını döner.

        Dönen `stop_code` alanı `iett_next_arrivals` aracına verilecek olan koddur.
        """
        return await app.iett_stops_search(query=query, limit=limit)

    @mcp.tool()
    @tool
    async def iett_line_buses(line_code: str, direction: str | None = None) -> str:
        """Bir otobüs hattındaki araçların anlık konumunu döner (ör. line_code="500T").

        `direction` verilirse yalnızca o yöne giden araçlar döner. Araç plakası hiçbir zaman
        döndürülmez; araçlar kapı numarasıyla tanımlanır.
        """
        return await app.iett_line_buses(line_code=line_code, direction=direction)

    @mcp.tool()
    @tool
    async def iett_next_arrivals(line_code: str, stop: str, limit: int = 3) -> str:
        """Bir hattın bir durağa tahmini varış sürelerini döner.

        `stop` durak kodu veya durak adı olabilir. Her tahmin hangi yöntemle üretildiğini
        (`stop_sequence`, `distance`, `schedule`) ve güven düzeyini bildirir.
        BU BİR TAHMİNDİR, resmi İETT bilgisi değildir; kullanıcıya böyle söyle.
        """
        return await app.iett_next_arrivals(line_code=line_code, stop=stop, limit=limit)

    @mcp.tool()
    @tool
    async def metro_status(line: str | None = None) -> str:
        """Metro İstanbul hatlarındaki canlı arıza ve çalışma duyurularını döner.

        Servis yalnızca duyurusu olan hatları döndürür; bir hat listede yoksa o hat için
        bildirilmiş bir aksaklık yok demektir.
        """
        return await app.metro_status(line=line)

    @mcp.tool()
    @tool
    async def metro_station_info(name: str) -> str:
        """Bir metro istasyonunun hattını, sırasını ve erişilebilirlik bilgisini döner.

        Asansör, yürüyen merdiven, WC, bebek bakım odası ve mescit bilgisi içerir.
        """
        return await app.metro_station_info(name=name)

    @mcp.tool()
    @tool
    async def traffic_index(window: str = "now") -> str:
        """İstanbul geneli trafik yoğunluk indeksini döner (1 akıcı, 99 kilitli).

        `window="now"` anlık değeri, `window="24h"` son 24 saati ve dünkü aynı saatle
        karşılaştırmayı döner.
        """
        return await app.traffic_index(window=window)

    @mcp.tool()
    @tool
    async def air_quality_now(place: str) -> str:
        """Bir yere en yakın istasyonun güncel hava kalitesi ölçümünü döner.

        PM10, SO2, O3, NO2, CO derişimleri ile AQI indeksi ve sağlık durumu metnini içerir.
        PM2.5 İBB API'sinde yoktur. Sağlık tavsiyesi değildir.
        """
        return await app.air_quality_now(place=place)

    @mcp.tool()
    @tool
    async def air_quality_forecast(place: str, horizon_hours: int = 6) -> str:
        """Kısa vadeli PM10 tahmini ve önümüzdeki en temiz zaman aralığını döner.

        İndeks değil saatlik derişim tahmin edilir, çünkü İBB PM10 indeksini 24 saatlik
        hareketli ortalamadan hesaplar. Sağlık tavsiyesi değildir.
        """
        return await app.air_quality_forecast(place=place, horizon_hours=horizon_hours)

    @mcp.tool()
    @tool
    async def city_freshness() -> str:
        """Her veri kaynağının ne kadar güncel olduğunu ve kalan istek bütçesini döner.

        Bir cevabın ne kadar taze veriye dayandığını söylemen gerektiğinde bunu çağır.
        """
        return await app.city_freshness()

    @mcp.resource("ibb://attribution")
    def attribution() -> str:
        """Veri kaynağı ve lisans bildirimi."""
        return f"{ATTRIBUTION}\n\n{ATTRIBUTION_EN}\n\nhttps://data.ibb.gov.tr/license"

    return mcp


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ibb-mcp", description="Unofficial MCP server over İstanbul open data")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--offline", action="store_true", help="Serve recorded fixtures instead of calling İBB")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,  # stdout is the MCP channel
    )

    settings = Settings.from_env()
    if args.offline:
        settings = Settings(
            gtfs_dir=settings.gtfs_dir,
            places_csv=settings.places_csv,
            fixtures_dir=settings.fixtures_dir,
            offline=True,
            default_radius_km=settings.default_radius_km,
            max_results=settings.max_results,
        )

    server = build_server(settings)
    if args.transport == "stdio":
        server.run(transport="stdio")
    else:
        # MCP 2.x takes the bind address as run() kwargs rather than on Settings.
        server.run(transport="streamable-http", host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
