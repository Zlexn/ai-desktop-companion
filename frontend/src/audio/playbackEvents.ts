import type { PlaybackRun } from '../expression/events';

export function samePlaybackRun(
  left: PlaybackRun | null,
  right: PlaybackRun,
): boolean {
  return (
    left?.assistantMessageId === right.assistantMessageId &&
    left.playbackRunId === right.playbackRunId
  );
}
