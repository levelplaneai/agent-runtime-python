# agent-runtime-sdk

Python SDK for running [agent-runtime](https://github.com/levelplaneai/agent-runtime) workflows. Wraps the agent-runtime binary to execute declarative `.agent` bundles from Python, with support for registering Python functions as callable tools.

## Installation

```bash
pip install agent-runtime-sdk
# or
uv add agent-runtime-sdk
```

The package ships pre-built binaries for macOS (arm64, amd64), Linux (amd64, arm64), and Windows (amd64) — no separate install required.

## Quick Start

```python
from agent_runtime import Runtime, RunError

rt = Runtime()

@rt.tool("pricing.get_quote", version="v1")
def get_quote(sku: str, quantity: int) -> dict:
    return {"unit_price": 9.99, "currency": "USD"}

try:
    output = rt.run("./my_bundle.agent", inputs={"sku": "ABC-1", "quantity": 10})
    print(output)
except RunError as e:
    print(f"Flow failed: {e} (run_id={e.run_id})")
```

## Authoring Bundles

Bundles are directories with a `.agent` extension containing a declarative flow definition. See [FLOWS.md](https://github.com/levelplaneai/agent-runtime/blob/main/FLOWS.md) in the main repo for the full authoring guide.

## API Reference

### `Runtime(binary=None, env=None)`

Creates a runtime instance.

- `binary` — explicit path to the `agent-runtime` binary (optional)
- `env` — extra environment variables merged into the subprocess environment

### `@rt.tool(name, version="v1")`

Decorator that registers a Python function as a tool callable by the workflow. The tool reference inside the bundle must match `name@version`.

```python
@rt.tool("supplier_api.get_price", version="v1")
def get_price(item_code: str) -> dict:
    return {"price": 42.0}

# Async tools are also supported
@rt.tool("data.fetch_record", version="v1")
async def fetch_record(record_id: str) -> dict:
    ...
```

### `rt.run(bundle, inputs=None, on_event=None) -> dict`

Executes a bundle synchronously and returns the flow output as a dict.

### `rt.arun(bundle, inputs=None, on_event=None) -> dict`

Async version of `run`. Use with `await` inside an async context.

```python
result = await rt.arun("./bundle.agent", inputs={"query": "hello"})
```

### `rt.validate(bundle)`

Validates a bundle directory. Raises `RuntimeError` if the bundle is invalid.

## File Inputs

Use `FileInput` to pass a local file as a flow input. The path is resolved to an absolute path automatically.

```python
from agent_runtime import Runtime, FileInput

rt = Runtime()
output = rt.run("./ocr_bundle.agent", inputs={"document": FileInput("./invoice.pdf")})
```

## Streaming Events

Pass an `on_event` callback to receive `TraceEvent` objects as the workflow executes.

```python
def on_event(event: TraceEvent) -> None:
    print(f"[{event.event}] node={event.node} duration={event.duration_ms}ms")

rt.run("./bundle.agent", inputs={...}, on_event=on_event)
```

Key `TraceEvent` fields:

| Field | Type | Description |
|---|---|---|
| `event` | `str` | Event type (e.g. `node.start`, `node.done`, `tool.call`) |
| `node` | `str` | Node name in the flow |
| `node_type` | `str` | Node type (e.g. `llm`, `tool`, `router`) |
| `tool` | `str` | Tool reference if a tool was called |
| `model` | `str` | Model name for LLM nodes |
| `input_tokens` | `int` | Tokens consumed |
| `output_tokens` | `int` | Tokens produced |
| `duration_ms` | `int` | Node execution time |
| `error` | `str` | Error message if the node failed |
| `output` | `dict` | Node output |

## Binary Resolution

The SDK locates the `agent-runtime` binary in this order:

1. `binary` argument passed to `Runtime()`
2. `AGENT_RUNTIME_BIN` environment variable
3. Bundled platform binary (included in the package)
4. `agent-runtime` on `PATH`

## Development

```bash
uv run pytest          # run tests
uv run ruff check .    # lint
```
