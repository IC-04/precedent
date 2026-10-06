"""Turn a template's {value, range, pool, choices, jitter} specs into concrete values.

The canonical seed uses every `value`, so it reproduces the brief exactly. Any other
seed samples from the same specs with one Random(seed), so worlds are deterministic.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from random import Random
from typing import Any

import yaml

TEMPLATES = Path(__file__).with_name("templates")


def load_template(name: str) -> dict[str, Any]:
    return yaml.safe_load((TEMPLATES / f"{name}.yaml").read_text())


def _round(x: float, step: int) -> int:
    return int(round(x / step) * step)


class Resolver:
    def __init__(self, seed: int, canonical_seed: int, pools: dict[str, list[Any]]):
        self.rng = Random(seed)
        self.canonical = seed == canonical_seed
        self.pools = pools
        self.taken: set[str] = set()

    def __call__(self, spec: Any) -> Any:
        if not isinstance(spec, dict) or "value" not in spec:
            return spec
        value = spec["value"]
        if self.canonical:
            if isinstance(value, str):
                self.taken.add(value)
            return value
        if "pool" in spec:
            return self.take(spec["pool"])
        if "choices" in spec:
            return self.rng.choice(spec["choices"])
        if "range" in spec:
            return self._from_range(spec["range"], spec.get("step", 1))
        if "jitter" in spec:
            j = spec["jitter"]
            return _round(value * (1 + self.rng.uniform(-j, j)), spec.get("step", 1))
        return value

    def _from_range(self, bounds: list[Any], step: int) -> Any:
        lo, hi = bounds
        if isinstance(lo, date):
            return lo + timedelta(days=self.rng.randint(0, (hi - lo).days))
        if isinstance(lo, int) and isinstance(hi, int):
            return _round(self.rng.randint(lo, hi), step)
        raise ValueError(f"unsupported range {bounds!r}")

    def take(self, pool: str) -> Any:
        """Pick an unused item from a named pool (names are never reused in one world)."""
        options = [x for x in self.pools[pool] if _key(x) not in self.taken]
        if not options:
            raise ValueError(f"pool {pool!r} exhausted")
        pick = self.rng.choice(options)
        self.taken.add(_key(pick))
        return pick

    def take_named(self, pool: str, name: str) -> Any:
        """Take a specific pool item (canonical worlds pin their story names)."""
        for x in self.pools[pool]:
            if _key(x) == name:
                self.taken.add(name)
                return x
        raise ValueError(f"{name!r} not in pool {pool!r}")


def _key(x: Any) -> str:
    return x["name"] if isinstance(x, dict) else str(x)
