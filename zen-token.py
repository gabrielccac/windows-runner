#!/usr/bin/env python3
"""
Token generation with Zendriver.

Install:
  pip install zendriver
"""
import asyncio
import os
import zendriver as zd


URL = "https://servicos.receitafederal.gov.br/servico/certidoes/#/home/cpf"

HEADLESS = os.environ.get("HEADLESS", "false").lower() in ("1", "true", "yes")

# Extra Chrome flags for faster startup on Windows CI runners.
_CI_BROWSER_ARGS = [
    "--disable-extensions",   # slightly faster startup
    "--no-first-run",         # skip first-run setup
    "--mute-audio",           # no audio subsystem needed
]

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
        disable_webgl=True,
        disable_webrtc=True,
        browser_args=_CI_BROWSER_ARGS,
    )
    page = await browser.get(URL)
    print("⚒️  Page opened")

    try:
        # Invisible hCaptcha iframe may be hidden, so only require DOM presence.
        for _ in range(60):
            widget_present = await page.evaluate(
                "document.querySelector('[data-hcaptcha-widget-id]') !== null"
            )
            ready = await page.evaluate("typeof hcaptcha !== 'undefined'")
            if widget_present and ready:
                break
            await asyncio.sleep(0.5)
        else:
            print("⛔ hCaptcha timed out")
            return None

        print("🔎 hCaptcha widget found")
        print("🔑 hCaptcha ready, executing...")
        await page.evaluate(JS_START_TOKEN_EXECUTION)

        for _ in range(30):
            token = await page.evaluate("window.__zd_hcaptcha_token")
            if isinstance(token, str) and token.strip():
                print("🔑 Token generated")
                return token.strip()
            err = await page.evaluate("window.__zd_hcaptcha_error")
            if err:
                print(f"⛔ Generation failed: {err}")
                return None
            await asyncio.sleep(0.5)

        print("⛔ Generation failed: token response timeout")
        return None
    except Exception as exc:
        print(f"⛔ Error: {exc}")
        return None
    finally:
        await browser.stop()
        await asyncio.sleep(0.2)


async def main() -> int:
    token = await generate_token()
    if token:
        print(f"✅ Token: {token}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
