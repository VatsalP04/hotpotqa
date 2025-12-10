"""
Lightweight probes for Llama hidden states.

This module defines:
- ProbeConfig: configuration dataclass for probes.
- BaseProbe: abstract base class.
- DenseLinearProbe: linear probe on hidden states (optionally L1-sparse).
- MassMeanProbe: "mass-mean direction" probe with 1D logistic calibration.

All probes are designed to be fast to train on relatively small datasets
(<= ~10k examples) and moderate-dimensional inputs (e.g. residual stream).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Union

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F


ArrayLike = Union[np.ndarray, torch.Tensor]


# -------------------------
#  Config & base class
# -------------------------


@dataclass
class ProbeConfig:
    """Configuration for a probe.

    Attributes
    ----------
    probe_type:
        One of {"dense_linear", "mass_mean"}.
    layer:
        Layer index this probe is associated with (if applicable).
    task_name:
        Name of the target task, e.g. "correct", "correct_given_recall1",
        or "recall_full".
    feature_names:
        Optional list of names for each input feature. Purely metadata.
    use_l1:
        Whether to use L1 regularization on the weights (for dense linear probes).
    l1_lambda:
        Strength of L1 penalty (if use_l1 is True).
    """

    probe_type: str
    layer: Optional[int] = None
    task_name: str = "correct"
    feature_names: Optional[List[str]] = None
    use_l1: bool = False
    l1_lambda: float = 0.0


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

    def fit(  # type: ignore[override]
        self,
        train_x: ArrayLike,
        train_y: ArrayLike,
        val_x: Optional[ArrayLike] = None,
        val_y: Optional[ArrayLike] = None,
        **kwargs: Any,
    ) -> Dict[str, float]:
        """Fit the probe on training data.

        Parameters
        ----------
        train_x:
            Training features, shape (N, D).
        train_y:
            Training labels, shape (N,) or (N, 1), values in {0, 1}.
        val_x, val_y:
            Optional validation data for monitoring.

        Returns
        -------
        metrics:
            Dictionary of metrics (at least train_loss; possibly val_loss).
        """
        raise NotImplementedError

    def predict_proba(self, x: ArrayLike) -> np.ndarray:
        """Predict probabilities P(y=1 | x).

        Parameters
        ----------
        x:
            Features, shape (N, D).

        Returns
        -------
        probs:
            numpy array of shape (N,) with values in [0, 1].
        """
        raise NotImplementedError

    def predict(self, x: ArrayLike, threshold: float = 0.5) -> np.ndarray:
        """Predict binary labels using a given threshold."""
        probs = self.predict_proba(x)
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
    """Load a probe (any subclass) from disk.

    Parameters
    ----------
    path:
        File path passed to torch.save in `BaseProbe.save`.

    Returns
    -------
    probe:
        An instance of DenseLinearProbe or MassMeanProbe.
    """
    payload = torch.load(path, map_location="cpu")
    probe_type = payload["probe_type"]
    config_dict = payload["config"]
    state = payload["state"]
    config = ProbeConfig(**config_dict)

    if probe_type == "dense_linear":
        probe: BaseProbe = DenseLinearProbe(config)
    elif probe_type == "mass_mean":
        probe = MassMeanProbe(config)
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

        assert self.linear is not None  # for type checker
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
        global_step = 0

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
                global_step += 1

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

    def predict_proba(self, x: ArrayLike) -> np.ndarray:  # type: ignore[override]
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
    """Mass-mean direction probe with 1D logistic calibration.

    For a given task and layer, we:
      - Compute class means μ_pos, μ_neg in activation space.
      - Define a direction v = μ_pos - μ_neg (normalized).
      - Project activations onto this direction (optionally centered).
      - Fit a scalar logistic regression on the projections.

    This is inspired by "truth direction" / mass-mean probing ideas, but
    implemented as a simple, fast heuristic.
    """

    def __init__(self, config: ProbeConfig):
        if config.probe_type != "mass_mean":
            config.probe_type = "mass_mean"
        super().__init__(config)

        # Learned / computed quantities
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
        weight_decay: float = 0.0,  # unused, present for API compatibility
        batch_size: int = 0,  # unused (we train alpha/beta on all data at once)
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
            # Degenerate case: collapse to a simple all-ones direction
            v = torch.ones_like(v)
            v_norm = v.norm(p=2)
        v = v / v_norm

        center = 0.5 * (mu_pos + mu_neg)

        self.direction = v.detach().clone()
        self.center = center.detach().clone()

        # Compute scalar projections s = (x - center) dot v
        x_centered = x - self.center
        s = torch.einsum("nd,d->n", x_centered, self.direction)

        # Fit scalar logistic regression: p = sigmoid(alpha * s + beta).
        alpha = torch.zeros(1, device=dev, requires_grad=True)
        beta = torch.zeros(1, device=dev, requires_grad=True)

        criterion = nn.BCEWithLogitsLoss()
        optimizer = torch.optim.Adam([alpha, beta], lr=lr, weight_decay=weight_decay)

        metrics: Dict[str, float] = {}

        # Optional validation set
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

        # Store learned alpha/beta on CPU
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

    def predict_proba(self, x: ArrayLike) -> np.ndarray:  # type: ignore[override]
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


__all__ = [
    "ProbeConfig",
    "BaseProbe",
    "DenseLinearProbe",
    "MassMeanProbe",
    "load_probe",
]