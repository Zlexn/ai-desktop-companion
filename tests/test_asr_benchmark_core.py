from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from asr_benchmark_core import (  # noqa: E402
    BenchmarkConfig,
    CorpusEntry,
    ResourceSampler,
    Segment,
    TranscriptionInfo,
    character_error_rate,
    compute_metrics,
    dry_run_plan,
    percentile,
    planned_attempt_count,
    run_benchmark,
    run_single_transcription,
    validate_benchmark_config,
    validate_manifest,
    word_error_rate,
    write_all_outputs,
)

FULL_REVISION = "536b0662742c02347bc0e980a01041f333bce120"


class FakeTranscriber:
    def __init__(self, text: str = "测试参考文本", duration: float = 1.0) -> None:
        self.text = text
        self.duration = duration
        self.calls: list[Path] = []

    def transcribe(self, audio_path: Path, *, language: str, beam_size: int):
        self.calls.append(audio_path)
        return [Segment(text=self.text, start=0.0, end=self.duration)], TranscriptionInfo(
            language=language,
            language_probability=0.99,
            duration=self.duration,
        )


class GeneratorTranscriber:
    def __init__(self) -> None:
        self.materialized = False

    def transcribe(self, audio_path: Path, *, language: str, beam_size: int):
        def segments():
            yield Segment(text="测试", start=0.0, end=0.5)
            self.materialized = True
            yield Segment(text="完成", start=0.5, end=1.0)

        return segments(), TranscriptionInfo(language=language, language_probability=0.8, duration=1.0)


class ErrorTranscriber:
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def transcribe(self, audio_path: Path, *, language: str, beam_size: int):
        self.calls += 1
        raise RuntimeError(self.message)


class StoppableSampler:
    stopped = False

    def start(self) -> None:
        StoppableSampler.stopped = False

    def stop(self):
        from asr_benchmark_core import ResourceSummary

        StoppableSampler.stopped = True
        return ResourceSummary(sample_count=1)


def make_manifest(tmp_path: Path, rows: list[dict] | None = None) -> tuple[Path, Path]:
    corpus_root = tmp_path / "corpus"
    clean = corpus_root / "clean"
    clean.mkdir(parents=True)
    (clean / "P001.wav").write_bytes(b"fake wav")
    (clean / "P002.wav").write_bytes(b"fake wav")
    manifest = tmp_path / "manifest.jsonl"
    if rows is None:
        rows = [
            {
                "id": "P001",
                "audio_path": "clean/P001.wav",
                "reference_text": "测试参考文本",
                "category": "daily",
                "language": "zh",
                "condition": "clean",
                "authorized": True,
            }
        ]
    manifest.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")
    return manifest, corpus_root


def make_config(tmp_path: Path, manifest: Path, corpus_root: Path, **overrides) -> BenchmarkConfig:
    model_path = tmp_path / "model"
    model_path.mkdir(exist_ok=True)
    data = {
        "manifest": manifest,
        "corpus_root": corpus_root,
        "model_path": model_path,
        "model_name": "small",
        "model_revision": FULL_REVISION,
        "device": "cuda",
        "compute_type": "float16",
        "language": "zh",
        "beam_size": 1,
        "warmup_runs": 2,
        "repeats": 3,
        "output_dir": tmp_path / "out",
        "max_items": None,
        "seed": 123,
        "offline": True,
        "dry_run": False,
        "include_full_text": False,
    }
    data.update(overrides)
    return BenchmarkConfig(**data)


def test_manifest_validation_accepts_valid_jsonl(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)

    result = validate_manifest(manifest, corpus_root)

    assert result.ok
    assert len(result.entries) == 1
    assert result.entries[0].case_id == "P001"
    assert result.entries[0].audio_path.is_file()


def test_manifest_rejects_path_traversal(tmp_path: Path):
    manifest, corpus_root = make_manifest(
        tmp_path,
        [{"id": "P001", "audio_path": "../secret.wav", "reference_text": "x", "category": "daily", "language": "zh", "condition": "clean", "authorized": True}],
    )

    result = validate_manifest(manifest, corpus_root)

    assert not result.ok
    assert any("must not traverse" in error or "escapes corpus root" in error for error in result.errors)


def test_manifest_rejects_unauthorized_entries(tmp_path: Path):
    manifest, corpus_root = make_manifest(
        tmp_path,
        [{"id": "P001", "audio_path": "clean/P001.wav", "reference_text": "x", "category": "daily", "language": "zh", "condition": "clean", "authorized": False}],
    )

    result = validate_manifest(manifest, corpus_root)

    assert not result.ok
    assert any("authorized must be true" in error for error in result.errors)


def test_manifest_rejects_urls_and_missing_files(tmp_path: Path):
    manifest, corpus_root = make_manifest(
        tmp_path,
        [
            {"id": "P001", "audio_path": "https://example.com/a.wav", "reference_text": "x", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
            {"id": "P002", "audio_path": "clean/missing.wav", "reference_text": "x", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        ],
    )

    result = validate_manifest(manifest, corpus_root)

    assert not result.ok
    assert any("must be relative" in error for error in result.errors)
    assert any("does not exist" in error for error in result.errors)


def test_manifest_rejects_duplicate_id_empty_reference_and_forbidden_paths(tmp_path: Path):
    corpus_root = tmp_path / "corpus"
    forbidden = corpus_root / "asr-benchmark-results"
    forbidden.mkdir(parents=True)
    (forbidden / "P002.wav").write_bytes(b"fake")
    (corpus_root / "clean").mkdir()
    (corpus_root / "clean" / "P001.wav").write_bytes(b"fake")
    manifest = tmp_path / "manifest.jsonl"
    rows = [
        {"id": "P001", "audio_path": "clean/P001.wav", "reference_text": "文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        {"id": "P001", "audio_path": "clean/P001.wav", "reference_text": "文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        {"id": "P003", "audio_path": "clean/P001.wav", "reference_text": "", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        {"id": "P004", "audio_path": "asr-benchmark-results/P002.wav", "reference_text": "文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
    ]
    manifest.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    result = validate_manifest(manifest, corpus_root)

    assert not result.ok
    assert any("duplicate id" in error for error in result.errors)
    assert any("reference_text" in error for error in result.errors)
    assert any("model/cache/result" in error for error in result.errors)


def test_config_rejects_missing_model_url_online_and_short_revision(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    config = make_config(
        tmp_path,
        manifest,
        corpus_root,
        model_path=Path("https://example.com/model"),
        model_revision="536b066",
        offline=False,
    )

    errors = validate_benchmark_config(config)

    assert any("local path" in error for error in errors)
    assert any("full 40-character" in error for error in errors)
    assert any("online mode is not allowed" in error for error in errors)


def test_dry_run_counts_plan_without_loading_model(tmp_path: Path):
    manifest, corpus_root = make_manifest(
        tmp_path,
        [
            {"id": "P001", "audio_path": "clean/P001.wav", "reference_text": "测试参考文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
            {"id": "P002", "audio_path": "clean/P002.wav", "reference_text": "第二条文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        ],
    )
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, dry_run=True, warmup_runs=2, repeats=3, max_items=1)

    plan = dry_run_plan(config, entries)

    assert plan["dry_run"] is True
    assert plan["offline"] is True
    assert plan["item_count"] == 1
    assert plan["planned_attempts"] == 5


def test_segments_are_fully_materialized_before_timing_stops(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entry = validate_manifest(manifest, corpus_root).entries[0]
    transcriber = GeneratorTranscriber()

    hypothesis, timing = run_single_transcription(transcriber, entry, language="zh", beam_size=1)

    assert transcriber.materialized is True
    assert hypothesis == "测试完成"
    assert timing.segment_count == 2
    assert timing.audio_duration_ms == 1000


def test_warmup_is_excluded_and_repeats_count_is_correct(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=2, repeats=3)
    transcriber = FakeTranscriber()

    result = run_benchmark(config, entries, transcriber, sampler_factory=None)
    from asr_benchmark_core import summarize_results

    summary = summarize_results(result.results)

    assert len(transcriber.calls) == planned_attempt_count(1, 2, 3)
    assert sum(case.is_warmup for case in result.results) == 2
    assert summary["measured_total"] == 3
    assert summary["success_count"] == 3


def test_percentile_and_rtf_helpers():
    assert percentile([10, 20, 30, 40], 50) == 25
    assert percentile([10, 20, 30, 40], 95) == pytest.approx(38.5)

    timing_ms = 500
    audio_duration_ms = 1000
    assert timing_ms / audio_duration_ms == 0.5


def test_cer_wer_exact_match_number_and_mixed_terms():
    metrics = compute_metrics("我今天在 VS Code 运行 npm test，订单编号 9072。", "我今天在 VS Code 运行 npm test 订单编号 9072")

    assert metrics.cer == 0
    assert metrics.exact_match is True
    assert metrics.wer == 0
    assert metrics.number_fragment_accuracy == 1
    assert metrics.mixed_term_accuracy == 1
    assert character_error_rate("测试", "测错") == 0.5
    assert word_error_rate("run npm test", "run pytest") == pytest.approx(2 / 3)


def test_model_exception_is_recorded(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=0, repeats=1)

    result = run_benchmark(config, entries, ErrorTranscriber("provider failed"), sampler_factory=None)

    assert result.results[0].error == "provider failed"
    assert result.results[0].error_type == "RuntimeError"
    assert result.exit_code == 0


def test_oom_stops_current_configuration(tmp_path: Path):
    manifest, corpus_root = make_manifest(
        tmp_path,
        [
            {"id": "P001", "audio_path": "clean/P001.wav", "reference_text": "测试参考文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
            {"id": "P002", "audio_path": "clean/P002.wav", "reference_text": "第二条文本", "category": "daily", "language": "zh", "condition": "clean", "authorized": True},
        ],
    )
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=0, repeats=3)
    transcriber = ErrorTranscriber("CUDA out of memory")

    result = run_benchmark(config, entries, transcriber, sampler_factory=None)

    assert result.stopped_after_oom is True
    assert result.exit_code == 20
    assert transcriber.calls == 1
    assert len(result.results) == 1
    assert result.results[0].error_type == "oom"


def test_resource_sampler_stops_on_exception(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=0, repeats=1)

    run_benchmark(config, entries, ErrorTranscriber("provider failed"), sampler_factory=StoppableSampler)

    assert StoppableSampler.stopped is True


def test_outputs_are_written_without_full_private_text_by_default(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=0, repeats=1)
    result = run_benchmark(config, entries, FakeTranscriber(), sampler_factory=None)

    paths = write_all_outputs(result)

    assert {path.name for path in paths} == {"results.json", "details.csv", "summary.md", "environment.json"}
    results_json = json.loads((config.output_dir / "results.json").read_text(encoding="utf-8"))
    assert results_json["privacy"]["raw_audio_copied"] is False
    assert results_json["privacy"]["full_text_included"] is False
    assert "reference_text" not in results_json["cases"][0]
    summary = (config.output_dir / "summary.md").read_text(encoding="utf-8")
    assert "测试参考文本" not in summary
    with (config.output_dir / "details.csv").open(encoding="utf-8", newline="") as file:
        rows = list(csv.DictReader(file))
    assert "reference_text" not in rows[0]


def test_full_text_output_requires_explicit_flag(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    entries = validate_manifest(manifest, corpus_root).entries
    config = make_config(tmp_path, manifest, corpus_root, warmup_runs=0, repeats=1, include_full_text=True)
    result = run_benchmark(config, entries, FakeTranscriber(), sampler_factory=None)

    write_all_outputs(result)

    data = json.loads((config.output_dir / "asr-benchmark-full-text-results.json").read_text(encoding="utf-8"))
    assert data["privacy"]["full_text_included"] is True
    assert data["cases"][0]["reference_text"] == "测试参考文本"


def test_cli_dry_run_does_not_import_faster_whisper_or_touch_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    manifest, corpus_root = make_manifest(tmp_path)
    model_path = tmp_path / "model"
    model_path.mkdir()

    def fail_import(name, *args, **kwargs):
        if name == "faster_whisper":
            raise AssertionError("dry-run imported faster_whisper")
        return original_import(name, *args, **kwargs)

    original_import = __import__
    monkeypatch.setattr("builtins.__import__", fail_import)
    import run_asr_benchmark

    code = run_asr_benchmark.main(
        [
            "--manifest",
            str(manifest),
            "--corpus-root",
            str(corpus_root),
            "--model-path",
            str(model_path),
            "--model-name",
            "small",
            "--model-revision",
            FULL_REVISION,
            "--dry-run",
        ]
    )

    assert code == 0


def test_cli_no_model_smoke_writes_outputs_without_network(tmp_path: Path):
    manifest, corpus_root = make_manifest(tmp_path)
    model_path = tmp_path / "model"
    model_path.mkdir()
    output_dir = tmp_path / "out"
    script = ROOT / "scripts" / "run_asr_benchmark.py"

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--manifest",
            str(manifest),
            "--corpus-root",
            str(corpus_root),
            "--model-path",
            str(model_path),
            "--model-name",
            "small",
            "--model-revision",
            FULL_REVISION,
            "--warmup-runs",
            "0",
            "--repeats",
            "1",
            "--output-dir",
            str(output_dir),
            "--no-model-smoke",
        ],
        check=False,
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    assert (output_dir / "results.json").is_file()
    assert (output_dir / "details.csv").is_file()
    assert (output_dir / "summary.md").is_file()
    assert (output_dir / "environment.json").is_file()


def test_windows_cuda_dll_discovery_finds_nvidia_bin_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import run_asr_benchmark

    site_packages = tmp_path / "site-packages"
    cublas_bin = site_packages / "nvidia" / "cublas" / "bin"
    cudnn_bin = site_packages / "nvidia" / "cudnn" / "bin"
    empty_bin = site_packages / "nvidia" / "empty" / "bin"
    cublas_bin.mkdir(parents=True)
    cudnn_bin.mkdir(parents=True)
    empty_bin.mkdir(parents=True)
    (cublas_bin / "cublas64_12.dll").write_bytes(b"dll")
    (cudnn_bin / "cudnn64_9.dll").write_bytes(b"dll")

    monkeypatch.setattr(run_asr_benchmark.os, "name", "nt")
    monkeypatch.setattr(run_asr_benchmark.site, "getsitepackages", lambda: [str(site_packages)])
    monkeypatch.setattr(run_asr_benchmark.site, "getusersitepackages", lambda: "")

    dirs = run_asr_benchmark.discover_windows_cuda_dll_dirs()

    assert cublas_bin.resolve() in dirs
    assert cudnn_bin.resolve() in dirs
    assert empty_bin.resolve() not in dirs


def test_windows_cuda_dll_dirs_are_added_to_path_and_search_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import run_asr_benchmark

    site_packages = tmp_path / "site-packages"
    cublas_bin = site_packages / "nvidia" / "cublas" / "bin"
    cublas_bin.mkdir(parents=True)
    (cublas_bin / "cublas64_12.dll").write_bytes(b"dll")
    handles: list[str] = []

    monkeypatch.setattr(run_asr_benchmark.os, "name", "nt")
    monkeypatch.setattr(run_asr_benchmark.site, "getsitepackages", lambda: [str(site_packages)])
    monkeypatch.setattr(run_asr_benchmark.site, "getusersitepackages", lambda: "")
    monkeypatch.setenv("PATH", "base-path")
    monkeypatch.setattr(run_asr_benchmark.os, "add_dll_directory", lambda path: handles.append(path) or f"handle:{path}", raising=False)
    run_asr_benchmark._DLL_DIRECTORY_HANDLES.clear()

    added = run_asr_benchmark.add_windows_cuda_dll_dirs()

    assert added == [cublas_bin.resolve()]
    assert str(cublas_bin.resolve()) in run_asr_benchmark.os.environ["PATH"]
    assert handles == [str(cublas_bin.resolve())]
    assert run_asr_benchmark._DLL_DIRECTORY_HANDLES == [f"handle:{cublas_bin.resolve()}"]
