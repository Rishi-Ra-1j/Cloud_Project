"""Unit tests for the output schema (data/schema.json, kit): 4 keys, 8 intents."""
import json
from pathlib import Path

SCHEMA = json.loads((Path(__file__).resolve().parents[1] / "data" / "schema.json").read_text())


def test_schema_has_exactly_four_keys():
    assert SCHEMA["keys"] == ["intent", "date", "time", "place"]


def test_schema_has_eight_intents():
    assert len(SCHEMA["intents"]) == 8
    assert "alarm_set" in SCHEMA["intents"] and "recommendation_events" in SCHEMA["intents"]


def test_json_schema_forbids_extra_properties():
    assert SCHEMA["json_schema"]["additionalProperties"] is False
    assert SCHEMA["json_schema"]["required"] == ["intent", "date", "time", "place"]
