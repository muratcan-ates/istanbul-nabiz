"""Small server-rendered HTML templates for the stop page and its A6 print card."""

from __future__ import annotations

from html import escape
from typing import Any
from urllib.parse import quote

from ibb_mcp.config import ATTRIBUTION


def _document(title: str, body: str, *, body_class: str = "stop-page") -> str:
    return f"""<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark"><title>{escape(title)}</title>
<link rel="stylesheet" href="/css/tokens.css"><link rel="stylesheet" href="/css/base.css">
<link rel="stylesheet" href="/css/stop_card.css"></head>
<body class="{body_class}"><p class="stop-band">Resmî İBB hizmeti değildir. Bağımsız öğrenci projesi.</p>
{body}</body></html>"""


def render_code_form(error: str | None = None) -> str:
    alert = f'<p class="stop-error" role="alert">{escape(error)}</p>' if error else ""
    body = f"""<main id="main" class="stop-card" aria-labelledby="form-title">
<h1 id="form-title">Durak kartı</h1>{alert}
<form class="stop-form" method="get" action="/d"><label for="kod">Durak kodu</label>
<input id="kod" name="kod" inputmode="numeric" pattern="[0-9]{{1,9}}" maxlength="9" autocomplete="off" required>
<button type="submit">Göster</button></form>
<p>Durak direğindeki kodu girin.</p></main>
<footer class="stop-foot"><p>Bu sayfada yapay zekâ kullanılmaz. Soru sormak için asistana geçin.</p>
<p>{ATTRIBUTION}</p></footer>"""
    return _document("Durak kartı · İstanbul Nabız", body)


def render_stop_missing(message: str) -> str:
    body = f"""<main id="main" class="stop-card" aria-labelledby="missing-title">
<h1 id="missing-title">{escape(message)}</h1><p>Durak direğindeki kodu kontrol edin.</p>
{_render_code_form_body()}</main>
<footer class="stop-foot"><p>Bu sayfada yapay zekâ kullanılmaz. Soru sormak için asistana geçin.</p>
<p>{ATTRIBUTION}</p></footer>"""
    return _document("Durak bulunamadı · İstanbul Nabız", body)


def _render_code_form_body() -> str:
    return """<form class="stop-form" method="get" action="/d"><label for="kod">Durak kodu</label>
<input id="kod" name="kod" inputmode="numeric" pattern="[0-9]{1,9}" maxlength="9" autocomplete="off" required>
<button type="submit">Göster</button></form>"""


def _line_rows(data: dict[str, Any]) -> str:
    lines = data.get("lines") or []
    if not lines:
        message = "Bu sunucuda hat listesi yüklü değil." if not data.get("lines_known") else "Bu durak için hat kaydı bulunamadı."
        return f'<p class="stop-muted">{message}</p>'
    rows = []
    for item in lines:
        line = escape(str(item.get("line", "")))
        display = item.get("display")
        if display is None:
            href = f"/d/{quote(str(data['code']), safe='')}?hat={quote(str(item.get('line', '')), safe='')}"
            when = f'<a href="{escape(href, quote=True)}">Varışı göster</a>'
        elif item.get("minutes") is not None:
            when = f"<b>{escape(str(display))}</b>"
        else:
            when = escape(str(display))
        rows.append(
            f'<li class="stop-line"><span class="stop-line-code">{line}</span> <span class="stop-line-when">{when}</span></li>'
        )
    return f'<ul class="stop-lines">{"".join(rows)}</ul>'


def _alternative(metro: dict[str, Any]) -> str:
    alternative = metro.get("alternative")
    if not alternative:
        return (
            "<p>İBB kaydında asansör arızası görünmeyen yakın bir istasyon bulunamadı. "
            '<a href="tel:153">153 ile teyit edin</a>.</p>'
        )
    station = escape(str(alternative.get("station") or ""))
    line = escape(str(alternative.get("line") or ""))
    minutes = alternative.get("extra_minutes")
    duration = (
        f" · istasyonlar arası tahminen {int(minutes)} dk (dönüş dahil değil)"
        if isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
        else " · süre bilinmiyor"
    )
    reason = alternative.get("reason")
    reason_html = f"<p>{escape(str(reason))}</p>" if reason else ""
    approval = "Operatör onaylı (simüle)" if metro.get("operator_approved") else "Operatör onayı yok"
    ask_href = escape(str(metro.get("ask_href") or ""), quote=True)
    return (
        f"<p>Adımsız alternatif: {station} ({line}){duration}</p>{reason_html}"
        f'<p>{approval}</p><p><a href="{ask_href}">Asistana sor: adımsız yol</a></p>'
    )


def _metro_section(metro: dict[str, Any] | None) -> str:
    if not metro:
        return ""
    station = escape(str(metro.get("station") or ""))
    lines = [escape(str(line)) for line in metro.get("lines") or []]
    label = f"{station} ({', '.join(lines)})" if lines else station
    status = metro.get("lift_status")
    state_class = status if status in {"working", "out_of_service", "unknown"} else "unknown"
    stale = '<p class="stop-stale">Kayıt eski olabilir.</p>' if metro.get("stale") else ""
    extra = _alternative(metro) if status == "out_of_service" else ""
    return f"""<section class="stop-metro" aria-labelledby="metro-title">
<h2 id="metro-title">Yakındaki raylı istasyon: {label}</h2>
<p>Duraktan {int(metro.get("distance_m") or 0)} m.</p>
<p class="stop-lift is-{state_class}">{escape(str(metro.get("lift_line") or "Asansör durumu doğrulanamadı"))}</p>
{stale}{extra}</section>"""


def render_stop_page(data: dict[str, Any]) -> str:
    code, name = escape(str(data["code"])), escape(str(data["name"]))
    direction = data.get("direction")
    direction_line = f" · Yön: {escape(str(direction))}" if direction else ""
    offline = (
        '<p class="stop-offline">Kayıtlı veri: bu sunucu çevrimdışı çalışıyor, varışlar canlı değil.</p>'
        if data.get("offline")
        else ""
    )
    question = (
        f"{data['code']} kodlu durağa {data['lines'][0]['line']} ne zaman gelir?"
        if data.get("lines")
        else f"{data['name']} durağı"
    )
    ask = f"/?q={quote(question, safe='')}"
    body = f"""<main id="main" class="stop-card" aria-labelledby="stop-title">
<h1 id="stop-title">{name}</h1><p class="stop-meta">Durak kodu {code}{direction_line}</p>{offline}
<section aria-labelledby="lines-title"><h2 id="lines-title">Hatlar ve varış</h2>{_line_rows(data)}
<p>Varış tek dakika olarak gösterilir. Doğrulanamazsa sayı gösterilmez.</p>
<p>Varışlar tahminidir; resmî İETT bilgisi değildir.</p></section>
{_metro_section(data.get("metro"))}
<nav class="stop-actions" aria-label="Durak kartı işlemleri"><a class="stop-action" href="/d/{code}">Yenile</a>
<a class="stop-action" href="{escape(ask, quote=True)}">Asistana sor</a>
<a class="stop-action" href="/d/{code}/yazdir">Kartı yazdır</a></nav>
</main><footer class="stop-foot"><p>Bu sayfada yapay zekâ kullanılmaz. Soru sormak için asistana geçin.</p>
<p>{ATTRIBUTION}</p></footer>"""
    return _document(f"{name} durağı · İstanbul Nabız", body)


def render_print_card(data: dict[str, Any], qr: str | None) -> str:
    code, name = escape(str(data["code"])), escape(str(data["name"]))
    lines = ", ".join(escape(str(item["line"])) for item in data.get("lines") or [])
    line_html = f'<p class="print-lines">Hatlar: {lines}</p>' if lines else ""
    qr_html = qr or '<p class="print-qr-missing">QR üretici kurulu değil. Bağlantıyı elle yazın:</p>'
    url = escape(str(data["url"]))
    body = f"""<article class="print-card" aria-labelledby="print-title"><p class="print-band">İstanbul Nabız · Durak kartı</p>
<h1 id="print-title">{name}</h1><p class="print-code">Durak kodu {code}</p>{line_html}
<figure class="print-qr">{qr_html}<figcaption class="print-url">{url}</figcaption></figure>
<p class="print-howto">Telefonunuzun kamerasıyla okutun: canlı varış ve asansör kaydı.</p>
<p class="print-band print-band-bottom">Resmî İBB hizmeti değildir. İBB Açık Veri Portalı, CC BY 4.0.</p></article>
<p class="print-hint no-print">Yazdırmak için tarayıcının Yazdır komutunu kullanın; kağıt boyutu A6.</p>
<a class="stop-action no-print" href="/d/{code}">Durak sayfasına dön</a>"""
    return _document(f"{name} durağı kartı · İstanbul Nabız", body, body_class="stop-print")
