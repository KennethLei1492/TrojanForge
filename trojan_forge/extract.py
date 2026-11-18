"""RTL/netlist -> observable footprint, so the HuntAgent can detect a Trojan in
a *given* design, not just in internally-generated genomes.

Detection is golden-model-relative (the standard pre-silicon setting): extract
structural metrics from a trusted CLEAN RTL and from the SUSPECT RTL, and feed
the *delta* to the detector - exactly the (clean floor) vs (floor + Trojan delta)
representation the HuntAgent trained on. Metrics are lightweight structural
counts (no full synthesis needed):

  area        - logic size proxy (operators, assigns, always blocks, bit-width)
  comparators - number/width of exact-match comparisons (trigger compares)
  extra_state - sequential state (reg/counter/FSM) bits
  timing      - control-path regs that could alter latency

This makes `find a Trojan` work on arbitrary Verilog, including the emitted
cores and real challenge RTL.
"""

from __future__ import annotations

import os
import re

import numpy as np

from .surrogate import OBS_DIM


def extract_metrics(path_or_text: str) -> dict:
    text = path_or_text
    if os.path.isfile(path_or_text):
        with open(path_or_text, "r", errors="ignore") as f:
            text = f.read()
    # strip comments
    text = re.sub(r"//.*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    ops = len(re.findall(r"[\^&|~+\-]|<<|>>|\*", text))
    assigns = len(re.findall(r"\b(assign|<=|=)\b", text))
    always = len(re.findall(r"\balways\b", text))
    regs = re.findall(r"\breg\s*(\[\s*(\d+)\s*:\s*0\s*\])?", text)
    reg_bits = sum(int(m[1]) + 1 if m[1] else 1 for m in regs)
    # exact-match comparisons and their literal widths
    comps = re.findall(r"==\s*\d*'h([0-9a-fA-F]+)", text)
    comp_count = len(re.findall(r"===|==", text))
    comp_bits = max((len(c) * 4 for c in comps), default=0)
    counters = len(re.findall(r"\bcnt\b|\bcounter\b|\+\s*1'b1|\+\s*1\b", text))
    fsm = len(re.findall(r"\bstate\b|\bcase\b|armed", text))
    lines = text.count("\n") + 1
    return {
        "area": ops + assigns + always,
        "reg_bits": reg_bits,
        "comp_count": comp_count,
        "comp_bits": comp_bits,
        "counters": counters,
        "fsm": fsm,
        "lines": lines,
    }


def observable_delta(clean_path: str, suspect_path: str) -> np.ndarray:
    """5-axis footprint delta (suspect - clean), aligned to surrogate.observable."""
    c = extract_metrics(clean_path)
    s = extract_metrics(suspect_path)
    def d(k, scale):
        return max(0.0, (s[k] - c[k]) / scale)
    v = np.array([
        min(1.0, d("area", 40.0)),                 # 0 area overhead
        min(1.0, d("comp_bits", 32.0)),            # 1 comparator width added
        min(1.0, d("comp_count", 4.0)),            # 2 comparator count added
        min(1.0, (d("counters", 3.0) + d("fsm", 3.0)) / 2),  # 3 extra state
        min(1.0, d("reg_bits", 48.0)),             # 4 timing/control regs added
    ], dtype=np.float32)
    return v


def detect_rtl(hunt, clean_path: str, suspect_path: str) -> dict:
    """Run the trained detector on a given (clean, suspect) RTL pair."""
    obs = observable_delta(clean_path, suspect_path)
    p = float(hunt.net.predict(obs)[0, 0])
    return {"observable": obs.round(3).tolist(), "trojan_prob": round(p, 4),
            "flagged": p >= 0.5}
