"""The hardware-Trojan design space.

The CSAW 2026 submission designs are the **baseline** (flagged `baseline=True`);
the rest of the space is drawn from the public hardware-Trojan literature so the
generator can produce *all kinds* of Trojans across *all kinds* of hardware, and
the detector/fixer generalise far beyond the three competition cores.

Sources grounding the taxonomy (see SOURCES.md for the full list):
  * Tehranipoor & Koushanfar, "A Survey of Hardware Trojan Taxonomy and
    Detection," IEEE Design & Test, 2010 - the 5-axis taxonomy: insertion phase,
    abstraction level, activation (trigger), effect (payload), location.
  * Trust-Hub.org benchmark suite + Taxonomy.pdf - 17 design classes (AES, DES,
    RSA, PIC, MC8051, RS-232, memctrl, wb_conmax, Ethernet, ISCAS89 s-series,
    ITC99 b-series, ...) and the always-on / triggered (internal/external)
    activation split.
  * Yang et al., "A2: Analog Malicious Hardware," IEEE S&P 2016 - the analog
    charge-accumulation trigger and privilege-escalation payload.
  * Shakya/Cruz et al. & the "Advancing the State-of-the-Art in HT Design"
    formal model (arXiv:1605.08413) - trigger signal dimension d, payload
    propagation delay t, implicit-behaviour factor alpha, St vs Si channel.

A genome therefore spans SIX categorical axes (target, trigger, payload, stealth,
abstraction level, payload channel) plus FOUR continuous attributes
(trigger rarity bits, area budget, implicit-alpha, propagation delay). Each
option carries grounded numeric priors in [0,1]; the agents learn which
*combinations* survive detection while staying impactful.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Option:
    key: str
    impact: float = 0.5      # damage if it fires
    rarity: float = 0.5      # how rare/stealthy the trigger condition is
    area: float = 0.5        # logic/area cost (higher = more detectable)
    evasion: float = 0.5     # intrinsic resistance to static (RTL/gate) detection
    baseline: bool = False   # True => part of the CSAW 2026 baseline submission
    source: str = ""         # short provenance tag
    note: str = ""


# --- Trigger mechanisms -------------------------------------------------------
# CSAW baselines first, then the broader literature.
TRIGGERS: list[Option] = [
    # ---- CSAW 2026 baseline ----
    Option("two_block_knock", impact=0.70, rarity=0.98, area=0.30, evasion=0.80,
           baseline=True, source="CSAW ch1",
           note="enc(DEADC0DE)->enc(FEEDFACE) sequence, joint prob 2^-64"),
    Option("magic_nonce", impact=0.85, rarity=0.95, area=0.35, evasion=0.75,
           baseline=True, source="CSAW ch2",
           note="provisioning nonce == magic value"),
    Option("frame_counter", impact=0.60, rarity=0.85, area=0.25, evasion=0.70,
           baseline=True, source="CSAW ch3",
           note="time-bomb after N audio frames (128-frame FIR bypass)"),
    # ---- condition-based / combinational (Trust-Hub) ----
    Option("combinational_constant", impact=0.50, rarity=0.30, area=0.15, evasion=0.25,
           source="Trust-Hub", note="single magic operand; a bare comparator, easy to find"),
    Option("rare_data_pattern", impact=0.55, rarity=0.70, area=0.20, evasion=0.45,
           source="Trust-Hub", note="uncommon but reachable data word on a bus"),
    Option("cheat_code_address", impact=0.55, rarity=0.88, area=0.20, evasion=0.65,
           source="Trust-Hub", note="access to an undocumented register/address window"),
    Option("comparator_wide", impact=0.55, rarity=0.90, area=0.55, evasion=0.30,
           source="arXiv:1605.08413", note="wide exact-match compare (large d); rare but a visible tell"),
    # ---- time/sequence-based (counters, FSMs) ----
    Option("lfsr_counter", impact=0.65, rarity=0.92, area=0.30, evasion=0.72,
           source="arXiv:1605.08413", note="k-XOR-LFSR time-bomb; rarity from sequence depth, small d"),
    Option("rare_fsm_state", impact=0.60, rarity=0.90, area=0.40, evasion=0.60,
           source="Trust-Hub", note="unreachable-under-spec FSM state via a crafted sequence"),
    Option("counter_plus_data", impact=0.75, rarity=0.96, area=0.45, evasion=0.78,
           source="Trust-Hub", note="hybrid: rare data word AND a counter threshold"),
    Option("protocol_sequence", impact=0.70, rarity=0.94, area=0.35, evasion=0.74,
           source="Trust-Hub RS232/AES", note="specific bus/handshake message sequence"),
    # ---- externally-triggered ----
    Option("external_input_pin", impact=0.55, rarity=0.80, area=0.18, evasion=0.55,
           source="Trust-Hub (external)", note="activated by a specific user input / GPIO pattern"),
    Option("component_output", impact=0.60, rarity=0.82, area=0.22, evasion=0.58,
           source="Trust-Hub (external)", note="fires on another component's output value"),
    # ---- analog / physical (below the digital layer) ----
    Option("analog_charge_accum", impact=0.80, rarity=0.97, area=0.10, evasion=0.95,
           source="A2 (Yang 2016)", note="capacitor siphons charge from toggling wires; invisible to digital sim"),
    Option("thermal_trigger", impact=0.50, rarity=0.93, area=0.55, evasion=0.85,
           source="survey", note="activates above a temperature threshold"),
    Option("ring_oscillator_aging", impact=0.55, rarity=0.90, area=0.50, evasion=0.82,
           source="survey", note="aging/RO-based; fires after accumulated stress"),
    Option("em_antenna", impact=0.50, rarity=0.88, area=0.40, evasion=0.80,
           source="Trust-Hub taxonomy", note="unshielded wire as EM trigger/leak path"),
    # ---- always-on ----
    Option("always_on", impact=0.45, rarity=0.05, area=0.20, evasion=0.35,
           source="Trust-Hub (always-on)", note="no trigger; continuous degradation/leak"),
]

# --- Payloads / effects -------------------------------------------------------
PAYLOADS: list[Option] = [
    # ---- CSAW 2026 baseline ----
    Option("key_exfiltration", impact=0.98, rarity=0.5, area=0.35, evasion=0.55,
           baseline=True, source="CSAW ch1/ch2A", note="stream the device key on the read path (CVSS 9.0)"),
    Option("auth_tag_bypass", impact=0.95, rarity=0.5, area=0.30, evasion=0.60,
           baseline=True, source="CSAW ch2B", note="force AEAD tag-verify to pass (CVSS 9.0)"),
    Option("forced_nonce_reuse", impact=0.78, rarity=0.5, area=0.25, evasion=0.65,
           baseline=True, source="CSAW ch2C", note="pin the nonce so keystream repeats (CVSS 7.1)"),
    Option("data_corruption", impact=0.70, rarity=0.5, area=0.20, evasion=0.70,
           baseline=True, source="CSAW ch3", note="bypass the FIR filter; raw/aliased audio passes"),
    # ---- information leakage (Trust-Hub effect: leak information) ----
    Option("sidechannel_leak", impact=0.80, rarity=0.5, area=0.25, evasion=0.80,
           source="A2/survey", note="leak secret via power/EM/timing side channel (Si)"),
    Option("memory_readout", impact=0.85, rarity=0.5, area=0.35, evasion=0.55,
           source="Trust-Hub", note="dump protected memory/registers to an output port"),
    # ---- functional change / corruption ----
    Option("output_inversion", impact=0.65, rarity=0.5, area=0.15, evasion=0.72,
           source="arXiv:1605.08413", note="invert/alter a computed output (k-XOR-LFSR style)"),
    Option("bitflip_fault", impact=0.72, rarity=0.5, area=0.30, evasion=0.58,
           source="survey (DFA)", note="inject a fault into a datapath register (enables DFA)"),
    Option("instruction_corruption", impact=0.88, rarity=0.5, area=0.45, evasion=0.50,
           source="survey", note="corrupt a fetched instruction / control word in a CPU"),
    # ---- control / access ----
    Option("privilege_escalation", impact=0.90, rarity=0.5, area=0.40, evasion=0.50,
           source="A2 (Yang 2016)", note="flip an access-control bit to grant an illegal mode"),
    Option("backdoor_access", impact=0.85, rarity=0.5, area=0.35, evasion=0.60,
           source="survey", note="open an undocumented control/debug path"),
    # ---- availability / parametric (Trust-Hub effect: DoS / change-spec) ----
    Option("denial_of_service", impact=0.60, rarity=0.5, area=0.20, evasion=0.60,
           source="Trust-Hub (DoS)", note="hang BUSY / wedge the FSM on trigger"),
    Option("performance_degradation", impact=0.55, rarity=0.5, area=0.18, evasion=0.75,
           source="Trust-Hub (change-spec)", note="slow timing / inject latency, within spec envelope"),
    Option("reliability_aging", impact=0.58, rarity=0.5, area=0.30, evasion=0.78,
           source="survey", note="accelerate wear / NBTI to cause later field failure"),
    Option("energy_drain", impact=0.50, rarity=0.5, area=0.22, evasion=0.76,
           source="survey (Si)", note="waste power/battery via a side-channel payload"),
]

# --- Victim IP cores ("all kinds of hardware") --------------------------------
TARGETS: list[Option] = [
    # ---- CSAW 2026 baseline ----
    Option("feistel_crypto_core", impact=0.90, area=0.40, baseline=True, source="CSAW ch1",
           note="32-bit byte-substitution SPI accelerator"),
    Option("ascon_aead128", impact=0.95, area=0.60, baseline=True, source="CSAW ch2",
           note="EEPROM-keyed AEAD accelerator"),
    Option("fir_audio_filter", impact=0.60, area=0.30, baseline=True, source="CSAW ch3",
           note="63-tap FIR audio filter"),
    # ---- cryptographic cores (Trust-Hub) ----
    Option("aes128_core", impact=0.95, area=0.70, source="Trust-Hub AES"),
    Option("des_core", impact=0.85, area=0.55, source="Trust-Hub DES"),
    Option("rsa_core", impact=0.92, area=0.80, source="Trust-Hub BasicRSA"),
    Option("sha256_core", impact=0.80, area=0.65, source="Trust-Hub SHA"),
    Option("prng_trng", impact=0.85, area=0.35, source="survey", note="(T)RNG - bias it to weaken all keys"),
    # ---- processors / microcontrollers ----
    Option("riscv_rv32i_core", impact=0.92, area=0.85, source="survey"),
    Option("or1200_cpu", impact=0.90, area=0.85, source="A2 (Yang 2016)"),
    Option("pic_mcu", impact=0.75, area=0.45, source="Trust-Hub PIC"),
    Option("mc8051_mcu", impact=0.78, area=0.50, source="Trust-Hub MC8051"),
    # ---- communication / bus / memory ----
    Option("uart_rs232", impact=0.50, area=0.18, source="Trust-Hub RS232"),
    Option("spi_peripheral", impact=0.50, area=0.18, source="CSAW/Trust-Hub"),
    Option("i2c_controller", impact=0.50, area=0.20, source="CSAW ch2"),
    Option("ethernet_mac", impact=0.70, area=0.60, source="Trust-Hub Ethernet"),
    Option("wishbone_interconnect", impact=0.72, area=0.55, source="Trust-Hub wb_conmax"),
    Option("memory_controller", impact=0.75, area=0.50, source="Trust-Hub memctrl"),
    Option("dma_engine", impact=0.80, area=0.55, source="survey"),
    Option("pcie_controller", impact=0.78, area=0.70, source="survey"),
    # ---- benchmark circuits (ISCAS89 / ITC99) ----
    Option("iscas89_s15850", impact=0.55, area=0.45, source="Trust-Hub ISCAS89"),
    Option("iscas89_s35932", impact=0.58, area=0.60, source="Trust-Hub ISCAS89"),
    Option("itc99_b19", impact=0.60, area=0.75, source="Trust-Hub ITC99"),
    # ---- SoC infrastructure ----
    Option("gps_baseband", impact=0.82, area=0.65, source="survey"),
    Option("power_management_unit", impact=0.68, area=0.40, source="survey"),
    Option("jtag_debug_tap", impact=0.80, area=0.25, source="survey", note="debug port - natural backdoor host"),
]

# --- Stealth / obfuscation techniques (evasion vs the detector) ---------------
STEALTH: list[Option] = [
    Option("param_gated", area=0.10, evasion=0.60, baseline=True, source="CSAW",
           note="whole Trojan behind TROJAN_EN so EN=0 is provably clean"),
    Option("resource_sharing", area=0.05, evasion=0.80, source="survey",
           note="reuse existing adders/muxes so area overhead ~ 0 (hardest to spot)"),
    Option("dont_care_encoding", area=0.15, evasion=0.72, source="DeTrust/survey",
           note="hide logic in unused encodings / don't-care states"),
    Option("split_trigger", area=0.30, evasion=0.78, source="DeTrust",
           note="distribute the trigger across modules to defeat structural analysis"),
    Option("timing_matched", area=0.25, evasion=0.68, source="CSAW",
           note="pad so BUSY/latency is bit-identical to the clean core"),
    Option("rare_node_insertion", area=0.20, evasion=0.74, source="survey",
           note="attach to nets with very low switching probability (evades activity-based ATPG)"),
    Option("analog_sublayer", area=0.05, evasion=0.96, source="A2 (Yang 2016)",
           note="implement below the digital netlist (capacitor/doping) - invisible to RTL/gate tools"),
    Option("layout_fill_cells", area=0.10, evasion=0.88, source="survey",
           note="hide in filler/decap cells at the physical layer"),
    Option("none", area=0.0, evasion=0.20, source="baseline",
           note="unobfuscated - trivially detectable"),
]

# --- NEW taxonomy axis: abstraction level the Trojan is inserted at ------------
# (Tehranipoor/Koushanfar) - determines which detectors can even see it.
ABSTRACTIONS: list[Option] = [
    Option("rtl_soft_ip", area=0.5, evasion=0.40, source="taxonomy",
           note="RTL source edit - visible to RTL review + simulation"),
    Option("gate_firm_ip", area=0.5, evasion=0.55, source="taxonomy",
           note="gate-netlist edit - needs structural/ATPG analysis"),
    Option("transistor_hard_ip", area=0.5, evasion=0.80, source="taxonomy",
           note="transistor-level - evades RTL/gate tools"),
    Option("layout_physical", area=0.5, evasion=0.92, source="A2/taxonomy",
           note="layout/fabrication - evades all pre-silicon netlist detection"),
]

# --- NEW taxonomy axis: payload delivery channel (St vs Si) -------------------
CHANNELS: list[Option] = [
    Option("standard_io", evasion=0.45, source="arXiv:1605.08413",
           note="payload observable on normal I/O (St) - testable functionally"),
    Option("side_channel", evasion=0.85, source="A2/arXiv:1605.08413",
           note="payload via power/EM/thermal/timing (Si) - invisible to functional test"),
]


def _names(opts): return [o.key for o in opts]
def _index(opts): return {o.key: o for o in opts}


TRIGGER_NAMES, TRIGGER_IX = _names(TRIGGERS), _index(TRIGGERS)
PAYLOAD_NAMES, PAYLOAD_IX = _names(PAYLOADS), _index(PAYLOADS)
TARGET_NAMES, TARGET_IX = _names(TARGETS), _index(TARGETS)
STEALTH_NAMES, STEALTH_IX = _names(STEALTH), _index(STEALTH)
ABSTRACTION_NAMES, ABSTRACTION_IX = _names(ABSTRACTIONS), _index(ABSTRACTIONS)
CHANNEL_NAMES, CHANNEL_IX = _names(CHANNELS), _index(CHANNELS)

DIMS = {
    "trigger": TRIGGER_NAMES, "payload": PAYLOAD_NAMES, "target": TARGET_NAMES,
    "stealth": STEALTH_NAMES, "abstraction": ABSTRACTION_NAMES, "channel": CHANNEL_NAMES,
}

BASELINE = {
    "triggers": [o.key for o in TRIGGERS if o.baseline],
    "payloads": [o.key for o in PAYLOADS if o.baseline],
    "targets": [o.key for o in TARGETS if o.baseline],
}


@dataclass
class TrainConfig:
    seed: int = 1337
    n_cont: int = 4          # trigger_prob_exp, area_budget, implicit_alpha, prop_delay
    hide_hidden: tuple = (128, 128)
    hunt_hidden: tuple = (160, 96)
    fix_hidden: tuple = (128, 96)
    lr: float = 0.01
    buffer_cap: int = 20000
    batch: int = 64
    max_self_correct: int = 4
    stealth_accept: float = 0.75
    impact_accept: float = 0.70
    eps_start: float = 0.9
    eps_end: float = 0.08
    eps_decay_steps: int = 5000
    hunt_every: int = 1
    fix_every: int = 1
    device_lc_budget: int = 5280   # iCE40-UP5K logic cells (CSAW board); scales the fit check
