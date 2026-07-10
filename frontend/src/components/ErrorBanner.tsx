interface ErrorBannerProps {
  message: string | null;
  onDismiss: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  if (!message) return null;

  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      <button type="button" onClick={onDismiss}>关闭</button>
    </div>
  );
}
