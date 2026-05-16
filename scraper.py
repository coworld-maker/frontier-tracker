import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright, Page, Response, Browser

CONCURRENCY = 16         # parallel browser contexts
ROUTE_TIMEOUT_MS = 15_000  # 15s per route before giving up
GO_WILD_BRANDS = {"go wild", "gowild", "wild"}
FRONTIER_SEARCH = "https://www.flyfrontier.com/travel/book-a-flight/"

# All airports Frontier serves as of 2025
FRONTIER_AIRPORTS = [
    "ABQ", "ATL", "AUS", "BNA", "BOS", "BUF", "BWI", "CHS", "CLE", "CLT",
    "CMH", "CVG", "DAL", "DCA", "DEN", "DFW", "DTW", "EWR", "FLL", "GRR",
    "GSP", "HOU", "IAD", "IAH", "IND", "JAX", "LAS", "LAX", "LGA", "MCI",
    "MCO", "MDW", "MEM", "MHT", "MIA", "MKE", "MSP", "MSY", "OAK", "OKC",
    "OMA", "ORD", "ORF", "PHL", "PHX", "PIT", "PVD", "RDU", "RIC", "ROC",
    "RSW", "SAN", "SAT", "SDF", "SEA", "SFO", "SJC", "SJU", "SLC", "SMF",
    "STL", "SYR", "TPA", "TUL", "TUS", "TYS",
]

# Hardcoded Frontier route pairs (both directions) used when live discovery fails.
# Covers DEN hub-and-spoke + major point-to-point markets (~380 directional pairs).
_HUB_SPOKES = [
    # DEN is Frontier's main hub — connects to nearly every served city
    ("DEN", "ABQ"), ("DEN", "ATL"), ("DEN", "AUS"), ("DEN", "BNA"), ("DEN", "BOS"),
    ("DEN", "BUF"), ("DEN", "BWI"), ("DEN", "CHS"), ("DEN", "CLE"), ("DEN", "CLT"),
    ("DEN", "CMH"), ("DEN", "CVG"), ("DEN", "DAL"), ("DEN", "DCA"), ("DEN", "DFW"),
    ("DEN", "DTW"), ("DEN", "EWR"), ("DEN", "FLL"), ("DEN", "GRR"), ("DEN", "GSP"),
    ("DEN", "HOU"), ("DEN", "IAD"), ("DEN", "IAH"), ("DEN", "IND"), ("DEN", "JAX"),
    ("DEN", "LAS"), ("DEN", "LAX"), ("DEN", "LGA"), ("DEN", "MCI"), ("DEN", "MCO"),
    ("DEN", "MDW"), ("DEN", "MEM"), ("DEN", "MHT"), ("DEN", "MIA"), ("DEN", "MKE"),
    ("DEN", "MSP"), ("DEN", "MSY"), ("DEN", "OAK"), ("DEN", "OKC"), ("DEN", "OMA"),
    ("DEN", "ORD"), ("DEN", "ORF"), ("DEN", "PHL"), ("DEN", "PHX"), ("DEN", "PIT"),
    ("DEN", "PVD"), ("DEN", "RDU"), ("DEN", "RIC"), ("DEN", "ROC"), ("DEN", "RSW"),
    ("DEN", "SAN"), ("DEN", "SAT"), ("DEN", "SDF"), ("DEN", "SEA"), ("DEN", "SFO"),
    ("DEN", "SJC"), ("DEN", "SJU"), ("DEN", "SLC"), ("DEN", "SMF"), ("DEN", "STL"),
    ("DEN", "SYR"), ("DEN", "TPA"), ("DEN", "TUL"), ("DEN", "TUS"), ("DEN", "TYS"),
    # ATL point-to-point
    ("ATL", "FLL"), ("ATL", "LAS"), ("ATL", "LAX"), ("ATL", "MCO"), ("ATL", "MDW"),
    ("ATL", "MIA"), ("ATL", "PHX"), ("ATL", "SJU"), ("ATL", "TPA"), ("ATL", "BOS"),
    ("ATL", "EWR"), ("ATL", "PHL"),
    # Chicago MDW point-to-point
    ("MDW", "FLL"), ("MDW", "LAS"), ("MDW", "MCO"), ("MDW", "MIA"), ("MDW", "PHX"),
    ("MDW", "TPA"), ("MDW", "SJU"), ("MDW", "MSY"), ("MDW", "PHL"),
    # LAS point-to-point
    ("LAS", "ATL"), ("LAS", "CLT"), ("LAS", "FLL"), ("LAS", "IAH"), ("LAS", "LAX"),
    ("LAS", "MCO"), ("LAS", "MIA"), ("LAS", "MSP"), ("LAS", "OAK"), ("LAS", "ORD"),
    ("LAS", "PHX"), ("LAS", "SAN"), ("LAS", "SFO"), ("LAS", "SJC"), ("LAS", "TPA"),
    # MCO point-to-point
    ("MCO", "BOS"), ("MCO", "BWI"), ("MCO", "CLT"), ("MCO", "EWR"), ("MCO", "FLL"),
    ("MCO", "IAD"), ("MCO", "LGA"), ("MCO", "MIA"), ("MCO", "PHL"), ("MCO", "PHX"),
    ("MCO", "MSP"), ("MCO", "SJU"),
    # PHX point-to-point
    ("PHX", "LAX"), ("PHX", "OAK"), ("PHX", "SAN"), ("PHX", "SFO"), ("PHX", "SJC"),
    ("PHX", "TPA"), ("PHX", "MSP"), ("PHX", "ORD"), ("PHX", "FLL"), ("PHX", "MIA"),
    # FLL point-to-point
    ("FLL", "BOS"), ("FLL", "BWI"), ("FLL", "CLE"), ("FLL", "CLT"), ("FLL", "EWR"),
    ("FLL", "IAD"), ("FLL", "LGA"), ("FLL", "MDW"), ("FLL", "MIA"), ("FLL", "PHL"),
    # MIA point-to-point
    ("MIA", "BOS"), ("MIA", "EWR"), ("MIA", "LGA"), ("MIA", "MDW"), ("MIA", "ORD"),
    ("MIA", "PHL"),
    # SJU (San Juan) point-to-point
    ("SJU", "BWI"), ("SJU", "CLT"), ("SJU", "EWR"), ("SJU", "FLL"), ("SJU", "IAD"),
    ("SJU", "MIA"), ("SJU", "ORD"), ("SJU", "PHL"),
    # West Coast / Southwest
    ("LAX", "SFO"), ("LAX", "SJC"), ("LAX", "SEA"), ("LAX", "OAK"),
    ("SFO", "SEA"), ("SAN", "SEA"), ("OAK", "SEA"),
    # Texas point-to-point
    ("DAL", "LAS"), ("DAL", "MCO"), ("DAL", "MIA"), ("DAL", "PHX"),
    ("AUS", "LAS"), ("AUS", "MCO"), ("AUS", "PHX"),
    ("SAT", "LAS"), ("SAT", "MCO"),
    ("HOU", "LAS"), ("HOU", "MCO"), ("HOU", "MIA"),
    # Southeast point-to-point
    ("TPA", "BOS"), ("TPA", "BWI"), ("TPA", "CLT"), ("TPA", "EWR"),
    ("TPA", "LGA"), ("TPA", "MDW"), ("TPA", "PHL"),
    ("MSY", "LAS"), ("MSY", "MCO"), ("MSY", "PHX"),
    # Midwest point-to-point
    ("ORD", "FLL"), ("ORD", "LAS"), ("ORD", "MCO"), ("ORD", "MIA"), ("ORD", "PHX"),
    ("MSP", "FLL"), ("MSP", "MCO"), ("MSP", "PHX"), ("MSP", "TPA"),
    ("MCI", "LAS"), ("MCI", "MCO"), ("MCI", "PHX"),
    # Mid-Atlantic / Northeast
    ("PHL", "FLL"), ("PHL", "LAS"), ("PHL", "MCO"), ("PHL", "MIA"), ("PHL", "PHX"),
    ("PHL", "TPA"), ("PHL", "SJU"),
    ("EWR", "FLL"), ("EWR", "MCO"), ("EWR", "PHX"), ("EWR", "TPA"),
    ("BOS", "FLL"), ("BOS", "MCO"), ("BOS", "MIA"), ("BOS", "TPA"),
]

# Expand both directions
FRONTIER_KNOWN_ROUTES: set[tuple[str, str]] = set()
for _o, _d in _HUB_SPOKES:
    FRONTIER_KNOWN_ROUTES.add((_o, _d))
    FRONTIER_KNOWN_ROUTES.add((_d, _o))

STEALTH_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


@dataclass
class GoWildFlight:
    origin: str
    destination: str
    date: str
    departure_time: str
    flight_number: str
    price: float
    currency: str
    fare_class: str

    def key(self) -> str:
        return f"{self.origin}-{self.destination}-{self.date}-{self.flight_number}"

    def label(self) -> str:
        price_str = f"${self.price:.0f}" if self.price > 0 else "$0 (taxes only)"
        return (
            f"{self.origin} → {self.destination} | "
            f"{self.date} {self.departure_time} | "
            f"Flight {self.flight_number} | {price_str}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _date_range(days: int, timezone: str) -> list[str]:
    tz = ZoneInfo(timezone)
    today = datetime.now(tz=tz).date()
    return [(today + timedelta(days=i)).isoformat() for i in range(1, days + 1)]


def _is_go_wild(brand: str) -> bool:
    b = brand.lower()
    return any(w in b for w in GO_WILD_BRANDS)


def _extract_go_wild_flights(data: Any, route: dict, date: str) -> list[GoWildFlight]:
    flights: list[GoWildFlight] = []
    max_price = route.get("maxPrice")

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        has_price = any(k in node for k in ("price", "totalPrice", "amount", "fare"))
        has_context = any(k in node for k in (
            "flightNumber", "flight_number", "segments", "legs",
            "fareBrand", "fare_brand", "brandName", "fareFamily", "productName",
        ))
        if has_price and has_context:
            brand = str(
                node.get("fareBrand") or node.get("fare_brand") or
                node.get("brandName") or node.get("fareFamily") or
                node.get("productName") or ""
            )
            if _is_go_wild(brand):
                price = float(
                    node.get("price") or node.get("totalPrice") or
                    node.get("amount") or node.get("fare") or 0
                )
                if max_price is None or price <= max_price:
                    flights.append(GoWildFlight(
                        origin=route["origin"],
                        destination=route["destination"],
                        date=date,
                        departure_time=str(
                            node.get("departureTime") or node.get("departure_time") or
                            node.get("departureDatetime") or node.get("departs") or ""
                        ),
                        flight_number=str(
                            node.get("flightNumber") or node.get("flight_number") or
                            node.get("flightNo") or node.get("number") or "UNK"
                        ),
                        price=price,
                        currency=str(node.get("currency") or node.get("currencyCode") or "USD"),
                        fare_class=brand or "Go Wild",
                    ))
        for v in node.values():
            walk(v)

    walk(data)
    return flights


def _collect_airport_codes(node: Any, out: list[str]) -> None:
    if isinstance(node, list):
        for item in node:
            _collect_airport_codes(item, out)
    elif isinstance(node, dict):
        for key, val in node.items():
            if key.lower() in ("code", "iata", "airportcode", "stationcode", "id") and isinstance(val, str):
                c = val.strip().upper()
                if len(c) == 3 and c.isalpha():
                    out.append(c)
            else:
                _collect_airport_codes(val, out)
    elif isinstance(node, str):
        c = node.strip().upper()
        if len(c) == 3 and c.isalpha():
            out.append(c)


async def _new_context(browser: Browser):
    return await browser.new_context(
        user_agent=USER_AGENT,
        extra_http_headers=STEALTH_HEADERS,
        viewport={"width": 1280, "height": 800},
    )


# ---------------------------------------------------------------------------
# Route discovery (parallel)
# ---------------------------------------------------------------------------

async def _discover_origin(sem: asyncio.Semaphore, browser: Browser, origin: str) -> list[str]:
    async with sem:
        context = await _new_context(browser)
        page = await context.new_page()
        pending: list[Response] = []

        def on_response(r: Response) -> None:
            ct = r.headers.get("content-type", "")
            if r.status == 200 and "application/json" in ct:
                url = r.url
                if any(kw in url for kw in ("destination", "airport", "route", "station")):
                    if "flyfrontier" in url or "frontierairlines" in url:
                        pending.append(r)

        page.on("response", on_response)
        found: list[str] = []
        try:
            url = FRONTIER_SEARCH + "?" + urlencode({"origin": origin, "tripType": "ONE_WAY"})
            await page.goto(url, wait_until="networkidle", timeout=30_000)
            await page.wait_for_timeout(1_500)
            for r in pending:
                try:
                    data = await r.json()
                    _collect_airport_codes(data, found)
                except Exception:
                    pass
        except Exception:
            pass
        finally:
            await context.close()
        return [d for d in found if d != origin and d in FRONTIER_AIRPORTS]


async def _discover_routes_async(browser: Browser) -> list[tuple[str, str]]:
    print("Discovering Frontier routes (parallel)…")
    sem = asyncio.Semaphore(CONCURRENCY)
    tasks = [_discover_origin(sem, browser, o) for o in FRONTIER_AIRPORTS]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    pairs: set[tuple[str, str]] = set()
    for origin, result in zip(FRONTIER_AIRPORTS, results):
        if isinstance(result, list):
            for dest in result:
                pairs.add((origin, dest))

    if not pairs:
        print("  API discovery yielded nothing — using hardcoded Frontier route list")
        pairs = set(FRONTIER_KNOWN_ROUTES)

    print(f"  {len(pairs)} route pairs to check")
    return sorted(pairs)


# ---------------------------------------------------------------------------
# Route checking (parallel)
# ---------------------------------------------------------------------------

async def _check_route(
    sem: asyncio.Semaphore,
    browser: Browser,
    route: dict,
    date: str,
) -> list[GoWildFlight]:
    async with sem:
        context = await _new_context(browser)
        page = await context.new_page()
        pending: list[Response] = []

        def on_response(r: Response) -> None:
            ct = r.headers.get("content-type", "")
            if r.status != 200 or "application/json" not in ct:
                return
            url = r.url
            if (
                ("flyfrontier" in url or "frontierairlines" in url)
                and "/api/" in url
                and any(kw in url for kw in ("flight", "avail", "search", "offer"))
            ):
                pending.append(r)

        page.on("response", on_response)
        captured: list[GoWildFlight] = []
        seen: set[str] = set()

        try:
            params = urlencode({
                "origin": route["origin"], "destination": route["destination"],
                "departDate": date, "returnDate": "",
                "adults": "1", "children": "0", "infants": "0",
                "tripType": "ONE_WAY",
            })
            await page.goto(
                f"{FRONTIER_SEARCH}?{params}",
                wait_until="networkidle",
                timeout=ROUTE_TIMEOUT_MS,
            )
            await page.wait_for_timeout(2_000)

            for r in pending:
                try:
                    data = await r.json()
                    for f in _extract_go_wild_flights(data, route, date):
                        if f.key() not in seen:
                            seen.add(f.key())
                            captured.append(f)
                except Exception:
                    pass

            # DOM fallback
            try:
                cards = await page.locator('[data-testid*="flight"], .flight-card, .fare-cell').all()
                for card in cards:
                    text = await card.text_content() or ""
                    if not any(b in text.lower() for b in GO_WILD_BRANDS):
                        continue
                    pm = re.search(r"\$(\d+(?:\.\d+)?)", text)
                    price = float(pm.group(1)) if pm else 0.0
                    mp = route.get("maxPrice")
                    if mp is not None and price > mp:
                        continue
                    fn_m = re.search(r"F9\s*(\d+)", text, re.IGNORECASE)
                    fn = f"F9{fn_m.group(1)}" if fn_m else "UNK"
                    tm = re.search(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text, re.IGNORECASE)
                    dep = tm.group(0) if tm else ""
                    if fn != "UNK" or dep:
                        f = GoWildFlight(route["origin"], route["destination"], date, dep, fn, price, "USD", "Go Wild")
                        if f.key() not in seen:
                            seen.add(f.key())
                            captured.append(f)
            except Exception:
                pass

        except Exception as e:
            o, d = route["origin"], route["destination"]
            print(f"    Timeout/error {o}→{d} {date}: {type(e).__name__}")
        finally:
            await context.close()

        return captured


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def _run(config: dict, timezone: str) -> list[GoWildFlight]:
    all_routes_mode = config.get("all_routes", False)
    days_ahead = config.get("days_ahead", 3 if all_routes_mode else 14)
    dates = _date_range(days_ahead, timezone)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            if all_routes_mode:
                pairs = await _discover_routes_async(browser)
                routes_to_check = [
                    {"origin": o, "destination": d, "maxPrice": config.get("maxPrice")}
                    for o, d in pairs
                ]
            else:
                routes_to_check = config.get("routes", [])

            total = len(routes_to_check) * len(dates)
            print(f"Checking {len(routes_to_check)} route(s) × {len(dates)} date(s) = {total} searches ({CONCURRENCY} parallel)")

            sem = asyncio.Semaphore(CONCURRENCY)
            tasks = [
                _check_route(sem, browser, route, date)
                for route in routes_to_check
                for date in (
                    dates if all_routes_mode or route.get("dates") == "flexible"
                    else route.get("dates", dates)
                )
            ]

            all_results: list[GoWildFlight] = []
            done = 0
            for coro in asyncio.as_completed(tasks):
                flights = await coro
                all_results.extend(flights)
                done += 1
                if done % 50 == 0:
                    print(f"  Progress: {done}/{len(tasks)} searches complete, {len(all_results)} Go Wild flight(s) found so far")

        finally:
            await browser.close()

    return all_results


def scrape_go_wild_flights(config: dict, timezone: str = "America/Chicago") -> list[GoWildFlight]:
    return asyncio.run(_run(config, timezone))
