import copy
import networkx as nx
import heapq
import random
import json
from graph_initializer import load_and_initialize_graph

class LightningStatefulSimulator:
    def __init__(self, json_file):
        # Load graph (Capacities are in MSATs now)
        self.G = load_and_initialize_graph(json_file)
        self.failed_transactions = [] 
        self.node_failures = {} 
        
    def get_route(self, src, dst, amount_msat):
        """
        Dijkstra Routing: Finds path with lowest FEE that has sufficient capacity.
        """
        pq = [(0, src, [])]
        visited = set()
        min_costs = {src: 0}
        
        while pq:
            cost, u, path = heapq.heappop(pq)
            
            if u == dst:
                return path
            
            if u in visited: continue
            visited.add(u)
            
            # G[u] gives us neighbors of u
            for v, data in self.G[u].items():
                # 1. Capacity Check
                if data['balance'] < amount_msat:
                    continue
                
                # 2. Fee Calculation
                base_fee = data.get('base_fee', 1000)
                fee_rate = data.get('fee_rate', 1)
                fee = base_fee + (amount_msat * fee_rate / 1_000_000)
                
                new_cost = cost + fee
                
                if new_cost < min_costs.get(v, float('inf')):
                    min_costs[v] = new_cost
                    heapq.heappush(pq, (new_cost, v, path + [(u, v)]))
                    
        return None 

    def diagnose_bottleneck(self, src, dst, amount_msat):
        """
        FORENSIC ANALYSIS:
        If standard routing fails, this finds the shortest topological path
        and identifies the FIRST node that lacks liquidity.
        """
        try:
            # Find shortest path purely by hops (ignoring fees/balance)
            path = nx.shortest_path(self.G, src, dst)
            
            # Walk the path to find the bottleneck
            for i in range(len(path)-1):
                u, v = path[i], path[i+1]
                # Check if this link is the one that failed
                if self.G[u][v]['balance'] < amount_msat:
                    return u # THIS NODE is the culprit (Depleted Hub)
                    
            return None # Should not happen if path exists but route failed
            
        except nx.NetworkXNoPath:
            return None # Graph is disconnected

    def execute_transaction(self, src, dst, amount_msat, tx_id):
        path_edges = self.get_route(src, dst, amount_msat)
        
        if not path_edges:
            # --- SMART LOGIC: Find out WHO failed ---
            culprit = self.diagnose_bottleneck(src, dst, amount_msat)
            reason = "LIQUIDITY_FAIL" if culprit else "NO_PATH"
            
            self._log_failure(src, dst, amount_msat, reason, failed_at_node=culprit)
            return False
        
        # Double check liquidity just in case
        for u, v in path_edges:
            if self.G[u][v]['balance'] < amount_msat:
                # This should technically be caught by get_route, but safety first
                self._log_failure(src, dst, amount_msat, "RACE_CONDITION", failed_at_node=u)
                return False
                
        # ATOMIC UPDATE
        for u, v in path_edges:
            self.G[u][v]['balance'] -= amount_msat 
            self.G[v][u]['balance'] += amount_msat 
            
        return True

    def _log_failure(self, src, dst, amt, reason, failed_at_node):
        self.failed_transactions.append({
            'src': src,
            'dst': dst,
            'amount': amt,
            'reason': reason,
            'failed_at': failed_at_node
        })
        
        # Count failures per node
        if failed_at_node:
            self.node_failures[failed_at_node] = self.node_failures.get(failed_at_node, 0) + 1

    def run_sequential_workload(self, num_tx=1000):
        print(f"⚡ Running {num_tx} Sequential Transactions...")
        nodes = list(self.G.nodes())
        success_count = 0
        
        for i in range(num_tx):
            # Pick random pair
            s, d = random.sample(nodes, 2)
            
            # Generate typical payment size (1k to 100k sats = 1M to 100M msats)
            # Reduced slightly to allow some early successes
            amt = random.randint(1_000, 100_000) * 1000 
            
            if self.execute_transaction(s, d, amt, i):
                success_count += 1
            
            if i % 100 == 0:
                print(f"   Progress: {i}/{num_tx} | Success Rate: {(success_count/(i+1))*100:.1f}%")
                
        return success_count, self.failed_transactions

def apply_revive(G):
    """Perform a global 50/50 rebalancing across every directed edge."""
    G_new = copy.deepcopy(G)
    for u, v, data in G_new.edges(data=True):
        cap = data.get('capacity', 0)
        balance = cap // 2
        G_new[u][v]['balance'] = balance
        if G_new.has_edge(v, u):
            G_new[v][u]['balance'] = balance
    return G_new

if __name__ == "__main__":
    sim = LightningStatefulSimulator("data/lngraph_2021_11_25__16_00.json")
    sim.run_sequential_workload(num_tx=500)