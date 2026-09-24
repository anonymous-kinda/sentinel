import type { ReactNode } from "react";
import type { NodeInfo } from "./api/types";

// Tabs contributed by mission modules and platform features (sync, passes,
// assistant). A tab appears only when the node reports the module, so the
// public read-only node and a minimal edge build show exactly what they run.

export interface ExtensionContext {
  node: NodeInfo | null;
  version: number;
  nowMs: number;
  bump: () => void;
}

export interface ExtensionTab {
  id: string;
  label: string;
  module: string;
  render: (ctx: ExtensionContext) => ReactNode;
  status?: (ctx: ExtensionContext) => ReactNode;
}

const REGISTRY: ExtensionTab[] = [];

export function registerTab(tab: ExtensionTab): void {
  REGISTRY.push(tab);
}

export function extensionTabs(node: NodeInfo | null): ExtensionTab[] {
  if (!node) return [];
  return REGISTRY.filter((t) => node.modules.includes(t.module));
}
