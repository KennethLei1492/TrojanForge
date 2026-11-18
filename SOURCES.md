# Sources grounding the TrojanForge design space

The CSAW 2026 submission designs are the **baseline**; the rest of the
trigger / payload / target / stealth space is drawn from the public
hardware-Trojan literature so the generator produces *all kinds* of Trojans
across *all kinds* of hardware. Each `Option` in [`config.py`](trojan_forge/config.py)
carries a `source` tag pointing back to one of these.

## Taxonomy (the 5 axes: insertion phase · abstraction level · activation · effect · location)
- M. Tehranipoor and F. Koushanfar, "A Survey of Hardware Trojan Taxonomy and
  Detection," *IEEE Design & Test of Computers*, 2010. The canonical
  trigger+payload decomposition and the five classification axes.
- Trust-Hub taxonomy document — https://trust-hub.org/downloads/resource/pdf/Taxonomy.pdf
  (always-on vs triggered; internal/external activation; change-function /
  change-spec / leak-information / denial-of-service effects; EM leak via
  unshielded wire).
- Survey, "Information Flow Tracking Methods for Protecting Cyber-Physical
  Systems against Hardware Trojans," arXiv:2301.02620 (insertion phase,
  abstraction levels system→RTL→gate→transistor→physical, location).

## Benchmark design classes (the hardware targets)
- Trust-Hub.org benchmark suite — 17 design classes incl. AES, DES, BasicRSA,
  SHA, PIC, MC8051, RS-232, memctrl, wb_conmax, Ethernet, and ISCAS89
  (s15850/s35932) / ITC99 (b19) circuits.
- Krieg, "Reflections on Trusting TrustHUB," 2023 —
  https://repositum.tuwien.at/handle/20.500.12708/191214 (17 design classes;
  effectiveness criteria: correctness, maliciousness, stealthiness, persistence).
- Politecnico di Torino RT-level Trust-Hub table (per-class benchmark counts:
  AES 21, b19 3, BasicRSA 4, MC8051 7, memctrl 1, PIC 4, RS-232 10, wb_conmax 2).

## Trigger / payload formal attributes (dimension d, delay t, implicit-α, St/Si)
- "Advancing the State-of-the-Art in Hardware Trojans Design," arXiv:1605.08413
  — trigger signal dimension *d* (comparator width), payload propagation delay
  *t*, implicit-behaviour factor *α* (P(output looks normal when triggered)),
  trigger locality *l*, standard-I/O (St) vs side-channel (Si) payload channel,
  combinational vs k-XOR-LFSR sequential triggers.

## Analog / sub-digital Trojans (the layout_physical + analog_* options)
- K. Yang, M. Hicks, Q. Dong, T. Austin, D. Sylvester, "A2: Analog Malicious
  Hardware," *IEEE S&P 2016* — https://www.cse.umich.edu/cse/awards/pdfs/A2_SP_2016.pdf
  (capacitor charge-accumulation trigger siphoning charge from toggling wires;
  as little as one gate; privilege-escalation payload on an OR1200; invisible to
  digital-only and known side-channel defenses). This grounds
  `analog_charge_accum`, `analog_sublayer`, `layout_physical`, and why the
  digital twin-check marks these Trojans out-of-scope.

## Detection-evasion techniques (the stealth axis)
- DeTrust-style distributed/implicit triggers (split_trigger, dont_care_encoding)
  — hiding trigger logic from structural analysis.
- Rare-node insertion / low-controllability nets to evade activity-based ATPG
  (rare_node_insertion), per the detection surveys above.

> These are used to model *how Trojans are built* so the detector and fixer can
> be trained to find and remove them. The framework is for the sanctioned,
> NYU-run CSAW AHA! academic competition and defensive Trojan research; it does
> not target real or third-party hardware.
