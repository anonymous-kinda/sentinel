import { registerTab } from "./extensions";
import { SyncPanel } from "./components/SyncPanel";

// Feature tabs appear only on nodes that report the module.
registerTab({ id: "sync", label: "Sync", module: "sync", render: (ctx) => <SyncPanel version={ctx.version} /> });
