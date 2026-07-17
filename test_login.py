"""
Local login test — opens a VISIBLE browser so we can watch what Frontier's
login flow actually does (2FA prompt? captcha? straight in?).

Run with:
  export FRONTIER_EMAIL="you@example.com"
  export FRONTIER_PASSWORD="yourpassword"
  python test_login.py
"""
import asyncio
import os
import sys

from playwright.async_api import async_playwright

from scraper import _login, USER_AGENT, STEALTH_HEADERS, FRONTIER_HOME


async def main():
    email = os.environ.get("FRONTIER_EMAIL", "")
    password = os.environ.get("FRONTIER_PASSWORD", "")
    if not email or not password:
        print("Set FRONTIER_EMAIL and FRONTIER_PASSWORD env vars first.")
        sys.exit(1)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=200)
        state = await _login(browser, email, password)

        if state:
            print("\n✅ Login worked with no 2FA — saving session state to auth_state.json")
            import json
            with open("auth_state.json", "w") as f:
                json.dump(state, f)
        else:
            print("\n⚠️  Login did not complete cleanly.")
            print("Watch the browser window — is it asking for a verification code?")
            print("Leaving browser open for 120s so you can look…")
            await asyncio.sleep(120)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
