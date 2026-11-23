import { Component, ErrorInfo, ReactNode } from "react";
import { AlertTriangle, RefreshCw, LogOut } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Uncaught error caught by ErrorBoundary:", error, errorInfo);
    this.setState({ error, errorInfo });
  }

  private handleReset = () => {
    localStorage.clear();
    window.location.href = "/login";
  };

  private handleReload = () => {
    window.location.reload();
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center p-6 bg-slate-950 text-slate-100">
          <div className="max-w-xl w-full p-8 rounded-2xl bg-slate-900 border border-rose-500/30 shadow-2xl">
            <div className="flex items-center gap-3 text-rose-400 mb-4">
              <AlertTriangle className="w-8 h-8 flex-shrink-0" />
              <div>
                <h2 className="text-lg font-bold text-white">Application Exception Caught</h2>
                <p className="text-xs text-rose-300">
                  The dashboard caught an unexpected render error. The state has been preserved.
                </p>
              </div>
            </div>

            {this.state.error && (
              <pre className="p-3 mb-6 rounded-lg bg-slate-950 border border-slate-800 text-xs font-mono text-rose-300 overflow-x-auto whitespace-pre-wrap">
                {this.state.error.toString()}
              </pre>
            )}

            <div className="flex flex-wrap gap-3">
              <button
                onClick={this.handleReload}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-sky-600 hover:bg-sky-500 text-white text-xs font-medium transition-colors"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Reload Page</span>
              </button>
              <button
                onClick={this.handleReset}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium transition-colors"
              >
                <LogOut className="w-3.5 h-3.5" />
                <span>Clear Cache & Relog</span>
              </button>
            </div>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
