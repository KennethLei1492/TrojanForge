"""Checkpoint save/load for the three trained agents, so a model persists across
runs and 24/7 training can resume where it left off.

Backend-agnostic: MLP.state() returns plain numpy arrays (torch backend) or
lists (numpy backend), so a single pickle round-trips either. A checkpoint also
stores step counters and the detector/fixer running stats, and a small JSON
sidecar makes it human-readable.
"""

from __future__ import annotations

import json
import os
import pickle
import time

CKPT = "checkpoint.pkl"
META = "checkpoint.json"


def save(orch, run_dir: str) -> str:
    os.makedirs(run_dir, exist_ok=True)
    blob = {
        "version": 1,
        "steps": orch.steps,
        "best": orch.best,
        "hide": orch.hide.critic.state(),
        "hide_step": orch.hide.step,
        "hunt": orch.hunt.net.state(),
        "hunt_stats": {"tp": orch.hunt.tp, "tn": orch.hunt.tn,
                       "fp": orch.hunt.fp, "fn": orch.hunt.fn, "seen": orch.hunt.seen},
        "fix": orch.fix.q.state(),
        "fix_stats": {"repairs": orch.fix.repairs, "neutralised": orch.fix.neutralised},
    }
    path = os.path.join(run_dir, CKPT)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        pickle.dump(blob, f)
    os.replace(tmp, path)
    with open(os.path.join(run_dir, META), "w") as f:
        json.dump({"steps": orch.steps, "best_reward": orch.best.get("reward"),
                   "hunt": orch.hunt.metrics(), "fix": orch.fix.metrics(),
                   "saved": time.ctime()}, f, indent=2, default=str)
    return path


def load(orch, run_dir: str) -> bool:
    path = os.path.join(run_dir, CKPT)
    if not os.path.isfile(path):
        return False
    with open(path, "rb") as f:
        blob = pickle.load(f)
    orch.steps = blob.get("steps", 0)
    orch.best = blob.get("best", {"reward": -1.0})
    orch.hide.critic.load_state(blob["hide"])
    orch.hide.step = blob.get("hide_step", orch.steps)
    orch.hunt.net.load_state(blob["hunt"])
    hs = blob.get("hunt_stats", {})
    orch.hunt.tp, orch.hunt.tn = hs.get("tp", 0), hs.get("tn", 0)
    orch.hunt.fp, orch.hunt.fn = hs.get("fp", 0), hs.get("fn", 0)
    orch.hunt.seen = hs.get("seen", 0)
    orch.fix.q.load_state(blob["fix"])
    fs = blob.get("fix_stats", {})
    orch.fix.repairs, orch.fix.neutralised = fs.get("repairs", 0), fs.get("neutralised", 0)
    return True
