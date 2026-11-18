"""Experience buffer + the live spreadsheet that tracks every Trojan created.

Two outputs, written under runs/<timestamp>/:
  * trojans.csv   - append-only, one row per Trojan the HideAgent produces,
                    with its full design, the surrogate scorecard, the detector's
                    verdict, and the fixer's outcome. Safe to tail 24/7.
  * trojans.xlsx  - a formatted workbook (rebuilt periodically) with two sheets:
                    "Trojans" (every design) and "Summary" (coverage across
                    hardware targets x trigger types, acceptance / detection /
                    neutralisation rates) - the "test across all kinds of
                    hardware and all kinds of triggers" view.

The buffer also feeds the learners: it stores (features, reward) for Hide,
genomes for Hunt, and (features, action, reward) for Fix.
"""

from __future__ import annotations

import csv
import os
import time
from collections import deque

import numpy as np

from . import config as C

CSV_FIELDS = [
    "ts", "step", "gid", "target", "trigger", "payload", "stealth",
    "abstraction", "channel", "baseline", "implicit_alpha", "prop_delay",
    "trigger_bits", "trigger_prob", "area_cells", "fits",
    "stealth_score", "impact", "static_detect", "detector_prob",
    "evasion", "reward", "accepted", "self_correct_rounds",
    "fix_action", "fix_neutralised", "fix_collateral", "fix_reward",
    "real_verify", "real_stealthy", "real_triggers",
]


class Tracker:
    def __init__(self, cfg: C.TrainConfig, run_dir: str):
        self.cfg = cfg
        self.run_dir = run_dir
        os.makedirs(run_dir, exist_ok=True)
        self.csv_path = os.path.join(run_dir, "trojans.csv")
        self.xlsx_path = os.path.join(run_dir, "trojans.xlsx")
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="") as f:
                csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()
        # experience buffers
        self.hide_feats = deque(maxlen=cfg.buffer_cap)
        self.hide_rewards = deque(maxlen=cfg.buffer_cap)
        self.hunt_genomes = deque(maxlen=cfg.buffer_cap)
        self.fix_feats = deque(maxlen=cfg.buffer_cap)
        self.fix_actions = deque(maxlen=cfg.buffer_cap)
        self.fix_rewards = deque(maxlen=cfg.buffer_cap)
        self.rows = []          # kept for the xlsx rebuild (capped)
        self.n = 0

    # -- record one full Hide/Hunt/Fix episode ------------------------------
    def record(self, row: dict):
        self.n += 1
        with open(self.csv_path, "a", newline="") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(
                {k: row.get(k, "") for k in CSV_FIELDS})
        self.rows.append(row)
        if len(self.rows) > 50000:
            self.rows = self.rows[-50000:]

    def add_experience(self, feats, reward, genome, fix_feats=None,
                       fix_action=None, fix_reward=None):
        self.hide_feats.append(feats)
        self.hide_rewards.append(reward)
        self.hunt_genomes.append(genome)
        if fix_feats is not None:
            self.fix_feats.append(fix_feats)
            self.fix_actions.append(fix_action)
            self.fix_rewards.append(fix_reward)

    def hide_batch(self, n):
        if len(self.hide_feats) < 8:
            return None, None
        idx = np.random.randint(0, len(self.hide_feats), size=min(n, len(self.hide_feats)))
        feats = np.array([self.hide_feats[i] for i in idx], dtype=np.float32)
        rew = np.array([self.hide_rewards[i] for i in idx], dtype=np.float32)
        return feats, rew

    def hunt_batch(self, n):
        if len(self.hunt_genomes) < 4:
            return []
        idx = np.random.randint(0, len(self.hunt_genomes), size=min(n, len(self.hunt_genomes)))
        return [self.hunt_genomes[i] for i in idx]

    def fix_batch(self, n):
        if len(self.fix_feats) < 8:
            return [], [], []
        idx = np.random.randint(0, len(self.fix_feats), size=min(n, len(self.fix_feats)))
        return ([self.fix_feats[i] for i in idx],
                [self.fix_actions[i] for i in idx],
                [self.fix_rewards[i] for i in idx])

    # -- the formatted workbook --------------------------------------------
    def write_xlsx(self):
        try:
            from openpyxl import Workbook
            from openpyxl.styles import Font, PatternFill
        except Exception:
            return False
        wb = Workbook()
        ws = wb.active
        ws.title = "Trojans"
        ws.append(CSV_FIELDS)
        for c in ws[1]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor="305496")
            c.font = Font(bold=True, color="FFFFFF")
        for row in self.rows[-5000:]:
            ws.append([row.get(k, "") for k in CSV_FIELDS])
        # summary sheet: coverage target x trigger + rates
        s = wb.create_sheet("Summary")
        s.append(["Coverage matrix: accepted Trojans per target x trigger"])
        s.append([""] + C.TRIGGER_NAMES)
        counts = {t: {tr: 0 for tr in C.TRIGGER_NAMES} for t in C.TARGET_NAMES}
        acc = det = neut = tot = 0
        for r in self.rows:
            t, tr = r.get("target"), r.get("trigger")
            if t in counts and tr in counts[t] and r.get("accepted"):
                counts[t][tr] += 1
            tot += 1
            acc += bool(r.get("accepted"))
            det += bool(r.get("detector_prob", 0) and float(r.get("detector_prob", 0)) >= 0.5)
            neut += bool(r.get("fix_neutralised"))
        for t in C.TARGET_NAMES:
            s.append([t] + [counts[t][tr] for tr in C.TRIGGER_NAMES])
        s.append([])
        s.append(["Totals"])
        s.append(["trojans_logged", tot])
        s.append(["accepted (stealthy+impactful)", acc, f"{(acc/tot if tot else 0):.1%}"])
        s.append(["detected by HuntAgent", det, f"{(det/tot if tot else 0):.1%}"])
        s.append(["neutralised by FixAgent", neut, f"{(neut/tot if tot else 0):.1%}"])
        tmp = self.xlsx_path + ".tmp"
        wb.save(tmp)
        os.replace(tmp, self.xlsx_path)
        return True
