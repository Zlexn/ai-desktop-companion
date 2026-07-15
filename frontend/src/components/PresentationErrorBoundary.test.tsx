import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { PresentationErrorBoundary } from './PresentationErrorBoundary';

function Broken(): never {
  throw new Error('preview broke');
}

it('isolates a preview error from sibling chat content', () => {
  const consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined);
  try {
    render(
      <div>
        <span>聊天仍可用</span>
        <PresentationErrorBoundary>
          <Broken />
        </PresentationErrorBoundary>
      </div>,
    );
    expect(screen.getByText('聊天仍可用')).toBeInTheDocument();
    expect(screen.getByText('角色预览暂时不可用。')).toBeInTheDocument();
  } finally {
    consoleError.mockRestore();
  }
});
