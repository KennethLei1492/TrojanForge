"""TrojanGenome - one hardware-Trojan design, and its feature encoding.

Six categorical axes + four continuous attributes (grounded in the taxonomy,
see config.py and SOURCES.md):

  categorical: target, trigger, payload, stealth, abstraction, channel
  continuous:  trigger_prob_exp  -> trigger rarity in bits, 2^-(4..64)
               area_budget       -> fraction of device logic-cell budget
               implicit_alpha    -> P(output looks normal when triggered) [arXiv:1605.08413]
               prop_delay        -> payload propagation delay, cycles (normalised)

`features()` is the fixed-width vector every network sees: one-hot of the six
categoricals, the four continuous attributes, and the four numeric priors
(impact/rarity/area/evasion) of each chosen categorical option.
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


FEATURE_DIM = (
    len(C.TARGET_NAMES) + len(C.TRIGGER_NAMES) + len(C.PAYLOAD_NAMES)
    + len(C.STEALTH_NAMES) + len(C.ABSTRACTION_NAMES) + len(C.CHANNEL_NAMES)
    + 4                        # continuous attributes
    + 4 * 6                    # 4 priors x 6 chosen options
)

HEAD_SIZES = {
    "target": len(C.TARGET_NAMES), "trigger": len(C.TRIGGER_NAMES),
    "payload": len(C.PAYLOAD_NAMES), "stealth": len(C.STEALTH_NAMES),
    "abstraction": len(C.ABSTRACTION_NAMES), "channel": len(C.CHANNEL_NAMES),
}


@dataclass
class TrojanGenome:
    target: str
    trigger: str
    payload: str
    stealth: str
    abstraction: str = "rtl_soft_ip"
    channel: str = "standard_io"
    trigger_prob_exp: float = 0.5   # [0,1]
    area_budget: float = 0.3        # [0,1]
    implicit_alpha: float = 0.5     # [0,1] - how normal the output looks when fired
    prop_delay: float = 0.1         # [0,1] - payload propagation delay

    def trigger_bits(self) -> float:
        return 4.0 + self.trigger_prob_exp * 60.0

    def trigger_probability(self) -> float:
        return 2.0 ** (-self.trigger_bits())

    def area_cells(self) -> int:
        base = self.area_budget * C.TrainConfig.device_lc_budget * 0.08
        st = C.STEALTH_IX[self.stealth]
        return int(max(1, base * (0.1 + st.area)))

    def opts(self):
        return (C.TARGET_IX[self.target], C.TRIGGER_IX[self.trigger],
                C.PAYLOAD_IX[self.payload], C.STEALTH_IX[self.stealth],
                C.ABSTRACTION_IX[self.abstraction], C.CHANNEL_IX[self.channel])

    def features(self) -> np.ndarray:
        opts = self.opts()
        priors = np.array([v for o in opts
                           for v in (o.impact, o.rarity, o.area, o.evasion)],
                          dtype=np.float32)
        return np.concatenate([
            _onehot(self.target, C.TARGET_NAMES),
            _onehot(self.trigger, C.TRIGGER_NAMES),
            _onehot(self.payload, C.PAYLOAD_NAMES),
            _onehot(self.stealth, C.STEALTH_NAMES),
            _onehot(self.abstraction, C.ABSTRACTION_NAMES),
            _onehot(self.channel, C.CHANNEL_NAMES),
            np.array([self.trigger_prob_exp, self.area_budget,
                      self.implicit_alpha, self.prop_delay], dtype=np.float32),
            priors,
        ])

    def gid(self) -> str:
        raw = "|".join(str(x) for x in (
            self.target, self.trigger, self.payload, self.stealth,
            self.abstraction, self.channel,
            round(self.trigger_prob_exp, 3), round(self.area_budget, 3),
            round(self.implicit_alpha, 3), round(self.prop_delay, 3)))
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def as_row(self) -> dict:
        d = asdict(self)
        d["gid"] = self.gid()
        d["trigger_bits"] = round(self.trigger_bits(), 1)
        d["area_cells"] = self.area_cells()
        return d

    def copy(self) -> "TrojanGenome":
        return TrojanGenome(**asdict(self))


_FIELDS = ("target", "trigger", "payload", "stealth", "abstraction", "channel",
           "trigger_prob_exp", "area_budget", "implicit_alpha", "prop_delay")


from dataclasses import field


@dataclass
class Constraints:
    """Restrict the design space. In `rtl_only` mode the generator only emits
    insertable, iverilog-verifiable RTL Trojans (what the CSAW event needs)."""
    rtl_only: bool = False
    targets: list | None = None        # restrict to these targets (e.g. one challenge core)

    def triggers(self):
        return C.DIGITAL_TRIGGERS if self.rtl_only else C.TRIGGER_NAMES

    def payloads(self):
        return C.DIGITAL_PAYLOADS if self.rtl_only else C.PAYLOAD_NAMES

    def stealths(self):
        return C.DIGITAL_STEALTH if self.rtl_only else C.STEALTH_NAMES

    def abstractions(self):
        return ["rtl_soft_ip"] if self.rtl_only else C.ABSTRACTION_NAMES

    def channels(self):
        return C.DIGITAL_CHANNELS if self.rtl_only else C.CHANNEL_NAMES

    def target_pool(self):
        return self.targets or C.TARGET_NAMES

    def apply(self, g: "TrojanGenome") -> "TrojanGenome":
        """Snap a genome into the allowed subset (used after focus overrides)."""
        if g.trigger not in self.triggers():
            g.trigger = self.triggers()[0] if g.trigger not in self.triggers() else g.trigger
        if self.rtl_only:
            if g.trigger not in C.DIGITAL_TRIGGERS: g.trigger = "two_block_knock"
            if g.payload not in C.DIGITAL_PAYLOADS: g.payload = "key_exfiltration"
            if g.stealth not in C.DIGITAL_STEALTH: g.stealth = "resource_sharing"
            g.abstraction = "rtl_soft_ip"
            g.channel = "standard_io"
        return g


def random_genome(rng: np.random.Generator, cons: "Constraints | None" = None) -> TrojanGenome:
    cons = cons or Constraints()
    return TrojanGenome(
        target=rng.choice(cons.target_pool()),
        trigger=rng.choice(cons.triggers()),
        payload=rng.choice(cons.payloads()),
        stealth=rng.choice(cons.stealths()),
        abstraction=rng.choice(cons.abstractions()),
        channel=rng.choice(cons.channels()),
        trigger_prob_exp=float(rng.random()),
        area_budget=float(rng.random()),
        implicit_alpha=float(rng.random()),
        prop_delay=float(rng.random()),
    )
