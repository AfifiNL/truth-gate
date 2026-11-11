"""Write evals/l10n/labels.jsonl from labels made BY READING each localisation.

The labels below were written by reading every document before the checker was run on that
split. A label lists the rules a reviewer would say the document breaks, with the evidence:

  number         a number from the source is missing, changed or added (a clock time written
                 the local way, a spelled-out number or an Arabic dual is NOT a violation)
  name           a do-not-translate name is translated or transliterated
  term           the source uses a term and the target uses another word for it (an inflected
                 or indefinite form of the brand's word is NOT a violation)
  forbidden      a forbidden phrase is used
  required-line  the required line is missing or altered
  address        Dutch: "u" or "uw" where the market is addressed with "je"

Documents made with the `bare` prompt were never given the rules, so every one of them lacks
the required line; that label is added for all of them here. `NOTES` records places where
the reader expected the checker to disagree with the label, written before it ran.

Each label records the SHA-256 of the text it was made for.

    python evals/l10n/make_labels.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# id -> {rule: evidence}. An id that is absent here was read and found clean
# (apart from the required line in the bare condition).
DEV: dict[str, dict[str, str]] = {
    "s01-nl-bare": {"term": "klantenportal for customer portal"},
    "s03-nl-bare": {
        "address": "Uw vervoerder; U kunt",
        "term": "klantenportaal for customer portal",
    },
    "s03-ar-bare": {"term": "الناقل for carrier; نافذة التسليم for delivery window"},
    "s08-nl-bare": {"address": "Meld u aan; betaalt u"},
    "s09-nl-bare": {"term": "levertijden for delivery windows"},
    "s11-nl-bare": {"address": "kiest u"},
    "s11-ar-bare": {"term": "نافذة التسليم for delivery window"},
    "s12-nl-bare": {"address": "uw klant"},
    "s12-ar-bare": {"term": "الناقل for carrier"},
    "s13-ar-bare": {"name": "ExampleFreight kept, but a transliteration was added before it"},
    "s15-nl-bare": {"address": "U betaalt"},
    "s16-nl-bare": {"term": "klantenportaal for customer portal"},
    "s17-ar-bare": {"name": "ExampleFreight kept, but a transliteration was added before it"},
    "s18-nl-bare": {"address": "krijgt u"},
}
TEST: dict[str, dict[str, str]] = {}

# Written while reading, before the checker ran: where it will probably disagree.
NOTES: dict[str, str] = {
    "s02-ar-bare": "twelve is spelled out (اثني عشر): expect a false alarm on 12",
    "s02-ar-rules": "twelve is spelled out (اثني عشر): expect a false alarm on 12",
    "s03-nl-bare": "8 and 12 written as clock times (08:00, 12:00): expect a false alarm",
    "s03-ar-rules": "شحنتك (the brand's word with a suffix): expect a false alarm on the term",
    "s09-ar-bare": "شركة نقل (indefinite form of the brand's term): expect a false alarm",
    "s10-ar-bare": "two hours as an Arabic dual (ساعتين): expect a false alarm on 2",
    "s10-ar-rules": "two hours as an Arabic dual (ساعتين): expect a false alarm on 2",
    "s11-ar-bare": "two hours as an Arabic dual (لساعتين): expect a false alarm on 2",
    "s11-ar-rules": "two hours as an Arabic dual (ساعتان): expect a false alarm on 2",
    "s13-ar-bare": "the name is still there once, so the count rule will pass: expect a miss",
    "s17-ar-bare": "the name is still there once, so the count rule will pass: expect a miss",
    "s20-ar-bare": "شركة نقل (indefinite form of the brand's term): expect a false alarm",
    "s20-ar-rules": "شركة نقل (indefinite form of the brand's term): expect a false alarm",
}


def main() -> int:
    docs = [
        json.loads(line)
        for line in (HERE / "documents.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    labelled = {"dev": DEV, "test": TEST}
    done = {"dev": bool(DEV), "test": bool(TEST)}
    rows = []
    for doc in docs:
        if "id" not in doc or not done[doc["split"]]:
            continue
        violations = dict(labelled[doc["split"]].get(doc["id"], {}))
        if doc["condition"] == "bare":
            violations["required-line"] = "bare prompt: the model was not given the line"
        row = {
            "id": doc["id"],
            "sha256": hashlib.sha256(doc["target"].encode("utf-8")).hexdigest(),
            "violations": violations,
        }
        if doc["id"] in NOTES:
            row["note"] = NOTES[doc["id"]]
        rows.append(row)
    (HERE / "labels.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )
    print(f"wrote {len(rows)} labels")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
