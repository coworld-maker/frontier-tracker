from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from playwright.async_api import async_playwright, Page, Response, Browser, BrowserContext

CONCURRENCY = 8          # lower while logged-in to reduce bot-detection risk
ROUTE_TIMEOUT_MS = 20_000
GO_WILD_BRANDS = {"go wild", "gowild", "wild"}
FRONTIER_HOME = "https://booking.flyfrontier.com"

# All airports Frontier serves
FRONTIER_AIRPORTS = [
    "ABQ", "ATL", "AUS", "BNA", "BOS", "BUF", "BWI", "CHS", "CLE", "CLT",
    "CMH", "CVG", "DAL", "DCA", "DEN", "DFW", "DTW", "EWR", "FLL", "GRR",
    "GSP", "HOU", "IAD", "IAH", "IND", "JAX", "LAS", "LAX", "LGA", "MCI",
    "MCO", "MDW", "MEM", "MHT", "MIA", "MKE", "MSP", "MSY", "OAK", "OKC",
    "OMA", "ORD", "ORF", "PHL", "PHX", "PIT", "PVD", "RDU", "RIC", "ROC",
    "RSW", "SAN", "SAT", "SDF", "SEA", "SFO", "SJC", "SJU", "SLC", "SMF",
    "STL", "SYR", "TPA", "TUL", "TUS", "TYS",
]

_HUB_SPOKES = [
    # DEN hub
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
    # Chicago MDW
    ("MDW", "FLL"), ("MDW", "LAS"), ("MDW", "MCO"), ("MDW", "MIA"), ("MDW", "PHX"),
    ("MDW", "TPA"), ("MDW", "SJU"), ("MDW", "MSY"), ("MDW", "PHL"),
    # LAS
    ("LAS", "ATL"), ("LAS", "CLT"), ("LAS", "FLL"), ("LAS", "IAH"), ("LAS", "LAX"),
    ("LAS", "MCO"), ("LAS", "MIA"), ("LAS", "MSP"), ("LAS", "OAK"), ("LAS", "ORD"),
    ("LAS", "PHX"), ("LAS", "SAN"), ("LAS", "SFO"), ("LAS", "SJC"), ("LAS", "TPA"),
    # MCO
    ("MCO", "BOS"), ("MCO", "BWI"), ("MCO", "CLT"), ("MCO", "EWR"), ("MCO", "FLL"),
    ("MCO", "IAD"), ("MCO", "LGA"), ("MCO", "MIA"), ("MCO", "PHL"), ("MCO", "PHX"),
    ("MCO", "MSP"), ("MCO", "SJU"),
    # PHX
    ("PHX", "LAX"), ("PHX", "OAK"), ("PHX", "SAN"), ("PHX", "SFO"), ("PHX", "SJC"),
    ("PHX", "TPA"), ("PHX", "MSP"), ("PHX", "ORD"), ("PHX", "FLL"), ("PHX", "MIA"),
    # FLL
    ("FLL", "BOS"), ("FLL", "BWI"), ("FLL", "CLE"), ("FLL", "CLT"), ("FLL", "EWR"),
    ("FLL", "IAD"), ("FLL", "LGA"), ("FLL", "MDW"), ("FLL", "MIA"), ("FLL", "PHL"),
    # MIA
    ("MIA", "BOS"), ("MIA", "EWR"), ("MIA", "LGA"), ("MIA", "MDW"), ("MIA", "ORD"),
    ("MIA", "PHL"),
    # SJU
    ("SJU", "BWI"), ("SJU", "CLT"), ("SJU", "EWR"), ("SJU", "FLL"), ("SJU", "IAD"),
    ("SJU", "MIA"), ("SJU", "ORD"), ("SJU", "PHL"),
    # West Coast
    ("LAX", "SFO"), ("LAX", "SJC"), ("LAX", "SEA"), ("LAX", "OAK"),
    ("SFO", "SEA"), ("SAN", "SEA"), ("OAK", "SEA"),
    # Texas
    ("DAL", "LAS"), ("DAL", "MCO"), ("DAL", "MIA"), ("DAL", "PHX"),
    ("AUS", "LAS"), ("AUS", "MCO"), ("AUS", "PHX"),
    ("SAT", "LAS"), ("SAT", "MCO"),
    ("HOU", "LAS"), ("HOU", "MCO"), ("HOU", "MIA"),
    # Southeast
    ("TPA", "BOS"), ("TPA", "BWI"), ("TPA", "CLT"), ("TPA", "EWR"),
    ("TPA", "LGA"), ("TPA", "MDW"), ("TPA", "PHL"),
    ("MSY", "LAS"), ("MSY", "MCO"), ("MSY", "PHX"),
    # Midwest
    ("ORD", "FLL"), ("ORD", "LAS"), ("ORD", "MCO"), ("ORD", "MIA"), ("ORD", "PHX"),
    ("MSP", "FLL"), ("MSP", "MCO"), ("MSP", "PHX"), ("MSP", "TPA"),
    ("MCI", "LAS"), ("MCI", "MCO"), ("MCI", "PHX"),
    # Mid-Atlantic / Northeast
    ("PHL", "FLL"), ("PHL", "LAS"), ("PHL", "MCO"), ("PHL", "MIA"), ("PHL", "PHX"),
    ("PHL", "TPA"), ("PHL", "SJU"),
    ("EWR", "FLL"), ("EWR", "MCO"), ("EWR", "PHX"), ("EWR", "TPA"),
    ("BOS", "FLL"), ("BOS", "MCO"), ("BOS", "MIA"), ("BOS", "TPA"),
]

FRONTIER_KNOWN_ROUTES: set[tuple[str, str]] = set()
for _o, _d in _HUB_SPOKES:
    FRONTIER_KNOWN_ROUTES.add((_o, _d))
    FRONTIER_KNOWN_ROUTES.add((_d, _o))

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

STEALTH_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}


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
        has_price = any(k in node for k in ("price", "totalPrice", "amount", "fare", "total"))
        has_context = any(k in node for k in (
            "flightNumber", "flight_number", "segments", "legs",
            "fareBrand", "fare_brand", "brandName", "fareFamily", "productName",
            "fareType", "cabin", "productType",
        ))
        if has_price and has_context:
            brand = str(
                node.get("fareBrand") or node.get("fare_brand") or
                node.get("brandName") or node.get("fareFamily") or
                node.get("productName") or node.get("fareType") or
                node.get("productType") or ""
            )
            if _is_go_wild(brand):
                raw_price = (
                    node.get("price") or node.get("totalPrice") or
                    node.get("amount") or node.get("fare") or
                    node.get("total") or 0
                )
                # price may be nested: {"amount": 0, "currency": "USD"}
                if isinstance(raw_price, dict):
                    raw_price = raw_price.get("amount", 0) or raw_price.get("value", 0)
                price = float(raw_price)
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


async def _new_context(browser: Browser, auth_state: dict | None = None) -> BrowserContext:
    kwargs = dict(
        user_agent=USER_AGENT,
        extra_http_headers=STEALTH_HEADERS,
        viewport={"width": 1280, "height": 800},
    )
    if auth_state:
        kwargs["storage_state"] = auth_state
    return await browser.new_context(**kwargs)


def _is_frontier_url(url: str) -> bool:
    return "flyfrontier" in url or "frontierairlines" in url


# ---------------------------------------------------------------------------
# Saved session (preferred — avoids 2FA entirely)
# ---------------------------------------------------------------------------

def _load_saved_auth_state() -> dict | None:
    """Load a previously captured session from FRONTIER_AUTH_STATE env var
    (GitHub Secret) or a local auth_state.json file."""
    import json

    raw = os.environ.get("FRONTIER_AUTH_STATE", "").strip()
    source = "FRONTIER_AUTH_STATE secret"
    if not raw:
        try:
            with open("auth_state.json") as f:
                raw = f.read()
            source = "auth_state.json"
        except FileNotFoundError:
            return None

    try:
        state = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  ⚠️  Could not parse saved session from {source}: {e}")
        return None

    print(f"  Loaded saved Frontier session from {source} "
          f"({len(state.get('cookies', []))} cookies).")
    return state


async def _validate_auth_state(browser: Browser, auth_state: dict) -> dict | None:
    """Open the booking site with the saved session and confirm it's still
    logged in. Returns the state if valid, else None."""
    context = await _new_context(browser, auth_state)
    page = await context.new_page()
    try:
        await page.goto(FRONTIER_HOME, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(4_000)
        body = (await page.evaluate("document.body.innerText")).lower()
        if any(s in body for s in ("sign out", "log out", "logout", "my account", "miles")):
            print("  ✅ Saved session is still valid.")
            return auth_state
        print("  ⚠️  Saved session appears EXPIRED — run save_session.py locally "
              "and update the FRONTIER_AUTH_STATE secret.")
        return None
    except Exception as e:
        print(f"  Session validation error: {type(e).__name__}: {e} — using it anyway.")
        return auth_state
    finally:
        await context.close()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

async def _login(browser: Browser, email: str, password: str) -> dict | None:
    """Log in to Frontier and return the serialized auth state (cookies + storage)."""
    context = await _new_context(browser)
    page = await context.new_page()
    auth_state = None

    try:
        print("Logging in to Frontier…")
        await page.goto(FRONTIER_HOME, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(3_000)

        # Find and click sign-in link
        sign_in_selectors = [
            'a:has-text("Sign In")',
            'button:has-text("Sign In")',
            'a:has-text("Log In")',
            '[data-testid*="sign"]',
            '[data-cy*="sign"]',
            'a[href*="sign"]',
            'a[href*="login"]',
        ]
        clicked = False
        for sel in sign_in_selectors:
            try:
                elem = page.locator(sel).first
                if await elem.is_visible(timeout=2_000):
                    await elem.click()
                    clicked = True
                    print(f"  Clicked sign-in: {sel!r}")
                    break
            except Exception:
                continue

        if not clicked:
            print("  No sign-in button found on homepage — trying direct login URL…")
            for login_url in [
                f"{FRONTIER_HOME}/account/login",
                f"{FRONTIER_HOME}/login",
                f"{FRONTIER_HOME}/signIn",
            ]:
                try:
                    await page.goto(login_url, wait_until="domcontentloaded", timeout=15_000)
                    if page.url == login_url or "login" in page.url or "sign" in page.url.lower():
                        print(f"  At login URL: {page.url}")
                        break
                except Exception:
                    pass

        await page.wait_for_timeout(2_000)

        # Fill email
        try:
            email_input = page.locator(
                'input[type="email"], input[name*="email" i], input[id*="email" i], input[placeholder*="email" i]'
            ).first
            await email_input.wait_for(state="visible", timeout=10_000)
            await email_input.fill(email)
            print("  Filled email.")
        except Exception as e:
            print(f"  Email field not found: {e}")
            return None

        await page.wait_for_timeout(500)

        # Fill password
        try:
            pw_input = page.locator('input[type="password"]').first
            await pw_input.wait_for(state="visible", timeout=5_000)
            await pw_input.fill(password)
            print("  Filled password.")
        except Exception as e:
            print(f"  Password field not found: {e}")
            return None

        await page.wait_for_timeout(500)

        # Submit
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Log In")',
            'button:has-text("Continue")',
        ]
        for sel in submit_selectors:
            try:
                btn = page.locator(sel).first
                if await btn.is_visible(timeout=2_000):
                    await btn.click()
                    print(f"  Clicked submit: {sel!r}")
                    break
            except Exception:
                continue

        submit_time = time.time()
        await page.wait_for_timeout(4_000)

        # --- 2FA: Frontier emails a verification code on every login ---
        otp_input = None
        otp_selectors = [
            'input[autocomplete="one-time-code"]',
            'input[name*="code" i]',
            'input[id*="code" i]',
            'input[name*="otp" i]',
            'input[id*="otp" i]',
            'input[placeholder*="code" i]',
        ]
        for sel in otp_selectors:
            try:
                e = page.locator(sel).first
                if await e.is_visible(timeout=2_000):
                    otp_input = e
                    print(f"  2FA code screen detected ({sel!r}).")
                    break
            except Exception:
                continue

        if otp_input is not None:
            gmail_user = os.environ.get("GMAIL_EMAIL", email)
            gmail_app_pw = os.environ.get("GMAIL_APP_PASSWORD", "")
            if not gmail_app_pw:
                print("  ⚠️  2FA required but GMAIL_APP_PASSWORD is not set — cannot proceed.")
                return None

            from otp import fetch_frontier_otp
            print("  Polling Gmail for the verification code…")
            code = await asyncio.to_thread(
                fetch_frontier_otp, gmail_user, gmail_app_pw, submit_time
            )
            if not code:
                print("  ⚠️  No OTP email arrived — login failed.")
                return None

            await otp_input.fill(code)
            print(f"  Entered code.")
            await page.wait_for_timeout(500)
            for sel in [
                'button[type="submit"]',
                'button:has-text("Verify")',
                'button:has-text("Continue")',
                'button:has-text("Submit")',
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=2_000):
                        await btn.click()
                        break
                except Exception:
                    continue

        # Wait for navigation after login
        try:
            await page.wait_for_url(
                lambda url: "login" not in url.lower() and "sign" not in url.lower(),
                timeout=15_000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(3_000)

        final_url = page.url
        print(f"  Login result URL: {final_url}")

        if "login" in final_url.lower() or "sign" in final_url.lower():
            print("  ⚠️  Still on login page — credentials may be wrong or bot-blocked.")
            return None

        auth_state = await context.storage_state()
        print("  ✅ Login succeeded — auth state captured.")

    except Exception as e:
        print(f"  Login error: {type(e).__name__}: {e}")
    finally:
        await context.close()

    return auth_state


# ---------------------------------------------------------------------------
# Route discovery
# ---------------------------------------------------------------------------

async def _discover_routes_async(browser: Browser, auth_state: dict | None) -> list[tuple[str, str]]:
    print("Using hardcoded Frontier route list…")
    pairs = sorted(FRONTIER_KNOWN_ROUTES)
    print(f"  {len(pairs)} route pairs to check")
    return pairs


# ---------------------------------------------------------------------------
# Route checking (parallel)
# ---------------------------------------------------------------------------

async def _check_route(
    sem: asyncio.Semaphore,
    browser: Browser,
    auth_state: dict | None,
    route: dict,
    date: str,
    search_url_template: list[str],  # mutable [url] so we can share the discovered URL
) -> list[GoWildFlight]:
    async with sem:
        context = await _new_context(browser, auth_state)
        page = await context.new_page()
        pending: list[Response] = []

        def on_response(r: Response) -> None:
            ct = r.headers.get("content-type", "")
            if r.status == 200 and "application/json" in ct and _is_frontier_url(r.url):
                pending.append(r)

        page.on("response", on_response)
        captured: list[GoWildFlight] = []
        seen: set[str] = set()

        origin = route["origin"]
        dest = route["destination"]

        try:
            # Build search URL
            params = urlencode({
                "origin": origin,
                "destination": dest,
                "departDate": date,
                "adults": "1",
                "children": "0",
                "infants": "0",
                "tripType": "ONE_WAY",
            })

            # Use discovered URL template if available, else try known patterns
            if search_url_template:
                url = f"{search_url_template[0]}?{params}"
            else:
                url = f"{FRONTIER_HOME}/flight/search?{params}"

            await page.goto(url, wait_until="networkidle", timeout=ROUTE_TIMEOUT_MS)
            await page.wait_for_timeout(2_500)

            # If page redirected to homepage (bot block), try form fill as fallback
            if "booking.flyfrontier.com" in page.url and "/flight" not in page.url:
                await _fill_search_form(page, origin, dest, date)
                await page.wait_for_timeout(3_000)

                # Record actual results URL for future requests
                if "/flight" in page.url and not search_url_template:
                    base = page.url.split("?")[0]
                    search_url_template.append(base)
                    print(f"  Discovered search URL: {base}")

            # Process captured JSON responses
            for r in pending:
                try:
                    data = await r.json()
                    for f in _extract_go_wild_flights(data, route, date):
                        if f.key() not in seen:
                            seen.add(f.key())
                            captured.append(f)
                except Exception:
                    pass

            # DOM fallback — scan visible fare cards
            try:
                body_text = await page.evaluate("document.body.innerText")
                if any(b in body_text.lower() for b in GO_WILD_BRANDS):
                    cards = await page.locator(
                        '[data-testid*="flight"], .flight-card, .fare-cell, '
                        '[class*="fare"], [class*="flight"]'
                    ).all()
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
                        f = GoWildFlight(origin, dest, date, dep, fn, price, "USD", "Go Wild")
                        if f.key() not in seen:
                            seen.add(f.key())
                            captured.append(f)
            except Exception:
                pass

        except Exception as e:
            print(f"    Error {origin}→{dest} {date}: {type(e).__name__}")
        finally:
            await context.close()

        return captured


async def _fill_search_form(page: Page, origin: str, dest: str, date: str) -> None:
    """Try to fill the booking search form directly."""
    # One-way toggle
    for sel in ['label:has-text("One-way")', 'input[value*="ONE_WAY"]', '#oneWay', '[data-testid*="oneway"]']:
        try:
            e = page.locator(sel).first
            if await e.is_visible(timeout=1_000):
                await e.click()
                break
        except Exception:
            pass

    # Origin field
    for sel in ['input[name*="origin" i]', 'input[id*="from" i]', 'input[placeholder*="from" i]', '#Origin']:
        try:
            e = page.locator(sel).first
            if await e.is_visible(timeout=1_000):
                await e.triple_click()
                await e.type(origin, delay=80)
                await page.wait_for_timeout(1_000)
                for suggestion in [f'li:has-text("{origin}")', f'[data-iata="{origin}"]', f'[data-code="{origin}"]']:
                    try:
                        s = page.locator(suggestion).first
                        if await s.is_visible(timeout=1_000):
                            await s.click()
                            break
                    except Exception:
                        pass
                break
        except Exception:
            pass

    # Destination field
    for sel in ['input[name*="dest" i]', 'input[id*="to" i]', 'input[placeholder*="to" i]', '#Destination']:
        try:
            e = page.locator(sel).first
            if await e.is_visible(timeout=1_000):
                await e.triple_click()
                await e.type(dest, delay=80)
                await page.wait_for_timeout(1_000)
                for suggestion in [f'li:has-text("{dest}")', f'[data-iata="{dest}"]', f'[data-code="{dest}"]']:
                    try:
                        s = page.locator(suggestion).first
                        if await s.is_visible(timeout=1_000):
                            await s.click()
                            break
                    except Exception:
                        pass
                break
        except Exception:
            pass

    # Date field
    for sel in ['input[name*="depart" i]', 'input[type="date"]', 'input[id*="date" i]', '#DepartDate']:
        try:
            e = page.locator(sel).first
            if await e.is_visible(timeout=1_000):
                await e.fill(date)
                break
        except Exception:
            pass

    # Submit
    for sel in ['button[type="submit"]', 'input[value="SEARCH"]', 'button:has-text("Search")', 'button:has-text("SEARCH")']:
        try:
            e = page.locator(sel).first
            if await e.is_visible(timeout=1_000):
                await e.click()
                break
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def _run(config: dict, timezone: str) -> list[GoWildFlight]:
    days_ahead = config.get("days_ahead", 7)
    dates = _date_range(days_ahead, timezone)

    email = config.get("frontier_email") or os.environ.get("FRONTIER_EMAIL", "")
    password = config.get("frontier_password") or os.environ.get("FRONTIER_PASSWORD", "")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        try:
            # Auth priority: saved session (FRONTIER_AUTH_STATE or auth_state.json)
            # > interactive login > anonymous
            auth_state = _load_saved_auth_state()
            if auth_state:
                auth_state = await _validate_auth_state(browser, auth_state)

            if auth_state is None and email and password:
                auth_state = await _login(browser, email, password)
                if auth_state is None:
                    print("  Login failed — continuing without authentication (Go Wild fares may not appear)")
            elif auth_state is None:
                print("  No Frontier session or credentials configured — searching without login")

            # Route discovery
            all_routes_mode = config.get("all_routes", False)
            if all_routes_mode:
                pairs = await _discover_routes_async(browser, auth_state)
                routes_to_check = [
                    {"origin": o, "destination": d, "maxPrice": config.get("maxPrice")}
                    for o, d in pairs
                ]
            else:
                routes_to_check = config.get("routes", [])

            total = len(routes_to_check) * len(dates)
            print(f"Checking {len(routes_to_check)} route(s) × {len(dates)} date(s) = {total} searches ({CONCURRENCY} parallel)")

            sem = asyncio.Semaphore(CONCURRENCY)
            search_url_template: list[str] = []  # shared mutable to record discovered URL

            tasks = [
                _check_route(sem, browser, auth_state, route, date, search_url_template)
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
                    print(f"  Progress: {done}/{len(tasks)} done, {len(all_results)} Go Wild flight(s) found so far")

        finally:
            await browser.close()

    return all_results


def scrape_go_wild_flights(config: dict, timezone: str = "America/Chicago") -> list[GoWildFlight]:
    return asyncio.run(_run(config, timezone))
