"""Grounded surrogate verifier - the external signal the agents learn against.

Running Icarus Verilog / yosys on every candidate, 24/7, is too slow to drive
millions of gradient steps, so the inner loop scores each genome with a
*grounded analytic surrogate* that reproduces the submission's qualitative
physics:

  * STEALTH rises with trigger rarity (bits), with the stealth technique's
    evasion prior, and with staying inside the device logic-cell budget; it
    falls as area overhead grows (a big Trojan is easy to see).  This mirrors
    the real verifier's "bit-identical to the clean twin on non-trigger traffic
    AND fits the UP5K" criterion.
  * IMPACT is the payload's damage prior lifted by how well it suits the target
    (key-exfil on a crypto core >> key-exfil on a UART), and by the trigger's
    own impact prior.
  * FIT is a hard constraint: area_cells must be <= device budget, like the
    93-95% LC fit the team reported.
  * DETECTABILITY is what a *static* (non-learned) scanner would flag: large
    area, no obfuscation, common trigger.  The learned HuntAgent then tries to
    beat this static baseline, and the HideAgent tries to beat the HuntAgent.

`real_verify()` is the optional ground-truth path: it emits Verilog for the
genome and runs the actual iverilog twin-check when the toolchain is present.
It is used sparsely (to calibrate / audit the surrogate), not on every step.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import config as C
from .genome import TrojanGenome


# target x payload affinity: how damaging this payload is on this target.
# Grounded: exfil/auth/nonce belong on crypto; corruption on the filter; etc.
_AFFINITY = {
    "key_exfiltration": {"feistel_crypto_core": 1.0, "ascon_aead128": 1.0,
                         "aes128_core": 1.0, "sha256_core": 0.7, "riscv_rv32i_core": 0.6,
                         "dma_engine": 0.7},
    "auth_tag_bypass": {"ascon_aead128": 1.0, "aes128_core": 0.9, "sha256_core": 0.8},
    "forced_nonce_reuse": {"ascon_aead128": 1.0, "aes128_core": 0.9},
    "data_corruption": {"fir_audio_filter": 1.0, "dma_engine": 0.8, "uart_controller": 0.7},
    "denial_of_service": {"uart_controller": 0.9, "spi_peripheral": 0.9,
                          "i2c_controller": 0.9, "fir_audio_filter": 0.8},
    "privilege_escalation": {"riscv_rv32i_core": 1.0, "dma_engine": 0.9},
    "bitflip_fault": {"aes128_core": 0.9, "feistel_crypto_core": 0.9,
                      "sha256_core": 0.8, "riscv_rv32i_core": 0.8},
}


def _affinity(payload: str, target: str) -> float:
    return _AFFINITY.get(payload, {}).get(target, 0.35)


@dataclass
class Scorecard:
    stealth: float          # [0,1] - how invisible to inspection + fits device
    impact: float           # [0,1] - damage when it fires
    fits: bool              # hard device constraint
    static_detect: float    # [0,1] - a non-learned scanner's suspicion
    compiles: bool          # surrogate compile check (always True unless pathological)
    area_cells: int
    trigger_bits: float

    def summary(self) -> dict:
        return {
            "stealth": round(self.stealth, 4),
            "impact": round(self.impact, 4),
            "fits": self.fits,
            "static_detect": round(self.static_detect, 4),
            "area_cells": self.area_cells,
            "trigger_bits": round(self.trigger_bits, 1),
        }


def score(g: TrojanGenome) -> Scorecard:
    t, tr, pl, st = g.opts()
    bits = g.trigger_bits()
    area = g.area_cells()
    fits = area <= C.TrainConfig.device_lc_budget

    # --- stealth ---
    rarity = min(1.0, bits / 64.0)                      # 64-bit trigger -> 1.0
    area_pen = min(1.0, area / (0.12 * C.TrainConfig.device_lc_budget))
    stealth = (0.45 * rarity + 0.35 * st.evasion + 0.20 * tr.evasion) * (1.0 - 0.5 * area_pen)
    if not fits:
        stealth *= 0.25                                 # a Trojan that won't fit is useless
    stealth = float(np.clip(stealth, 0.0, 1.0))

    # --- impact ---
    aff = _affinity(pl.key, t.key)
    impact = 0.65 * pl.impact * aff + 0.20 * tr.impact + 0.15 * t.impact
    impact = float(np.clip(impact, 0.0, 1.0))

    # --- static (non-learned) detectability ---
    static = 0.55 * area_pen + 0.30 * (1 - st.evasion) + 0.15 * (1 - rarity)
    if st.key == "none":
        static = min(1.0, static + 0.25)
    static_detect = float(np.clip(static, 0.0, 1.0))

    return Scorecard(stealth, impact, fits, static_detect,
                     compiles=True, area_cells=area, trigger_bits=bits)


OBS_DIM = 5


def _floor(g: TrojanGenome, rng) -> np.ndarray:
    """Benign complexity floor for this target - present in BOTH the clean and
    the Trojaned footprint, so a Trojan can only be spotted by its *delta*."""
    complexity = C.TARGET_IX[g.target].area      # 0.15 (UART) .. 0.85 (RISC-V)
    base = np.array([0.35, 0.30, 0.30, 0.45, 0.10]) * complexity
    return np.clip(base + rng.normal(0.0, 0.06, size=OBS_DIM), 0.0, 1.0)


def observable(g: TrojanGenome, trojaned: bool = True) -> np.ndarray:
    """What a *static netlist scanner* can measure - the only thing the detector
    sees. This is where the adversarial game lives: a stealthy Trojan drives
    these numbers toward the clean region, and the HideAgent is rewarded for it.

      0 area_norm        extra logic as a fraction of a visible budget
      1 trigger_narrow   1 - rarity  (a *common* trigger looks like normal logic
                         to a scanner; a 64-bit knock is a near-zero-probability
                         comparator chain - paradoxically a tell, so scanners
                         flag wide exact-match comparators)
      2 comparators      normalised count of exact-match comparator bits
      3 extra_state      extra FSM/counter state bits (time-bombs add these)
      4 timing_delta     deviation from the clean core's latency fingerprint

    A clean design sits near zero on all five (plus measurement noise).
    """
    rng = np.random.default_rng(abs(hash(g.gid())) % (2**32))
    floor = _floor(g, rng)
    if not trojaned:
        # a clean design is just the benign complexity floor (no Trojan delta)
        return floor.astype(np.float32)
    # the Trojan's *additional* footprint on top of the floor. Obfuscation
    # (stealth technique evasion) and a well-matched design shrink the delta
    # toward zero - and a zero-delta Trojan is, by construction, invisible, which
    # is exactly the hard case the detector must still try to catch.
    t, tr, pl, st = g.opts()
    area_norm = min(1.0, g.area_cells() / (0.12 * C.TrainConfig.device_lc_budget))
    # Combinational footprint depends on the trigger TYPE, not its rarity bits:
    # a two-block knock reaches 2^-64 across time with two small compares (tiny
    # footprint), while a combinational_constant needs a wide, visible match.
    comb = 1.0 - tr.evasion                      # low for knock/nonce, high for constant
    extra_state = 0.6 if g.trigger in ("frame_counter", "counter_plus_data",
                                       "rare_fsm_state") else 0.12
    timing_delta = 0.0 if st.key == "timing_matched" else min(1.0, 0.1 + 0.4 * area_norm)
    shrink = st.evasion
    delta = np.array([
        area_norm * (1 - 0.85 * shrink),
        comb * (1 - 0.6 * shrink),
        comb * (1 - 0.7 * shrink),
        extra_state * (1 - 0.8 * shrink),
        timing_delta * (1 - 0.7 * shrink),
    ])
    return np.clip(floor + delta, 0.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# optional ground-truth path (real iverilog), used sparsely for calibration
# ---------------------------------------------------------------------------
def real_verify(g: TrojanGenome, workdir: str) -> dict:
    """Emit Verilog for the genome and run the real iverilog twin-check.

    Returns {available, compiles, stealthy, triggers, log}. If the toolchain is
    missing, `available=False` and the caller falls back to the surrogate.
    """
    from .rtl_emitter import emit_project
    from . import toolchain
    if not toolchain.have("iverilog"):
        return {"available": False}
    paths = emit_project(g, workdir)
    res = toolchain.run_twin_check(paths, workdir)
    res["available"] = True
    return res
