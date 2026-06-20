import pandas as pd
import random
import os

class SmartLifelineAgent:
    def __init__(self, features_csv):
        self.features_csv = features_csv
        self.rich_nodes = self._load_rich_nodes()
        
    def _load_rich_nodes(self):
        """
        Identifies the 'Wealthiest' nodes in the network using the CSV features.
        We look for nodes that are mathematically central (Eigenvector) and high-capacity.
        """
        print(f"🧠 [Smart Agent] Loading rich nodes from {self.features_csv}...")
        
        if not os.path.exists(self.features_csv):
            print(f"❌ Error: Could not find {self.features_csv}")
            return []

        try:
            df = pd.read_csv(self.features_csv)
        except Exception as e:
            print(f"❌ Error reading CSV: {e}")
            return []

        # DATA VALIDATION
        # We need 'eigenvector' to determine who is a "Hub"
        # We need 'node_pub' to know their ID
        required_cols = ['node_pub', 'eigenvector']
        if not all(col in df.columns for col in required_cols):
            print(f"❌ Error: CSV missing required columns: {required_cols}")
            print(f"   Found columns: {df.columns.tolist()}")
            return []

        # LOGIC:
        # Sort by Eigenvector Centrality (Descending). 
        # These are the nodes connected to other important nodes.
        rich_df = df.sort_values(by='eigenvector', ascending=False).head(100)
        
        candidates = rich_df['node_pub'].tolist()
        
        print(f"   -> Found {len(candidates)} Elite Liquidity Providers (Top 100 by Centrality).")
        return candidates

    def generate_prescriptions(self, depleted_hubs_df, num_lifelines=2):
        """
        Takes a DataFrame of depleted (failing) hubs and prescribes new channels.
        
        Strategy:
        For every 'sick' node (depleted hub), connect it to 'num_lifelines' 
        distinct Rich Nodes to inject liquidity.
        """
        if not self.rich_nodes:
            print("⚠️ [Smart Agent] No rich nodes available to prescribe! Check your CSV.")
            return []

        print(f"💊 [Smart Agent] Generating cures for {len(depleted_hubs_df)} depleted hubs...")
        
        new_channels = [] 
        
        # LIFELINE CAPACITY: 5,000,000 sats (5 Billion msats)
        # We use a large capacity to ensure the bottleneck is cleared.
        LIFELINE_CAPACITY_MSAT = 5_000_000 * 1000 
        
        for index, row in depleted_hubs_df.iterrows():
            sick_node = row['node_pub']
            
            # Filter: Don't let a node connect to itself
            valid_donors = [n for n in self.rich_nodes if n != sick_node]
            
            # Select donors randomly from the elite list to spread the load
            if len(valid_donors) < num_lifelines:
                donors = valid_donors
            else:
                donors = random.sample(valid_donors, num_lifelines)
            
            for donor in donors:
                new_channels.append({
                    'u': sick_node,
                    'v': donor,
                    'capacity': LIFELINE_CAPACITY_MSAT
                })
                    
        print(f"   -> Prescribed {len(new_channels)} new Lifeline Channels.")
        return new_channels












# import json
# import random
# import pandas as pd

# class SmartLifelineAgent:
#     def __init__(self, metrics_file):
#         self.metrics_file = metrics_file
#         self.rich_nodes = self._load_rich_nodes()
        
#     def _load_rich_nodes(self):
#         """
#         Identifies the 'Wealthiest' nodes in the network to act as Liquidity Providers.
#         We use Eigenvector Centrality (connected to other important people) 
#         and Betweenness (critical bridges).
#         """
#         print("🧠 [Smart Agent] Identifying Liquidity Providers...")
#         with open(self.metrics_file, 'r') as f:
#             data = json.load(f)
            
#         # Extract metrics
#         candidates = []
#         for node, m in data.get('all_nodes_metrics', {}).items():
#             # Score = Combination of Betweenness and Capacity (if available)
#             # For now, we lean heavily on Eigenvector as a proxy for 'Connectedness'
#             score = m.get('eigenvector', 0) + m.get('betweenness', 0)
#             candidates.append((node, score))
            
#         # Sort by score descending
#         candidates.sort(key=lambda x: x[1], reverse=True)
        
#         # Keep top 50 "Banks"
#         top_50 = [c[0] for c in candidates[:50]]
#         print(f"   -> Found {len(top_50)} Elite Liquidity Providers.")
#         return top_50

#     def generate_prescriptions(self, depleted_hubs_df, num_lifelines=2):
#         """
#         Takes a DataFrame of depleted hubs and prescribes new channels.
        
#         Strategy:
#         For every sick hub, connect it to 'num_lifelines' distinct Rich Nodes.
#         """
#         print(f"💊 [Smart Agent] Generating cures for {len(depleted_hubs_df)} depleted hubs...")
        
#         new_channels = [] # List of (source, dest, capacity)
        
#         # LIFELINE CAPACITY: 5,000,000 sats (5B msats)
#         # This is a 'fat' channel designed to solve the liquidity crunch.
#         LIFELINE_CAPACITY_MSAT = 5_000_000 * 1000 
        
#         for index, row in depleted_hubs_df.iterrows():
#             sick_node = row['node_pub']
            
#             # Pick 'num_lifelines' rich nodes to connect to
#             # We shuffle the rich list so we don't just connect everyone to Node #1
#             donors = random.sample(self.rich_nodes, min(len(self.rich_nodes), num_lifelines))
            
#             for donor in donors:
#                 if sick_node != donor:
#                     new_channels.append({
#                         'u': sick_node,
#                         'v': donor,
#                         'capacity': LIFELINE_CAPACITY_MSAT
#                     })
                    
#         print(f"   -> Prescribed {len(new_channels)} new Lifeline Channels.")
#         return new_channels