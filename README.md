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
A `TrojanGenome` is `(target, trigger, payload, stealth, trigger_prob_exp,
area_budget)`. Eight triggers (incl. the 2⁻⁶⁴ knock, 128-frame counter, magic
nonce), seven payloads (key exfil, auth bypass, nonce reuse, FIR corruption, …),
ten hardware targets (the three CSAW cores + AES/RISC-V/UART/SPI/I²C/…), six
stealth techniques. Every option carries grounded numeric priors.

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
Within a couple of minutes of self-play the generator **rediscovers the human
team's actual winning Trojans** — `feistel_crypto_core + two_block_knock +
key_exfiltration` (challenge 1) and `ascon_aead128 + two_block_knock +
auth_tag_bypass` (challenge 2B) — at high evasion, while the detector keeps
co-adapting. That is the whole system working as one: create an impactful
stealthy Trojan, detect Trojans using what it created, and patch the damage —
training itself to improve the entire time.
