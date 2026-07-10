# 2B-4 Real ASR Benchmark Preparation

> Status: benchmark runner completed for pilot evaluation; C1-C4 completed; initial integration candidate selected as C3. Real ASR application integration: **NOT STARTED**.
>
> Current phase: Stage 2 — voice features. 2B-1/2B-2/2B-3 are completed. 2B-4 prepares a reproducible local ASR benchmark only.
>
> Environment preparation commit: `5f703f0` (`chore: prepare isolated ASR benchmark environment`).
>
> Runner implementation status: **IMPLEMENTING**. The runner is independent from application ASR code and is validated only with unit tests, dry-run, and no-model smoke checks in this task.
>
> Baseline commit before 2B-4 preparation: `4f15a902aba973ad43e9a55561ed7ca4fb635049` (`feat: complete stage 2B-3 browser recording UI`).
>
> Environment facts recorded on 2026-06-26: `.venv-asr-bench` exists separately from the project runtime; `faster-whisper==1.2.1`, `ctranslate2==4.8.0`, `nvidia-cublas-cu12==12.9.2.10`, and `nvidia-cuda-nvrtc-cu12==12.9.86` are installed there; `small` and `medium` faster-whisper snapshots are downloaded. C1 `small`/`cuda`/`float16`, C2 `medium`/`cuda`/`int8_float16`, C3 `medium`/`cuda`/`float16`, and C4 `small`/`cpu`/`int8` have pilot-corpus benchmark data.

## 1. Scope and hard boundaries

2B-4 is an offline benchmark-preparation task. It does **not** integrate real ASR into the application.

This task must not change:

- `backend/app/asr/base.py` or the application `ASRProvider` protocol.
- `backend/app/services/asr_service.py` or application ASR validation behavior.
- `POST /api/audio/transcriptions` public behavior.
- `backend/pyproject.toml` or the main project runtime dependencies.
- Stage 2C, VAD, streaming, interruption, Stage 3 memory, or Stage 4 emotion features.

This task must not do:

- Run `small` or `medium` real transcription.
- Download `turbo`.
- Install or evaluate `sherpa-onnx`.
- Access the microphone.
- Commit model weights, Hugging Face cache contents, benchmark corpus audio, private transcripts, or virtual environments.

## 2. Existing 2B-3 baseline

The application currently has:

- `ASRProvider` protocol and fake ASR provider.
- `ASRService` upload validation and fake provider invocation.
- `POST /api/audio/transcriptions` multipart endpoint.
- Frontend manual recording UI that uploads browser recordings to Fake ASR.
- Transcript review in the text input before manual send.

The real ASR benchmark runner must stay independent of this code. The benchmark may inform a later real ASR provider task, but it must not modify the provider/service/route during 2B-4.

## 3. Hardware and software audit

| Item | Value |
|---|---|
| GPU | NVIDIA GeForce RTX 3060 **Laptop** GPU |
| Actual VRAM | **6144 MiB** |
| Compute Capability | **8.6** |
| NVIDIA driver | 610.62 (WDDM) |
| OS | Windows 11 Home China, 10.0.26200, 64-bit |
| Python for benchmark env | 3.12.6 |
| faster-whisper | 1.2.1 |
| CTranslate2 | 4.8.0 |
| Main project `.venv` ASR/ML deps | Not used for benchmark; must remain unmodified |

`nvidia-smi` reports CUDA compatibility from the driver. That is not the same thing as a separately installed CUDA Toolkit. For this benchmark, CTranslate2 wheels provide the runtime path used by faster-whisper.

## 4. Model cache and Git safety

Model cache policy:

- Hugging Face model snapshots live outside the repository under the user's Hugging Face cache by default.
- `.venv-asr-bench/` is ignored.
- Local corpus directories and generated benchmark result directories are ignored.
- Model weights must never be placed under the repository.
- Private audio and private full-text benchmark outputs must never be committed.

Pinned faster-whisper snapshots already downloaded:

| Model | Repo | Full revision |
|---|---|---|
| small | `Systran/faster-whisper-small` | `536b0662742c02347bc0e980a01041f333bce120` |
| medium | `Systran/faster-whisper-medium` | `08e178d48790749d25932bbc082711ddcfdfbc4f` |

`turbo` is deferred and is not part of this benchmark-preparation baseline.

## 5. Current model-load VRAM observations

The following numbers are **model-load VRAM observations**, not peak inference VRAM. They were observed after model construction returned, without running real transcription.

| Model | Device | Compute type | Device-total used after load | Approx. load delta | Label |
|---|---|---|---:|---:|---|
| small | cuda | float16 | ~1072 MiB | ~673 MiB | model-load VRAM observation |
| medium | cuda | int8_float16 | ~1456 MiB | ~1057 MiB | model-load VRAM observation |
| medium | cuda | float16 | ~2384 MiB | ~1985 MiB | model-load VRAM observation |

Important measurement discipline:

- Model-load VRAM is not the same as inference peak VRAM.
- Future benchmark execution must sample VRAM during `model.transcribe(...)` and after `segments = list(segments)` has fully materialized.
- Device-total GPU sampling is not process-exclusive. Results must preserve the baseline and label the sampling scope.
- No accuracy, latency, RTF, CER, WER, or inference peak VRAM has been measured yet.

## 6. Primary candidate status

`medium` + `cuda` + `float16` is the **primary candidate for benchmark execution**, not a final production selection.

Reasoning before real transcription:

1. It fits in model-load observation on the 6144 MiB RTX 3060 Laptop GPU.
2. It avoids the possible accuracy tradeoff of int8 quantization if latency and inference peak VRAM remain acceptable.
3. It must still prove accuracy, hot latency, RTF, inference peak VRAM, stability, and coexistence constraints.

Production ASR selection is **NOT DECIDED**. A model can only be selected after real corpus benchmark data and privacy-reviewed results.

## 7. Formal benchmark matrix to support later

The runner must be able to express this matrix, but this preparation task does not execute it:

| Config | Model | Device | Compute type | Beam size | Language |
|---|---|---|---|---:|---|
| C1 | small | cuda | float16 | 1 | zh |
| C2 | medium | cuda | int8_float16 | 1 | zh |
| C3 | medium | cuda | float16 | 1 | zh |
| C4 | small | cpu | int8 | 1 | zh |

Excluded from this round:

- `turbo`.
- `sherpa-onnx`.
- Batch inference.
- VAD.
- Streaming ASR.

## 8. Benchmark timing boundary

Each future real transcription measurement must:

1. Record the GPU synchronization strategy before timing.
2. Start timing immediately before `model.transcribe(...)`.
3. Fully materialize `segments = list(segments)`.
4. Stop timing only after all segments are materialized.
5. Record `decode_and_transcribe_ms`, `audio_duration_ms`, RTF, segment count, detected language, and detected language probability.
6. Record model load time, first inference time, and warmed inference time separately.
7. Exclude model load and warmup from hot P50/P95.

## 9. Corpus and privacy plan

Corpus manifest format: UTF-8 JSONL. Each line describes one authorized audio file relative to a corpus root.

Required fields:

```json
{"id":"P001","audio_path":"clean/P001.wav","reference_text":"测试参考文本","category":"daily","language":"zh","condition":"clean","authorized":true}
```

Validation requirements:

- `id` must be unique.
- `audio_path` must be relative to the corpus root.
- Path traversal and URLs are rejected.
- The referenced file must exist.
- `reference_text` must be non-empty.
- `authorized` must be exactly `true`.
- Repository model/cache/result paths must not be accepted as corpus audio.
- Example manifests must not contain private text or absolute paths.

## 10. Metrics to implement in the runner

Accuracy metrics:

- Chinese CER.
- English token WER.
- Full sentence exact match.
- Number fragment accuracy.
- Mixed Chinese/English technical-term accuracy.

Normalization requirements:

- Unicode NFKC.
- English lowercase.
- Configurable whitespace ignoring.
- Configurable punctuation ignoring.
- Preserve raw reference/hypothesis separately from normalized forms.
- No LLM scoring.

Resource metrics:

- GPU baseline used memory.
- GPU peak used memory.
- GPU delta peak.
- System RAM baseline.
- System RAM peak.
- CPU peak.
- Sampling scope (`device-total` when process-exclusive GPU memory is unavailable).

## 11. Output artifacts for future benchmark execution

The runner should create these files under an output directory:

- `results.json`
- `details.csv`
- `summary.md`
- `environment.json`

Privacy defaults:

- `summary.md` must not include full hypothesis/reference text by default.
- `details.csv` should use case IDs and metrics, not full text.
- Full text output requires an explicit local flag and remains ignored by Git by default.
- Raw audio is never copied into the output directory.

## 12. ASR and real TTS coexistence

ASR and real TTS simultaneous residency has **not** been verified.

The current medium float16 recommendation is only a benchmark candidate. It does not prove that a future real TTS model can coexist in VRAM, that both can remain resident, or that latency remains acceptable when both features are active.

## 13. Deferred candidates

- `turbo`: deferred. It is not downloaded and not part of the formal 2B-4 matrix.
- `sherpa-onnx`: deferred. It remains a backup research path only if faster-whisper is later eliminated by data or compatibility.

## 14. Benchmark runner implementation baseline

The independent runner files are:

- `scripts/asr_benchmark_core.py` — manifest validation, metrics, injected transcriber loop, resource sampling, privacy-safe output writers.
- `scripts/run_asr_benchmark.py` — CLI wrapper. It defaults to offline/local-only behavior, rejects remote model paths, and does not load `faster-whisper` during `--dry-run`.
- `docs/stage2b4-corpus-manifest.example.jsonl` — synthetic, non-private manifest example.
- `tests/test_asr_benchmark_core.py` — fake/no-model tests only.

Supported CLI options:

```text
--manifest --corpus-root --model-path --model-name --model-revision
--device --compute-type --language --beam-size --warmup-runs --repeats
--output-dir --max-items --seed --offline --dry-run
```

Additional local-only options:

- `--no-model-smoke` writes output artifacts through an injected no-model transcriber for runner plumbing checks only.
- `--include-full-text-output` explicitly writes full reference/hypothesis text to ignored local output files. It is off by default.

Timing and execution rules implemented for future real runs:

- The core starts timing immediately before `transcriber.transcribe(...)`.
- It materializes `segments = list(segments)` before stopping the transcription timer.
- It records decode/transcribe time, audio duration, RTF, segment count, detected language, and detected language probability.
- Warmup runs are marked and excluded from hot P50/P95 summaries.
- Model load time is supplied separately by the CLI and is not mixed into hot statistics.
- OOM-like errors stop the current configuration instead of repeating failures.
- The runner is single-process and non-parallel for one candidate configuration; formal matrix execution should launch separate processes per configuration.

Privacy defaults:

- `summary.md` and default `details.csv`/`results.json` omit full reference and hypothesis text.
- Raw audio is never copied to the output directory.
- Full text output requires explicit local opt-in and is covered by `.gitignore` patterns.

## 15. C1 pilot benchmark result — 2026-06-26

After adding Windows CUDA DLL discovery to the independent runner and installing CUDA runtime wheels in `.venv-asr-bench`, C1 completed successfully on the 12-item pilot corpus.

Environment/runtime additions:

- `nvidia-cublas-cu12==12.9.2.10`
- `nvidia-cuda-nvrtc-cu12==12.9.86`
- The runner adds local `site-packages/nvidia/*/bin` DLL directories on Windows before loading `faster-whisper`.

C1 configuration:

| Model | Device | Compute type | Beam size | Language | Warmup | Repeats |
|---|---|---|---:|---|---:|---:|
| small | cuda | float16 | 1 | zh | 2 | 3 |

Output directory:

```text
asr-benchmark-results/C1-small-cuda-float16-full/
```

Summary:

| Metric | Result |
|---|---:|
| Measured successes | 36 |
| Measured failures | 0 |
| OOM count | 0 |
| Model load | 875.14 ms |
| First inference | 464.67 ms |
| P50 decode+transcribe | 172.61 ms |
| P95 decode+transcribe | 200.51 ms |
| P50 RTF | 0.03066 |
| P95 RTF | 0.03790 |
| Mean CER | 0.13512 |
| Mean WER | 1.23333 |
| GPU baseline used | 1115 MiB |
| GPU peak used | 1325 MiB |
| GPU delta peak | 210 MiB |

Interpretation boundaries:

- This is real ASR pilot-corpus data for C1 only.
- The corpus has 12 local authorized `.m4a` files and is not committed to Git.
- `summary.md` and default result artifacts omit full reference/hypothesis text.
- C1 passing does not decide production ASR model selection.
- C2, C3, and C4 have not been executed.
- Real ASR application integration has not started.
- ASR and real TTS simultaneous residency remains unverified.

## 16. C2 pilot benchmark result — 2026-06-26

C2 completed successfully on the same 12-item pilot corpus.

C2 configuration:

| Model | Device | Compute type | Beam size | Language | Warmup | Repeats |
|---|---|---|---:|---|---:|---:|
| medium | cuda | int8_float16 | 1 | zh | 2 | 3 |

Output directory:

```text
asr-benchmark-results/C2-medium-cuda-int8_float16-full/
```

Summary:

| Metric | Result |
|---|---:|
| Measured successes | 36 |
| Measured failures | 0 |
| OOM count | 0 |
| Model load | 3155.87 ms |
| First inference | 692.71 ms |
| P50 decode+transcribe | 391.51 ms |
| P95 decode+transcribe | 451.21 ms |
| P50 RTF | 0.07078 |
| P95 RTF | 0.08528 |
| Mean CER | 0.12249 |
| Mean WER | 1.06667 |
| GPU baseline used | 1465 MiB |
| GPU peak used | 1739 MiB |
| GPU delta peak | 274 MiB |

C1 vs C2 preliminary comparison:

| Metric | C1 small cuda float16 | C2 medium cuda int8_float16 |
|---|---:|---:|
| Measured successes | 36 | 36 |
| OOM count | 0 | 0 |
| P50 decode+transcribe | 172.61 ms | 391.51 ms |
| P95 decode+transcribe | 200.51 ms | 451.21 ms |
| P50 RTF | 0.03066 | 0.07078 |
| P95 RTF | 0.03790 | 0.08528 |
| Mean CER | 0.13512 | 0.12249 |
| Mean WER | 1.23333 | 1.06667 |
| GPU delta peak | 210 MiB | 274 MiB |

Interpretation boundaries:

- C2 improves pilot mean CER and WER slightly versus C1, but is roughly 2.2x slower on P50/P95 decode+transcribe.
- Both C1 and C2 are comfortably faster than real time on this pilot corpus.
- C2 passing does not decide production ASR model selection.
- C3 and C4 have not been executed.
- Real ASR application integration has not started.
- ASR and real TTS simultaneous residency remains unverified.

## 17. C3 pilot benchmark result — 2026-06-26

C3 completed successfully on the same 12-item pilot corpus.

C3 configuration:

| Model | Device | Compute type | Beam size | Language | Warmup | Repeats |
|---|---|---|---:|---|---:|---:|
| medium | cuda | float16 | 1 | zh | 2 | 3 |

Output directory:

```text
asr-benchmark-results/C3-medium-cuda-float16-full/
```

Summary:

| Metric | Result |
|---|---:|
| Measured successes | 36 |
| Measured failures | 0 |
| OOM count | 0 |
| Model load | 1960.74 ms |
| First inference | 666.00 ms |
| P50 decode+transcribe | 378.55 ms |
| P95 decode+transcribe | 436.00 ms |
| P50 RTF | 0.06818 |
| P95 RTF | 0.08241 |
| Mean CER | 0.12249 |
| Mean WER | 0.73333 |
| GPU baseline used | 2440 MiB |
| GPU peak used | 2714 MiB |
| GPU delta peak | 274 MiB |

C1/C2/C3 preliminary comparison:

| Metric | C1 small cuda float16 | C2 medium cuda int8_float16 | C3 medium cuda float16 |
|---|---:|---:|---:|
| Measured successes | 36 | 36 | 36 |
| OOM count | 0 | 0 | 0 |
| P50 decode+transcribe | 172.61 ms | 391.51 ms | 378.55 ms |
| P95 decode+transcribe | 200.51 ms | 451.21 ms | 436.00 ms |
| P50 RTF | 0.03066 | 0.07078 | 0.06818 |
| P95 RTF | 0.03790 | 0.08528 | 0.08241 |
| Mean CER | 0.13512 | 0.12249 | 0.12249 |
| Mean WER | 1.23333 | 1.06667 | 0.73333 |
| GPU delta peak | 210 MiB | 274 MiB | 274 MiB |

Interpretation boundaries:

- C3 has the same pilot mean CER as C2 and better pilot WER than C2.
- C3 is slightly faster than C2 in this run and remains comfortably faster than real time.
- The device-total GPU baseline before C3 was higher than earlier runs, so only the recorded delta should be compared cautiously.
- C3 passing does not decide production ASR model selection.
- C4 has not been executed.
- Real ASR application integration has not started.
- ASR and real TTS simultaneous residency remains unverified.

## 18. C4 pilot benchmark result — 2026-06-26

C4 completed successfully on the same 12-item pilot corpus.

C4 configuration:

| Model | Device | Compute type | Beam size | Language | Warmup | Repeats |
|---|---|---|---:|---|---:|---:|
| small | cpu | int8 | 1 | zh | 2 | 3 |

Output directory:

```text
asr-benchmark-results/C4-small-cpu-int8-full/
```

Summary:

| Metric | Result |
|---|---:|
| Measured successes | 36 |
| Measured failures | 0 |
| OOM count | 0 |
| Model load | 1114.73 ms |
| First inference | 1659.12 ms |
| P50 decode+transcribe | 1968.48 ms |
| P95 decode+transcribe | 2111.97 ms |
| P50 RTF | 0.35012 |
| P95 RTF | 0.42883 |
| Mean CER | 0.12871 |
| Mean WER | 1.23333 |
| GPU baseline used | 441 MiB |
| GPU peak used | 448 MiB |
| GPU delta peak | 7 MiB |

C1/C2/C3/C4 preliminary comparison:

| Metric | C1 small cuda float16 | C2 medium cuda int8_float16 | C3 medium cuda float16 | C4 small cpu int8 |
|---|---:|---:|---:|---:|
| Measured successes | 36 | 36 | 36 | 36 |
| OOM count | 0 | 0 | 0 | 0 |
| P50 decode+transcribe | 172.61 ms | 391.51 ms | 378.55 ms | 1968.48 ms |
| P95 decode+transcribe | 200.51 ms | 451.21 ms | 436.00 ms | 2111.97 ms |
| P50 RTF | 0.03066 | 0.07078 | 0.06818 | 0.35012 |
| P95 RTF | 0.03790 | 0.08528 | 0.08241 | 0.42883 |
| Mean CER | 0.13512 | 0.12249 | 0.12249 | 0.12871 |
| Mean WER | 1.23333 | 1.06667 | 0.73333 | 1.23333 |
| GPU delta peak | 210 MiB | 274 MiB | 274 MiB | 7 MiB |

Preliminary selection note:

- C3 is the strongest pilot candidate among C1-C4 by combined accuracy and speed: best WER, tied-best CER, no OOM, and sub-0.1 P95 RTF.
- C2 is close to C3 but has worse WER in this pilot run.
- C1 is much faster but less accurate.
- C4 is a viable CPU fallback because it is still faster than real time, but it is much slower than GPU configs and not the best accuracy result.
- Production ASR selection is still **NOT DECIDED** until transcript-level review and integration constraints are checked.
- Real ASR application integration has not started.
- ASR and real TTS simultaneous residency remains unverified.

## 19. Transcript-level review and initial ASR candidate — 2026-06-26

A local full-text review was generated for C1-C4 with `--include-full-text-output`, `warmup-runs=0`, and `repeats=1`. These review artifacts are under `asr-benchmark-results/review-*` and are covered by `.gitignore`; they must not be committed.

Review observations:

- C3 preserves normal daily Chinese sentences well after punctuation-insensitive normalization.
- The largest metric penalties are from numeric normalization mismatches, especially Chinese numerals in the reference versus Arabic digits in the hypothesis. Example class: `一二三四五` versus `12345`, and date/time numerals rendered as `2026年6月26日` / `8点30分`.
- Mixed technical terms remain the most important weakness. C3 is better than C1/C2/C4 overall, but still splits or reformats terms such as `SQLite` in at least one pilot item.
- Some Simplified/Traditional Chinese character variants appear in C3 output, for example `帮/幫`, `总结/總結`, `刚才/剛才`, `对话/對話`. This hurts the current CER but is mostly normalizable for downstream text input if desired.
- Short filler words such as `嗯` may be omitted. This is acceptable for command-style interaction but should be considered if conversational fidelity becomes important.

Selection decision for next implementation task:

- **Initial real ASR integration candidate: C3 (`medium` / `cuda` / `float16` / `beam_size=1` / `language=zh`).**
- **CPU fallback candidate: C4 (`small` / `cpu` / `int8`).**
- This is not a final production ASR selection; it is the first integration candidate for an application provider behind existing abstractions.

Why C3:

- It has 0 failures and 0 OOM on the pilot corpus.
- It ties C2 for best mean CER and has the best pilot WER.
- It is slightly faster than C2 in the full benchmark run.
- It remains far faster than real time on the pilot corpus.

Implementation implications for the next task:

- Add a real FasterWhisper ASR provider behind the existing application `ASRProvider` abstraction.
- Keep `/api/audio/transcriptions` response shape and validation behavior stable.
- Keep fake ASR as the default/test provider.
- Configure the real provider through environment/settings only.
- Add a startup/runtime check or controlled error for missing CUDA runtime DLLs.
- Do not enter 2C, VAD, streaming, long-term memory, or emotion features.

## 20. Historical next steps

At the time of this benchmark plan, the next steps were to commit benchmark updates and plan the real FasterWhisper ASR provider integration with C3 as the initial candidate and C4 as CPU fallback. Those tasks were later completed in Stage 2B-5 and Stage 2B-6. This section is retained only as historical evidence; the current project stage and next task are tracked in `CLAUDE.md`.
