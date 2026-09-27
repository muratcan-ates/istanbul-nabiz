from __future__ import annotations

import json
import re

from test_static_a11y import STATIC, node_json

CATALOG = {
    "tr": {
        "ui.skills.add": "Listeme ekle",
        "ui.skills.added": "Program listenize eklendi.",
        "ui.skills.any": "Fark etmez",
        "ui.skills.area_label": "İlgilendiğiniz alanlar",
        "ui.skills.area_limit": "En çok üç alan seçebilirsiniz.",
        "ui.skills.areas_found": "Seçilen alanlar",
        "ui.skills.bad_request": "Seçimleri kontrol edip yeniden deneyin.",
        "ui.skills.bio_name": "Bölgesel İstihdam Ofisleri",
        "ui.skills.bio_title": "Bölgesel İstihdam Ofisleri iş ilanları",
        "ui.skills.bio_unavailable": "İlanları Nabız göremez; sayfa içeriği JavaScript ile yükleniyor, veri alınamadı.",
        "ui.skills.branch_label": "Ne için?",
        "ui.skills.centers_found": "Seçilen ilçedeki merkezler",
        "ui.skills.catalog_missing": "katalogda yok",
        "ui.skills.checklist_error": "Resmî kontrol listesi okunamadı.",
        "ui.skills.checklist_loading": "Kontrol listesi okunuyor.",
        "ui.skills.checklist_disclaimer": "Başvurunuzun durumunu Nabız göremez; kurum doğrulaması değildir.",
        "ui.skills.choose_branch": "Alanları görmek için önce bir dal seçin.",
        "ui.skills.classrooms": "derslik",
        "ui.skills.clear": "Seçimleri temizle",
        "ui.skills.consent": "Seçimlerimi ve listemi bu cihazda hatırla",
        "ui.skills.date_unknown": "bilinmiyor",
        "ui.skills.disclaimer": "Resmî İBB hizmeti değildir.",
        "ui.skills.district_label": "İlçe",
        "ui.skills.erase": "Bu cihazdan sil",
        "ui.skills.erased": "Bu cihazdaki liste silindi.",
        "ui.skills.freshness": "İSMEK kataloğu · kayıtlı · alındı {date}",
        "ui.skills.freshness_unknown": "İSMEK kataloğunun kayıt tarihi okunamadı.",
        "ui.skills.program_catalog": "Eğitim programları",
        "ui.skills.centers_catalog": "Eğitim merkezleri",
        "ui.skills.intro": (
            "İBB’nin Enstitü İstanbul İSMEK kataloğundaki program adlarını seçiminize göre gösterir; "
            "başvuruyu siz yaparsınız."
        ),
        "ui.skills.ismek_name": "Enstitü İstanbul İSMEK",
        "ui.skills.keyword_hint": "Kişisel bilgi yazmayın. En çok 40 karakter.",
        "ui.skills.keyword_label": "Anahtar kelime",
        "ui.skills.list_empty": "Henüz program eklemediniz.",
        "ui.skills.list_limit": "En çok beş program ekleyebilirsiniz.",
        "ui.skills.list_title": "Listem",
        "ui.skills.loaded": "Katalog verisi okundu.",
        "ui.skills.loading": "Katalog okunuyor.",
        "ui.skills.loading_matches": "Eşleşmeler hazırlanıyor.",
        "ui.skills.mode_label": "Eğitim tipi",
        "ui.skills.more": "Daha fazla",
        "ui.skills.nabiz_suggests": "Nabız önerisi",
        "ui.skills.no_terms": "Arama rehberi için bir alan ya da anahtar kelime seçin.",
        "ui.skills.official_from": "Resmî sayfadan",
        "ui.skills.official_group": "Resmî sayfadan",
        "ui.skills.offline": "Katalog şu an okunamadı.",
        "ui.skills.open_bio": "BİO sayfasını aç",
        "ui.skills.open_ismek": "İSMEK’te aç",
        "ui.skills.open_to_load": "Kataloğu okumak için bölümü açın.",
        "ui.skills.optional": "İsteğe bağlı",
        "ui.skills.program_count": "program",
        "ui.skills.programs_found": "Program adları",
        "ui.skills.reason_catalog": "İSMEK kataloğu",
        "ui.skills.reason_choice": "Sizin seçiminiz",
        "ui.skills.remove": "Listeden çıkar",
        "ui.skills.result_count": "{programs} program adı, {centers} merkez",
        "ui.skills.results_title": "Eşleşme sonuçları",
        "ui.skills.saved": "Listemde",
        "ui.skills.search_guide": "Neyi arayacaksınız",
        "ui.skills.self_group": "Sizin işaretiniz",
        "ui.skills.source": "Kaynak",
        "ui.skills.source_turkish": "Source text is Turkish.",
        "ui.skills.step_read_page": "Programın resmî sayfasında gün, saat ve merkezi okudum",
        "ui.skills.step_checked_travel": "Merkeze ulaşımı kontrol ettim",
        "ui.skills.step_applied_myself": "Başvuruyu resmî sitede kendim yaptım",
        "ui.skills.submit": "Eşleşmeleri göster",
        "ui.skills.time_label": "Zaman",
        "ui.skills.title": "Kurs ve iş keşfi",
        "ui.skills.unavailable": "Katalog şu an okunamadı.",
        "ui.skills.why": "Neden bu sonuç?",
        "ui.skills.work_hint": "İşe hazırlanmak istiyorsanız Mesleki ve Teknik Eğitimler dalını seçin.",
    },
    "en": {
        "ui.skills.add": "Add to my list",
        "ui.skills.added": "The program was added to your list.",
        "ui.skills.any": "No preference",
        "ui.skills.area_label": "Areas you are interested in",
        "ui.skills.area_limit": "You can select up to three areas.",
        "ui.skills.areas_found": "Selected areas",
        "ui.skills.bad_request": "Check your selections and try again.",
        "ui.skills.bio_name": "Regional Employment Offices",
        "ui.skills.bio_title": "Regional Employment Offices job listings",
        "ui.skills.bio_unavailable": (
            "Nabız cannot read listings; the page loads its content with JavaScript, "
            "so data was unavailable."
        ),
        "ui.skills.branch_label": "What are you looking for?",
        "ui.skills.centers_found": "Centers in the selected district",
        "ui.skills.catalog_missing": "not in the catalog",
        "ui.skills.checklist_error": "The official checklist could not be read.",
        "ui.skills.checklist_loading": "Reading the checklist.",
        "ui.skills.checklist_disclaimer": "Nabız cannot see your application status; this is not an institutional verification.",
        "ui.skills.choose_branch": "Choose a branch first to see its areas.",
        "ui.skills.classrooms": "classrooms",
        "ui.skills.clear": "Clear selections",
        "ui.skills.consent": "Remember my selections and list on this device",
        "ui.skills.date_unknown": "unknown",
        "ui.skills.disclaimer": "This is not an official İBB service.",
        "ui.skills.district_label": "District",
        "ui.skills.erase": "Delete from this device",
        "ui.skills.erased": "The list on this device was deleted.",
        "ui.skills.freshness": "İSMEK catalog · recorded · retrieved {date}",
        "ui.skills.freshness_unknown": "The catalog retrieval date is unavailable.",
        "ui.skills.program_catalog": "Training programs",
        "ui.skills.centers_catalog": "Training centers",
        "ui.skills.intro": (
            "Shows program names from the İBB Enstitü İstanbul İSMEK catalog based on your selections; "
            "you submit any application yourself."
        ),
        "ui.skills.ismek_name": "Enstitü İstanbul İSMEK",
        "ui.skills.keyword_hint": "Do not enter personal information. Up to 40 characters.",
        "ui.skills.keyword_label": "Keyword",
        "ui.skills.list_empty": "You have not added a program yet.",
        "ui.skills.list_limit": "You can add up to five programs.",
        "ui.skills.list_title": "My list",
        "ui.skills.loaded": "Catalog data was read.",
        "ui.skills.loading": "Reading the catalog.",
        "ui.skills.loading_matches": "Preparing matches.",
        "ui.skills.mode_label": "Training format",
        "ui.skills.more": "More",
        "ui.skills.nabiz_suggests": "Nabız suggestion",
        "ui.skills.no_terms": "Choose an area or keyword for a search guide.",
        "ui.skills.official_from": "From the official page",
        "ui.skills.official_group": "From the official page",
        "ui.skills.offline": "The catalog could not be read right now.",
        "ui.skills.open_bio": "Open the BİO page",
        "ui.skills.open_ismek": "Open in İSMEK",
        "ui.skills.open_to_load": "Open this section to read the catalog.",
        "ui.skills.optional": "Optional",
        "ui.skills.program_count": "programs",
        "ui.skills.programs_found": "Program names",
        "ui.skills.reason_catalog": "İSMEK catalog",
        "ui.skills.reason_choice": "Your selection",
        "ui.skills.remove": "Remove from list",
        "ui.skills.result_count": "{programs} program names, {centers} centers",
        "ui.skills.results_title": "Match results",
        "ui.skills.saved": "In my list",
        "ui.skills.search_guide": "What will you search for?",
        "ui.skills.self_group": "Your checklist",
        "ui.skills.source": "Source",
        "ui.skills.source_turkish": "Source text is Turkish.",
        "ui.skills.step_read_page": "I read the days, times, and center on the official program page",
        "ui.skills.step_checked_travel": "I checked how to reach the center",
        "ui.skills.step_applied_myself": "I applied myself on the official site",
        "ui.skills.submit": "Show matches",
        "ui.skills.time_label": "Time",
        "ui.skills.title": "Course and job discovery",
        "ui.skills.unavailable": "The catalog could not be read right now.",
        "ui.skills.why": "Why this result?",
        "ui.skills.work_hint": "To prepare for work, you can choose the Vocational and Technical Training branch.",
    },
}


def test_catalog_has_exact_tr_and_en_pairs_for_every_module_string() -> None:
    js = ["skills.js", "skills_view.js"]
    keys = set()
    fallbacks = {}
    call_pattern = re.compile(r"t\(\s*(['\"])(ui\.skills\.[^'\"]+)\1\s*,\s*(['\"])((?:\\.|[^\\])*?)\3", re.S)
    key_pattern = re.compile(r"t\(\s*(['\"])(ui\.skills\.[^'\"]+)\1")
    for name in js:
        source = (STATIC / "js" / name).read_text(encoding="utf-8")
        keys.update(match.group(2) for match in key_pattern.finditer(source))
        fallbacks.update({match.group(2): match.group(4).replace("\\'", "'") for match in call_pattern.finditer(source)})
    keys.update({f"ui.skills.step_{name}" for name in ("read_page", "checked_travel", "applied_myself")})
    assert keys == set(CATALOG["tr"]) == set(CATALOG["en"])
    assert all(CATALOG["tr"][key] == value for key, value in fallbacks.items())
    for key in keys:
        assert set(re.findall(r"\{(\w+)\}", CATALOG["tr"][key])) == set(re.findall(r"\{(\w+)\}", CATALOG["en"][key]))


def test_view_helpers_are_pure_escape_text_and_gate_device_storage(tmp_path) -> None:
    view_url = json.dumps((STATIC / "js" / "skills_view.js").as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    tr = json.dumps(CATALOG["tr"], ensure_ascii=False)
    body = f"""
const i18n = await import({i18n_url});
i18n.setCatalogs('tr', {tr}, {tr});
const view = await import({view_url});
const now=1_800_000_000_000;
const valid={{version:1,at:now,choices:{{branch:'',areas:[],keyword:'',district:'',mode:'',time:''}},saved:[],checks:{{}}}};
const markup=view.resultMarkup({{
  available:true, areas:[],
  programs:[{{code:'1',name:'<script>',url:'https://enstitu.ibb.istanbul/portal/x',reasons:[{{from:'choice',text:'excel'}}]}}],
  centers:[], source:{{name:'Enstitü İstanbul İSMEK',license:'Lisans belirtilmemiş',programs_url:'https://enstitu.ibb.istanbul/portal/p',centers_url:'https://enstitu.ibb.istanbul/portal/c'}}
}},[]);
const jobs=view.jobsMarkup({{
  card:{{url:'https://bio.ibb.istanbul/',title:'BİO'}},search_terms:[],label:'Nabız önerisi; ilan değildir'
}});
const emptyChoices={{branch:'',areas:[],keyword:'',district:'',mode:'',time:''}};
const options={{
  branches:['Mesleki ve Teknik Eğitimler'],
  areas:[{{name:'Bilişim Teknolojileri',branch:'Mesleki ve Teknik Eğitimler',programs:153}}],
  districts:['Kadıköy'],modes:[],times:[]
}};
const noBranch=view.formMarkup(options,emptyChoices,false);
const selectedBranch=view.formMarkup(options,{{...emptyChoices,branch:'Mesleki ve Teknik Eğitimler'}},false);
const initial=view.sectionMarkup(null,{{choices:emptyChoices,consent:false,saved:[],checks:[]}},'Open to read',null,{{}},'');
console.log(JSON.stringify({{key:view.STORAGE_KEY,days:view.KEEP_DAYS,maxAreas:view.MAX_AREAS,maxSaved:view.MAX_SAVED,
  valid:view.parseStored(JSON.stringify(valid),now),expired:view.parseStored(JSON.stringify({{...valid,at:now-31*86400000}}),now),
  broken:view.parseStored('{{',now),denied:view.toStored(false,{{}},[],{{}},now),markup,jobs,noBranch,selectedBranch,initial}}));
"""
    values = node_json(tmp_path, {}, f"globalThis.window={{location:{{search:'',origin:'http://localhost'}}}};\n{body}")
    assert values["key"] == "nabiz.skills.v1" and values["days"] == 30
    assert values["maxAreas"] == 3 and values["maxSaved"] == 5
    assert values["valid"]["version"] == 1 and values["expired"] is None and values["broken"] is None
    assert values["denied"] is None
    assert "&lt;script&gt;" in values["markup"] and "<script>" not in values["markup"]
    assert "Sizin seçiminiz" in values["markup"] and 'target="_blank" rel="noopener"' in values["markup"]
    assert 'name="areas"' not in values["noBranch"]
    assert 'name="areas"' in values["selectedBranch"] and '<option lang="tr"' in values["selectedBranch"]
    assert "Neden bu sonuç?" in values["markup"] and "skills-unavailable" not in values["initial"]
    assert "kayıtlı · alındı bilinmiyor" not in values["initial"]
    assert "Eğitim programları" in values["markup"] and "Eğitim merkezleri" in values["markup"]
    assert "0 ilan" not in values["jobs"] and "<ul>" not in values["jobs"]


def test_mount_without_a_known_anchor_does_not_add_styles_or_make_a_request(tmp_path) -> None:
    module_url = json.dumps((STATIC / "js" / "skills.js").as_uri())
    i18n_url = json.dumps((STATIC / "js" / "i18n_text.js").as_uri())
    body = f"""
globalThis.fetch=()=>{{globalThis.calls+=1;return Promise.resolve({{ok:true}})}};
globalThis.calls=0;
globalThis.window={{location:{{search:'',origin:'http://localhost'}},addEventListener:()=>{{}},removeEventListener:()=>{{}}}};
globalThis.document={{querySelector:()=>null,getElementById:()=>null}};
const i18n=await import({i18n_url}); i18n.setCatalogs('tr',{{}},{{}});
const mod=await import({module_url});
console.log(JSON.stringify({{calls,anchors:mod.ANCHORS,style:mod.STYLESHEET,id:mod.SECTION_ID,mounted:mod.mountSkills(document)}}));
"""
    values = node_json(tmp_path, {}, body)
    assert values == {
        "calls": 0,
        "anchors": ["#city-tools", "#hesabim"],
        "style": "/css/skills.css",
        "id": "kurs-is",
        "mounted": None,
    }


def test_css_and_scripts_have_no_motion_colour_literals_or_primary_fill() -> None:
    js = "\n".join((STATIC / "js" / name).read_text(encoding="utf-8") for name in ("skills.js", "skills_view.js"))
    css = (STATIC / "css" / "skills.css").read_text(encoding="utf-8")
    assert "btn-primary" not in js + css and "infinite" not in css
    assert not re.search(r"\b(?:transition|animation)\s*:", css)
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\boklch\(", css)
    assert not any(char in js + css for char in ("—", "–"))
    assert "/js/skills.js" not in (STATIC / "sw.js").read_text(encoding="utf-8")
