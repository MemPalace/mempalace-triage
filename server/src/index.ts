import { cors } from "@elysiajs/cors";
import { migrate } from "drizzle-orm/bun-sqlite/migrator";
import { resolve } from "node:path";
import { Elysia } from "elysia";
import { syncMaintainersFromConfig } from "@/auth/allowlist";
import { db } from "@/db/client";
import { publicApi } from "@/api/public";
import { wsApi } from "@/api/ws";
import { startPollerLoop } from "@/sync/poller";

// ─── Startup: migrations + maintainers seed ──────────────────────────────────

const migrationsFolder = resolve(import.meta.dir, "db/migrations");
migrate(db, { migrationsFolder });
console.log(`[boot] migrations applied from ${migrationsFolder}`);

const seedResult = await syncMaintainersFromConfig();
console.log(
  `[boot] maintainers: +${seedResult.added} added, ${seedResult.updated} updated, ${seedResult.deactivated} deactivated`,
);

// ─── Poller ──────────────────────────────────────────────────────────────────

const pollerEnabled = process.env.POLLER_ENABLED !== "false";
if (pollerEnabled) {
  startPollerLoop();
  console.log("[boot] poller started");
} else {
  console.log("[boot] poller disabled (POLLER_ENABLED=false)");
}

// ─── Elysia app ──────────────────────────────────────────────────────────────

const PORT = Number(process.env.PORT ?? 7800);
const DASHBOARD_DIST = process.env.DASHBOARD_DIST;

const app = new Elysia()
  .use(cors({ origin: true, credentials: true }))
  .get("/healthz", () => ({ ok: true, ts: Date.now() }))
  .use(publicApi)
  .use(wsApi);

if (DASHBOARD_DIST) {
  // Prod single-origin deploy: bun serves the built Angular dashboard from
  // the same port as the API + WebSocket. For each GET we try the file on
  // disk first; if missing, fall back to index.html so Angular's router
  // handles the client-side route. We avoid @elysiajs/static here because it
  // requires process.getBuiltinModule, which current Bun doesn't expose.
  const INDEX = `${DASHBOARD_DIST}/index.html`;
  app.get("/*", async ({ request }) => {
    const pathname = new URL(request.url).pathname;
    if (pathname !== "/") {
      const file = Bun.file(`${DASHBOARD_DIST}${pathname}`);
      if (await file.exists()) return file;
    }
    return Bun.file(INDEX);
  });
  console.log(`[boot] serving dashboard from ${DASHBOARD_DIST}`);
} else {
  app.get("/", () => ({
    service: "mempalace-triage-server",
    version: "0.1.0",
    docs: "/api",
  }));
}

app.listen(PORT);

console.log(`[boot] listening on http://localhost:${PORT}`);

export type App = typeof app;
