import { Component, type ReactNode } from "react";

/** A failing panel degrades to a notice; it never takes the console down. */
export class ErrorBoundary extends Component<{ label: string; children: ReactNode }, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: String(error) };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel-error">
          {this.props.label} unavailable: {this.state.error}. The rest of the console is unaffected.
        </div>
      );
    }
    return this.props.children;
  }
}
