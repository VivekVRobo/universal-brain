"""Authority-neutral stdio Language Server Protocol runtime for V5.2.

Traceability: REQ-ENG-021, REQ-ENG-022, REQ-ENG-023, REQ-ENG-033,
ALN-007, ALN-012, ALN-020.

This client owns only the lifecycle of an already operator-authorized language
server process. It never writes source files and it never applies WorkspaceEdits.
All refactor application remains behind ToolGateway.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from universal_brain.tools.runner.policies import EnvironmentSanitizer
from universal_brain.tools.sandbox.confinement import confine_path

from .semantic import SemanticBackendUnavailable


class LspProtocolError(RuntimeError):
    """Raised when the language server violates the expected JSON-RPC framing."""


class StdioLspBackend:
    """Small standard-LSP JSON-RPC client over stdio.

    The implementation intentionally serializes requests. That is sufficient for
    deterministic engineering sensing and keeps recovery/error behavior easy to
    audit. Server-to-client requests are answered conservatively so common language
    servers can initialize without granting them host authority.
    """

    def __init__(
        self,
        command: list[str],
        *,
        workspace_root: Path,
        root_uri: str | None = None,
        initialization_options: dict[str, Any] | None = None,
        environment_overrides: dict[str, str] | None = None,
        request_timeout_seconds: float = 30.0,
    ) -> None:
        if not command or not command[0].strip():
            raise ValueError("language-server command is required")
        self.command = list(command)
        self.workspace_root = workspace_root.resolve()
        self.root_uri = root_uri or self.workspace_root.as_uri()
        self.initialization_options = dict(initialization_options or {})
        self.environment_overrides = dict(environment_overrides or {})
        self.request_timeout_seconds = max(1.0, float(request_timeout_seconds))
        self._process: asyncio.subprocess.Process | None = None
        self._next_id = 1
        self._request_lock = asyncio.Lock()
        self._opened_versions: dict[str, int] = {}
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def stderr_tail(self) -> str:
        return "".join(self._stderr_tail[-100:])[-12000:]

    async def start(self) -> None:
        if self.running:
            return
        clean_env = EnvironmentSanitizer.sanitize_environment(
            base_env=dict(os.environ), overrides=self.environment_overrides
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self.command,
                cwd=str(self.workspace_root),
                env=clean_env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=(os.name != "nt"),
            )
        except (OSError, ValueError) as exc:
            self._process = None
            raise SemanticBackendUnavailable(
                f"Unable to launch language server {self.command[0]!r}: {exc}"
            ) from exc

        self._stderr_task = asyncio.create_task(self._drain_stderr())
        try:
            await self.request(
                "initialize",
                {
                    "processId": os.getpid(),
                    "clientInfo": {"name": "Universal Brain", "version": "5.2"},
                    "rootUri": self.root_uri,
                    "capabilities": {
                        "textDocument": {
                            "documentSymbol": {},
                            "references": {},
                            "rename": {"prepareSupport": False},
                            "diagnostic": {},
                        },
                        "workspace": {"symbol": {}},
                    },
                    "initializationOptions": self.initialization_options,
                },
            )
            await self.notify("initialized", {})
        except Exception:
            await self.close(force=True)
            raise

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        if not self.running:
            if method == "initialize" and self._process is not None:
                # create_subprocess_exec succeeded, but returncode may have been
                # populated immediately. Surface stderr with a useful error.
                if self._process.returncode is not None:
                    raise SemanticBackendUnavailable(
                        f"language server exited during startup: {self.stderr_tail}"
                    )
            elif self._process is None:
                await self.start()
        assert self._process is not None
        async with self._request_lock:
            request_id = self._next_id
            self._next_id += 1
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            deadline = asyncio.get_running_loop().time() + self.request_timeout_seconds
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError(f"LSP request timed out: {method}")
                message = await asyncio.wait_for(self._read_message(), timeout=remaining)
                if message.get("id") == request_id and "method" not in message:
                    if message.get("error") is not None:
                        error = message["error"]
                        raise LspProtocolError(f"LSP {method} error: {error}")
                    return message.get("result")
                if "method" in message and "id" in message:
                    await self._handle_server_request(message)
                # Notifications and responses for unknown IDs are ignored; this
                # single-flight client never intentionally has another request
                # outstanding.

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if not self.running:
            await self.start()
        await self._write_message({"jsonrpc": "2.0", "method": method, "params": params})

    async def open_document(
        self,
        path: Path,
        *,
        language_id: str,
        version: int = 1,
    ) -> str:
        confined = confine_path(path.resolve(), self.workspace_root)
        text = confined.read_text(encoding="utf-8")
        uri = confined.as_uri()
        await self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": language_id,
                    "version": version,
                    "text": text,
                }
            },
        )
        self._opened_versions[uri] = version
        return uri

    async def change_document(self, path: Path, *, version: int | None = None) -> int:
        confined = confine_path(path.resolve(), self.workspace_root)
        uri = confined.as_uri()
        current = self._opened_versions.get(uri)
        if current is None:
            raise ValueError("document must be opened before change_document")
        next_version = version if version is not None else current + 1
        if next_version <= current:
            raise ValueError("LSP document versions must increase monotonically")
        await self.notify(
            "textDocument/didChange",
            {
                "textDocument": {"uri": uri, "version": next_version},
                "contentChanges": [{"text": confined.read_text(encoding="utf-8")}],
            },
        )
        self._opened_versions[uri] = next_version
        return next_version

    async def close_document(self, path: Path) -> None:
        confined = confine_path(path.resolve(), self.workspace_root)
        uri = confined.as_uri()
        if uri in self._opened_versions:
            await self.notify("textDocument/didClose", {"textDocument": {"uri": uri}})
            self._opened_versions.pop(uri, None)

    async def close(self, *, force: bool = False) -> None:
        process = self._process
        if process is None:
            return
        if not force and process.returncode is None:
            try:
                await self.request("shutdown", {})
                await self._write_message({"jsonrpc": "2.0", "method": "exit", "params": {}})
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except Exception:
                force = True
        if force and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        if self._stderr_task is not None:
            if not self._stderr_task.done():
                self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._process = None
        self._stderr_task = None
        self._opened_versions.clear()

    async def __aenter__(self) -> "StdioLspBackend":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close(force=exc is not None)

    async def _write_message(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.stdin is None or process.returncode is not None:
            raise SemanticBackendUnavailable("language server process is not running")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        process.stdin.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
        await process.stdin.drain()

    async def _read_message(self) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdout is None:
            raise SemanticBackendUnavailable("language server stdout is unavailable")
        headers: dict[str, str] = {}
        while True:
            line = await process.stdout.readline()
            if not line:
                raise SemanticBackendUnavailable(
                    f"language server closed stdout unexpectedly: {self.stderr_tail}"
                )
            if line in (b"\r\n", b"\n"):
                break
            try:
                key, value = line.decode("ascii").split(":", 1)
            except ValueError as exc:
                raise LspProtocolError(f"Malformed LSP header: {line!r}") from exc
            headers[key.strip().lower()] = value.strip()
        try:
            content_length = int(headers["content-length"])
        except (KeyError, ValueError) as exc:
            raise LspProtocolError("LSP message missing valid Content-Length") from exc
        body = await process.stdout.readexactly(content_length)
        try:
            message = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise LspProtocolError("LSP response body is not valid UTF-8 JSON") from exc
        if not isinstance(message, dict):
            raise LspProtocolError("LSP response must be a JSON object")
        return message

    async def _handle_server_request(self, message: dict[str, Any]) -> None:
        method = str(message.get("method", ""))
        request_id = message.get("id")
        if method == "workspace/configuration":
            items = (message.get("params") or {}).get("items") or []
            result: Any = [{} for _ in items]
        elif method in {"window/workDoneProgress/create", "client/registerCapability", "client/unregisterCapability"}:
            result = None
        elif method == "workspace/workspaceFolders":
            result = [{"uri": self.root_uri, "name": self.workspace_root.name}]
        else:
            # Conservatively answer unsupported server requests with JSON-RPC
            # method-not-found rather than giving the language server any host action.
            await self._write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Client method not supported: {method}"},
                }
            )
            return
        await self._write_message({"jsonrpc": "2.0", "id": request_id, "result": result})

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            self._stderr_tail.append(line.decode("utf-8", errors="replace"))
            if len(self._stderr_tail) > 200:
                del self._stderr_tail[:50]
