# Stage 2F-1 Streaming Performance Measurement Baseline Evidence

Status: COMPLETED on 2026-06-29.

## Scope

This slice adds a repeatable fake-provider browser measurement baseline for the existing non-streaming half-duplex voice turn. It measures ASR, chat, TTS, playback trigger, and end-to-end timing through the real browser UI.

It does not implement streaming ASR, streaming TTS, output device selection, long-term memory, or emotion behavior.

## Validation

| Command | Result |
|---|---|
| `node scripts/measure-voice-turn-latency.mjs` with app not running | PASS as failure-path check — exits 1 with `Frontend is not reachable` |
| `npm run measure:voice-turn` with app not running | PASS as failure-path check — exits 1 with `Frontend is not reachable` |
| `npm run measure:voice-turn` with fake backend/frontend | PASS — 3 valid measured runs, 0 console/page errors |
| `npm test -- --run src/App.test.tsx` | PASS — 18 passed |
| `npm test -- --run` | PASS — 81 passed |
| `npm run typecheck` | PASS |
| `npm run build` | PASS |
| `npm run test:e2e` | PASS — 5 passed |

## Measurement output

```json
{
  "runCount": 3,
  "frontendUrl": "http://127.0.0.1:15176",
  "runs": [
    {
      "index": 1,
      "recordingMs": 374.32,
      "stopToTranscriptMs": 6.96,
      "sendToAssistantVisibleMs": 79.9,
      "chatRequestMs": 13.83,
      "ttsRequestMs": 1.18,
      "ttsResponseToPlayMs": 68.21,
      "sendToPlaybackMs": 93.28,
      "endToEndMs": 529.18,
      "transcriptionRequests": 1,
      "chatPostRequests": 1,
      "ttsRequests": 1,
      "playCalls": 1
    },
    {
      "index": 2,
      "recordingMs": 364.4,
      "stopToTranscriptMs": 4.09,
      "sendToAssistantVisibleMs": 1.9,
      "chatRequestMs": 13.49,
      "ttsRequestMs": 0.82,
      "ttsResponseToPlayMs": 5.49,
      "sendToPlaybackMs": 30.75,
      "endToEndMs": 432.54,
      "transcriptionRequests": 1,
      "chatPostRequests": 1,
      "ttsRequests": 1,
      "playCalls": 1
    },
    {
      "index": 3,
      "recordingMs": 362.87,
      "stopToTranscriptMs": 25.17,
      "sendToAssistantVisibleMs": 2.42,
      "chatRequestMs": 14.04,
      "ttsRequestMs": 0.82,
      "ttsResponseToPlayMs": 5.25,
      "sendToPlaybackMs": 28.09,
      "endToEndMs": 452.22,
      "transcriptionRequests": 1,
      "chatPostRequests": 1,
      "ttsRequests": 1,
      "playCalls": 1
    }
  ],
  "summary": {
    "recordingMs": { "min": 362.87, "mean": 367.2, "max": 374.32 },
    "stopToTranscriptMs": { "min": 4.09, "mean": 12.07, "max": 25.17 },
    "sendToAssistantVisibleMs": { "min": 1.9, "mean": 28.07, "max": 79.9 },
    "chatRequestMs": { "min": 13.49, "mean": 13.79, "max": 14.04 },
    "ttsRequestMs": { "min": 0.82, "mean": 0.94, "max": 1.18 },
    "ttsResponseToPlayMs": { "min": 5.25, "mean": 26.32, "max": 68.21 },
    "sendToPlaybackMs": { "min": 28.09, "mean": 50.71, "max": 93.28 },
    "endToEndMs": { "min": 432.54, "mean": 471.31, "max": 529.18 }
  },
  "consoleErrors": [],
  "pageErrors": []
}
```

## Debug note

The first measurement run produced negative playback timings because the script mixed Node-side `performance.now()` timestamps with browser-context `performance.now()` timestamps captured inside the injected `HTMLMediaElement.play`. The script now records playback trigger time on the Node/Playwright side immediately after observing the browser play-call count change, so all reported durations use one clock origin.

## Notes

- This is a fake-provider browser baseline only.
- These values are useful for regression comparison and measurement shape, not for real provider latency claims.
- No real microphone, real ASR, real LLM, or real TTS provider was used.
- No streaming ASR/TTS was implemented by this task.
