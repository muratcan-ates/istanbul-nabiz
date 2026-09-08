"""Tests for the numeric-faithfulness checker, and for the agent that depends on it.

The faithfulness tests are the point of the file: they pin down what counts as an invented
number, because that judgement is the project's central honesty claim and a silent change
to it would silently weaken every eval result.

The agent tests live here too rather than in a file of their own — ``NabizAgent`` is what
consumes the checker, and its two interesting behaviours (repair after a failed check,
answering at all with no model quota) cannot be verified without it.
"""

from __future__ import annotations

import json
import pathlib

import httpx
import pytest
import respx

from ibb_mcp.models import Provenance, ToolResult
from ibb_mcp.tools import Nabiz
from nabiz.agent import LlmConfig, NabizAgent, build_tool_schemas, check_faithfulness, detect_language
from nabiz.agent import agent as agent_module
from nabiz.agent.agent import TOOL_DESCRIPTIONS
from nabiz.agent.llm import LlmUnavailable, available, detect_provider, require

# ======================================================================================
# 1. number extraction and Turkish formatting
# ======================================================================================


def test_turkish_decimal_comma_is_a_decimal_point():
    report = check_faithfulness("Otoparka uzaklık 12,5 km.", {"distance_km": 12.5})
    assert report.passed
    assert [n.value for n in report.checked_numbers] == [12.5]


def test_turkish_thousands_dot_is_a_group_separator():
    report = check_faithfulness("Filoda 1.250 araç var.", {"fleet": 1250})
    assert report.passed
    assert report.checked_numbers[0].value == 1250.0


def test_thousands_dot_reading_is_ambiguous_and_both_readings_are_tried():
    """``1.250`` is 1250 in Turkish and 1.25 in English; either source value supports it."""
    assert check_faithfulness("Değer 1.250.", {"v": 1.25}).passed
    assert check_faithfulness("Değer 1.250.", {"v": 1250}).passed
    assert not check_faithfulness("Değer 1.250.", {"v": 9}).passed


def test_mixed_turkish_grouping_and_decimal():
    report = check_faithfulness("Toplam 12.345,6 km yol.", {"km": 12345.6})
    assert report.passed
    assert report.checked_numbers[0].value == pytest.approx(12345.6)


def test_percentage_is_checked_as_a_plain_number():
    supported = check_faithfulness("Doluluk %45.", {"occupancy_pct": 45})
    invented = check_faithfulness("Doluluk %45.", {"occupancy_pct": 60})
    assert supported.passed
    assert not invented.passed
    assert invented.unsupported_texts == ["45"]


def test_negative_and_zero_values_are_extracted_with_their_sign():
    report = check_faithfulness("Fark -3, boş yer 0.", {"delta": -3, "empty": 0})
    assert report.passed
    assert [n.value for n in report.checked_numbers] == [-3.0, 0.0]


def test_a_negative_number_is_not_supported_by_its_positive_twin():
    report = check_faithfulness("Fark -3 birim.", {"delta": 3})
    assert not report.passed
    assert report.unsupported_texts == ["-3"]


def test_a_hyphenated_range_is_two_positive_numbers_not_a_negative():
    report = check_faithfulness("Otobüs 12-15 dakika içinde gelir.", {"low": 12, "high": 15})
    assert report.passed
    assert [n.value for n in report.checked_numbers] == [12.0, 15.0]


# ======================================================================================
# 2. what is deliberately not a quantity
# ======================================================================================


def test_dates_and_clock_times_are_not_quantities():
    report = check_faithfulness("2026-09-08 tarihinde, saat 09:15'te ölçüldü.", {})
    assert report.passed
    assert report.checked_numbers == []


def test_turkish_date_format_is_not_a_quantity():
    report = check_faithfulness("Güncelleme: 08.09.2026 05:10:17.", {})
    assert report.passed
    assert report.checked_numbers == []


def test_a_duration_is_a_quantity_even_though_it_is_about_time():
    report = check_faithfulness("Otobüs 13 dakika sonra gelir.", {"eta_minutes": 13})
    assert [n.value for n in report.checked_numbers] == [13.0]


def test_list_markers_and_line_identifiers_are_skipped():
    answer = "1. M4 hattında sorun yok.\n2. T1 tramvayı çalışıyor."
    report = check_faithfulness(answer, {})
    assert report.passed
    assert report.checked_numbers == []


def test_a_bus_line_code_is_a_name_not_a_quantity():
    """``500T`` and ``34AS`` are identifiers. Checking their digits would flag a correct
    answer whenever the evidence happened not to contain the number 500, so digits glued
    to letters are skipped in both directions."""
    report = check_faithfulness("500T ve 34AS hatları geliyor, 3 araç var.", {"count": 3})
    assert report.passed
    assert [n.value for n in report.checked_numbers] == [3.0]


# ======================================================================================
# 3. rounding tolerance
# ======================================================================================


def test_rounding_up_from_a_fraction_is_allowed():
    """0.9 may be written as 1: |0.9 - 1| <= 0.5, the tolerance for a 0-decimal number."""
    assert check_faithfulness("Yaklaşık 1 dakika.", {"eta_minutes": 0.9}).passed


def test_rounding_to_one_decimal_is_allowed():
    assert check_faithfulness("PM10 12,5 µg/m³.", {"pm10": 12.47}).passed


def test_rounding_tolerance_shrinks_as_precision_grows():
    """12,5 tolerates ±0,05 — so 12,47 is fine and 12,7 is not."""
    assert check_faithfulness("PM10 12,5.", {"pm10": 12.47}).passed
    assert not check_faithfulness("PM10 12,5.", {"pm10": 12.7}).passed


def test_off_by_one_integers_are_not_rounding():
    report = check_faithfulness("250 otopark var.", {"count": 249})
    assert not report.passed
    assert report.unsupported[0].text == "250"


# ======================================================================================
# 4. where support may be found
# ======================================================================================


def test_deeply_nested_tool_results_are_searched():
    payload = {
        "data": {"parks": [{"name": "Zincirlikuyu", "detail": {"empty": [7, 12]}}]},
        "provenance": {"age": "8 dk önce"},
    }
    report = check_faithfulness("Zincirlikuyu'nda 12 boş yer var, veri 8 dakikalık.", payload)
    assert report.passed


def test_numbers_inside_source_strings_count_as_support():
    """The İSPARK tariff arrives as free text; quoting a price from it is not invention."""
    payload = {"tariff": "İlk 1 saat 30 TL, sonraki her saat 15 TL"}
    assert check_faithfulness("İlk 1 saat 30 TL.", payload).passed
    assert not check_faithfulness("İlk 1 saat 90 TL.", payload).passed


def test_a_list_of_pydantic_tool_results_is_searched():
    results = [
        ToolResult(data={"index": 42}, provenance=Provenance(source="traffic", source_url="x")),
        ToolResult(data={"count": 3}, provenance=Provenance(source="ispark", source_url="y")),
    ]
    assert check_faithfulness("Trafik indeksi 42, 3 otopark boş.", results).passed


def test_a_json_string_payload_is_parsed_before_searching():
    assert check_faithfulness("Boş yer 18.", json.dumps({"data": {"empty": 18}})).passed


def test_a_number_the_user_supplied_is_not_a_fabrication():
    question = "Taksim'e 20 dakika sonra varıyorum, otopark var mı?"
    assert check_faithfulness("20 dakika sonra Taksim'de 3 otopark açık olur.", {"count": 3}, question=question).passed


def test_the_same_number_without_the_question_is_unsupported():
    assert not check_faithfulness("20 dakika sonra 3 otopark açık.", {"count": 3}).passed


# ======================================================================================
# 5. the report itself
# ======================================================================================


def test_an_answer_with_no_numbers_passes():
    report = check_faithfulness("M4 hattında bildirilmiş bir arıza yok.", {"count": 0})
    assert report.passed
    assert report.checked_numbers == []
    assert "sayı yok" in report.explanation


def test_an_unsupported_number_is_caught_and_explained():
    report = check_faithfulness("Zincirlikuyu'nda 47 boş yer var.", {"data": {"empty": 12}})
    assert not report.passed
    assert report.unsupported_texts == ["47"]
    assert "47" in report.explanation
    assert report.checked_numbers[0].matched is None
    assert "47" in report.repair_instruction("tr")
    assert "47" in report.repair_instruction("en")


def test_a_supported_number_records_the_value_that_supported_it():
    report = check_faithfulness("Yaklaşık 8 dakika.", {"eta_minutes": 7.6})
    assert report.passed
    assert report.checked_numbers[0].matched == pytest.approx(7.6)
    assert report.source_value_count >= 1


def test_a_passing_report_offers_no_repair_instruction():
    assert check_faithfulness("Hiç sayı yok.", {}).repair_instruction() == ""


# ======================================================================================
# 6. the agent that uses the checker
# ======================================================================================

FAKE_LLM = LlmConfig(base_url="http://fake-llm/v1", api_key="k", model="test-model", provider="openai_compatible")


@pytest.fixture
def agent(ctx) -> NabizAgent:
    """An agent over the offline fixtures with no model configured."""
    return NabizAgent(Nabiz(ctx), config=LlmConfig(), system_prompt="test prompt")


def _completion(content=None, tool_calls=None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(tool_calls)
        ]
    return {"model": "test-model", "choices": [{"message": message, "finish_reason": "stop"}], "usage": {"total_tokens": 15}}


def test_tool_schemas_cover_the_twelve_mcp_tools():
    schemas = build_tool_schemas()
    names = [schema["function"]["name"] for schema in schemas]
    assert len(names) == 12
    assert set(names) == set(TOOL_DESCRIPTIONS)
    for schema in schemas:
        assert schema["function"]["description"].strip()


def test_tool_schema_types_and_required_fields_come_from_the_signature():
    schema = next(s for s in build_tool_schemas() if s["function"]["name"] == "ispark_find_parking")["function"]
    properties = schema["parameters"]["properties"]
    assert properties["radius_km"]["type"] == "number"
    assert properties["min_free"]["type"] == "integer"
    assert properties["open_now"]["type"] == "boolean"
    assert schema["parameters"]["required"] == []  # every parameter has a default
    assert "with_tariff" not in properties  # the MCP server does not advertise it either
    arrivals = next(s for s in build_tool_schemas() if s["function"]["name"] == "iett_next_arrivals")["function"]
    assert arrivals["parameters"]["required"] == ["line_code", "stop"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Taksim'de hangi otoparkta yer var?", "ispark_find_parking"),
        ("M4'te arıza var mı?", "metro_status"),
        ("Kartal istasyonunda asansör var mı?", "metro_station_info"),
        ("Beşiktaş'ta hava kalitesi nasıl?", "air_quality_now"),
        ("Beşiktaş'ta koşu için hava ne zaman uygun?", "air_quality_forecast"),
        ("Şu an trafik nasıl?", "traffic_index"),
        ("Verinin yaşı ne kadar?", "city_freshness"),
    ],
)
def test_deterministic_routing_picks_the_journey_tool(agent: NabizAgent, question: str, expected: str):
    assert agent.route(question)[0] == expected


def test_deterministic_routing_refuses_to_invent_a_place(agent: NabizAgent):
    assert agent.route("hava kalitesi nasıl?") == ("", {"reason": "place"})


@pytest.mark.parametrize("question", ["M4'te arıza var mı?", "M4te arıza var mı?", "M4ün durumu ne?"])
def test_a_metro_code_survives_its_turkish_case_ending(agent: NabizAgent, question: str):
    assert agent.route(question) == ("metro_status", {"line": "M4"})


def test_a_bus_line_outranks_the_word_metro_in_the_question(agent: NabizAgent):
    """"500T 4. Levent metro durağına ne zaman gelir" is a bus question, not a metro one."""
    tool, arguments = agent.route("500T 4. Levent metro durağına ne zaman gelir?")
    assert tool == "iett_next_arrivals"
    assert arguments["line_code"] == "500T"
    assert "Levent" in arguments["stop"]


def test_detect_language():
    assert detect_language("Taksim'de otopark var mı?") == "tr"
    assert detect_language("Which car parks near Taksim have space?") == "en"


async def test_deterministic_mode_answers_and_cites_without_a_model(agent: NabizAgent):
    answer = await agent.ask("Kartal istasyonunda asansör var mı?")
    assert answer.mode == "deterministic"
    assert answer.tool_names == ["metro_station_info"]
    assert "asansör" in answer.text
    assert answer.faithfulness.passed, answer.faithfulness.explanation
    assert answer.citations[0]["source"] == "metro_stations"
    assert "CC BY 4.0" in answer.text


async def test_deterministic_mode_asks_for_a_place_instead_of_guessing(agent: NabizAgent):
    answer = await agent.ask("hava kalitesi nasıl?")
    assert answer.tool_calls == []
    assert "Hangi semt" in answer.text


async def test_a_failing_tool_becomes_a_message_not_an_exception(agent: NabizAgent):
    record = await agent._call_tool("metro_station_info", {"name": "Yokistasyon"})
    assert record.ok is False
    assert "bulamadım" in (record.error or "")


async def test_model_loop_calls_a_tool_then_answers(ctx):
    agent = NabizAgent(Nabiz(ctx), config=FAKE_LLM, system_prompt="test prompt")
    with respx.mock:
        respx.post("http://fake-llm/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_completion(tool_calls=[("metro_status", {"line": "M4"})])),
                httpx.Response(200, json=_completion(content="M4 için bildirilmiş 0 duyuru var.")),
            ]
        )
        answer = await agent.ask("M4'te arıza var mı?")
    assert answer.mode == "llm"
    assert answer.tool_names == ["metro_status"]
    assert answer.faithfulness.passed
    assert answer.usage["total_tokens"] == 30
    assert answer.citations[0]["tool"] == "metro_status"


async def test_an_unsupported_number_triggers_exactly_one_repair(ctx):
    agent = NabizAgent(Nabiz(ctx), config=FAKE_LLM, system_prompt="test prompt")
    with respx.mock:
        route = respx.post("http://fake-llm/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_completion(tool_calls=[("traffic_index", {"window": "now"})])),
                httpx.Response(200, json=_completion(content="Trafik indeksi 91.")),
                httpx.Response(200, json=_completion(content="Trafik indeksi 60.")),
            ]
        )
        answer = await agent.ask("Şu an trafik nasıl?")
    assert route.call_count == 3
    assert answer.repaired is True
    assert answer.faithfulness.passed
    assert answer.warnings == []


async def test_a_hallucination_that_survives_repair_is_returned_flagged(ctx):
    agent = NabizAgent(Nabiz(ctx), config=FAKE_LLM, system_prompt="test prompt")
    with respx.mock:
        respx.post("http://fake-llm/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_completion(tool_calls=[("traffic_index", {"window": "now"})])),
                httpx.Response(200, json=_completion(content="Trafik indeksi 91.")),
                httpx.Response(200, json=_completion(content="Yine 91 diyorum.")),
            ]
        )
        answer = await agent.ask("Şu an trafik nasıl?")
    assert answer.faithfulness.passed is False
    assert answer.faithfulness.unsupported_texts == ["91"]
    assert answer.warnings and "sadakat" in answer.warnings[0]


async def test_a_dead_endpoint_falls_back_to_deterministic_mode(ctx):
    agent = NabizAgent(Nabiz(ctx), config=FAKE_LLM, system_prompt="test prompt")
    with respx.mock:
        respx.post("http://fake-llm/v1/chat/completions").mock(return_value=httpx.Response(500, text="no quota"))
        answer = await agent.ask("Şu an trafik nasıl?")
    assert answer.mode == "deterministic"
    assert "İstanbul trafik" in answer.text
    assert any("deterministic" in warning for warning in answer.warnings)


# ======================================================================================
# 7. the model switch
# ======================================================================================


def test_llm_config_reads_the_environment_and_classifies_the_provider():
    config = LlmConfig.from_env(
        {"NABIZ_LLM_BASE_URL": "https://r.openai.azure.com/openai/v1/", "NABIZ_LLM_MODEL": "gpt-4.1-mini"}
    )
    assert config.provider == "azure_openai"
    assert config.base_url.endswith("/v1")  # trailing slash trimmed
    assert available(config)


def test_llm_config_falls_back_to_the_unprefixed_names():
    config = LlmConfig.from_env({"LLM_BASE_URL": "http://localhost:5273/v1"}, probe=False)
    assert config.provider == "foundry_local"


def test_llm_config_without_configuration_is_provider_none():
    config = LlmConfig.from_env({}, probe=False)
    assert config.provider == "none"
    assert not available(config)
    with pytest.raises(LlmUnavailable) as excinfo:
        require(config)
    assert "NABIZ_LLM_BASE_URL" in str(excinfo.value)


def test_provider_detection():
    assert detect_provider("https://x.openai.azure.com/openai/v1") == "azure_openai"
    assert detect_provider("http://localhost:5273/v1") == "foundry_local"
    assert detect_provider("https://models.example.com/v1") == "openai_compatible"


def test_the_system_prompt_ships_with_the_package():
    prompt = pathlib.Path(__file__).resolve().parents[1] / "src" / "nabiz" / "agent" / "system_prompt.md"
    text = prompt.read_text(encoding="utf-8")
    assert "sağlık tavsiyesi değildir" in text.lower()
    assert "stop_sequence" in text


# ======================================================================================
# 8. regressions found in adversarial review
# ======================================================================================


def test_a_source_timestamp_does_not_license_an_invented_count():
    """Every payload carries ``observed_at``. If its digits counted as support, the month
    and the day would silently license exactly the sizes of number a model invents."""
    payload = {
        "data": {"count": 3},
        "provenance": {"observed_at": "2026-09-08T09:15:33+03:00", "age": "0 sn önce"},
    }
    assert check_faithfulness("Taksim çevresinde 3 otopark var.", payload).passed
    for invented in ("9", "8", "15", "33", "2026"):
        report = check_faithfulness(f"Taksim çevresinde {invented} otopark var.", payload)
        assert not report.passed, f"{invented} was supported by the timestamp alone"


def test_an_iso_date_does_not_manufacture_negative_support():
    payload = {"provenance": {"observed_at": "2026-09-08T09:15:33+03:00"}}
    assert not check_faithfulness("Fark -8 birim.", payload).passed


def test_a_quoted_tariff_still_supports_its_prices():
    """The mask must not cost rule 4 its real job."""
    payload = {"tariff": "İlk 1 saat 30 TL, sonraki her saat 15 TL"}
    assert check_faithfulness("İlk saat 30 TL, sonrası 15 TL.", payload).passed


async def test_prose_written_before_the_tool_results_is_never_the_answer(ctx):
    """A reply may carry chatter *and* tool calls. When the step budget ends on such a
    reply, that chatter predates the evidence, so the loop must still force a real answer."""
    agent = NabizAgent(Nabiz(ctx), config=FAKE_LLM, system_prompt="test prompt")
    with respx.mock:
        route = respx.post("http://fake-llm/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(200, json=_completion("Trafiğe bakıyorum…", [("traffic_index", {"window": "now"})])),
                httpx.Response(200, json=_completion("Bir de tazeliğe bakayım…", [("city_freshness", {})])),
                httpx.Response(200, json=_completion(content="Trafik indeksi 60.")),
            ]
        )
        answer = await agent.ask("Şu an trafik nasıl?", max_steps=2)
    assert route.call_count == 3
    assert answer.text == "Trafik indeksi 60."


def test_an_airport_question_is_not_an_air_quality_question(agent: NabizAgent):
    """The exclusion has to be a prefix test: "havalimanına" is the form people write."""
    for question in ("Havalimanına nasıl giderim?", "Havalimanında ne var?", "Havaalanına gidiyorum"):
        assert agent.route(question)[0] != "air_quality_now", question


@pytest.mark.parametrize(
    ("question", "expected_stop"),
    [
        ("500T otobüsü 4. Levent durağına ne zaman gelir?", "4. Levent"),
        ("500T hattı Şifa durağına kaç dakika sonra gelir?", "Şifa"),
        ("500T 4. Levent metro durağına ne zaman gelir?", "4. Levent metro"),
    ],
)
def test_the_line_code_is_not_swallowed_into_the_stop_name(agent: NabizAgent, question: str, expected_stop: str):
    tool, arguments = agent.route(question)
    assert tool == "iett_next_arrivals"
    assert arguments["line_code"] == "500T"
    assert arguments["stop"] == expected_stop


async def test_an_out_of_scope_question_is_refused_not_answered_with_freshness(agent: NabizAgent):
    """"How do I get to the airport?" has no tool. Dumping data ages at it would be a
    non sequitur wearing an answer's clothes."""
    answer = await agent.ask("Havalimanına nasıl giderim?")
    assert answer.tool_calls == []
    assert "yanıtlayamıyorum" in answer.text


def test_a_freshness_question_routes_on_its_keywords_not_on_the_catch_all(agent: NabizAgent):
    for question in ("Verinin yaşı ne kadar?", "Veri ne kadar güncel?", "Bu veri güncel mi?"):
        assert agent.route(question)[0] == "city_freshness", question


async def test_a_relayed_tool_error_is_evidence_not_a_fabrication(agent: NabizAgent):
    """The error text names the lines that do serve the stop. Those numbers came from the
    tool, so flagging them would punish the agent for relaying the error verbatim."""
    answer = await agent.ask("500T hattı Şifa durağına kaç dakika sonra gelir?")
    assert answer.tool_calls[0].ok is False
    assert answer.faithfulness.passed, answer.faithfulness.explanation


def test_the_attribution_line_never_counts_as_an_invented_number():
    """"CC BY 4.0" is boilerplate the template always appends; it must neither fail the
    check nor supply the values 4 and 0 to everything else."""
    assert check_faithfulness("Hiç veri yok.\nKaynak: İBB Açık Veri (CC BY 4.0).", None).passed
    assert not check_faithfulness("4 otopark var.\nKaynak: İBB Açık Veri (CC BY 4.0).", None).passed


async def test_a_failed_check_is_warned_about_in_deterministic_mode_too(agent: NabizAgent, monkeypatch):
    """A hand-written template can grow a numeric constant. When it does, the failure must
    surface as a warning here exactly as it does on the model path."""
    monkeypatch.setitem(agent_module._RENDERERS, "traffic_index", lambda data: ["Sabit 777 sayısı."])
    answer = await agent.ask("Şu an trafik nasıl?")
    assert answer.faithfulness.passed is False
    assert any("sadakat" in warning for warning in answer.warnings)
