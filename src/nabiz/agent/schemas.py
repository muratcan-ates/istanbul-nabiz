"""The agent's tool surface: the MCP tools' Turkish descriptions and their function schemas.

Split out of :mod:`nabiz.agent.agent` on 2026-09-23 (docs/ENGINEERING.md §13, split S7): the
table below is data that changes whenever a tool's MCP description does, and it made the
agent's loop the largest module in the repository. :mod:`nabiz.agent.agent` still imports
``TOOL_DESCRIPTIONS`` and ``build_tool_schemas`` from here, so both old import paths work.
"""

from __future__ import annotations

import inspect
import typing
from typing import Any

from ibb_mcp.tools import Nabiz

#: Turkish descriptions, verbatim from ``ibb_mcp/server.py``. They are duplicated rather
#: than imported because the MCP tools are closures created inside the server's registration
#: functions: reading them would mean constructing a live server and an HTTP client just to
#: read a docstring. ``tests/test_faithfulness.py`` compares every entry with the server's
#: ``list_tools()`` output (whitespace aside), so a description changed in one place fails there.
TOOL_DESCRIPTIONS: dict[str, str] = {
    "places_resolve": "İstanbul'da bir yer adını koordinata çevirir (semt, ilçe, metro istasyonu, simge yer). "
    "Kullanıcı bir yer adı söylediğinde önce bunu çağır, sonra koordinatları diğer araçlara ver.",
    "ispark_find_parking": "Bir yerin yakınındaki İSPARK otoparklarını canlı boş yer sayısıyla listeler. "
    "`place` (ör. \"Taksim\") ya da `lat`/`lon` ver. Sonuçta kapasite, boş yer, otopark tipi, yürüme mesafesi ve "
    "ilk üç otopark için tarife bilgisi döner. Veri ~10 dakikada bir güncellenir.",
    "ispark_typical_occupancy": "Bir otoparkın belirli gün ve saatteki tipik doluluğunu döner (\"genelde ne kadar dolu?\"). "
    "`park_id` İSPARK kimliği (`ispark_find_parking` sonucundan); `weekday` 0=Pazartesi … 6=Pazar, `hour` 0–23 İstanbul saati; "
    "verilmezse şu an. Sonuç ortanca ve çeyrekler, yüzde doluluk. İBB otopark geçmişi yayınlamadığı için bu profil projenin "
    "kendi topladığı anlık görüntülerden üretilir (data/reference/occupancy_profile.json); hücrede 3'ten az gözlem varsa ya da "
    "gözlemler tek bir günden geliyorsa `available: false` ve gerekçe döner, tahmin üretilmez. `provenance.reported_at` "
    "profildeki en yeni gözlemin zamanıdır.",
    "iett_stops_search": "İETT otobüs duraklarını ada göre arar; durak kodu, adı ve koordinatını döner. "
    "Dönen `stop_code` alanı `iett_next_arrivals` aracına verilecek olan koddur.",
    "iett_line_buses": "Bir otobüs hattındaki araçların anlık konumunu döner (ör. line_code=\"500T\"). "
    "`direction` verilirse yalnızca o yöne giden araçlar döner. Araç plakası hiçbir zaman döndürülmez; "
    "araçlar kapı numarasıyla tanımlanır.",
    "iett_next_arrivals": "Bir hattın bir durağa tahmini varış sürelerini döner. `stop` durak kodu veya durak adı olabilir. Her "
    "tahmin hangi yöntemle üretildiğini (`stop_sequence`, `distance`, `schedule`) ve güven düzeyini bildirir. Durak başına süre "
    "varsayılan olarak kalibre edilmemiş 120 sn'dir; `diagnostics` içindeki `rate_mode`, `rate_source` ve `rate_reason` hangi "
    "oranın neden kullanıldığını söyler. BU BİR TAHMİNDİR, resmi İETT bilgisi değildir; kullanıcıya böyle söyle.",
    "metro_status": "Metro İstanbul hatlarındaki canlı arıza ve çalışma duyurularını döner. Servis yalnızca duyurusu "
    "olan hatları döndürür; bir hat listede yoksa o hat için bildirilmiş bir aksaklık yok demektir. Gece metrosu, "
    "çalışma günleri, sefer saatleri ya da yolcu hakları gibi hizmet bilgisi için değildir: onlar için `ibb_services_search`.",
    "metro_station_info": "Bir metro istasyonunun hattını, sırasını ve erişilebilirlik bilgisini döner. "
    "Asansör, yürüyen merdiven, WC, bebek bakım odası ve mescit bilgisi içerir.",
    "metro_equipment_status": "Metro İstanbul'un kullanılamaz olarak kaydettiği asansör, yürüyen merdiven ve yürüyen bantları "
    "döner. `station` (ör. \"Kartal\"), `line` (ör. \"M2\") ve `group` (\"Asansör\", \"Yürüyen Merdiven\", \"Yürüyen Bant\") "
    "isteğe bağlı süzgeçlerdir. İstasyon verilirse `data.station` o istasyonun asansör durumunu özetler. Her kayıtta İBB'nin "
    "tipi (Arıza, Revizyon, Çalıştırılmıyor) ayrı döner. Listede olmayan bir ekipman kullanılabilir diye doğrulanmış DEĞİLDİR: "
    "\"çalışıyor\" deme, \"İBB kaydında arıza yok\" de. `ibb_date` İBB kaydındaki tarihtir; anlamı belgelenmemiştir, dönüş "
    "tarihi olarak söyleme. `uncertainty` kodlarını ve `note` alanını kullanıcıya aktar.",
    "traffic_index": "İstanbul geneli trafik yoğunluk indeksini döner (1 akıcı, 99 kilitli). `window=\"now\"` anlık "
    "değeri, `window=\"24h\"` son 24 saati ve dünkü aynı saatle karşılaştırmayı döner. `now` ayrıca `typical` alanında "
    "anlık değeri bu gün ve saatin İBB geçmişinden (son 28 gün, saatlik) ölçülen ortancasıyla karşılaştırır; hücrede "
    "3'ten az gözlem varsa ya da geçmiş okunamazsa `available: false` ve gerekçe döner.",
    "air_quality_now": "Bir yere en yakın istasyonun güncel hava kalitesi ölçümünü döner. PM10, SO2, O3, NO2, CO "
    "derişimleri ile AQI indeksi ve sağlık durumu metnini içerir. PM2.5 İBB API'sinde yoktur. "
    "Sağlık tavsiyesi değildir.",
    "air_quality_forecast": "Kısa vadeli PM10 tahmini ve önümüzdeki en temiz zaman aralığını döner. İndeks değil "
    "saatlik derişim tahmin edilir, çünkü İBB PM10 indeksini 24 saatlik hareketli ortalamadan hesaplar. "
    "Sağlık tavsiyesi değildir.",
    "plan_journey": "İki nokta arasında araba, metro, tek hatlı otobüs ve yürüyüşü süre ve konforla KARŞILAŞTIRIR. \"Şu an "
    "arabayla mı, metroyla mı?\" sorusunu yanıtlar; adım adım yol tarifi DEĞİLDİR. Her uç için yer adı (`origin`, `destination`; "
    "ör. \"Kadıköy\") ya da koordinat (`origin_lat`/`origin_lon`, `destination_lat`/`destination_lon`; derece, WGS84, İstanbul "
    "içi) ver. Süreler dakika, mesafeler km. Canlı trafik indeksi, İSPARK boş yer, metro duyuruları ve İETT GTFS durak "
    "sıralarından hesaplanır; kullanılan her varsayım (hız, yol katsayısı, otopark arama süresi) sonuçta adıyla ve değeriyle "
    "döner. Yarım koordinat, İstanbul dışı nokta ya da bulunamayan yer adı reddedilir. Hesaplanamayan seçenekler (aktarmalı "
    "otobüs, Boğaz'ı yürüyerek geçmek, GTFS yoksa otobüs) `unavailable_options` içinde gerekçesiyle gelir. Metro seçeneği "
    "istasyon ağı üzerinde hat hat gider (binilen her hat ve her aktarma ayrı bacak); Boğaz'ı yalnızca Marmaray tüpüyle geçer, "
    "Metrobüs ve vapur veride yoktur. Otobüs süresi varsayılan olarak durak başına kalibre edilmemiş 120 sn'den hesaplanır; "
    "kullanılan oran ve gerekçesi `assumptions` içinde döner. Aynı yönde aktarmasız giden diğer hatlar `other_direct_lines` "
    "içinde durak sayısıyla, süresiz gelir. `readings` içindeki `traffic_typical`, anlık trafiği bu saatin ölçülmüş olağan "
    "seviyesiyle kıyaslar.",
    "line_reliability": "Bir İETT hattının belirli saatteki sefer aralığını ve düzenliliğini (kümelenme) döner. "
    "\"500T bu saatte ne sıklıkla gelir, otobüsler kümeleniyor mu?\" sorusunu yanıtlar. `line_code` hat kodu "
    "(ör. \"500T\"); `hour` 0–23 İstanbul saati, verilmezse şu an. Sonuç: ortanca sefer aralığı (dakika), aralıkların "
    "değişim katsayısı (cv) ve etiketi, gözlem ve araç sayısı, ölçüm penceresi. İETT bu ölçüyü yayınlamaz; değerler "
    "projenin kendi araç konumu anlık görüntülerinden (~3,2 dk adımla) hesaplanmış GEÇMİŞTİR, canlı değildir ve "
    "kaçırılan geçişler yüzünden üst sınırdır. Yeterli gözlem yoksa `available: false` ve gerekçe döner "
    "(kaynak: data/reference/line_reliability.json).",
    "ibb_services_search": "İstanbul'daki kamu hizmeti sayfalarından derlenmiş yerel dizinde arama yapar. Her sonuçta kaynak "
    "cümlesi, bağlantısı ve alınma tarihi döner. Abonelik, başvuru, belge, gece metrosu ve sefer saatleri gibi hizmet "
    "sorularında kullan. Cevabı yalnızca "
    "dönen alıntılara dayandır ve her alıntının bağlantısını ver. Dizin sunucuda kurulu değilse ya da doğrulanabilir eşleşme "
    "yoksa `note` döner; o zaman bilgi uydurma, bulunamadığını söyle. Bu araç İBB'ye canlı istek atmaz; dizin önceden kurulur "
    "ve `fetched_at` sayfanın alındığı tarihtir.",
    "city_freshness": "Her veri kaynağının ne kadar güncel olduğunu ve kalan istek bütçesini döner. Bir cevabın ne kadar taze "
    "veriye dayandığını söylemen gerektiğinde bunu çağır. `data_age_seconds` verinin kendi yaşıdır (kaynak bir ölçüm zamanı "
    "bildiriyorsa `reported_at_utc`'den); `age_seconds` yalnızca kaynağın en son ne zaman okunduğudur. Tazelik sorulduğunda "
    "`data_age_seconds` değerini söyle.",
}

#: MCP tools the agent deliberately does not offer its model. ``check_alerts`` evaluates a
#: subscription the *caller* holds (places with coordinates, rules, muted keys); the web
#: agent is asked one question and holds none, so offering the tool would invite the model
#: to invent a subscription. The web page reaches the alert engine through its own route.
NOT_OFFERED: dict[str, str] = {"check_alerts": "needs a client-held subscription the agent does not have"}

#: Parameters the MCP server does not advertise; the agent keeps the same surface.
HIDDEN_PARAMS: dict[str, set[str]] = {"ispark_find_parking": {"with_tariff"}}

PARAM_HINTS: dict[str, str] = {
    "place": "Yer adı, ör. 'Taksim', 'Kadıköy', 'Beşiktaş'.",
    "query": "Aranacak metin.",
    "line_code": "İETT hat kodu, ör. '500T', '34AS'.",
    "line": "Metro hat adı, ör. 'M4'.",
    "stop": "Durak adı veya durak kodu.",
    "name": "İstasyon adı, ör. 'Kartal'.",
    "station": "Metro istasyonu adı, ör. 'Kartal'.",
    "group": "'Asansör', 'Yürüyen Merdiven' ya da 'Yürüyen Bant'; verilmezse üçü de.",
    "window": "'now' ya da '24h'.",
    "horizon_hours": "Kaç saatlik tahmin isteniyor (en fazla 6).",
    "park_id": "İSPARK otopark kimliği (ispark_find_parking sonucundaki park_id).",
    "radius_km": "Arama yarıçapı, kilometre.",
    "min_free": "En az kaç boş yer olsun.",
    "origin": "Başlangıç yeri adı, ör. 'Taksim'. Koordinat verildiyse yalnızca etiket olur.",
    "destination": "Varış yeri adı, ör. 'Kadıköy'. Koordinat verildiyse yalnızca etiket olur.",
    "origin_lat": "Başlangıç enlemi, derece (WGS84); origin_lon ile birlikte verilmeli.",
    "origin_lon": "Başlangıç boylamı, derece (WGS84); origin_lat ile birlikte verilmeli.",
    "destination_lat": "Varış enlemi, derece (WGS84); destination_lon ile birlikte verilmeli.",
    "destination_lon": "Varış boylamı, derece (WGS84); destination_lat ile birlikte verilmeli.",
    "slow_walk": "Yavaş yürüyen kişi: yürüme hızı düşük, aktarma cezası yüksek.",
    "planned": "True ise günün ilk ve son planlanan seferi de döner (tarife, tahmin değil).",
    "hour": "0–23 İstanbul saati; verilmezse şu an.",
    "weekday": "0=Pazartesi … 6=Pazar; verilmezse bugün.",
}

_JSON_TYPES: dict[Any, str] = {str: "string", int: "integer", float: "number", bool: "boolean"}


def _json_type(annotation: Any) -> str:
    """Map a Python annotation onto a JSON Schema type, unwrapping ``X | None``."""
    args = [arg for arg in typing.get_args(annotation) if arg is not type(None)]
    base = args[0] if args else annotation
    return _JSON_TYPES.get(base, "string")


def build_tool_schemas(names: list[str] | None = None) -> list[dict[str, Any]]:
    """OpenAI-style function schemas derived from the ``Nabiz`` method signatures."""
    schemas: list[dict[str, Any]] = []
    for name in names or list(TOOL_DESCRIPTIONS):
        method = getattr(Nabiz, name)
        hints = typing.get_type_hints(method)
        hidden = HIDDEN_PARAMS.get(name, set())
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in inspect.signature(method).parameters.values():
            if param.name in {"self", "return"} or param.name in hidden:
                continue
            schema: dict[str, Any] = {"type": _json_type(hints.get(param.name, str))}
            if param.name in PARAM_HINTS:
                schema["description"] = PARAM_HINTS[param.name]
            if param.default is not inspect.Parameter.empty and param.default is not None:
                schema["default"] = param.default
            properties[param.name] = schema
            if param.default is inspect.Parameter.empty:
                required.append(param.name)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": TOOL_DESCRIPTIONS[name],
                    "parameters": {"type": "object", "properties": properties, "required": required},
                },
            }
        )
    return schemas
