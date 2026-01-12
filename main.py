import os
from dotenv import load_dotenv

# Load Fyers Environment Variables - Must be first!
load_dotenv("env/fyers.env")

from flask import Flask
from flask_socketio import SocketIO
from app.routes import main

import logging

class AccessLogFilter(logging.Filter):
    def filter(self, record):
        return "/fyers/callback" not in record.getMessage()

# Filter out sensitive auth callback logs from werkzeug
logging.getLogger('werkzeug').addFilter(AccessLogFilter())

app = Flask(__name__)

# Secrets and config from environment (set via .env / container)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')

# Register routes
app.register_blueprint(main)

# Initialize Socket.IO
async_mode = os.environ.get('SOCKETIO_ASYNC_MODE', 'threading')  # 'eventlet' recommended in production
cors_origins_env = os.environ.get('CORS_ORIGINS', '*')
# If '*' allow all; otherwise split comma-separated list
cors_allowed = '*' if cors_origins_env.strip() == '*' else [o.strip() for o in cors_origins_env.split(',') if o.strip()]
socketio = SocketIO(app, cors_allowed_origins=cors_allowed, async_mode=async_mode)

# Debug: log effective CORS for sockets
try:
	print(f"SocketIO async_mode={async_mode}, cors_allowed_origins={cors_allowed}")
except Exception:
	pass

# Import socket events after socketio is created
from app.socket_events import register_socket_events
register_socket_events(socketio)

if __name__ == '__main__':
	# Dev server; production uses Gunicorn with eventlet
	import argparse
	parser = argparse.ArgumentParser(description='Run the Nifty-Orderflow app')
	parser.add_argument('--port', type=int, default=int(os.environ.get('APP_PORT', 5000)), help='Port to run the app on')
	args = parser.parse_args()
	
	debug = os.environ.get('FLASK_ENV', 'development') != 'production'
	host = os.environ.get('APP_HOST', '0.0.0.0')
	socketio.run(app, debug=debug, host=host, port=args.port)
