import type { MessageAudioState } from '../hooks/useAudioPlaybackController';

interface AssistantAudioControlsProps {
  audioState: MessageAudioState;
  onPause: () => void;
  onPlay: () => void;
  onReplay: () => void;
  onResume: () => void;
  onStop: () => void;
  disabled?: boolean;
}

export function AssistantAudioControls({
  audioState,
  onPause,
  onPlay,
  onReplay,
  onResume,
  onStop,
  disabled = false,
}: AssistantAudioControlsProps) {
  const isSynthesizing = audioState.state === 'synthesizing';
  const isPlaying = audioState.state === 'playing';
  const isPaused = audioState.state === 'paused';
  const hasAudio = audioState.state === 'ready' || isPlaying || isPaused;
  const controlsDisabled = disabled || isSynthesizing;

  return (
    <div className="audio-controls" aria-label="语音播放控制">
      {!hasAudio ? (
        <button type="button" disabled={controlsDisabled} onClick={onPlay}>
          {isSynthesizing ? '生成中…' : disabled ? '播放暂停' : '播放'}
        </button>
      ) : null}
      {audioState.state === 'ready' ? (
        <button type="button" disabled={disabled} onClick={onPlay}>
          播放
        </button>
      ) : null}
      {isPlaying ? (
        <button type="button" disabled={disabled} onClick={onPause}>
          暂停
        </button>
      ) : null}
      {isPaused ? (
        <button type="button" disabled={disabled} onClick={onResume}>
          继续
        </button>
      ) : null}
      {hasAudio ? (
        <>
          <button type="button" disabled={disabled} onClick={onStop}>
            停止
          </button>
          <button type="button" disabled={disabled} onClick={onReplay}>
            重播
          </button>
        </>
      ) : null}
      {audioState.error ? <span className="audio-controls__error">{audioState.error}</span> : null}
    </div>
  );
}
