export function round(value) {
  return Math.round(value * 100) / 100;
}

function stats(values) {
  const finite = values.filter((value) => Number.isFinite(value));
  if (finite.length === 0) return { min: null, mean: null, max: null };
  return {
    min: round(Math.min(...finite)),
    mean: round(finite.reduce((sum, value) => sum + value, 0) / finite.length),
    max: round(Math.max(...finite)),
  };
}

export function summarizeVoiceTurnRuns(runs) {
  return {
    recordingMs: stats(runs.map((run) => run.recordingMs)),
    stopToTranscriptMs: stats(runs.map((run) => run.stopToTranscriptMs)),
    sendToAssistantVisibleMs: stats(runs.map((run) => run.sendToAssistantVisibleMs)),
    chatRequestMs: stats(runs.map((run) => run.chatRequestMs)),
    streamTtsRequestToFirstSegmentMs: stats(runs.map((run) => run.streamTtsRequestToFirstSegmentMs)),
    streamFirstSegmentToPlayMs: stats(runs.map((run) => run.streamFirstSegmentToPlayMs)),
    streamSendToFirstPlaybackMs: stats(runs.map((run) => run.streamSendToFirstPlaybackMs)),
    streamDoneMs: stats(runs.map((run) => run.streamDoneMs)),
    streamSegmentCount: stats(runs.map((run) => run.streamSegmentCount)),
    endToEndMs: stats(runs.map((run) => run.endToEndMs)),
  };
}

export function validateStreamingVoiceTurnRun(run) {
  const validCounts = run.transcriptionRequests === 1
    && run.chatPostRequests === 1
    && run.streamTtsRequests === 1
    && run.ttsRequests === 0
    && run.playCalls === 1
    && run.streamSegmentCount >= 1;
  if (validCounts) return null;
  return 'Expected exactly one transcription, chat, streaming TTS, playback event, and at least one stream segment.';
}
