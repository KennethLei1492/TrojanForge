"""The 24/7 co-training orchestrator - Hide || Hunt || Fix, asynchronously.

Three asyncio workers share one experience buffer (tracker.py) and run forever
(or for a fixed step/time budget):

  * HIDE worker  - proposes a Trojan (with bounded self-correction), evaluates it
                   against the current detector, records the episode, and pushes
                   experience. This is the create step.
  * HUNT worker  - continuously retrains the detector on the newest Trojans vs
                   clean twins from the buffer. This is the detect step, trained
                   on the generator's own output.
  * FIX worker   - continuously retrains the remediation policy on repair
                   outcomes. This is the fix step.

Because all three share the buffer and run concurrently, improving one pressures
the others: a stealthier generator degrades the detector's recall, which the
detector then recovers, which pushes the generator again - the self-improving
adversarial loop the brief asks for ("create, detect, and exploit the weaknesses
all in one, constantly training itself to improve").

Parallelism / batching inside a step uses pipeline_core.BoundedExecutor, the
prebuilt parallelization model. A periodic checkpoint writes the live
spreadsheet and a JSON status file.
"""

from __future__ import annotations

import asyncio
import json
import os
import time

import numpy as np

from . import config as C
from . import surrogate, genome as G
from .hide_agent import HideAgent, reward as hide_reward
from .hunt_agent import HuntAgent
from .fix_agent import FixAgent, ACTIONS
from .tracker import Tracker
from .pipeline_core import ResponseCache, BoundedExecutor, self_consistency


class Orchestrator:
    def __init__(self, cfg: C.TrainConfig, run_dir: str,
                 real_verify_every: int = 0, constraints=None, focus=None):
        self.cfg = cfg
        self.run_dir = run_dir
        self.constraints = constraints or G.Constraints()
        self.focus = focus or {}
        self.hide = HideAgent(cfg, self.constraints)
        self.hunt = HuntAgent(cfg)
        self.fix = FixAgent(cfg)
        self.tracker = Tracker(cfg, run_dir)
        self.cache = ResponseCache(cap=8192, ttl=7200)
        self.executor = BoundedExecutor(max_workers=4, retries=1)
        self.real_verify_every = real_verify_every
        self.rng = np.random.default_rng(cfg.seed + 7)
        self.steps = 0
        self.best = {"reward": -1.0}
        self._stop = False
        self._lock = asyncio.Lock()

    # ---- one HIDE episode (create -> evaluate -> maybe fix -> record) -----
    def _episode(self) -> dict:
        # a fixed task (self.focus) pins the target/payload; otherwise rotate
        # coverage over the allowed pools so every target/trigger is exercised.
        focus = dict(self.focus)
        if not focus.get("focus_target") and self.rng.random() < 0.4:
            focus["focus_target"] = self.rng.choice(self.constraints.target_pool())
        if not focus.get("focus_payload") and self.rng.random() < 0.4:
            focus["focus_payload"] = self.rng.choice(self.constraints.payloads())
        res = self.hide.propose(self.hunt, focus=focus)
        g = res.output
        sc = res.usage["scorecard"]
        det_p = self.hunt.detect_prob(g)
        evasion = 1.0 - det_p
        r = hide_reward(sc, evasion)
        accepted = res.status.value == "SUCCESS"

        # FIX: if the Trojan is real (fits + impactful), try to repair it
        fix = {}
        fix_feats = fix_action = fix_r = None
        if sc.fits and sc.impact >= 0.4:
            fix = self.fix.repair(g, explore=max(0.05, self.hide._epsilon() * 0.5))
            fix_feats = g.features()
            fix_action = fix["action_idx"]
            fix_r = fix["fix_reward"]

        # REAL verify (sparse ground-truth audit of the surrogate)
        real = {"available": False}
        if self.real_verify_every and self.steps % self.real_verify_every == 0:
            wd = os.path.join(self.run_dir, "rtl", g.gid())
            try:
                real = surrogate.real_verify(g, wd)
            except Exception as exc:
                real = {"available": False, "error": str(exc)}

        row = {
            "ts": round(time.time(), 2), "step": self.steps, "gid": g.gid(),
            "target": g.target, "trigger": g.trigger, "payload": g.payload,
            "stealth": g.stealth, "abstraction": g.abstraction, "channel": g.channel,
            "baseline": (g.trigger in C.BASELINE["triggers"]
                         or g.payload in C.BASELINE["payloads"]
                         or g.target in C.BASELINE["targets"]),
            "implicit_alpha": round(g.implicit_alpha, 3), "prop_delay": round(g.prop_delay, 3),
            "trigger_bits": round(g.trigger_bits(), 1),
            "trigger_prob": f"2^-{g.trigger_bits():.0f}",
            "area_cells": sc.area_cells, "fits": sc.fits,
            "stealth_score": round(sc.stealth, 4), "impact": round(sc.impact, 4),
            "static_detect": round(sc.static_detect, 4),
            "detector_prob": round(det_p, 4), "evasion": round(evasion, 4),
            "reward": round(r, 4), "accepted": accepted,
            "self_correct_rounds": res.steps - 1,
            "fix_action": fix.get("action", ""),
            "fix_neutralised": fix.get("neutralised", ""),
            "fix_collateral": fix.get("collateral", ""),
            "fix_reward": fix.get("fix_reward", ""),
            "real_verify": real.get("available", False),
            "real_stealthy": real.get("stealthy", ""),
            "real_triggers": real.get("triggers", ""),
        }
        return {"row": row, "feats": g.features(), "reward": r, "genome": g,
                "fix_feats": fix_feats, "fix_action": fix_action, "fix_reward": fix_r}

    async def hide_worker(self):
        while not self._stop:
            # produce a small wave of episodes in parallel (BoundedExecutor)
            eps = await asyncio.to_thread(
                self.executor.map, lambda _: self._episode(), list(range(4)))
            async with self._lock:
                for e in eps:
                    if "error" in e:
                        continue
                    self.tracker.record(e["row"])
                    self.tracker.add_experience(
                        e["feats"], e["reward"], e["genome"],
                        e["fix_feats"], e["fix_action"], e["fix_reward"])
                    if e["reward"] > self.best["reward"]:
                        self.best = {"reward": e["reward"], **e["row"]}
                    self.steps += 1
                # train the HIDE critic on replayed experience
                feats, rew = self.tracker.hide_batch(self.cfg.batch)
                if feats is not None:
                    self.hide.learn(feats, rew)
            await asyncio.sleep(0)

    async def hunt_worker(self):
        while not self._stop:
            async with self._lock:
                gs = self.tracker.hunt_batch(self.cfg.batch)
            if gs:
                await asyncio.to_thread(self.hunt.train_on, gs)
            await asyncio.sleep(0.001)

    async def fix_worker(self):
        while not self._stop:
            async with self._lock:
                fb = self.tracker.fix_batch(self.cfg.batch)
            if fb[0]:
                await asyncio.to_thread(self.fix.learn, *fb)
            await asyncio.sleep(0.001)

    def save(self, run_dir=None):
        from . import persistence
        return persistence.save(self, run_dir or self.run_dir)

    def load(self, run_dir):
        from . import persistence
        return persistence.load(self, run_dir)

    async def checkpoint_worker(self, every=5.0):
        while not self._stop:
            await asyncio.sleep(every)
            async with self._lock:
                self.tracker.write_xlsx()
                self._write_status()
                self.save()

    def _write_status(self):
        status = {
            "steps": self.steps,
            "trojans_logged": self.tracker.n,
            "best": self.best,
            "hunt": self.hunt.metrics(),
            "fix": self.fix.metrics(),
            "cache": {"hits": self.cache.hits, "misses": self.cache.misses},
            "backend": __import__("trojan_forge.nn", fromlist=["BACKEND"]).BACKEND,
            "updated": time.ctime(),
        }
        with open(os.path.join(self.run_dir, "status.json"), "w") as f:
            json.dump(status, f, indent=2, default=str)
        return status

    async def run(self, max_steps=None, max_seconds=None, quiet=False):
        start = time.time()
        workers = [asyncio.create_task(w) for w in (
            self.hide_worker(), self.hunt_worker(), self.fix_worker(),
            self.checkpoint_worker())]

        async def monitor():
            last = 0
            while not self._stop:
                await asyncio.sleep(2.0)
                if not quiet and self.steps != last:
                    m = self.hunt.metrics(); fm = self.fix.metrics()
                    print(f"[{self.steps:>7} steps] best_reward={self.best['reward']:.3f} "
                          f"hunt_acc={m['acc']:.2f} recall={m['recall']:.2f} "
                          f"fix_rate={fm['neutralise_rate']:.2f} "
                          f"logged={self.tracker.n}")
                    last = self.steps
                if max_steps and self.steps >= max_steps:
                    self._stop = True
                if max_seconds and time.time() - start >= max_seconds:
                    self._stop = True

        mon = asyncio.create_task(monitor())
        try:
            await mon
        finally:
            self._stop = True
            for w in workers:
                w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            async with self._lock:
                self.tracker.write_xlsx()
                final = self._write_status()
                self.save()
        return final


def run_sync(cfg=None, run_dir=None, max_steps=2000, max_seconds=None,
             real_verify_every=0, quiet=False, constraints=None, focus=None,
             load_dir=None):
    cfg = cfg or C.TrainConfig()
    if run_dir is None:
        run_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "runs", time.strftime("%Y%m%d-%H%M%S"))
    orch = Orchestrator(cfg, run_dir, real_verify_every=real_verify_every,
                        constraints=constraints, focus=focus)
    if load_dir and orch.load(load_dir):
        print(f"resumed from checkpoint: {load_dir} (step {orch.steps})")
    final = asyncio.run(orch.run(max_steps=max_steps, max_seconds=max_seconds,
                                 quiet=quiet))
    return orch, final
