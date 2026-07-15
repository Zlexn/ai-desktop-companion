import { cleanup, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { ExpressionPreviewState } from '../expression/previewReducer';
import { ExpressionPreview } from './ExpressionPreview';

const state: ExpressionPreviewState = {
  selectedAssistantMessageId: 'a',
  expression: {
    type: 'expression',
    assistantMessageId: 'a',
    schemaVersion: 1,
    delivery: 'reassuring',
    intensity: 'medium',
    rate: 0.96,
    source: 'persisted_plan',
  },
  activeRun: { assistantMessageId: 'a', playbackRunId: 4 },
  phase: 'speaking',
};

afterEach(cleanup);

describe('ExpressionPreview', () => {
  it('renders expression, speaking status and the in-memory label without images', () => {
    render(
      <ExpressionPreview
        state={state}
        displayLabel="我会陪你慢慢说。"
      />,
    );

    expect(
      screen.getByRole('region', { name: '角色表现预览' }),
    ).toBeInTheDocument();
    expect(screen.getByText('安慰表达')).toBeInTheDocument();
    expect(screen.getByText('正在说话')).toBeInTheDocument();
    expect(screen.getByText('我会陪你慢慢说。')).toBeInTheDocument();
    expect(screen.getByText('这是角色表达策略，不代表真实感情或意识。')).toBeInTheDocument();
    expect(screen.getByText('正在说话').parentElement).toHaveAttribute('aria-live', 'polite');
    expect(document.querySelector('img')).toBeNull();
  });

  it.each([
    ['neutral', '中性表达'],
    ['warm', '温和表达'],
    ['reassuring', '安慰表达'],
    ['reserved', '克制表达'],
    ['firm', '坚定表达'],
  ] as const)('shows the fixed delivery label for %s', (delivery, label) => {
    render(
      <ExpressionPreview
        state={{
          ...state,
          expression: state.expression ? { ...state.expression, delivery } : null,
        }}
        displayLabel="助手消息"
      />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it.each([
    ['idle', '等待消息'],
    ['ready', '准备就绪'],
    ['speaking', '正在说话'],
    ['paused', '已暂停'],
  ] as const)('shows accessible text for %s', (phase, label) => {
    render(
      <ExpressionPreview state={{ ...state, phase }} displayLabel="助手消息" />,
    );
    expect(screen.getByText(label)).toBeInTheDocument();
  });
});
