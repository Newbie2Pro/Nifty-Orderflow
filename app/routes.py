
from flask import Blueprint, render_template, request, jsonify, redirect
import os
import sys

# Add paths for imports
for path in ['ticker', 'core/fyers']:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', path))

from ticker.fyers_sm import SymbolMaster
from core.fyers.auth import FyersAuth
from core.fyers.fyers_data import FyersDataFeed

# Initialize blueprint and services
main = Blueprint('main', __name__)
symbol_master = SymbolMaster()
auth = FyersAuth()
fyers_data_feed = FyersDataFeed()

# Route handlers
@main.route('/')
def index():
    return render_template('base.html')

@main.route('/chart')
def chart():
    default_symbol = symbol_master.get_active_nifty_future()
    return render_template('chart.html', default_symbol=default_symbol)

# Authentication routes
@main.route('/login')
def login():
    return redirect(auth.get_auth_url())

@main.route('/auto-login')
def auto_login():
    if auth.auto_login():
        return redirect('/chart')
    else:
        return "Auto Login failed. Check logs for details.", 400

@main.route('/fyers/callback')
def fyers_callback():
    auth_code = request.args.get('auth_code') or request.args.get('code')
    if not auth_code:
        return "Authentication failed: No authorization code received", 400
    
    # Create a fresh auth instance to handle the new token
    callback_auth = FyersAuth()
    if callback_auth.generate_access_token(auth_code):
        return redirect('/chart')
    else:
        return "Authentication failed: Could not generate access token", 400

@main.route('/logout')
def logout():
    auth.logout()
    return redirect('/')

# API routes
@main.route('/api/symbols', methods=['GET'])
def api_symbols():
    q = request.args.get('q', '')
    category = request.args.get('category', 'All')
    limit = int(request.args.get('limit', 50))
    return jsonify(symbol_master.unified_symbol_search(query=q, category=category, limit=limit))

# ---------------- Watchlist APIs ----------------
@main.route('/api/watchlist', methods=['GET'])
def api_watchlist_list():
    q = request.args.get('q', '')
    limit = int(request.args.get('limit', 200))
    data = symbol_master.get_watchlist(query=q, limit=limit)
    # Ensure watchlisted true in payload
    for item in data:
        item['watchlisted'] = True
    return jsonify(data)

@main.route('/api/watchlist', methods=['POST'])
def api_watchlist_add():
    body = request.get_json(silent=True) or {}
    symbol = body.get('symbol')
    description = body.get('description', '')
    exchange = body.get('exchange', 'NSE')
    original_type = body.get('type', body.get('original_type', ''))
    if not symbol:
        return jsonify({"success": False, "error": "symbol required"}), 400
    ok = symbol_master.add_to_watchlist(symbol, description, exchange, original_type)
    return jsonify({"success": ok})

@main.route('/api/watchlist/<symbol>', methods=['DELETE'])
def api_watchlist_remove(symbol):
    if not symbol:
        return jsonify({"success": False, "error": "symbol required"}), 400
    ok = symbol_master.remove_from_watchlist(symbol)
    return jsonify({"success": ok})

@main.route('/api/symbols/by-expiry', methods=['GET'])
def api_symbols_by_expiry():
    expiry = request.args.get('expiry', '')
    limit = int(request.args.get('limit', 50))
    if not expiry:
        return jsonify([])
    return jsonify(symbol_master.search_symbols_by_expiry(expiry, limit=limit))

@main.route('/api/symbols/refresh', methods=['POST'])
def api_symbols_refresh():
    try:
        urls = [
            "https://public.fyers.in/sym_details/NSE_CM.csv",
            "https://public.fyers.in/sym_details/NSE_FO.csv",
            "https://public.fyers.in/sym_details/NSE_CD.csv",
        ]
        symbol_master.process_all(urls)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@main.route('/api/clear_processor_state', methods=['POST'])
def api_clear_processor_state():
    """Clear processor state when switching timeframes to prevent stale data"""
    try:
        data = request.get_json()
        symbol = data.get('symbol')
        timeframe = data.get('timeframe')
        bucket_size = float(data.get('bucket_size', 0.05))
        multiplier = int(data.get('multiplier', 100))
        
        if not symbol or not timeframe:
            return jsonify({'error': 'Missing symbol or timeframe'}), 400
        
        from core.fyers.processor import clear_processor_state
        
        success = clear_processor_state(symbol, timeframe, bucket_size, multiplier)
        
        return jsonify({
            'success': success,
            'message': f'Processor state {"cleared" if success else "not found"} for {symbol}-{timeframe}',
            'symbol': symbol,
            'timeframe': timeframe
        })
        
    except Exception as e:
        print(f"Error in /api/clear_processor_state: {e}")
        return jsonify({'error': 'Failed to clear processor state', 'details': str(e)}), 500



@main.route('/api/historical', methods=['GET'])
def api_historical():
    symbol = request.args.get('symbol')
    timeframe = request.args.get('timeframe', '5min')
    bucket_size = request.args.get('bucket_size', 0.05)
    multiplier = request.args.get('multiplier', 100)
    if not symbol:
        return jsonify({'error': 'Missing symbol parameter'}), 400

    try:
        # Create fresh data feed instance to pick up any new tokens
        fresh_data_feed = FyersDataFeed()
        data = fresh_data_feed.get_historical_data(
            symbol,
            timeframe=timeframe,
            bucket_size=float(bucket_size),
            multiplier=int(multiplier)
        )
        return jsonify(data)
    except Exception as e:
        print(f"Error in /api/historical: {e}")
        return jsonify({'error': 'Failed to fetch historical data'}), 500
