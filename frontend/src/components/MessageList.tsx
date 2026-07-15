import type { Message } from '../api/types';
import { AssistantAudioControls } from './AssistantAudioControls';
import { useAudioPlaybackController } from '../hooks/useAudioPlaybackController';

interface MessageListProps {
  messages: Message[];
  audioController: ReturnType<typeof useAudioPlaybackController>;
  playbackBlocked: boolean;
}

export function MessageList({ messages, audioController, playbackBlocked }: MessageListProps) {
  if (messages.length === 0) {
    return <p className="empty-state">发送一句话，开始和角色聊天。</p>;
  }

  return (
    <div className="message-list" aria-label="消息列表">
      {messages.map((message) => (
        <article className={`message message--${message.role}`} key={message.id}>
          <span className="message__role">{message.role === 'user' ? '你' : '林夕'}</span>
          <p>{message.content}</p>
          {message.role === 'assistant' ? (
            <AssistantAudioControls
              audioState={audioController.stateFor(message.id)}
              onPause={() => audioController.pause(message.id)}
              onPlay={() => audioController.play(message.id)}
              onReplay={() => audioController.replay(message.id)}
              onResume={() => audioController.resume(message.id)}
              onStop={() => audioController.stop(message.id)}
              disabled={playbackBlocked}
            />
          ) : null}
        </article>
      ))}
    </div>
  );
}
