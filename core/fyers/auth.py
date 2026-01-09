import os
import json
import hashlib
import logging
import requests
import base64
import pyotp
from typing import Dict, Tuple, Optional, Any
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta

# Load credentials from environment variables
# Ensure these are set via .env / container environment
CLIENT_ID = os.environ.get('FYERS_CLIENT_ID')
SECRET_KEY = os.environ.get('FYERS_SECRET_KEY')
REDIRECT_URI = os.environ.get('FYERS_REDIRECT_URI')

logger = logging.getLogger(__name__)

class FyersApiError(Exception):
    """Custom exception for Fyers API related errors."""
    
    def __init__(self, message: str, status_code: Optional[int] = None, response_data: Optional[Dict] = None):
        self.message = message
        self.status_code = status_code
        self.response_data = response_data
        super().__init__(self.message)
    
    def __str__(self) -> str:
        parts = [self.message]
        if self.status_code:
            parts.append(f"Status code: {self.status_code}")
        if self.response_data:
            parts.append(f"Response: {self.response_data}")
        return " | ".join(parts)

class TokenManager:
    """Optimized token storage manager."""
    
    def __init__(self, token_file_path: str):
        self.token_file_path = token_file_path
    
    def load(self) -> Dict[str, Any]:
        """Load token data from file."""
        try:
            if not os.path.exists(self.token_file_path):
                return {}
                
            with open(self.token_file_path, 'r') as f:
                content = f.read().strip()
                return json.loads(content) if content else {}
        except (json.JSONDecodeError, Exception) as e:
            logger.error(f"Error loading token: {str(e)}")
            return {}
    
    def save(self, token_data: Dict[str, Any]) -> bool:
        """Save token data to file."""
        try:
            os.makedirs(os.path.dirname(self.token_file_path), exist_ok=True)
            
            # Ensure expiry is in timestamp format
            if 'expiry' in token_data and isinstance(token_data['expiry'], datetime):
                token_data['expiry'] = token_data['expiry'].timestamp()
                
            with open(self.token_file_path, 'w') as f:
                json.dump(token_data, f)
            logger.info("Token saved to file")
            return True
        except Exception as e:
            logger.error(f"Error saving token: {str(e)}")
            return False
    
    def delete(self) -> bool:
        """Delete the token file."""
        try:
            if os.path.exists(self.token_file_path):
                os.remove(self.token_file_path)
                logger.info("Token file removed")
            return True
        except Exception as e:
            logger.error(f"Error removing token file: {str(e)}")
            return False
    
    def is_token_valid(self, token_data: Dict[str, Any]) -> bool:
        """Check if token data is valid and not expired."""
        if not (token_data.get('access_token') and token_data.get('expiry')):
            return False
            
        expiry = token_data['expiry']
        if isinstance(expiry, (float, int)):
            expiry = datetime.fromtimestamp(expiry)
            
        return datetime.now() < expiry

class FyersAuth:
    """Optimized Fyers API v3 authentication handler."""
    
    # API endpoints and constants
    AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
    TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"
    LOGOUT_URL = "https://api-t1.fyers.in/api/v3/logout"
    TOKEN_EXPIRY_HOURS = 24
    
    def __init__(self, token_file: Optional[str] = None):
        """Initialize the Fyers authentication handler."""
        if not CLIENT_ID or not SECRET_KEY or not REDIRECT_URI:
            logger.warning(
                "Missing Fyers credentials in environment. Set FYERS_CLIENT_ID, FYERS_SECRET_KEY, FYERS_REDIRECT_URI"
            )
        self.client_id = CLIENT_ID or ""
        self.secret_key = SECRET_KEY or ""
        self.redirect_uri = REDIRECT_URI or ""
        self.access_token = None
        self.refresh_token = None
        self.token_expiry = None
        self.token_file = token_file or os.path.join("data", "token.json")
        self.token_manager = TokenManager(self.token_file)
        self._load_token()
    
    def _load_token(self) -> bool:
        """Load access token from file if available."""
        token_data = self.token_manager.load()
        
        if not token_data or not self.token_manager.is_token_valid(token_data):
            return False
            
        self.access_token = token_data.get('access_token')
        self.refresh_token = token_data.get('refresh_token')
        self.token_expiry = token_data.get('expiry')
        
        if isinstance(self.token_expiry, (float, int)):
            self.token_expiry = datetime.fromtimestamp(self.token_expiry)
            
        logger.info("Loaded valid token from file")
        return True
    
    def _save_token(self) -> bool:
        """Save access token to file."""
        token_data = {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expiry': self.token_expiry
        }
        return self.token_manager.save(token_data)
    
    def _get_app_id_hash(self) -> str:
        """Generate the app ID hash required for API authentication."""
        return hashlib.sha256(f"{self.client_id}:{self.secret_key}".encode()).hexdigest()
    
    def auto_login(self) -> bool:
        """
        Perform headless login using TOTP and PIN to get auth code, 
        then generate access token.
        """
        fy_id = os.environ.get('FYERS_FY_ID')
        totp_key = os.environ.get('FYERS_TOTP_KEY')
        pin = os.environ.get('FYERS_PIN')
        
        if not (fy_id and totp_key and pin):
            logger.error("Auto Login failed: Missing FYERS_FY_ID, FYERS_TOTP_KEY, or FYERS_PIN in env")
            return False
            
        try:
            logger.info("Starting Auto Login flow...")
            
            # Helper for base64
            def getEncodedString(string):
                base64_bytes = base64.b64encode(string.encode("ascii"))
                return base64_bytes.decode("ascii")

            # 1. Send Login OTP
            URL_SEND_LOGIN_OTP = "https://api-t2.fyers.in/vagator/v2/send_login_otp_v2"
            res = requests.post(URL_SEND_LOGIN_OTP, json={"fy_id": getEncodedString(fy_id), "app_id": "2"}).json()
            
            if 'request_key' not in res:
                logger.error(f"Auto Login Failed at OTP Request: {res}")
                return False

            # 2. Verify OTP
            import time
            time.sleep(1) # Small delay
            URL_VERIFY_OTP = "https://api-t2.fyers.in/vagator/v2/verify_otp"
            otp_val = pyotp.TOTP(totp_key).now()
            res2 = requests.post(url=URL_VERIFY_OTP, json= {"request_key":res["request_key"],"otp":otp_val}).json()
            
            if 'request_key' not in res2:
                 logger.error(f"Auto Login Failed at OTP Verify: {res2}")
                 return False

            # 3. Verify PIN
            ses = requests.Session()
            URL_VERIFY_OTP2 = "https://api-t2.fyers.in/vagator/v2/verify_pin_v2"
            payload2 = {"request_key": res2["request_key"], "identity_type": "pin", "identifier": getEncodedString(pin)}
            res3 = ses.post(URL_VERIFY_OTP2, json=payload2).json()
            
            if 'data' not in res3 or 'access_token' not in res3['data']:
                logger.error(f"Auto Login Failed at PIN Verify: {res3}")
                return False
                
            # Set authorization header for the session
            ses.headers.update({'authorization': f"Bearer {res3['data']['access_token']}"})
            
            # 4. Request Auth Code
            # Assume client_id format is 'APPID-100' -> 'APPID'
            app_id_short = self.client_id[:-4] if len(self.client_id) > 4 else self.client_id

            TOKENURL = "https://api-t1.fyers.in/api/v3/token"
            payload3 = {
                "fyers_id": fy_id, 
                "app_id": app_id_short, 
                "redirect_uri": self.redirect_uri, 
                "appType": "100", 
                "code_challenge": "", 
                "state": "None", 
                "scope": "", 
                "nonce": "", 
                "response_type": "code", 
                "create_cookie": True
            }
            
            res4 = ses.post(TOKENURL, json=payload3).json()
            
            if 'Url' not in res4:
                 logger.error(f"Auto Login Failed at Token Request: {res4}")
                 return False
                 
            url = res4['Url']
            auth_code = self.extract_auth_code(url)
            
            if not auth_code:
                logger.error("Auto Login Failed: Could not extract auth code")
                return False
                
            # 5. Generate Access Token
            return self.generate_access_token(auth_code)

        except Exception as e:
            logger.error(f"Auto Login Exception: {str(e)}")
            return False

    def get_auth_url(self, state: Optional[str] = None) -> str:
        """Get the Fyers authentication URL for web-based authentication."""
        params = {
            'client_id': self.client_id,
            'redirect_uri': self.redirect_uri,
            'response_type': 'code'
        }
        
        if state:
            params['state'] = state
            
        query_string = '&'.join(f"{k}={v}" for k, v in params.items())
        auth_url = f"{self.AUTH_URL}?{query_string}"
        
        # logger.info(f"Generated auth URL: {auth_url}")
        return auth_url
    
    def extract_auth_code(self, url: str) -> Optional[str]:
        """Extract the authorization code from a callback URL."""
        try:
            parsed_url = urlparse(url)
            query_params = parse_qs(parsed_url.query)
            
            # Check for both 'code' and 'auth_code' as Fyers might use either
            auth_code = query_params.get('auth_code', [None])[0] or query_params.get('code', [None])[0]
            
            if auth_code:
                logger.info("Successfully extracted auth code from URL")
                return auth_code
            else:
                logger.warning("No auth code found in URL")
                return None
                
        except Exception as e:
            logger.error(f"Error extracting auth code: {str(e)}")
            return None
    
    def generate_access_token(self, auth_code: str) -> bool:
        """Generate access token using authorization code."""
        try:
            payload = {
                "grant_type": "authorization_code",
                "appIdHash": self._get_app_id_hash(),
                "code": auth_code
            }
            
            logger.info("Requesting access token...")
            response = requests.post(self.TOKEN_URL, json=payload)
            
            if response.status_code != 200:
                raise FyersApiError(
                    f"HTTP error during token generation", 
                    status_code=response.status_code, 
                    response_data=response.text
                )
                
            response_data = response.json()
            
            if response_data.get('s') != 'ok':
                raise FyersApiError(
                    f"Token generation failed: {response_data.get('message', 'Unknown error')}", 
                    response_data=response_data
                )
                
            self.access_token = response_data['access_token']
            self.refresh_token = response_data.get('refresh_token')
            self.token_expiry = datetime.now() + timedelta(hours=self.TOKEN_EXPIRY_HOURS)
            
            self._save_token()
            logger.info("Access token generated successfully")
            return True
            
        except FyersApiError:
            raise
        except Exception as e:
            logger.error(f"Error generating access token: {str(e)}")
            return False
    
    def is_token_valid(self) -> bool:
        """Check if the current token is valid and not expired."""
        return (self.access_token and self.token_expiry and 
                datetime.now() < self.token_expiry)
    
    def is_authenticated(self) -> bool:
        """Check if user is authenticated with a valid token."""
        return self.is_token_valid()
    
    def logout(self) -> bool:
        """Logout and clear stored tokens."""
        try:
            if self.access_token:
                # Attempt to logout via API
                headers = {"Authorization": f"Bearer {self.access_token}"}
                requests.post(self.LOGOUT_URL, headers=headers)
            
            # Clear local tokens
            self.access_token = None
            self.refresh_token = None
            self.token_expiry = None
            self.token_manager.delete()
            
            logger.info("Logged out successfully")
            return True
        except Exception as e:
            logger.error(f"Error during logout: {str(e)}")
            return False
    
    def get_auth_header(self) -> Dict[str, str]:
        """Get authorization header for API requests."""
        if not self.access_token:
            raise FyersApiError("No access token available")
        return {"Authorization": f"Bearer {self.access_token}"}
    
    def authenticate(self) -> Optional[str]:
        """Perform the complete authentication process."""
        if self.is_token_valid():
            return self.access_token
        
        logger.error("Authentication required - please use web flow")
        return None
    
    @classmethod
    def get_fyers_credentials(cls) -> Tuple[str, Optional[str]]:
        """Get Fyers API credentials after ensuring authentication."""
        auth = cls()
        if not auth.is_authenticated():
            auth.authenticate()
        return auth.client_id, auth.access_token
    
    @classmethod
    def refresh_credentials(cls) -> bool:
        """Force refresh of credentials by creating a new auth instance."""
        try:
            auth = cls()
            return auth.is_authenticated()
        except Exception as e:
            logger.error(f"Error refreshing credentials: {str(e)}")
            return False
