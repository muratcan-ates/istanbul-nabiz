"""P00 D2a: İBB Açık Veri sits in the console's "Bilgi ve planlama", closed, and the citizen copy stays."""

from __future__ import annotations

import re

from conftest import REPO_ROOT

STATIC = REPO_ROOT / "src" / "nabiz" / "console" / "static"


def planning_section(html: str) -> str:
    start = html.index("<span>Bilgi ve planlama</span>")
    return html[start:html.index("</details>\n\n    <details", start)]


def test_open_data_is_the_last_closed_disclosure_of_knowledge_and_planning() -> None:
    html = (STATIC / "console.html").read_text(encoding="utf-8")
    section = planning_section(html)
    disclosure = section[section.index('<details id="open-data-console">'):]
    opening = r"<details id=\"open-data-console\">\s*<summary>Açık veri</summary>\s*<div id=\"open-data-mount\">"
    assert re.search(opening, disclosure)
    assert section.index('id="scenario-mount"') < section.index('id="open-data-mount"')
    assert " open" not in disclosure.split(">", 1)[0]
    for anchor in ("acik-veri-form", "acik-veri-q", "acik-veri-chips", "acik-veri-result"):
        assert f'id="{anchor}"' in disclosure
    assert html.count('<script type="module" src="/js/open_data.js"></script>') == 1
    nav = html[html.index('<nav class="console-nav"'):html.index("</nav>")]
    assert "open-data" not in nav and "acik-veri" not in nav


def test_the_citizen_copy_and_the_shell_are_unchanged() -> None:
    index = (STATIC / "index.html").read_text(encoding="utf-8")
    assert '<section id="acik-veri"' in index and 'id="acik-veri-form"' in index
    shell = (STATIC / "sw.js").read_text(encoding="utf-8")
    assert shell.count("'/js/open_data.js'") == 1
    source = (STATIC / "js" / "open_data.js").read_text(encoding="utf-8")
    assert "#open-data-mount" in source.split("*/", 1)[0]
