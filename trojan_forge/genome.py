"""TrojanGenome - one hardware-Trojan design, and its feature encoding.

A genome is the full specification the HideAgent emits and the HuntAgent /
FixAgent consume:

    (target, trigger, payload, stealth, trigger_prob_exp, area_budget)

The four categorical choices come from config.py; the two continuous knobs are
learned per-design:

    trigger_prob_exp  in [0,1] -> maps to 2^-(4 .. 64): how many bits the trigger
                      condition is (challenge_1's knock is the 2^-64 extreme).
    area_budget       in [0,1] -> fraction of the device logic-cell budget the
                      Trojan is allowed to spend.

`features()` produces the fixed-width vector every network sees: one-hot of the
four categoricals, the two continuous knobs, and the four numeric priors of each
chosen option (impact/rarity/area/evasion). That gives the networks both the
identity of the choice and its grounded physical prior.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, asdict

import numpy as np

from . import config as C


def _onehot(name: str, names: list[str]) -> np.ndarray:
    v = np.zeros(len(names), dtype=np.float32)
    v[names.index(name)] = 1.0
    return v


# feature layout width, computed once
FEATURE_DIM = (
    len(C.TARGET_NAMES) + len(C.TRIGGER_NAMES)
    + len(C.PAYLOAD_NAMES) + len(C.STEALTH_NAMES)
    + 2                      # continuous knobs
    + 4 * 4                  # 4 priors x 4 chosen options
)

# number of discrete head outputs the HideAgent policy scores
HEAD_SIZES = {
    "target": len(C.TARGET_NAMES),
    "trigger": len(C.TRIGGER_NAMES),
    "payload": len(C.PAYLOAD_NAMES),
    "stealth": len(C.STEALTH_NAMES),
}


@dataclass
class TrojanGenome:
    target: str
    trigger: str
    payload: str
    stealth: str
    trigger_prob_exp: float = 0.5   # [0,1]
    area_budget: float = 0.3        # [0,1]

    # ---- derived physical quantities (grounded) ----
    def trigger_bits(self) -> float:
        """Map the knob to an effective trigger width in bits (4..64)."""
        return 4.0 + self.trigger_prob_exp * 60.0

    def trigger_probability(self) -> float:
        return 2.0 ** (-self.trigger_bits())

    def area_cells(self) -> int:
        """Estimated extra logic cells, grounded in the chosen stealth technique.

        resource_sharing pushes overhead toward ~0 (challenge note: +0 area);
        'none' is the full ask. Range anchored to the submission's +30..+300 LC.
        """
        base = self.area_budget * C.TrainConfig.device_lc_budget * 0.08
        st = C.STEALTH_IX[self.stealth]
        return int(max(2, base * (0.1 + st.area)))

    def opts(self):
        return (C.TARGET_IX[self.target], C.TRIGGER_IX[self.trigger],
                C.PAYLOAD_IX[self.payload], C.STEALTH_IX[self.stealth])

    def features(self) -> np.ndarray:
        t, tr, pl, st = self.opts()
        priors = np.array([
            t.impact, t.rarity, t.area, t.evasion,
            tr.impact, tr.rarity, tr.area, tr.evasion,
            pl.impact, pl.rarity, pl.area, pl.evasion,
            st.impact, st.rarity, st.area, st.evasion,
        ], dtype=np.float32)
        return np.concatenate([
            _onehot(self.target, C.TARGET_NAMES),
            _onehot(self.trigger, C.TRIGGER_NAMES),
            _onehot(self.payload, C.PAYLOAD_NAMES),
            _onehot(self.stealth, C.STEALTH_NAMES),
            np.array([self.trigger_prob_exp, self.area_budget], dtype=np.float32),
            priors,
        ])

    def gid(self) -> str:
        raw = f"{self.target}|{self.trigger}|{self.payload}|{self.stealth}|" \
              f"{self.trigger_prob_exp:.3f}|{self.area_budget:.3f}"
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def as_row(self) -> dict:
        d = asdict(self)
        d["gid"] = self.gid()
        d["trigger_bits"] = round(self.trigger_bits(), 1)
        d["area_cells"] = self.area_cells()
        return d


def random_genome(rng: np.random.Generator) -> TrojanGenome:
    return TrojanGenome(
        target=rng.choice(C.TARGET_NAMES),
        trigger=rng.choice(C.TRIGGER_NAMES),
        payload=rng.choice(C.PAYLOAD_NAMES),
        stealth=rng.choice(C.STEALTH_NAMES),
        trigger_prob_exp=float(rng.random()),
        area_budget=float(rng.random()),
    )


def from_choices(target_i, trigger_i, payload_i, stealth_i,
                 prob_exp, area_budget) -> TrojanGenome:
    return TrojanGenome(
        target=C.TARGET_NAMES[target_i],
        trigger=C.TRIGGER_NAMES[trigger_i],
        payload=C.PAYLOAD_NAMES[payload_i],
        stealth=C.STEALTH_NAMES[stealth_i],
        trigger_prob_exp=float(np.clip(prob_exp, 0, 1)),
        area_budget=float(np.clip(area_budget, 0, 1)),
    )
