"""Track 1 - HIDE. A learnable Trojan generator with bounded self-correction.

The agent is a *critic* MLP that predicts the co-training reward of a genome
from its features. To produce a Trojan it:

  1. PLANS (pipeline_core.plan_then_act): picks a strategy - which target family
     and payload class to pursue this step - from the task request.
  2. PROPOSES: samples a batch of candidate genomes consistent with the plan,
     scores each with the critic, and takes the argmax (epsilon-greedy).
  3. SELF-CORRECTS: this is the core requirement. It reads *external signals*
     only - the grounded surrogate scorecard and the current detector's verdict -
     and revises the weakest dimension, for at most `max_self_correct` rounds.
     This is exactly the bounded, external-signal-gated self-correction the
     prebuilt answer_verification_model prescribes (Huang et al. 2024): the model
     is NOT allowed to "correct" from its own say-so, only from a verifier.

The reward it learns toward couples all three tracks:

    reward = impact * stealth * fits * evasion(detector)

so improving the Trojan means staying impactful AND fitting the device AND
fooling the *current* HuntAgent - a moving target, which is what forces the
whole system to keep improving instead of converging.
"""

from __future__ import annotations

import numpy as np

from . import config as C
from . import surrogate, genome as G
from .nn import MLP
from .pipeline_core import TaskRequest, TaskResult, Status, plan_then_act


def reward(sc: surrogate.Scorecard, evasion: float) -> float:
    """Scalar objective the generator maximises (all three tracks coupled)."""
    base = sc.impact * sc.stealth
    return float(np.clip(base * (0.5 + 0.5 * evasion) * (1.0 if sc.fits else 0.2), 0, 1))


class HideAgent:
    def __init__(self, cfg: C.TrainConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed)
        self.critic = MLP(G.FEATURE_DIM, cfg.hide_hidden, 1, out_act="sigmoid",
                          lr=cfg.lr, loss="mse", seed=cfg.seed)
        self.step = 0

    # -- plan-then-act: choose a focus for this proposal --------------------
    def _plan(self, req: TaskRequest) -> dict:
        focus_payload = req.meta.get("focus_payload")
        focus_target = req.meta.get("focus_target")
        return {
            "strategy": "evade_then_impact",
            "focus_payload": focus_payload,
            "focus_target": focus_target,
            "self_correct_budget": self.cfg.max_self_correct,
        }

    def _epsilon(self) -> float:
        c = self.cfg
        frac = min(1.0, self.step / c.eps_decay_steps)
        return c.eps_start + (c.eps_end - c.eps_start) * frac

    def _sample_candidate(self, plan: dict) -> G.TrojanGenome:
        g = G.random_genome(self.rng)
        if plan.get("focus_payload"):
            g.payload = plan["focus_payload"]
        if plan.get("focus_target"):
            g.target = plan["focus_target"]
        return g

    def _critic_score(self, g: G.TrojanGenome) -> float:
        return float(self.critic.predict(g.features())[0, 0])

    def _act(self, req: TaskRequest, plan: dict) -> TaskResult:
        detector = req.payload["detector"]           # HuntAgent (for evasion signal)
        eps = self._epsilon()
        # ---- propose: best-of-N under the critic (epsilon-greedy) ----
        cands = [self._sample_candidate(plan) for _ in range(24)]
        if self.rng.random() < eps:
            g = self.rng.choice(cands)
        else:
            g = max(cands, key=self._critic_score)
        trace = []
        # ---- bounded self-correction on EXTERNAL signals only ----
        for rnd in range(plan["self_correct_budget"] + 1):
            sc = surrogate.score(g)
            evasion = 1.0 - detector.detect_prob(g)
            r = reward(sc, evasion)
            trace.append({"round": rnd, "gid": g.gid(), **sc.summary(),
                          "evasion": round(evasion, 4), "reward": round(r, 4)})
            accept = (sc.stealth >= self.cfg.stealth_accept
                      and sc.impact >= self.cfg.impact_accept
                      and sc.fits and evasion >= 0.5)
            if accept or rnd == plan["self_correct_budget"]:
                break
            g = self._revise(g, sc, evasion, detector)   # external-signal-gated
        status = Status.SUCCESS if accept else Status.NEEDS_REVIEW
        return TaskResult(status=status, output=g, evidence=trace,
                          confidence=r, steps=len(trace),
                          usage={"reward": r, "stealth": sc.stealth,
                                 "impact": sc.impact, "evasion": evasion,
                                 "fits": sc.fits, "scorecard": sc})

    _LOWER_LAYER = {"rtl_soft_ip": "gate_firm_ip", "gate_firm_ip": "transistor_hard_ip",
                    "transistor_hard_ip": "layout_physical", "layout_physical": "layout_physical"}

    def _revise(self, g, sc, evasion, detector):
        """Fix the single weakest external signal. No self-generated 'fixes'."""
        new = g.copy()
        if not sc.fits or sc.area_cells > 0.1 * self.cfg.device_lc_budget:
            new.area_budget = max(0.05, g.area_budget * 0.6)        # shrink to fit
            new.stealth = "resource_sharing"                         # ~0-area obfuscation
        elif evasion < 0.5:
            # detector is catching us -> push to a lower layer / stronger obfuscation
            new.stealth = max(C.STEALTH, key=lambda o: o.evasion).key
            new.abstraction = self._LOWER_LAYER[g.abstraction]
            new.trigger_prob_exp = min(1.0, g.trigger_prob_exp + 0.2)
        elif sc.stealth < self.cfg.stealth_accept:
            new.trigger_prob_exp = min(1.0, g.trigger_prob_exp + 0.15)
            new.implicit_alpha = min(1.0, g.implicit_alpha + 0.2)    # look more normal when fired
        elif sc.impact < self.cfg.impact_accept:
            best = max(C.PAYLOADS, key=lambda o: surrogate._affinity(o.key, g.target) * o.impact)
            new.payload = best.key
            new.prop_delay = max(0.0, g.prop_delay - 0.2)            # fire sooner -> more impact
        return new

    def propose(self, detector, focus=None) -> TaskResult:
        meta = focus or {}
        req = TaskRequest(kind="hide", payload={"detector": detector}, meta=meta)
        res = plan_then_act(self._plan, self._act, req)
        self.step += 1
        return res

    def learn(self, feats: np.ndarray, rewards: np.ndarray) -> float:
        """Train the critic to predict realised reward from genome features."""
        return self.critic.train_step(feats, rewards.reshape(-1, 1))
