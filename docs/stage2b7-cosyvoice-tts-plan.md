# 2B-7 CosyVoice 3 Real TTS Provider Integration Plan

> Status: planning | Date: 2026-06-27
>
> **Goal:** Integrate CosyVoice 3 as the first real local TTS provider behind the existing `TTSProvider` interface, enabling natural Chinese speech output for the character.

## 1. Architecture Decision: Process Isolation

**Problem:** CosyVoice 3 requires Python 3.10; main `.venv` uses Python 3.12. In-process loading is impossible.

**Decision:** Run CosyVoice 3 as a separate subprocess/HTTP server.

**Options compared:**

| Option | Python compat | Complexity | Latency | Maintainability |
|--------|--------------|------------|---------|-----------------|
| A. Separate HTTP server (CosyVoice FastAPI) | ✅ Any | Medium | +network RTT | ✅ Clean separation |
| B. subprocess stdin/stdout | ✅ Any | High | +IPC | ❌ Fragile |
| C. Shared venv upgrade | ❌ | Low | Best | ❌ Requires Python 3.10 |
| D. kokoro-82M (Python 3.12 compat) | ✅ | Low | Best | ❌ No Chinese support |

**Selected: Option A** — Separate CosyVoice FastAPI HTTP server on `127.0.0.1` with a dedicated `.venv-tts` (Python 3.10).

## 2. Provider Design

```
backend/app/tts/cosyvoice_provider.py → TTSProvider impl
  → httpx.AsyncClient → http://127.0.0.1:${TTS_PORT}/v1/audio/speech
  → CosyVoice 3 server (.venv-tts, Python 3.10)
```

### Configuration

```env
TTS_PROVIDER=cosyvoice
TTS_COSYVOICE_BASE_URL=http://127.0.0.1:8001
TTS_COSYVOICE_MODEL=Fun-CosyVoice3-0.5B-2512
TTS_COSYVOICE_VOICE_ID=default-zh-female
TTS_COSYVOICE_SPEED=1.0
TTS_COSYVOICE_TIMEOUT_SECONDS=30
```

### Provider Interface (unchanged)

```python
class CosyVoiceTTSProvider:
    async def synthesize(self, text: str, voice_id: str | None, speed: float) -> SpeechSynthesisResult:
        # POST to CosyVoice server
        # Returns WAV audio bytes
```

## 3. Resource Assessment

| Resource | Measured / Estimate |
|----------|---------------------|
| Local GPU | RTX 3060 Laptop GPU, 6144 MiB total, ~5480 MiB free before TTS |
| CosyVoice 3 0.5B VRAM (FP16) | ~2.9–4.0 GB depending on mode |
| FasterWhisper medium VRAM | ~274 MiB measured delta in prior benchmark |
| Combined expected peak | ~3.2–4.5 GB |
| Safety margin on 6GB GPU | Tight but viable if no streaming/style-control/batching |
| **Verdict** | ✅ Feasible for short non-streaming synthesis; benchmark required before declaring real-time |

Model download: ~2GB (Fun-CosyVoice3-0.5B-2512 + ttsfrd)

## 4. Voice Character Design

Target character: 雪之下雪乃 (Yukinoshita Yukino)
- Personality: Cool, intelligent, articulate, occasionally sarcastic
- Voice style: Clear, calm female voice, measured pace
- Source: CosyVoice 3 base model or provide a reference voice clip
- **License check required before voice cloning**

Default option: Use CosyVoice 3 base female voice without cloning, as it already supports Chinese.

## 5. Task Breakdown

### Task 1: CosyVoice 3 Server Setup
- Create `.venv-tts` with Python 3.10
- Clone CosyVoice repo
- Install dependencies
- Download Fun-CosyVoice3-0.5B-2512 model
- Verify inference works

### Task 2: CosyVoiceTTSProvider Implementation
- Implement `CosyVoiceTTSProvider` behind existing `TTSProvider`
- Add `TTS_PROVIDER=cosyvoice` to config
- Add `CosyVoiceTTSServer` helper to start/health-check CosyVoice process

### Task 3: Integration Testing
- Provider unit tests
- API smoke with real CosyVoice
- UI smoke: real ASR → DeepSeek chat → real TTS playback

### Task 4: Documentation
- Update README, CLAUDE.md
- Record verification results

## 6. Non-goals
- No streaming TTS in this task
- No emotion-driven voice modulation (Stage 4)
- No voice cloning
- No VAD/interruption (2D/2E)

## 7. Prerequisites
- Python 3.10 installed on system — **DONE: Python 3.10.11 installed via winget on 2026-06-27**
- Git with submodule support — **DONE: `external/CosyVoice` cloned with submodules**
- ~5GB disk space for model and dependencies
- External dependency installation authorization — **BLOCKED by permission policy; user must explicitly allow or run command manually**

## 8. Implementation progress — 2026-06-27

Completed:

- Added `CosyVoiceHTTPProvider` behind existing `TTSProvider` interface.
- Added `TTS_PROVIDER=cosyvoice-http` configuration.
- Added safe HTTP timeout/error mapping to existing `TTSError` hierarchy.
- Disabled environment proxy inheritance for local CosyVoice HTTP calls (`trust_env=False`), required for reliable `127.0.0.1` requests on this Windows environment.
- Added unit tests for config, factory, payload shape, timeout mapping, and HTTP error mapping.
- Installed Python 3.10.11 and created isolated `.venv-tts`.
- Installed CosyVoice dependencies after adding a build constraint for `setuptools<81` to satisfy `openai-whisper==20231117` build-time `pkg_resources` usage.
- Downloaded `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` into `external/CosyVoice/pretrained_models/Fun-CosyVoice3-0.5B-2512`.
- Verified local CosyVoice3 synthesis smoke with non-private Chinese text.
- Added a local OpenAI-compatible smoke server at `scripts/cosyvoice3_openai_server.py`.
- Verified main backend `/api/audio/speech` through `TTS_PROVIDER=cosyvoice-http`.

Verification:

- Dependency import check: PASS (`torch 2.3.1+cu121`, `torchaudio 2.3.1+cu121`, CUDA available on RTX 3060 Laptop GPU).
- Local CosyVoice3 synthesis smoke: PASS.
  - Output: `data/cosyvoice-smoke-output.wav`
  - Output bytes: 245,804
  - Sample rate: 24,000 Hz
  - Audio duration: 5,120 ms
  - Model load: 12,668 ms
  - Synthesis: 6,144 ms
  - GPU reserved after load/synth: ~3.5 GB
- Local `/v1/audio/speech` direct API smoke: PASS.
  - Status: 200
  - Content-Type: `audio/wav`
  - Duration: 5,120 ms
  - Sample rate: 24,000 Hz
  - Output bytes: 245,804
- Main backend `cosyvoice-http` smoke: PASS.
  - Status: 200
  - Content-Type: `audio/wav`
  - Provider: `cosyvoice-http`
  - Model: `Fun-CosyVoice3-0.5B-2512`
  - Duration: 4,480 ms
  - Sample rate: 24,000 Hz
  - Output bytes: 215,084
- Browser real TTS playback UI smoke: PASS.
  - Playwright seeded a session through the backend, opened the browser UI, clicked assistant-message `播放`, and observed `/api/audio/speech` response.
  - Response: status 200, `content-type: audio/wav`, provider `cosyvoice-http`, model `Fun-CosyVoice3-0.5B-2512`, duration 5,200 ms, sample rate 24,000 Hz.
  - UI result: no audio error, 0 console errors.
  - Screenshot: `frontend/test-results/real-tts-ui-smoke.png`.
- Backend regression: PASS (`204 passed, 1 warning`).

Notes:

- The smoke uses the official CosyVoice sample prompt audio (`external/CosyVoice/asset/zero_shot_prompt.wav`) only for local technical verification.
- This task does **not** clone or imitate Yukinoshita Yukino, any voice actor, celebrity, or unauthorized voice.
- Real TTS remains opt-in via `TTS_PROVIDER=cosyvoice-http` and requires starting the separate local CosyVoice server.
- This task does not implement 2C full half-duplex voice turns, VAD, interruption, streaming, memory, or emotion.

Next recommended task:

- Package the CosyVoice local server startup instructions into the main README and then plan 2C full half-duplex voice turns: ASR transcript → existing text chat → real TTS playback, while keeping manual confirmation/default no-autoplay boundaries.