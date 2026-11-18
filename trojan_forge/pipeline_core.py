"""pipeline_core - the shared contract reused from prebuilt-ai-technique-models.

This is a focused re-implementation of the four ideas TrojanForge borrows from
the prebuilt models, on one contract so the three agents compose:

  * TaskRequest / TaskResult   - typed request/result with status + usage
    (prebuilt_models: "one contract, six implementations").
  * plan_then_act              - every agent reasons about the task (chooses a
    strategy) before acting; the plan is attached to the result for audit
    (prebuilt_models rule 1: "every model reasons before it acts").
  * BoundedExecutor            - bounded-concurrency, jittered-retry parallel
    executor (prebuilt parallelization_model) used by the 24/7 orchestrator.
  * self_consistency           - sample a decision k times and take the modal /
    mean answer (answer_verification_model), used to stabilise acceptance.
  * ResponseCache              - TTL+LRU memo so identical genomes are not
    re-verified (caching_model).

Keeping these here means the training loop's structure is literally the prebuilt
pipeline, not a bespoke script.
"""

from __future__ import annotations

import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    CACHED = "CACHED"


@dataclass
class TaskRequest:
    kind: str                       # "hide" | "hunt" | "fix"
    payload: Any = None
    domain: str = "electrical_engineering"
    meta: dict = field(default_factory=dict)


@dataclass
class TaskResult:
    status: Status
    output: Any = None
    plan: dict = field(default_factory=dict)
    evidence: list = field(default_factory=list)
    confidence: float = 0.0
    steps: int = 0
    usage: dict = field(default_factory=dict)


def plan_then_act(planner: Callable[[TaskRequest], dict],
                  actor: Callable[[TaskRequest, dict], TaskResult],
                  req: TaskRequest) -> TaskResult:
    """Reason about the request (planner), then execute (actor). The plan is
    attached to the result so every decision is auditable."""
    plan = planner(req)
    res = actor(req, plan)
    res.plan = plan
    return res


class ResponseCache:
    """TTL + LRU cache (caching_model) to avoid re-verifying identical genomes."""

    def __init__(self, cap=4096, ttl=3600.0):
        self.cap, self.ttl = cap, ttl
        self._d: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self.hits = self.misses = 0

    def get(self, key):
        now = time.time()
        if key in self._d:
            ts, val = self._d[key]
            if now - ts <= self.ttl:
                self._d.move_to_end(key)
                self.hits += 1
                return val
            del self._d[key]
        self.misses += 1
        return None

    def put(self, key, val):
        self._d[key] = (time.time(), val)
        self._d.move_to_end(key)
        while len(self._d) > self.cap:
            self._d.popitem(last=False)


class BoundedExecutor:
    """Bounded-concurrency parallel map with jittered retry (parallelization_model)."""

    def __init__(self, max_workers=4, retries=1):
        self.max_workers = max_workers
        self.retries = retries

    def map(self, fn: Callable, items: list) -> list:
        out = [None] * len(items)
        with ThreadPoolExecutor(max_workers=self.max_workers) as ex:
            futs = {}
            for i, it in enumerate(items):
                futs[ex.submit(self._with_retry, fn, it)] = i
            for fut in as_completed(futs):
                out[futs[fut]] = fut.result()
        return out

    def _with_retry(self, fn, item):
        last = None
        for attempt in range(self.retries + 1):
            try:
                return fn(item)
            except Exception as exc:  # pragma: no cover
                last = exc
                time.sleep(0.01 * (attempt + 1))
        return {"error": str(last)}


def self_consistency(sampler: Callable[[], Any], k: int = 5, mode="mean"):
    """Sample a decision k times; return the stabilised answer + agreement.

    (answer_verification_model: self-consistency.) `mode="mode"` for categorical,
    `mode="mean"` for scalar confidence."""
    samples = [sampler() for _ in range(k)]
    if mode == "mode":
        c = Counter(samples)
        best, n = c.most_common(1)[0]
        return best, n / k
    vals = [float(s) for s in samples]
    mean = sum(vals) / len(vals)
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    agreement = 1.0 / (1.0 + var)
    return mean, agreement
