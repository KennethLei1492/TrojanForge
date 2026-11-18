"""The hardware-Trojan design space, grounded in the CSAW 2026 submission.

Every enum value below is anchored to something real in
Final-CSAW-2026-Documentation so the learned models optimise over the *same*
space the human team competed in, then push beyond it:

  * TRIGGERS     - how a Trojan decides to fire. Rarer trigger -> stealthier.
                   "two_block_knock" is challenge_1's DEADC0DE->FEEDFACE knock
                   (joint probability 2^-64); "frame_counter" is challenge_3's
                   128-frame FIR bypass; "magic_nonce" is challenge_2 Trojan A.
  * PAYLOADS     - what fires. CVSS anchors from the submission RESULTS tables.
  * TARGETS      - the victim IP. The three CSAW targets plus common cores so the
                   detector/fixer generalise "across all kinds of hardware".
  * STEALTH_TECH - the obfuscation applied so the Trojan evades the detector and
                   stays bit-identical to the clean twin on non-trigger traffic.

Each dimension carries numeric priors (base_impact, base_rarity, base_area,
base_evasion) in [0,1] used by the grounded surrogate (surrogate.py). The
learnable agents do NOT just read these priors - they learn, from the
co-training signal, which *combinations* survive detection while staying
impactful, which is exactly the thing the priors alone cannot tell you.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Option:
    key: str
    # priors in [0,1]
    impact: float = 0.5      # damage if it fires
    rarity: float = 0.5      # how rare/stealthy the trigger condition is
    area: float = 0.5        # logic/area cost (higher = more detectable)
    evasion: float = 0.5     # intrinsic resistance to static detection
    note: str = ""


# --- Trigger mechanisms (how the Trojan decides to fire) ----------------------
TRIGGERS: list[Option] = [
    Option("combinational_constant", impact=0.5, rarity=0.30, area=0.15, evasion=0.25,
           note="fires on a single magic operand; cheap but comparatively easy to find"),
    Option("two_block_knock", impact=0.7, rarity=0.98, area=0.30, evasion=0.80,
           note="challenge_1: enc(DEADC0DE)->enc(FEEDFACE), joint prob 2^-64"),
    Option("frame_counter", impact=0.6, rarity=0.85, area=0.25, evasion=0.70,
           note="challenge_3: time-bomb after N audio frames (128-frame FIR bypass)"),
    Option("magic_nonce", impact=0.85, rarity=0.95, area=0.35, evasion=0.75,
           note="challenge_2 Trojan A: provisioning nonce == magic value"),
    Option("rare_fsm_state", impact=0.6, rarity=0.90, area=0.40, evasion=0.60,
           note="unreachable-under-spec FSM state entered by a crafted sequence"),
    Option("cheat_code_address", impact=0.55, rarity=0.88, area=0.20, evasion=0.65,
           note="access to an undocumented register/address window"),
    Option("temperature_sidechannel", impact=0.5, rarity=0.93, area=0.55, evasion=0.85,
           note="analog/ring-oscillator trigger; very hard to find in RTL sim"),
    Option("counter_plus_data", impact=0.75, rarity=0.96, area=0.45, evasion=0.78,
           note="hybrid: rare data word AND an internal counter threshold"),
]

# --- Payloads (what the Trojan does when it fires) ----------------------------
PAYLOADS: list[Option] = [
    Option("key_exfiltration", impact=0.98, rarity=0.5, area=0.35, evasion=0.55,
           note="challenge_1 / challenge_2A: stream the device key on the read path (CVSS 9.0)"),
    Option("auth_tag_bypass", impact=0.95, rarity=0.5, area=0.30, evasion=0.60,
           note="challenge_2B: force AEAD tag-verify to pass (CVSS 9.0)"),
    Option("forced_nonce_reuse", impact=0.78, rarity=0.5, area=0.25, evasion=0.65,
           note="challenge_2C: pin the nonce so keystream repeats (CVSS 7.1)"),
    Option("data_corruption", impact=0.70, rarity=0.5, area=0.20, evasion=0.70,
           note="challenge_3: bypass the FIR filter so raw/aliased audio passes"),
    Option("denial_of_service", impact=0.60, rarity=0.5, area=0.20, evasion=0.60,
           note="hang BUSY / wedge the FSM on trigger"),
    Option("privilege_escalation", impact=0.88, rarity=0.5, area=0.40, evasion=0.50,
           note="flip an access-control bit to grant an illegal mode"),
    Option("bitflip_fault", impact=0.72, rarity=0.5, area=0.30, evasion=0.58,
           note="inject a fault into a datapath register (DFA-enabling)"),
]

# --- Victim IP cores ("all kinds of hardware") --------------------------------
TARGETS: list[Option] = [
    Option("feistel_crypto_core", impact=0.9, rarity=0.5, area=0.40, evasion=0.5,
           note="challenge_1: 32-bit byte-substitution SPI accelerator"),
    Option("ascon_aead128", impact=0.95, rarity=0.5, area=0.60, evasion=0.5,
           note="challenge_2: EEPROM-keyed AEAD accelerator"),
    Option("fir_audio_filter", impact=0.6, rarity=0.5, area=0.30, evasion=0.5,
           note="challenge_3: 63-tap FIR audio filter"),
    Option("aes128_core", impact=0.95, rarity=0.5, area=0.70, evasion=0.5),
    Option("uart_controller", impact=0.45, rarity=0.5, area=0.15, evasion=0.5),
    Option("spi_peripheral", impact=0.5, rarity=0.5, area=0.18, evasion=0.5),
    Option("i2c_controller", impact=0.5, rarity=0.5, area=0.20, evasion=0.5),
    Option("riscv_rv32i_core", impact=0.9, rarity=0.5, area=0.85, evasion=0.5),
    Option("sha256_core", impact=0.8, rarity=0.5, area=0.65, evasion=0.5),
    Option("dma_engine", impact=0.8, rarity=0.5, area=0.55, evasion=0.5),
]

# --- Stealth / obfuscation techniques (evasion vs the detector) ---------------
STEALTH: list[Option] = [
    Option("param_gated", impact=0.5, rarity=0.5, area=0.10, evasion=0.60,
           note="challenge pattern: whole Trojan behind TROJAN_EN so EN=0 is provably clean"),
    Option("dont_care_encoding", impact=0.5, rarity=0.5, area=0.15, evasion=0.72,
           note="hide logic in unused encodings / don't-care states"),
    Option("resource_sharing", impact=0.5, rarity=0.5, area=0.05, evasion=0.80,
           note="reuse existing adders/muxes so area overhead ~ 0 (hardest to spot)"),
    Option("split_trigger", impact=0.5, rarity=0.5, area=0.30, evasion=0.78,
           note="distribute the trigger across modules so no single signal looks suspicious"),
    Option("timing_matched", impact=0.5, rarity=0.5, area=0.25, evasion=0.68,
           note="pad so BUSY/latency is bit-identical to the clean core"),
    Option("none", impact=0.5, rarity=0.5, area=0.0, evasion=0.20,
           note="unobfuscated baseline - trivially detectable"),
]


# convenient name lists / lookup
def _names(opts: list[Option]) -> list[str]:
    return [o.key for o in opts]


def _index(opts: list[Option]) -> dict[str, Option]:
    return {o.key: o for o in opts}


TRIGGER_NAMES = _names(TRIGGERS)
PAYLOAD_NAMES = _names(PAYLOADS)
TARGET_NAMES = _names(TARGETS)
STEALTH_NAMES = _names(STEALTH)

TRIGGER_IX = _index(TRIGGERS)
PAYLOAD_IX = _index(PAYLOADS)
TARGET_IX = _index(TARGETS)
STEALTH_IX = _index(STEALTH)

DIMS = {
    "trigger": TRIGGER_NAMES,
    "payload": PAYLOAD_NAMES,
    "target": TARGET_NAMES,
    "stealth": STEALTH_NAMES,
}


@dataclass
class TrainConfig:
    """Hyper-parameters for the co-training loop."""
    seed: int = 1337
    # continuous knobs the generator also learns, per genome:
    #   trigger_prob_exp: rarity exponent (how many bits the trigger condition is)
    #   area_budget:      fraction of device LCs the Trojan may spend
    n_cont: int = 2
    # network sizes
    hide_hidden: tuple = (96, 96)
    hunt_hidden: tuple = (128, 64)
    fix_hidden: tuple = (96, 64)
    lr: float = 0.01
    # replay / experience
    buffer_cap: int = 20000
    batch: int = 64
    # self-correction (bounded, external-signal only - Huang et al. 2024)
    max_self_correct: int = 4
    # acceptance thresholds (what counts as an "impactful, stealthy" Trojan)
    stealth_accept: float = 0.75
    impact_accept: float = 0.70
    # exploration
    eps_start: float = 0.9
    eps_end: float = 0.08
    eps_decay_steps: int = 4000
    # how often (in Hide steps) to retrain Hunt and Fix on fresh experience
    hunt_every: int = 1
    fix_every: int = 1
    device_lc_budget: int = 5280   # iCE40-UP5K logic cells (grounds the area/fit check)
