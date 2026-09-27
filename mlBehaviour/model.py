"""
model.py

A deliberately small/fast model, meant for verifying the pipeline works
end-to-end (data loads, shapes line up, loss goes down) before you invest in
anything bigger. ~Tens of thousands of parameters, trains on CPU in minutes
on a handful of clips.

Architecture: a couple of Conv1d layers (to look at local audio context)
feeding a single-layer GRU (to give it some memory across time), then a
linear head mapping to the Ohbot axes -- 8 by default (7 if the data was
converted with --exclude-head-tilt; n_axes is inferred from the data, see
ohbot_dataset.py). Output is squashed with sigmoid and scaled to [0, 10]
to match Ohbot's native range and the training targets produced by
beat2_to_ohbot.py.
"""

import torch
import torch.nn as nn


class OhbotAudioModel(nn.Module):
    def __init__(self, n_mels=40, n_axes=7, conv_channels=32, gru_hidden=64):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(n_mels, conv_channels, kernel_size=5, padding=2),
            nn.BatchNorm1d(conv_channels),
            nn.ReLU(),
            nn.Conv1d(conv_channels, conv_channels, kernel_size=5, padding=2),
            nn.BatchNorm1d(conv_channels),
            nn.ReLU(),
        )
        self.gru = nn.GRU(input_size=conv_channels, hidden_size=gru_hidden,
                           num_layers=1, batch_first=True)
        self.head = nn.Linear(gru_hidden, n_axes)

    def forward(self, features, lengths=None):
        """
        features: (B, T, n_mels)
        lengths:  (B,) optional, actual (unpadded) sequence lengths -- used
                  to pack the sequence so the GRU ignores padding.
        returns:  (B, T, n_axes) predicted servo values in [0, 10]
        """
        x = features.transpose(1, 2)          # (B, n_mels, T)
        x = self.conv(x)                      # (B, conv_channels, T)
        x = x.transpose(1, 2)                 # (B, T, conv_channels)

        if lengths is not None:
            packed = nn.utils.rnn.pack_padded_sequence(
                x, lengths.cpu(), batch_first=True, enforce_sorted=False)
            packed_out, _ = self.gru(packed)
            x, _ = nn.utils.rnn.pad_packed_sequence(
                packed_out, batch_first=True, total_length=features.shape[1])
        else:
            x, _ = self.gru(x)

        out = torch.sigmoid(self.head(x)) * 10.0
        return out

    def num_params(self):
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
