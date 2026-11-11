"""Build evals/pairs/cases.jsonl from hand-written pairs (deterministic; no model involved).

Each case is an English source, a Dutch or Arabic target, and a kind: `clean`, or one planted
error. An error case is the clean target with one edit, written out below so a reviewer can
read exactly what changed. `hard` marks cases written to show a known limit: the checker is
expected to get them wrong, and the README reports them.

The Dutch was written by the author and has not been checked by a native speaker.

    python evals/pairs/build_cases.py          # rewrite evals/pairs/cases.jsonl
    python evals/pairs/build_cases.py --check  # exit 1 if the committed file is stale
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

LINE = {"nl-NL": "Prijzen zijn exclusief btw.", "ar": "الأسعار لا تشمل ضريبة القيمة المضافة."}

# id -> (English source, clean Dutch target, clean Arabic target)
PAIRS: dict[str, tuple[str, str, str]] = {
    "s1": (
        "ExampleFreight moved 1,200 shipments a day in 2024, and 98.5% arrived on time.",
        "ExampleFreight verwerkte in 2024 1.200 zendingen per dag, en 98,5% kwam op tijd aan.",
        "نقلت ExampleFreight في عام 2024 نحو 1,200 شحنة يوميًا، ووصل 98.5% منها في الموعد.",
    ),
    "s2": (
        "TrackBoard plans start at €49 per month for teams of up to twelve people.",
        "Een TrackBoard-abonnement kost vanaf € 49 per maand, voor teams tot twaalf personen.",
        "تبدأ خطط TrackBoard من 49 يورو شهريًا للفرق التي تضم حتى 12 شخصًا.",
    ),
    "s3": (
        "Open the customer portal to follow every shipment in real time.",
        "Open het klantportaal en volg elke zending in realtime.",
        "افتح بوابة العملاء لمتابعة كل شحنة لحظة بلحظة.",
    ),
    "s4": (
        "In 2023 our 350 drivers delivered 2.5 million parcels across 14 countries.",
        "In 2023 bezorgden onze 350 chauffeurs 2,5 miljoen pakketten in 14 landen.",
        "في عام 2023 سلّم سائقونا البالغ عددهم 350 سائقًا 2.5 مليون طرد في 14 دولة.",
    ),
    "s5": (
        "Customers who switched to TrackBoard cut late deliveries by 30% within six months.",
        "Klanten die overstapten op TrackBoard hadden binnen zes maanden 30% minder late "
        "leveringen.",
        "العملاء الذين انتقلوا إلى TrackBoard خفّضوا التسليمات المتأخرة بنسبة 30% خلال ستة أشهر.",
    ),
    "s6": (
        "Your shipment is insured up to $5,000 at no extra cost.",
        "Je zending is verzekerd tot $ 5.000, zonder extra kosten.",
        "الشحنة مؤمَّنة حتى 5,000 دولار دون أي تكلفة إضافية.",
    ),
    "s7": (
        "ExampleFreight has 3 warehouses and a support team of 40 people, open 7 days a week.",
        "ExampleFreight heeft 3 magazijnen en een supportteam van 40 mensen, 7 dagen per week "
        "bereikbaar.",
        "لدى ExampleFreight ثلاثة مستودعات وفريق دعم من 40 شخصًا، يعمل 7 أيام في الأسبوع.",
    ),
    "s8": (
        "Sign up before 31 March and get 3 months of TrackBoard free.",
        "Meld je vóór 31 maart aan en krijg 3 maanden TrackBoard gratis.",
        "سجّل قبل 31 مارس واحصل على 3 أشهر من TrackBoard مجانًا.",
    ),
}

# (pair, market, kind, text in the clean target, what replaces it)
EDITS: list[tuple[str, str, str, str, str]] = [
    ("s1", "nl-NL", "changed_number", "1.200", "1.300"),
    ("s5", "nl-NL", "changed_number", "30%", "13%"),
    ("s4", "ar", "changed_number", "350", "530"),
    ("s2", "ar", "changed_number", "12", "20"),
    # the source's "1,200" copied as it stands: in Dutch that is 1.2
    ("s1", "nl-NL", "source_format", "1.200", "1,200"),
    ("s6", "nl-NL", "source_format", "5.000", "5,000"),
    ("s4", "nl-NL", "dropped_number", " in 14 landen", ""),
    ("s7", "ar", "dropped_number", "يعمل 7 أيام في الأسبوع", "يعمل طوال الأسبوع"),
    ("s3", "nl-NL", "added_number", "in realtime", "in realtime, net als 500 andere klanten"),
    ("s5", "ar", "added_number", "خلال ستة أشهر", "خلال ستة أشهر، مثل أكثر من 200 عميل"),
    ("s5", "nl-NL", "percent_lost", "30%", "30"),
    ("s1", "ar", "percent_lost", "98.5%", "98.5"),
    ("s2", "nl-NL", "translated_name", "TrackBoard", "Volgbord"),
    ("s1", "nl-NL", "translated_name", "ExampleFreight", "VoorbeeldVracht"),
    ("s5", "ar", "translated_name", "TrackBoard", "تراك بورد"),
    ("s7", "ar", "translated_name", "ExampleFreight", "إكزامبل فريت"),
    ("s3", "nl-NL", "missing_term", "klantportaal", "klantenomgeving"),
    ("s1", "nl-NL", "missing_term", "zendingen", "pakketten"),
    ("s3", "ar", "missing_term", "شحنة", "طرد"),
    ("s3", "ar", "missing_term", "بوابة العملاء", "منصة العملاء"),
    ("s8", "nl-NL", "forbidden", "gratis.", "gratis, met gratis verzending."),
    (
        "s2",
        "nl-NL",
        "forbidden",
        "Een TrackBoard-abonnement",
        "Het goedkoopste TrackBoard-abonnement",
    ),
    ("s8", "ar", "forbidden", "مجانًا.", "مجانًا مع شحن مجاني."),
    ("s2", "ar", "forbidden", "شخصًا.", "شخصًا، وهي الأرخص في السوق."),
    ("s6", "nl-NL", "address", "Je zending", "Uw zending"),
    ("s8", "nl-NL", "address", "Meld je vóór 31 maart aan", "Meldt u zich vóór 31 maart aan"),
    ("s3", "nl-NL", "address", "Open het klantportaal", "Open uw klantportaal"),
]

# Pairs where the required line is left out: (pair, market)
NO_LINE = [("s7", "nl-NL"), ("s4", "ar")]

# Known limits. (id, market, kind, source, target): the outcome the checker gets wrong.
HARD: list[tuple[str, str, str, str, str]] = [
    (
        "h1",
        "nl-NL",
        "changed_meaning",  # same number, opposite claim: passes
        PAIRS["s5"][0],
        PAIRS["s5"][1].replace("30% minder", "30% meer"),
    ),
    (
        "h2",
        "nl-NL",
        "swapped_numbers",  # both numbers are there, on the wrong nouns: passes
        PAIRS["s7"][0],
        PAIRS["s7"][1].replace("3 magazijnen", "40 magazijnen").replace("40 mensen", "3 mensen"),
    ),
    (
        "h3",
        "nl-NL",
        "forbidden",  # an inflected form of a forbidden phrase is not the listed phrase: passes
        PAIRS["s8"][0],
        PAIRS["s8"][1].replace("gratis.", "gratis, en we verzenden gratis."),
    ),
    (
        "h4",
        "nl-NL",
        "clean",  # a clock time converted to 24 hours: reported as a changed number
        "You can change the delivery address until 6 pm.",
        "Je kunt het afleveradres wijzigen tot 18.00 uur.",
    ),
    (
        "h5",
        "nl-NL",
        "clean",  # a long compound number word is not read
        "Our 350 drivers know every route.",
        "Onze driehonderdvijftig chauffeurs kennen elke route.",
    ),
    (
        "h6",
        "nl-NL",
        "clean",  # a name replaced by a pronoun the second time
        "TrackBoard is new. TrackBoard shows every route.",
        "TrackBoard is nieuw. Het toont elke route.",
    ),
    (
        "h7",
        "ar",
        "clean",  # the Arabic dual says "two" without a number word
        "Get the first two months free.",
        "احصل على أول شهرين مجانًا.",
    ),
    (
        "h8",
        "ar",
        "clean",  # a possessive suffix on a term is not a listed form
        "Your shipment is on its way.",
        "شحنتك في الطريق.",
    ),
    (
        "h9",
        "ar",
        "clean",  # a compound number word is read as two numbers
        "A team of 25 people.",
        "فريق من خمسة وعشرين شخصًا.",
    ),
]


def build() -> list[dict[str, object]]:
    cases: list[dict[str, object]] = []

    def add(kind: str, hard: bool, market: str, source: str, target: str, cid: str = "") -> None:
        n = len(cases) + 1
        cases.append(
            {
                "id": cid or f"p{n:02d}",
                "split": "dev" if n % 2 else "test",
                "market": market,
                "kind": kind,
                "hard": hard,
                "source": source,
                "target": target,
            }
        )

    for pid, (source, dutch, arabic) in PAIRS.items():
        for market, target in (("nl-NL", dutch), ("ar", arabic)):
            if (pid, market) in NO_LINE:
                add("missing_line", False, market, source, target)
            else:
                add("clean", False, market, source, f"{target}\n\n{LINE[market]}")
    for pid, market, kind, old, new in EDITS:
        source = PAIRS[pid][0]
        clean = PAIRS[pid][1 if market == "nl-NL" else 2]
        if old not in clean:
            raise SystemExit(f"{pid} {market} {kind}: {old!r} is not in the clean target")
        add(kind, False, market, source, f"{clean.replace(old, new, 1)}\n\n{LINE[market]}")
    for cid, market, kind, source, target in HARD:
        add(kind, True, market, source, f"{target}\n\n{LINE[market]}", cid)
    return cases


def main() -> int:
    path = Path(__file__).with_name("cases.jsonl")
    text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in build())
    if "--check" in sys.argv:
        if not path.exists() or path.read_text(encoding="utf-8") != text:
            print("evals/pairs/cases.jsonl is stale: run python evals/pairs/build_cases.py")
            return 1
        return 0
    path.write_text(text, encoding="utf-8")
    print(f"wrote {len(build())} cases to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
