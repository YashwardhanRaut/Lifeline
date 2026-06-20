import pandas as pd
import matplotlib.pyplot as plt
import copy
import random
import numpy as np
import multiprocessing
from multiprocessing import Pool

# Import your modules
from ln_simulation_core import LightningStatefulSimulator
from analyze_faliures import analyze_simulation_failures
from smart_lifeline_agent import SmartLifelineAgent

# --- CONFIGURATION ---
GRAPH_FILE = "data/lngraph_2021_11_25__16_00.json"
METRICS_FILE = "data/rich_node_features_dynamic.csv"

# CONSTANTS
NUM_TRANSACTIONS = 5000
# Total Budget = 300 channels * 10,000,000 sats = 3,000,000,000 sats
TOTAL_BUDGET = 300 * 10_000_000 * 1000 

# The range of 'N' (Number of new channels) to test
CHANNEL_COUNTS = [10, 50, 100, 200, 300, 500, 750, 1000]

# ---------------------------------------------------------
# HELPER: Deterministic Chaos
# ---------------------------------------------------------
def get_chaos_graph(graph_file, seed=42):
    sim = LightningStatefulSimulator(graph_file)
    random.seed(seed) 
    scenarios = [(0.5, 0.5), (0.75, 0.25), (0.25, 0.75), (1.0, 0.0), (0.0, 1.0)]
    for u, v, data in sim.G.edges(data=True):
        cap = data['capacity']
        ratio_a, ratio_b = random.choice(scenarios)
        sim.G[u][v]['balance'] = int(cap * ratio_a)
        if sim.G.has_edge(v, u):
            sim.G[v][u]['balance'] = int(cap * ratio_b)
    return sim.G

# ---------------------------------------------------------
# HELPER: Revive Rebalancing
# ---------------------------------------------------------
def apply_revive(G):
    G_new = copy.deepcopy(G)
    for u, v, data in G_new.edges(data=True):
        cap = data['capacity']
        G_new[u][v]['balance'] = cap // 2
        if G_new.has_edge(v, u):
            G_new[v][u]['balance'] = cap // 2
    return G_new

# ---------------------------------------------------------
# HELPER: Workload
# ---------------------------------------------------------
def generate_workload(G, num_tx):
    nodes = list(G.nodes())
    workload = []
    random.seed(99) 
    for i in range(num_tx):
        src, dst = random.sample(nodes, 2)
        amt = random.randint(1_000, 250_000) * 1000 
        workload.append({'id': i, 'src': src, 'dst': dst, 'amount': amt})
    return workload

# ---------------------------------------------------------
# WORKER: Evaluation Function
# ---------------------------------------------------------
def run_simulation_step(G, workload):
    """Runs sim and returns success rate."""
    sim = LightningStatefulSimulator(GRAPH_FILE) # Dummy init
    sim.G = copy.deepcopy(G) # Inject state
    
    success = 0
    for tx in workload:
        if sim.execute_transaction(tx['src'], tx['dst'], tx['amount'], 999):
            success += 1
    return (success / len(workload)) * 100

# ---------------------------------------------------------
# WORKER: The "Variable N" Runner
# ---------------------------------------------------------
def process_sensitivity_point(n, total_budget, base_G, workload, failures_list):
    """
    Calculates the outcome for a specific number of channels 'n'.
    Capacity is scaled: capacity = total_budget / n
    """
    print(f"   ⚙️ Processing N={n} ...")
    
    # 1. Calculate Capacity per Channel (Integer division)
    cap_per_channel = int(total_budget / n)
    
    # 2. Get Recommendations (Top N)
    # We re-instantiate agent here to be safe, though it's stateless mostly
    # We analyze failures ONCE in main, pass the list here to save time
    depleted_df, _ = analyze_simulation_failures(failures_list, save_report=False)
    
    lifeline_agent = SmartLifelineAgent(METRICS_FILE)
    # Ask for N prescriptions
    # Note: We need to ensure we request enough. The agent usually processes whole DF.
    # We take the top N rows of the depleted DF to generate N links.
    recs = lifeline_agent.generate_prescriptions(depleted_df.head(n), num_lifelines=1)
    
    # If agent returned fewer than N (rare), just use what we have
    actual_n = len(recs)
    
    # 3. Create Augmented Graph (Lifeline Only)
    G_lifeline = copy.deepcopy(base_G)
    for rec in recs:
        u, v = rec['u'], rec['v']
        if not G_lifeline.has_edge(u, v):
            # Add edge with SCALED capacity
            G_lifeline.add_edge(u, v, capacity=cap_per_channel, balance=cap_per_channel//2, base_fee=1000, fee_rate=1)
            G_lifeline.add_edge(v, u, capacity=cap_per_channel, balance=cap_per_channel//2, base_fee=1000, fee_rate=1)

    # 4. Run Strategy 3: Lifeline
    score_lifeline = run_simulation_step(G_lifeline, workload)
    
    # 5. Create Augmented + Revive Graph
    G_combo = apply_revive(G_lifeline)
    
    # 6. Run Strategy 4: Lifeline + Revive
    score_combo = run_simulation_step(G_combo, workload)
    
    print(f"      -> N={n} | Cap={cap_per_channel//1000:,}k | Lifeline: {score_lifeline:.2f}% | Combo: {score_combo:.2f}%")
    return (n, score_lifeline, score_combo)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

# ---------------------------------------------------------
# MAIN (CORRECTED)
# ---------------------------------------------------------
def run_sensitivity_analysis():
    print(f"🎓 THESIS: SENSITIVITY ANALYSIS (Budget Constraint)")
    # Note: 300 * 10M sats = 3 billion sats = 30 BTC, not 30,000 BTC. 
    # Just a print formatting fix, math is fine.
    print(f"   Budget: {TOTAL_BUDGET/100_000_000:.2f} BTC Total") 
    print(f"   Varying N from {min(CHANNEL_COUNTS)} to {max(CHANNEL_COUNTS)}")
    
    # 1. PRE-CALCULATE BASELINE (Constant Lines)
    print("\n🔹 Step 1: Establishing Baselines...")
    base_G = get_chaos_graph(GRAPH_FILE)
    workload = generate_workload(base_G, NUM_TRANSACTIONS)
    
    # --- FIX START ---
    # Run Baseline (No changes)
    sim_base = LightningStatefulSimulator(GRAPH_FILE)
    sim_base.G = copy.deepcopy(base_G)
    
    base_success_count = 0 # Initialize counter
    for tx in workload:
        # We assume execute_transaction returns True for success
        if sim_base.execute_transaction(tx['src'], tx['dst'], tx['amount'], tx['id']):
            base_success_count += 1
            
    score_base = (base_success_count / len(workload)) * 100
    failures_base = sim_base.failed_transactions # This attribute exists
    # --- FIX END ---
    
    # Run Revive Baseline (Base + Revive)
    G_revive = apply_revive(base_G)
    score_revive = run_simulation_step(G_revive, workload)
    
    print(f"   -> Baseline (Chaos): {score_base:.2f}%")
    print(f"   -> Baseline + Revive: {score_revive:.2f}%")

    # 2. RUN VARIABLE N EXPERIMENTS
    print("\n🔹 Step 2: Running Scaling Experiments...")
    
    tasks = []
    for n in CHANNEL_COUNTS:
        tasks.append((n, TOTAL_BUDGET, base_G, workload, failures_base))
    
    with Pool(processes=4) as pool:
        results = pool.starmap(process_sensitivity_point, tasks)
        
    results.sort(key=lambda x: x[0])
    
    x_vals = [r[0] for r in results]
    y_lifeline = [r[1] for r in results]
    y_combo = [r[2] for r in results]
    
    y_base = [score_base] * len(x_vals)
    y_revive = [score_revive] * len(x_vals)

    # 3. PLOTTING
    print("\n" + "="*60)
    print("📊 DATA TABLE")
    print("="*60)
    print(f"{'N':<5} | {'Cap (Sats)':<12} | {'Base':<8} | {'Revive':<8} | {'Lifeline':<8} | {'Combo':<8}")
    for i, n in enumerate(x_vals):
        cap = TOTAL_BUDGET // n
        # Format sats nicely
        cap_display = f"{cap // 1000:,}" 
        print(f"{n:<5} | {cap_display:<12} | {y_base[i]:.2f}%   | {y_revive[i]:.2f}%   | {y_lifeline[i]:.2f}%   | {y_combo[i]:.2f}%")

    plt.figure(figsize=(10, 6))
    
    plt.plot(x_vals, y_base, label='Base (Chaos)', color='gray', linestyle=':', linewidth=2)
    plt.plot(x_vals, y_revive, label='Base + Revive', color='orange', linestyle='--', linewidth=2)
    plt.plot(x_vals, y_lifeline, label='Lifeline (Var N)', color='blue', marker='o', linewidth=2)
    plt.plot(x_vals, y_combo, label='Lifeline + Revive', color='green', marker='s', linewidth=2)
    
    plt.title(f"Sensitivity Analysis: Success Rate vs Channel Count\n(Constant Liquidity Budget: {TOTAL_BUDGET/100_000_000:.2f} BTC)")
    plt.xlabel("Number of New Channels (N)")
    plt.ylabel("Success Rate (%)")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    # Annotate the peak
    best_idx = np.argmax(y_combo)
    best_n = x_vals[best_idx]
    best_val = y_combo[best_idx]
    plt.annotate(f'Peak: {best_val:.2f}% (N={best_n})', 
                 xy=(best_n, best_val), 
                 xytext=(best_n, best_val+1),
                 arrowprops=dict(facecolor='black', shrink=0.05),
                 ha='center')

    plt.savefig("thesis_sensitivity_analysis.png")
    print("\n✅ Sensitivity Chart saved as 'thesis_sensitivity_analysis.png'")



# def run_sensitivity_analysis():
#     print(f"🎓 THESIS: SENSITIVITY ANALYSIS (Budget Constraint)")
#     print(f"   Budget: {TOTAL_BUDGET/100000000:.2f} BTC Total")
#     print(f"   Varying N from {min(CHANNEL_COUNTS)} to {max(CHANNEL_COUNTS)}")
    
#     # 1. PRE-CALCULATE BASELINE (Constant Lines)
#     print("\n🔹 Step 1: Establishing Baselines...")
#     base_G = get_chaos_graph(GRAPH_FILE)
#     workload = generate_workload(base_G, NUM_TRANSACTIONS)
    
#     # Run Baseline (No changes)
#     sim_base = LightningStatefulSimulator(GRAPH_FILE)
#     sim_base.G = copy.deepcopy(base_G)
#     for tx in workload:
#         sim_base.execute_transaction(tx['src'], tx['dst'], tx['amount'], tx['id'])
    
#     score_base = (len(sim_base.successful_transactions) / len(workload)) * 100
#     failures_base = sim_base.failed_transactions # NEED THIS for the agent
    
#     # Run Revive Baseline (Base + Revive)
#     G_revive = apply_revive(base_G)
#     score_revive = run_simulation_step(G_revive, workload)
    
#     print(f"   -> Baseline (Chaos): {score_base:.2f}%")
#     print(f"   -> Baseline + Revive: {score_revive:.2f}%")

#     # 2. RUN VARIABLE N EXPERIMENTS
#     print("\n🔹 Step 2: Running Scaling Experiments...")
    
#     # Prepare arguments for parallel processing
#     # Note: passing large objects (G, failures) to mp can be slow due to pickling.
#     # But for 8 tasks, it's acceptable.
#     tasks = []
#     for n in CHANNEL_COUNTS:
#         tasks.append((n, TOTAL_BUDGET, base_G, workload, failures_base))
    
#     with Pool(processes=4) as pool:
#         # We use a wrapper to unpack args because starmap is cleaner
#         results = pool.starmap(process_sensitivity_point, tasks)
        
#     # Sort results by N just in case
#     results.sort(key=lambda x: x[0])
    
#     # Extract data for plotting
#     x_vals = [r[0] for r in results]
#     y_lifeline = [r[1] for r in results]
#     y_combo = [r[2] for r in results]
    
#     # Create constant arrays for the baselines
#     y_base = [score_base] * len(x_vals)
#     y_revive = [score_revive] * len(x_vals)

#     # 3. PLOTTING
#     print("\n" + "="*60)
#     print("📊 DATA TABLE")
#     print("="*60)
#     print(f"{'N':<5} | {'Cap (Sats)':<12} | {'Base':<8} | {'Revive':<8} | {'Lifeline':<8} | {'Combo':<8}")
#     for i, n in enumerate(x_vals):
#         cap = TOTAL_BUDGET // n
#         print(f"{n:<5} | {cap:<12} | {y_base[i]:.2f}%   | {y_revive[i]:.2f}%   | {y_lifeline[i]:.2f}%   | {y_combo[i]:.2f}%")

#     plt.figure(figsize=(10, 6))
    
#     # Plot Constant Baselines
#     plt.plot(x_vals, y_base, label='Base (Chaos)', color='gray', linestyle=':', linewidth=2)
#     plt.plot(x_vals, y_revive, label='Base + Revive', color='orange', linestyle='--', linewidth=2)
    
#     # Plot Variable Lines
#     plt.plot(x_vals, y_lifeline, label='Lifeline (Var N)', color='blue', marker='o', linewidth=2)
#     plt.plot(x_vals, y_combo, label='Lifeline + Revive', color='green', marker='s', linewidth=2)
    
#     plt.title(f"Sensitivity Analysis: Success Rate vs Channel Count\n(Constant Liquidity Budget: {TOTAL_BUDGET/100_000_000} BTC)")
#     plt.xlabel("Number of New Channels (N)")
#     plt.ylabel("Success Rate (%)")
#     plt.legend()
#     plt.grid(True, alpha=0.3)
    
#     # Annotate the peak
#     best_idx = np.argmax(y_combo)
#     best_n = x_vals[best_idx]
#     best_val = y_combo[best_idx]
#     plt.annotate(f'Peak: {best_val:.2f}% (N={best_n})', 
#                  xy=(best_n, best_val), 
#                  xytext=(best_n, best_val+1),
#                  arrowprops=dict(facecolor='black', shrink=0.05),
#                  ha='center')

#     plt.savefig("thesis_sensitivity_analysis.png")
#     print("\n✅ Sensitivity Chart saved as 'thesis_sensitivity_analysis.png'")

if __name__ == "__main__":
    run_sensitivity_analysis()