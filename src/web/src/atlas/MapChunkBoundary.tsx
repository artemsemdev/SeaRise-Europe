import { Component, type ReactNode } from "react";

interface MapChunkBoundaryProps {
  readonly children: ReactNode;
  readonly onFailure: () => void;
}

/** Keep the rest of the atlas usable when its map module fails. */
export class MapChunkBoundary extends Component<MapChunkBoundaryProps, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch() {
    this.props.onFailure();
  }

  render() {
    return this.state.failed ? null : this.props.children;
  }
}
