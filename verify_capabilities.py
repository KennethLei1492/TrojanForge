"""End-to-end capability check: given a task, can the system CREATE a Trojan,
FIND a Trojan, and FIX the damage? Trains briefly, then drives one task through
all three agents and reports exactly what each produced (incl. REAL iverilog).

Run:  python verify_capabilities.py
"""
from __future__ import annotations
import os, sys, time, json
import numpy as np

from trojan_forge import config as C, genome as G, surrogate
from trojan_forge.orchestrator import Orchestrator
from trojan_forge.hide_agent import reward as hide_reward
from trojan_forge import toolchain

RUN = os.path.join("runs", "verify-" + time.strftime("%H%M%S"))
# rtl_only => the generator only emits insertable, iverilog-verifiable RTL Trojans
orch = Orchestrator(C.TrainConfig(), RUN, real_verify_every=0,
                    constraints=G.Constraints(rtl_only=True))

# --- train briefly so the three policies are not random ---
print("Training the three agents briefly (co-training)...")
rng = np.random.default_rng(0)
for i in range(1200):
    ep = orch._episode()
    orch.tracker.record(ep["row"])
    orch.tracker.add_experience(ep["feats"], ep["reward"], ep["genome"],
                                ep["fix_feats"], ep["fix_action"], ep["fix_reward"])
    orch.steps += 1
    f, r = orch.tracker.hide_batch(64)
    if f is not None: orch.hide.learn(f, r)
    gs = orch.tracker.hunt_batch(64)
    if gs: orch.hunt.train_on(gs)
    fb = orch.tracker.fix_batch(64)
    if fb[0]: orch.fix.learn(*fb)
print(f"  done. hunt={orch.hunt.metrics()}  fix={orch.fix.metrics()}\n")

# ============================================================
# TASK (given): "Insert a key-exfiltration Trojan into the ASCON AEAD core."
# ============================================================
TASK = {"focus_target": "ascon_aead128", "focus_payload": "key_exfiltration"}
print("="*64)
print("TASK:", TASK)
print("="*64)

# ---- 1. CREATE (Track 1 / Hide) ----
res = orch.hide.propose(orch.hunt, focus=TASK)
g = res.output
sc = surrogate.score(g)
print("\n[1] CREATE -> HideAgent produced this design:")
for k, v in g.as_row().items():
    print(f"      {k:16}: {v}")
print(f"    scorecard: stealth={sc.stealth:.3f} impact={sc.impact:.3f} fits={sc.fits}")
print(f"    self-correction rounds used: {res.steps-1}  status: {res.status.value}")

# ---- real RTL ground truth (digital cores only) ----
print("\n    REAL iverilog twin-check on the emitted RTL:")
wd = os.path.join(RUN, "rtl", g.gid())
from trojan_forge.rtl_emitter import emit_project
paths = emit_project(g, wd)
real = surrogate.real_verify(g, wd)
if not real.get("available"):
    print("      (iverilog not on PATH - surrogate only)")
elif real.get("compiles") is None:
    print(f"      sub-digital Trojan: {real.get('note')}")
else:
    print(f"      compiles={real['compiles']} stealthy={real['stealthy']} "
          f"triggers={real['triggers']} allpass={real.get('allpass')}")
    print(f"      emitted RTL: {paths['trojan']}")

# ---- 2. FIND (Track 2 / Hunt) on the REAL emitted RTL ----
from trojan_forge import extract, remediate
print("\n[2] FIND -> HuntAgent detector on the GIVEN RTL (golden-model delta):")
rtl_find = extract.detect_rtl(orch.hunt, paths["clean"], paths["trojan"])
rtl_clean = extract.detect_rtl(orch.hunt, paths["clean"], paths["clean"])
print(f"      P(trojan | clean vs trojaned RTL)     = {rtl_find['trojan_prob']:.3f}  -> {'FLAGGED' if rtl_find['flagged'] else 'missed'}")
print(f"      P(trojan | clean vs clean RTL)        = {rtl_clean['trojan_prob']:.3f}  -> {'false-alarm' if rtl_clean['flagged'] else 'cleared'}")
# sweep: detect across many freshly-generated trojans vs their clean twins
T, Fp = [], []
for _ in range(400):
    gg = G.random_genome(rng)
    T.append(orch.hunt.detect_prob(gg) >= .5)
    Fp.append(orch.hunt.clean_prob(gg) >= .5)
print(f"      over 400 random designs: recall(find trojans)={np.mean(T):.2%}  "
      f"false-positive rate={np.mean(Fp):.2%}")

# ---- 3. FIX (Track 3 / Fix): patch the REAL RTL and re-verify ----
from trojan_forge.fix_agent import ACTIONS
print("\n[3] FIX -> FixAgent patches the RTL, proven by re-simulation:")
a = orch.fix.choose(g, explore=0.0)
proof = remediate.repair_and_verify(g, ACTIONS[a], wd)
print(f"      chosen action        : {ACTIONS[a]}")
print(f"      neutralised (proven) : {proof.get('neutralised')}")
print(f"      stealth preserved    : {proof.get('stealthy_preserved')}")
print(f"      trigger still fires  : {proof.get('trigger_still_fires')}")
print(f"      patched RTL          : {proof.get('patched_rtl')}")
# does it pick the right action per payload class on average?
print("\n      Fix policy's preferred action per payload (sanity):")
for pl in ["key_exfiltration", "denial_of_service", "privilege_escalation", "data_corruption"]:
    gg = G.TrojanGenome("aes128_core", "two_block_knock", pl, "resource_sharing")
    a = int(np.argmax(orch.fix.q.predict(gg.features())[0]))
    print(f"        {pl:22} -> {ACTIONS[a]}")

print("\n" + "="*64)
print("SUMMARY: create (emits real RTL, verified by iverilog for digital cores),")
print("find (trained detector over the footprint), fix (remediation policy).")
