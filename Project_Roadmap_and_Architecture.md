# Fyers 5-Second Data & Imbalance Monitor - Project Roadmap & Architecture

## 1. Unified App Strategy: The "Transplant" Approach

We are merging the best of three worlds into a high-performance trading dashboard.

### Core Components
*   **Framework (The Body):** **[chartink](https://github.com/kodebuds/chartink)**. Provides the Flask structure, Polars-based processing, and a professional Lightweight Charts frontend.
*   **Data Engine (The Heart):** **[fyers-websockets]**. We will replace `chartink`'s standard Fyers SDK feed with the custom **Protobuf + Versova** engine. This is essential for 50-level depth and sub-millisecond precision.
*   **Analytics (The Brain):** **fyers_depth_imbalance.py**. The specific logic for Imbalance (10/20/50 levels), Sentiment, and Market Regime.
*   **Persistence (The Memory):** **DuckDB**. A new layer to save every 5s snapshot for historical replay and long-term analysis.

### Architecture Structure
```text
/Fyers_Unified_App/
├── app/
│   ├── routes.py          # Flask routes (Dashboard, Imbalance, Search)
│   └── socket_events.py   # Manages Protobuf WebSocket thread & Socket.IO broadcasts
├── core/
│   ├── engine/
│   │   ├── protobuf/      # Protobuf definitions (msg_pb2.py)
│   │   ├── versova.py     # Custom WebSocket logic from fyers-websockets
│   │   └── book_mgr.py    # 50-level Order Book reconstruction logic
│   ├── processor/
│   │   ├── imbalance.py   # Imbalance & Sentiment logic (from fyers_depth_imbalance.py)
│   │   └── flow.py        # Order Flow & Cumulative Delta (Polars based)
│   └── database.py        # DuckDB integration for 5s/Snapshot persistence
├── templates/             # Unified Dashboard (Merging chartink + Imbalance Monitor)
└── static/                # JS Widgets for DOM, Heatmap, and Order Flow
```

## 2. Technical Requirements

*   **Database:** DuckDB (In-process OLAP).
*   **Processing:** Polars (High-speed DataFrames).
*   **Protocol:** Fyers Versova (Protobuf over Binary WebSockets).
*   **Compliance:** Maintain the "Midnight Token Cleanup" from `fyers-websockets`.

## 3. Roadmap

### Phase 1: Engine Transplant (Weeks 1-2)
*   **Goal:** Get `chartink` running with the `fyers-websockets` Protobuf engine.
*   **Action:**
    1.  Migrate `msg_pb2.py` and the `asyncio` websocket loop into `app/socket_events.py`.
    2.  Ensure authentication uses the `database.py` token management from `fyers-websockets`.
    3.  Add an **AutoLogin** button to the main landing page using the headless login logic (TOTP/PIN) from `ActiveDataDownloader.py` for seamless session initialization.
    4.  Successfully stream raw 50-level depth into the Flask console.

### Phase 2: Analytics & Persistence (Weeks 3-4)
*   **Goal:** Calculate metrics and save to DuckDB.
*   **Action:**
    1.  Implement the `calculate_order_book_imbalance` and `interpret_imbalance` functions in the backend.
    2.  Setup DuckDB tables for `tick_data` and `book_snapshots`.
    3.  Create a background worker to flush `Polars` buffers to DuckDB every 5 seconds.

### Phase 3: Unified Dashboard (Weeks 5-6)
*   **Goal:** A single UI for Charts, DOM, and Imbalance.
*   **Action:**
    1.  Create a "Unified Dashboard" template that hosts the Lightweight Chart and the Imbalance Monitor widgets.
    2.  Implement the "Large Order Watch" tile using the live trade stream.
    3.  Add the symbol search widget using local Master CSV files for instant response.

### Phase 4: Polish & Advanced Metrics (Week 7+)
*   **Goal:** Replicate professional "Order Flow" metrics.
*   **Action:**
    1.  Implement **Cumulative Volume Delta (CVD)**.
    2.  Build the "Market Regime" badges (Bullish/Bearish/Neutral).
    3.  Add sound alerts for large orders (as seen in `flowsurface`).
