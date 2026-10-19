import os


def use_stub(name: str) -> bool:
    """True when CLEANSWEEP_STUBS lists this package (or says 'all')."""
    raw = os.environ.get("CLEANSWEEP_STUBS", "")
    names = {n.strip() for n in raw.split(",") if n.strip()}
    return "all" in names or name in names
