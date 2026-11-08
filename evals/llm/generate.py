"""Generate the LLM-written eval set (live model calls: costs money, needs credentials).

    TG_MAX_LIVE_CALLS=48 uv run --group live python evals/llm/generate.py

Vertex AI through Application Default Credentials (GOOGLE_CLOUD_PROJECT and the usual ADC
variables in the environment); this script never reads, prints or stores credentials.
Every request counts toward TG_MAX_LIVE_CALLS (default 0: no calls at all). SDK retries are off,
so one request is one call. A failed call leaves a gap; running again requests only the ids
that are missing from evals/llm/documents.jsonl. Generated text is stored as returned and never
edited: labels live in evals/llm/labels.jsonl.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import random
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
FACTS = HERE.parent / "facts.yaml"
OUT = HERE / "documents.jsonl"
MODEL = os.environ.get("TG_GEMINI_MODEL", "gemini-3.6-flash")
LOCATION = os.environ.get("TG_GEMINI_LOCATION", "eu")
THINKING = "LOW"

SYSTEM = (
    "You write short business documents for test data. Everything is fictional: the person, "
    "the companies and the university in the facts are invented. Never mention any real "
    "company, organisation, product, place or person, except the software tools in the skills "
    "list. Write plain English prose without headings or lists."
)

GENRES = {
    "bio": "a third-person speaker bio of 60 to 90 words about the subject",
    "service": (
        "a 50 to 80 word blurb for the website of the customer support service the subject "
        "ran at ExampleParcel Co (the fictional company in the facts)"
    ),
    "report": (
        "one paragraph of 70 to 100 words for a fictional internal annual report on the support "
        "team's results under the subject"
    ),
}
ERRORS = {
    "wrong_number": (
        "Change exactly one number taken from the facts to a different, plausible value. In "
        "injected_error, give the value you wrote and the value in the fact."
    ),
    "wrong_context": (
        "Take exactly one number from the facts, keep its value unchanged, and attach it to a "
        "different claim than the one in its fact (for example a team size presented as years "
        "of experience). In injected_error, give the number and the claim you attached it to."
    ),
    "invented_skill": (
        "Claim that the subject uses exactly one software tool, platform or technical skill "
        "that appears neither in the skills list nor in the facts. In injected_error, name it."
    ),
    "blocked_phrase": (
        "Use exactly one of the blocked phrases, word for word. In injected_error, give the phrase."
    ),
}
KINDS = ["clean", "wrong_number", "clean", "wrong_context", "clean", "invented_skill", "clean",
         "blocked_phrase"]  # fmt: skip


class Output(BaseModel):
    document: str
    injected_error: str


def requests() -> list[dict[str, Any]]:
    facts = yaml.safe_load(FACTS.read_text(encoding="utf-8"))
    ids = [f["id"] for f in facts["facts"]]
    rng = random.Random(1109)  # noqa: S311 - a fixed choice of facts, not security
    out: list[dict[str, Any]] = []
    for genre in GENRES:
        for rep, split in enumerate(("dev", "heldout")):
            for kind in KINDS:
                out.append(
                    {
                        "id": f"L{len(out) + 1:02d}",
                        "split": split,
                        "genre": genre,
                        "requested": kind,
                        "focus": sorted(rng.sample(ids, 4)),
                        "rep": rep,
                    }
                )
    return out


def prompt(req: dict[str, Any], facts: dict[str, Any]) -> str:
    by_id = {f["id"]: f["text"] for f in facts["facts"]}
    lines = ["Facts (the only source you may use):"]
    lines += [f"- {f['text']}" for f in facts["facts"]]
    lines.append("Skills list: " + ", ".join(facts["skills"]))
    lines.append("Blocked phrases: " + ", ".join(facts["blocked_phrases"]))
    lines.append(f"Subject: {facts['subject']}.")
    lines.append("")
    lines.append(f"Task: write {GENRES[req['genre']]}. Mainly use these facts:")
    lines += [f"- {by_id[i]}" for i in req["focus"]]
    lines.append(
        "Rules: use only the facts above; add no other number, date, tool, skill, company, "
        "product or place; do not use the blocked phrases."
    )
    if req["requested"] == "clean":
        lines.append('Set injected_error to "none".')
    else:
        lines.append(
            "This document is test data for a fact-checking tool. Follow the rules above, "
            "except for exactly ONE deliberate error: " + ERRORS[req["requested"]] + " Everything "
            "else must stay faithful to the facts."
        )
    return "\n".join(lines)


class Budget:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.used >= self.cap:
                return False
            self.used += 1
            return True


def main() -> int:
    cap = int(os.environ.get("TG_MAX_LIVE_CALLS", "0"))
    facts = yaml.safe_load(FACTS.read_text(encoding="utf-8"))
    todo = requests()
    done: dict[str, dict[str, Any]] = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "id" in row:
                done[row["id"]] = row
    todo = [r for r in todo if r["id"] not in done]
    print(f"{len(done)} documents on file, {len(todo)} to request, cap {cap} calls")
    if not todo or cap <= 0:
        return 0 if not todo else 2

    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        location=LOCATION,
        http_options=types.HttpOptions(
            timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=Output,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(THINKING)),
    )
    budget = Budget(cap)
    lock = threading.Lock()
    failures: list[str] = []

    def run(req: dict[str, Any]) -> None:
        if not budget.take():
            with lock:
                failures.append(f"{req['id']}: cap reached, not requested")
            return
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=prompt(req, facts), config=config
            )
            out = Output.model_validate_json(resp.text or "")
        except Exception as exc:  # vendor errors by type and status only
            code = getattr(exc, "code", None)
            with lock:
                failures.append(
                    f"{req['id']}: {type(exc).__name__}" + (f" (HTTP {code})" if code else "")
                )
            return
        row = {
            **{k: req[k] for k in ("id", "split", "genre", "requested", "focus")},
            "document": out.document,
            "model_report": out.injected_error,
            "raw_response": resp.text,  # the model's exact output, kept as evidence
        }
        with lock:
            done[req["id"]] = row

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(run, todo))

    template = SYSTEM + json.dumps(GENRES) + json.dumps(ERRORS)
    meta = {
        "model": MODEL,
        "location": LOCATION,
        "thinking_level": THINKING.lower(),
        "prompt_sha256": hashlib.sha256(template.encode()).hexdigest()[:16],
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    rows = [done[k] for k in sorted(done)]
    OUT.write_text(
        json.dumps({"meta": meta})
        + "\n"
        + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    print(f"calls used: {budget.used}; documents on file: {len(rows)}")
    for f in failures:
        print("FAILED " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
