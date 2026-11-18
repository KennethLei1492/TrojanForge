# TrojanForge — self-correcting Hide / Hunt / Fix co-training

A deep-learning system that **trains itself** to do all three CSAW 2026 AHA!
tracks at once, as one continuously-improving adversarial loop:

| Track | 🫥 **Hide** | 🕵️ **Hunt** | 🛠️ **Fix** |
|---|---|---|---|
| Goal | insert stealthy hardware Trojans | detect Trojans / verify designs | trace failures & patch the damage |
| Agent | `HideAgent` (generator + bounded self-correction) | `HuntAgent` (detector) | `FixAgent` (remediation policy) |
| Learns from | the co-training reward (impact × stealth × evasion) | **the Trojans Hide creates** vs clean twins | repair outcomes (neutralise − collateral) |

The three agents run **asynchronously, in parallel, 24/7**, sharing one
experience buffer. Improving one pressures the others — a stealthier generator
degrades the detector's recall, the detector recovers, which pushes the
generator again — so the system keeps improving instead of converging.

Built on two code bases:

* **[Final-CSAW-2026-Documentation](https://github.com/KennethLei1492/Final-CSAW-2026-Documentation)** — the real
  `generate → insert → verify → retry` Trojan pipeline. Its designs ground the
  whole search space: the 2⁻⁶⁴ two-block "knock" trigger, CVSS-9.0 key
  exfiltration, forced nonce reuse, the 128-frame FIR bypass, the 93–95 % UP5K
  logic-cell fit, the clean-twin stealth check. TrojanForge **models how those
  Trojans are built and then improves on them** by searching the full
  trigger × payload × hardware × stealth space.
* **[prebuilt-ai-technique-models](https://github.com/KennethLei1492/prebuilt-ai-technique-models)** — its
  `pipeline_core` contract is reused in [`pipeline_core.py`](trojan_forge/pipeline_core.py):
  plan-then-act, a bounded-concurrency parallel executor, self-consistency
  verification, a TTL/LRU response cache, and — most importantly — **bounded
  self-correction gated on external signals only** (Huang et al. 2024), which is
  exactly how the HideAgent revises a candidate.

> **Scope / ethics.** This is a defensive research tool for the sanctioned,
> NYU-run CSAW AHA! academic competition (the rules *require* AI-generated Trojan
> RTL, to advance Trojan **detection and defense**). The inner loop is a grounded
> analytic surrogate; the optional ground-truth path only ever drives a local
> Icarus Verilog twin-simulation. Nothing here targets real or third-party
> hardware.

---

## Quick start

```powershell
pip install -r requirements.txt            # numpy required; torch preferred; openpyxl for xlsx

python -m trojan_forge --once              # run a single Hide/Hunt/Fix episode, print the row
python -m trojan_forge --steps 2000        # a bounded co-training run
.\run_training.ps1 -Hours 24               # run 24/7 for a day
.\run_training.ps1 -Forever                # run until Ctrl-C
python -m trojan_forge --real-verify-every 200   # periodically audit with REAL iverilog
```

Every run writes to `runs/<timestamp>/`:

* **`trojans.csv`** — append-only, one row per Trojan created (safe to `tail` live).
* **`trojans.xlsx`** — formatted workbook, rebuilt every few seconds:
  * **Trojans** sheet — every design with its scorecard, the detector's verdict and the fixer's outcome.
  * **Summary** sheet — the **coverage matrix** (accepted Trojans per *hardware target* × *trigger type*) plus accept / detect / neutralise rates — the "test across all kinds of hardware and all kinds of triggers" view.
* **`status.json`** — live metrics (best reward, detector accuracy/recall, fix rate, backend).

---

## How it works

### The design space ([`config.py`](trojan_forge/config.py), [`genome.py`](trojan_forge/genome.py))
A `TrojanGenome` spans **six categorical axes** — `target, trigger, payload,
stealth, abstraction-level, payload-channel` — plus **four continuous
attributes** (trigger rarity bits, area budget, implicit-α, propagation delay),
a categorical space of **~505,000 combinations**. The CSAW 2026 designs are the
flagged **baseline** (`baseline=True`); the rest is grounded in the public
hardware-Trojan literature so the system covers *all kinds* of Trojans across
*all kinds* of hardware (see [SOURCES.md](SOURCES.md)):

* **18 triggers** — CSAW knock / magic-nonce / frame-counter, plus combinational
  comparators, LFSR/counter time-bombs, rare FSM states, protocol sequences,
  external-input, and **analog / sub-digital** triggers (A2 charge-accumulation,
  thermal, ring-oscillator aging, EM antenna).
* **15 payloads** — the Trust-Hub effect classes: information leakage (key exfil,
  side-channel, memory readout), functional corruption (output inversion, fault
  injection, instruction corruption), control (privilege escalation, backdoor),
  and availability/parametric (DoS, performance degradation, aging, energy drain).
* **26 hardware targets** — the three CSAW cores plus the Trust-Hub families
  (AES/DES/RSA/SHA, PIC/MC8051, RS-232/Ethernet/wb_conmax/memctrl, ISCAS89
  s-series, ITC99 b19) and RISC-V/OR1200/DMA/PCIe/JTAG/GPS/PMU.
* **9 stealth techniques** + **4 abstraction levels** (RTL→gate→transistor→layout,
  deciding which detectors can even see the Trojan) + **2 channels** (standard-I/O
  vs side-channel). Every option carries grounded numeric priors.

Taxonomy axes follow Tehranipoor & Koushanfar (2010), Trust-Hub, the
arXiv:1605.08413 formal trigger model (dimension *d*, delay *t*, implicit *α*),
and A2 (Yang 2016) for the analog layer — all cited in [SOURCES.md](SOURCES.md).

### The grounded verifier ([`surrogate.py`](trojan_forge/surrogate.py))
Scores a genome's **stealth, impact, device fit and static detectability** from
the submission's real physics, and produces the **observable footprint** a static
scanner sees. The key modelling choice: a clean design and a Trojaned design sit
on the **same benign-complexity floor**, and the Trojan only adds a *delta that
shrinks toward zero* as stealth improves — so a well-hidden Trojan is genuinely
indistinguishable, giving the detector an irreducible error to fight. Rare
*sequential* triggers (the knock) buy rarity with a tiny footprint; a wide
combinational constant does not — the real trade-off.

### The three learners ([`nn.py`](trojan_forge/nn.py))
Real MLPs trained by gradient descent. **PyTorch** backend by default; a
self-contained **NumPy MLP with hand-written back-prop** is the fallback so the
loop never hard-fails. Same API either way.

* **Hide** ([`hide_agent.py`](trojan_forge/hide_agent.py)) — a critic that predicts
  reward; proposes best-of-N candidates, then **self-corrects** by reading the
  surrogate + current detector and fixing its single weakest *external* signal,
  bounded to 4 rounds.
* **Hunt** ([`hunt_agent.py`](trojan_forge/hunt_agent.py)) — a classifier over the
  observable footprint, trained on **Hide's own Trojans** (positives) vs clean
  twins (negatives). This is "use the created Trojan to detect other Trojans."
* **Fix** ([`fix_agent.py`](trojan_forge/fix_agent.py)) — a Q-network over five
  grounded remediation actions (tie-off payload, excise trigger, add assertion,
  resynthesise isolated, quarantine), rewarded for neutralising with least
  collateral.

### The 24/7 loop ([`orchestrator.py`](trojan_forge/orchestrator.py))
Four asyncio workers — `hide` (create), `hunt` (detect), `fix` (repair), and a
checkpointer — share the buffer and run forever. Hide waves are evaluated in
parallel via the `pipeline_core` bounded executor.

### Ground truth ([`rtl_emitter.py`](trojan_forge/rtl_emitter.py), [`toolchain.py`](trojan_forge/toolchain.py))
`--real-verify-every N` emits synthesizable Verilog for a genome — a clean core
and a `TROJAN_EN`-gated twin plus a self-checking testbench that proves
*bit-identical on 200 non-trigger words* **and** that the knock fires — and runs
it under **real Icarus Verilog**, exactly like challenge 1's `tb_trojan`. Used
sparsely to audit the surrogate.

---

## What it demonstrates
Within a couple of minutes of self-play the generator **rediscovers real-world
attacks on its own**:

* the human team's winning CSAW Trojans — `feistel_crypto_core + two_block_knock
  + key_exfiltration` (challenge 1), `ascon_aead128 + ... + auth_tag_bypass`
  (challenge 2B);
* and, across the broadened space, the **A2 analog attack** — `analog_charge_accum
  + analog_sublayer + layout_physical + privilege_escalation` on a microcontroller
  (the Yang 2016 threat model), which a digital netlist scanner cannot see.

As the generator pushes into sub-digital evasion the detector's catch-rate drops
and it must re-learn — a genuine arms race, with coverage spread across 20+
hardware targets and most trigger/payload classes, baseline and novel alike.
That is the whole system working as one: create an impactful stealthy Trojan,
detect Trojans using what it created, and patch the damage — training itself to
improve the entire time.
