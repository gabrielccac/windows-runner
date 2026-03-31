#!/usr/bin/env python3
"""
Token generation with Zendriver.
"""
import asyncio
import time

import zendriver as zd


URL = "https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf"

# SPA sends failures to e.g.
# https://servicos.receitafederal.gov.br/erro-captcha#/home/cpf&hCaptchaResponse=...
# Use location.href in JS (hash included); CDP page.url often misses or lags hash updates.
ERRO_CAPTCHA_MARKER = "erro-captcha"

HEADLESS = False

# zd.start(browser=...) — "auto" | "chrome" | "brave". Keeps Zendriver’s normal resolution.
BROWSER: str = "auto"

# Faster polling (was 0.5s). Total wait budget preserved via iteration counts below.
POLL_INTERVAL_SEC = 0.2
# 150 * 0.2s ≈ 30s (same max wait as old 60 * 0.5s readiness loop).
READINESS_MAX_ITERATIONS = 150
# 75 * 0.2s ≈ 15s (same as old 30 * 0.5s token loop).
TOKEN_POLL_MAX_ITERATIONS = 75

# Extra flags on top of Zendriver defaults (good for VPS / headless / low CPU).
# Defaults already include: --no-first-run, --password-store=basic, --disable-dev-shm-usage, etc.
BROWSER_ARGS_EXTRA: list[str] = [
    "--disable-gpu",
    "--disable-software-rasterizer",
    "--mute-audio",
    "--disable-features=TranslateUI",
]

# Slightly more tolerant CDP attach on slow machines (defaults 0.25s / 10 tries).
BROWSER_CONNECTION_TIMEOUT = 0.5
BROWSER_CONNECTION_MAX_TRIES = 15

# One CDP round-trip: widget DOM + hcaptcha global (was two evaluates per iteration).
JS_READINESS = """(() => ({
    widget: document.querySelector('[data-hcaptcha-widget-id]') !== null,
    ready: typeof hcaptcha !== 'undefined',
}))()"""

# One CDP round-trip per poll: token + error + full URL (hash routes need location.href).
JS_TOKEN_SNAPSHOT = """(() => ({
    token: window.__zd_hcaptcha_token,
    err: window.__zd_hcaptcha_error,
    href: location.href,
}))()"""


def _is_erro_captcha_url(url: str | None) -> bool:
    return bool(url and ERRO_CAPTCHA_MARKER in url.lower())

JS_START_TOKEN_EXECUTION = """
(() => {
    window.__zd_hcaptcha_token = null;
    window.__zd_hcaptcha_error = null;
    (async function() {
        try {
            const el = document.querySelector('[data-hcaptcha-widget-id]');
            if (!el) throw new Error('No hCaptcha element found');
            if (typeof hcaptcha === 'undefined') {
                throw new Error('hcaptcha not loaded');
            }
            const id = el.getAttribute('data-hcaptcha-widget-id');
            const result = await hcaptcha.execute(id, { async: true });
            window.__zd_hcaptcha_token = result && result.response ? result.response : null;
        } catch (e) {
            window.__zd_hcaptcha_error = String(e);
        }
    })();
    return true;
})()
"""


async def generate_token() -> str | None:
    browser = await zd.start(
        headless=HEADLESS,
        browser=BROWSER,
        disable_webrtc=True,
        disable_webgl=True,
        browser_args=BROWSER_ARGS_EXTRA,
        browser_connection_timeout=BROWSER_CONNECTION_TIMEOUT,
        browser_connection_max_tries=BROWSER_CONNECTION_MAX_TRIES,
    )
    page = await browser.get(URL)
    print("⚒️  Page opened")

    try:
        # Invisible hCaptcha iframe may be hidden, so only require DOM presence.
        for _ in range(READINESS_MAX_ITERATIONS):
            snap = await page.evaluate(JS_READINESS)
            widget_present = snap.get("widget") if isinstance(snap, dict) else False
            ready = snap.get("ready") if isinstance(snap, dict) else False
            if widget_present and ready:
                break
            await asyncio.sleep(POLL_INTERVAL_SEC)
        else:
            print("⛔ hCaptcha timed out")
            return None

        print("🔎 hCaptcha widget found")
        print("🔑 hCaptcha ready, executing...")
        await page.evaluate(JS_START_TOKEN_EXECUTION)

        for _ in range(TOKEN_POLL_MAX_ITERATIONS):
            snap = await page.evaluate(JS_TOKEN_SNAPSHOT)
            if not isinstance(snap, dict):
                await asyncio.sleep(POLL_INTERVAL_SEC)
                continue
            href = snap.get("href")
            if isinstance(href, str) and _is_erro_captcha_url(href):
                print(f"⛔ Receita erro-captcha redirect: {href}")
                return None
            token = snap.get("token")
            err = snap.get("err")
            if isinstance(token, str) and token.strip():
                return token.strip()
            if err:
                print(f"⛔ Generation failed: {err}")
                return None
            await asyncio.sleep(POLL_INTERVAL_SEC)

        # Final snapshot: timeout path may have landed on erro-captcha without token/err set.
        final = await page.evaluate(JS_TOKEN_SNAPSHOT)
        if isinstance(final, dict):
            href = final.get("href")
            if isinstance(href, str) and _is_erro_captcha_url(href):
                print(f"⛔ Receita erro-captcha redirect")
                return None
        print("⛔ Generation failed: token response timeout")
        return None
    except Exception as exc:
        print(f"⛔ Error: {exc}")
        return None
    finally:
        await browser.stop()
        await asyncio.sleep(0.2)


async def main() -> int:
    t0 = time.perf_counter()
    token = await generate_token()
    elapsed = time.perf_counter() - t0
    print(f"⏱️  Total time: {elapsed:.2f}s")
    if token:
        print("🔑 Token:")
        print(token)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
