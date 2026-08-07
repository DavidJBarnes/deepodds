import { Outlet } from "react-router-dom";
import { VerbatimTabs } from "@/components/verbatim/VerbatimTabs";

/** Shell for the Verbatim sub-views: renders the tab strip once, above whichever
 * view is active, instead of each page having to remember to include it. */
export default function VerbatimLayout() {
  return (
    // text-slate-200 mirrors the `body { color: #e2e8f0 }` that Verbatim's own
    // index.css provided and that the ported components were written against.
    // Scoped to this subtree rather than applied globally, so it cannot change
    // how Longshot or Edge Explorer render.
    <div className="space-y-4 text-slate-200">
      <VerbatimTabs />
      <Outlet />
    </div>
  );
}
