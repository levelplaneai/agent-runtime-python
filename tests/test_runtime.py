"""Integration tests for Runtime.

These tests require the agent-runtime binary to be built and available.
Run `scripts/build_binaries.sh` or set AGENT_RUNTIME_BIN before running.

Tests that need the binary are skipped automatically if it is not found.
"""
import asyncio
import shutil
import sys
from pathlib import Path

import pytest

from agent_runtime import FileInput, MissingAPIKeyError, Runtime, TraceEvent
from agent_runtime._runtime import _find_binary

BUNDLE_ROOT = Path(__file__).parent.parent.parent / "agent-runtime" / "testdata"
HAIKU_BUNDLE = BUNDLE_ROOT / "haiku_maker.agent"
RFQ_BUNDLE = BUNDLE_ROOT / "rfq_processor.agent"

# Skip integration tests when binary not available
try:
    _BINARY = _find_binary(None)
    HAS_BINARY = True
except FileNotFoundError:
    HAS_BINARY = False

needs_binary = pytest.mark.skipif(not HAS_BINARY, reason="agent-runtime binary not found")
needs_bundles = pytest.mark.skipif(
    not BUNDLE_ROOT.exists(), reason="testdata bundles not found"
)


# ---------------------------------------------------------------------------
# Unit tests (no binary required)
# ---------------------------------------------------------------------------

class TestFindBinary:
    def test_explicit_path_returned_as_is(self, tmp_path):
        fake = tmp_path / "agent-runtime"
        fake.touch()
        assert _find_binary(str(fake)) == str(fake)

    def test_env_var_takes_precedence(self, tmp_path, monkeypatch):
        fake = tmp_path / "agent-runtime"
        fake.touch()
        monkeypatch.setenv("AGENT_RUNTIME_BIN", str(fake))
        assert _find_binary(None) == str(fake)

    def test_raises_when_not_found(self, monkeypatch):
        monkeypatch.delenv("AGENT_RUNTIME_BIN", raising=False)
        monkeypatch.setattr(shutil, "which", lambda _: None)
        # Use an unsupported platform so the bundled-binary lookup is skipped
        monkeypatch.setattr(sys, "platform", "unsupported_os")
        with pytest.raises(FileNotFoundError):
            _find_binary(None)


class TestBuildCmd:
    def setup_method(self):
        self.rt = Runtime.__new__(Runtime)
        self.rt._binary = "/usr/local/bin/agent-runtime"
        self.rt._tools = {}
        self.rt._env = None

    def test_basic_cmd(self):
        cmd = self.rt._build_cmd("./bundle", {}, "/tmp/data", "run-123", 0)
        assert cmd[:3] == ["/usr/local/bin/agent-runtime", "run", "./bundle"]
        assert "--data-dir" in cmd
        assert "--run-id" in cmd

    def test_string_inputs(self):
        cmd = self.rt._build_cmd("./bundle", {"key": "value"}, "/tmp/data", "id", 0)
        assert "--input" in cmd
        idx = cmd.index("--input")
        assert cmd[idx + 1] == "key=value"

    def test_file_input(self, tmp_path):
        f = tmp_path / "doc.pdf"
        f.write_bytes(b"pdf")
        cmd = self.rt._build_cmd("./bundle", {"doc": FileInput(f)}, "/tmp/data", "id", 0)
        input_args = [cmd[i + 1] for i, v in enumerate(cmd) if v == "--input"]
        assert any(a.startswith("doc=@") for a in input_args)

    def test_tool_flags(self):
        self.rt._tools = {"my_ns.my_tool@v1": lambda: {}}
        cmd = self.rt._build_cmd("./bundle", {}, "/tmp/data", "id", 9999)
        assert "--tool" in cmd
        idx = cmd.index("--tool")
        assert "my_ns.my_tool@v1=http://127.0.0.1:9999/tools/my_ns.my_tool@v1" == cmd[idx + 1]


class TestReadResult:
    def setup_method(self):
        self.rt = Runtime.__new__(Runtime)
        self.rt._binary = "/usr/local/bin/agent-runtime"
        self.rt._tools = {}
        self.rt._env = None

    def test_missing_api_key_raises_MissingAPIKeyError(self, tmp_path):
        stderr = (
            b"error: missing API key(s) required to run bundle \"haiku_maker\"\n\n"
            b"  ANTHROPIC_API_KEY\n"
            b"    models : anthropic/claude-haiku-4-5-20251001\n"
            b"    nodes  : make_haiku, critique_haiku\n"
            b"    fix    : export ANTHROPIC_API_KEY=<your-key>\n\n"
            b"missing-api-key: ANTHROPIC_API_KEY\n"
        )
        with pytest.raises(MissingAPIKeyError) as exc_info:
            self.rt._read_result(str(tmp_path), "run-1", 1, stderr)
        assert exc_info.value.missing_keys == ["ANTHROPIC_API_KEY"]

    def test_multiple_missing_keys_parsed(self, tmp_path):
        stderr = (
            b"missing-api-key: ANTHROPIC_API_KEY\n"
            b"missing-api-key: OPENAI_API_KEY\n"
        )
        with pytest.raises(MissingAPIKeyError) as exc_info:
            self.rt._read_result(str(tmp_path), "run-1", 1, stderr)
        assert sorted(exc_info.value.missing_keys) == ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"]

    def test_non_key_error_raises_RuntimeError(self, tmp_path):
        stderr = b"error: bundle not found\n"
        with pytest.raises(RuntimeError) as exc_info:
            self.rt._read_result(str(tmp_path), "run-1", 1, stderr)
        assert not isinstance(exc_info.value, MissingAPIKeyError)
        assert "bundle not found" in str(exc_info.value)


class TestTraceEvent:
    def test_from_json(self):
        line = '{"event":"node_done","node":"make_haiku","type":"prompt","duration_ms":1234,"ts":1234567890}'
        ev = TraceEvent.from_json(line)
        assert ev.event == "node_done"
        assert ev.node == "make_haiku"
        assert ev.duration_ms == 1234

    def test_missing_optional_fields_default(self):
        ev = TraceEvent.from_json('{"event":"flow_start","ts":0}')
        assert ev.flow == ""
        assert ev.input_tokens == 0


# ---------------------------------------------------------------------------
# Integration tests (binary + bundles required)
# ---------------------------------------------------------------------------

@needs_binary
@needs_bundles
class TestValidate:
    def test_valid_bundle(self):
        rt = Runtime()
        rt.validate(str(HAIKU_BUNDLE))  # should not raise

    def test_invalid_path_raises(self):
        rt = Runtime()
        with pytest.raises(RuntimeError):
            rt.validate("/nonexistent/bundle.agent")


@needs_binary
@needs_bundles
class TestRun:
    def test_haiku_maker_returns_output(self):
        rt = Runtime()
        result = rt.run(str(HAIKU_BUNDLE), inputs={"topic": "autumn"})
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_trace_events_delivered(self):
        rt = Runtime()
        events: list[TraceEvent] = []
        rt.run(str(HAIKU_BUNDLE), inputs={"topic": "spring"}, on_event=events.append)
        event_names = {e.event for e in events}
        assert "flow_start" in event_names
        assert "flow_done" in event_names

    def test_rfq_with_python_tool(self):
        rt = Runtime()
        call_log: list[dict] = []

        @rt.tool("supplier_api.get_price", version="v1")
        def get_price(**kwargs) -> dict:
            call_log.append(kwargs)
            return {"unit_price": 10.0, "currency": "USD", "lead_time_days": 5}

        result = rt.run(
            str(RFQ_BUNDLE),
            inputs={"rfq_document": "Please quote 10 units of widget ABC-123"},
        )
        assert isinstance(result, dict)
        assert len(call_log) > 0


@needs_binary
@needs_bundles
class TestArun:
    def test_arun_returns_same_as_run(self):
        rt = Runtime()

        async def go():
            return await rt.arun(str(HAIKU_BUNDLE), inputs={"topic": "winter"})

        result = asyncio.run(go())
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_arun_with_async_on_event(self):
        rt = Runtime()
        events: list[TraceEvent] = []

        async def collect(ev: TraceEvent) -> None:
            events.append(ev)

        async def go():
            return await rt.arun(
                str(HAIKU_BUNDLE), inputs={"topic": "ocean"}, on_event=collect
            )

        asyncio.run(go())
        assert any(e.event == "flow_done" for e in events)
