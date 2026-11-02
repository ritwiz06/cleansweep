"""Property tests on generated inputs (seeded): the redactor never lets a secret through, and a
watch clean never costs more test runs than the budget has left."""

import random
import string

from cleansweep.agents.secrets import Redactor
from cleansweep.agents.watch import BASELINE_RUNS, affordable, clean_cost, decide

WORDS = ["the", "cart", "total", "returns", "value", "items", "price", "list", "of", "and"]
ALNUM = string.ascii_letters + string.digits
UPPER = string.ascii_uppercase + string.digits


def fake_secret(rng: random.Random) -> str:
    """A secret-looking string of a random kind, made up at run time."""

    def pick(chars, n):
        return "".join(rng.choice(chars) for _ in range(n))

    return rng.choice(
        [
            lambda: "AKIA" + pick(UPPER, 16),
            lambda: "ghp_" + pick(ALNUM, 36),
            lambda: "xoxb-" + pick(ALNUM, 14),
            lambda: "AIza" + pick(ALNUM, 35),
            lambda: "sk-" + pick(ALNUM, 28),
        ]
    )()


def filler(rng: random.Random) -> str:
    return " ".join(rng.choice(WORDS) + rng.choice(["", ",", ".", "\n"]) for _ in range(12))


def test_the_redactor_masks_every_planted_secret_and_nothing_else():
    rng = random.Random(572)
    for _ in range(300):
        secrets = [fake_secret(rng) for _ in range(rng.randint(1, 3))]
        known = "".join(rng.choice(ALNUM) for _ in range(20))
        parts = [filler(rng), *secrets, f"token: {known}", filler(rng)]
        rng.shuffle(parts)
        text = " ".join(parts)
        redact = Redactor({known})
        out = redact(text)
        assert not any(s in out for s in [*secrets, known])
        assert redact(out) == out
        plain = filler(rng)
        assert redact(plain) == plain


def test_a_watch_clean_never_costs_more_than_the_budget_left():
    rng = random.Random(572)
    for _ in range(2000):
        items, budget = rng.randint(0, 60), rng.randint(0, 80)
        used = rng.randint(0, budget)
        state = {
            "open_items": items,
            "loc": rng.randint(1, 5000),
            "slop_loc": rng.randint(0, 400),
            "new_items": rng.randint(0, 6),
            "commits_since_clean": rng.randint(0, 30),
            "budget_tests": budget,
            "test_runs_used": used,
        }
        choice, _ = decide(state)
        can = affordable(items, budget - used) if budget else items
        if choice == "clean":
            assert can > 0 and (not budget or clean_cost(can) <= budget - used)
        more = {**state, "slop_loc": state["slop_loc"] + rng.randint(1, 400)}
        if choice == "clean":
            assert decide(more)[0] == "clean"  # more slop never turns a clean into a wait
        assert affordable(items, budget - used, BASELINE_RUNS) <= items
