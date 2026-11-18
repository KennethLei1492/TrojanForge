"""Neural backbones for the three agents.

Primary backend is PyTorch (confirmed working on this machine). A compact
NumPy MLP with hand-written backprop is kept as a fallback so the 24/7 loop
never hard-fails if torch is missing - the public API (`MLP`, `.predict`,
`.train_step`) is identical either way, so the agents don't care which is live.

All three agents are genuine multi-layer perceptrons trained by gradient
descent. "Self-correction" (the bounded, external-signal-gated revision loop)
lives in the agents, not here; here we just provide the differentiable learners.
"""

from __future__ import annotations

import numpy as np

try:
    import torch
    import torch.nn as _tnn
    _HAS_TORCH = True
except Exception:  # pragma: no cover
    _HAS_TORCH = False

BACKEND = "torch" if _HAS_TORCH else "numpy"


# ---------------------------------------------------------------------------
# Torch backend
# ---------------------------------------------------------------------------
if _HAS_TORCH:

    class _TorchMLP(_tnn.Module):
        def __init__(self, n_in, hidden, n_out, out_act):
            super().__init__()
            layers = []
            prev = n_in
            for h in hidden:
                layers += [_tnn.Linear(prev, h), _tnn.LayerNorm(h), _tnn.GELU()]
                prev = h
            layers += [_tnn.Linear(prev, n_out)]
            self.net = _tnn.Sequential(*layers)
            self.out_act = out_act

        def forward(self, x):
            y = self.net(x)
            if self.out_act == "sigmoid":
                y = torch.sigmoid(y)
            elif self.out_act == "softmax":
                y = torch.softmax(y, dim=-1)
            return y

    class MLP:
        """Thin trainer around a torch MLP. out_act in {linear, sigmoid, softmax}."""

        def __init__(self, n_in, hidden, n_out, out_act="linear", lr=0.01,
                     loss="mse", seed=0):
            torch.manual_seed(seed)
            self.model = _TorchMLP(n_in, list(hidden), n_out, out_act)
            self.opt = torch.optim.Adam(self.model.parameters(), lr=lr)
            self.loss_name = loss
            self.n_in, self.n_out, self.out_act = n_in, n_out, out_act

        def predict(self, X):
            self.model.eval()
            with torch.no_grad():
                t = torch.as_tensor(np.atleast_2d(np.asarray(X, dtype=np.float32)))
                return self.model(t).cpu().numpy()

        def train_step(self, X, Y, sample_w=None):
            self.model.train()
            t = torch.as_tensor(np.atleast_2d(np.asarray(X, dtype=np.float32)))
            y = torch.as_tensor(np.atleast_2d(np.asarray(Y, dtype=np.float32)))
            pred = self.model(t)
            if self.loss_name == "bce":
                per = _tnn.functional.binary_cross_entropy(pred, y, reduction="none")
            elif self.loss_name == "ce":
                per = -(y * torch.log(pred.clamp_min(1e-7))).sum(-1, keepdim=True)
            else:
                per = (pred - y) ** 2
            if sample_w is not None:
                w = torch.as_tensor(np.asarray(sample_w, dtype=np.float32)).reshape(-1, 1)
                loss = (per * w).mean()
            else:
                loss = per.mean()
            self.opt.zero_grad()
            loss.backward()
            self.opt.step()
            return float(loss.detach().cpu())

        def state(self):
            return {k: v.cpu().numpy() for k, v in self.model.state_dict().items()}

        def load_state(self, s):
            sd = {k: torch.as_tensor(v) for k, v in s.items()}
            self.model.load_state_dict(sd)


# ---------------------------------------------------------------------------
# NumPy backend (fallback) - a real MLP with manual backprop
# ---------------------------------------------------------------------------
else:  # pragma: no cover

    def _gelu(x):
        return 0.5 * x * (1.0 + np.tanh(0.79788456 * (x + 0.044715 * x ** 3)))

    def _gelu_grad(x):
        t = np.tanh(0.79788456 * (x + 0.044715 * x ** 3))
        left = 0.5 * (1 + t)
        right = 0.5 * x * (1 - t ** 2) * 0.79788456 * (1 + 0.134145 * x ** 2)
        return left + right

    class MLP:
        def __init__(self, n_in, hidden, n_out, out_act="linear", lr=0.01,
                     loss="mse", seed=0):
            rng = np.random.default_rng(seed)
            self.sizes = [n_in, *hidden, n_out]
            self.W, self.b = [], []
            for a, b in zip(self.sizes[:-1], self.sizes[1:]):
                self.W.append(rng.normal(0, np.sqrt(2.0 / a), (a, b)))
                self.b.append(np.zeros(b))
            self.lr, self.out_act, self.loss_name = lr, out_act, loss
            self.n_in, self.n_out = n_in, n_out
            self.mW = [np.zeros_like(w) for w in self.W]
            self.vW = [np.zeros_like(w) for w in self.W]
            self.mb = [np.zeros_like(b) for b in self.b]
            self.vb = [np.zeros_like(b) for b in self.b]
            self.t = 0

        def _forward(self, X):
            a = np.atleast_2d(np.asarray(X, dtype=np.float64))
            acts, zs = [a], []
            for i, (W, b) in enumerate(zip(self.W, self.b)):
                z = a @ W + b
                zs.append(z)
                if i < len(self.W) - 1:
                    a = _gelu(z)
                else:
                    if self.out_act == "sigmoid":
                        a = 1 / (1 + np.exp(-z))
                    elif self.out_act == "softmax":
                        e = np.exp(z - z.max(axis=1, keepdims=True))
                        a = e / e.sum(axis=1, keepdims=True)
                    else:
                        a = z
                acts.append(a)
            return acts, zs

        def predict(self, X):
            return self._forward(X)[0][-1]

        def train_step(self, X, Y, sample_w=None):
            acts, zs = self._forward(X)
            y = np.atleast_2d(np.asarray(Y, dtype=np.float64))
            pred = acts[-1]
            n = y.shape[0]
            if self.loss_name == "bce":
                p = np.clip(pred, 1e-7, 1 - 1e-7)
                loss = -(y * np.log(p) + (1 - y) * np.log(1 - p)).mean()
                delta = (pred - y)
            elif self.loss_name == "ce":
                loss = -(y * np.log(np.clip(pred, 1e-7, 1))).sum(1).mean()
                delta = (pred - y)
            else:
                loss = ((pred - y) ** 2).mean()
                delta = 2 * (pred - y) / pred.shape[1]
            if sample_w is not None:
                w = np.asarray(sample_w, dtype=np.float64).reshape(-1, 1)
                delta = delta * w
            delta = delta / n
            self.t += 1
            for i in reversed(range(len(self.W))):
                gW = acts[i].T @ delta
                gb = delta.sum(0)
                # adam
                for m, v, g, P in ((self.mW, self.vW, gW, self.W),
                                   (self.mb, self.vb, gb, self.b)):
                    m[i] = 0.9 * m[i] + 0.1 * g
                    v[i] = 0.999 * v[i] + 0.001 * (g * g)
                    mh = m[i] / (1 - 0.9 ** self.t)
                    vh = v[i] / (1 - 0.999 ** self.t)
                    P[i] -= self.lr * mh / (np.sqrt(vh) + 1e-8)
                if i > 0:
                    delta = (delta @ self.W[i].T) * _gelu_grad(zs[i - 1])
            return float(loss)

        def state(self):
            return {"W": [w.copy() for w in self.W], "b": [b.copy() for b in self.b]}

        def load_state(self, s):
            self.W = [w.copy() for w in s["W"]]
            self.b = [b.copy() for b in s["b"]]
