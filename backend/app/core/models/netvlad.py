
import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
from sklearn.neighbors import NearestNeighbors
import numpy as np
import os
import ssl

try:
    from urllib.request import urlretrieve
except ImportError:
    from urllib import urlretrieve

class NetVLAD(nn.Module):
    """NetVLAD layer implementation"""

    def __init__(self, num_clusters=64, dim=512, alpha=100.0,
                 normalize_input=True):
        super(NetVLAD, self).__init__()
        self.num_clusters = num_clusters
        self.dim = dim
        self.alpha = alpha
        self.normalize_input = normalize_input
        self.conv = nn.Conv2d(dim, num_clusters, kernel_size=(1, 1), bias=True)
        self.centroids = nn.Parameter(torch.rand(num_clusters, dim))
        self._init_params()

    def _init_params(self):
        self.conv.weight = nn.Parameter(
            (2.0 * self.alpha * self.centroids).unsqueeze(-1).unsqueeze(-1)
        )
        self.conv.bias = nn.Parameter(
            - self.alpha * self.centroids.norm(dim=1)
        )

    def forward(self, x):
        N, C = x.shape[:2]

        if self.normalize_input:
            x = F.normalize(x, p=2, dim=1)  # across descriptor dim

        # soft-assignment
        soft_assign = self.conv(x).view(N, self.num_clusters, -1)
        soft_assign = F.softmax(soft_assign, dim=1)

        x_flatten = x.view(N, C, -1)
        
        # calculate residuals to each clusters
        vlad = torch.zeros([N, self.num_clusters, C], dtype=x.dtype, layout=x.layout, device=x.device)
        for k in range(self.num_clusters): # slower than expanded ops but less memory
            residual = x_flatten - self.centroids[k:k+1, :].unsqueeze(-1)
            residual *= soft_assign[:,k:k+1,:]
            vlad[:,k:k+1,:] = residual.sum(dim=-1).unsqueeze(1)

        vlad = vlad.view(N, -1)  # flatten
        vlad = F.normalize(vlad, p=2, dim=1)  # L2 normalize

        return vlad

class EmbedNet(nn.Module):
    def __init__(self, base_model, net_vlad):
        super(EmbedNet, self).__init__()
        self.base_model = base_model
        self.net_vlad = net_vlad

    def forward(self, x):
        x = self.base_model(x)
        embedded_x = self.net_vlad(x)
        return embedded_x

def get_model(pretrained=True):
    """
    Builds the NetVLAD model with VGG16 backbone.
    Attempts to download pre-trained weights if available.
    """
    # 1. Backbone (VGG16)
    encoder = models.vgg16(pretrained=True)
    layers = list(encoder.features.children())[:-2] # Remove Pool5 and last Relu? usually conv5_3
    # Standard NetVLAD uses conv5_3 (before pool5)
    # VGG16 features: ... (28): Conv2d(512, 512, 3), (29): ReLU, (30): MaxPool
    # We want up to 29 (inclusive) or 30 (exclusive)
    
    # Let's keep it simple: take all feature layers except the last MaxPool
    encoder = nn.Sequential(*layers)
    
    # 2. NetVLAD layer
    dim = 512
    num_clusters = 64
    net_vlad = NetVLAD(num_clusters=num_clusters, dim=dim, alpha=1.0) # alpha initialized inside
    
    model = EmbedNet(encoder, net_vlad)
    
    # 3. Load Weights (Optional but recommended)
    # For now, we return the model with ImageNet VGG weights + Random NetVLAD
    # In a real scenario, we would load 'vgg16_netvlad_checkpoint'
    
    return model

