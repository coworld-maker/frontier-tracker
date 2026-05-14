import json
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright, Page, Response, Browser

FRONTIER_SEARCH = "https://www.flyfrontier.com/travel/book-a-flight/"
GO_WILD_BRANDS = {"go wild", "gowild", "wild"}

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


def _extract_go_wild_flights(
    data: Any, route: dict, date: str
) -> list[GoWildFlight]:
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
                node.get("fareBrand")
                or node.get("fare_brand")
                or node.get("brandName")
                or node.get("fareFamily")
                or node.get("productName")
                or ""
            )
            if _flight_is_go_wild(brand_raw):
                price = float(
                    node.get("price")
                    or node.get("totalPrice")
                    or node.get("amount")
                    or node.get("fare")
                    or 0
                )
                if max_price is None or price <= max_price:
                    fn = str(
                        node.get("flightNumber")
                        or node.get("flight_number")
                        or node.get("flightNo")
                        or node.get("number")
                        or "UNK"
                    )
                    dep = str(
                        node.get("departureTime")
                        or node.get("departure_time")
                        or node.get("departureDatetime")
                        or node.get("departureDateTime")
                        or node.get("departs")
                        or ""
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
                # Still recurse into children regardless
        for v in node.values():
            walk(v)

    walk(data)
    return flights


def _dom_fallback(page: Page, route: dict, date: str) -> list[GoWildFlight]:
    """Parse Go Wild mentions directly from rendered DOM as a fallback."""
    flights: list[GoWildFlight] = []
    max_price = route.get("maxPrice")
    try:
        cards = page.locator('[data-testid*="flight"], .flight-card, .fare-cell').all()
        for card in cards:
            text = card.text_content() or ""
            lower = text.lower()
            if not any(b in lower for b in GO_WILD_BRANDS):
                continue
            import re
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


def _build_search_url(origin: str, destination: str, date: str) -> str:
    from urllib.parse import urlencode
    params = urlencode({
        "origin": origin,
        "destination": destination,
        "departDate": date,
        "returnDate": "",
        "adults": "1",
        "children": "0",
        "infants": "0",
        "tripType": "ONE_WAY",
    })
    return f"{FRONTIER_SEARCH}?{params}"


def _check_route(browser: Browser, route: dict, date: str) -> list[GoWildFlight]:
    context = browser.new_context(
        user_agent=USER_AGENT,
        extra_http_headers=STEALTH_HEADERS,
        viewport={"width": 1280, "height": 800},
    )
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
        url = _build_search_url(route["origin"], route["destination"], date)
        page.goto(url, wait_until="networkidle", timeout=45_000)
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


def scrape_go_wild_flights(routes: list[dict], timezone: str = "America/Chicago") -> list[GoWildFlight]:
    results: list[GoWildFlight] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for route in routes:
                dates = (
                    _date_range(14, timezone)
                    if route.get("dates") == "flexible"
                    else route["dates"]
                )
                for date in dates:
                    print(f"  Checking {route['origin']} → {route['destination']} on {date}…")
                    results.extend(_check_route(browser, route, date))
                    time.sleep(2.5)
        finally:
            browser.close()
    return results
