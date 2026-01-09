import time
import json
import asyncio
import websockets
import threading
from .protobuf import msg_pb2

class FyersVersovaEngine:
    def __init__(self, auth_token, api_key, symbol, on_message_callback=None, log_callback=None):
        self.auth_token = auth_token
        self.api_key = api_key
        self.symbol = symbol
        self.on_message_callback = on_message_callback
        self.log_callback = log_callback or print
        
        self.websocket_url = "wss://rtsocket-api.fyers.in/versova"
        self.websocket = None
        self.running = False
        self.last_ping_time = 0
        
        # Order book storage
        self.order_books = {}

    def log(self, message):
        if self.log_callback:
            self.log_callback(f"[Versova] {message}")

    def update_order_book(self, ticker, bids, asks, tbq, tsq, timestamp, is_snapshot):
        """Enhanced order book update with guaranteed 50-level depth maintenance"""
        if ticker not in self.order_books:
            # Initialize empty order book with 50 levels
            self.order_books[ticker] = {
                'bids': {i: {'price': 0.0, 'qty': 0, 'orders': 0, 'level': i} for i in range(50)},
                'asks': {i: {'price': 0.0, 'qty': 0, 'orders': 0, 'level': i} for i in range(50)},
                'tbq': 0,
                'tsq': 0,
                'timestamp': 0,
                'initialized': False
            }
        
        book = self.order_books[ticker]
        book['tbq'] = tbq
        book['tsq'] = tsq
        book['timestamp'] = timestamp
        
        first_update = not book.get('initialized', False)
        
        if is_snapshot or first_update:
            if first_update:
                # Only reset on very first update
                for i in range(50):
                    book['bids'][i] = {'price': 0.0, 'qty': 0, 'orders': 0, 'level': i}
                    book['asks'][i] = {'price': 0.0, 'qty': 0, 'orders': 0, 'level': i}
        
        # Process bid updates
        for bid in bids:
            level = bid['level']
            if 0 <= level < 50:
                old_data = book['bids'][level]
                
                if bid['price'] == 0.0 and bid['qty'] > 0:
                    if old_data['price'] > 0:
                        book['bids'][level] = {
                            'price': old_data['price'], 
                            'qty': bid['qty'],
                            'orders': bid['orders'], 
                            'level': level
                        }
                elif bid['qty'] == 0:
                    if bid['price'] == 0.0 and old_data['price'] > 0:
                        book['bids'][level] = {
                            'price': old_data['price'], 
                            'qty': 0, 
                            'orders': bid['orders'], 
                            'level': level
                        }
                    elif bid['price'] > 0:
                        book['bids'][level] = bid
                    else:
                        if old_data['price'] > 0:
                            book['bids'][level] = {
                                'price': old_data['price'], 
                                'qty': 0, 
                                'orders': bid['orders'], 
                                'level': level
                            }
                        else:
                            book['bids'][level] = {'price': 0.0, 'qty': 0, 'orders': 0, 'level': level}
                else:
                    book['bids'][level] = bid
        
        # Process ask updates
        for ask in asks:
            level = ask['level']
            if 0 <= level < 50:
                old_data = book['asks'][level]
                
                if ask['price'] == 0.0 and ask['qty'] > 0:
                    if old_data['price'] > 0:
                        book['asks'][level] = {
                            'price': old_data['price'], 
                            'qty': ask['qty'],
                            'orders': ask['orders'], 
                            'level': level
                        }
                elif ask['qty'] == 0:
                    if ask['price'] == 0.0 and old_data['price'] > 0:
                        book['asks'][level] = {
                            'price': old_data['price'], 
                            'qty': 0, 
                            'orders': ask['orders'], 
                            'level': level
                        }
                    elif ask['price'] > 0:
                        book['asks'][level] = ask
                    else:
                        if old_data['price'] > 0:
                            book['asks'][level] = {
                                'price': old_data['price'], 
                                'qty': 0, 
                                'orders': ask['orders'], 
                                'level': level
                            }
                        else:
                            book['asks'][level] = {'price': 0.0, 'qty': 0, 'orders': 0, 'level': level}
                else:
                    book['asks'][level] = ask
        
        book['initialized'] = True

    def get_full_order_book(self, ticker):
        """Get the complete 50-level order book for display with proper depth reconstruction"""
        if ticker not in self.order_books:
            return None
        
        book = self.order_books[ticker]
        
        # Get all bid levels with valid prices
        raw_bids = []
        for i in range(50):
            bid = book['bids'][i]
            if bid['price'] > 0:
                raw_bids.append(bid)
        
        # Sort bids by price (highest first)
        raw_bids.sort(key=lambda x: x['price'], reverse=True)
        active_bids = []
        for i, bid in enumerate(raw_bids[:50]):
            active_bids.append({
                'price': bid['price'],
                'qty': bid['qty'],
                'orders': bid['orders'],
                'level': i
            })
        
        # Get all ask levels with valid prices
        raw_asks = []
        for i in range(50):
            ask = book['asks'][i]
            if ask['price'] > 0:
                raw_asks.append(ask)
        
        # Sort asks by price (lowest first)
        raw_asks.sort(key=lambda x: x['price'])
        active_asks = []
        for i, ask in enumerate(raw_asks[:50]):
            active_asks.append({
                'price': ask['price'],
                'qty': ask['qty'],
                'orders': ask['orders'],
                'level': i
            })
        
        return {
            'ticker': ticker,
            'tbq': book['tbq'],
            'tsq': book['tsq'],
            'timestamp': book['timestamp'],
            'bids': active_bids,
            'asks': active_asks,
            'bidprice': [bid['price'] for bid in active_bids],
            'askprice': [ask['price'] for ask in active_asks],
            'bidqty': [bid['qty'] for bid in active_bids],
            'askqty': [ask['qty'] for ask in active_asks],
            'bidordn': [bid['orders'] for bid in active_bids],
            'askordn': [ask['orders'] for ask in active_asks]
        }

    def process_market_depth(self, message_bytes):
        """Process market depth protobuf message"""
        try:
            socket_message = msg_pb2.SocketMessage()
            socket_message.ParseFromString(message_bytes)
            
            if socket_message.error:
                self.log(f"Error in socket message: {socket_message.msg}")
                return None
                
            market_data = {}
            for ticker, feed in socket_message.feeds.items():
                timestamp = feed.feed_time.value if feed.feed_time else None
                tbq = feed.depth.tbq.value if feed.depth.tbq else 0
                tsq = feed.depth.tsq.value if feed.depth.tsq else 0
                is_snapshot = socket_message.snapshot
                
                update_bids = []
                for bid in feed.depth.bids:
                    update_bids.append({
                        'price': bid.price.value / 100.0,
                        'qty': bid.qty.value,
                        'orders': bid.nord.value,
                        'level': bid.num.value
                    })
                
                update_asks = []
                for ask in feed.depth.asks:
                    update_asks.append({
                        'price': ask.price.value / 100.0,
                        'qty': ask.qty.value,
                        'orders': ask.nord.value,
                        'level': ask.num.value
                    })
                
                self.update_order_book(ticker, update_bids, update_asks, tbq, tsq, timestamp, is_snapshot)
                
                full_book = self.get_full_order_book(ticker)
                if full_book:
                    market_data[ticker] = full_book
            
            return market_data if len(market_data) > 0 else None
            
        except Exception as e:
            self.log(f"Error processing market depth: {e}")
            return None

    async def _run_loop(self):
        """Async loop for WebSocket connection"""
        self.running = True
        
        while self.running:
            try:
                auth_header = f"{self.api_key}:{self.auth_token}"
                
                async with websockets.connect(
                    self.websocket_url,
                    extra_headers={"Authorization": auth_header}
                ) as ws:
                    self.websocket = ws
                    self.log("Connected to Fyers Versova")
                    
                    # Subscribe
                    subscribe_msg = {
                        "type": 1,
                        "data": {
                            "subs": 1,
                            "symbols": [self.symbol],
                            "mode": "depth",
                            "channel": "1"
                        }
                    }
                    await ws.send(json.dumps(subscribe_msg))
                    
                    # Resume
                    resume_msg = {
                        "type": 2,
                        "data": {
                            "resumeChannels": ["1"],
                            "pauseChannels": []
                        }
                    }
                    await ws.send(json.dumps(resume_msg))
                    
                    self.last_ping_time = time.time()
                    
                    while self.running:
                        try:
                            # Ping/Pong logic
                            if time.time() - self.last_ping_time >= 30:
                                await ws.send("ping")
                                self.last_ping_time = time.time()
                            
                            message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                            
                            if isinstance(message, bytes):
                                market_data = self.process_market_depth(message)
                                if market_data and self.on_message_callback:
                                    self.on_message_callback(market_data)
                            
                        except asyncio.TimeoutError:
                            continue
                        except websockets.ConnectionClosed:
                            self.log("Connection closed")
                            break
                        except Exception as e:
                            self.log(f"Error in receive loop: {e}")
                            
            except Exception as e:
                self.log(f"Connection error: {e}")
                await asyncio.sleep(5)

    def start(self):
        """Start the WebSocket in a background thread"""
        def run():
            asyncio.run(self._run_loop())
        
        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop the WebSocket"""
        self.running = False
        if self.thread:
            self.thread.join()
