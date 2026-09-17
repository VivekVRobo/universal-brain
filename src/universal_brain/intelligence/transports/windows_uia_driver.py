"""Authorized Windows UI Automation chat driver.

This adapter uses the Windows accessibility/UIA tree through pywinauto. It does not
inject credentials, bypass login/MFA, hide automation, or defeat application limits.
The target application must already be installed, running, and authorized by the
operator.
"""
from __future__ import annotations

import asyncio
import hashlib
import platform
from pathlib import Path
from typing import Any

from .base import TransportOutageError, TransportTimeoutError
from .desktop import DesktopModelDriver
from ..schemas import ModelUsage, NormalizedModelResult


class WindowsUIAChatDriver(DesktopModelDriver):
    def __init__(self, *, backend_factory=None) -> None:
        self.backend_factory = backend_factory
        self._application = None
        self._window = None

    def _build_application(self):
        if self.backend_factory is not None:
            return self.backend_factory()
        if platform.system().lower() != "windows":
            raise TransportOutageError("Windows UIA transport requires Windows")
        try:
            from pywinauto import Application
        except ImportError as exc:
            raise TransportOutageError(
                "Install optional desktop dependency 'pywinauto'"
            ) from exc
        return Application(backend="uia")

    @staticmethod
    def _window_kwargs(route) -> dict[str, Any]:
        if route.config.get("title_re"):
            return {"title_re": str(route.config["title_re"])}
        if route.config.get("title"):
            return {"title": str(route.config["title"])}
        raise TransportOutageError("Desktop route requires title or title_re")

    def _connect_sync(self, route):
        app = self._application or self._build_application()
        connect_kwargs: dict[str, Any] = {}
        if route.config.get("process_id"):
            connect_kwargs["process"] = int(route.config["process_id"])
        elif route.config.get("executable_path"):
            connect_kwargs["path"] = str(route.config["executable_path"])
        else:
            connect_kwargs.update(self._window_kwargs(route))
        app.connect(timeout=float(route.config.get("connect_timeout_seconds", 5)), **connect_kwargs)
        window = app.window(**self._window_kwargs(route))
        window.wait("exists ready", timeout=float(route.config.get("window_timeout_seconds", 10)))
        self._application = app
        self._window = window
        return window

    @staticmethod
    def _control(window, route, prefix: str, *, required: bool = True):
        kwargs: dict[str, Any] = {}
        mapping = {
            "auto_id": f"{prefix}_auto_id",
            "title": f"{prefix}_title",
            "title_re": f"{prefix}_title_re",
            "control_type": f"{prefix}_control_type",
        }
        for field, config_key in mapping.items():
            value = route.config.get(config_key)
            if value:
                kwargs[field] = str(value)
        if not kwargs:
            if required:
                raise TransportOutageError(
                    f"Desktop route requires at least one {prefix}_* UIA selector"
                )
            return None
        return window.child_window(**kwargs)

    async def is_available(self, route):
        try:
            await asyncio.to_thread(self._connect_sync, route)
            return True
        except Exception:
            return False

    def _read_text_sync(self, control) -> str:
        try:
            text = control.window_text()
            if text:
                return str(text).strip()
        except Exception:
            pass
        try:
            texts = control.texts()
            return "\n".join(str(item) for item in texts if str(item).strip()).strip()
        except Exception:
            return ""

    def _set_prompt_sync(self, control, prompt: str) -> None:
        control.wait("exists enabled visible", timeout=10)
        try:
            control.set_edit_text(prompt)
            return
        except Exception:
            pass
        control.click_input()
        try:
            control.type_keys("^a{BACKSPACE}", set_foreground=False)
        except Exception:
            pass
        control.type_keys(prompt, with_spaces=True, set_foreground=False)

    def _submit_sync(self, window, route, prompt_control) -> None:
        submit = self._control(window, route, "submit", required=False)
        if submit is not None:
            submit.wait("exists enabled visible", timeout=10)
            submit.click_input()
        else:
            prompt_control.type_keys("{ENTER}", set_foreground=False)

    def _capture_sync(self, window, path: Path) -> bool:
        try:
            image = window.capture_as_image()
            image.save(str(path))
            return True
        except Exception:
            return False

    async def submit(self, model, route, request):
        window = await asyncio.to_thread(self._connect_sync, route)
        prompt_control = self._control(window, route, "prompt")
        response_control = self._control(window, route, "response")
        prompt = "\n\n".join(
            f"[{message.role.upper()}]\n{message.content}" for message in request.messages
        )
        before = await asyncio.to_thread(self._read_text_sync, response_control)
        await asyncio.to_thread(self._set_prompt_sync, prompt_control, prompt)
        await asyncio.to_thread(self._submit_sync, window, route, prompt_control)

        deadline = (
            asyncio.get_running_loop().time()
            + float(route.config.get("response_timeout_seconds", 180))
        )
        stable = ""
        stable_polls = 0
        required_stable = max(int(route.config.get("stable_polls", 3)), 1)
        poll_seconds = max(float(route.config.get("poll_seconds", 0.75)), 0.1)
        while asyncio.get_running_loop().time() < deadline:
            text = await asyncio.to_thread(self._read_text_sync, response_control)
            candidate = text.strip()
            if candidate and candidate != before and candidate == stable:
                stable_polls += 1
            elif candidate and candidate != before:
                stable = candidate
                stable_polls = 0
            if stable and stable_polls >= required_stable:
                break
            await asyncio.sleep(poll_seconds)
        if not stable:
            raise TransportTimeoutError("desktop UI response did not stabilize")

        root = Path(
            str(route.config.get("artifact_dir", ".universal_brain/evidence/desktop"))
        )
        directory = root / route.route_id / str(request.request_id)
        directory.mkdir(parents=True, exist_ok=True)
        screenshot = directory / "final.png"
        captured = await asyncio.to_thread(self._capture_sync, window, screenshot)
        evidence = {
            "response_sha256": hashlib.sha256(stable.encode()).hexdigest(),
            "window_title": str(route.config.get("title") or route.config.get("title_re") or ""),
        }
        if captured:
            evidence["session_artifact"] = str(screenshot)
        return NormalizedModelResult(
            request_id=request.request_id,
            model_key=model.model_key,
            route_id=route.route_id,
            output_text=stable,
            usage=ModelUsage(),
            evidence=evidence,
            raw_metadata={"usage_unavailable": True, "driver": "windows_uia_chat"},
        )

    async def recover_session(self, route, conversation_ref=None):
        if not await self.is_available(route):
            raise TransportOutageError(f"Desktop route {route.route_id} unavailable")
        return conversation_ref

    async def close(self):
        self._application = None
        self._window = None
