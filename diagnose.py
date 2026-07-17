"""
Diagnostic script — runs a single DEN→LAS search and dumps:
  - Every JSON response from flyfrontier.com (URL + truncated body)
  - Whether any fare/brand data is present
  - A screenshot of the page after load
  - DOM text content (first 3000 chars)

Run with:  python diagnose.py
"""
import asyncio
import json
from datetime import date, timedelta
from urllib.parse import urlencode

from playwright.async_api import async_playwright

ORIGIN = "DEN"
DEST = "LAS"
SEARCH_URL = "https://booking.flyfrontier.com/flight/search"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}


def _contains_fare_keywords(obj, depth=0):
    """Recursively search for fare/brand related keys."""
    if depth > 10:
        return []
    hits = []
    keywords = {"gowild", "go wild", "wild", "farebrand", "fare_brand", "brandname",
                "fareFamily", "productName", "price", "amount", "totalPrice"}
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() in keywords:
                hits.append(f"  key={k!r} value={str(v)[:100]!r}")
            hits.extend(_contains_fare_keywords(v, depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            hits.extend(_contains_fare_keywords(item, depth + 1))
    return hits


async def main():
    depart = (date.today() + timedelta(days=2)).isoformat()
    params = urlencode({
        "origin": ORIGIN, "destination": DEST,
        "departDate": depart, "returnDate": "",
        "adults": "1", "children": "0", "infants": "0",
        "tripType": "ONE_WAY",
    })
    url = f"{SEARCH_URL}?{params}"
    print(f"\n{'='*60}")
    print(f"Searching: {ORIGIN} → {DEST} on {depart}")
    print(f"URL: {url}")
    print(f"{'='*60}\n")

    all_responses = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            extra_http_headers=HEADERS,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        # Capture ALL JSON responses from flyfrontier.com
        async def on_response(r):
            if "flyfrontier" not in r.url and "frontierairlines" not in r.url:
                return
            ct = r.headers.get("content-type", "")
            if r.status == 200 and "application/json" in ct:
                try:
                    data = await r.json()
                    all_responses.append((r.url, data))
                except Exception:
                    pass

        page.on("response", on_response)

        print(f"Navigating to booking homepage…")
        try:
            await page.goto("https://booking.flyfrontier.com/", wait_until="networkidle", timeout=40_000)
        except Exception as e:
            print(f"  Navigation exception: {type(e).__name__}: {e}")

        await page.wait_for_timeout(2_000)

        print("  Selecting One-way…")
        try:
            await page.locator('label:has-text("One-way"), input[value*="one"], #OneWay').first.click()
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  One-way click failed: {e}")

        print(f"  Filling origin={ORIGIN}…")
        try:
            orig_input = page.locator('input[name*="origin" i], input[placeholder*="from" i], #Origin').first
            await orig_input.fill("")
            await orig_input.type(ORIGIN, delay=80)
            await page.wait_for_timeout(1_000)
            await page.locator(f'li:has-text("{ORIGIN}"), [data-iata="{ORIGIN}"]').first.click()
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  Origin fill failed: {e}")

        print(f"  Filling destination={DEST}…")
        try:
            dest_input = page.locator('input[name*="dest" i], input[placeholder*="to" i], #Destination').first
            await dest_input.fill("")
            await dest_input.type(DEST, delay=80)
            await page.wait_for_timeout(1_000)
            await page.locator(f'li:has-text("{DEST}"), [data-iata="{DEST}"]').first.click()
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  Destination fill failed: {e}")

        print(f"  Setting depart date={depart}…")
        try:
            date_input = page.locator('input[name*="depart" i], input[type="date"], #DepartDate').first
            await date_input.fill(depart)
            await page.wait_for_timeout(500)
        except Exception as e:
            print(f"  Date fill failed: {e}")

        await page.screenshot(path="diagnose_before_search.png")
        print("  Screenshot before search: diagnose_before_search.png")

        print("  Clicking SEARCH…")
        try:
            search_btn = page.locator('input[value="SEARCH"], button:has-text("SEARCH"), button[type="submit"]').first
            await search_btn.click()
            print("  Clicked. Waiting up to 20s for results…")
            await page.wait_for_timeout(20_000)
        except Exception as e:
            print(f"  Search click failed: {e}")

        print(f"  Final URL: {page.url}")

        # Screenshot
        await page.screenshot(path="diagnose_screenshot.png", full_page=True)
        print("\nScreenshot saved: diagnose_screenshot.png")

        # DOM text
        body_text = await page.evaluate("document.body.innerText")
        print(f"\n--- DOM text (first 3000 chars) ---")
        print(body_text[:3000])

        await browser.close()

    print(f"\n{'='*60}")
    print(f"Total JSON responses captured from flyfrontier.com: {len(all_responses)}")
    print(f"{'='*60}")

    if not all_responses:
        print("\n⚠️  NO JSON API responses were intercepted.")
        print("   Possible causes:")
        print("   - Frontier blocks headless Chrome (bot detection)")
        print("   - Flight data loads via WebSocket or non-JSON format")
        print("   - URL params don't auto-trigger a search")
    else:
        for i, (resp_url, data) in enumerate(all_responses):
            print(f"\n[{i+1}] {resp_url}")
            hits = _contains_fare_keywords(data)
            if hits:
                print(f"  ✅ Contains fare/brand keys:")
                for h in hits[:20]:
                    print(h)
            else:
                body_preview = json.dumps(data)[:300]
                print(f"  (no fare keys found) preview: {body_preview}")

    # Check DOM for Go Wild text
    if "go wild" in body_text.lower() or "gowild" in body_text.lower():
        print("\n✅ 'Go Wild' text found in DOM!")
    else:
        print("\n⚠️  'Go Wild' NOT found in DOM text")

    if "$" in body_text:
        # Find price-like strings
        import re
        prices = re.findall(r"\$\d+(?:\.\d+)?", body_text)
        print(f"   Price strings found in DOM: {prices[:20]}")
    else:
        print("   No price strings ($) found in DOM")


if __name__ == "__main__":
    asyncio.run(main())
