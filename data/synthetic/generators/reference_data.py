"""Generators for policyholders, policyholder_members, bank_details, hospitals.

Priya and Rahul are seeded with the exact IDs docs/use-case.md and docs/plan.md
require (they appear verbatim in scenario S01 and S06 sample inputs):
    Priya Raman -> KHA-SIL-004512, member MEM-004512-01
    Rahul Verma -> KHA-SIL-007731, member MEM-007731-01

Everything else is fabricated via Faker with a fixed seed, so `make seed` is
reproducible (docs/plan.md M1: "make seed is idempotent").
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from faker import Faker

SEED = 20260925  # fixed so repeated `make seed` runs produce the same data
fake = Faker("en_IN")
Faker.seed(SEED)
random.seed(SEED)

PLANS = ["Silver", "Gold"]
SUM_INSURED = {"Silver": 500_000, "Gold": 1_000_000}

CITIES = [
    "Coimbatore", "Chennai", "Bengaluru", "Hyderabad", "Pune", "Mumbai",
    "Kochi", "Madurai", "Vellore", "Mysuru",
]

HOSPITAL_NAME_TEMPLATES = [
    "{city} Multispeciality Hospital",
    "{city} General Hospital",
    "Sunrise Hospital, {city}",
    "Lakeview Clinic, {city}",
    "{city} Institute of Medical Sciences",
    "St. Mary's Hospital, {city}",
    "Apex Care Hospital, {city}",
    "{city} District Hospital",
]


def _random_start_date() -> date:
    # between 6 months and 8 years ago, so waiting periods vary across the seed set
    days_ago = random.randint(180, 8 * 365)
    return date.today() - timedelta(days=days_ago)


def gen_hospitals(n: int = 25, n_watchlisted: int = 3) -> list[dict]:
    hospitals = []
    used_names = set()
    for i in range(1, n + 1):
        city = random.choice(CITIES)
        template = random.choice(HOSPITAL_NAME_TEMPLATES)
        name = template.format(city=city)
        while name in used_names:
            name = f"{template.format(city=city)} {random.randint(2, 9)}"
        used_names.add(name)
        hospitals.append(
            {
                "hospital_id": f"HOSP-{i:03d}",
                "name": name,
                "city": city,
                "network": random.random() > 0.15,
                "watchlist": False,
            }
        )
    # S01/S06 reference "Sunrise Multispeciality Hospital, Coimbatore" and
    # "Lakeview Clinic, Coimbatore" by exact name, and neither is described as
    # watchlisted — fix these first, then flag watchlist hospitals from the rest.
    hospitals[0] = {"hospital_id": "HOSP-001", "name": "Sunrise Multispeciality Hospital, Coimbatore", "city": "Coimbatore", "network": True, "watchlist": False}
    hospitals[1] = {"hospital_id": "HOSP-002", "name": "Lakeview Clinic, Coimbatore", "city": "Coimbatore", "network": True, "watchlist": False}

    # Flag exactly n_watchlisted hospitals (used by scenario S10), never the two fixed ones above.
    for h in random.sample(hospitals[2:], n_watchlisted):
        h["watchlist"] = True
    return hospitals


def _gen_member(member_id: str, name: str, age: int) -> dict:
    return {"member_id": member_id, "name": name, "age": age, "relationship_to_holder": "self"}


def gen_policyholders(n: int = 60) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (policyholders, members, bank_details). Includes the fixed
    Priya and Rahul fixtures as policy #1 and #2; the rest are generated."""

    policyholders: list[dict] = []
    members: list[dict] = []
    bank_details: list[dict] = []

    def add_policy(policy_number: str, name: str, contact: str, plan: str,
                    start_date: date, member_rows: list[dict], account_number: str, ifsc: str) -> None:
        policyholders.append(
            {
                "policy_number": policy_number,
                "name": name,
                "contact": contact,
                "plan": plan,
                "sum_insured": SUM_INSURED[plan],
                "start_date": start_date,
            }
        )
        for m in member_rows:
            members.append({**m, "policy_number": policy_number})
        bank_details.append({"policy_number": policy_number, "account_number": account_number, "ifsc": ifsc})

    # --- Fixed fixtures required by S01/S06 ---
    add_policy(
        "KHA-SIL-004512", "Priya Raman", "priya.raman@example.com", "Silver",
        date.today() - timedelta(days=14 * 30),  # ~14 months old, matches S01 narrative
        [_gen_member("MEM-004512-01", "Priya Raman", 34)],
        "500100" + "".join(str(random.randint(0, 9)) for _ in range(8)), "HDFC0001234",
    )
    add_policy(
        "KHA-SIL-007731", "Rahul Verma", "rahul.verma@example.com", "Silver",
        date.today() - timedelta(days=20),  # 20 days old, matches S03/S06 narrative (recent policy)
        [_gen_member("MEM-007731-01", "Rahul Verma", 29)],
        "500200" + "".join(str(random.randint(0, 9)) for _ in range(8)), "ICIC0005678",
    )

    # --- Remaining fabricated policies ---
    for i in range(3, n + 1):
        plan = random.choice(PLANS)
        policy_number = f"KHA-{'SIL' if plan == 'Silver' else 'GLD'}-{100000 + i:06d}"
        holder_name = fake.name()
        n_members = random.randint(1, 3)
        member_rows = [_gen_member(f"MEM-{100000 + i:06d}-01", holder_name, random.randint(22, 75))]
        for m in range(2, n_members + 1):
            member_rows.append(
                _gen_member(f"MEM-{100000 + i:06d}-{m:02d}", fake.name(), random.randint(1, 80))
            )
        add_policy(
            policy_number,
            holder_name,
            fake.unique.email(),
            plan,
            _random_start_date(),
            member_rows,
            "".join(str(random.randint(0, 9)) for _ in range(14)),
            random.choice(["HDFC", "ICIC", "SBIN", "AXIS", "KKBK"]) + "0" + str(random.randint(100000, 999999)),
        )

    return policyholders, members, bank_details
