"""Track 3, made real: patch a Trojaned RTL and PROVE the fix by re-running the
twin-check. The FixAgent picks the action (fix_agent.py); this module applies it
to actual Verilog and re-verifies, closing the loop create -> detect -> repair.

Actions -> RTL transforms (on the emitted Trojan core):
  remove_trigger_logic / resynth_isolated / quarantine_region
        -> excise the Trojan: gate the whole payload off (`if (TROJAN_EN)` ->
           `if (1'b0)`), so the core is provably clean again.
  tie_off_payload
        -> neutralise the payload action only (leak<=0 / out_data normal /
           out_valid follows in_valid / status<=0), leaving trigger logic inert.
  monitor_assertion
        -> add a runtime assertion that TRAPS the trigger but does NOT remove it;
           in simulation the payload still fires, so this detects-but-not-removes
           (reported honestly as not neutralised).

Neutralised := after patching, the twin-check shows the Trojaned twin is once
again bit-identical to the clean twin on the trigger (no divergence) while normal
traffic stays identical.
"""

from __future__ import annotations

import os
import re

from . import toolchain


_BENIGN = {
    "leak <= 32'h8E043CB1;": "leak <= 32'h0;",
    "out_data <= 32'hBADC0DE0;": "out_data <= (in_data <<< 1) ^ (in_data >> 3) ^ acc;",
    "out_valid <= 1'b0;": "out_valid <= in_valid;",
    "status <= 8'h80;": "status <= 8'h0;",
}


def patch_rtl(trojan_path: str, out_path: str, action: str) -> str:
    with open(trojan_path, "r", errors="ignore") as f:
        src = f.read()
    if action in ("remove_trigger_logic", "resynth_isolated", "quarantine_region"):
        patched = src.replace("if (TROJAN_EN) begin", "if (1'b0) begin")
    elif action == "tie_off_payload":
        patched = src
        for bad, good in _BENIGN.items():
            patched = patched.replace(bad, good)
    elif action == "monitor_assertion":
        # add an assertion but leave the payload in place (detect, not remove)
        patched = src.replace(
            "if (fire) begin",
            "if (fire) begin\n                        // synthesis translate_off\n"
            "                        $display(\"[HT-MONITOR] trigger asserted\");\n"
            "                        // synthesis translate_on")
    else:
        patched = src
    with open(out_path, "w") as f:
        f.write(patched)
    return out_path


def verify_neutralised(patched_core: str, tb_path: str, workdir: str) -> dict:
    """Re-run the twin-check with the patched core as the TROJAN_EN=1 twin."""
    if not (toolchain.have("iverilog") and toolchain.have("vvp")):
        return {"available": False}
    res = toolchain.run_twin_check({"trojan": patched_core, "tb": tb_path}, workdir)
    if not res.get("compiles"):
        return {"available": True, "compiles": False, "neutralised": False, "log": res.get("log", "")}
    # neutralised: stealth preserved AND the trigger no longer diverges the twins
    neutralised = bool(res.get("stealthy")) and not bool(res.get("triggers"))
    return {"available": True, "compiles": True,
            "stealthy_preserved": bool(res.get("stealthy")),
            "trigger_still_fires": bool(res.get("triggers")),
            "neutralised": neutralised}


def repair_and_verify(genome, action: str, workdir: str) -> dict:
    """Full real-RTL repair: emit the Trojan, patch it, re-verify neutralisation."""
    from .rtl_emitter import emit_project
    if not toolchain.have("iverilog"):
        return {"available": False}
    paths = emit_project(genome, workdir)
    patched = patch_rtl(paths["trojan"], os.path.join(workdir, "core_patched.v"), action)
    out = verify_neutralised(patched, paths["tb"], workdir)
    out["action"] = action
    out["patched_rtl"] = patched
    return out
