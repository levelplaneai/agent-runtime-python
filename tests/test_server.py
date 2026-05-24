"""Unit tests for ToolServer."""
import json
import urllib.request
from urllib.error import HTTPError

import pytest

from agent_runtime._server import ToolServer


def test_tool_called_and_returns_dict():
    def greet(name: str) -> dict:
        return {"greeting": f"hello, {name}"}

    server = ToolServer({"my_ns.greet@v1": greet})
    server.start()
    try:
        body = json.dumps({"name": "world"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/tools/my_ns.greet@v1",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        assert result == {"greeting": "hello, world"}
    finally:
        server.stop()


def test_unknown_tool_returns_404():
    server = ToolServer({})
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/tools/missing@v1",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 404
    finally:
        server.stop()


def test_tool_exception_returns_500():
    def boom(**_):
        raise ValueError("something went wrong")

    server = ToolServer({"ns.boom@v1": boom})
    server.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/tools/ns.boom@v1",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 500
        body = json.loads(exc_info.value.read())
        assert "something went wrong" in body["error"]
    finally:
        server.stop()


def test_async_tool_is_dispatched():
    import asyncio

    async def async_greet(name: str) -> dict:
        await asyncio.sleep(0)
        return {"greeting": f"async hello, {name}"}

    server = ToolServer({"ns.async_greet@v1": async_greet})
    server.start()
    try:
        body = json.dumps({"name": "async"}).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/tools/ns.async_greet@v1",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        assert result == {"greeting": "async hello, async"}
    finally:
        server.stop()


def test_multiple_tools_on_same_server():
    tools = {
        "ns.add@v1": lambda a, b: {"sum": a + b},
        "ns.mul@v1": lambda a, b: {"product": a * b},
    }
    server = ToolServer(tools)
    server.start()
    try:
        for ref, payload, expected_key in [
            ("ns.add@v1", {"a": 3, "b": 4}, "sum"),
            ("ns.mul@v1", {"a": 3, "b": 4}, "product"),
        ]:
            body = json.dumps(payload).encode()
            req = urllib.request.Request(
                f"http://127.0.0.1:{server.port}/tools/{ref}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
            assert expected_key in result
    finally:
        server.stop()
