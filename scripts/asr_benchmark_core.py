"""Core helpers for the independent 2B-4 ASR benchmark runner.

This module is intentionally separate from the application ASR provider/service.
It validates corpus manifests, computes deterministic text metrics, runs injected
transcribers, samples host/GPU resources, and writes privacy-safe benchmark
artifacts. It does not import faster-whisper at module import time and tests can
exercise it without loading any real ASR model.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import re
import statistics
import subprocess
import sys
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, Sequence

REQUIRED_MANIFEST_FIELDS = {
    "id",
    "audio_path",
    "reference_text",
    "category",
    "language",
    "condition",
    "authorized",
}
REPO_FORBIDDEN_AUDIO_PARTS = {
    ".git",
    ".venv",
    ".venv-asr-bench",
    "models",
    "model-cache",
    "hf-cache",
    "huggingface",
    "asr-benchmark-output",
    "asr-benchmark-results",
}
PUNCTUATION_CHARS = (
    "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
    "，。！？；：（）【】《》、“”‘’…—·￥"
)


@dataclass(frozen=True)
class NormalizationOptions:
    """Text normalization controls used by metrics."""

    ignore_whitespace: bool = True
    ignore_punctuation: bool = True


@dataclass(frozen=True)
class CorpusEntry:
    """One validated manifest row."""

    case_id: str
    audio_path: Path
    audio_rel_path: str
    reference_text: str
    category: str
    language: str
    condition: str


@dataclass(frozen=True)
class ManifestValidationResult:
    """Manifest validation output."""

    entries: list[CorpusEntry]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class BenchmarkConfig:
    """Runtime configuration for one benchmark candidate."""

    manifest: Path
    corpus_root: Path
    model_path: Path
    model_name: str
    model_revision: str
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "zh"
    beam_size: int = 1
    warmup_runs: int = 2
    repeats: int = 3
    output_dir: Path = Path("asr-benchmark-output")
    max_items: int | None = None
    seed: int = 0
    offline: bool = True
    dry_run: bool = False
    include_full_text: bool = False


@dataclass(frozen=True)
class Segment:
    """Materialized ASR segment."""

    text: str
    start: float | None = None
    end: float | None = None


@dataclass(frozen=True)
class TranscriptionInfo:
    """ASR metadata returned by a transcriber."""

    language: str | None = None
    language_probability: float | None = None
    duration: float | None = None


@dataclass(frozen=True)
class TranscriptionOutput:
    """Output from an injected transcriber."""

    segments: list[Segment]
    info: TranscriptionInfo

    @property
    def text(self) -> str:
        return "".join(segment.text for segment in self.segments).strip()


@dataclass(frozen=True)
class TranscriptionTiming:
    """Timing boundary for one complete transcribe call."""

    decode_and_transcribe_ms: float
    audio_duration_ms: float
    rtf: float
    segment_count: int
    detected_language: str | None
    detected_language_probability: float | None
    gpu_sync_strategy: str


@dataclass(frozen=True)
class MetricBundle:
    """Accuracy metrics for one case."""

    normalized_reference: str
    normalized_hypothesis: str
    cer: float
    wer: float | None
    exact_match: bool
    number_fragment_accuracy: float | None
    mixed_term_accuracy: float | None


@dataclass(frozen=True)
class CaseResult:
    """One attempted transcription result."""

    case_id: str
    run_index: int
    is_warmup: bool
    category: str
    language: str
    condition: str
    audio_duration_ms: float
    timing: TranscriptionTiming | None
    metrics: MetricBundle | None
    error: str | None = None
    error_type: str | None = None
    hypothesis: str | None = None
    reference: str | None = None


@dataclass(frozen=True)
class ResourceSummary:
    """Resource sampling summary for one benchmark run."""

    sampling_scope: str = "device-total"
    gpu_baseline_used_mib: int | None = None
    gpu_peak_used_mib: int | None = None
    gpu_delta_peak_mib: int | None = None
    system_ram_baseline_mb: float | None = None
    system_ram_peak_mb: float | None = None
    cpu_peak_percent: float | None = None
    sample_count: int = 0


@dataclass(frozen=True)
class BenchmarkResult:
    """Full benchmark result for one candidate."""

    config: BenchmarkConfig
    started_at: str
    corpus_hash: str
    model_load_ms: float | None
    first_inference_ms: float | None
    results: list[CaseResult]
    resources: ResourceSummary
    environment: dict[str, Any]
    exit_code: int = 0
    stopped_after_oom: bool = False
    dry_run: bool = False


class Transcriber(Protocol):
    """Injected ASR implementation used by the benchmark core."""

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str,
        beam_size: int,
    ) -> tuple[Any, Any]:
        """Return an iterable of segments and provider info."""


def is_url(value: str) -> bool:
    return bool(re.match(r"^(https?|ftp|s3|gs|hf):[/\\]{1,2}", value, flags=re.IGNORECASE))


def is_relative_safe_path(value: str) -> bool:
    path = Path(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and not is_url(value)


def is_forbidden_corpus_path(path: Path) -> bool:
    lowered_parts = {part.lower() for part in path.parts}
    return bool(lowered_parts & REPO_FORBIDDEN_AUDIO_PARTS)


def validate_manifest(manifest_path: Path, corpus_root: Path) -> ManifestValidationResult:
    """Validate a UTF-8 JSONL corpus manifest.

    The function returns all errors instead of raising so dry-runs can report a
    full checklist. Audio paths are resolved under ``corpus_root`` and must exist.
    """

    errors: list[str] = []
    entries: list[CorpusEntry] = []
    seen_ids: set[str] = set()
    manifest_path = Path(manifest_path)
    corpus_root = Path(corpus_root).resolve()

    if is_url(str(manifest_path)):
        return ManifestValidationResult([], ["manifest must be a local JSONL file, not a URL"])
    if manifest_path.suffix.lower() != ".jsonl":
        errors.append(f"manifest must use .jsonl extension: {manifest_path}")
    if not manifest_path.is_file():
        errors.append(f"manifest does not exist: {manifest_path}")
        return ManifestValidationResult([], errors)
    if is_forbidden_corpus_path(corpus_root):
        errors.append(f"corpus_root must not point at model/cache/result directories: {corpus_root}")

    try:
        lines = manifest_path.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        return ManifestValidationResult([], [f"manifest must be UTF-8: {exc}"])

    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"line {line_no}: invalid JSON: {exc.msg}")
            continue
        if not isinstance(row, dict):
            errors.append(f"line {line_no}: row must be a JSON object")
            continue

        missing = sorted(REQUIRED_MANIFEST_FIELDS - set(row))
        if missing:
            errors.append(f"line {line_no}: missing required fields: {', '.join(missing)}")
            continue

        case_id = str(row["id"]).strip()
        audio_rel = str(row["audio_path"]).replace("\\", "/").strip()
        reference_text = str(row["reference_text"]).strip()

        row_failed = False
        if not case_id:
            errors.append(f"line {line_no}: id must be non-empty")
            row_failed = True
        elif case_id in seen_ids:
            errors.append(f"line {line_no}: duplicate id: {case_id}")
            row_failed = True
        else:
            seen_ids.add(case_id)

        if not is_relative_safe_path(audio_rel):
            errors.append(f"line {line_no}: audio_path must be relative, local, and must not traverse: {audio_rel}")
            row_failed = True
        if not reference_text:
            errors.append(f"line {line_no}: reference_text must be non-empty")
            row_failed = True
        if row["authorized"] is not True:
            errors.append(f"line {line_no}: authorized must be true")
            row_failed = True

        audio_path = (corpus_root / audio_rel).resolve()
        try:
            audio_path.relative_to(corpus_root)
        except ValueError:
            errors.append(f"line {line_no}: audio_path escapes corpus root: {audio_rel}")
            row_failed = True
        if is_forbidden_corpus_path(audio_path):
            errors.append(f"line {line_no}: audio_path points at model/cache/result directory: {audio_rel}")
            row_failed = True
        if not audio_path.is_file():
            errors.append(f"line {line_no}: audio file does not exist: {audio_rel}")
            row_failed = True

        if row_failed:
            continue

        entries.append(
            CorpusEntry(
                case_id=case_id,
                audio_path=audio_path,
                audio_rel_path=audio_rel,
                reference_text=reference_text,
                category=str(row["category"]).strip(),
                language=str(row["language"]).strip(),
                condition=str(row["condition"]).strip(),
            )
        )

    return ManifestValidationResult(entries, errors)


def validate_benchmark_config(config: BenchmarkConfig) -> list[str]:
    """Validate runner configuration without loading a model."""

    errors: list[str] = []
    if is_url(str(config.model_path)):
        errors.append("model_path must be a local path, not a URL")
    elif not config.model_path.exists():
        errors.append(f"model_path does not exist: {config.model_path}")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", config.model_revision):
        errors.append("model_revision must be a full 40-character commit hash")
    if config.warmup_runs < 0:
        errors.append("warmup_runs must be >= 0")
    if config.repeats < 1:
        errors.append("repeats must be >= 1")
    if config.beam_size < 1:
        errors.append("beam_size must be >= 1")
    if config.max_items is not None and config.max_items < 1:
        errors.append("max_items must be >= 1 when provided")
    if not config.offline:
        errors.append("online mode is not allowed by this runner; provide a local model_path")
    return errors


def normalize_text(text: str, options: NormalizationOptions | None = None) -> str:
    """Normalize text while preserving raw text separately in result objects."""

    options = options or NormalizationOptions()
    normalized = unicodedata.normalize("NFKC", text).lower().strip()
    if options.ignore_punctuation:
        normalized = normalized.translate(str.maketrans("", "", PUNCTUATION_CHARS))
    if options.ignore_whitespace:
        normalized = re.sub(r"\s+", "", normalized)
    else:
        normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def levenshtein_distance(reference: Sequence[str], hypothesis: Sequence[str]) -> int:
    """Compute edit distance with substitution cost 1."""

    if not reference:
        return len(hypothesis)
    if not hypothesis:
        return len(reference)
    previous = list(range(len(hypothesis) + 1))
    for i, ref_item in enumerate(reference, start=1):
        current = [i]
        for j, hyp_item in enumerate(hypothesis, start=1):
            substitution = previous[j - 1] + (0 if ref_item == hyp_item else 1)
            insertion = current[j - 1] + 1
            deletion = previous[j] + 1
            current.append(min(substitution, insertion, deletion))
        previous = current
    return previous[-1]


def character_error_rate(reference: str, hypothesis: str) -> float:
    """Chinese-compatible character error rate."""

    ref_chars = list(reference)
    hyp_chars = list(hypothesis)
    if not ref_chars:
        return 0.0 if not hyp_chars else 1.0
    return levenshtein_distance(ref_chars, hyp_chars) / len(ref_chars)


def english_tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9_.+-]*", text.lower())


def word_error_rate(reference: str, hypothesis: str) -> float | None:
    """English token WER. Returns None when the reference has no English tokens."""

    ref_tokens = english_tokens(reference)
    if not ref_tokens:
        return None
    hyp_tokens = english_tokens(hypothesis)
    return levenshtein_distance(ref_tokens, hyp_tokens) / len(ref_tokens)


def numeric_fragments(text: str) -> list[str]:
    """Extract Arabic and common Chinese numeric fragments."""

    return re.findall(r"\d+|[零〇一二三四五六七八九十百千万亿两]+", text)


def fragment_accuracy(reference_fragments: list[str], hypothesis_fragments: list[str]) -> float | None:
    if not reference_fragments:
        return None
    matched = sum(1 for fragment in reference_fragments if fragment in hypothesis_fragments)
    return matched / len(reference_fragments)


def mixed_terms(text: str) -> list[str]:
    return english_tokens(text)


def mixed_term_accuracy(reference: str, hypothesis: str) -> float | None:
    ref_terms = sorted(set(mixed_terms(reference)))
    if not ref_terms:
        return None
    hyp_terms = set(mixed_terms(hypothesis))
    return sum(1 for term in ref_terms if term in hyp_terms) / len(ref_terms)


def compute_metrics(
    reference: str,
    hypothesis: str,
    *,
    options: NormalizationOptions | None = None,
) -> MetricBundle:
    """Compute all benchmark accuracy metrics without LLM scoring."""

    options = options or NormalizationOptions()
    normalized_reference = normalize_text(reference, options)
    normalized_hypothesis = normalize_text(hypothesis, options)
    return MetricBundle(
        normalized_reference=normalized_reference,
        normalized_hypothesis=normalized_hypothesis,
        cer=character_error_rate(normalized_reference, normalized_hypothesis),
        wer=word_error_rate(reference, hypothesis),
        exact_match=normalized_reference == normalized_hypothesis,
        number_fragment_accuracy=fragment_accuracy(numeric_fragments(reference), numeric_fragments(hypothesis)),
        mixed_term_accuracy=mixed_term_accuracy(reference, hypothesis),
    )


def percentile(values: Sequence[float], pct: float) -> float | None:
    """Linear-interpolated percentile for deterministic summaries."""

    if not values:
        return None
    sorted_values = sorted(values)
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (pct / 100) * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def corpus_manifest_hash(entries: Sequence[CorpusEntry]) -> str:
    """Hash manifest contents without hashing audio bytes or copying audio."""

    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item.case_id):
        digest.update(entry.case_id.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.audio_rel_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entry.reference_text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def planned_attempt_count(item_count: int, warmup_runs: int, repeats: int) -> int:
    return item_count * (warmup_runs + repeats)


def _segment_text(segment: Any) -> str:
    if isinstance(segment, Segment):
        return segment.text
    if isinstance(segment, dict):
        return str(segment.get("text", ""))
    return str(getattr(segment, "text", ""))


def _segment_start(segment: Any) -> float | None:
    if isinstance(segment, Segment):
        return segment.start
    if isinstance(segment, dict):
        value = segment.get("start")
    else:
        value = getattr(segment, "start", None)
    return None if value is None else float(value)


def _segment_end(segment: Any) -> float | None:
    if isinstance(segment, Segment):
        return segment.end
    if isinstance(segment, dict):
        value = segment.get("end")
    else:
        value = getattr(segment, "end", None)
    return None if value is None else float(value)


def _info_language(info: Any) -> str | None:
    if isinstance(info, TranscriptionInfo):
        return info.language
    if isinstance(info, dict):
        value = info.get("language")
    else:
        value = getattr(info, "language", None)
    return None if value is None else str(value)


def _info_language_probability(info: Any) -> float | None:
    if isinstance(info, TranscriptionInfo):
        value = info.language_probability
    elif isinstance(info, dict):
        value = info.get("language_probability")
    else:
        value = getattr(info, "language_probability", None)
    return None if value is None else float(value)


def _info_duration_seconds(info: Any, segments: Sequence[Any]) -> float | None:
    if isinstance(info, TranscriptionInfo):
        value = info.duration
    elif isinstance(info, dict):
        value = info.get("duration")
    else:
        value = getattr(info, "duration", None)
    if value is not None:
        return float(value)
    ends = [_segment_end(segment) for segment in segments]
    numeric_ends = [value for value in ends if value is not None]
    if numeric_ends:
        return max(numeric_ends)
    return None


def run_single_transcription(
    transcriber: Transcriber,
    entry: CorpusEntry,
    *,
    language: str,
    beam_size: int,
    gpu_sync_strategy: str = "cuda operations synchronized by provider; timer stops after segments materialization",
) -> tuple[str, TranscriptionTiming]:
    """Run one ASR call and stop timing only after ``segments = list(segments)``."""

    start = time.perf_counter()
    segments_iter, info = transcriber.transcribe(entry.audio_path, language=language, beam_size=beam_size)
    segments = list(segments_iter)
    elapsed_ms = (time.perf_counter() - start) * 1000
    hypothesis = "".join(_segment_text(segment) for segment in segments).strip()
    duration_seconds = _info_duration_seconds(info, segments)
    audio_duration_ms = (duration_seconds * 1000) if duration_seconds is not None else 0.0
    rtf = elapsed_ms / audio_duration_ms if audio_duration_ms > 0 else 0.0
    timing = TranscriptionTiming(
        decode_and_transcribe_ms=elapsed_ms,
        audio_duration_ms=audio_duration_ms,
        rtf=rtf,
        segment_count=len(segments),
        detected_language=_info_language(info),
        detected_language_probability=_info_language_probability(info),
        gpu_sync_strategy=gpu_sync_strategy,
    )
    return hypothesis, timing


def is_oom_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return "out of memory" in text or "oom" in text or "cuda" in text and "memory" in text


class ResourceSampler:
    """Best-effort read-only resource sampler.

    GPU sampling uses nvidia-smi device totals. RAM/CPU use psutil when available;
    otherwise they remain None rather than adding a new dependency.
    """

    def __init__(self, interval_sec: float = 0.2) -> None:
        self.interval_sec = interval_sec
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._samples: list[dict[str, float | int | None]] = []
        self._baseline_gpu = query_gpu_used_mib()
        self._baseline_ram = query_system_ram_mb()

    def _sample_once(self) -> dict[str, float | int | None]:
        return {
            "gpu_used_mib": query_gpu_used_mib(),
            "system_ram_mb": query_system_ram_mb(),
            "cpu_percent": query_cpu_percent(),
        }

    def _run(self) -> None:
        while not self._stop_event.is_set():
            sample = self._sample_once()
            with self._lock:
                self._samples.append(sample)
            self._stop_event.wait(self.interval_sec)

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> ResourceSummary:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        with self._lock:
            samples = list(self._samples)
        gpu_values = [int(sample["gpu_used_mib"]) for sample in samples if sample.get("gpu_used_mib") is not None]
        ram_values = [float(sample["system_ram_mb"]) for sample in samples if sample.get("system_ram_mb") is not None]
        cpu_values = [float(sample["cpu_percent"]) for sample in samples if sample.get("cpu_percent") is not None]
        gpu_peak = max(gpu_values) if gpu_values else None
        return ResourceSummary(
            sampling_scope="device-total",
            gpu_baseline_used_mib=self._baseline_gpu,
            gpu_peak_used_mib=gpu_peak,
            gpu_delta_peak_mib=(gpu_peak - self._baseline_gpu) if gpu_peak is not None and self._baseline_gpu is not None else None,
            system_ram_baseline_mb=self._baseline_ram,
            system_ram_peak_mb=max(ram_values) if ram_values else None,
            cpu_peak_percent=max(cpu_values) if cpu_values else None,
            sample_count=len(samples),
        )


def query_gpu_used_mib() -> int | None:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.used",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        return int(output.strip().splitlines()[0].strip())
    except Exception:
        return None


def query_system_ram_mb() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return float(psutil.virtual_memory().used / (1024 * 1024))
    except Exception:
        return None


def query_cpu_percent() -> float | None:
    try:
        import psutil  # type: ignore[import-not-found]

        return float(psutil.cpu_percent(interval=None))
    except Exception:
        return None


def collect_environment() -> dict[str, Any]:
    """Collect environment metadata without requiring faster-whisper to be installed."""

    env: dict[str, Any] = {
        "windows_version": platform.platform(),
        "python_version": sys.version.split()[0],
        "gpu_name": None,
        "gpu_driver_version": None,
        "gpu_total_vram_mib": None,
        "faster_whisper_version": None,
        "ctranslate2_version": None,
    }
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total",
                "--format=csv,noheader,nounits",
            ],
            text=True,
            timeout=5,
        )
        name, driver, total = [part.strip() for part in output.strip().splitlines()[0].split(",")[:3]]
        env["gpu_name"] = name
        env["gpu_driver_version"] = driver
        env["gpu_total_vram_mib"] = int(total)
    except Exception:
        pass
    try:
        import faster_whisper  # type: ignore[import-not-found]

        env["faster_whisper_version"] = getattr(faster_whisper, "__version__", "unknown")
    except Exception:
        pass
    try:
        import ctranslate2  # type: ignore[import-not-found]

        env["ctranslate2_version"] = getattr(ctranslate2, "__version__", "unknown")
    except Exception:
        pass
    return env


def select_entries(entries: Sequence[CorpusEntry], max_items: int | None) -> list[CorpusEntry]:
    selected = list(entries)
    if max_items is not None:
        selected = selected[:max_items]
    return selected


def run_benchmark(
    config: BenchmarkConfig,
    entries: Sequence[CorpusEntry],
    transcriber: Transcriber,
    *,
    sampler_factory: type[ResourceSampler] | None = ResourceSampler,
    model_load_ms: float | None = None,
) -> BenchmarkResult:
    """Run warmups and measured repeats with an injected transcriber.

    OOM stops the current configuration immediately. Warmups are marked and are
    excluded from summary statistics by ``summarize_results``.
    """

    started_at = datetime.now(UTC).isoformat()
    selected_entries = select_entries(entries, config.max_items)
    results: list[CaseResult] = []
    sampler = sampler_factory() if sampler_factory is not None else None
    stopped_after_oom = False
    exit_code = 0
    first_inference_ms: float | None = None

    if sampler is not None:
        sampler.start()
    try:
        for run_index in range(config.warmup_runs + config.repeats):
            is_warmup = run_index < config.warmup_runs
            measured_index = 0 if is_warmup else run_index - config.warmup_runs + 1
            for entry in selected_entries:
                try:
                    hypothesis, timing = run_single_transcription(
                        transcriber,
                        entry,
                        language=config.language,
                        beam_size=config.beam_size,
                    )
                    if first_inference_ms is None:
                        first_inference_ms = timing.decode_and_transcribe_ms
                    metrics = compute_metrics(entry.reference_text, hypothesis)
                    results.append(
                        CaseResult(
                            case_id=entry.case_id,
                            run_index=measured_index,
                            is_warmup=is_warmup,
                            category=entry.category,
                            language=entry.language,
                            condition=entry.condition,
                            audio_duration_ms=timing.audio_duration_ms,
                            timing=timing,
                            metrics=metrics,
                            hypothesis=hypothesis,
                            reference=entry.reference_text,
                        )
                    )
                except Exception as exc:
                    oom = is_oom_error(exc)
                    results.append(
                        CaseResult(
                            case_id=entry.case_id,
                            run_index=measured_index,
                            is_warmup=is_warmup,
                            category=entry.category,
                            language=entry.language,
                            condition=entry.condition,
                            audio_duration_ms=0.0,
                            timing=None,
                            metrics=None,
                            error=str(exc),
                            error_type="oom" if oom else type(exc).__name__,
                        )
                    )
                    if oom:
                        stopped_after_oom = True
                        exit_code = 20
                        return _build_benchmark_result(
                            config,
                            started_at,
                            selected_entries,
                            model_load_ms,
                            first_inference_ms,
                            results,
                            sampler.stop() if sampler is not None else ResourceSummary(),
                            exit_code,
                            stopped_after_oom,
                        )
    finally:
        resources = sampler.stop() if sampler is not None else ResourceSummary()

    return _build_benchmark_result(
        config,
        started_at,
        selected_entries,
        model_load_ms,
        first_inference_ms,
        results,
        resources,
        exit_code,
        stopped_after_oom,
    )


def _build_benchmark_result(
    config: BenchmarkConfig,
    started_at: str,
    entries: Sequence[CorpusEntry],
    model_load_ms: float | None,
    first_inference_ms: float | None,
    results: list[CaseResult],
    resources: ResourceSummary,
    exit_code: int,
    stopped_after_oom: bool,
) -> BenchmarkResult:
    return BenchmarkResult(
        config=config,
        started_at=started_at,
        corpus_hash=corpus_manifest_hash(entries),
        model_load_ms=model_load_ms,
        first_inference_ms=first_inference_ms,
        results=results,
        resources=resources,
        environment=collect_environment(),
        exit_code=exit_code,
        stopped_after_oom=stopped_after_oom,
        dry_run=config.dry_run,
    )


def summarize_results(results: Sequence[CaseResult]) -> dict[str, Any]:
    """Summarize measured rows only; model load and warmups are excluded."""

    measured = [result for result in results if not result.is_warmup]
    successes = [result for result in measured if result.error is None and result.timing is not None]
    failures = [result for result in measured if result.error is not None]
    latencies = [result.timing.decode_and_transcribe_ms for result in successes if result.timing is not None]
    rtfs = [result.timing.rtf for result in successes if result.timing is not None]
    cers = [result.metrics.cer for result in successes if result.metrics is not None]
    wers = [result.metrics.wer for result in successes if result.metrics is not None and result.metrics.wer is not None]
    return {
        "measured_total": len(measured),
        "success_count": len(successes),
        "failure_count": len(failures),
        "oom_count": sum(1 for result in measured if result.error_type == "oom"),
        "p50_decode_and_transcribe_ms": percentile(latencies, 50),
        "p95_decode_and_transcribe_ms": percentile(latencies, 95),
        "p50_rtf": percentile(rtfs, 50),
        "p95_rtf": percentile(rtfs, 95),
        "mean_cer": statistics.mean(cers) if cers else None,
        "mean_wer": statistics.mean(wers) if wers else None,
    }


def dry_run_plan(config: BenchmarkConfig, entries: Sequence[CorpusEntry]) -> dict[str, Any]:
    selected_entries = select_entries(entries, config.max_items)
    return {
        "dry_run": True,
        "offline": config.offline,
        "model_path": str(config.model_path),
        "model_name": config.model_name,
        "model_revision": config.model_revision,
        "device": config.device,
        "compute_type": config.compute_type,
        "language": config.language,
        "beam_size": config.beam_size,
        "warmup_runs": config.warmup_runs,
        "repeats": config.repeats,
        "item_count": len(selected_entries),
        "planned_attempts": planned_attempt_count(len(selected_entries), config.warmup_runs, config.repeats),
        "corpus_hash": corpus_manifest_hash(selected_entries),
    }


def ensure_output_dir(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def result_to_dict(result: BenchmarkResult, *, include_full_text: bool = False) -> dict[str, Any]:
    summary = summarize_results(result.results)
    rows: list[dict[str, Any]] = []
    for case in result.results:
        row: dict[str, Any] = {
            "case_id": case.case_id,
            "run_index": case.run_index,
            "is_warmup": case.is_warmup,
            "category": case.category,
            "language": case.language,
            "condition": case.condition,
            "audio_duration_ms": case.audio_duration_ms,
            "decode_and_transcribe_ms": case.timing.decode_and_transcribe_ms if case.timing else None,
            "rtf": case.timing.rtf if case.timing else None,
            "segment_count": case.timing.segment_count if case.timing else None,
            "detected_language": case.timing.detected_language if case.timing else None,
            "detected_language_probability": case.timing.detected_language_probability if case.timing else None,
            "cer": case.metrics.cer if case.metrics else None,
            "wer": case.metrics.wer if case.metrics else None,
            "exact_match": case.metrics.exact_match if case.metrics else None,
            "number_fragment_accuracy": case.metrics.number_fragment_accuracy if case.metrics else None,
            "mixed_term_accuracy": case.metrics.mixed_term_accuracy if case.metrics else None,
            "error": case.error,
            "error_type": case.error_type,
        }
        if include_full_text:
            row["reference_text"] = case.reference
            row["hypothesis_text"] = case.hypothesis
            row["normalized_reference"] = case.metrics.normalized_reference if case.metrics else None
            row["normalized_hypothesis"] = case.metrics.normalized_hypothesis if case.metrics else None
        rows.append(row)

    return {
        "schema_version": 1,
        "started_at": result.started_at,
        "environment": result.environment,
        "model": {
            "name": result.config.model_name,
            "revision": result.config.model_revision,
            "path": str(result.config.model_path),
            "device": result.config.device,
            "compute_type": result.config.compute_type,
            "beam_size": result.config.beam_size,
            "language": result.config.language,
        },
        "corpus_hash": result.corpus_hash,
        "timing": {
            "model_load_ms": result.model_load_ms,
            "first_inference_ms": result.first_inference_ms,
            "summary_excludes_model_load_and_warmups": True,
        },
        "summary": summary,
        "resources": result.resources.__dict__,
        "exit_code": result.exit_code,
        "stopped_after_oom": result.stopped_after_oom,
        "privacy": {
            "raw_audio_copied": False,
            "full_text_included": include_full_text,
        },
        "cases": rows,
    }


def write_results_json(result: BenchmarkResult, output_dir: Path, *, include_full_text: bool = False) -> Path:
    ensure_output_dir(output_dir)
    path = output_dir / ("asr-benchmark-full-text-results.json" if include_full_text else "results.json")
    path.write_text(json.dumps(result_to_dict(result, include_full_text=include_full_text), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_details_csv(result: BenchmarkResult, output_dir: Path, *, include_full_text: bool = False) -> Path:
    ensure_output_dir(output_dir)
    path = output_dir / ("asr-benchmark-full-text-details.csv" if include_full_text else "details.csv")
    fields = [
        "case_id",
        "run_index",
        "is_warmup",
        "category",
        "language",
        "condition",
        "audio_duration_ms",
        "decode_and_transcribe_ms",
        "rtf",
        "segment_count",
        "detected_language",
        "detected_language_probability",
        "cer",
        "wer",
        "exact_match",
        "number_fragment_accuracy",
        "mixed_term_accuracy",
        "error_type",
        "error",
    ]
    if include_full_text:
        fields.extend(["reference_text", "hypothesis_text", "normalized_reference", "normalized_hypothesis"])
    rows = result_to_dict(result, include_full_text=include_full_text)["cases"]
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_environment_json(result: BenchmarkResult, output_dir: Path) -> Path:
    ensure_output_dir(output_dir)
    path = output_dir / "environment.json"
    path.write_text(json.dumps(result.environment, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_summary_md(result: BenchmarkResult, output_dir: Path) -> Path:
    ensure_output_dir(output_dir)
    summary = summarize_results(result.results)
    path = output_dir / "summary.md"
    lines = [
        "# ASR Benchmark Summary",
        "",
        f"- Started at: `{result.started_at}`",
        f"- Model: `{result.config.model_name}`",
        f"- Revision: `{result.config.model_revision}`",
        f"- Device: `{result.config.device}`",
        f"- Compute type: `{result.config.compute_type}`",
        f"- Beam size: `{result.config.beam_size}`",
        f"- Language: `{result.config.language}`",
        f"- Corpus hash: `{result.corpus_hash}`",
        f"- Model load ms: `{result.model_load_ms}`",
        f"- First inference ms: `{result.first_inference_ms}`",
        f"- Measured successes: `{summary['success_count']}`",
        f"- Measured failures: `{summary['failure_count']}`",
        f"- OOM count: `{summary['oom_count']}`",
        f"- P50 decode+transcribe ms: `{summary['p50_decode_and_transcribe_ms']}`",
        f"- P95 decode+transcribe ms: `{summary['p95_decode_and_transcribe_ms']}`",
        f"- P50 RTF: `{summary['p50_rtf']}`",
        f"- P95 RTF: `{summary['p95_rtf']}`",
        f"- Mean CER: `{summary['mean_cer']}`",
        f"- Mean WER: `{summary['mean_wer']}`",
        f"- GPU sampling scope: `{result.resources.sampling_scope}`",
        f"- GPU baseline used MiB: `{result.resources.gpu_baseline_used_mib}`",
        f"- GPU peak used MiB: `{result.resources.gpu_peak_used_mib}`",
        f"- GPU delta peak MiB: `{result.resources.gpu_delta_peak_mib}`",
        "",
        "Privacy: this summary intentionally omits full reference and hypothesis text. Raw audio is never copied to the output directory.",
        "Timing note: hot P50/P95 exclude model load time and warmup runs.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_all_outputs(result: BenchmarkResult) -> list[Path]:
    include_full_text = result.config.include_full_text
    return [
        write_results_json(result, result.config.output_dir, include_full_text=include_full_text),
        write_details_csv(result, result.config.output_dir, include_full_text=include_full_text),
        write_summary_md(result, result.config.output_dir),
        write_environment_json(result, result.config.output_dir),
    ]
