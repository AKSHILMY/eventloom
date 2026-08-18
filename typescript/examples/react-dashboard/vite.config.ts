import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// No dev-server proxy: the app talks to the Python backend
// (python/eventloom/examples/dashboard_app.py, :8000) directly, cross-origin,
// via its CORSMiddleware. A same-origin proxy setup is tempting to avoid
// CORS config, but dev proxies forward whatever cookies the browser has for
// `localhost` regardless of which app set them — including large ones from
// unrelated local apps, which can break naive proxies (Vite's included)
// outright with an opaque 500. Direct cross-origin + CORS sidesteps that
// class of problem entirely, and `StreamConnection` doesn't send credentials
// by default anyway, so no cookies cross the boundary either way.
export default defineConfig({
  plugins: [react()],
});
