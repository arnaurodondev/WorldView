#!/usr/bin/env python3
"""
Worldview demo screencast recorder.

Records a ~2.5-minute demo walking through the two core workflows:
  1. Generation: article → knowledge graph (NVIDIA entity intelligence: relations + graph neighborhood)
  2. Access: question → grounded answer (TSMC supply-chain exposure, then an AI-semiconductor screen)

All selectors below are taken from the actual frontend codebase
(apps/worldview-web), verified 2026-07-11:
  - Login dev button ........ button with text "Dev Login (no Zitadel)"   (app/login/page.tsx)
  - Instrument route ........ /instruments/<TICKER>                        (ticker-addressable, in sidebar)
  - Intelligence tab ........ button with text "INTELLIGENCE"              (components/instrument/tabs/InstrumentTabs.tsx, no aria-label)
  - Chat textarea ........... textarea[aria-label="Chat message input"]    (app/(app)/chat/page.tsx)
  - Chat send button ........ button[aria-label="Send message"]            (plain Enter also submits)
  - Streaming indicator ..... button with text "Stop generating"          (visible only while streaming)

Auth note (IMPORTANT): dev-login stores the access token in React state ONLY —
it sets no cookie and nothing in localStorage (contexts/AuthContext.tsx). A full
page reload therefore LOSES the session and hangs on "Initializing session…".
Consequently this script performs exactly ONE full page load — the /login page,
with ?redirect_to=<first destination> so dev-login's client-side router.replace()
lands us on the entity page already authenticated — and every subsequent hop is a
client-side navigation (clicking a Next.js <Link>, which preserves the in-memory
AuthProvider that wraps the whole app). Never call page.goto after login.

Requirements (install once):
    brew install ffmpeg
    .venv-demo/bin/pip install playwright && .venv-demo/bin/playwright install chromium

Usage:
    # Frontend must be running:  cd apps/worldview-web && pnpm dev
    .venv-demo/bin/python scripts/record_demo.py            # full recording → demo/worldview-demo.mp4
    .venv-demo/bin/python scripts/record_demo.py --fast     # quick selector smoke test (no recording)
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PWTimeout

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "http://localhost:3001"
OUTPUT_DIR = Path("demo")
OUTPUT_FILE = OUTPUT_DIR / "worldview-demo.mp4"
SHOTS_DIR = OUTPUT_DIR
RECORDING_DEVICE = "3"  # macOS AVFoundation screen index (ffmpeg -f avfoundation -list_devices: [3] Capture screen 0)

VIEWPORT = {"width": 1440, "height": 900}

# Record in Brave (Chromium-based) rather than the Playwright-bundled Chromium.
# Playwright has no "brave" channel, so we point it at Brave's binary directly.
# Falls back to bundled Chromium if Brave isn't installed at this path.
BRAVE_PATH = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"

# The instrument used for the "Generation" workflow (ticker-addressable route).
ENTITY_TICKER = "NVDA"

CHAT_QUESTION = "What is my exposure to TSMC? Show me supply chain relationships."
SCREENER_QUESTION = "Screen for AI semiconductor companies with market cap above $50B and positive YoY revenue growth."


# Timing profiles. --fast collapses all pauses and types instantly.
class Timing:
    def __init__(self, fast: bool):
        self.fast = fast
        self.short = 0.5 if fast else 1.5
        self.medium = 0.5 if fast else 2.5
        self.long = 0.5 if fast else 3.5
        self.type_delay_ms = 0 if fast else 35
        # Maximum wait for streaming to *start* (first "Stop generating" appearance).
        self.stream_start_timeout_ms = 6000 if fast else 15000
        # How long to *show* the streaming answer before clicking "Stop generating".
        # We interrupt mid-stream deliberately to keep the demo under 2.5 minutes;
        # the partial answer is still inspectable and demonstrates the capability.
        self.stream_show_s = 3 if fast else 25
        # Fallback wait when no "Stop generating" button ever appears (very fast or
        # cached answer delivered synchronously before button can render).
        self.stream_timeout_ms = 45000 if fast else 60000


# ---------------------------------------------------------------------------
# Screen recording (ffmpeg + macOS AVFoundation)
# ---------------------------------------------------------------------------


def start_recording(output_path: Path) -> subprocess.Popen:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "avfoundation",
        "-framerate",
        "30",
        "-capture_cursor",
        "1",
        "-capture_mouse_clicks",
        "1",
        "-i",
        f"{RECORDING_DEVICE}:none",
        "-vcodec",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        str(output_path),
    ]
    print(f"[recorder] Starting: {' '.join(cmd)}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    return proc


def stop_recording(proc: subprocess.Popen):
    try:
        proc.stdin.write(b"q")
        proc.stdin.flush()
        proc.wait(timeout=10)
    except Exception:
        proc.terminate()
    print(f"[recorder] Stopped. Output: {OUTPUT_FILE}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log_ok(step: str, msg: str = ""):
    print(f"  OK    [{step}] {msg}".rstrip())


def log_fail(step: str, msg: str):
    print(f"  FAILED[{step}] {msg}")


def shot(page: Page, step: str):
    try:
        SHOTS_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(SHOTS_DIR / f"screenshot_{step}.png"))
    except Exception as exc:  # never let a screenshot crash the demo
        print(f"  (screenshot {step} failed: {exc})")


def settle(page: Page):
    """Wait for network to go idle, tolerating pages that never fully idle."""
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except PWTimeout:
        pass


def login_and_land(page: Page, dest: str, t: Timing) -> bool:
    """The ONLY full page load: open /login with a redirect_to, click Dev Login,
    and let dev-login's client-side router.replace() land us on `dest` already
    authenticated (in-memory token preserved for the rest of the session).

    The login page probes /api/v1/auth/login to check if OIDC is unavailable.
    Next.js converts the upstream 502 to 500 when proxying, so the probe's
    `if (resp.status === 502)` check never fires and the Dev Login button stays
    hidden. Intercept the probe and return an explicit 502 so devLoginAvailable
    flips to true and the button appears."""
    from urllib.parse import quote

    # Intercept the OIDC probe (GET /api/v1/auth/login) and return 502 so the
    # Dev Login button appears. Route is method-specific to avoid accidentally
    # intercepting the POST /api/v1/auth/dev-login that handleDevLogin fires.
    def _intercept_oidc_probe(route):
        if route.request.method == "GET":
            route.fulfill(status=502, body='{"error":"oidc_discovery_failed"}')
        else:
            route.continue_()

    page.route("**/api/v1/auth/login", _intercept_oidc_probe)

    # Log network responses to diagnose dev-login failures.
    def _on_response(response):
        if "auth" in response.url:
            print(f"  [net] {response.request.method} {response.url} → {response.status}")

    page.on("response", _on_response)

    page.goto(f"{BASE_URL}/login?redirect_to={quote(dest, safe='')}", wait_until="domcontentloaded")
    settle(page)
    time.sleep(t.short)

    btn = page.get_by_role("button", name="Dev Login (no Zitadel)")
    try:
        btn.wait_for(state="visible", timeout=20000)
        print("  [login] Dev Login button found (role=button name)")
    except PWTimeout:
        # Try text-based fallback
        btn = page.locator("button", has_text="Dev Login").first
        try:
            btn.wait_for(state="visible", timeout=5000)
            print("  [login] Dev Login button found (text fallback)")
        except PWTimeout:
            # Button never appeared — dump page state for diagnosis
            all_btns = [b for b in page.locator("button").all_text_contents() if b.strip()]
            print(f"  [login] DIAGNOSIS: button not found. Page URL={page.url}")
            print(f"  [login] DIAGNOSIS: all buttons on page: {all_btns[:8]}")
            body_excerpt = page.locator("body").inner_text()[:200].replace("\n", " ")
            print(f"  [login] DIAGNOSIS: body excerpt: {body_excerpt}")
            shot(page, "login-debug")
            return False
    btn.click()
    print("  [login] button clicked, waiting for URL to leave /login")

    # router.replace(dest) is client-side — wait until we leave /login and the
    # session-init guard clears.
    try:
        page.wait_for_url(lambda url: "/login" not in url, timeout=20000)
        print(f"  [login] URL changed to: {page.url}")
    except PWTimeout:
        print(f"  [login] TIMEOUT waiting for URL change. Current URL: {page.url}")
        body_excerpt = page.locator("body").inner_text()[:200].replace("\n", " ")
        print(f"  [login] body: {body_excerpt}")
        shot(page, "login-timeout")
        return False
    wait_session_ready(page)
    settle(page)
    time.sleep(t.short)
    return True


def wait_session_ready(page: Page, timeout_ms: int = 20000):
    """Wait for the (app) layout's 'Initializing session…' guard to clear."""
    try:
        page.wait_for_function(
            "() => !document.body.innerText.includes('Initializing session')",
            timeout=timeout_ms,
        )
    except PWTimeout:
        pass


def click_nav(page: Page, href: str, t: Timing) -> bool:
    """Client-side navigation via a sidebar Next.js <Link> (preserves auth)."""
    link = page.locator(f'a[href="{href}"]').first
    try:
        link.wait_for(state="visible", timeout=15000)
        link.click()
    except PWTimeout:
        return False
    try:
        page.wait_for_url(lambda url: href in url, timeout=15000)
    except PWTimeout:
        return False
    wait_session_ready(page)
    settle(page)
    time.sleep(t.short)
    return True


def scroll_by(page: Page, px: int, pause: float):
    page.evaluate("(px) => window.scrollBy({top: px, behavior: 'smooth'})", px)
    time.sleep(pause)


# ---------------------------------------------------------------------------
# Demo steps — each returns True/False for the --fast smoke test
# ---------------------------------------------------------------------------


def step_login(page: Page, t: Timing) -> bool:
    """0:00 — dev-login and land directly on the NVIDIA instrument page."""
    step = "01-login"
    if not login_and_land(page, f"/instruments/{ENTITY_TICKER}", t):
        log_fail(step, "dev-login failed or did not land on the entity page")
        shot(page, step)
        return False
    log_ok(step, f"authenticated, landed on {page.url}")
    time.sleep(t.medium)
    shot(page, step)
    return True


def step_entity_page(page: Page, t: Timing) -> bool:
    """Workflow I: NVIDIA entity — profile, relations, graph neighborhood.
    We are already on /instruments/NVDA from the login redirect."""
    step = "02-entity"
    if ENTITY_TICKER not in page.url:
        log_fail(step, f"not on the entity page (url={page.url})")
        shot(page, step)
        return False
    time.sleep(t.medium)
    shot(page, "02a-entity-quote")

    # Switch to the INTELLIGENCE tab (relations + graph neighborhood live here).
    # The tab buttons in InstrumentTabs.tsx have no aria-label — only text content.
    tab = page.locator("button", has_text="INTELLIGENCE").first
    try:
        tab.wait_for(state="visible", timeout=30000)
        tab.click()
    except PWTimeout:
        log_fail(step, "INTELLIGENCE tab button not found (text-based selector)")
        shot(page, step)
        return False

    settle(page)
    time.sleep(t.long)
    # Reveal relations / related-entities / path-insights below the fold.
    scroll_by(page, 500, t.medium)
    shot(page, "02b-entity-intelligence")
    scroll_by(page, 500, t.medium)
    log_ok(step, "NVDA intelligence tab shown")
    return True


def dismiss_cookie_banner(page: Page):
    """Dismiss the cookie-consent banner if present (it overlaps the composer)."""
    for name in ("Accept all", "Reject optional"):
        btn = page.get_by_role("button", name=name)
        try:
            if btn.is_visible():
                btn.click()
                return
        except Exception as exc:
            # Best-effort; banner may not be present
            _ = exc


def open_composer(page: Page, t: Timing):
    """The chat empty-state hides the composer until a conversation exists.
    Click 'New conversation' / 'Start new chat' to reveal it, then wait for
    the textarea to appear before returning."""
    box = page.locator('textarea[aria-label="Chat message input"]')
    try:
        box.wait_for(state="visible", timeout=3000)
        print("  [chat] textarea already visible")
        return
    except PWTimeout:
        pass

    # Try "New conversation" (EmptyState CTA) or "Start new chat" (sidebar).
    opened = False
    for btn_name in ("New conversation", "Start new chat"):
        btn = page.get_by_role("button", name=btn_name).first
        try:
            btn.wait_for(state="visible", timeout=3000)
            print(f"  [chat] clicking '{btn_name}' to open composer")
            btn.click()
            opened = True
            break
        except PWTimeout:
            pass

    if not opened:
        # Dump diagnostics
        all_btns = [b for b in page.locator("button").all_text_contents() if b.strip()]
        print(f"  [chat] WARNING: no open-composer button found. URL={page.url}")
        print(f"  [chat] buttons on page: {all_btns[:10]}")
        shot(page, "chat-no-composer-btn")
        return

    # handleNewChat is synchronous (sets activeThreadId → textarea renders immediately)
    # but give React a tick to re-render before we proceed.
    try:
        box.wait_for(state="visible", timeout=5000)
        print("  [chat] textarea appeared after button click")
    except PWTimeout:
        print("  [chat] WARNING: textarea still not visible after button click")
        shot(page, "chat-textarea-missing")


def _send_chat(page: Page, question: str, t: Timing, step: str) -> bool:
    box = page.get_by_role("textbox", name="Chat message input")
    try:
        box.wait_for(state="visible", timeout=30000)
    except PWTimeout:
        # Fall back to the raw textarea selector.
        box = page.locator('textarea[aria-label="Chat message input"]')
        try:
            box.wait_for(state="visible", timeout=5000)
        except PWTimeout:
            log_fail(step, "chat textarea not found")
            shot(page, step)
            return False

    # The composer is DISABLED (aria-busy) while a previous answer is still
    # streaming. Wait for it to become enabled before typing, otherwise the
    # click/type races the in-flight stream and fails.
    try:
        page.wait_for_selector(
            'textarea[aria-label="Chat message input"]:not([disabled])',
            timeout=t.stream_timeout_ms,
        )
    except PWTimeout:
        log_fail(step, "chat composer stayed disabled (previous answer still streaming)")
        shot(page, step)
        return False

    box.click()
    box.fill("")  # clear any residual text
    box.type(question, delay=t.type_delay_ms)
    time.sleep(t.short)
    page.keyboard.press("Enter")

    # Streaming shows a "Stop generating" button; wait for it to appear then
    # disappear. If it never appears (very fast answer / non-streaming), just
    # fall through after a fixed wait.
    # Wait for streaming to start (Stop-generating button appears).
    stop_btn = page.get_by_role("button", name="Stop generating")
    streaming_started = False
    try:
        stop_btn.wait_for(state="visible", timeout=t.stream_start_timeout_ms)
        streaming_started = True
    except PWTimeout:
        pass

    if streaming_started:
        # Show the streaming answer for demo_show_s seconds, then interrupt.
        time.sleep(t.stream_show_s)
        try:
            if stop_btn.is_visible():
                stop_btn.click()  # clean stop — composer re-enables faster than an abandon
                stop_btn.wait_for(state="hidden", timeout=6000)
        except Exception as exc:
            _ = exc  # best-effort stop; compose re-enables on its own if this fails
    else:
        # Button never appeared; either answer was instant or stream failed.
        time.sleep(t.medium if t.fast else t.long)
    return True


def step_chat_exposure(page: Page, t: Timing) -> bool:
    """Workflow II: portfolio/graph exposure question."""
    step = "03-chat"
    # Scroll back to top so the sidebar link is not behind the bottom of the viewport.
    page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
    time.sleep(0.3)
    if not click_nav(page, "/chat", t):
        log_fail(step, "could not client-side navigate to /chat")
        shot(page, step)
        return False
    dismiss_cookie_banner(page)
    open_composer(page, t)
    time.sleep(t.short)
    if not _send_chat(page, CHAT_QUESTION, t, step):
        return False
    time.sleep(t.short)
    scroll_by(page, 600, t.medium)  # scroll through the streamed answer + citations
    shot(page, "03-chat-answer")
    scroll_by(page, 400, t.medium)
    log_ok(step, "TSMC exposure answer rendered")
    return True


def step_screener(page: Page, t: Timing) -> bool:
    """Workflow II: natural-language AI-semiconductor screen (asked in chat)."""
    step = "04-screener"
    if not _send_chat(page, SCREENER_QUESTION, t, step):
        return False
    time.sleep(t.short)
    scroll_by(page, 700, t.medium)  # reveal the result table
    shot(page, "04-screener-result")
    time.sleep(t.long)  # closing hold on the result
    log_ok(step, "screener answer rendered")
    return True


STEPS = [
    ("login", step_login),
    ("entity", step_entity_page),
    ("chat", step_chat_exposure),
    ("screener", step_screener),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def preflight() -> bool:
    import http.client
    import urllib.parse

    parsed = urllib.parse.urlparse(BASE_URL)
    try:
        conn = http.client.HTTPConnection(parsed.netloc, timeout=5)
        conn.request("GET", parsed.path or "/")
        resp = conn.getresponse()
        code = resp.status
        conn.close()
    except Exception as exc:
        print(f"ERROR: frontend not reachable at {BASE_URL} ({exc}).")
        print("Start it with: cd apps/worldview-web && pnpm dev")
        return False
    print(f"[preflight] frontend {BASE_URL} → HTTP {code}")
    return True


def run(fast: bool):
    t = Timing(fast)

    if not preflight():
        sys.exit(1)

    recorder = None
    if not fast:
        if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode != 0:
            print("ERROR: ffmpeg not installed (needed for webm→mp4 conversion). Run: brew install ffmpeg")
            sys.exit(1)
        print("=" * 60)
        print("Worldview demo recorder — FULL RECORDING")
        print(f"Output: {OUTPUT_FILE}")
        print("=" * 60)
    else:
        print("=" * 60)
        print("Worldview demo recorder — FAST SMOKE TEST (no recording)")
        print("=" * 60)

    # Video temp dir for Playwright's browser recording (used in full mode only).
    # Playwright records the browser tab as WebM; we convert to MP4 with ffmpeg.
    # This avoids macOS Screen Recording permission issues with AVFoundation.
    video_tmp_dir = OUTPUT_DIR / "playwright-video" if not fast else None
    if video_tmp_dir is not None:
        video_tmp_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, bool] = {}
    pw_video_path: str | None = None  # resolved inside the sync_playwright() block
    try:
        with sync_playwright() as p:
            # Use bundled Playwright Chromium — Brave has stricter security that can
            # block local dev-login fetch requests. Chromium is more permissive for
            # localhost API calls without a real TLS cert.
            browser = p.chromium.launch(
                headless=False,
                args=[
                    "--disable-infobars",
                    "--no-default-browser-check",
                    "--disable-web-security",  # allow localhost cross-origin
                    "--allow-insecure-localhost",
                ],
            )
            print("[browser] Using bundled Playwright Chromium")
            ctx_kwargs: dict = {"viewport": VIEWPORT, "locale": "en-US"}
            if video_tmp_dir is not None:
                # Playwright records the browser window at the viewport size.
                # path() is only valid AFTER context.close() but BEFORE the
                # sync_playwright() context exits (event loop must still be open).
                ctx_kwargs["record_video_dir"] = str(video_tmp_dir)
                ctx_kwargs["record_video_size"] = {"width": VIEWPORT["width"], "height": VIEWPORT["height"]}
            context = browser.new_context(**ctx_kwargs)
            page = context.new_page()
            page.set_default_timeout(30000)

            for name, fn in STEPS:
                try:
                    ok = fn(page, t)
                except Exception as exc:  # keep going so later selectors still get tested
                    ok = False
                    log_fail(name, f"exception: {exc}")
                    shot(page, f"error-{name}")
                results[name] = ok
                # In fast mode we keep going even on failure to test all selectors.
                if not ok and not fast:
                    print(f"[demo] step '{name}' failed; continuing.")

            if not fast:
                print("[demo] All steps complete — holding 3s...")
                time.sleep(3)
            # Grab the video path while the event loop is still open (after close,
            # before sync_playwright() exits).  page.video is None in fast mode.
            video_ref = page.video
            context.close()  # finalises the WebM file on disk
            if video_ref is not None:
                pw_video_path = video_ref.path()
            browser.close()
    finally:
        if recorder is not None:
            stop_recording(recorder)

    # Convert Playwright WebM → MP4 (no macOS screen-recording permission needed).
    if not fast and pw_video_path is not None:
        try:
            webm_path = pw_video_path
            print(f"[video] Browser recording: {webm_path}")
            OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(webm_path),
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-pix_fmt",
                    "yuv420p",
                    str(OUTPUT_FILE),
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                size_mb = OUTPUT_FILE.stat().st_size / 1_048_576
                print(f"[video] Saved {OUTPUT_FILE} ({size_mb:.1f} MB)")
            else:
                print(f"[video] ffmpeg conversion failed:\n{result.stderr[-400:]}")
        except Exception as exc:
            print(f"[video] Error extracting video: {exc}")

    print("\n" + "=" * 60)
    print("RESULTS")
    for name, _ in STEPS:
        status = "OK" if results.get(name) else "FAILED"
        print(f"  {status:6} {name}")
    print("=" * 60)
    if not fast:
        print(f"\nVideo: {OUTPUT_FILE}")
        print("Trim intro/outro if needed:")
        print("  ffmpeg -i demo/worldview-demo.mp4 -ss 2 -to 150 -c copy demo/worldview-demo-trimmed.mp4")

    if not all(results.get(n) for n, _ in STEPS):
        sys.exit(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Record (or smoke-test) the Worldview demo.")
    ap.add_argument(
        "--fast",
        action="store_true",
        help="Quick selector smoke test: instant typing, short pauses, no screen recording.",
    )
    args = ap.parse_args()
    run(fast=args.fast)
