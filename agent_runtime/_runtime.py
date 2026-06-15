from __future__ import annotations

import asyncio
import inspect
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from ._server import ToolServer
from ._types import FileInput, MissingAPIKeyError, RunError, TraceEvent


def _find_binary(explicit: str | None) -> str:
    if explicit:
        return explicit

    if env := os.environ.get("AGENT_RUNTIME_BIN"):
        return env

    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64"
    os_name = {"darwin": "darwin", "linux": "linux", "win32": "windows"}.get(sys.platform)
    if os_name:
        suffix = ".exe" if os_name == "windows" else ""
        bundled = Path(__file__).parent / "bin" / f"agent-runtime-{os_name}-{arch}{suffix}"
        if bundled.exists():
            if os_name != "windows" and not os.access(bundled, os.X_OK):
                bundled.chmod(0o755)
            return str(bundled)

    if found := shutil.which("agent-runtime"):
        return found

    raise FileNotFoundError(
        "agent-runtime binary not found. "
        "Build it with scripts/build_binaries.sh or set AGENT_RUNTIME_BIN."
    )


class Runtime:
    """Wraps the agent-runtime Go binary via subprocess.

    Usage::

        rt = Runtime()

        @rt.tool("my_ns.my_tool", version="v1")
        def my_tool(arg1: str) -> dict:
            return {"result": arg1.upper()}

        output = rt.run("./my_bundle.agent", inputs={"question": "hello"})
    """

    def __init__(
        self,
        binary: str | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self._binary = _find_binary(binary)
        self._env = env
        self._tools: dict[str, Callable] = {}

    def tool(self, name: str, version: str = "v1") -> Callable:
        """Decorator that registers a Python function as an agent tool."""
        ref = f"{name}@{version}"

        def decorator(fn: Callable) -> Callable:
            self._tools[ref] = fn
            return fn

        return decorator

    def validate(self, bundle: str) -> None:
        """Validate a bundle directory. Raises RuntimeError if invalid."""
        result = subprocess.run(
            [self._binary, "validate", bundle],
            capture_output=True,
            text=True,
            env=self._make_env(),
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    def run(
        self,
        bundle: str,
        inputs: dict[str, Any] | None = None,
        on_event: Callable[[TraceEvent], None] | None = None,
        start_at: str | None = None,
        stop_after: str | None = None,
        seed_outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a bundle synchronously and return the flow output."""
        server: ToolServer | None = None
        data_dir = tempfile.mkdtemp(prefix="agent-runtime-")
        run_id = str(uuid.uuid4())
        seed_file: str | None = None
        if seed_outputs:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as sf:
                json.dump({"seed_outputs": seed_outputs}, sf)
                seed_file = sf.name
        try:
            port = 0
            if self._tools:
                server = ToolServer(self._tools)
                server.start()
                port = server.port

            cmd = self._build_cmd(bundle, inputs or {}, data_dir, run_id, port, start_at=start_at, stop_after=stop_after, seed_file=seed_file)
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._make_env(),
            )
            if proc.stdout is None:
                raise RuntimeError("subprocess stdout pipe unexpectedly None")

            stderr_chunks: list[bytes] = []

            def _drain_stderr() -> None:
                if proc.stderr:
                    stderr_chunks.append(proc.stderr.read())

            drain_thread = threading.Thread(target=_drain_stderr, daemon=True)
            drain_thread.start()

            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = TraceEvent.from_json(line)
                except (json.JSONDecodeError, KeyError):
                    continue
                if on_event is not None:
                    on_event(event)

            proc.wait()
            drain_thread.join()
            stderr_bytes = stderr_chunks[0] if stderr_chunks else b""

            return self._read_result(data_dir, run_id, proc.returncode, stderr_bytes)
        finally:
            if server is not None:
                server.stop()
            shutil.rmtree(data_dir, ignore_errors=True)
            if seed_file:
                try:
                    os.unlink(seed_file)
                except OSError:
                    pass

    async def arun(
        self,
        bundle: str,
        inputs: dict[str, Any] | None = None,
        on_event: Callable[[TraceEvent], Any] | None = None,
        start_at: str | None = None,
        stop_after: str | None = None,
        seed_outputs: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run a bundle asynchronously and return the flow output."""
        server: ToolServer | None = None
        data_dir = tempfile.mkdtemp(prefix="agent-runtime-")
        run_id = str(uuid.uuid4())
        seed_file: str | None = None
        if seed_outputs:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as sf:
                json.dump({"seed_outputs": seed_outputs}, sf)
                seed_file = sf.name
        try:
            port = 0
            if self._tools:
                server = ToolServer(self._tools)
                server.start()
                port = server.port

            cmd = self._build_cmd(bundle, inputs or {}, data_dir, run_id, port, start_at=start_at, stop_after=stop_after, seed_file=seed_file)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._make_env(),
                limit=2**22,  # 4 MB — model responses can exceed the 64 KB default
            )
            if proc.stdout is None:
                raise RuntimeError("subprocess stdout pipe unexpectedly None")
            async for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    event = TraceEvent.from_json(line)
                except (json.JSONDecodeError, KeyError):
                    continue
                if on_event is not None:
                    if inspect.iscoroutinefunction(on_event):
                        await on_event(event)
                    else:
                        on_event(event)

            await proc.wait()
            stderr_bytes = await proc.stderr.read() if proc.stderr else b""

            return self._read_result(data_dir, run_id, proc.returncode, stderr_bytes)
        finally:
            if server is not None:
                server.stop()
            shutil.rmtree(data_dir, ignore_errors=True)
            if seed_file:
                try:
                    os.unlink(seed_file)
                except OSError:
                    pass

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_cmd(
        self,
        bundle: str,
        inputs: dict[str, Any],
        data_dir: str,
        run_id: str,
        tool_port: int,
        start_at: str | None = None,
        stop_after: str | None = None,
        seed_file: str | None = None,
    ) -> list[str]:
        cmd = [self._binary, "run", bundle, "--data-dir", data_dir, "--run-id", run_id]

        for key, value in inputs.items():
            if isinstance(value, FileInput):
                cmd += ["--input", f"{key}=@{value.path}"]
            elif isinstance(value, (dict, list, bool)):
                cmd += ["--input", f"{key}={json.dumps(value)}"]
            else:
                cmd += ["--input", f"{key}={value}"]

        for ref in self._tools:
            url = f"http://127.0.0.1:{tool_port}/tools/{ref}"
            cmd += ["--tool", f"{ref}={url}"]

        if start_at:
            cmd += ["--from", start_at]
        if stop_after:
            cmd += ["--to", stop_after]
        if seed_file:
            cmd += ["--seed", seed_file]

        return cmd

    def _read_result(
        self,
        data_dir: str,
        run_id: str,
        returncode: int | None,
        stderr_bytes: bytes = b"",
    ) -> dict[str, Any]:
        run_dir = Path(data_dir) / "runs" / run_id
        meta_path = run_dir / "meta.json"

        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == "error":
                raise RunError(meta.get("error", "unknown error"), run_id=run_id)
            output_path = run_dir / "output.json"
            if output_path.exists():
                return json.loads(output_path.read_text())
            return {}

        if returncode != 0:
            stderr_text = stderr_bytes.decode(errors="replace").strip()
            missing_keys = [
                line[len("missing-api-key: "):].strip()
                for line in stderr_text.splitlines()
                if line.startswith("missing-api-key: ")
            ]
            if missing_keys:
                raise MissingAPIKeyError(missing_keys, stderr_text)
            raise RuntimeError(
                f"agent-runtime exited with code {returncode}: {stderr_text}"
            )
        return {}

    def _make_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if self._env:
            env.update(self._env)
        return env
