"""Track 3 - FIX. A learnable remediation policy.

Given a Trojan the HuntAgent has flagged, the FixAgent chooses a remediation
action. It is a Q-network: MLP(genome features -> value per action). It picks the
action with the highest predicted neutralisation value, applies it, and is
rewarded by the grounded outcome:

    fix_reward = neutralised * (1 - collateral)

where `neutralised` means the payload can no longer fire and `collateral` is how
much legitimate function the patch disturbs (a good fix removes the Trojan
without changing the clean behaviour - the same bar challenge_3's remediation
had to meet). The efficacy of each action depends on the payload class, grounded
in how these attacks are actually removed:

  * tie_off_payload        - force the payload's output net to its benign value
  * remove_trigger_logic   - excise the comparator/FSM that arms the Trojan
  * monitor_assertion      - add a runtime assertion that traps the trigger
  * resynth_isolated       - resynthesise with the suspect region resource-isolated
  * quarantine_region      - fence off the region / gate its outputs

The policy learns which action neutralises which payload with least collateral,
closing the loop: Hide makes damage, Hunt finds it, Fix repairs it.
"""

from __future__ import annotations

import numpy as np

from . import config as C
from . import genome as G
from .nn import MLP

ACTIONS = ["tie_off_payload", "remove_trigger_logic", "monitor_assertion",
           "resynth_isolated", "quarantine_region"]

# grounded efficacy: P(neutralise), collateral per (action, payload-class)
# payload classes: exfil, bypass, corruption, dos, fault
_CLASS = {
    "key_exfiltration": "exfil", "auth_tag_bypass": "bypass",
    "privilege_escalation": "bypass", "forced_nonce_reuse": "bypass",
    "data_corruption": "corruption", "denial_of_service": "dos",
    "bitflip_fault": "fault",
}
#               (neutralise, collateral)
_EFFICACY = {
    "tie_off_payload":      {"exfil": (0.95, 0.05), "bypass": (0.80, 0.10),
                             "corruption": (0.70, 0.20), "dos": (0.55, 0.15),
                             "fault": (0.75, 0.15)},
    "remove_trigger_logic": {"exfil": (0.85, 0.15), "bypass": (0.85, 0.15),
                             "corruption": (0.80, 0.15), "dos": (0.80, 0.10),
                             "fault": (0.80, 0.15)},
    "monitor_assertion":    {"exfil": (0.60, 0.02), "bypass": (0.60, 0.02),
                             "corruption": (0.65, 0.03), "dos": (0.90, 0.05),
                             "fault": (0.70, 0.04)},
    "resynth_isolated":     {"exfil": (0.75, 0.25), "bypass": (0.75, 0.25),
                             "corruption": (0.78, 0.22), "dos": (0.70, 0.20),
                             "fault": (0.82, 0.20)},
    "quarantine_region":    {"exfil": (0.88, 0.30), "bypass": (0.88, 0.30),
                             "corruption": (0.85, 0.28), "dos": (0.92, 0.25),
                             "fault": (0.80, 0.30)},
}


def apply_fix(action: str, g: G.TrojanGenome, rng: np.random.Generator) -> dict:
    """Grounded outcome of applying `action` to Trojan `g`."""
    cls = _CLASS.get(g.payload, "fault")
    neut_p, coll = _EFFICACY[action][cls]
    # harder-to-reach triggers are harder to excise/tie-off
    neut_p *= (1.0 - 0.15 * min(1.0, g.trigger_bits() / 64.0))
    neutralised = rng.random() < neut_p
    collateral = coll * (0.6 + 0.4 * g.area_budget)
    fix_reward = (1.0 if neutralised else 0.0) * (1.0 - collateral)
    return {"action": action, "neutralised": bool(neutralised),
            "collateral": round(float(collateral), 4),
            "fix_reward": round(float(fix_reward), 4)}


class FixAgent:
    def __init__(self, cfg: C.TrainConfig):
        self.cfg = cfg
        self.rng = np.random.default_rng(cfg.seed + 2)
        self.q = MLP(G.FEATURE_DIM, cfg.fix_hidden, len(ACTIONS),
                     out_act="sigmoid", lr=cfg.lr, loss="mse", seed=cfg.seed + 2)
        self.repairs = 0
        self.neutralised = 0

    def choose(self, g: G.TrojanGenome, explore=0.1) -> int:
        if self.rng.random() < explore:
            return int(self.rng.integers(len(ACTIONS)))
        return int(np.argmax(self.q.predict(g.features())[0]))

    def repair(self, g: G.TrojanGenome, explore=0.1) -> dict:
        a = self.choose(g, explore)
        outcome = apply_fix(ACTIONS[a], g, self.rng)
        outcome["action_idx"] = a
        self.repairs += 1
        self.neutralised += outcome["neutralised"]
        return outcome

    def learn(self, feats_list, action_idxs, rewards) -> float:
        """Train Q toward the realised fix reward for the taken action only."""
        if not feats_list:
            return 0.0
        X = np.array(feats_list, dtype=np.float32)
        target = self.q.predict(X)                 # start from current estimates
        for i, (a, r) in enumerate(zip(action_idxs, rewards)):
            target[i, a] = r                       # supervise only the taken action
        return self.q.train_step(X, target)

    def metrics(self) -> dict:
        rate = self.neutralised / self.repairs if self.repairs else 0.0
        return {"repairs": self.repairs, "neutralise_rate": round(rate, 4)}
