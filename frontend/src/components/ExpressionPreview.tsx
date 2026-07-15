import type { ExpressionPreviewState } from '../expression/previewReducer';

const DELIVERY_LABEL = {
  neutral: '中性表达',
  warm: '温和表达',
  reassuring: '安慰表达',
  reserved: '克制表达',
  firm: '坚定表达',
} as const;

const PHASE_LABEL = {
  idle: '等待消息',
  ready: '准备就绪',
  speaking: '正在说话',
  paused: '已暂停',
} as const;

interface ExpressionPreviewProps {
  state: ExpressionPreviewState;
  displayLabel: string;
}

export function ExpressionPreview({
  state,
  displayLabel,
}: ExpressionPreviewProps) {
  const delivery = state.expression?.delivery ?? 'neutral';
  return (
    <section
      className={`expression-preview expression-preview--${delivery}`}
      aria-label="角色表现预览"
    >
      <div className="expression-preview__avatar" aria-hidden="true">
        <span />
      </div>
      <div className="expression-preview__status" aria-live="polite">
        <strong>{DELIVERY_LABEL[delivery]}</strong>
        <span>{PHASE_LABEL[state.phase]}</span>
      </div>
      <p className="expression-preview__label">{displayLabel}</p>
      <small>这是角色表达策略，不代表真实感情或意识。</small>
    </section>
  );
}
