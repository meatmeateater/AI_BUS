# Taipei Bus AI Route Planner (v3)

A Python-based AI agent that helps navigate the complex Taipei Bus network. It uses the **TDX Transport API** for real-time data and employs a custom **Greedy Hop & Recursive Bridging** algorithm to find efficient routes, even for difficult, multi-transfer destinations.

## 🚀 Key Features

- **Real-time & Static Data Hybrid**: Combines a static route graph (for connectivity) with real-time ETA data (for accurate decision making).
- **Greedy Hop Algorithm (v3)**:
    - **Priority 1: Direct Routes**. Always prefers a direct bus if available.
    - **Priority 2: Greedy Hop (1-Transfer)**. Finds the fastest bus to a major transfer hub, then instructs the user to "Ask Again" at the hub. This mimics human intuition ("Get on the bus first!").
    - **Priority 3: Recursive Bridging (>1 Transfer)**. Solves deep connectivity issues by finding a "Bridge Route" to connect distant zones, guiding the user to the first transfer point.
- **MCP Server Integration**: Designed to work as a tool for AI assistants (Claude, Cursor, etc.).
- **Benchmark Suite**: Includes scripts to verify route quality against random or specific destinations.

## 🛠️ Installation

1. Clone the repository.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Set up environment variables in `.env` (copy from `.env.example`):
   ```
   TDX_CLIENT_ID=your_client_id
   TDX_CLIENT_SECRET=your_client_secret
   ```

## 🏗️ Project Structure

- `src/`
    - `mcp_server.py`: Main entry point. Defines tools `plan_trip` and `get_bus_arrival_time`.
    - `graph_engine.py`: Core pathfinding logic (Greedy Hop implementation).
    - `tdx_client.py`: Handles TDX API authentication and data fetching.
    - `crawler_core.py`: Legacy crawler adapter.
- `data/static/bus_graph.json`: Pre-built graph of Taipei/New Taipei bus network.
- `scripts/`
    - `benchmark_random.py`: Test 50 random destinations.
    - `simulate_full_journey.py`: Simulate the full multi-leg journey (recursive requests).
    - `build_network_graph.py`: (Optional) Re-build static graph.

## 🧪 Running Benchmarks

To verify the algorithm's performance:

```bash
# Run random 50-stop test
python scripts/benchmark_random.py

# Run full journey simulation (chains multiple requests)
python scripts/simulate_full_journey.py
```

## 📝 Algorithm Logic

**Why Greedy Hop?**
Traditional BFS algorithms fail on large, real-time networks because predicting a second transfer 1 hour in the future is unreliable.
Our approach:
1. **Focus on Leg 1**: Find the best bus *right now*.
2. **Guide to Hub**: If no direct bus, get the user to a transfer hub or bridge route.
3. **Recursive Inquiry**: Once at the hub, re-evaluate with fresh data.

This results in higher success rates and more practical advice for commuters.

## ⚠️ Notes
- The system caches real-time data for 60 seconds to respect API rate limits.
- "Safe Transfer" warnings are issued if a connecting bus has low frequency.
