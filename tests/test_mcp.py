from __future__ import annotations

import sys

import anyio
import pytest
from mcp import Client, StdioServerParameters

from conftest import ROOT
from truth_gate.facts import Facts
from truth_gate.mcp_server import build_server


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_tools_over_the_in_memory_transport(example_facts: Facts, mode: str) -> None:
    async def go() -> None:
        async with Client(build_server(example_facts), mode=mode) as client:  # type: ignore[arg-type]
            names = sorted(t.name for t in (await client.list_tools()).tools)
            assert names == ["check_document", "list_facts"]
            bad = await client.call_tool("check_document", {"text": "Led 15 engineers."})
            assert not bad.is_error
            assert bad.structured_content is not None
            assert bad.structured_content["passed"] is False
            assert bad.structured_content["findings"][0]["text"] == "15"
            huge = await client.call_tool("check_document", {"text": "x" * 200_001})
            assert huge.is_error
            listed = await client.call_tool("list_facts", {})
            assert listed.structured_content is not None
            assert "PostgreSQL" in listed.structured_content["skills"]

    anyio.run(go)


def test_stdio_entry_point_serves_tools() -> None:
    """The real `truth-gate serve` process, spoken to over stdin/stdout."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "truth_gate.cli", "serve", "--facts", str(ROOT / "examples" / "facts.yaml")],
    )

    async def go() -> None:
        async with Client(params) as client:
            res = await client.call_tool(
                "check_document", {"text": "Cut monthly cloud costs by 18% in 2022."}
            )
            assert res.structured_content is not None
            assert res.structured_content["passed"] is True

    anyio.run(go)
