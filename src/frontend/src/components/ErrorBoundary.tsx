import { Component, type ErrorInfo, type ReactNode } from 'react';

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

    return (
      <div className="crash" role="alert">
        <h2>The console hit an unexpected error</h2>
        <p className="muted">
          The orchestration run is unaffected on the server. Dismiss this to return to the
          console, or reload the page for a clean slate.
        </p>
        <pre>{error.stack ?? error.message}</pre>
        <div style={{ marginTop: 16, display: 'flex', gap: 10 }}>
          <button type="button" className="btn btn--primary" onClick={this.reset}>
            Dismiss
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}

export default ErrorBoundary;
