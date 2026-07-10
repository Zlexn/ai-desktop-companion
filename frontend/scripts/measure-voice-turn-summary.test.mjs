import { describe, expect, it } from 'vitest';

import { summarizeVoiceTurnRuns, validateStreamingVoiceTurnRun } from './measure-voice-turn-summary.mjs';

describe('measure voice turn summary helpers', () => {
  it('accepts exactly one streaming TTS request and no legacy TTS request', () => {
    const run = {
      transcriptionRequests: 1,
      chatPostRequests: 1,
      streamTtsRequests: 1,
      ttsRequests: 0,
      playCalls: 1,
      streamSegmentCount: 1,
    };

    expect(validateStreamingVoiceTurnRun(run)).toBeNull();
  });

  it('rejects legacy non-streaming TTS for the streaming measurement path', () => {
    const run = {
      transcriptionRequests: 1,
      chatPostRequests: 1,
      streamTtsRequests: 0,
      ttsRequests: 1,
      playCalls: 1,
      streamSegmentCount: 0,
    };

    expect(validateStreamingVoiceTurnRun(run)).toBe(
      'Expected exactly one transcription, chat, streaming TTS, playback event, and at least one stream segment.',
    );
  });

  it('includes streaming first-segment timing fields', () => {
    const summary = summarizeVoiceTurnRuns([
      {
        recordingMs: 100,
        stopToTranscriptMs: 10,
        sendToAssistantVisibleMs: 20,
        chatRequestMs: 15,
        streamTtsRequestToFirstSegmentMs: 30,
        streamFirstSegmentToPlayMs: 5,
        streamSendToFirstPlaybackMs: 40,
        streamDoneMs: 50,
        streamSegmentCount: 2,
        endToEndMs: 150,
      },
    ]);

    expect(summary.streamTtsRequestToFirstSegmentMs).toEqual({ min: 30, mean: 30, max: 30 });
    expect(summary.streamFirstSegmentToPlayMs).toEqual({ min: 5, mean: 5, max: 5 });
    expect(summary.streamSegmentCount).toEqual({ min: 2, mean: 2, max: 2 });
  });
});
