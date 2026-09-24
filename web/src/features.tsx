import { registerTab } from "./extensions";
import { SyncPanel } from "./components/SyncPanel";
import { AiTierBadge, AssistantPanel } from "./components/AssistantPanel";
import { PassesPanel } from "./components/passes/PassesPanel";

// Feature tabs appear only on nodes that report the module.
registerTab({ id: "passes", label: "Passes", module: "passes", render: (ctx) => <PassesPanel node={ctx.node} version={ctx.version} nowMs={ctx.nowMs} /> });
registerTab({ id: "sync", label: "Sync", module: "sync", render: (ctx) => <SyncPanel version={ctx.version} /> });
registerTab({
  id: "assistant",
  label: "Assistant",
  module: "ai",
  render: (ctx) => <AssistantPanel version={ctx.version} />,
  status: (ctx) => <AiTierBadge version={ctx.version} />,
});
