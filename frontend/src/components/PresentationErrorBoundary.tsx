import { Component, type ErrorInfo, type ReactNode } from 'react';

interface PresentationErrorBoundaryProps {
  children: ReactNode;
}

interface PresentationErrorBoundaryState {
  failed: boolean;
}

export class PresentationErrorBoundary extends Component<
  PresentationErrorBoundaryProps,
  PresentationErrorBoundaryState
> {
  state: PresentationErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): PresentationErrorBoundaryState {
    return { failed: true };
  }

  componentDidCatch(_error: Error, _info: ErrorInfo): void {
    // The preview is optional; the local fallback keeps the chat UI usable.
  }

  render(): ReactNode {
    if (this.state.failed) {
      return <p role="status">角色预览暂时不可用。</p>;
    }
    return this.props.children;
  }
}
