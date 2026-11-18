"""Thin wrapper over Icarus Verilog (and yosys) - the real ground-truth path.

Mirrors the role of challenge_1/pipeline/common/toolchain.py: compile + run a
self-checking testbench and read its verdict. Only used to audit/calibrate the
surrogate, so missing tools are non-fatal.
"""

from __future__ import annotations

import os
import shutil
import subprocess


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd, cwd, timeout=120):
    try:
        p = subprocess.run(cmd, cwd=cwd, text=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=timeout, check=False)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired as exc:
        return 124, f"[timeout] {exc}\n"
    except FileNotFoundError as exc:
        return 127, f"[missing] {exc}\n"


def run_twin_check(paths: dict, workdir: str, timeout: int = 120) -> dict:
    """Compile the emitted sources + testbench and parse the verdict.

    The emitted testbench prints:
      [STEALTH-OK]  non-trigger traffic is bit-identical between twins
      [TRIGGER-OK]  the trigger fired and the payload diverged the Trojaned twin
      TF: ALL PASS  both held
    """
    if not (have("iverilog") and have("vvp")):
        return {"available": False}
    workdir = os.path.abspath(workdir)
    out = os.path.join(workdir, "twin.vvp")
    # The Trojan core is parameterised by TROJAN_EN; the TB instantiates it twice
    # (EN=0 clean twin vs EN=1 Trojaned). Compiling the separate clean file too
    # would duplicate `module core`, so only the parameterised core + TB go in.
    # Resolve to absolute paths so a relative run-dir still compiles (cwd=workdir).
    srcs = [os.path.abspath(paths["trojan"]), os.path.abspath(paths["tb"])]
    rc, log = _run(["iverilog", "-g2012", "-o", out, "-s", "tb_twin", *srcs], workdir, timeout)
    if rc != 0:
        return {"available": True, "compiles": False, "stealthy": False,
                "triggers": False, "log": log}
    rc2, run = _run(["vvp", out], workdir, timeout)
    log += "\n" + run
    return {
        "available": True,
        "compiles": True,
        "stealthy": "[STEALTH-OK]" in run,
        "triggers": "[TRIGGER-OK]" in run,
        "allpass": "TF: ALL PASS" in run,
        "log": log,
    }


def ice40_area(sources, top, workdir, timeout=300) -> dict:
    if not have("yosys"):
        return {"available": False}
    script = f"read_verilog -sv {' '.join(sources)}; synth_ice40 -top {top}; stat"
    rc, log = _run(["yosys", "-q", "-p", script], workdir, timeout)
    cells = None
    for line in log.splitlines():
        if "Number of cells" in line:
            try:
                cells = int(line.split(":")[1])
            except Exception:
                pass
    return {"available": True, "ok": rc == 0, "cells": cells, "log": log}
