import { Component, type ErrorInfo, type ReactNode } from "react";
import { log } from "../lib/log";

interface Props {
  label: string;
  /** What the panel shows, such as the selected event. When it changes the
   *  panel gets another try, so one malformed record cannot blank the pane
   *  for every other. */
  resetKey?: unknown;
  children: ReactNode;
}

/** A failing panel degrades to a notice; it never takes the console down. */
export class ErrorBoundary extends Component<Props, { error: string | null }> {
  state = { error: null as string | null };

  static getDerivedStateFromError(error: unknown) {
    return { error: String(error) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    log.error({ panel: this.props.label, error: String(error), component_stack: info.componentStack }, "Panel render failed");
  }

  componentDidUpdate(previous: Props) {
    if (this.state.error !== null && previous.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (this.state.error) {
      return (
        <div className="panel-error" role="alert">
          {this.props.label} unavailable: {this.state.error}. The rest of the console is unaffected.
        </div>
      );
    }
    return this.props.children;
  }
}
