"""Tests for eventloom.contrib.pydantic_v1.json_parser — previously had zero
coverage anywhere (ported from the untracked pyd_v1/ prototype)."""

from eventloom.contrib.pydantic_v1.json_parser import parse_partial_json, repair_partial_json


def test_repair_closes_dangling_open_string():
    assert repair_partial_json('{"name": "Ad') == '{"name": "Ad"}'


def test_repair_strips_trailing_comma():
    assert repair_partial_json('{"a": 1,') == '{"a": 1}'


def test_repair_strips_trailing_key_with_no_colon():
    assert repair_partial_json('{"a": 1, "b') == '{"a": 1}'


def test_repair_strips_trailing_colon_and_its_key():
    assert repair_partial_json('{"a": 1, "b":') == '{"a": 1}'


def test_repair_strips_partial_boolean_literal():
    assert repair_partial_json('{"a": tru') == "{}"


def test_repair_strips_partial_null_literal():
    assert repair_partial_json('{"a": nul') == "{}"


def test_repair_closes_open_array_and_object():
    assert repair_partial_json('{"items": [1, 2') == '{"items": [1, 2]}'


def test_repair_empty_input_returns_empty_object():
    assert repair_partial_json("") == "{}"
    assert repair_partial_json("   ") == "{}"


def test_repair_handles_escaped_quote_inside_open_string():
    result = repair_partial_json(r'{"a": "quote \" inside')
    assert result == r'{"a": "quote \" inside"}'


def test_parse_partial_json_returns_none_for_unparseable_leftover():
    # A trailing bare '-' isn't stripped by any phase-2 rule — json.loads
    # should fail on the repaired string, and parse_partial_json returns
    # None rather than raising.
    assert parse_partial_json('{"a": -') is None


def test_parse_partial_json_returns_none_for_empty_or_blank():
    assert parse_partial_json("") is None
    assert parse_partial_json("   ") is None


def test_parse_partial_json_returns_none_for_non_dict_top_level():
    assert parse_partial_json("[1, 2, 3]") is None


def test_parse_partial_json_returns_dict_for_complete_json():
    assert parse_partial_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}


def test_parse_partial_json_progressively_grows_across_simulated_tokens():
    # Simulates repeated calls with an accumulating buffer, as base.py does.
    chunks = ['{"na', 'me": "A', 'da", "ag', 'e": 3', '6}']
    accumulated = ""
    results = []
    for chunk in chunks:
        accumulated += chunk
        results.append(parse_partial_json(accumulated))

    # Not every intermediate chunk necessarily parses (e.g. mid-key), but the
    # final one always does and reflects the complete data.
    assert results[-1] == {"name": "Ada", "age": 36}
    assert all(r is None or isinstance(r, dict) for r in results)
