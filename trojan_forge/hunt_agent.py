"""Track 2 - HUNT. A learnable hardware-Trojan detector.

The detector is a binary classifier over the *observable* netlist footprint
(surrogate.observable): area overhead, comparator width, extra state, timing
deviation - the only things a static scanner can see. It never sees the genome's
categorical identity, so it cannot cheat; it must learn the physical signature.

It co-trains against the HideAgent: every Trojan the generator proposes becomes a
hard positive, and a matched clean design becomes a negative. As Hide learns to
shrink its footprint, Hunt must learn subtler cues - and vice versa. This is the
"use the created trojan to help detect other trojans" requirement, made literal:
the generator's output is the detector's training set.
"""

from __future__ import annotations

import numpy as np

from . import config as C
from . import surrogate, genome as G
from .nn import MLP


class HuntAgent:
    def __init__(self, cfg: C.TrainConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed + 1)
        self.net = MLP(surrogate.OBS_DIM, cfg.hunt_hidden, 1, out_act="sigmoid",
                       lr=cfg.lr, loss="bce", seed=cfg.seed + 1)
        self.seen = 0
        self.tp = self.tn = self.fp = self.fn = 0

    def detect_prob(self, g: G.TrojanGenome) -> float:
        obs = surrogate.observable(g, trojaned=True)
        return float(self.net.predict(obs)[0, 0])

    def clean_prob(self, g: G.TrojanGenome) -> float:
        obs = surrogate.observable(g, trojaned=False)
        return float(self.net.predict(obs)[0, 0])

    def train_on(self, trojan_genomes: list[G.TrojanGenome]) -> dict:
        """One supervised step: Trojan footprints (y=1) vs clean footprints (y=0)."""
        if not trojan_genomes:
            return {"loss": 0.0}
        X, Y = [], []
        for g in trojan_genomes:
            X.append(surrogate.observable(g, trojaned=True)); Y.append([1.0])
            X.append(surrogate.observable(g, trojaned=False)); Y.append([0.0])
        X = np.array(X, dtype=np.float32); Y = np.array(Y, dtype=np.float32)
        loss = self.net.train_step(X, Y)
        # running confusion stats on this batch
        p = self.net.predict(X)[:, 0]
        for pi, yi in zip(p, Y[:, 0]):
            hit = pi >= 0.5
            if yi > 0.5:
                self.tp += hit; self.fn += (not hit)
            else:
                self.fp += hit; self.tn += (not hit)
        self.seen += len(trojan_genomes)
        return {"loss": loss}

    def metrics(self) -> dict:
        tot = self.tp + self.tn + self.fp + self.fn
        if tot == 0:
            return {"acc": 0.0, "precision": 0.0, "recall": 0.0, "seen": self.seen}
        acc = (self.tp + self.tn) / tot
        prec = self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0
        rec = self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0
        return {"acc": round(acc, 4), "precision": round(prec, 4),
                "recall": round(rec, 4), "seen": self.seen}
