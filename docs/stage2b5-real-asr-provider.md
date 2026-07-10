# 2B-5 Real ASR Provider Integration

> Status: implementation baseline complete; real provider smoke validated through `.venv-asr-bench`; main project optional ASR dependencies are declared but not installed in `.venv` by this task because package installation was blocked by permission policy.
>
> Current phase: Stage 2 — voice features. This task integrates a real FasterWhisper ASR provider behind the existing Stage 2B ASR abstraction. It does not implement 2C, VAD, streaming, interruption, long-term memory, or emotion.

## Scope

2B-5 keeps the existing browser recording and transcription API boundary stable:

- `POST /api/audio/transcriptions` response shape is unchanged.
- `ASRService` upload validation remains the gate for file size, MIME type, language, and provider result validation.
- Fake ASR remains the default provider for tests and normal development.
- FasterWhisper is enabled only with explicit local configuration.
- Raw audio is written only to a temporary file required by FasterWhisper and deleted in `finally`.

## Initial candidate

The initial real ASR candidate is based on the 2B-4 benchmark review:

| Setting | Value |
|---|---|
| Provider | `faster-whisper` |
| Model | `medium` |
| Revision | `08e178d48790749d25932bbc082711ddcfdfbc4f` |
| Device | `cuda` |
| Compute type | `float16` |
| Beam size | `1` |
| Language | `zh` |

CPU fallback candidate:

| Setting | Value |
|---|---|
| Model | `small` |
| Device | `cpu` |
| Compute type | `int8` |

This is an initial integration candidate, not a final production ASR selection.

## Configuration

Default remains fake:

```env
ASR_PROVIDER=fake
```

Local real ASR example:

```env
ASR_PROVIDER=faster-whisper
ASR_FASTER_WHISPER_MODEL_PATH=C:\Users\<you>\.cache\huggingface\hub\models--Systran--faster-whisper-medium\snapshots\08e178d48790749d25932bbc082711ddcfdfbc4f
ASR_FASTER_WHISPER_MODEL_NAME=medium
ASR_FASTER_WHISPER_MODEL_REVISION=08e178d48790749d25932bbc082711ddcfdfbc4f
ASR_FASTER_WHISPER_DEVICE=cuda
ASR_FASTER_WHISPER_COMPUTE_TYPE=float16
ASR_FASTER_WHISPER_BEAM_SIZE=1
ASR_FASTER_WHISPER_TIMEOUT_SECONDS=30
```

## Dependencies

Optional backend ASR dependencies are declared in `backend/pyproject.toml` under the `asr` extra:

```text
faster-whisper==1.2.1
nvidia-cublas-cu12==12.9.2.10; platform_system == 'Windows'
nvidia-cuda-nvrtc-cu12==12.9.86; platform_system == 'Windows'
```

In this task, installing those packages into the main `.venv` was blocked by permission policy. Real provider smoke validation used the already prepared `.venv-asr-bench` environment.

## Verification

Automated backend regression:

```text
.\.venv\Scripts\python.exe -m pytest backend/tests -v
```

Result:

```text
200 passed, 1 warning
```

Real provider smoke through `ASRService` using `.venv-asr-bench`:

- Input: local pilot `P001.m4a`
- Provider: `faster-whisper`
- Model: `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`
- Result: successful transcription response with duration and inference metadata

## Boundaries not crossed

- No 2C voice-turn orchestration.
- No VAD.
- No streaming ASR.
- No interruption.
- No long-term memory.
- No emotion system.
- No raw audio persistence.
- No API response shape change.

## 2B-6 main application smoke — 2026-06-27

Status: **PASS**

Verification:

- Main `.venv` ASR extra install: PASS（依赖已全部就绪，`faster-whisper==1.2.1`、`ctranslate2==4.8.0`、`nvidia-cublas-cu12==12.9.2.10`、`nvidia-cuda-nvrtc-cu12==12.9.86`）
- Main `.venv` import check: PASS（`import faster_whisper, ctranslate2` 成功）
- Provider construction: PASS（`faster-whisper` / `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`）
- Backend regression with Fake ASR: PASS（200 passed）
- Frontend regression: PASS（47 tests、typecheck、build、4 E2E 全部通过）
- Real ASR API smoke: PASS（P001.m4a → `"今天晚上我想先休息十分钟,然后再继续整理桌面。"`，`provider: faster-whisper`，`inference_ms: 3583`）
- Browser manual recording UI smoke: PASS（Playwright 自动化：转写 23 字符正确进入输入框，API 200，0 console errors）
- GPU model: `medium@08e178d48790749d25932bbc082711ddcfdfbc4f`，CUDA float16，inference ~2.9s for 6.7s audio

Notes:

- Real ASR remains opt-in through `ASR_PROVIDER=faster-whisper`.
- Fake ASR remains the default automated test path.
- This smoke does not decide final production ASR selection.
- This smoke does not implement real TTS, 2C, VAD, interruption, streaming, memory, or emotion.
- Next recommended task: begin real local TTS provider selection and integration planning (CosyVoice 3 is the leading candidate as of 2026-06).
