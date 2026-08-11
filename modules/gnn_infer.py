"""
GraphSAGE inference without torch_geometric.

modules/gnn_model.py defines and trains the GNN, but it imports torch_geometric,
which is not installed in this environment — which is precisely why the trained
model in models/gnn_model.pt has never been used by the pipeline. Installing
torch_geometric pulls compiled extensions pinned to a specific torch build and is
a poor thing to attempt near a deadline.

The forward pass does not need it. PyG's SAGEConv with mean aggregation computes

    h_i = W_l . mean_{j in N(i)} x_j  +  b  +  W_r . x_i

and the checkpoint contains exactly those tensors (`convs.k.lin_l.weight`,
`convs.k.lin_l.bias`, `convs.k.lin_r.weight`; lin_r carries no bias, matching
PyG's bias=False). Reimplementing it in plain PyTorch is a few lines, adds no
dependency, and produces the same numbers as the trained model.

Node features must be built in the same order the model was trained on
(see CommunityGNN.build_graph_from_networkx):

    [toxicity_rate, polarization, churn_rate, echo_chamber_index,
     community_health_index/100, in_degree/100, out_degree/100,
     (avg_sentiment+1)/2, negative_edge_ratio]
"""

from __future__ import annotations

import logging
from pathlib import Path

import networkx as nx
import numpy as np
import torch
import torch.nn.functional as F

log = logging.getLogger("APOLLO-M.GNN")

ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "models" / "gnn_model.pt"
N_FEATURES = 9


def build_features(graph: nx.DiGraph, chm_results: list) -> tuple:
    """Node feature matrix in the training order, plus the node list."""
    nodes = list(graph.nodes())
    idx = {n: i for i, n in enumerate(nodes)}
    lookup = {str(r["subreddit"]).replace("r/", "").lower(): r for r in chm_results}

    feats = []
    for n in nodes:
        chm = lookup.get(str(n).lower().replace("r/", ""), {})
        in_deg, out_deg = graph.in_degree(n), graph.out_degree(n)
        sentiments = [d.get("weight", 0) for _, _, d in graph.edges(n, data=True)]
        avg_sent = float(np.mean(sentiments)) if sentiments else 0.0
        neg_ratio = (sum(1 for s in sentiments if s < 0) / len(sentiments)
                     if sentiments else 0.0)
        feats.append([
            float(chm.get("toxicity_rate", 0.1)),
            float(chm.get("polarization", 0.05)),
            float(chm.get("churn_rate", 0.5)),
            float(chm.get("echo_chamber_index", 0.4)),
            float(chm.get("community_health_index", 80)) / 100.0,
            min(in_deg / 100.0, 1.0),
            min(out_deg / 100.0, 1.0),
            (avg_sent + 1) / 2.0,
            neg_ratio,
        ])
    return torch.tensor(feats, dtype=torch.float), nodes, idx


def _mean_aggregate(x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
    """Mean of each node's in-neighbours; isolated nodes aggregate to zero."""
    n = x.size(0)
    out = torch.zeros_like(x)
    if edge_index.numel() == 0:
        return out
    src, dst = edge_index[0], edge_index[1]
    out.index_add_(0, dst, x[src])
    counts = torch.zeros(n, device=x.device).index_add_(
        0, dst, torch.ones(src.size(0), device=x.device))
    return out / counts.clamp(min=1).unsqueeze(1)


def forward(state: dict, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
    """Run the 3-layer SAGE stack exactly as GraphSAGE.forward does."""
    n_layers = len({k.split(".")[1] for k in state if k.startswith("convs.")})
    h = x
    for i in range(n_layers):
        wl = state[f"convs.{i}.lin_l.weight"]
        bl = state.get(f"convs.{i}.lin_l.bias")
        wr = state[f"convs.{i}.lin_r.weight"]
        h = F.linear(_mean_aggregate(h, edge_index), wl, bl) + F.linear(h, wr)
        if i < n_layers - 1:
            h = F.relu(h)
    return h


def community_risk(graph: nx.DiGraph, chm_results: list) -> dict:
    """
    Structural risk in [0, 1] for every community present in the graph.

    Returns an empty dict when the weights are absent, so a caller can degrade
    to "no GNN column" rather than fail.
    """
    if not WEIGHTS.exists():
        log.warning("models/gnn_model.pt not found — skipping GNN inference")
        return {}

    state = torch.load(WEIGHTS, map_location="cpu", weights_only=False)
    in_dim = state["convs.0.lin_l.weight"].shape[1]
    if in_dim != N_FEATURES:
        log.warning("checkpoint expects %d features, builder produces %d — skipping",
                    in_dim, N_FEATURES)
        return {}

    x, nodes, idx = build_features(graph, chm_results)
    edges = [[idx[u], idx[v]] for u, v in graph.edges() if u in idx and v in idx]
    edge_index = (torch.tensor(edges, dtype=torch.long).t().contiguous()
                  if edges else torch.zeros((2, 0), dtype=torch.long))

    with torch.no_grad():
        logits = forward(state, x, edge_index)
        risk = torch.sigmoid(logits).squeeze(-1)

    log.info("GNN inference over %d nodes / %d edges", x.size(0), edge_index.size(1))
    return {str(n).replace("r/", "").lower(): float(r) for n, r in zip(nodes, risk)}
