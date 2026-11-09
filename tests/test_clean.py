"""Unit tests for worker/clean.py: each rejection reason, duplicates, id order."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from clean import clean_records


def rec(id_, text, raw):
    return {"id": id_, "text": text, "teacher_raw": raw}


def good(text="set alarm for seven am tomorrow"):
    return json.dumps({"intent": "alarm_set", "date": "tomorrow", "time": "seven am", "place": None})


def test_valid_record_is_kept():
    kept, counts = clean_records([rec("C0001", "set alarm for seven am tomorrow", good())])
    assert counts == {"input": 1, "a": 0, "b": 0, "c": 0, "d": 0, "duplicates": 0, "kept": 1}
    assert kept[0]["id"] == "C0001"


def test_invalid_json_is_rejected_a():
    kept, counts = clean_records([rec("C0001", "set alarm for seven am", "not json")])
    assert counts["a"] == 1 and counts["kept"] == 0


def test_wrong_keys_are_rejected_b():
    raw = json.dumps({"intent": "alarm_set", "date": None, "time": "seven am"})
    kept, counts = clean_records([rec("C0001", "set alarm for seven am", raw)])
    assert counts["b"] == 1 and counts["kept"] == 0


def test_bad_intent_is_rejected_c():
    raw = json.dumps({"intent": "fly_to_moon", "date": None, "time": None, "place": None})
    kept, counts = clean_records([rec("C0001", "set alarm", raw)])
    assert counts["c"] == 1 and counts["kept"] == 0


def test_slot_not_in_command_is_rejected_d():
    raw = json.dumps({"intent": "alarm_set", "date": "tomorrow", "time": "seven am", "place": "paris"})
    kept, counts = clean_records([rec("C0001", "set alarm for seven am tomorrow", raw)])
    assert counts["d"] == 1 and counts["kept"] == 0


def test_duplicate_keeps_smallest_id_and_output_is_in_id_order():
    r1 = rec("C0002", "set alarm for seven am tomorrow", good())
    r2 = rec("C0001", "set alarm for seven am tomorrow", good())
    kept, counts = clean_records([r1, r2])
    assert counts["duplicates"] == 1 and counts["kept"] == 1
    assert kept[0]["id"] == "C0001"
    assert counts["input"] == counts["a"] + counts["b"] + counts["c"] + counts["d"] + counts["duplicates"] + counts["kept"]
