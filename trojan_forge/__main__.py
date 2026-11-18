"""CLI entry point for TrojanForge.

    python -m trojan_forge --steps 2000          # bounded run
    python -m trojan_forge --hours 24            # run 24/7 (time-bounded)
    python -m trojan_forge --forever             # run until Ctrl-C
    python -m trojan_forge --once                # a single Hide/Hunt/Fix episode
    python -m trojan_forge --real-verify-every 200   # audit with real iverilog
    python -m trojan_forge --run-dir runs/myrun  # choose the output folder
"""

from __future__ import annotations

import argparse
import os
import time

from . import config as C
from .orchestrator import run_sync, Orchestrator
from .nn import BACKEND


def main(argv=None):
    p = argparse.ArgumentParser("trojan_forge")
    p.add_argument("--steps", type=int, default=2000)
    p.add_argument("--hours", type=float, default=None)
    p.add_argument("--forever", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--real-verify-every", type=int, default=0)
    p.add_argument("--run-dir", default=None)
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    cfg = C.TrainConfig(seed=a.seed)
    print(f"TrojanForge  (backend={BACKEND})")

    if a.once:
        run_dir = a.run_dir or os.path.join("runs", "once-" + time.strftime("%H%M%S"))
        orch = Orchestrator(cfg, run_dir, real_verify_every=1 if a.real_verify_every else 0)
        ep = orch._episode()
        orch.tracker.record(ep["row"])
        orch.tracker.write_xlsx()
        import json
        print(json.dumps(ep["row"], indent=2, default=str))
        print(f"\nwrote {orch.tracker.csv_path}\n      {orch.tracker.xlsx_path}")
        return 0

    max_seconds = a.hours * 3600 if a.hours else None
    max_steps = None if (a.forever or a.hours) else a.steps
    orch, final = run_sync(cfg=cfg, run_dir=a.run_dir, max_steps=max_steps,
                           max_seconds=max_seconds,
                           real_verify_every=a.real_verify_every, quiet=a.quiet)
    import json
    print("\n=== final ===")
    print(json.dumps(final, indent=2, default=str))
    print(f"\noutputs in: {orch.run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
