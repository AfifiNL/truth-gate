"""MCP server (stdio): lets an agent check its own draft before a person sees it.

The facts file and the optional brand file are fixed when the server starts
(`truth-gate serve --facts FILE [--brand FILE]`). Tools take document text only, never a path,
so a client cannot make the server read other files.
"""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from truth_gate.brand import Brand
from truth_gate.checker import Checker
from truth_gate.facts import Facts
from truth_gate.pair import PairChecker

INSTRUCTIONS = (
    "Check a draft against the facts file before showing it to a person. Every number must "
    "come from a fact and be used in that fact's context; only listed skills may be claimed; "
    "blocked phrases fail. Fix every error and check again; warnings are style advice."
)
PAIR_INSTRUCTIONS = (
    " When you localise a document, check the draft with check_localised against its English "
    "source before showing it to a person. Fix the draft, never the source or the brand rules."
)


def build_server(facts: Facts, brand: Brand | None = None) -> MCPServer:
    checker = Checker(facts)
    server = MCPServer(
        "truth-gate", instructions=INSTRUCTIONS + (PAIR_INSTRUCTIONS if brand else "")
    )

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
        out: dict[str, Any] = {
            "subject": facts.subject,
            "facts": [{"id": f.id, "text": f.text, "source": f.source} for f in facts.facts],
            "skills": sorted(checker.vocabulary.allowed),
            "blocked_phrases": facts.blocked_phrases,
        }
        if brand is not None:
            out["brand"] = brand.model_dump()
        return out

    if brand is None:
        return server
    pair_checkers = {name: PairChecker(brand, name) for name in brand.markets}

    @server.tool()
    def check_localised(source_text: str, target_text: str, market: str) -> dict[str, Any]:
        """Check a localised draft against its English source and the rules of one market
        (each text at most 200,000 characters).

        Returns passed, error and warning counts, and findings with side (source or target),
        line/column, rule and message: numbers that differ from the source, names that must
        stay as written, missing terms, forbidden phrases, missing required lines and, for
        Dutch, the wrong form of address. `market` must be one of the brand file's markets
        (see list_facts).
        """
        if market not in pair_checkers:
            raise ValueError(
                f"unknown market {market!r}; the brand file has: {', '.join(pair_checkers)}"
            )
        return pair_checkers[market].check(source_text, target_text).model_dump(mode="json")

    return server
