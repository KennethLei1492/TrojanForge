"""CLI entry point for TrojanForge.

Training:
    python -m trojan_forge --steps 2000              # bounded run
    python -m trojan_forge --hours 24                # time-bounded 24/7
    python -m trojan_forge --forever                 # run until killed
    python -m trojan_forge --rtl-only                # only insertable, iverilog-
                                                     #   verifiable RTL Trojans
    python -m trojan_forge --rtl-only --target ascon_aead128 --payload key_exfiltration
    python -m trojan_forge --load runs/prev --run-dir runs/prev   # resume a checkpoint
    python -m trojan_forge --once                    # one Hide/Hunt/Fix episode
    python -m trojan_forge --real-verify-every 200   # audit with real iverilog

Event task (produce ONE verified RTL Trojan for a given core, then prove a fix):
    python -m trojan_forge task --target feistel_crypto_core --payload key_exfiltration
"""

from __future__ import annotations

import argparse
import json
import os
import time

from . import config as C
from . import genome as G
from .orchestrator import run_sync, Orchestrator
from .nn import BACKEND


def _focus(target, payload):
    f = {}
    if target:
        f["focus_target"] = target
    if payload:
        f["focus_payload"] = payload
    return f


def cmd_task(a):
    """Given a task, CREATE a verified RTL Trojan, FIND it, and prove a FIX."""
    from . import surrogate, remediate, extract
    from .rtl_emitter import emit_project
    cfg = C.TrainConfig(seed=a.seed)
    cons = G.Constraints(rtl_only=True, targets=[a.target] if a.target else None)
    run_dir = a.run_dir or os.path.join("runs", "task-" + time.strftime("%H%M%S"))
    orch = Orchestrator(cfg, run_dir, constraints=cons, focus=_focus(a.target, a.payload))
    if a.load:
        orch.load(a.load)
    else:
        print(f"training briefly (rtl-only) for task... backend={BACKEND}")
        for _ in range(a.train_steps):
            ep = orch._episode()
            orch.tracker.add_experience(ep["feats"], ep["reward"], ep["genome"],
                                        ep["fix_feats"], ep["fix_action"], ep["fix_reward"])
            orch.steps += 1
            f, r = orch.tracker.hide_batch(cfg.batch)
            if f is not None: orch.hide.learn(f, r)
            gs = orch.tracker.hunt_batch(cfg.batch)
            if gs: orch.hunt.train_on(gs)
            fb = orch.tracker.fix_batch(cfg.batch)
            if fb[0]: orch.fix.learn(*fb)

    res = orch.hide.propose(orch.hunt, focus=_focus(a.target, a.payload))
    g = res.output
    print("\n[CREATE] design:", json.dumps(g.as_row(), indent=2, default=str))
    wd = os.path.join(run_dir, "rtl", g.gid())
    paths = emit_project(g, wd)
    real = surrogate.real_verify(g, wd)
    print(f"[CREATE] real iverilog: compiles={real.get('compiles')} "
          f"stealthy={real.get('stealthy')} triggers={real.get('triggers')} "
          f"allpass={real.get('allpass')}   RTL: {paths['trojan']}")

    find = extract.detect_rtl(orch.hunt, paths["clean"], paths["trojan"])
    print(f"[FIND]   detector on (clean vs trojaned) RTL: prob={find['trojan_prob']} "
          f"flagged={find['flagged']}")

    act_idx = orch.fix.choose(g, explore=0.0)
    from .fix_agent import ACTIONS
    action = ACTIONS[act_idx]
    fix = remediate.repair_and_verify(g, action, wd)
    print(f"[FIX]    action={action} -> neutralised={fix.get('neutralised')} "
          f"stealth_preserved={fix.get('stealthy_preserved')} "
          f"still_fires={fix.get('trigger_still_fires')}   patched: {fix.get('patched_rtl')}")
    orch.save()
    print(f"\noutputs + checkpoint in: {run_dir}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser("trojan_forge")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("task", help="produce one verified RTL Trojan + fix for a target")
    t.add_argument("--target", default=None)
    t.add_argument("--payload", default=None)
    t.add_argument("--train-steps", type=int, default=1500)
    t.add_argument("--load", default=None)
    t.add_argument("--run-dir", default=None)
    t.add_argument("--seed", type=int, default=1337)

    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--hours", type=float, default=None)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--rtl-only", action="store_true")
    p.add_argument("--target", default=None)
    p.add_argument("--payload", default=None)
    p.add_argument("--load", default=None)
    p.add_argument("--real-verify-every", type=int, default=0)
    p.add_argument("--run-dir", default=None)
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "task":
        return cmd_task(a)

    cfg = C.TrainConfig(seed=a.seed)
    cons = G.Constraints(rtl_only=a.rtl_only, targets=[a.target] if a.target else None)
    focus = _focus(a.target, a.payload)
    print(f"TrojanForge  (backend={BACKEND}, rtl_only={a.rtl_only})")

    if a.once:
        run_dir = a.run_dir or os.path.join("runs", "once-" + time.strftime("%H%M%S"))
        orch = Orchestrator(cfg, run_dir, constraints=cons, focus=focus,
                            real_verify_every=1 if a.real_verify_every else 0)
        ep = orch._episode()
        orch.tracker.record(ep["row"])
        orch.tracker.write_xlsx()
        print(json.dumps(ep["row"], indent=2, default=str))
        print(f"\nwrote {orch.tracker.csv_path}\n      {orch.tracker.xlsx_path}")
        return 0

    max_seconds = a.hours * 3600 if a.hours else None
    max_steps = None if (a.forever or a.hours) else a.steps
    orch, final = run_sync(cfg=cfg, run_dir=a.run_dir, max_steps=max_steps,
                           max_seconds=max_seconds, real_verify_every=a.real_verify_every,
                           quiet=a.quiet, constraints=cons, focus=focus, load_dir=a.load)
    print("\n=== final ===")
    print(json.dumps(final, indent=2, default=str))
    print(f"\noutputs in: {orch.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
