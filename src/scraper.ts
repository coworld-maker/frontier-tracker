import { chromium } from "playwright";
import type { GoWildFlight, Route } from "./types.js";

const FRONTIER_SEARCH = "https://www.flyfrontier.com/travel/book-a-flight/";

// Go Wild fare classes Frontier uses in their API responses
const GO_WILD_FARE_BRANDS = ["go wild", "gowild", "wild"];

function dateRange(days: number, timezone: string): string[] {
  const dates: string[] = [];
  const now = new Date(
    new Date().toLocaleString("en-US", { timeZone: timezone })
  );
  for (let i = 1; i <= days; i++) {
    const d = new Date(now);
    d.setDate(d.getDate() + i);
    dates.push(d.toISOString().split("T")[0]);
  }
  return dates;
}

function flightKey(f: GoWildFlight): string {
  return `${f.origin}-${f.destination}-${f.date}-${f.flightNumber}`;
}

export async function scrapeGoWildFlights(
  routes: Route[],
  timezone = "America/Chicago"
): Promise<GoWildFlight[]> {
  const browser = await chromium.launch({ headless: true });
  const results: GoWildFlight[] = [];

  try {
    for (const route of routes) {
      const dates =
        route.dates === "flexible"
          ? dateRange(14, timezone)
          : route.dates;

      for (const date of dates) {
        console.log(
          `  Checking ${route.origin} → ${route.destination} on ${date}…`
        );
        const flights = await checkRoute(browser, route, date);
        results.push(...flights);
        // Polite delay between requests
        await new Promise((r) => setTimeout(r, 2500));
      }
    }
  } finally {
    await browser.close();
  }

  return results;
}

async function checkRoute(
  browser: Awaited<ReturnType<typeof chromium.launch>>,
  route: Route,
  date: string
): Promise<GoWildFlight[]> {
  const context = await browser.newContext({
    userAgent:
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    extraHTTPHeaders: {
      "Accept-Language": "en-US,en;q=0.9",
    },
  });
  const page = await context.newPage();
  const capturedFlights: GoWildFlight[] = [];

  // Intercept Frontier's internal availability API responses
  page.on("response", async (response) => {
    const url = response.url();
    const contentType = response.headers()["content-type"] ?? "";

    if (
      !contentType.includes("application/json") ||
      response.status() !== 200
    ) {
      return;
    }

    // Match Frontier's flight search API patterns
    const isFlightApi =
      url.includes("/api/") &&
      (url.includes("flight") ||
        url.includes("avail") ||
        url.includes("search") ||
        url.includes("offer")) &&
      (url.includes("flyfrontier") || url.includes("frontierairlines"));

    if (!isFlightApi) return;

    try {
      const json = await response.json();
      const flights = extractGoWildFlights(json, route, date);
      capturedFlights.push(...flights);
    } catch {
      // Non-JSON or parse error — skip
    }
  });

  try {
    // Build the deep-link search URL for this route/date
    const searchUrl = buildSearchUrl(route.origin, route.destination, date);
    await page.goto(searchUrl, { waitUntil: "networkidle", timeout: 45_000 });

    // Wait a moment for lazy-loaded results
    await page.waitForTimeout(3000);

    // Fallback: also try to parse any Go Wild mentions in the DOM
    const domFlights = await extractFromDom(page, route, date);
    capturedFlights.push(...domFlights);
  } catch (err) {
    console.warn(
      `    Warning: ${route.origin}→${route.destination} ${date}: ${(err as Error).message}`
    );
  } finally {
    await context.close();
  }

  // Deduplicate by flight key
  const seen = new Set<string>();
  return capturedFlights.filter((f) => {
    const k = flightKey(f);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function buildSearchUrl(origin: string, dest: string, date: string): string {
  // Frontier's search accepts these query params for one-way trips
  const params = new URLSearchParams({
    origin,
    destination: dest,
    departDate: date,
    returnDate: "",
    adults: "1",
    children: "0",
    infants: "0",
    tripType: "ONE_WAY",
  });
  return `${FRONTIER_SEARCH}?${params.toString()}`;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function extractGoWildFlights(json: any, route: Route, date: string): GoWildFlight[] {
  const flights: GoWildFlight[] = [];

  // Walk the JSON tree looking for flight objects with Go Wild fares
  function walk(node: unknown) {
    if (!node || typeof node !== "object") return;
    if (Array.isArray(node)) {
      node.forEach(walk);
      return;
    }
    const obj = node as Record<string, unknown>;

    // Detect a flight-like object
    const hasPrice = "price" in obj || "totalPrice" in obj || "amount" in obj;
    const hasFlight =
      "flightNumber" in obj ||
      "flight_number" in obj ||
      "segments" in obj ||
      "legs" in obj;
    const hasFareBrand =
      "fareBrand" in obj ||
      "fare_brand" in obj ||
      "brandName" in obj ||
      "fareFamily" in obj ||
      "productName" in obj;

    if (hasPrice && (hasFlight || hasFareBrand)) {
      const brandRaw = String(
        obj.fareBrand ?? obj.fare_brand ?? obj.brandName ??
        obj.fareFamily ?? obj.productName ?? ""
      ).toLowerCase();

      const isGoWild = GO_WILD_FARE_BRANDS.some((b) => brandRaw.includes(b));
      if (!isGoWild) {
        // Still recurse children
        Object.values(obj).forEach(walk);
        return;
      }

      const price = Number(
        obj.price ?? obj.totalPrice ?? obj.amount ?? obj.fare ?? 0
      );

      if (route.maxPrice === undefined || price <= route.maxPrice) {
        const rawFlight = extractFlightFields(obj, route, date);
        if (rawFlight) flights.push(rawFlight);
      }
    }

    Object.values(obj).forEach(walk);
  }

  walk(json);
  return flights;
}

function extractFlightFields(
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  obj: Record<string, any>,
  route: Route,
  date: string
): GoWildFlight | null {
  const flightNumber = String(
    obj.flightNumber ?? obj.flight_number ?? obj.flightNo ?? obj.number ?? "UNK"
  );
  const departureTime = String(
    obj.departureTime ?? obj.departure_time ?? obj.departureDatetime ??
    obj.departureDateTime ?? obj.departs ?? ""
  );
  const price = Number(
    obj.price ?? obj.totalPrice ?? obj.amount ?? obj.fare ?? 0
  );
  const currency = String(obj.currency ?? obj.currencyCode ?? "USD");
  const fareClass = String(
    obj.fareBrand ?? obj.fare_brand ?? obj.brandName ??
    obj.fareFamily ?? obj.productName ?? "Go Wild"
  );

  return {
    origin: route.origin,
    destination: route.destination,
    date,
    departureTime,
    flightNumber,
    price,
    currency,
    fareClass,
  };
}

// Fallback: scrape Go Wild mentions directly from rendered DOM
async function extractFromDom(
  page: import("playwright").Page,
  route: Route,
  date: string
): Promise<GoWildFlight[]> {
  const flights: GoWildFlight[] = [];

  try {
    // Look for elements that mention "Go Wild" with associated prices
    const cards = await page.locator('[data-testid*="flight"], .flight-card, .fare-cell').all();
    for (const card of cards) {
      const text = await card.textContent().catch(() => "");
      if (!text) continue;
      const lower = text.toLowerCase();
      if (!GO_WILD_FARE_BRANDS.some((b) => lower.includes(b))) continue;

      // Parse a price from text like "$0" or "$9"
      const priceMatch = text.match(/\$(\d+(?:\.\d+)?)/);
      const price = priceMatch ? Number(priceMatch[1]) : 0;

      if (route.maxPrice === undefined || price <= route.maxPrice) {
        // Extract a flight number from text like "F9 1234"
        const fnMatch = text.match(/F9\s*(\d+)/i);
        const flightNumber = fnMatch ? `F9${fnMatch[1]}` : "UNK";

        // Extract time like "8:45 AM"
        const timeMatch = text.match(/\d{1,2}:\d{2}\s*(?:AM|PM)/i);
        const departureTime = timeMatch ? timeMatch[0] : "";

        if (flightNumber !== "UNK" || departureTime) {
          flights.push({
            origin: route.origin,
            destination: route.destination,
            date,
            departureTime,
            flightNumber,
            price,
            currency: "USD",
            fareClass: "Go Wild",
          });
        }
      }
    }
  } catch {
    // DOM extraction is best-effort
  }

  return flights;
}
