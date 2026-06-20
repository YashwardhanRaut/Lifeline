import json
import networkx as nx
import random

def load_and_initialize_graph(json_path):
    """
    Loads LN graph from JSON and initializes all channels with 
    perfect 50/50 balance split.
    CONVERTS ALL CAPACITIES TO MILLI-SATOSHIS (MSAT) TO MATCH TRANSACTIONS.
    """
    print(f"⚡ Initializing Graph from {json_path} (Converting Sats -> Msats)...")
    
    with open(json_path, 'r', encoding='utf-8', errors='replace') as f:
        data = json.load(f)
        
    G = nx.DiGraph() # Directed graph because balances are directional
    
    for edge in data['edges']:
        u = edge['node1_pub']
        v = edge['node2_pub']
        
        # --- FIX: CONVERT TO MSATS ---
        # JSON capacity is usually in Sats. We multiply by 1000.
        capacity_sats = int(edge['capacity'])
        capacity_msat = capacity_sats * 1000 
        
        channel_id = edge.get('channel_id', '0')
        
        # 50/50 Split Calculation
        half_cap = capacity_msat // 2
        
        # Robust Policy Extraction
        p1 = edge.get('node1_policy') or {}
        p2 = edge.get('node2_policy') or {}
        
        # Add Edge U -> V
        G.add_edge(u, v, 
                   capacity=capacity_msat, 
                   balance=half_cap,     
                   channel_id=channel_id,
                   base_fee=int(p1.get('fee_base_msat', 1000)),
                   fee_rate=int(p1.get('fee_rate_milli_msat', 1)))
                   
        # Add Edge V -> U
        G.add_edge(v, u, 
                   capacity=capacity_msat, 
                   balance=capacity_msat - half_cap, 
                   channel_id=channel_id,
                   base_fee=int(p2.get('fee_base_msat', 1000)),
                   fee_rate=int(p2.get('fee_rate_milli_msat', 1)))

    print(f"   -> Graph Ready: {G.number_of_nodes()} Nodes, {G.number_of_edges()} Directed Channels (MSAT)")
    return G

def print_graph_stats(G):
    total_cap = 0
    total_balance = 0
    for u, v, data in G.edges(data=True):
        total_cap += data['capacity']
        total_balance += data['balance']
    
    # Divide by 2 because capacity is duplicated in DiGraph, and divide by 100M for BTC
    btc_cap = (total_cap / 2) / 100_000_000_000 
    print(f"   -> Total Network Capacity: {btc_cap:.2f} BTC") 

if __name__ == "__main__":
    G = load_and_initialize_graph("data/lngraph_2021_11_25__16_00.json")
    print_graph_stats(G)










# import json
# import networkx as nx
# import random

# def load_and_initialize_graph(json_path):
#     """
#     Loads LN graph from JSON and initializes all channels with 
#     perfect 50/50 balance split. Handles missing/null policies safely.
#     """
#     print(f"⚡ Initializing Graph from {json_path} with 50/50 Balances...")
    
#     with open(json_path, 'r') as f:
#         data = json.load(f)
        
#     G = nx.DiGraph() # Directed graph because balances are directional
    
#     for edge in data['edges']:
#         u = edge['node1_pub']
#         v = edge['node2_pub']
#         capacity = int(edge['capacity'])
#         channel_id = edge.get('channel_id', '0')
        
#         # 50/50 Split Calculation
#         half_cap = capacity // 2
        
#         # --- ROBUST POLICY EXTRACTION ---
#         # "or {}" forces None values to become empty dicts
#         p1 = edge.get('node1_policy') or {}
#         p2 = edge.get('node2_policy') or {}
        
#         # Add Edge U -> V (U's outbound liquidity)
#         G.add_edge(u, v, 
#                    capacity=capacity, 
#                    balance=half_cap,     # U has 50%
#                    channel_id=channel_id,
#                    base_fee=int(p1.get('fee_base_msat', 1000)),
#                    fee_rate=int(p1.get('fee_rate_milli_msat', 1)))
                   
#         # Add Edge V -> U (V's outbound liquidity)
#         G.add_edge(v, u, 
#                    capacity=capacity, 
#                    balance=capacity - half_cap, # V has the other 50%
#                    channel_id=channel_id,
#                    base_fee=int(p2.get('fee_base_msat', 1000)),
#                    fee_rate=int(p2.get('fee_rate_milli_msat', 1)))

#     print(f"   -> Graph Ready: {G.number_of_nodes()} Nodes, {G.number_of_edges()} Directed Channels")
#     return G

# # Helper to check balance state
# def print_graph_stats(G):
#     total_cap = 0
#     total_balance = 0
#     for u, v, data in G.edges(data=True):
#         total_cap += data['capacity']
#         total_balance += data['balance']
    
#     print(f"   -> Total Network Capacity: {total_cap/2:,.0f} sats") 
#     print(f"   -> Total Active Liquidity: {total_balance:,.0f} sats")

# if __name__ == "__main__":
#     # Test run
#     G = load_and_initialize_graph("data/lngraph_2021_11_25__16_00.json")
#     print_graph_stats(G)










# import json
# import networkx as nx
# import random

# def load_and_initialize_graph(json_path):
#     """
#     Loads LN graph from JSON and initializes all channels with 
#     perfect 50/50 balance split.
#     """
#     print(f"⚡ Initializing Graph from {json_path} with 50/50 Balances...")
    
#     with open(json_path, 'r') as f:
#         data = json.load(f)
        
#     G = nx.DiGraph() # Directed graph because balances are directional
    
#     for edge in data['edges']:
#         u = edge['node1_pub']
#         v = edge['node2_pub']
#         capacity = int(edge['capacity'])
#         channel_id = edge.get('channel_id', '0')
        
#         # 50/50 Split Calculation
#         half_cap = capacity // 2
        
#         # --- ROBUST POLICY EXTRACTION (The Fix) ---
#         # If 'node1_policy' is None, 'or {}' converts it to empty dict
#         p1 = edge.get('node1_policy') or {}
#         p2 = edge.get('node2_policy') or {}

#         # Add Edge U -> V (U's outbound liquidity)
#         G.add_edge(u, v, 
#                    capacity=capacity, 
#                    balance=half_cap,     # U has 50%
#                    channel_id=channel_id,
#                    base_fee=int(edge.get('node1_policy', {}).get('fee_base_msat', 1000)),
#                    fee_rate=int(edge.get('node1_policy', {}).get('fee_rate_milli_msat', 1)))
                   
#         # Add Edge V -> U (V's outbound liquidity)
#         G.add_edge(v, u, 
#                    capacity=capacity, 
#                    balance=capacity - half_cap, # V has the other 50%
#                    channel_id=channel_id,
#                    base_fee=int(edge.get('node2_policy', {}).get('fee_base_msat', 1000)),
#                    fee_rate=int(edge.get('node2_policy', {}).get('fee_rate_milli_msat', 1)))

#     print(f"   -> Graph Ready: {G.number_of_nodes()} Nodes, {G.number_of_edges()} Directed Channels")
#     return G

# # Helper to check balance state (Call this to verify your initialization)
# def print_graph_stats(G):
#     total_cap = 0
#     total_balance = 0
#     for u, v, data in G.edges(data=True):
#         total_cap += data['capacity']
#         total_balance += data['balance']
    
#     # Total balance in DiGraph is counted twice (once per direction), 
#     # but actual locked Bitcoin is capacity.
#     # So sum(balance) should equal sum(capacity) in a DiGraph representation if summed correctly.
#     print(f"   -> Total Network Capacity: {total_cap/2:,.0f} sats") 
#     print(f"   -> Total Active Liquidity: {total_balance:,.0f} sats")

# if __name__ == "__main__":
#     # Test run
#     G = load_and_initialize_graph("data/lngraph_2021_11_25__16_00.json")
#     print_graph_stats(G)