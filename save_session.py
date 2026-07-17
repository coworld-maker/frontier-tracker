"""
One-time (well, occasional) manual login to capture a Frontier session.

Opens a visible browser at booking.flyfrontier.com. YOU log in by hand —
email, password, and the emailed verification code. The script detects the
logged-in session and saves it to auth_state.json.

Then copy the file contents into the FRONTIER_AUTH_STATE GitHub Secret:
  cat auth_state.json | pbcopy
  → repo Settings → Secrets → Actions → FRONTIER_AUTH_STATE → paste

Re-run this whenever the session expires (the workflow log will say so).

Run with:  python3 save_session.py
"""
import asyncio
import json

from playwright.async_api import async_playwright

from scraper import FRONTIER_HOME, USER_AGENT, STEALTH_HEADERS

MAX_WAIT_MINUTES = 10


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            extra_http_headers=STEALTH_HEADERS,
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()
        await page.goto(FRONTIER_HOME, wait_until="domcontentloaded")

        print("=" * 60)
        print("A browser window is open. Log in to your Frontier account:")
        print("  1. Click Sign In / Log In")
        print("  2. Enter email + password")
        print("  3. Enter the verification code from your email")
        print(f"Waiting up to {MAX_WAIT_MINUTES} minutes for login…")
        print("=" * 60)

        logged_in = False
        for _ in range(MAX_WAIT_MINUTES * 12):  # poll every 5s
            await asyncio.sleep(5)
            try:
                body = await page.evaluate("document.body.innerText")
                low = body.lower()
                if any(s in low for s in ("my account", "sign out", "log out", "logout", "miles")):
                    logged_in = True
                    break
            except Exception:
                pass

        if not logged_in:
            print("\n⚠️  Never detected a logged-in state. If you DID log in successfully,")
            print("    the session will still be saved — check the file works in Actions.")

        state = await context.storage_state()
        with open("auth_state.json", "w") as f:
            json.dump(state, f)
        print(f"\n✅ Session saved to auth_state.json "
              f"({len(state.get('cookies', []))} cookies, "
              f"{len(state.get('origins', []))} origins with storage).")
        print("\nNext steps:")
        print("  cat auth_state.json | pbcopy")
        print("  → GitHub repo → Settings → Secrets and variables → Actions")
        print("  → New repository secret → name: FRONTIER_AUTH_STATE → paste value")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
