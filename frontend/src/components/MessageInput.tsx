import { FormEvent, useState } from 'react';

interface MessageInputProps {
  disabled: boolean;
  onSend: (content: string) => Promise<void>;
  /** ASR transcript pending user action — null means no pending transcript. */
  pendingTranscript: string | null;
  /** Called when the user discards the pending transcript without applying it. */
  onClearPendingTranscript: () => void;
  onSendAndSpeakTranscript: (transcript: string) => Promise<void>;
  voiceTurnBusy: boolean;
  voiceTurnError: string | null;
}

export function MessageInput({
  disabled,
  onSend,
  pendingTranscript,
  onClearPendingTranscript,
  onSendAndSpeakTranscript,
  voiceTurnBusy,
  voiceTurnError,
}: MessageInputProps) {
  const [content, setContent] = useState('');

  // Apply transcript when pendingTranscript arrives and input is empty
  const prevPendingRef = { current: pendingTranscript };
  if (pendingTranscript !== null && pendingTranscript !== prevPendingRef.current) {
    prevPendingRef.current = pendingTranscript;
  }

  function applyReplace(transcript: string) {
    setContent(transcript);
    onClearPendingTranscript();
  }

  function applyAppend(transcript: string) {
    setContent((prev) => (prev.trim() ? prev + '\n' + transcript : transcript));
    onClearPendingTranscript();
  }

  function applyDiscard() {
    onClearPendingTranscript();
  }

  async function applySendAndSpeak(transcript: string) {
    await onSendAndSpeakTranscript(transcript);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const cleanContent = content.trim();
    if (!cleanContent) return;
    await onSend(cleanContent);
    setContent('');
  }

  return (
    <div className="message-input-wrapper">
      {/* pending transcript conflict area */}
      {pendingTranscript !== null && (
        <div className="message-input__pending" role="status" aria-live="polite">
          <span className="message-input__pending-label">转写待确认：{pendingTranscript}</span>
          <div className="message-input__pending-actions">
            <button type="button" aria-label="替换输入框" onClick={() => applyReplace(pendingTranscript)}>
              替换
            </button>
            <button type="button" aria-label="追加到输入框" onClick={() => applyAppend(pendingTranscript)}>
              追加
            </button>
            <button
              type="button"
              aria-label="发送并朗读"
              disabled={disabled || voiceTurnBusy}
              onClick={() => void applySendAndSpeak(pendingTranscript)}
            >
              {voiceTurnBusy ? '发送并朗读中…' : '发送并朗读'}
            </button>
            <button type="button" aria-label="丢弃转写" onClick={applyDiscard}>
              丢弃
            </button>
          </div>
        </div>
      )}

      {voiceTurnError ? (
        <div className="message-input__voice-error" role="alert">
          {voiceTurnError}
        </div>
      ) : null}

      <form className="message-input" onSubmit={handleSubmit}>
        <label htmlFor="message-content">输入消息</label>
        <textarea
          id="message-content"
          value={content}
          disabled={disabled}
          placeholder="和林夕说点什么……"
          onChange={(event) => setContent(event.target.value)}
        />
        <button type="submit" disabled={disabled || content.trim().length === 0}>
          发送
        </button>
      </form>
    </div>
  );
}
