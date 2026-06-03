"""Tests for the tolerant JSON extractor in the rubric grader — the grader reply
often wraps the object in prose or a ```json fence even under --json-schema."""
import pytest
from evals.lib.rubric import _extract_json_object


def test_pure_json():
    assert _extract_json_object('{"score": 85, "overall_pass": true}')["score"] == 85


def test_fenced_json():
    txt = "Here is the result:\n\n```json\n{\"score\": 70, \"overall_pass\": false}\n```"
    assert _extract_json_object(txt)["score"] == 70


def test_prose_prefixed_json():
    # The exact failure mode reproduced locally.
    txt = 'No skills needed.\n\n```json\n{\n  "score": 85,\n  "overall_pass": true,\n  "checks": []\n}\n```'
    out = _extract_json_object(txt)
    assert out["score"] == 85 and out["overall_pass"] is True


def test_bare_object_in_prose_no_fence():
    txt = 'The verdict is {"score": 60, "overall_pass": false, "checks": []} per the rubric.'
    assert _extract_json_object(txt)["score"] == 60


def test_no_json_raises():
    with pytest.raises(ValueError):
        _extract_json_object("there is no json here")
