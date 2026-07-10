import type { UseAudioInputDevicesResult } from '../hooks/useAudioInputDevices';
import type { UseAudioOutputDevicesResult } from '../hooks/useAudioOutputDevices';
import type { UseManualAudioRecorderResult } from '../hooks/useManualAudioRecorder';

interface VoiceRecorderProps {
  recorder: UseManualAudioRecorderResult;
  disabled: boolean;
  vadStatusMessage?: string | null;
  hintMessage?: string | null;
  audioInputDevices: UseAudioInputDevicesResult;
  audioOutputDevices: UseAudioOutputDevicesResult;
}

function formatElapsed(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

export function VoiceRecorder({
  recorder,
  disabled,
  vadStatusMessage,
  hintMessage,
  audioInputDevices,
  audioOutputDevices,
}: VoiceRecorderProps) {
  const { status, elapsedMs, error } = recorder;
  const deviceControlsDisabled = disabled || recorder.isPlaybackBlocked;

  return (
    <div className="voice-recorder" aria-live="polite">
      {hintMessage ? <span className="voice-recorder__hint">{hintMessage}</span> : null}
      <div className="voice-recorder__devices">
        <label>
          麦克风
          <select
            aria-label="麦克风"
            value={audioInputDevices.selectedDeviceId}
            disabled={deviceControlsDisabled}
            onChange={(event) => audioInputDevices.setSelectedDeviceId(event.target.value)}
          >
            <option value="">系统默认麦克风</option>
            {audioInputDevices.devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-label="刷新设备"
          disabled={deviceControlsDisabled || audioInputDevices.status === 'loading'}
          onClick={() => { void audioInputDevices.refreshDevices(); }}
        >
          刷新设备
        </button>
        {audioInputDevices.status === 'loading' ? <span>正在读取麦克风设备</span> : null}
        {audioInputDevices.status === 'unsupported' || audioInputDevices.status === 'error' ? (
          <span className="voice-recorder__device-error">{audioInputDevices.error}</span>
        ) : null}
      </div>
      <div className="voice-recorder__devices">
        <label>
          扬声器/耳机
          <select
            aria-label="扬声器/耳机"
            value={audioOutputDevices.selectedDeviceId}
            disabled={deviceControlsDisabled || audioOutputDevices.status === 'unsupported'}
            onChange={(event) => audioOutputDevices.setSelectedDeviceId(event.target.value)}
          >
            <option value="">系统默认输出设备</option>
            {audioOutputDevices.devices.map((device) => (
              <option key={device.deviceId} value={device.deviceId}>
                {device.label}
              </option>
            ))}
          </select>
        </label>
        {audioOutputDevices.canSelectOutput ? (
          <button
            type="button"
            aria-label="选择输出设备"
            disabled={deviceControlsDisabled || audioOutputDevices.status === 'loading'}
            onClick={() => { void audioOutputDevices.selectOutputDevice(); }}
          >
            选择输出设备
          </button>
        ) : null}
        <button
          type="button"
          aria-label="刷新输出设备"
          disabled={deviceControlsDisabled || audioOutputDevices.status === 'loading' || audioOutputDevices.status === 'unsupported'}
          onClick={() => { void audioOutputDevices.refreshDevices(); }}
        >
          刷新输出设备
        </button>
        {audioOutputDevices.status === 'loading' ? <span>正在读取输出设备</span> : null}
        {audioOutputDevices.status === 'unsupported' || audioOutputDevices.status === 'error' ? (
          <span className="voice-recorder__device-error">{audioOutputDevices.error}</span>
        ) : null}
      </div>
      {/* idle */}
      {status === 'idle' && (
        <button
          type="button"
          aria-label="开始录音"
          disabled={disabled}
          onClick={() => recorder.startRecording('')}
        >
          开始录音
        </button>
      )}

      {/* requesting permission */}
      {status === 'requesting_permission' && (
        <div className="voice-recorder__status">
          <span aria-label="正在请求麦克风权限">正在请求麦克风权限</span>
        </div>
      )}

      {/* recording */}
      {status === 'recording' && (
        <div className="voice-recorder__recording">
          <span className="voice-recorder__indicator" aria-hidden="true">🔴</span>
          <span aria-label={`已录音 ${formatElapsed(elapsedMs)}`}>{formatElapsed(elapsedMs)}</span>
          {vadStatusMessage ? (
            <span className="voice-recorder__vad-status" aria-label={vadStatusMessage}>
              {vadStatusMessage}
            </span>
          ) : null}
          <button type="button" aria-label="停止录音" onClick={() => recorder.stopRecording()}>
            停止录音
          </button>
          <button type="button" aria-label="取消录音" onClick={() => recorder.cancelRecording()}>
            取消
          </button>
        </div>
      )}

      {/* stopping */}
      {status === 'stopping' && (
        <div className="voice-recorder__status">
          <span>正在结束录音</span>
        </div>
      )}

      {/* uploading / transcribing */}
      {(status === 'uploading' || status === 'transcribing') && (
        <div className="voice-recorder__status">
          <span>正在转写</span>
          <button type="button" aria-label="取消转写" onClick={() => recorder.cancelRecording()}>
            取消转写
          </button>
        </div>
      )}

      {recorder.partialTranscript ? (
        <div className="voice-recorder__partial" aria-label="实时转写预览">
          实时转写预览：{recorder.partialTranscript}
        </div>
      ) : null}

      {/* ready — no visible controls here; transcript is in input box */}
      {status === 'ready' && null}

      {/* error */}
      {status === 'error' && error && (
        <div className="voice-recorder__error" role="alert">
          <span>{error.message}</span>
          <button type="button" aria-label="重试录音" disabled={disabled} onClick={() => recorder.startRecording('')}>
            重试
          </button>
        </div>
      )}
    </div>
  );
}
