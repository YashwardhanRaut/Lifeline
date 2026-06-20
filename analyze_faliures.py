import pandas as pd
import os

OUTPUT_REPORT = "data/depleted_hubs_report.csv"

def analyze_simulation_failures(failed_tx_list, save_report=True):
    print("\n🔍 ANALYZING NETWORK FAILURES...")
    
    df = pd.DataFrame(failed_tx_list)
    if df.empty:
        print("   ✅ No failures found! (Perfect Network)")
        return pd.DataFrame(), pd.DataFrame()

    # --- 1. DETECT HUB DEPLETION ---
    # Logic: Group by 'failed_at' node and count
    depleted_hubs = df['failed_at'].value_counts().reset_index()
    depleted_hubs.columns = ['node_pub', 'failure_count']
    
    # Save to CSV for the Experiment Runner
    if save_report:
        if not os.path.exists('data'): os.makedirs('data')
        depleted_hubs.to_csv(OUTPUT_REPORT, index=False)
        print(f"   💾 Saved failure report to {OUTPUT_REPORT}")

    # --- 2. DETECT FREQUENT PAIR FAILURES ---
    df['pair'] = list(zip(df['src'], df['dst']))
    failed_pairs = df['pair'].value_counts().reset_index()
    failed_pairs.columns = ['pair_tuple', 'failure_count']
    
    # Print Top 5 for sanity check
    print("\n🚨 TOP 5 DEPLETED HUBS:")
    print(depleted_hubs.head(5))
    
    return depleted_hubs, failed_pairs










    # import pandas as pd
    # from collections import Counter

    # def analyze_simulation_failures(failed_tx_list):
    #     print("\n🔍 ANALYZING NETWORK FAILURES...")
        
    #     df = pd.DataFrame(failed_tx_list)
    #     if df.empty:
    #         print("   ✅ No failures found! (Perfect Network)")
    #         return [], []

    #     # --- 1. DETECT HUB DEPLETION ---
    #     # Logic: Which nodes are causing the most failures when they try to forward?
    #     # These nodes have run out of outbound liquidity.
    #     depleted_hubs = df['failed_at'].value_counts().reset_index()
    #     depleted_hubs.columns = ['node_pub', 'failure_count']
        
    #     print("\n🚨 TOP 10 DEPLETED HUBS (Candidates for Rich Hub Lifeline):")
    #     print(depleted_hubs.head(10))

    #     # --- 2. DETECT FREQUENT PAIR FAILURES ---
    #     # Logic: Which Src-Dst pairs fail constantly?
    #     # These are "Friends" who need a direct channel.
    #     df['pair'] = list(zip(df['src'], df['dst']))
    #     failed_pairs = df['pair'].value_counts().reset_index()
    #     failed_pairs.columns = ['pair_tuple', 'failure_count']
        
    #     print("\n🤝 TOP 10 FAILED PAIRS (Candidates for Direct Channel):")
    #     print(failed_pairs.head(10))
        
    #     return depleted_hubs, failed_pairs

    # # Helper to run everything together
    # if __name__ == "__main__":
    #     from ln_simulation_core import LightningStatefulSimulator
        
    #     # 1. Run Sim
    #     sim = LightningStatefulSimulator("data/lngraph_2021_11_25__16_00.json")
    #     sim.run_sequential_workload(num_tx=2000)
        
    #     # 2. Analyze
    #     analyze_simulation_failures(sim.failed_transactions)