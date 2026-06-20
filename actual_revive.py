"""LP-based 'Actual Revive' rebalancer.

This module provides `actual_revive_rebalance(G, max_chunk_vars=20000)` which
implements the linear-program rebalancing described in Revive.pdf.
"""
import copy
import numpy as np
from scipy.optimize import linprog
import networkx as nx


def actual_revive_rebalance(G, max_chunk_vars=20000):
    """Run the LP-based 'Actual Revive' rebalancing.

    - Builds δ variables for directed edges with positive rebalancing need
      Δ_{u,v} = 0.5*(balance_uv + balance_vu) - balance_uv (msat units).
    - Solves maximize sum δ subject to node conservation and 0 <= δ <= min(Δ, balance_uv).
    - If overall problem is too large, decomposes into connected components and
      solves per-component; if a component is still too large, splits into node
      chunks to keep matrices tractable.
    """
    G_new = copy.deepcopy(G)

    # Build directed edge list and Δ/balance bounds
    edges = []  # list of (u,v)
    upper_msat = []
    nodes_set = set()

    for u, v, data in G_new.edges(data=True):
        # paired reverse edge must exist in our DiGraph
        if not G_new.has_edge(v, u):
            continue
        bal_uv = int(data.get('balance', 0))
        bal_vu = int(G_new[v][u].get('balance', 0))
        cap = int(data.get('capacity', bal_uv + bal_vu))
        delta_needed = (cap // 2) - bal_uv
        if delta_needed <= 0:
            continue

        ub = min(delta_needed, bal_uv)
        if ub <= 0:
            continue

        edges.append((u, v))
        upper_msat.append(int(ub))
        nodes_set.add(u); nodes_set.add(v)

    if not edges:
        return G_new

    # Induced undirected subgraph for decomposition
    H = nx.Graph()
    H.add_nodes_from(nodes_set)
    H.add_edges_from([(u, v) for u, v in edges])

    # Helper to solve LP for a component subgraph
    def solve_component(sub_nodes):
        # Collect variables (edges) within sub_nodes
        idx_map = {}
        var_edges = []
        ub = []
        for i, (u, v) in enumerate(edges):
            if u in sub_nodes and v in sub_nodes:
                idx_map[len(var_edges)] = i
                var_edges.append((u, v))
                ub.append(upper_msat[i])

        if not var_edges:
            return []  # nothing to apply

        # Map nodes to row indices
        node_list = sorted(list(sub_nodes))
        node_index = {n: i for i, n in enumerate(node_list)}

        n_vars = len(var_edges)
        n_nodes = len(node_list)

        # Objective: maximize sum(delta) -> minimize -sum(delta)
        c = -np.ones(n_vars, dtype=float)

        # A_eq: for each node row, sum_in - sum_out = 0
        A_eq = np.zeros((n_nodes, n_vars), dtype=float)
        for j, (u, v) in enumerate(var_edges):
            A_eq[node_index[v], j] += 1.0
            A_eq[node_index[u], j] -= 1.0

        b_eq = np.zeros(n_nodes, dtype=float)

        # Bounds per var in msat
        bounds = [(0.0, float(x)) for x in ub]

        try:
            res = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method='highs')
        except Exception:
            return []

        if not res.success:
            return []

        x = res.x

        # Floor to integer satoshis: convert msat->sats, floor, back to msat
        x_sats = np.floor(x / 1000.0).astype(np.int64)
        x_msat = (x_sats * 1000).astype(np.int64)

        # Apply deltas
        applied = []
        for j, val in enumerate(x_msat):
            if val <= 0:
                continue
            u, v = var_edges[j]
            # Add to u->v, subtract from v->u
            G_new[u][v]['balance'] = int(G_new[u][v].get('balance', 0)) + int(val)
            G_new[v][u]['balance'] = int(G_new[v][u].get('balance', 0)) - int(val)
            # Safety clamp
            if G_new[v][u]['balance'] < 0:
                G_new[v][u]['balance'] = 0
            applied.append((u, v, int(val)))

        return applied

    # Solve per connected component; if a component is too large, split into chunks
    applied_total = []
    for comp in nx.connected_components(H):
        comp_nodes = set(comp)
        # If comp has too many edges, split by node chunks
        comp_edges = [e for e in edges if e[0] in comp_nodes and e[1] in comp_nodes]
        if len(comp_edges) > max_chunk_vars:
            node_list = list(comp_nodes)
            chunk_size = max(1000, max_chunk_vars // 10)
            for i in range(0, len(node_list), chunk_size):
                chunk_nodes = set(node_list[i:i+chunk_size])
                applied = solve_component(chunk_nodes)
                applied_total.extend(applied)
        else:
            applied = solve_component(comp_nodes)
            applied_total.extend(applied)

    return G_new
