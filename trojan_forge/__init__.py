"""TrojanForge - adversarial self-play co-training for hardware-Trojan
Hide / Hunt / Fix (CSAW 2026 AHA! research framework).

Three learnable agents co-train in parallel, 24/7:

  * HideAgent  (Track 1): generates stealthy hardware Trojans and self-corrects
                           against external verifier signals (bounded, Huang 2024).
  * HuntAgent  (Track 2): a detector trained on the generator's own Trojans vs
                           clean designs - an adversarial, co-evolving loop.
  * FixAgent   (Track 3): a remediation policy rewarded when it neutralizes a
                           Trojan and restores the clean design's behaviour.

The design space, scoring and RTL are grounded in the team's real CSAW 2026
submission (Final-CSAW-2026-Documentation): 2^-64 "knock" triggers, CVSS-9.0 key
exfiltration, 93-95% UP5K logic-cell fit, the 128-frame FIR bypass, etc. The
training pipeline reuses the prebuilt-ai-technique-models contract: plan-then-act,
a bounded concurrency executor, self-consistency verification, and a response
cache (see pipeline_core.py).
"""

__version__ = "0.1.0"
