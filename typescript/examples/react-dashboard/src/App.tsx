import { createRegistry, StreamView } from "@akshilmy/eventloom-react";
import { ChartWidget, ErrorFallback, LogViewer, UserCard } from "./components";
import type { ChartData, LogLine, UserProfile } from "./components";

const registry = createRegistry()
  .register<"chart.data", ChartData>("chart.data", { renderer: ChartWidget })
  .register<"user.partial", UserProfile>("user.partial", { renderer: UserCard, strategy: "merge" })
  .register<"log.line", LogLine[]>("log.line", { renderer: LogViewer, strategy: "append" });

// Cross-origin, direct to the backend — not proxied through Vite's dev
// server. See dashboard_app.py's CORSMiddleware comment for why: a
// same-origin dev proxy can forward unrelated cookies other local apps set
// broadly on `localhost`, and large ones can break naive proxies outright.
const BACKEND_URL = "http://localhost:8000";

export function App() {
  return (
    <main style={{ fontFamily: "sans-serif", padding: 24, display: "grid", gap: 24 }}>
      <h1>eventloom dashboard example</h1>
      <p>
        Backed by <code>python/eventloom/examples/dashboard_app.py</code> — run it with{" "}
        <code>python examples/dashboard_app.py</code> before starting this app.
      </p>
      <StreamView endpoint={`${BACKEND_URL}/stream/dashboard`} registry={registry} fallback={ErrorFallback} />
    </main>
  );
}
