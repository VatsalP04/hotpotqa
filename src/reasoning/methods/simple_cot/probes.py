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
        
        self.q_vectors = nn.ParameterList([
            nn.Parameter(torch.randn(d_model))
            for _ in range(num_layers)
        ])
        
        self.v_vectors = nn.ParameterList([
            nn.Parameter(torch.randn(d_model))
            for _ in range(num_layers)
        ])
    
    def forward(self, hidden_states: torch.Tensor) -> torch.Tensor:
        batch_size = hidden_states.shape[0]
        num_layers = hidden_states.shape[1]
        seq_len = hidden_states.shape[2]
        
        logits = []
        for layer_idx in range(num_layers):
            layer_hidden = hidden_states[:, layer_idx, :, :]
            
            q = self.q_vectors[layer_idx]
            v = self.v_vectors[layer_idx]
            
            attention_scores = torch.einsum('bsd,d->bs', layer_hidden, q)
            attention_weights = F.softmax(attention_scores, dim=-1)
            
            token_scores = torch.einsum('bsd,d->bs', layer_hidden, v)
            
            logit = torch.einsum('bs,bs->b', attention_weights, token_scores)
            
            logits.append(logit.unsqueeze(1))
        
        return torch.cat(logits, dim=1)

