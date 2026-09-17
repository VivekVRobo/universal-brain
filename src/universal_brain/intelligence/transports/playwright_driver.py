"""Generic authorized chat-UI driver.

No stealth, CAPTCHA/MFA bypass, credential automation, or rate-limit evasion. The
operator owns the authenticated browser profile. Selectors and permitted upload
roots are configuration, not hard-coded provider assumptions.
"""
from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from urllib.parse import urlparse

from .base import TransportAuthError, TransportOutageError, TransportTimeoutError
from .browser import BrowserModelDriver
from ..schemas import ModelUsage, NormalizedModelResult


class PlaywrightChatUIDriver(BrowserModelDriver):
    def __init__(self):
        self._pw = None
        self._ctx = None
        self._page = None
        self._profile = None

    @staticmethod
    def _values(route, singular: str, plural: str) -> list[str]:
        values = route.config.get(plural)
        if isinstance(values, list):
            return [str(value) for value in values if str(value).strip()]
        single = route.config.get(singular)
        return [str(single)] if single else []

    def _required(self, route, key):
        value = route.config.get(key)
        if not value:
            raise TransportOutageError(
                f"Browser route {route.route_id} requires config['{key}']"
            )
        return str(value)

    @staticmethod
    def _same_origin(left: str, right: str) -> bool:
        a, b = urlparse(left), urlparse(right)
        return (a.scheme, a.netloc) == (b.scheme, b.netloc)

    async def _ensure(self, route, url=None):
        profile = self._required(route, "user_data_dir")
        target = self._required(route, "target_url")
        navigation = url or target
        if url and not self._same_origin(target, str(url)):
            raise TransportOutageError("conversation URL origin mismatch")
        if self._ctx is None:
            try:
                from playwright.async_api import async_playwright
            except ImportError as exc:
                raise TransportOutageError("Install optional dependency 'playwright'") from exc
            Path(profile).expanduser().mkdir(parents=True, exist_ok=True)
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(Path(profile).expanduser()),
                headless=bool(route.config.get("headless", False)),
            )
            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            self._profile = profile
        if self._page.url != navigation:
            await self._page.goto(
                navigation,
                wait_until="domcontentloaded",
                timeout=int(route.config.get("navigation_timeout_ms", 60_000)),
            )
        return self._page

    async def _first_locator(self, page, selectors: list[str], *, required: bool = True):
        for selector in selectors:
            locator = page.locator(selector)
            try:
                count = await locator.count()
            except Exception:
                continue
            if count > 0:
                return locator.last
        if required:
            raise TransportOutageError(
                "No configured selector matched the current authorized chat UI"
            )
        return None

    async def is_authenticated(self, route):
        page = await self._ensure(route)
        current_url = page.url.lower()
        if any(
            str(fragment).lower() in current_url
            for fragment in route.config.get("login_url_fragments", [])
        ):
            return False
        auth_selectors = self._values(
            route, "auth_required_selector", "auth_required_selectors"
        )
        for selector in auth_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    return False
            except Exception:
                continue
        return True

    def _validate_attachments(self, route, request) -> list[str]:
        raw = request.metadata.get("attachment_paths") or []
        if isinstance(raw, str):
            raw = [raw]
        if not raw:
            return []
        roots = [
            Path(value).expanduser().resolve()
            for value in route.config.get("allowed_upload_roots", [])
        ]
        if not roots:
            raise TransportOutageError(
                "Browser attachments require explicit allowed_upload_roots"
            )
        resolved: list[str] = []
        for item in raw:
            path = Path(str(item)).expanduser().resolve()
            if not path.is_file():
                raise TransportOutageError(f"Attachment does not exist: {path}")
            if not any(path == root or root in path.parents for root in roots):
                raise TransportOutageError(
                    f"Attachment path is outside authorized upload roots: {path}"
                )
            resolved.append(str(path))
        return resolved

    async def _upload_attachments(self, page, route, request) -> None:
        attachments = self._validate_attachments(route, request)
        if not attachments:
            return
        selectors = self._values(
            route, "attachment_input_selector", "attachment_input_selectors"
        )
        if not selectors:
            raise TransportOutageError(
                "attachment_input_selector(s) required when attachments are requested"
            )
        locator = await self._first_locator(page, selectors)
        await locator.set_input_files(attachments)
        await asyncio.sleep(float(route.config.get("attachment_settle_seconds", 0.75)))

    async def submit(self, model, route, request):
        conversation_ref = request.metadata.get("conversation_ref")
        page = await self._ensure(route, str(conversation_ref) if conversation_ref else None)
        if not await self.is_authenticated(route):
            raise TransportAuthError("operator login/2FA refresh required")

        await self._upload_attachments(page, route, request)
        prompt = "\n\n".join(
            f"[{message.role.upper()}]\n{message.content}" for message in request.messages
        )
        prompt_selectors = self._values(route, "prompt_selector", "prompt_selectors")
        response_selectors = self._values(route, "response_selector", "response_selectors")
        if not prompt_selectors:
            raise TransportOutageError("prompt_selector(s) not configured")
        if not response_selectors:
            raise TransportOutageError("response_selector(s) not configured")

        # Count on the matched selector, not on a parent. We re-resolve during polling
        # because chat UIs frequently replace response nodes while streaming.
        matched_response_selector = None
        before_count = 0
        for selector in response_selectors:
            count = await page.locator(selector).count()
            if count > 0:
                matched_response_selector = selector
                before_count = count
                break
        if matched_response_selector is None:
            # Empty new conversation UIs may have no response node yet. Use the first
            # configured selector and wait for the first node to appear.
            matched_response_selector = response_selectors[0]
            before_count = 0

        box = await self._first_locator(page, prompt_selectors)
        await box.click()
        try:
            await box.fill(prompt)
        except Exception:
            await page.keyboard.insert_text(prompt)

        submit_selectors = self._values(route, "submit_selector", "submit_selectors")
        submit = await self._first_locator(page, submit_selectors, required=False)
        if submit is not None:
            await submit.click()
        else:
            await box.press("Enter")

        deadline = (
            asyncio.get_running_loop().time()
            + int(route.config.get("response_timeout_ms", 180_000)) / 1000
        )
        stable = ""
        stable_polls = 0
        required_stable_polls = max(int(route.config.get("stable_polls", 3)), 1)
        poll_seconds = max(float(route.config.get("poll_seconds", 0.75)), 0.1)
        while asyncio.get_running_loop().time() < deadline:
            locator = page.locator(matched_response_selector)
            count = await locator.count()
            text = (
                (await locator.nth(count - 1).inner_text()).strip()
                if count > before_count or (before_count > 0 and count >= before_count)
                else ""
            )
            if text and text == stable:
                stable_polls += 1
            else:
                stable = text
                stable_polls = 0
            if stable and stable_polls >= required_stable_polls:
                break
            await asyncio.sleep(poll_seconds)
        if not stable:
            raise TransportTimeoutError("browser response did not stabilize")

        root = Path(
            str(route.config.get("artifact_dir", ".universal_brain/evidence/browser"))
        )
        directory = root / route.route_id / str(request.request_id)
        directory.mkdir(parents=True, exist_ok=True)
        screenshot = directory / "final.png"
        await page.screenshot(path=str(screenshot), full_page=True)
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text=stable,
            conversation_ref=page.url,
            usage=ModelUsage(),
            evidence={
                "session_artifact": str(screenshot),
                "response_sha256": hashlib.sha256(stable.encode()).hexdigest(),
                "source_url": page.url,
            },
            raw_metadata={
                "usage_unavailable": True,
                "driver": "playwright_chat_ui",
                "attachments_uploaded": len(self._validate_attachments(route, request)),
            },
        )

    async def recover_session(self, route, conversation_ref=None):
        target = self._required(route, "target_url")
        navigation = str(conversation_ref) if conversation_ref else target
        page = await self._ensure(route, navigation)
        if not await self.is_authenticated(route):
            raise TransportAuthError("operator login/2FA refresh required")
        missing_selectors = self._values(
            route, "conversation_missing_selector", "conversation_missing_selectors"
        )
        missing = False
        for selector in missing_selectors:
            try:
                if await page.locator(selector).count() > 0:
                    missing = True
                    break
            except Exception:
                continue
        if missing:
            page = await self._ensure(route, target)
        return page.url

    async def close(self):
        if self._ctx is not None:
            await self._ctx.close()
        if self._pw is not None:
            await self._pw.stop()
        self._ctx = None
        self._page = None
        self._pw = None
        self._profile = None
