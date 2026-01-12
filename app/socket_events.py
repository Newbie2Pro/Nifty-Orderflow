import threading
import time
import os
import sys
from flask_socketio import emit, disconnect, join_room, leave_room
from flask import request

# Add paths for imports
for path in ['core/fyers']:
    sys.path.append(os.path.join(os.path.dirname(__file__), '..', path))

from core.fyers.fyers_data import FyersDataFeed

# Global state for managing subscriptions and live data feeds
live_feeds = {}  # symbol -> {feed_instance, subscribers}
subscriber_rooms = {}  # room_id -> {symbol, timeframe, bucket_size, multiplier}
feed_threads = {}  # symbol -> thread

# Global WebSocket connection for multiple symbols (more efficient)
global_feed = None
global_feed_thread = None
subscribed_symbols = set()  # Track all symbols currently subscribed
socketio_instance = None  # Global reference to socketio


def register_socket_events(socketio):
    """Register all socket event handlers with improved error handling and cumulative delta support"""
    global socketio_instance
    socketio_instance = socketio

    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        print(f"Client connected: {request.sid}")
        emit('connected', {'data': 'Connected to TradeLab'})

    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection and cleanup"""
        print(f"Client disconnected: {request.sid}")
        cleanup_client_subscriptions(request.sid)

    @socketio.on('subscribe_symbol')
    def handle_subscribe_symbol(data):
        """
        Subscribe to live updates for a symbol with specific parameters
        Expected data: {
            'symbol': 'NSE:NIFTY25AUGFUT',
            'timeframe': '5m',
            'bucket_size': 0.05,
            'multiplier': 100,
            'chart_id': 'chart-0',
            'hist_seed': {...}  # Last candle for processor seeding (required)
        }
        """
        try:
            symbol = data.get('symbol')
            timeframe = data.get('timeframe', '5m')
            bucket_size = float(data.get('bucket_size', 0.05))
            multiplier = int(data.get('multiplier', 100))
            chart_id = data.get('chart_id')
            hist_seed = data.get('hist_seed')  # Historical seed candle from frontend

            if not symbol or not chart_id:
                emit('error', {'message': 'Missing symbol or chart_id'})
                return

            # Create room ID for this specific subscription
            room_id = f"{request.sid}_{chart_id}_{symbol}_{timeframe}_{bucket_size}_{multiplier}"

            # Join the room
            join_room(room_id)

            # Store subscription details
            subscriber_rooms[room_id] = {
                'symbol': symbol,
                'timeframe': timeframe,
                'bucket_size': bucket_size,
                'multiplier': multiplier,
                'chart_id': chart_id,
                'client_id': request.sid
            }

            # Start live feed with historical seeding from frontend
            start_live_feed(symbol, timeframe, bucket_size, multiplier, hist_seed)

            print(f"Client {request.sid} subscribed to {symbol} for chart {chart_id}")
            emit('subscription_success', {
                'symbol': symbol,
                'chart_id': chart_id,
                'room_id': room_id
            })

        except Exception as e:
            print(f"Error in subscribe_symbol: {e}")
            emit('error', {'message': str(e)})

    @socketio.on('unsubscribe_symbol')
    def handle_unsubscribe_symbol(data):
        """
        Unsubscribe from a symbol
        Expected data: {
            'symbol': 'NSE:NIFTY25AUGFUT',
            'chart_id': 'chart-0'
        }
        """
        try:
            symbol = data.get('symbol')
            chart_id = data.get('chart_id')

            if not symbol or not chart_id:
                emit('error', {'message': 'Missing symbol or chart_id'})
                return

            # Find and remove the room
            rooms_to_remove = []
            for room_id, room_data in subscriber_rooms.items():
                if (room_data['client_id'] == request.sid and
                    room_data['symbol'] == symbol and
                    room_data['chart_id'] == chart_id):
                    rooms_to_remove.append(room_id)

            for room_id in rooms_to_remove:
                leave_room(room_id)
                del subscriber_rooms[room_id]

            # Check if we should stop the feed for this symbol
            stop_live_feed_if_no_subscribers(symbol)

            print(f"Client {request.sid} unsubscribed from {symbol} for chart {chart_id}")
            emit('unsubscription_success', {
                'symbol': symbol,
                'chart_id': chart_id
            })

        except Exception as e:
            print(f"Error in unsubscribe_symbol: {e}")
            emit('error', {'message': str(e)})


def cleanup_client_subscriptions(client_id):
    """Clean up all subscriptions for a disconnected client"""
    rooms_to_remove = []
    symbols_to_check = set()

    for room_id, room_data in subscriber_rooms.items():
        if room_data['client_id'] == client_id:
            rooms_to_remove.append(room_id)
            symbols_to_check.add(room_data['symbol'])

    for room_id in rooms_to_remove:
        del subscriber_rooms[room_id]

    # Check if we should stop feeds for symbols with no subscribers
    for symbol in symbols_to_check:
        stop_live_feed_if_no_subscribers(symbol)


def start_live_feed(symbol, timeframe, bucket_size, multiplier, hist_seed=None):
    """Start live data feed for a symbol using global WebSocket connection"""
    global global_feed, global_feed_thread, subscribed_symbols

    # Add symbol to subscribed set
    subscribed_symbols.add(symbol)

    # If symbol already has subscribers, just increment count
    if symbol in live_feeds:
        live_feeds[symbol]['subscribers'] += 1
        return

    # Initialize symbol in live_feeds
    live_feeds[symbol] = {'subscribers': 1}

    # Seed the processor with frontend-provided historical data
    if hist_seed and isinstance(hist_seed, dict):
        try:
            from core.fyers.processor import process_live_data
            # Create a harmless seeding tick: use last close as ltp and zero volume
            seed_msg = {
                'symbol': symbol,
                'ltp': float(hist_seed.get('close', 0.0) or 0.0),
                'vol_traded_today': int(hist_seed.get('volume', 0) or 0),
                'last_traded_qty': 0
            }
            
            # Call process_live_data with hist_last_candle to seed internal state
            # This properly initializes cumulative delta from historical data
            process_live_data(seed_msg, timeframe=timeframe, bucket_size=bucket_size, multiplier=multiplier, hist_last_candle=hist_seed)
            print(f"[SEEDED]: Live aggregator for {symbol} from frontend historical candle time={hist_seed.get('time')} cum_delta={hist_seed.get('cum_delta', 0)}")
            
        except Exception as e:
            print(f"[SEED FAILED]: Failed to seed processor for {symbol}: {e}")
    else:
        print(f"[WARNING]: No historical seed provided for {symbol} - processor will start without seeding")

    # Start global feed if not already running
    if global_feed is None:
        try:
            start_global_feed()
        except Exception as e:
            print(f"Error starting global feed: {e}")
            return

    # Subscribe to the new symbol on existing connection
    try:
        if global_feed and hasattr(global_feed, 'subscribe'):
            global_feed.subscribe(symbols=[symbol], data_type="SymbolUpdate")
            print(f"Subscribed to {symbol} on global feed")
    except Exception as e:
        print(f"Error subscribing to {symbol}: {e}")


def start_global_feed():
    """Start the global WebSocket feed that handles all symbols"""
    global global_feed, global_feed_thread

    try:
        # Create new feed instance with fresh auth
        fyers_feed = FyersDataFeed(force_refresh_auth=True)

        # Create global callback that processes all incoming messages
        def global_live_data_callback(raw_message):
            # print(f"DEBUG: Received raw message type: {type(raw_message)}")
            if not raw_message:
                return

            # Handle different message formats
            if isinstance(raw_message, dict):
                process_single_message(raw_message)
            elif isinstance(raw_message, list):
                # Handle case where multiple symbols might be in a list
                for msg in raw_message:
                    if isinstance(msg, dict):
                        process_single_message(msg)
            else:
                print(f"Unexpected message format: {type(raw_message)} - {raw_message}")

        def process_single_message(msg):
            """Process a single message for all relevant rooms"""
            if not isinstance(msg, dict) or not msg.get('symbol'):
                # print(f"Invalid message format or missing symbol: {msg}")
                return

            msg_symbol = msg.get('symbol')
            # print(f"DEBUG: Processing message for {msg_symbol}")

            # Only process if we have subscribers for this symbol
            if msg_symbol not in subscribed_symbols:
                # print(f"DEBUG: No subscribers for {msg_symbol}")
                return

            # Find rooms subscribed to this symbol
            matching_rooms = [
                (room_id, room_data) for room_id, room_data in subscriber_rooms.items()
                if room_data['symbol'] == msg_symbol
            ]

            if not matching_rooms:
                return

            # Process the message for each room subscribed to this symbol
            for room_id, room_data in matching_rooms:
                try:
                    # Import processor here to avoid circular imports
                    from core.fyers.processor import process_live_data

                    # Process data with room-specific parameters
                    room_timeframe = room_data['timeframe']
                    room_bucket_size = room_data['bucket_size']
                    room_multiplier = room_data['multiplier']

                    processed_data = process_live_data(
                        msg,
                        timeframe=room_timeframe,
                        bucket_size=room_bucket_size,
                        multiplier=room_multiplier
                    )

                    if processed_data:
                        # Emit live data update with proper cumulative delta
                        if socketio_instance:
                            socketio_instance.emit('live_data_update', {
                                'symbol': msg_symbol,
                                'chart_id': room_data['chart_id'],
                                'data': processed_data,
                                'timeframe': room_timeframe,
                                'timestamp': time.time()
                            }, room=room_id)
                    #else:
                    #    print(f"No processed data returned for {msg_symbol} - likely duplicate tick or no volume")

                except Exception as e:
                    print(f"Error processing live data for room {room_id}: {e}")
                    import traceback
                    traceback.print_exc()

        # Start the global feed in a separate thread
        global_feed_thread = threading.Thread(
            target=run_global_live_feed,
            args=(fyers_feed, global_live_data_callback),
            daemon=True
        )
        global_feed_thread.start()

        # Do not reset global_feed here; it will be set inside run_global_live_feed

        print("Started global live feed")

    except Exception as e:
        print(f"Error starting global live feed: {e}")


def run_global_live_feed(fyers_feed, callback):
    """Run global live feed that handles all symbols"""
    global global_feed

    try:
        data_type = "SymbolUpdate"

        def onmessage(raw_message):
            """Pass raw message to callback for processing"""
            try:
                if raw_message and callback:
                    callback(raw_message)
            except Exception as e:
                print(f"Error in global live feed callback: {e}")

        def onerror(message):
            print("Global live feed error:", message)
            if socketio_instance:
                socketio_instance.emit('live_feed_error', {
                    'error': str(message)
                })

        def onclose(message):
            print("Global live feed connection closed:", message)
            if socketio_instance:
                socketio_instance.emit('live_feed_closed', {
                    'message': str(message)
                })

        def onopen():
            # Subscribe to all currently subscribed symbols using the local socket instance
            try:
                if subscribed_symbols:
                    symbols_list = list(subscribed_symbols)
                    sock.subscribe(symbols=symbols_list, data_type=data_type)
                    print(f"Global feed subscribed to symbols: {symbols_list}")
                sock.keep_running()
            except Exception as e:
                print(f"Global live feed error during onopen: {e}")
                if socketio_instance:
                    socketio_instance.emit('live_feed_error', {
                        'error': str(e)
                    })

        from fyers_apiv3.FyersWebsocket import data_ws
        sock = data_ws.FyersDataSocket(
            access_token=fyers_feed.access_token,
            log_path="",
            litemode=False,
            write_to_file=False,
            reconnect=True,
            on_connect=onopen,
            on_close=onclose,
            on_error=onerror,
            on_message=onmessage,
        )
        # Expose as global for other parts of this module
        global_feed = sock
        sock.connect()

    except Exception as e:
        print(f"Error in global live feed thread: {e}")


def stop_live_feed_if_no_subscribers(symbol):
    """Stop live feed if no active subscribers"""
    global global_feed, subscribed_symbols

    if symbol not in live_feeds:
        return

    # Check if any rooms are still subscribed to this symbol
    has_subscribers = any(
        room_data['symbol'] == symbol
        for room_data in subscriber_rooms.values()
    )

    if not has_subscribers:
        # Remove symbol from subscribed set
        subscribed_symbols.discard(symbol)

        # Unsubscribe from the symbol on global feed
        try:
            if global_feed and hasattr(global_feed, 'unsubscribe'):
                global_feed.unsubscribe(symbols=[symbol])
                print(f"Unsubscribed from {symbol} on global feed")
        except Exception as e:
            print(f"Error unsubscribing from {symbol}: {e}")

        # Remove from live_feeds tracking
        if symbol in live_feeds:
            del live_feeds[symbol]

        # Clean up legacy feed_threads if any
        if symbol in feed_threads:
            del feed_threads[symbol]

        print(f"Stopped live feed for {symbol} - no active subscribers")

        # If no symbols are subscribed, stop global feed
        if not subscribed_symbols and global_feed:
            try:
                global_feed.close_connection()
                global_feed = None
                print("Stopped global live feed - no active symbols")
            except Exception as e:
                print(f"Error stopping global feed: {e}")
