import json

import pytest
from pydantic import ValidationError

from film_transcriber.core.models import (
    ASRResult,
    ProcessingMetrics,
    Segment,
    TranscriptionResult,
)
from film_transcriber.exporters import render_json, render_srt, render_txt


@pytest.fixture
def result():
    return TranscriptionResult(
        job_id="example",
        source_filename="scène.mp4",
        source_duration_seconds=5000,
        scene_start_seconds=120,
        scene_duration_seconds=4000,
        model="small",
        device="cpu",
        compute_type="int8",
        vad_filter=True,
        beam_size=5,
        language="fr",
        language_probability=0.99,
        segments=[
            Segment(start=0, end=1.25, text="Bonjour à tous."),
            Segment(start=3661.123, end=3662.9996, text="Une fin éloignée."),
        ],
        metrics=ProcessingMetrics(
            extraction_seconds=0.2, inference_seconds=2, audio_duration_seconds=4000, rtf=0.0005
        ),
    )


def test_txt_unicode(result):
    assert render_txt(result) == "Bonjour à tous.\nUne fin éloignée.\n"


def test_srt_timestamps_are_scene_relative_with_hour_carry(result):
    assert render_srt(result) == (
        "1\n00:00:00,000 --> 00:00:01,250\nBonjour à tous.\n\n"
        "2\n01:01:01,123 --> 01:01:03,000\nUne fin éloignée.\n\n"
    )


def test_json_offset_metadata_and_unicode(result):
    encoded = render_json(result)
    decoded = json.loads(encoded)
    assert "éloignée" in encoded
    assert decoded["scene_start_seconds"] == 120
    assert decoded["segments"][0]["start"] == 0
    assert decoded["metrics"]["rtf"] == 0.0005
    assert TranscriptionResult.model_validate_json(encoded) == result


def test_empty_transcript_is_valid(result):
    result.segments = []
    assert render_txt(result) == ""
    assert render_srt(result) == ""
    assert json.loads(render_json(result))["segments"] == []


def test_submillisecond_cue_has_positive_srt_duration(result):
    result.segments = [Segment(start=0.0001, end=0.0002, text="Court")]
    assert "00:00:00,000 --> 00:00:00,001" in render_srt(result)


def test_multiline_cue_cannot_introduce_another_srt_block(result):
    result.segments = [Segment(start=0, end=1, text="Bonjour\n\nmonde")]
    assert "Bonjour monde\n\n" in render_srt(result)


def test_srt_rejects_mutated_bad_chronology(result):
    result.segments.reverse()
    with pytest.raises(ValueError, match="chronologiques"):
        render_srt(result)


def test_export_defends_against_mutated_empty_text(result):
    result.segments[0].text = " "
    assert render_txt(result) == "Une fin éloignée.\n"
    assert render_srt(result).startswith("1\n01:01:01")


@pytest.mark.parametrize(
    "parameters",
    [
        {"start": 0, "end": 1, "text": " "},
        {"start": 2, "end": 1, "text": "texte"},
        {"start": -1, "end": 1, "text": "texte"},
        {"start": 0, "end": float("inf"), "text": "texte"},
    ],
)
def test_segment_contract_rejects_invalid_output(parameters):
    with pytest.raises(ValidationError):
        Segment(**parameters)


def test_result_contract_rejects_overlap():
    with pytest.raises(ValidationError, match="chevauchement"):
        ASRResult(
            language="fr",
            segments=[
                Segment(start=0, end=2, text="un"),
                Segment(start=1, end=3, text="deux"),
            ],
        )
