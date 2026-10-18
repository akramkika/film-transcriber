import sys
import wave
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from film_transcriber.asr import faster_whisper as module
from film_transcriber.asr.faster_whisper import FasterWhisperEngine, resolve_model_path
from film_transcriber.core.config import Settings
from film_transcriber.core.errors import AppError
from film_transcriber.core.models import TranscriptionOptions


@pytest.fixture
def audio(tmp_path):
    path = tmp_path / "audio.wav"
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        stream.writeframes(b"\x00\x00" * 16000 * 3)
    return path


@pytest.fixture
def model_path(tmp_path):
    path = tmp_path / "model"
    path.mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json"):
        (path / name).write_bytes(b"fixture")
    return path


def test_audio_decoder_compatible_with_installed_pyav(audio):
    """Exercise the third-party boundary without downloading or loading a model."""
    from faster_whisper.audio import decode_audio

    decoded = decode_audio(str(audio), sampling_rate=16000)
    assert decoded.shape == (48000,)
    assert decoded.dtype.name == "float32"


def fake_model(segments):
    return SimpleNamespace(
        transcribe=Mock(
            return_value=(
                iter(segments),
                SimpleNamespace(language="fr", language_probability=0.98),
            )
        )
    )


def test_exhausts_generator_normalizes_and_bounds_segments(audio, model_path, monkeypatch):
    exhausted = []

    def generate():
        yield SimpleNamespace(start=-0.1, end=1.0, text="  Bonjour\n à tous. ")
        yield SimpleNamespace(start=0.8, end=1.5, text=" Encore. ")
        yield SimpleNamespace(start=1.6, end=2, text="  ")
        yield SimpleNamespace(start=2.0, end=4, text="Fin.")
        yield SimpleNamespace(start=4, end=5, text="Hors scène")
        exhausted.append(True)

    model = fake_model([])
    model.transcribe.return_value = (
        generate(),
        SimpleNamespace(language="fr", language_probability=0.9),
    )
    monkeypatch.setattr(module, "_create_model", lambda *args: model)
    engine = FasterWhisperEngine(Settings(model_path=model_path))
    result = engine.transcribe(
        audio, TranscriptionOptions(language="fr", vad_filter=False, beam_size=2)
    )
    assert exhausted == [True]
    assert [segment.text for segment in result.segments] == ["Bonjour à tous.", "Encore.", "Fin."]
    assert [(segment.start, segment.end) for segment in result.segments] == [
        (0, 1),
        (1, 1.5),
        (2, 3),
    ]
    assert result.language == "fr"
    assert model.transcribe.call_args.kwargs["beam_size"] == 2
    assert model.transcribe.call_args.kwargs["vad_filter"] is False


def test_lazy_model_loaded_once(audio, model_path, monkeypatch):
    model = fake_model([])
    factory = Mock(return_value=model)
    monkeypatch.setattr(module, "_create_model", factory)
    engine = FasterWhisperEngine(Settings(model_path=model_path))
    factory.assert_not_called()
    assert engine.transcribe(audio, TranscriptionOptions()).segments == []
    assert engine.transcribe(audio, TranscriptionOptions()).segments == []
    factory.assert_called_once()


def test_model_path_incomplete_does_not_fall_back_to_network(tmp_path):
    with pytest.raises(AppError) as error:
        resolve_model_path(Settings(model_path=tmp_path))
    assert error.value.category == "model_missing"
    assert "download-model" in error.value.message


def test_cache_lookup_strictly_local(model_path, monkeypatch):
    lookup = Mock(return_value=str(model_path))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=lookup))
    settings = Settings(model_name="small")
    assert resolve_model_path(settings) == model_path
    lookup.assert_called_once_with(
        "small", cache_dir=str(settings.model_cache_dir), local_files_only=True
    )


def test_cache_miss_actionable(monkeypatch):
    lookup = Mock(side_effect=OSError("PRIVATE"))
    monkeypatch.setitem(sys.modules, "faster_whisper.utils", SimpleNamespace(download_model=lookup))
    with pytest.raises(AppError) as error:
        resolve_model_path(Settings())
    assert error.value.category == "model_missing"
    assert "PRIVATE" not in error.value.message


def test_constructor_uses_local_files_only(model_path, monkeypatch):
    factory = Mock(return_value=object())
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=factory))
    module._create_model(model_path, Settings())
    assert factory.call_args.kwargs["local_files_only"] is True
    assert factory.call_args.kwargs["device"] == "cpu"
    assert factory.call_args.kwargs["compute_type"] == "int8"


@pytest.mark.parametrize(
    "failure,category",
    [
        (MemoryError(), "out_of_memory"),
        (RuntimeError("CUDA out of memory: PRIVATE"), "out_of_memory"),
        (RuntimeError("std::bad_alloc PRIVATE"), "out_of_memory"),
        (RuntimeError("PRIVATE"), "asr_failed"),
    ],
)
def test_lazy_inference_errors_are_caught(audio, model_path, monkeypatch, failure, category):
    def generate():
        yield SimpleNamespace(start=0, end=1, text="Début")
        raise failure

    model = fake_model([])
    model.transcribe.return_value = (
        generate(),
        SimpleNamespace(language="fr", language_probability=1),
    )
    monkeypatch.setattr(module, "_create_model", lambda *args: model)
    with pytest.raises(AppError) as error:
        FasterWhisperEngine(Settings(model_path=model_path)).transcribe(
            audio, TranscriptionOptions()
        )
    assert error.value.category == category
    assert "PRIVATE" not in error.value.message


def test_invalid_audio_rejected_before_model_load(tmp_path, monkeypatch):
    factory = Mock()
    monkeypatch.setattr(module, "_create_model", factory)
    with pytest.raises(AppError) as error:
        FasterWhisperEngine(Settings()).transcribe(tmp_path / "missing.wav", TranscriptionOptions())
    assert error.value.category == "invalid_audio"
    factory.assert_not_called()


def test_nonfinite_timestamps_fail(audio, model_path, monkeypatch):
    model = fake_model([SimpleNamespace(start=0, end=float("nan"), text="Texte")])
    monkeypatch.setattr(module, "_create_model", lambda *args: model)
    with pytest.raises(AppError) as error:
        FasterWhisperEngine(Settings(model_path=model_path)).transcribe(
            audio, TranscriptionOptions()
        )
    assert error.value.category == "asr_failed"


def test_missing_model_passes_domain_error(audio, tmp_path):
    with pytest.raises(AppError) as error:
        FasterWhisperEngine(Settings(model_path=tmp_path)).transcribe(audio, TranscriptionOptions())
    assert error.value.category == "model_missing"
