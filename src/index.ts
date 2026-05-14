import fs from "fs";
import path from "path";
import { scrapeGoWildFlights } from "./scraper.js";
import { sendNotifications } from "./notify.js";
import type { Config, GoWildFlight, SeenState } from "./types.js";

const CONFIG_PATH = path.resolve(process.cwd(), "config.json");
const STATE_PATH = path.resolve(process.cwd(), "data", "seen-flights.json");

// How long to keep a flight in the "seen" state before re-alerting (48h)
const RESEEN_TTL_MS = 48 * 60 * 60 * 1000;

function loadConfig(): Config {
  if (!fs.existsSync(CONFIG_PATH)) {
    console.error("config.json not found. Copy config.example.json to config.json and fill it in.");
    process.exit(1);
  }
  return JSON.parse(fs.readFileSync(CONFIG_PATH, "utf-8")) as Config;
}

function loadState(): SeenState {
  if (!fs.existsSync(STATE_PATH)) return {};
  try {
    return JSON.parse(fs.readFileSync(STATE_PATH, "utf-8")) as SeenState;
  } catch {
    return {};
  }
}

function saveState(state: SeenState): void {
  fs.mkdirSync(path.dirname(STATE_PATH), { recursive: true });
  fs.writeFileSync(STATE_PATH, JSON.stringify(state, null, 2));
}

function flightKey(f: GoWildFlight): string {
  return `${f.origin}-${f.destination}-${f.date}-${f.flightNumber}`;
}

function filterNew(flights: GoWildFlight[], state: SeenState): GoWildFlight[] {
  const now = Date.now();
  return flights.filter((f) => {
    const key = flightKey(f);
    const last = state[key] ?? 0;
    return now - last > RESEEN_TTL_MS;
  });
}

function updateState(flights: GoWildFlight[], state: SeenState): SeenState {
  const updated = { ...state };
  const now = Date.now();
  // Prune expired entries
  for (const [key, ts] of Object.entries(updated)) {
    if (now - ts > RESEEN_TTL_MS * 3) delete updated[key];
  }
  // Mark new flights
  for (const f of flights) {
    updated[flightKey(f)] = now;
  }
  return updated;
}

async function main() {
  console.log("Frontier Go Wild Tracker starting…");
  const config = loadConfig();
  const state = loadState();

  console.log(`Checking ${config.routes.length} route(s)…`);
  let allFlights: GoWildFlight[] = [];

  try {
    allFlights = await scrapeGoWildFlights(config.routes, config.timezone);
  } catch (err) {
    console.error("Scraper error:", err);
    process.exit(1);
  }

  console.log(`Found ${allFlights.length} Go Wild flight(s) total.`);

  const newFlights = filterNew(allFlights, state);
  console.log(`${newFlights.length} new (not seen in last 48h).`);

  if (newFlights.length > 0) {
    console.log("Sending notifications…");
    await sendNotifications(newFlights, config.notifications);
    const newState = updateState(newFlights, state);
    saveState(newState);
    console.log("State saved.");
  } else {
    console.log("No new flights to report.");
    // Still prune stale entries
    saveState(updateState([], state));
  }

  console.log("Done.");
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
