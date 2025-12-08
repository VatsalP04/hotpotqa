import torch
import torch.nn as nn
from typing import Optional
import torch.nn.functional as F


class BaselineProbe(nn.Module):
    def __init__(self, d_model: int, num_layers: int):
        super().__init__()
        self.num_layers = num_layers
        self.d_model = d_model
        
        self.classifiers = nn.ModuleList([
            nn.Linear(d_model, 1)
            for _ in range(num_layers)
        ])
    
    def forward(self, hidden_states: torch.Tensor, answer_token_indices: torch.Tensor) -> torch.Tensor:
        batch_size = hidden_states.shape[0]
        num_layers = hidden_states.shape[1]
        seq_len = hidden_states.shape[2]
        
        logits = []
        for layer_idx in range(num_layers):
            layer_hidden = hidden_states[:, layer_idx, :, :]
            
            batch_indices = torch.arange(batch_size, device=hidden_states.device)
            answer_hidden = layer_hidden[batch_indices, answer_token_indices]
            
            logit = self.classifiers[layer_idx](answer_hidden)
            logits.append(logit)
        
        return torch.stack(logits, dim=1)


class AttentionHeadProbe(nn.Module):
    def __init__(self, d_model: int, num_layers: int):
        super().__init__()
        self.num_layers = num_layers
        self.d_model = d_model
        
        # Use smaller initialization scale (0.001) to avoid softmax saturation
        self.q_vectors = nn.ParameterList([
            nn.Parameter(0.001 * torch.randn(d_model))
            for _ in range(num_layers)
        ])
        
        self.v_vectors = nn.ParameterList([
            nn.Parameter(0.001 * torch.randn(d_model))
            for _ in range(num_layers)
        ])
        
        # Add bias terms per layer (matching paper implementation)
        self.biases = nn.ParameterList([
            nn.Parameter(torch.zeros(1))
            for _ in range(num_layers)
        ])
    
    def forward(self, hidden_states: torch.Tensor, attn_mask: Optional[torch.Tensor] = None) -> torch.Tensor:
        """
        Forward pass for attention head probe.
        
        Args:
            hidden_states: [B, L, S, D] tensor of hidden states
            attn_mask: Optional [B, S] attention mask with 1 for real tokens, 0 for pads
        
        Returns:
            [B, L] tensor of logits per layer
        """
        B, L, S, D = hidden_states.shape
        logits = []
        
        for layer_idx in range(L):
            layer_hidden = hidden_states[:, layer_idx, :, :]   # [B, S, D]
            q = self.q_vectors[layer_idx]                      # [D]
            v = self.v_vectors[layer_idx]                      # [D]
            b = self.biases[layer_idx]                         # [1]
            
            scores = torch.einsum('bsd,d->bs', layer_hidden, q)  # [B, S]
            
            # Mask pad tokens before softmax (set to large negative value)
            if attn_mask is not None:
                # attn_mask: [B, S] with 1 for real tokens, 0 for pads
                scores = scores.masked_fill(attn_mask == 0, -10000.0)
            
            weights = F.softmax(scores, dim=-1)                 # [B, S]
            token_scores = torch.einsum('bsd,d->bs', layer_hidden, v)  # [B, S]
            
            # Weighted sum of token scores plus bias
            pooled = (weights * token_scores).sum(dim=1) + b    # [B]
            logits.append(pooled.unsqueeze(1))
        
        return torch.cat(logits, dim=1)  # [B, L]

