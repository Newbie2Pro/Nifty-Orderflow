# Chartink Footprint Chart Developer Documentation

## Overview

This document explains the data format requirements for displaying footprint charts in the Chartink application. It covers the backend data processing pipeline and the frontend chart rendering requirements.

## Architecture

The footprint chart system consists of:

1. **Backend**: Python data processor (`core/fyers/processor.py`) that handles live tick data and historical data processing
2. **Frontend**: JavaScript chart renderer (`static/js/chart.js`) that displays footprint charts using custom Lightweight Charts plugins

## Data Flow

```
Live Tick Data → Processor.py → WebSocket → Chart.js → Footprint Plugin → Rendered Chart
```

## Backend Data Format

### Core Data Structure

Each footprint candle/row contains the following structure:

```python
{
    # Basic OHLCV data
    'time': int,          # Unix timestamp in seconds
    'open': float,        # Opening price
    'high': float,        # Highest price
    'low': float,         # Lowest price
    'close': float,       # Closing price
    'volume': int,        # Total volume

    # Volume analysis
    'buy_vol': int,       # Aggressive buy volume
    'sell_vol': int,      # Aggressive sell volume
    'delta': int,         # buy_vol - sell_vol

    # Cumulative metrics
    'cum_delta': int,     # Cumulative delta for the trading session
    'cum_volume': int,    # Cumulative traded volume

    # Footprint data
    'footprint': [
        {
            'priceLevel': float,     # Price level
            'buyVolume': int,        # Buy volume at this level
            'sellVolume': int,       # Sell volume at this level
        }
        # ... more price levels
    ]
}
```

### Footprint Array Structure

The `footprint` array contains price buckets within the candle's high-low range:

```python
footprint = [
    {
        'priceLevel': 19550.25,  # Price level (rounded to 2 decimals)
        'buyVolume': 1500,       # Total buy volume at this price
        'sellVolume': 800,       # Total sell volume at this price
    },
    # ... sorted by priceLevel in descending order (high to low)
]
```

### Bucket Size Configuration

Footprint price levels are calculated using bucket size and multiplier:

```python
# Backend configuration
bucket_size = 0.05    # Base price increment
multiplier = 100      # Scaling factor
effective_bucket_size = bucket_size * multiplier  # 5.0

# Price bucket calculation
bucket_price = floor(price / effective_bucket_size) * effective_bucket_size
bucket_price = round(bucket_price, 2)
```

## Live Data Processing

### Tick Data Input

The processor accepts live tick messages with this format:

```python
{
    'symbol': str,              # Instrument symbol
    'ltp': float,               # Last traded price
    'exch_feed_time': int,      # Exchange feed timestamp
    'last_traded_qty': int,     # Trade quantity
    'vol_traded_today': int,    # Cumulative volume for the day
    'bid_price': float,         # Current bid price
    'ask_price': float,         # Current ask price
    'tot_buy_qty': int,         # Total buy quantity in orderbook
    'tot_sell_qty': int,        # Total sell quantity in orderbook
    'trade_id': str,            # Unique trade identifier
}
```

### Aggressor Volume Calculation

The processor determines buy/sell volume using these methods in order:

1. **Bid/Ask Spread Analysis**:
   - Trade at ask → aggressive buy
   - Trade at bid → aggressive sell
   - Trade inside spread → order book pressure analysis

2. **Order Book Pressure**: Based on tot_buy_qty vs tot_sell_qty ratios

3. **Price Change Direction**:
   - Price up → buying pressure
   - Price down → selling pressure

### Time Alignment

Candle timestamps are aligned to market open (09:15 IST):

```python
def calculate_aligned_time_bin(timestamp: int, interval_seconds: int) -> int:
    market_open_ts = get_market_open_timestamp(timestamp)
    seconds_since_open = timestamp - market_open_ts
    candle_period = seconds_since_open // interval_seconds
    return market_open_ts + (candle_period * interval_seconds)
```

## Frontend Data Requirements

### Chart.js Data Processing

The frontend expects data in this format:

```javascript
const candleData = {
    time: 1699123456,           // Unix timestamp
    open: 19545.50,
    high: 19555.75,
    low: 19542.25,
    close: 19548.00,
    volume: 125000,
    buy_vol: 68000,
    sell_vol: 57000,
    delta: 11000,
    cum_delta: 45000,
    cum_volume: 2500000,
    footprint: [
        {
            priceLevel: 19555.75,
            buyVolume: 2000,
            sellVolume: 1500
        }
        // ... more price levels
    ]
};
```

### Live Data Updates

WebSocket messages for live updates:

```javascript
{
    symbol: "NSE:NIFTY26JANFUT",
    chart_id: "chart-0",
    timeframe: "5m",
    timestamp: 1699123456789,
    data: {
        // Same structure as historical candle data
        time: 1699123456,
        open: 19548.00,
        high: 19550.25,
        low: 19547.50,
        close: 19549.75,
        volume: 5000,
        buy_vol: 2800,
        sell_vol: 2200,
        delta: 600,
        cum_delta: 45600,
        footprint: [...]
    }
}
```

## API Endpoints

### Historical Data

```
GET /api/historical?symbol={symbol}&timeframe={timeframe}&bucket_size={bucket_size}&multiplier={multiplier}
```

**Response**: Array of footprint candles in the format described above

### Live Data Subscription

WebSocket event for subscribing to live updates:

```javascript
socket.emit('subscribe_symbol', {
    symbol: "NSE:NIFTY26JANFUT",
    timeframe: "5m",
    bucket_size: 0.05,
    multiplier: 100,
    chart_id: "chart-0",
    hist_seed: lastHistoricalCandle  // Optional: last candle for continuity
});
```

### Clear Processor State

```
POST /api/clear_processor_state
Content-Type: application/json

{
    "symbol": "NSE:NIFTY26JANFUT",
    "timeframe": "5m",
    "bucket_size": 0.05,
    "multiplier": 100
}
```

## Configuration Parameters

### Bucket Size Settings

- **bucket_size**: Base price increment (default: 0.05)
- **multiplier**: Scaling factor (default: 100)
- **effective_bucket_size**: bucket_size * multiplier

Example configurations:
- Fine granularity: bucket_size=0.01, multiplier=100 → effective=1.0
- Coarse granularity: bucket_size=0.05, multiplier=100 → effective=5.0

### Supported Timeframes

```javascript
const TIMEFRAMES = {
    '1m': 60,      // 1 minute
    '5m': 300,     // 5 minutes
    '15m': 900,    // 15 minutes
    '1d': 86400    // 1 day
};
```

## Market Hours and Session Management

### Indian Market Hours

- **Market Open**: 09:15 IST
- **Market Close**: 15:30 IST
- **Cumulative Delta**: Resets at market open each trading day

### Session Detection

The system automatically detects new trading days and resets cumulative metrics:

```python
def is_same_trading_day(ts1: int, ts2: int) -> bool:
    market_open1 = get_market_open_timestamp(ts1)
    market_open2 = get_market_open_timestamp(ts2)
    return market_open1 == market_open2
```

## Error Handling

### Data Validation

Frontend validates incoming data:

```javascript
const validData = data.filter(item =>
    item && typeof item === 'object' &&
    !isNaN(item.time) &&
    !isNaN(item.open) && !isNaN(item.high) &&
    !isNaN(item.low) && !isNaN(item.close)
);
```

### Common Issues

1. **Missing Footprint Data**: Charts still render with basic OHLCV
2. **Invalid Timestamps**: Filtered out during validation
3. **Volume Mismatches**: Automatic reconciliation in processor
4. **Floating Point Precision**: Prices rounded to 2 decimal places

## Performance Considerations

### Backend Optimization

- Uses Polars for efficient historical data processing
- Implements proportional integer allocation to avoid floating-point drift
- Maintains in-memory state for live aggregation
- Limits footprint iterations to prevent memory issues

### Frontend Optimization

- Throttles legend updates for better performance
- Uses ResizeObserver for efficient chart resizing
- Implements proper cleanup for memory management
- Supports chart pooling for multi-chart layouts

## Debugging

### Backend Logging

```python
logger.info(f"Processed {symbol} tick: price={ltp}, volume={vol}, buy={buy}, sell={sell}")
```

### Frontend Debugging

```javascript
console.log(`Loading historical data for ${symbol}-${timeframe}:`, data);
console.log(`Subscribed to live updates for ${symbol} on ${chartId}`);
```

## Development Guidelines

### Adding New Features

1. **Backend**: Extend `CandleAggregator` class in `processor.py`
2. **Frontend**: Update footprint plugin in `static/js/plugins/footprint.js`
3. **API**: Add new endpoints in Flask application
4. **Testing**: Validate with both historical and live data

### Code Organization

- **Backend**: `core/fyers/processor.py` - All data processing logic
- **Frontend**: `static/js/chart.js` - Chart management and lifecycle
- **Plugins**: `static/js/plugins/footprint.js` - Footprint rendering logic
- **API**: Flask routes for data serving and WebSocket management

## Future Enhancements

1. **Additional Timeframes**: Support for 30m, 1h, 4h timeframes
2. **Custom Bucketing**: User-configurable bucket sizes -------Press (Ctrl + Alt + S)  implimented 
3. **Volume Profile**: Integration with volume profile analysis
4. **Real-time Alerts**: Configurable delta and volume alerts
5. **Historical Backtesting**: Playback of historical tick data

---

## Disclaimer

**IMPORTANT EDUCATIONAL DISCLAIMER**

This documentation is provided for development and educational purposes only. The Chartink footprint chart system is proprietary software developed by Kodebuds Research and Development.

**⚠️ CRITICAL WARNING - EDUCATIONAL PURPOSES ONLY:**
- **The calculation processes described in this documentation are from the developer's thought process to showcase how to build application interfaces**
- **ACTUAL ORDER FLOW CALCULATIONS ARE DIFFERENT FROM THIS IMPLEMENTATION**
- **CONSIDER THIS ONLY FOR EDUCATIONAL PURPOSES**
- **DO NOT TRADE ACCORDING TO THIS DATA**
- **AUTHORS ARE NOT RESPONSIBLE FOR ANY FINANCIAL LOSSES**

**Important Notes:**
- This documentation is intended for authorized developers working on the Chartink project
- The data formats and processing algorithms described here are specific to the Chartink trading application
- Market data processing and financial trading applications require careful testing and validation
- Always ensure compliance with applicable financial regulations and data usage policies
- The system is designed for Indian equity markets (NSE/BSE) with specific market hours and trading conventions
- The aggressor volume calculation methods shown are simplified implementations for demonstration purposes only

**Technical Support:**
For questions regarding implementation or data format specifications, please refer to the source code files mentioned above or contact the development team.

**Risk Warning:**
Trading and financial analysis tools carry inherent risks. Users should thoroughly understand the data processing limitations and validate results before making trading decisions based on this system. **NEVER USE THIS EDUCATIONAL IMPLEMENTATION FOR LIVE TRADING DECISIONS.**

---

This documentation provides a comprehensive overview of the data format requirements for Chartink's footprint charts. For implementation details, refer to the source code files mentioned above.

## Portfolio Project Notice

**This application is developed as a portfolio project to demonstrate development skills and capabilities for employment purposes.**

This project showcases my abilities in:
- Full-stack web development (Python backend, JavaScript frontend)
- Real-time data processing and WebSocket implementation
- Financial data visualization and chart rendering
- API development and system architecture
- Database integration and performance optimization

**Not for Trading:** While this application demonstrates technical concepts related to financial data processing, it is not intended for actual trading or investment decisions. The implementation is for educational and portfolio demonstration purposes only.