"""MCP server (stdio): lets an agent check its own draft before a person sees it.

The facts file is fixed when the server starts (`truth-gate serve --facts FILE`). Tools take
document text only, never a path, so a client cannot make the server read other files.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from truth_gate.checker import Checker
from truth_gate.facts import Facts

INSTRUCTIONS = (
    "Check a draft against the facts file before showing it to a person. Every number must "
    "come from a fact and be used in that fact's context; only listed skills may be claimed; "
    "blocked phrases fail. Fix every error and check again; warnings are style advice."
)


def build_server(facts: Facts) -> MCPServer:
    checker = Checker(facts)
    server = MCPServer("truth-gate", instructions=INSTRUCTIONS)

    @server.tool()
    def check_document(text: str) -> dict[str, Any]:
        """Check a draft (Markdown or plain text, at most 200,000 characters) against the facts
        file.

        Returns passed, error and warning counts, findings with line/column and message, and
        a trace from each accepted number to the fact that supports it. A longer document is
        rejected with an error instead of being checked in part.
        """
        return checker.check(text).model_dump()

    @server.tool()
    def list_facts() -> dict[str, Any]:
        """The facts, skills and blocked phrases the checker uses."""
        return {
            "subject": facts.subject,
            "facts": [{"id": f.id, "text": f.text, "source": f.source} for f in facts.facts],
            "skills": sorted(checker.vocabulary.allowed),
            "blocked_phrases": facts.blocked_phrases,
        }

    return server
