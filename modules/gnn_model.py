"""
APOLLO-M GNN Module
Replaces NetworkX statistics with real Graph Neural Network.
Architecture: GraphSAGE (inductive, works on unseen nodes)
Task: Community instability prediction from Reddit hyperlink graph

Input:  Reddit hyperlink network (35,776 nodes, 137,821 edges)
Output: Per-community instability score (0-1), risk classification
"""

import logging
import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pandas as pd
import networkx as nx
from pathlib import Path

log = logging.getLogger("APOLLO-M.GNN")

# ── Check PyG availability ─────────────────────────────────────
try:
    from torch_geometric.data import Data
    from torch_geometric.nn import SAGEConv, GCNConv, GATConv
    from torch_geometric.utils import from_networkx, degree
    GNN_AVAILABLE = True
    log.info("PyTorch Geometric available — using real GNN.")
except ImportError:
    GNN_AVAILABLE = False
    log.warning("PyTorch Geometric not available — using NetworkX fallback.")


# ── GraphSAGE Model ────────────────────────────────────────────
class GraphSAGE(nn.Module):
    """
    GraphSAGE for community instability prediction.
    Inductive learning — can generalize to new subreddits.
    3 layers: input → 128 → 64 → output
    """

    def __init__(self, in_channels: int, hidden_channels: int = 128,
                 out_channels: int = 1, num_layers: int = 3, dropout: float = 0.3):
        super().__init__()
        self.convs = nn.ModuleList()
        self.convs.append(SAGEConv(in_channels, hidden_channels))
        for _ in range(num_layers - 2):
            self.convs.append(SAGEConv(hidden_channels, hidden_channels))
        self.convs.append(SAGEConv(hidden_channels, out_channels))
        self.dropout = dropout

    def forward(self, x, edge_index):
        for i, conv in enumerate(self.convs[:-1]):
            x = conv(x, edge_index)
            x = F.relu(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.convs[-1](x, edge_index)
        return torch.sigmoid(x)


# ── GAT Model ─────────────────────────────────────────────────
class GAT(nn.Module):
    """
    Graph Attention Network — weights neighbor importance.
    Better for heterogeneous communities with varied interaction patterns.
    """

    def __init__(self, in_channels: int, hidden_channels: int = 64,
                 out_channels: int = 1, heads: int = 4, dropout: float = 0.3):
        super().__init__()
        self.conv1 = GATConv(in_channels, hidden_channels,
                             heads=heads, dropout=dropout)
        self.conv2 = GATConv(hidden_channels * heads, out_channels,
                             heads=1, concat=False, dropout=dropout)
        self.dropout = dropout

    def forward(self, x, edge_index):
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = F.elu(self.conv1(x, edge_index))
        x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.conv2(x, edge_index)
        return torch.sigmoid(x)


# ── GNN Pipeline ──────────────────────────────────────────────
class CommunityGNN:
    """
    Full GNN pipeline for APOLLO-M.
    1. Build graph from Reddit hyperlink network
    2. Extract node features from CHM scores
    3. Train GraphSAGE to predict instability
    4. Output per-community risk scores
    """

    def __init__(self, model_type: str = "sage", device: str = "cpu"):
        self.model_type = model_type
        self.device = device
        self.model = None
        self.node_map = {}       # subreddit name → node index
        self.node_names = []     # node index → subreddit name

    def build_graph_from_networkx(self, G: nx.DiGraph,
                                   chm_results: list) -> Data:
        """
        Convert NetworkX graph + CHM results to PyG Data object.
        Node features: [toxicity_rate, polarization, churn_rate,
                        echo_chamber_index, community_health_index,
                        in_degree, out_degree, sentiment]
        """
        log.info("Building PyG graph from Reddit hyperlink network...")

        # Build node index mapping
        all_nodes = list(G.nodes())
        self.node_names = all_nodes
        self.node_map = {node: i for i, node in enumerate(all_nodes)}
        n_nodes = len(all_nodes)

        # Build CHM lookup
        chm_lookup = {r["subreddit"].replace("r/", "").lower(): r
                      for r in chm_results}

        # ── Node features ──────────────────────────────────────
        features = []
        labels = []

        for node in all_nodes:
            node_key = str(node).lower().replace("r/", "")
            chm = chm_lookup.get(node_key, {})

            # Graph-based features
            in_deg  = G.in_degree(node) if G.in_degree(node) else 0
            out_deg = G.out_degree(node) if G.out_degree(node) else 0

            # Sentiment from edges
            out_edges = list(G.edges(node, data=True))
            sentiments = [d.get("weight", 0) for _, _, d in out_edges]
            avg_sentiment = np.mean(sentiments) if sentiments else 0.0
            neg_ratio = sum(1 for s in sentiments if s < 0) / len(sentiments) if sentiments else 0.0

            # CHM features (0 if community not in our dataset)
            tox   = float(chm.get("toxicity_rate", 0.1))
            polar = float(chm.get("polarization", 0.05))
            churn = float(chm.get("churn_rate", 0.5))
            echo  = float(chm.get("echo_chamber_index", 0.4))
            chi   = float(chm.get("community_health_index", 80)) / 100.0

            feat = [
                tox, polar, churn, echo, chi,
                min(in_deg / 100.0, 1.0),
                min(out_deg / 100.0, 1.0),
                (avg_sentiment + 1) / 2.0,  # normalize -1,1 to 0,1
                neg_ratio
            ]
            features.append(feat)

            # Label: 1 = at risk (CHI < 75), 0 = stable
            labels.append(1.0 if chi < 0.75 else 0.0)

        # ── Edge index ─────────────────────────────────────────
        edges = []
        for u, v in G.edges():
            if u in self.node_map and v in self.node_map:
                edges.append([self.node_map[u], self.node_map[v]])

        if not edges:
            log.warning("No edges found — using empty edge index")
            edge_index = torch.zeros((2, 0), dtype=torch.long)
        else:
            edge_index = torch.tensor(edges, dtype=torch.long).t().contiguous()

        x = torch.tensor(features, dtype=torch.float)
        y = torch.tensor(labels, dtype=torch.float).unsqueeze(1)

        data = Data(x=x, edge_index=edge_index, y=y)
        log.info(f"Graph built: {data.num_nodes} nodes, "
                 f"{data.num_edges} edges, "
                 f"{data.num_node_features} features")
        return data

    def train(self, data: Data, epochs: int = 50) -> list:
        """Train GNN on the community graph."""
        if not GNN_AVAILABLE:
            log.warning("GNN not available — skipping training.")
            return []

        in_channels = data.num_node_features

        if self.model_type == "sage":
            self.model = GraphSAGE(in_channels=in_channels,
                                   hidden_channels=128,
                                   out_channels=1,
                                   num_layers=3).to(self.device)
        else:
            self.model = GAT(in_channels=in_channels,
                             hidden_channels=64,
                             out_channels=1).to(self.device)

        optimizer = torch.optim.Adam(self.model.parameters(),
                                     lr=0.001, weight_decay=5e-4)
        criterion = nn.BCELoss()

        data = data.to(self.device)
        losses = []

        self.model.train()
        for epoch in range(epochs):
            optimizer.zero_grad()
            out = self.model(data.x, data.edge_index)
            loss = criterion(out, data.y)
            loss.backward()
            optimizer.step()
            losses.append(loss.item())

            if (epoch + 1) % 10 == 0:
                log.info(f"  GNN Epoch [{epoch+1}/{epochs}] "
                         f"Loss: {loss.item():.4f}")

        # Save model
        Path("models").mkdir(exist_ok=True)
        torch.save(self.model.state_dict(), "models/gnn_model.pt")
        log.info("GNN model saved → models/gnn_model.pt")
        return losses

    def predict(self, data: Data) -> dict:
        """
        Generate instability scores for all communities in the graph.
        Returns dict: {subreddit_name: instability_score}
        """
        if self.model is None:
            log.warning("GNN not trained — using degree centrality fallback.")
            return self._networkx_fallback(data)

        self.model.eval()
        data = data.to(self.device)

        with torch.no_grad():
            scores = self.model(data.x, data.edge_index).cpu().numpy().flatten()

        results = {}
        for i, name in enumerate(self.node_names):
            results[name] = round(float(scores[i]), 4)

        return results

    def analyze_community_graph(self, G: nx.DiGraph,
                                chm_results: list) -> pd.DataFrame:
        """
        Full GNN analysis pipeline.
        Returns DataFrame with GNN-predicted instability scores
        merged with CHM results.
        """
        log.info("\n── GNN LAYER (PyTorch Geometric) ────────────")

        if not GNN_AVAILABLE:
            log.warning("Using NetworkX fallback for graph analysis.")
            return self._networkx_analysis(G, chm_results)

        # Build graph
        data = self.build_graph_from_networkx(G, chm_results)

        # Train
        log.info(f"Training {self.model_type.upper()} on community graph...")
        losses = self.train(data, epochs=50)

        if losses:
            log.info(f"GNN training complete. "
                     f"Final loss: {losses[-1]:.4f}")

        # Predict
        scores = self.predict(data)

        # Merge with CHM results
        chm_df = pd.DataFrame(chm_results)
        chm_df["gnn_instability_score"] = chm_df["subreddit"].apply(
            lambda s: scores.get(s.replace("r/", ""), 0.5)
        )
        chm_df["gnn_risk"] = chm_df["gnn_instability_score"].apply(
            lambda s: "HIGH" if s > 0.7 else "MEDIUM" if s > 0.4 else "LOW"
        )

        log.info(f"GNN analysis complete for {len(chm_df)} communities.")
        log.info(f"GNN HIGH risk: {(chm_df['gnn_risk'] == 'HIGH').sum()} communities")
        log.info(f"GNN MEDIUM risk: {(chm_df['gnn_risk'] == 'MEDIUM').sum()} communities")
        log.info(f"GNN LOW risk: {(chm_df['gnn_risk'] == 'LOW').sum()} communities")

        return chm_df

    def _networkx_analysis(self, G: nx.DiGraph,
                           chm_results: list) -> pd.DataFrame:
        """NetworkX fallback when PyG not available."""
        log.info("Running NetworkX graph analysis...")
        chm_df = pd.DataFrame(chm_results)

        pagerank = nx.pagerank(G, alpha=0.85, max_iter=100)
        chm_df["gnn_instability_score"] = chm_df["subreddit"].apply(
            lambda s: round(pagerank.get(s.replace("r/", ""), 0.0) * 100, 4)
        )
        chm_df["gnn_risk"] = "MEDIUM"
        return chm_df

    def _networkx_fallback(self, data: Data) -> dict:
        return {name: 0.5 for name in self.node_names}