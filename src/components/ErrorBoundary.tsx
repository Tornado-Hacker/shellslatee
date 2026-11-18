import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { error: Error | null };

// The first run must never dump a raw stack trace on a stranger. Catch render
// crashes here and show something readable, with the message tucked behind a
// details toggle so support can still see it.
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Shellslatee UI error:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="grain grid h-screen place-items-center bg-bg px-6">
        <div className="w-full max-w-md rounded-2xl border bg-card/80 p-6 shadow-lg">
          <h1 className="font-display text-lg">Something went sideways</h1>
          <p className="mt-2 text-sm text-muted">
            Shellslatee hit an unexpected error. Your notes on disk are untouched. Reload to pick up
            where you left off.
          </p>
          <div className="mt-5 flex gap-2">
            <button className="btn btn-primary" onClick={() => window.location.reload()}>
              Reload
            </button>
            <button
              className="btn btn-ghost"
              onClick={() => {
                void navigator.clipboard?.writeText(String(this.state.error));
              }}
            >
              Copy details
            </button>
          </div>
          <details className="mt-4 text-[11px] text-muted">
            <summary className="cursor-pointer">Details</summary>
            <pre className="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-bg/60 p-2">
              {String(this.state.error)}
            </pre>
          </details>
        </div>
      </div>
    );
  }
}
