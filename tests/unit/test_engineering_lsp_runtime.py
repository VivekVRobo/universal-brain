from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from universal_brain.engineering.lsp_runtime import StdioLspBackend
from universal_brain.engineering.semantic import LspRenamePlanner, LspSemanticProvider, SourcePosition


_FAKE_SERVER = r'''
import json, sys

def read_msg():
    headers = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in (b"\r\n", b"\n"):
            break
        k, v = line.decode("ascii").split(":", 1)
        headers[k.lower().strip()] = v.strip()
    n = int(headers["content-length"])
    return json.loads(sys.stdin.buffer.read(n).decode("utf-8"))

def write_msg(msg):
    body = json.dumps(msg, separators=(",", ":")).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    sys.stdout.buffer.flush()

opened = None
while True:
    msg = read_msg()
    if msg is None:
        break
    method = msg.get("method")
    rid = msg.get("id")
    if method == "initialize":
        write_msg({"jsonrpc":"2.0","id":rid,"result":{"capabilities":{"documentSymbolProvider":True,"renameProvider":True}}})
    elif method == "initialized":
        pass
    elif method == "textDocument/didOpen":
        opened = msg["params"]["textDocument"]["uri"]
    elif method == "textDocument/didChange":
        pass
    elif method == "textDocument/documentSymbol":
        write_msg({"jsonrpc":"2.0","id":rid,"result":[{
            "name":"TrajectoryPlanner","kind":5,
            "range":{"start":{"line":0,"character":0},"end":{"line":1,"character":8}},
            "selectionRange":{"start":{"line":0,"character":6},"end":{"line":0,"character":23}}
        }]})
    elif method == "textDocument/diagnostic":
        write_msg({"jsonrpc":"2.0","id":rid,"result":{"items":[]}})
    elif method == "textDocument/rename":
        uri = msg["params"]["textDocument"]["uri"]
        write_msg({"jsonrpc":"2.0","id":rid,"result":{"changes":{uri:[{
            "range":{"start":{"line":0,"character":6},"end":{"line":0,"character":23}},
            "newText":msg["params"]["newName"]
        }]}}})
    elif method == "shutdown":
        write_msg({"jsonrpc":"2.0","id":rid,"result":None})
    elif method == "exit":
        break
    elif rid is not None:
        write_msg({"jsonrpc":"2.0","id":rid,"result":[]})
'''


@pytest.mark.asyncio
async def test_real_stdio_lsp_runtime_initializes_opens_and_serves_semantic_requests(tmp_path: Path):
    server = tmp_path / "fake_lsp.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    source = tmp_path / "planner.py"
    source.write_text("class TrajectoryPlanner:\n    pass\n", encoding="utf-8")

    backend = StdioLspBackend(
        [sys.executable, str(server)],
        workspace_root=tmp_path,
        request_timeout_seconds=5,
    )
    await backend.start()
    try:
        uri = await backend.open_document(source, language_id="python")
        provider = LspSemanticProvider(backend, provider_id="fake-stdio")
        symbols = await provider.document_symbols(uri)
        assert [item.name for item in symbols] == ["TrajectoryPlanner"]
        assert await provider.diagnostics(uri) == []

        rename = await LspRenamePlanner(backend, [tmp_path]).plan(
            uri=uri,
            position=SourcePosition(line=0, character=8),
            symbol_name="TrajectoryPlanner",
            new_name="SafePlanner",
        )
        assert rename.edits[0].new_text == "SafePlanner"
        assert Path(rename.edits[0].uri.removeprefix("file://")).name == "planner.py"
    finally:
        await backend.close()

    assert not backend.running


@pytest.mark.asyncio
async def test_lsp_runtime_refuses_document_outside_workspace(tmp_path: Path):
    server = tmp_path / "fake_lsp.py"
    server.write_text(_FAKE_SERVER, encoding="utf-8")
    outside = tmp_path.parent / f"outside-{tmp_path.name}.py"
    outside.write_text("x=1\n", encoding="utf-8")
    backend = StdioLspBackend([sys.executable, str(server)], workspace_root=tmp_path)
    await backend.start()
    try:
        with pytest.raises(Exception):
            await backend.open_document(outside, language_id="python")
    finally:
        await backend.close(force=True)
        outside.unlink(missing_ok=True)
