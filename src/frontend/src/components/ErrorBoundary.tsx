import { Component, type ErrorInfo, type ReactNode } from 'react';
import { useI18n } from '../lib/i18n';

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // eslint-disable-next-line no-console
    console.error('Control-room UI crashed:', error, info.componentStack);
  }

  private reset = (): void => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return <ErrorFallback error={error} onReset={this.reset} />;
  }
}

function ErrorFallback({ error, onReset }: { error: Error; onReset: () => void }) {
  const { t, text } = useI18n();
  return (
      <div className="crash" role="alert">
        <h2>{t('The console hit an unexpected error')}</h2>
        <p className="muted">
          {t('The orchestration run is unaffected on the server. Dismiss this to return to the console, or reload the page for a clean slate.')}
        </p>
        <p>{text(error.message)}</p>
        {error.stack ? <pre>{error.stack.replace(error.message, text(error.message))}</pre> : null}
        <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
          <button type="button" className="btn btn--primary" onClick={onReset}>
            {t('Dismiss')}
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => window.location.reload()}
          >
            {t('Reload')}
          </button>
        </div>
      </div>
  );
}

export default ErrorBoundary;
