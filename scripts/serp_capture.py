"""Playwright-based capture of a single Google SERP, focused on the AI Overview.

Run as a function via monitor_serp.py; not intended as a standalone CLI in the
common case. Standalone usage exists for debugging and for the one-time priming
run that solves Google's captcha to warm the persistent profile.

Uses a persistent Chromium profile at ~/.cache/serp-monitor/profile/. The first
time the profile is used, Google will challenge with a captcha; the priming run
(`python serp_capture.py --prime`) launches a visible browser so a human can
solve the captcha once. After that, subsequent headless runs reuse the
profile's cookies and avoid the challenge.

If captcha is detected on a headless run (HTML contains 'recaptcha' or shows
the /sorry/ interstitial), capture_serp raises CaptureCaptchaError so the
orchestrator can stop the run cleanly instead of recording 18 captcha pages.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import async_playwright

PROFILE_DIR = Path.home() / ".cache" / "serp-monitor" / "profile"

LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-features=IsolateOrigins,site-per-process",
]

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36"
)


class CaptureCaptchaError(RuntimeError):
    """Raised when Google challenged the capture with a captcha. Signals the
    orchestrator to halt and ask the user to re-prime the profile."""


@dataclass
class CaptureResult:
    """Outcome of one capture. The html and png paths are the on-disk locations
    of the saved artifacts; consumers parse the html themselves."""
    html_path: Path
    png_path: Path


def _looks_like_captcha(html: str) -> bool:
    """Cheap captcha-detector. Google's challenge pages are tiny (~6-8 KB) and
    contain 'recaptcha' or '/sorry/' markers. Real SERPs are >100 KB and
    don't reference recaptcha at the top of <body>."""
    if len(html) > 50_000:
        return False
    lo = html.lower()
    return ("recaptcha" in lo) or ("/sorry/" in lo) or ("unusual traffic" in lo)


async def capture_serp(
    query: str,
    out_dir: Path,
    slug: str,
    headless: bool = True,
) -> CaptureResult:
    """Capture one Google SERP. Returns paths to the saved html + png.

    `slug` is used as the filename stem so the orchestrator controls naming
    (e.g. `A1-best-russian-speaking-realtor-bay-area`).

    Raises CaptureCaptchaError if Google served a captcha challenge instead
    of a SERP. The caller should treat this as a hard stop (re-prime the
    profile) rather than retry per-query.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{slug}.html"
    png_path = out_dir / f"{slug}.png"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            args=LAUNCH_ARGS,
            locale="en-US",
            timezone_id="America/Los_Angeles",
            viewport={"width": 1440, "height": 900},
            user_agent=USER_AGENT,
        )
        # Hide navigator.webdriver — one of Google's headless tells.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        await page.goto(
            f"https://www.google.com/search?q={query.replace(' ', '+')}&hl=en&gl=us",
            wait_until="networkidle",
            timeout=30_000,
        )
        # Give AI Overview JS extra time to render; not all queries get one.
        await page.wait_for_timeout(3_000)
        content = await page.content()
        html_path.write_text(content, encoding="utf-8")
        await page.screenshot(path=str(png_path), full_page=True)
        await context.close()

    if _looks_like_captcha(html_path.read_text(encoding="utf-8")):
        raise CaptureCaptchaError(
            f"Captcha challenge on query {query!r}. "
            f"Re-prime the profile: uv run python scripts/serp_capture.py --prime"
        )

    return CaptureResult(html_path=html_path, png_path=png_path)


READY_FILE = PROFILE_DIR.parent / "ready"


async def prime_profile() -> None:
    """One-time interactive priming run. Launches a visible browser, navigates
    to a Google search, and waits for the human to solve any captcha.

    Signal that priming is done by creating the ready file in another shell:
        touch ~/.cache/serp-monitor/ready

    The script polls every 2 seconds for the file. Max wait: 10 minutes.
    The ready file is deleted on exit so each priming run needs a fresh signal.
    Cookies persist in PROFILE_DIR for subsequent headless runs.
    """
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    READY_FILE.unlink(missing_ok=True)  # clear any stale signal from a prior run

    print(f"Priming profile at: {PROFILE_DIR}")
    print("A browser window will open. If Google shows a captcha, solve it.")
    print(f"When you see a real Google SERP, signal ready in another terminal:")
    print(f"    touch {READY_FILE}")
    print(f"Then this script will close the browser and exit.")
    print(f"(Or wait 10 minutes for auto-timeout.)\n")

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            args=LAUNCH_ARGS,
            locale="en-US",
            timezone_id="America/Los_Angeles",
            viewport={"width": 1440, "height": 900},
            user_agent=USER_AGENT,
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = await context.new_page()
        await page.goto(
            "https://www.google.com/search?q=best+russian+speaking+realtor+bay+area&hl=en&gl=us",
            wait_until="domcontentloaded",
            timeout=60_000,
        )

        # Poll for ready file. Max 10 min wait.
        max_wait_s = 600
        elapsed = 0
        while not READY_FILE.exists() and elapsed < max_wait_s:
            await asyncio.sleep(2)
            elapsed += 2

        if READY_FILE.exists():
            print(f"Ready signal received after {elapsed}s. Closing browser.")
            READY_FILE.unlink()
        else:
            print(f"Timed out after {max_wait_s}s with no ready signal. Closing anyway.")

        await context.close()

    print("Profile primed. Subsequent headless runs should now succeed.")


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == "--prime":
        asyncio.run(prime_profile())
        sys.exit(0)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python serp_capture.py --prime           # one-time interactive priming")
        print("  python serp_capture.py '<query>'         # capture one query (debug)")
        sys.exit(2)

    q = sys.argv[1]
    out = Path("notes/serp-monitoring/_debug")
    try:
        result = asyncio.run(capture_serp(q, out, slug="debug"))
    except CaptureCaptchaError as e:
        print(f"ERROR: {e}")
        sys.exit(3)
    print(f"html: {result.html_path}")
    print(f"png:  {result.png_path}")
