import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, Page, Response, Browser

FRONTIER_SEARCH = "https://www.flyfrontier.com/travel/book-a-flight/"
GO_WILD_BRANDS = {"go wild", "gowild", "wild"}

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

STEALTH_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
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
        price_str = "FREE (taxes only)" if self.price == 0 else f"${self.price:.0f} {self.currency}"
        return f"{self.origin} → {self.destination}  |  {self.date} {self.departure_time}  |  Flight {self.flight_number}  |  {price_str}"


def _date_range(days: int, timezone: str) -> list[str]:
    tz = ZoneInfo(timezone)
    today = datetime.now(tz=tz).date()
    return [(today + timedelta(days=i)).isoformat() for i in range(1, days + 1)]


def _flight_is_go_wild(brand: str) -> bool:
    brand_lower = brand.lower()
    return any(b in brand_lower for b in GO_WILD_BRANDS)


def _new_context(browser: Browser):
    return browser.new_context(
        user_agent=USER_AGENT,
        extra_http_headers=STEALTH_HEADERS,
        viewport={"width": 1280, "height": 800},
    )


# ---------------------------------------------------------------------------
# Route discovery
# ---------------------------------------------------------------------------

def discover_routes(browser: Browser) -> list[tuple[str, str]]:
    """
    Visit Frontier's search page for each origin airport and intercept the
    API response that lists available destinations. Returns all valid (origin,
    destination) pairs Frontier actually flies.
    """
    print("Discovering all Frontier routes…")
    route_pairs: set[tuple[str, str]] = set()

    for origin in FRONTIER_AIRPORTS:
        context = _new_context(browser)
        page = context.new_page()
        found: list[str] = []

        def on_response(response: Response, _origin: str = origin) -> None:
            if response.status != 200:
                return
            ct = response.headers.get("content-type", "")
            if "application/json" not in ct:
                return
            url = response.url
            # Frontier's destinations/airports API
            if not any(kw in url for kw in ("destination", "airport", "route", "station")):
                return
            if not ("flyfrontier" in url or "frontierairlines" in url):
                return
            try:
                data = response.json()
                _collect_airport_codes(data, found)
            except Exception:
                pass

        page.on("response", on_response)

        try:
            # Navigating with an origin pre-selected triggers the destinations call
            url = (
                f"{FRONTIER_SEARCH}?"
                + urlencode({"origin": origin, "tripType": "ONE_WAY"})
            )
            page.goto(url, wait_until="networkidle", timeout=30_000)
            page.wait_for_timeout(2_000)

            # Also try clicking the destination field to trigger lazy-loaded data
            try:
                dest_field = page.locator(
                    'input[placeholder*="destination" i], input[placeholder*="to" i], '
                    '[data-testid*="destination"] input'
                ).first
                if dest_field.is_visible(timeout=2_000):
                    dest_field.click()
                    page.wait_for_timeout(1_500)
            except Exception:
                pass

        except Exception as e:
            print(f"  Warning: could not load destinations for {origin}: {e}")
        finally:
            context.close()

        for dest in found:
            if dest != origin and dest in FRONTIER_AIRPORTS:
                route_pairs.add((origin, dest))

        print(f"  {origin}: {len(found)} destination(s) found")
        time.sleep(1.5)

    # If the API discovery yielded nothing (site structure changed), fall back
    # to generating all combinations from the known airport list
    if not route_pairs:
        print("  API discovery found no routes — falling back to full airport matrix")
        for i, orig in enumerate(FRONTIER_AIRPORTS):
            for dest in FRONTIER_AIRPORTS[i + 1 :]:
                route_pairs.add((orig, dest))
                route_pairs.add((dest, orig))

    pairs = sorted(route_pairs)
    print(f"Total route pairs to check: {len(pairs)}")
    return pairs


def _collect_airport_codes(node: Any, out: list[str]) -> None:
    """Recursively walk JSON and collect IATA airport codes."""
    if isinstance(node, list):
        for item in node:
            _collect_airport_codes(item, out)
    elif isinstance(node, dict):
        for key, val in node.items():
            # Common field names for airport/station codes
            if key.lower() in ("code", "iata", "airportcode", "stationcode", "id") and isinstance(val, str):
                candidate = val.strip().upper()
                if len(candidate) == 3 and candidate.isalpha():
                    out.append(candidate)
            else:
                _collect_airport_codes(val, out)
    elif isinstance(node, str):
        # Bare 3-letter strings in arrays
        candidate = node.strip().upper()
        if len(candidate) == 3 and candidate.isalpha():
            out.append(candidate)


# ---------------------------------------------------------------------------
# Flight availability checking
# ---------------------------------------------------------------------------

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
        has_flight = any(k in node for k in ("flightNumber", "flight_number", "segments", "legs"))
        has_brand = any(k in node for k in ("fareBrand", "fare_brand", "brandName", "fareFamily", "productName"))

        if has_price and (has_flight or has_brand):
            brand_raw = str(
                node.get("fareBrand") or node.get("fare_brand") or node.get("brandName")
                or node.get("fareFamily") or node.get("productName") or ""
            )
            if _flight_is_go_wild(brand_raw):
                price = float(
                    node.get("price") or node.get("totalPrice")
                    or node.get("amount") or node.get("fare") or 0
                )
                if max_price is None or price <= max_price:
                    fn = str(
                        node.get("flightNumber") or node.get("flight_number")
                        or node.get("flightNo") or node.get("number") or "UNK"
                    )
                    dep = str(
                        node.get("departureTime") or node.get("departure_time")
                        or node.get("departureDatetime") or node.get("departureDateTime")
                        or node.get("departs") or ""
                    )
                    currency = str(node.get("currency") or node.get("currencyCode") or "USD")
                    fare_class = brand_raw or "Go Wild"
                    flights.append(
                        GoWildFlight(
                            origin=route["origin"],
                            destination=route["destination"],
                            date=date,
                            departure_time=dep,
                            flight_number=fn,
                            price=price,
                            currency=currency,
                            fare_class=fare_class,
                        )
                    )
        for v in node.values():
            walk(v)

    walk(data)
    return flights


def _dom_fallback(page: Page, route: dict, date: str) -> list[GoWildFlight]:
    flights: list[GoWildFlight] = []
    max_price = route.get("maxPrice")
    try:
        cards = page.locator('[data-testid*="flight"], .flight-card, .fare-cell').all()
        for card in cards:
            text = card.text_content() or ""
            lower = text.lower()
            if not any(b in lower for b in GO_WILD_BRANDS):
                continue
            price_match = re.search(r"\$(\d+(?:\.\d+)?)", text)
            price = float(price_match.group(1)) if price_match else 0.0
            if max_price is not None and price > max_price:
                continue
            fn_match = re.search(r"F9\s*(\d+)", text, re.IGNORECASE)
            flight_number = f"F9{fn_match.group(1)}" if fn_match else "UNK"
            time_match = re.search(r"\d{1,2}:\d{2}\s*(?:AM|PM)", text, re.IGNORECASE)
            departure_time = time_match.group(0) if time_match else ""
            if flight_number != "UNK" or departure_time:
                flights.append(
                    GoWildFlight(
                        origin=route["origin"],
                        destination=route["destination"],
                        date=date,
                        departure_time=departure_time,
                        flight_number=flight_number,
                        price=price,
                        currency="USD",
                        fare_class="Go Wild",
                    )
                )
    except Exception:
        pass
    return flights


def _check_route(browser: Browser, route: dict, date: str) -> list[GoWildFlight]:
    context = _new_context(browser)
    page = context.new_page()
    captured: list[GoWildFlight] = []
    seen_keys: set[str] = set()

    def on_response(response: Response) -> None:
        if response.status != 200:
            return
        ct = response.headers.get("content-type", "")
        if "application/json" not in ct:
            return
        url = response.url
        if not (
            ("flyfrontier" in url or "frontierairlines" in url)
            and "/api/" in url
            and any(kw in url for kw in ("flight", "avail", "search", "offer"))
        ):
            return
        try:
            data = response.json()
            for f in _extract_go_wild_flights(data, route, date):
                if f.key() not in seen_keys:
                    seen_keys.add(f.key())
                    captured.append(f)
        except Exception:
            pass

    page.on("response", on_response)

    try:
        params = urlencode({
            "origin": route["origin"],
            "destination": route["destination"],
            "departDate": date,
            "returnDate": "",
            "adults": "1",
            "children": "0",
            "infants": "0",
            "tripType": "ONE_WAY",
        })
        page.goto(f"{FRONTIER_SEARCH}?{params}", wait_until="networkidle", timeout=45_000)
        page.wait_for_timeout(3_000)
        for f in _dom_fallback(page, route, date):
            if f.key() not in seen_keys:
                seen_keys.add(f.key())
                captured.append(f)
    except Exception as e:
        print(f"    Warning: {route['origin']}→{route['destination']} {date}: {e}")
    finally:
        context.close()

    return captured


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def scrape_go_wild_flights(
    config: dict,
    timezone: str = "America/Chicago",
) -> list[GoWildFlight]:
    """
    Main entry point. Reads `all_routes` and `routes` from config.
    If all_routes is true, discovers every Frontier route automatically.
    """
    all_routes_mode = config.get("all_routes", False)
    days_ahead = config.get("days_ahead", 7 if all_routes_mode else 14)
    manual_routes = config.get("routes", [])

    results: list[GoWildFlight] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            if all_routes_mode:
                pairs = discover_routes(browser)
                # Wrap into route dicts so _check_route can use them
                routes_to_check = [
                    {"origin": o, "destination": d, "maxPrice": config.get("maxPrice")}
                    for o, d in pairs
                ]
            else:
                routes_to_check = manual_routes

            dates = _date_range(days_ahead, timezone)

            total = len(routes_to_check) * len(dates)
            print(f"Checking {len(routes_to_check)} route(s) × {len(dates)} date(s) = {total} searches")

            for i, route in enumerate(routes_to_check):
                route_dates = (
                    dates
                    if all_routes_mode or route.get("dates") == "flexible"
                    else route.get("dates", dates)
                )
                for date in route_dates:
                    print(f"  [{i+1}/{len(routes_to_check)}] {route['origin']} → {route['destination']} {date}…")
                    results.extend(_check_route(browser, route, date))
                    time.sleep(2.0)
        finally:
            browser.close()

    return results
