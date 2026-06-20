import os
import copy
import itertools
import pandas as pd
import matplotlib.pyplot as plt
import random
from ln_simulation_core import LightningStatefulSimulator, apply_revive
from sensitivity_script import get_chaos_graph
from smart_lifeline_agent import SmartLifelineAgent
from workload_generator import generate_workload
from actual_revive import actual_revive_rebalance

GRAPH_FILE = "data/lngraph_2021_11_25__16_00.json"
METRICS_FILE = "data/rich_node_features_dynamic.csv"
FALLBACK_METRICS_FILE = "data/rich_node_features.csv"
OUTPUT_PLOT = "budget_war_depletion_test4.png"
OUTPUT_CSV = "budget_war_depletion_test4.csv"
HUB_LIQ_CSV = "hub_outbound_liquidity_at_start4.csv"

SHADUF_BIND_SATS = 127531
LIFELINE_FEE_SATS = 4722
TOTAL_BUDGET_SATS = 600_000_000
N = TOTAL_BUDGET_SATS // SHADUF_BIND_SATS
BIND_M = 5
BIND_RATIO = 0.5
TRANSACTION_COUNT = 2_000
BATCH_SIZE = 1000
TOTAL_BATCHES = TRANSACTION_COUNT // BATCH_SIZE
# Depletion fraction range applied to each outbound channel of targeted hubs.
# Balance after depletion will be set to: int(capacity * uniform(DEPL_FRAC_MIN, DEPL_FRAC_MAX))
# Set these to tune how severely hubs are drained (0.0 .. 1.0).
DEPL_FRAC_MIN = 0.0
DEPL_FRAC_MAX = 0.2
DEPL_RANDOM_SEED = None


def load_top_hubs(features_csv, top_n):
    used_file = features_csv
    if not os.path.exists(features_csv):
        if os.path.exists(FALLBACK_METRICS_FILE):
            used_file = FALLBACK_METRICS_FILE
        else:
            raise FileNotFoundError(f"Metrics CSV not found: {features_csv}")

    df = pd.read_csv(used_file)
    node_col = None
    for candidate in ["node_pub", "node_id", "node", "pubkey", "node_pubkey"]:
        if candidate in df.columns:
            node_col = candidate
            break

    if node_col is None:
        raise ValueError("Could not find a node identifier column in the features CSV.")

    score_col = None
    for c in ["lifeline_score", "score", "eigenvector", "betweenness"]:
        if c in df.columns:
            score_col = c
            break

    if score_col is None:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        score_col = numeric_cols[0] if numeric_cols else node_col

    top_df = df.sort_values(by=score_col, ascending=False)
    hubs = []
    seen = set()
    for value in top_df[node_col].tolist():
        if value not in seen:
            hubs.append(value)
            seen.add(value)
            if len(hubs) >= top_n:
                break

    if len(hubs) < top_n:
        remaining = top_n - len(hubs)
        duplicate_fill = [v for v in top_df[node_col].tolist() if v in seen]
        while len(hubs) < top_n and duplicate_fill:
            hubs.append(duplicate_fill[len(hubs) % len(duplicate_fill)])
        hubs = hubs[:top_n]

    return hubs, used_file


def build_lifeline_graph(base_G, target_hubs, agent, capacity_msat):
    G_lifeline = copy.deepcopy(base_G)
    if not target_hubs:
        return G_lifeline

    hubs_df = pd.DataFrame({"node_pub": target_hubs})
    prescriptions = agent.generate_prescriptions(hubs_df, num_lifelines=1)

    added_edges = []
    for rec in prescriptions:
        u, v = rec.get("u"), rec.get("v")
        if u is None or v is None or u == v:
            continue
        if G_lifeline.has_edge(u, v):
            continue

        G_lifeline.add_edge(u, v, capacity=capacity_msat, balance=capacity_msat // 2, base_fee=1000, fee_rate=1)
        G_lifeline.add_edge(v, u, capacity=capacity_msat, balance=capacity_msat // 2, base_fee=1000, fee_rate=1)
        added_edges.append((u, v))

    # Best-effort fill if not enough edges
    if len(added_edges) < len(target_hubs):
        donors = [n for n in agent.rich_nodes if n not in target_hubs]
        donors_cycle = itertools.cycle(donors or target_hubs)
        for hub in target_hubs:
            if any(u == hub for u, _ in added_edges):
                continue

            for _ in range(len(donors) + 5 if donors else 10):
                donor = next(donors_cycle)
                if donor == hub or G_lifeline.has_edge(hub, donor):
                    continue
                G_lifeline.add_edge(hub, donor, capacity=capacity_msat, balance=capacity_msat // 2, base_fee=1000, fee_rate=1)
                G_lifeline.add_edge(donor, hub, capacity=capacity_msat, balance=capacity_msat // 2, base_fee=1000, fee_rate=1)
                added_edges.append((hub, donor))
                break

    return G_lifeline


def starve_top_hubs(G, hub_list, min_frac=DEPL_FRAC_MIN, max_frac=DEPL_FRAC_MAX, seed=DEPL_RANDOM_SEED):
    """For each hub in hub_list, deplete each outbound edge's balance to a
    random fraction in [min_frac, max_frac] of the channel capacity. The
    counterparty (reverse edge) keeps full capacity to model asymmetric
    liquidity. Returns dict of hub -> (before_outbound_msat, after_outbound_msat).

    Args:
        G: networkx DiGraph-like graph with directed edges containing
           'capacity' and 'balance'.
        hub_list: iterable of hub node ids to target.
        min_frac: minimum remaining fraction after depletion (0.0 .. 1.0).
        max_frac: maximum remaining fraction after depletion (0.0 .. 1.0).
        seed: optional RNG seed for reproducibility.
    """
    rng = random.Random(seed) if seed is not None else random
    stats = {}

    for hub in hub_list:
        if hub not in G:
            stats[hub] = (0, 0)
            continue

        # sum outbound before
        before = sum(data.get('balance', 0) for _, _, data in G.out_edges(hub, data=True))

        # For each outbound edge u->v set balance to a small random fraction
        # of capacity, and give v->u full capacity balance.
        for _, v, data in list(G.out_edges(hub, data=True)):
            cap = data.get('capacity', 0)
            # new remaining fraction for hub->v
            frac = rng.uniform(min_frac, max_frac)
            new_bal = int(cap * frac)
            data['balance'] = new_bal

            # ensure reverse edge v->hub exists and has full capacity balance
            if G.has_edge(v, hub):
                rdata = G[v][hub]
                rcap = rdata.get('capacity', cap)
                rdata['balance'] = rcap
            else:
                # add reverse edge with symmetric capacity and full balance
                G.add_edge(v, hub, capacity=cap, balance=cap, base_fee=1000, fee_rate=1)

        after = sum(data.get('balance', 0) for _, _, data in G.out_edges(hub, data=True))
        stats[hub] = (before, after)

    return stats


def build_shaduf_bindings(G, hubs, M, binding_ratio=0.5):
    bindings = {}
    bound_pool = {}
    for hub in hubs:
        if hub not in G:
            continue

        outgoing = [(v, data.get("capacity", 0)) for _, v, data in G.out_edges(hub, data=True)]
        incoming = [(u, data.get("capacity", 0)) for u, _, data in G.in_edges(hub, data=True)]
        neighbor_caps = {}
        for neighbor, cap in outgoing + incoming:
            neighbor_caps[neighbor] = max(neighbor_caps.get(neighbor, 0), cap)

        selected = [node for node, _ in sorted(neighbor_caps.items(), key=lambda item: item[1], reverse=True)][:M]
        bindings[hub] = selected

        pool = []
        for partner in selected:
            locked = 0
            if G.has_edge(partner, hub):
                p_data = G[partner][hub]
                cap = p_data.get('capacity', 0)
                lock_amt = int(cap * binding_ratio)
                available = p_data.get('balance', 0)
                lock_amt = min(lock_amt, available)
                if lock_amt > 0:
                    p_data['balance'] -= lock_amt
                    locked = lock_amt
            elif G.has_edge(hub, partner):
                p_data = G[hub][partner]
                cap = p_data.get('capacity', 0)
                lock_amt = int(cap * binding_ratio)
                available = p_data.get('balance', 0)
                lock_amt = min(lock_amt, available)
                if lock_amt > 0:
                    p_data['balance'] -= lock_amt
                    locked = lock_amt

            if locked > 0:
                pool.append((partner, locked))

        bound_pool[hub] = pool

    G.graph['shaduf_bound_pool'] = bound_pool
    return bindings


def run_batch(graph, batch, tx_prefix=0):
    sim = LightningStatefulSimulator(GRAPH_FILE)
    sim.G = graph

    success_count = 0
    volume_msat = 0
    results = []

    for tx in batch:
        ok = sim.execute_transaction(tx["src"], tx["dst"], tx["amount"], tx["id"] + tx_prefix)
        results.append(bool(ok))
        if ok:
            success_count += 1
            volume_msat += tx["amount"]

    return success_count, volume_msat, sim.G, results


def simulate_strategy(name, graph, workload, rebalance_fn=None, target_hubs=None):
    current_G = copy.deepcopy(graph)
    cumulative_success = 0
    cumulative_volume = 0
    history = []

    target_hubs_set = set(target_hubs or [])

    print(f"\n🏁 Simulating strategy: {name}")
    for batch_index in range(TOTAL_BATCHES):
        start = batch_index * BATCH_SIZE
        end = start + BATCH_SIZE
        batch = workload[start:end]

        success, volume, current_G, results = run_batch(current_G, batch, tx_prefix=batch_index * BATCH_SIZE)
        cumulative_success += success
        cumulative_volume += volume

        # compute targeted txn success for the first batch
        targeted_success = None
        targeted_total = None
        if batch_index == 0 and target_hubs_set:
            targeted_total = 0
            targeted_success = 0
            for i, tx in enumerate(batch):
                if tx['src'] in target_hubs_set or tx['dst'] in target_hubs_set:
                    targeted_total += 1
                    if results[i]:
                        targeted_success += 1

        if rebalance_fn is not None:
            current_G = rebalance_fn(current_G)

        success_pct = (cumulative_success / ((batch_index + 1) * BATCH_SIZE)) * 100
        history.append({
            "batch": batch_index + 1,
            "cumulative_transactions": (batch_index + 1) * BATCH_SIZE,
            "cumulative_success": cumulative_success,
            "cumulative_volume_msat": cumulative_volume,
            "cumulative_success_pct": success_pct,
            "first_batch_targeted_total": targeted_total,
            "first_batch_targeted_success": targeted_success,
        })

        if (batch_index + 1) % 50 == 0 or batch_index == 0:
            print(f"   {name}: batch {batch_index + 1}/{TOTAL_BATCHES} -> {success_pct:.2f}%")

    return history


def run_depletion_test():
    print("🚀 Budget War Depletion Test: Targeted Hub Starvation")

    base_G = get_chaos_graph(GRAPH_FILE)
    target_hubs, metrics_file = load_top_hubs(METRICS_FILE, N)
    agent = SmartLifelineAgent(metrics_file)

    print(f"   Targeting top {len(target_hubs)} hubs for starvation and treatment.")

    # record outbound liquidity before any manipulation
    pre_stats = {h: sum(d.get('balance', 0) for _, _, d in base_G.out_edges(h, data=True)) for h in target_hubs}

    # Starve the hubs in-place
    starve_stats = starve_top_hubs(base_G, target_hubs)

    # write hub liquidity stats
    rows = []
    for h in target_hubs:
        before, after = starve_stats.get(h, (pre_stats.get(h, 0), 0))
        rows.append({"hub": h, "outbound_before_msat": before, "outbound_after_msat": after})
    pd.DataFrame(rows).to_csv(HUB_LIQ_CSV, index=False)
    print(f"💾 Saved hub outbound liquidity to {HUB_LIQ_CSV}")

    # Prepare arms
    shaduf_graph = copy.deepcopy(base_G)

    # Build shaduf bindings on the starved graph (these will be ineffective)
    shaduf_bindings = build_shaduf_bindings(shaduf_graph, target_hubs, BIND_M)

    # Lifeline graph built from the starved base (structural injection)
    total_injection_sats = TOTAL_BUDGET_SATS - (N * LIFELINE_FEE_SATS)
    total_injection_msat = total_injection_sats * 1000
    lifeline_capacity_msat = total_injection_msat // N
    lifeline_graph = build_lifeline_graph(base_G, target_hubs, agent, lifeline_capacity_msat)

    # Generate workload once
    workload = generate_workload(base_G, TRANSACTION_COUNT)
    print(f"   Created workload: {len(workload)} transactions")

    # Baseline (No Intervention) - runs the starved network as-is
    baseline_graph = copy.deepcopy(base_G)
    history_baseline = simulate_strategy(
        "Baseline (No Intervention)",
        baseline_graph,
        workload,
        rebalance_fn=None,
        target_hubs=target_hubs,
    )

    # Arm A: Shaduf++ (will be starved)
    history_shaduf = simulate_strategy(
        "Shaduf++",
        shaduf_graph,
        workload,
        rebalance_fn=lambda g: apply_shaduf_rebalance(g, shaduf_bindings, BIND_RATIO) if 'apply_shaduf_rebalance' in globals() else g,
        target_hubs=target_hubs,
    )

    # Arm B: Lifeline Only (no revive)
    lifeline_only_graph = copy.deepcopy(lifeline_graph)
    history_lifeline_only = simulate_strategy(
        "Lifeline Only",
        lifeline_only_graph,
        workload,
        rebalance_fn=None,
        target_hubs=target_hubs,
    )

    # Arm C: Lifeline + 50/50 Revive (perfect revive helper)
    lifeline_revive_graph = copy.deepcopy(lifeline_graph)
    history_lifeline_revive_5050 = simulate_strategy(
        "Lifeline + 50/50 Revive",
        lifeline_revive_graph,
        workload,
        rebalance_fn=apply_revive,
        target_hubs=target_hubs,
    )

    # Arm D: Lifeline + Actual Revive (structural injection + LP)
    history_lifeline_actual = simulate_strategy(
        "Lifeline + Actual Revive",
        lifeline_graph,
        workload,
        rebalance_fn=lambda g: actual_revive_rebalance(g),
        target_hubs=target_hubs,
    )

    # Assemble results and save
    history_df = pd.DataFrame({
        "batch": [r["batch"] for r in history_shaduf],
        "baseline_cumulative_success_pct": [r["cumulative_success_pct"] for r in history_baseline],
        "baseline_first_batch_targeted_total": [r.get("first_batch_targeted_total") for r in history_baseline],
        "baseline_first_batch_targeted_success": [r.get("first_batch_targeted_success") for r in history_baseline],
        "shaduf_cumulative_success_pct": [r["cumulative_success_pct"] for r in history_shaduf],
        "shaduf_first_batch_targeted_total": [r.get("first_batch_targeted_total") for r in history_shaduf],
        "shaduf_first_batch_targeted_success": [r.get("first_batch_targeted_success") for r in history_shaduf],

        "lifeline_only_cumulative_success_pct": [r["cumulative_success_pct"] for r in history_lifeline_only],
        "lifeline_only_first_batch_targeted_total": [r.get("first_batch_targeted_total") for r in history_lifeline_only],
        "lifeline_only_first_batch_targeted_success": [r.get("first_batch_targeted_success") for r in history_lifeline_only],

        "lifeline_5050_cumulative_success_pct": [r["cumulative_success_pct"] for r in history_lifeline_revive_5050],
        "lifeline_5050_first_batch_targeted_total": [r.get("first_batch_targeted_total") for r in history_lifeline_revive_5050],
        "lifeline_5050_first_batch_targeted_success": [r.get("first_batch_targeted_success") for r in history_lifeline_revive_5050],

        "lifeline_actual_cumulative_success_pct": [r["cumulative_success_pct"] for r in history_lifeline_actual],
        "lifeline_actual_first_batch_targeted_total": [r.get("first_batch_targeted_total") for r in history_lifeline_actual],
        "lifeline_actual_first_batch_targeted_success": [r.get("first_batch_targeted_success") for r in history_lifeline_actual],
    })
    history_df.to_csv(OUTPUT_CSV, index=False)
    print(f"💾 Saved depletion test history to {OUTPUT_CSV}")

    x = history_df['batch'].tolist()
    y_baseline = history_df['baseline_cumulative_success_pct'].tolist()
    y_shaduf = history_df['shaduf_cumulative_success_pct'].tolist()
    y_lifeline_only = history_df['lifeline_only_cumulative_success_pct'].tolist()
    y_lifeline_5050 = history_df['lifeline_5050_cumulative_success_pct'].tolist()
    y_lifeline = history_df['lifeline_actual_cumulative_success_pct'].tolist()

    plt.figure(figsize=(12, 7))
    plt.plot(x, y_baseline, label='Baseline (No Intervention)', color='#444444', linestyle=':')
    plt.plot(x, y_shaduf, label='Shaduf++ (Starved)', color='#6a1b9a')
    plt.plot(x, y_lifeline_only, label='Lifeline Only', color='#1565c0')
    plt.plot(x, y_lifeline_5050, label='Lifeline + 50/50 Revive', color='#2e7d32', linestyle='--')
    plt.plot(x, y_lifeline, label='Lifeline + Actual Revive', color='#ff8f00')
    plt.title('Depletion Test: Success Ratio vs Batch Index (Starved Hub Scenario)')
    plt.xlabel('Batch Index (1,000 tx)')
    plt.ylabel('Cumulative Success Rate (%)')
    plt.legend()
    plt.grid(alpha=0.25)
    plt.tight_layout()
    plt.savefig(OUTPUT_PLOT)
    print(f"📈 Saved plot to {OUTPUT_PLOT}")


if __name__ == '__main__':
    run_depletion_test()
