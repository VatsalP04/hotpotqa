from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Union

import numpy as np
import torch
import torch.nn as nn


ArrayLike = Union[np.ndarray, torch.Tensor]


@dataclass
class ProbeConfig:
    """Configuration for a probe.

    Attributes
    ----------
    probe_type:
        One of {"dense_linear", "mass_mean", "mlp", "attn_pool"}.
    layer:
        Layer index this probe is associated with (if applicable).
    task_name:
        Name of the target task, e.g. "correct", "correct_given_recall1",
        or "recall_full".
    context_type:
        One of {"planning", "subanswer", "final"} (metadata only).
    hook_point:
        Hook name or shorthand, e.g. "resid_post" vs "resid_pre" (metadata only).
    feature_space:
        Optional string describing feature space, e.g. "resid", "sae".
    use_l1:
        Whether to use L1 regularization on the weights (dense_linear / mlp).
    l1_lambda:
        Strength of L1 penalty.
    hidden_dim:
        Hidden width for MLPProbe (ignored for other probes).
    """

    probe_type: str
    layer: Optional[int] = None
    task_name: str = "correct"
    context_type: str = "planning"
    hook_point: str = "resid_post"
    feature_space: str = "resid"
    use_l1: bool = False
    l1_lambda: float = 0.0
    hidden_dim: int = 512  # bumped from 256


def _to_tensor(x: ArrayLike, device: Optional[torch.device] = None) -> torch.Tensor:
    """Convert numpy / tensor / list to a float32 torch.Tensor on the given device."""
    if isinstance(x, torch.Tensor):
        t = x
    else:
        t = torch.as_tensor(x)
    t = t.float()
    if device is not None:
        t = t.to(device)
    return t


class BaseProbe:
    """Abstract interface for all probes.

    Subclasses must implement:
        - fit(...)
        - predict_proba(...)
        - _state_dict()
        - _load_state_dict(...)
    """

    def __init__(self, config: ProbeConfig):
        self.config = config

    @property
    def probe_type(self) -> str:
        return self.config.probe_type

    # ----- training API -----

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Fit the probe on training data."""
        raise NotImplementedError

    def predict_proba(self, x: ArrayLike, **kwargs: Any) -> np.ndarray:
        """Predict probabilities P(y=1 | x).

        Returns
        -------
        probs:
            numpy array of shape (N,) with values in [0, 1].
        """
        raise NotImplementedError

    def predict(self, x: ArrayLike, threshold: float = 0.5, **kwargs: Any) -> np.ndarray:
        """Predict binary labels using a given threshold."""
        probs = self.predict_proba(x, **kwargs)
        return (probs >= threshold).astype(np.int64)

    # ----- persistence -----

    def _state_dict(self) -> Dict[str, Any]:
        """Return a serializable state dict specific to the subclass."""
        raise NotImplementedError

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        """Load state from a dict produced by _state_dict."""
        raise NotImplementedError

    def save(self, path: str) -> None:
        """Save probe (config + state) to disk via torch.save."""
        payload = {
            "probe_type": self.config.probe_type,
            "config": asdict(self.config),
            "state": self._state_dict(),
        }
        torch.save(payload, path)


def load_probe(path: str) -> BaseProbe:
    """Load a probe (any subclass) from disk."""
    payload = torch.load(path, map_location="cpu", weights_only=False)
    probe_type = payload["probe_type"]
    config_dict = payload["config"]
    state = payload["state"]
    config = ProbeConfig(**config_dict)

    if probe_type == "dense_linear":
        probe: BaseProbe = DenseLinearProbe(config)
    elif probe_type == "mass_mean":
        probe = MassMeanProbe(config)
    elif probe_type == "mlp":
        probe = MLPProbe(config)
    elif probe_type == "attn_pool":
        probe = AttentionPoolingProbe(config)
    else:
        raise ValueError(f"Unknown probe_type in saved file: {probe_type}")

    probe._load_state_dict(state)
    return probe


# -------------------------
#  Dense linear probe
# -------------------------


class DenseLinearProbe(BaseProbe):
    """Linear probe on hidden states (or any D-dimensional features).

    Model: z = w^T x + b, p = sigmoid(z).

    Optionally supports L1 regularization on weights to encourage sparsity
    (config.use_l1 / config.l1_lambda).
    """

    def __init__(self, config: ProbeConfig):
        if config.probe_type != "dense_linear":
            config.probe_type = "dense_linear"
        super().__init__(config)
        self.linear: Optional[nn.Linear] = None
        self.input_dim: Optional[int] = None

    def _init_model(self, input_dim: int) -> None:
        self.input_dim = input_dim
        self.linear = nn.Linear(input_dim, 1)

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        *,
        num_epochs: int = 3,
        lr: float = 1e-3,
        weight_decay: float = 0.0,
        batch_size: int = 256,
        device: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, float]:
        # Decide device
        if device is None:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            dev = torch.device(device)

        x = _to_tensor(train_x, dev)
        y = _to_tensor(train_y, dev).view(-1)

        if x.ndim != 2:
            raise ValueError(f"train_x must be 2D (N, D), got shape {tuple(x.shape)}")
        if y.ndim != 1:
            raise ValueError(f"train_y must be 1D (N,), got shape {tuple(y.shape)}")

        n_samples, input_dim = x.shape

        if self.linear is None or self.input_dim != input_dim:
            self._init_model(input_dim)

        assert self.linear is not None
        self.linear.to(dev)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.AdamW(
            self.linear.parameters(), lr=lr, weight_decay=weight_decay
        )

        # Optional validation data
        has_val = val_x is not None and val_y is not None
        if has_val:
            vx = _to_tensor(val_x, dev)
            vy = _to_tensor(val_y, dev).view(-1)
        else:
            vx = vy = None

        metrics: Dict[str, float] = {}

        for epoch in range(num_epochs):
            # Shuffle indices
            perm = torch.randperm(n_samples, device=dev)
            epoch_loss = 0.0

            for start in range(0, n_samples, batch_size):
                end = start + batch_size
                idx = perm[start:end]
                batch_x = x[idx]
                batch_y = y[idx]

                optimizer.zero_grad()
                logits = self.linear(batch_x).squeeze(-1)
                loss = criterion(logits, batch_y)

                # Optional L1 regularization
                if self.config.use_l1 and self.config.l1_lambda > 0.0:
                    l1 = self.linear.weight.abs().sum()
                    loss = loss + self.config.l1_lambda * l1

                loss.backward()
                optimizer.step()

                epoch_loss += loss.item() * batch_x.size(0)

            epoch_loss /= n_samples
            metrics["train_loss"] = epoch_loss

            if has_val and vx is not None and vy is not None:
                with torch.no_grad():
                    v_logits = self.linear(vx).squeeze(-1)
                    v_loss = criterion(v_logits, vy).item()
                metrics["val_loss"] = v_loss

            if verbose:
                if has_val and "val_loss" in metrics:
                    print(
                        f"[DenseLinearProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}, val_loss={metrics['val_loss']:.4f}"
                    )
                else:
                    print(
                        f"[DenseLinearProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}"
                    )

        # Move model to CPU for inference/saving
        self.linear.to(torch.device("cpu"))

        return metrics

    def predict_proba(self, x: ArrayLike, **kwargs: Any) -> np.ndarray:  # type: ignore[override]
        if self.linear is None:
            raise RuntimeError("Probe has not been fitted yet (linear is None).")

        self.linear.eval()
        with torch.no_grad():
            t = _to_tensor(x, device=torch.device("cpu"))
            if t.ndim != 2:
                raise ValueError(f"x must be 2D (N, D), got shape {tuple(t.shape)}")
            logits = self.linear(t).squeeze(-1)
            probs = torch.sigmoid(logits)
        return probs.cpu().numpy()

    # ----- persistence -----

    def _state_dict(self) -> Dict[str, Any]:
        if self.linear is None:
            raise RuntimeError("Cannot save an uninitialized DenseLinearProbe.")
        return {
            "input_dim": self.input_dim,
            "state_dict": self.linear.state_dict(),
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        input_dim = state["input_dim"]
        self._init_model(input_dim)
        assert self.linear is not None
        self.linear.load_state_dict(state["state_dict"])
        self.linear.to(torch.device("cpu"))


# -------------------------
#  Mass-mean direction probe
# -------------------------


class MassMeanProbe(BaseProbe):
    """Mass-mean direction probe with 1D logistic calibration."""

    def __init__(self, config: ProbeConfig):
        if config.probe_type != "mass_mean":
            config.probe_type = "mass_mean"
        super().__init__(config)

        self.center: Optional[torch.Tensor] = None  # (D,)
        self.direction: Optional[torch.Tensor] = None  # (D,), unit vector
        self.alpha: Optional[torch.Tensor] = None  # scalar
        self.beta: Optional[torch.Tensor] = None  # scalar
        self.input_dim: Optional[int] = None

    def _check_initialized(self) -> None:
        if (
            self.center is None
            or self.direction is None
            or self.alpha is None
            or self.beta is None
        ):
            raise RuntimeError("MassMeanProbe is not fully initialized / fitted yet.")

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        *,
        num_epochs: int = 50,
        lr: float = 5e-2,
        weight_decay: float = 0.0,
        batch_size: int = 0,
        device: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, float]:
        # Decide device
        if device is None:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            dev = torch.device(device)

        x = _to_tensor(train_x, dev)
        y = _to_tensor(train_y, dev).view(-1)

        if x.ndim != 2:
            raise ValueError(f"train_x must be 2D (N, D), got shape {tuple(x.shape)}")
        if y.ndim != 1:
            raise ValueError(f"train_y must be 1D (N,), got shape {tuple(y.shape)}")

        n_samples, input_dim = x.shape
        self.input_dim = input_dim

        # Compute class means
        mask_pos = y > 0.5
        mask_neg = ~mask_pos
        n_pos = int(mask_pos.sum().item())
        n_neg = int(mask_neg.sum().item())
        if n_pos == 0 or n_neg == 0:
            raise ValueError(
                "Both positive and negative examples are required for MassMeanProbe."
            )

        mu_pos = x[mask_pos].mean(dim=0)
        mu_neg = x[mask_neg].mean(dim=0)

        # Direction and center
        v = mu_pos - mu_neg
        v_norm = v.norm(p=2)
        if v_norm.item() < 1e-8:
            v = torch.ones_like(v)
            v_norm = v.norm(p=2)
        v = v / v_norm

        center = 0.5 * (mu_pos + mu_neg)

        self.direction = v.detach().clone()
        self.center = center.detach().clone()

        # Scalar projections s = (x - center) dot v
        x_centered = x - self.center
        s = torch.einsum("nd,d->n", x_centered, self.direction)

        # Logistic regression p = sigmoid(alpha * s + beta)
        alpha = torch.zeros(1, device=dev, requires_grad=True)
        beta = torch.zeros(1, device=dev, requires_grad=True)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam([alpha, beta], lr=lr, weight_decay=weight_decay)

        metrics: Dict[str, float] = {}

        has_val = val_x is not None and val_y is not None
        if has_val:
            vx = _to_tensor(val_x, dev)
            vy = _to_tensor(val_y, dev).view(-1)
            vx_centered = vx - self.center
            vs = torch.einsum("nd,d->n", vx_centered, self.direction)
        else:
            vs = vy = None

        for epoch in range(num_epochs):
            optimizer.zero_grad()
            logits = alpha * s + beta
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()

            metrics["train_loss"] = float(loss.item())

            if has_val and vs is not None and vy is not None:
                with torch.no_grad():
                    v_logits = alpha * vs + beta
                    v_loss = criterion(v_logits, vy).item()
                metrics["val_loss"] = float(v_loss)

            if verbose and (epoch == 0 or (epoch + 1) % 10 == 0 or epoch == num_epochs - 1):
                if has_val and "val_loss" in metrics:
                    print(
                        f"[MassMeanProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={metrics['train_loss']:.4f}, "
                        f"val_loss={metrics['val_loss']:.4f}"
                    )
                else:
                    print(
                        f"[MassMeanProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={metrics['train_loss']:.4f}"
                    )

        # Move to CPU
        self.alpha = alpha.detach().cpu()
        self.beta = beta.detach().cpu()
        self.center = self.center.detach().cpu()
        self.direction = self.direction.detach().cpu()

        return metrics

    def _project(self, x: torch.Tensor) -> torch.Tensor:
        """Project x onto the learned direction (centered)."""
        self._check_initialized()
        assert self.center is not None and self.direction is not None
        x_centered = x - self.center
        s = torch.einsum("nd,d->n", x_centered, self.direction)
        return s

    def predict_proba(self, x: ArrayLike, **kwargs: Any) -> np.ndarray:  # type: ignore[override]
        self._check_initialized()
        assert self.alpha is not None and self.beta is not None

        with torch.no_grad():
            t = _to_tensor(x, device=torch.device("cpu"))
            if t.ndim != 2:
                raise ValueError(f"x must be 2D (N, D), got shape {tuple(t.shape)}")
            s = self._project(t)  # (N,)
            logits = self.alpha * s + self.beta
            probs = torch.sigmoid(logits)
        return probs.cpu().numpy()

    # ----- persistence -----

    def _state_dict(self) -> Dict[str, Any]:
        self._check_initialized()
        assert (
            self.center is not None
            and self.direction is not None
            and self.alpha is not None
            and self.beta is not None
        )
        return {
            "input_dim": self.input_dim,
            "center": self.center,
            "direction": self.direction,
            "alpha": self.alpha,
            "beta": self.beta,
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        self.input_dim = state["input_dim"]
        self.center = state["center"].float().cpu()
        self.direction = state["direction"].float().cpu()
        self.alpha = state["alpha"].float().cpu()
        self.beta = state["beta"].float().cpu()


# -------------------------
#  MLP probe (3-layer)
# -------------------------


class MLPProbe(BaseProbe):
    """Small 3-layer MLP probe.

    Model:
        h1 = GELU(W1 x + b1)
        h2 = GELU(W2 h1 + b2)
        z  = W3 h2 + b3
        p  = sigmoid(z).
    """

    def __init__(self, config: ProbeConfig):
        if config.probe_type != "mlp":
            config.probe_type = "mlp"
        super().__init__(config)
        self.net: Optional[nn.Sequential] = None
        self.input_dim: Optional[int] = None

    def _init_model(self, input_dim: int) -> None:
        self.input_dim = input_dim
        hidden_dim = self.config.hidden_dim
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        *,
        num_epochs: int = 3,
        lr: float = 1e-3,
        weight_decay: float = 0.0,
        batch_size: int = 256,
        device: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, float]:
        if device is None:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            dev = torch.device(device)

        x = _to_tensor(train_x, dev)
        y = _to_tensor(train_y, dev).view(-1)

        if x.ndim != 2:
            raise ValueError(f"train_x must be 2D (N, D), got shape {tuple(x.shape)}")
        if y.ndim != 1:
            raise ValueError(f"train_y must be 1D (N,), got shape {tuple(y.shape)}")

        n_samples, input_dim = x.shape

        if self.net is None or self.input_dim != input_dim:
            self._init_model(input_dim)

        assert self.net is not None
        self.net.to(dev)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.AdamW(
            self.net.parameters(), lr=lr, weight_decay=weight_decay
        )

        has_val = val_x is not None and val_y is not None
        if has_val:
            vx = _to_tensor(val_x, dev)
            vy = _to_tensor(val_y, dev).view(-1)
        else:
            vx = vy = None

        metrics: Dict[str, float] = {}

        for epoch in range(num_epochs):
            perm = torch.randperm(n_samples, device=dev)
            epoch_loss = 0.0

            for start in range(0, n_samples, batch_size):
                end = start + batch_size
                idx = perm[start:end]
                batch_x = x[idx]
                batch_y = y[idx]

                optimizer.zero_grad()
                logits = self.net(batch_x).squeeze(-1)
                loss = criterion(logits, batch_y)

                # Optional L1 on all weights
                if self.config.use_l1 and self.config.l1_lambda > 0.0:
                    l1 = 0.0
                    for name, p in self.net.named_parameters():
                        if "weight" in name:
                            l1 = l1 + p.abs().sum()
                    loss = loss + self.config.l1_lambda * l1

                loss.backward()
                optimizer.step()
                epoch_loss += loss.item() * batch_x.size(0)

            epoch_loss /= n_samples
            metrics["train_loss"] = epoch_loss

            if has_val and vx is not None and vy is not None:
                with torch.no_grad():
                    v_logits = self.net(vx).squeeze(-1)
                    v_loss = criterion(v_logits, vy).item()
                metrics["val_loss"] = v_loss

            if verbose:
                if has_val and "val_loss" in metrics:
                    print(
                        f"[MLPProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}, val_loss={metrics['val_loss']:.4f}"
                    )
                else:
                    print(
                        f"[MLPProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}"
                    )

        self.net.to(torch.device("cpu"))
        return metrics

    def predict_proba(self, x: ArrayLike, **kwargs: Any) -> np.ndarray:  # type: ignore[override]
        if self.net is None:
            raise RuntimeError("Probe has not been fitted yet (net is None).")
        self.net.eval()
        with torch.no_grad():
            t = _to_tensor(x, device=torch.device("cpu"))
            if t.ndim != 2:
                raise ValueError(f"x must be 2D (N, D), got shape {tuple(t.shape)}")
            logits = self.net(t).squeeze(-1)
            probs = torch.sigmoid(logits)
        return probs.cpu().numpy()

    def _state_dict(self) -> Dict[str, Any]:
        if self.net is None:
            raise RuntimeError("Cannot save an uninitialized MLPProbe.")
        return {
            "input_dim": self.input_dim,
            "state_dict": self.net.state_dict(),
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        input_dim = state["input_dim"]
        self._init_model(input_dim)
        assert self.net is not None
        self.net.load_state_dict(state["state_dict"])
        self.net.to(torch.device("cpu"))


# -------------------------
#  Attention pooling probe
# -------------------------


class AttentionPoolingProbe(BaseProbe):
    """Attention-style probe with learnable query & value vectors."""

    def __init__(self, config: ProbeConfig):
        if config.probe_type != "attn_pool":
            config.probe_type = "attn_pool"
        super().__init__(config)
        self.query: Optional[torch.Tensor] = None  # (D,)
        self.value: Optional[torch.Tensor] = None  # (D,)
        self.alpha: Optional[torch.Tensor] = None  # scalar
        self.beta: Optional[torch.Tensor] = None  # scalar
        self.input_dim: Optional[int] = None

    def _init_params(self, d_model: int, device: torch.device) -> None:
        self.input_dim = d_model
        std = 1.0 / (d_model ** 0.5)
        self.query = nn.Parameter(torch.randn(d_model, device=device) * std)
        self.value = nn.Parameter(torch.randn(d_model, device=device) * std)
        self.alpha = nn.Parameter(torch.tensor(1.0, device=device))
        self.beta = nn.Parameter(torch.tensor(0.0, device=device))
        self._params = nn.ParameterList([self.query, self.value, self.alpha, self.beta])

    def _check_init(self) -> None:
        if (
            self.query is None
            or self.value is None
            or self.alpha is None
            or self.beta is None
        ):
            raise RuntimeError("AttentionPoolingProbe is not initialized / fitted yet.")

    def _forward_logits(
        self,
        H: torch.Tensor,      # (B, T, D)
        lengths: torch.Tensor # (B,)
    ) -> torch.Tensor:
        """Compute logits for a batch."""
        self._check_init()
        assert self.query is not None and self.value is not None
        assert self.alpha is not None and self.beta is not None

        B, T, D = H.shape
        device = H.device

        scores = torch.einsum("btd,d->bt", H, self.query)  # (B, T)

        positions = torch.arange(T, device=device).unsqueeze(0)  # (1, T)
        mask = positions >= lengths.unsqueeze(1)                 # (B, T)
        scores = scores.masked_fill(mask, -1e9)

        attn = scores.softmax(dim=-1)  # (B, T)
        v_scores = torch.einsum("btd,d->bt", H, self.value)  # (B, T)
        s = (attn * v_scores).sum(dim=-1)  # (B,)
        logits = self.alpha * s + self.beta
        return logits

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        *,
        lengths: Optional[ArrayLike] = None,
        val_lengths: Optional[ArrayLike] = None,
        num_epochs: int = 5,
        lr: float = 1e-3,
        weight_decay: float = 0.0,
        batch_size: int = 32,
        device: Optional[str] = None,
        verbose: bool = False,
    ) -> Dict[str, float]:
        if lengths is None:
            raise ValueError("AttentionPoolingProbe.fit requires `lengths` kwarg.")

        if device is None:
            dev = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            dev = torch.device(device)

        H = _to_tensor(train_x, dev)              # (N, T, D)
        y = _to_tensor(train_y, dev).view(-1)     # (N,)
        lens = _to_tensor(lengths, dev).long()    # (N,)

        if H.ndim != 3:
            raise ValueError(f"train_x must be 3D (N, T, D), got shape {tuple(H.shape)}")
        if y.ndim != 1:
            raise ValueError(f"train_y must be 1D (N,), got shape {tuple(y.shape)}")

        N, T, D = H.shape

        if self.input_dim is None:
            self._init_params(D, dev)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.AdamW(
            self._params.parameters(), lr=lr, weight_decay=weight_decay
        )

        has_val = val_x is not None and val_y is not None and val_lengths is not None
        if has_val:
            vH = _to_tensor(val_x, dev)
            vy = _to_tensor(val_y, dev).view(-1)
            vlen = _to_tensor(val_lengths, dev).long()
        else:
            vH = vy = vlen = None

        metrics: Dict[str, float] = {}

        for epoch in range(num_epochs):
            perm = torch.randperm(N, device=dev)
            epoch_loss = 0.0

            for start in range(0, N, batch_size):
                end = start + batch_size
                idx = perm[start:end]
                batch_H = H[idx]
                batch_y = y[idx]
                batch_len = lens[idx]

                optimizer.zero_grad()
                logits = self._forward_logits(batch_H, batch_len)
                loss = criterion(logits, batch_y)
                loss.backward()
                optimizer.step()

                epoch_loss += loss.item() * batch_H.size(0)

            epoch_loss /= N
            metrics["train_loss"] = epoch_loss

            if has_val and vH is not None and vy is not None and vlen is not None:
                with torch.no_grad():
                    v_logits = self._forward_logits(vH, vlen)
                    v_loss = criterion(v_logits, vy).item()
                metrics["val_loss"] = v_loss

            if verbose:
                if has_val and "val_loss" in metrics:
                    print(
                        f"[AttentionPoolingProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}, val_loss={metrics['val_loss']:.4f}"
                    )
                else:
                    print(
                        f"[AttentionPoolingProbe] Epoch {epoch+1}/{num_epochs} "
                        f"- train_loss={epoch_loss:.4f}"
                    )

        # Move params to CPU
        self.query = self.query.detach().cpu() if self.query is not None else None
        self.value = self.value.detach().cpu() if self.value is not None else None
        self.alpha = self.alpha.detach().cpu() if self.alpha is not None else None
        self.beta = self.beta.detach().cpu() if self.beta is not None else None

        return metrics

    def predict_proba(
        self,
        x: ArrayLike,
        *,
        lengths: ArrayLike,
        **kwargs: Any,
    ) -> np.ndarray:  # type: ignore[override]
        if lengths is None:
            raise ValueError("AttentionPoolingProbe.predict_proba requires `lengths` kwarg.")
        self._check_init()

        with torch.no_grad():
            H = _to_tensor(x, device=torch.device("cpu"))
            lens = _to_tensor(lengths, device=torch.device("cpu")).long()
            if H.ndim != 3:
                raise ValueError(f"x must be 3D (N, T, D), got shape {tuple(H.shape)}")

            logits = self._forward_logits(H, lens)
            probs = torch.sigmoid(logits)
        return probs.cpu().numpy()

    def _state_dict(self) -> Dict[str, Any]:
        self._check_init()
        assert (
            self.query is not None
            and self.value is not None
            and self.alpha is not None
            and self.beta is not None
        )
        return {
            "input_dim": self.input_dim,
            "query": self.query,
            "value": self.value,
            "alpha": self.alpha,
            "beta": self.beta,
        }

    def _load_state_dict(self, state: Dict[str, Any]) -> None:
        self.input_dim = state["input_dim"]
        dev = torch.device("cpu")
        self.query = state["query"].float().to(dev)
        self.value = state["value"].float().to(dev)
        self.alpha = state["alpha"].float().to(dev)
        self.beta = state["beta"].float().to(dev)
        self._params = nn.ParameterList(
            [
                nn.Parameter(self.query, requires_grad=True),
                nn.Parameter(self.value, requires_grad=True),
                nn.Parameter(self.alpha, requires_grad=True),
                nn.Parameter(self.beta, requires_grad=True),
            ]
        )


# -------------------------
#  Streaming attention probe
# -------------------------


class StreamingAttentionProbe(nn.Module):
    """Small attention-pooling head over tokens.

    H: (B, T, D), lengths: (B,)
    - Compute per-token scores from a query MLP.
    - Softmax over valid tokens.
    - Weighted sum of value MLP outputs.
    - Logistic classifier on pooled vector.
    """

    def __init__(self, d_model: int, hidden_dim: int = 128):
        super().__init__()
        self.q_proj = nn.Linear(d_model, hidden_dim)
        self.v_proj = nn.Linear(d_model, hidden_dim)
        self.score = nn.Linear(hidden_dim, 1, bias=False)
        self.classifier = nn.Linear(hidden_dim, 1)

    def forward(self, H: torch.Tensor, lengths: torch.Tensor) -> torch.Tensor:
        """
        H: (B, T, D) float32
        lengths: (B,) int64, number of valid tokens per example
        Returns: logits (B,)
        """
        B, T, D = H.shape
        device = H.device

        positions = torch.arange(T, device=device).unsqueeze(0)  # (1, T)
        mask = positions < lengths.unsqueeze(1)  # (B, T), True for valid tokens

        q = torch.tanh(self.q_proj(H))  # (B, T, H)
        scores = self.score(q).squeeze(-1)  # (B, T)

        scores = scores.masked_fill(~mask, float("-inf"))
        attn = torch.softmax(scores, dim=1)  # (B, T)

        v = torch.tanh(self.v_proj(H))  # (B, T, H)
        pooled = torch.einsum("bt,bth->bh", attn, v)  # (B, H)

        logits = self.classifier(pooled).squeeze(-1)  # (B,)
        return logits


__all__ = [
    "ArrayLike",
    "ProbeConfig",
    "BaseProbe",
    "DenseLinearProbe",
    "MassMeanProbe",
    "MLPProbe",
    "AttentionPoolingProbe",
    "StreamingAttentionProbe",
    "load_probe",
]
