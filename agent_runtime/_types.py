from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class TraceEvent:
    event: str
    ts: int
    flow: str = ""
    bundle: str = ""
    node: str = ""
    node_type: str = ""
    tool: str = ""
    model: str = ""
    inputs: dict[str, Any] = field(default_factory=dict)
    output: dict[str, Any] = field(default_factory=dict)
    args: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    attempt: int = 0
    max_retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 0
    item_index: int = 0
    item_count: int = 0
    chosen_target: str = ""
    branch_name: str = ""

    @classmethod
    def from_json(cls, line: str | bytes) -> TraceEvent:
        data: dict[str, Any] = json.loads(line)
        return cls(
            event=data.get("event", ""),
            ts=data.get("ts", 0),
            flow=data.get("flow", ""),
            bundle=data.get("bundle", ""),
            node=data.get("node", ""),
            node_type=data.get("type", ""),
            tool=data.get("tool", ""),
            model=data.get("model", ""),
            inputs=data.get("inputs") or {},
            output=data.get("output") or {},
            args=data.get("args") or {},
            error=data.get("error", ""),
            attempt=data.get("attempt", 0),
            max_retries=data.get("max_retries", 0),
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            duration_ms=data.get("duration_ms", 0),
            item_index=data.get("item_index", 0),
            item_count=data.get("item_count", 0),
            chosen_target=data.get("chosen_target", ""),
            branch_name=data.get("branch_name", ""),
        )


@dataclass
class FileInput:
    """Wraps a file path to be passed as a flow input via --input key=@path."""

    path: str | Path

    def __post_init__(self) -> None:
        self.path = Path(self.path).resolve()


class RunError(Exception):
    """Raised when the runtime reports a flow execution error."""

    def __init__(self, message: str, run_id: str = "") -> None:
        super().__init__(message)
        self.run_id = run_id


class MissingAPIKeyError(RuntimeError):
    """Raised before a run when required LLM provider API keys are absent.

    Attributes:
        missing_keys: List of environment variable names that must be set.
    """

    def __init__(self, missing_keys: list[str], detail: str = "") -> None:
        self.missing_keys = missing_keys
        summary = "Missing API key(s): " + ", ".join(sorted(missing_keys))
        super().__init__(f"{summary}\n\n{detail}".strip() if detail else summary)
