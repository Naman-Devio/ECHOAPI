"""
API Key Authentication System
Simple and secure API key management
"""

import secrets
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any
from fastapi import HTTPException, Security, status, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import logging

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)

class APIKeyManager:
    """Manages API keys with rate limiting and usage tracking"""
    
    def __init__(self, keys_file: str = "api_keys.json"):
        self.keys_file = Path(keys_file)
        self.api_keys = self._load_keys()
        
        # Create default keys if none exist
        if not self.api_keys:
            self._create_default_keys()
    
    def _load_keys(self) -> Dict[str, Dict[str, Any]]:
        """Load API keys from file"""
        if self.keys_file.exists():
            try:
                with open(self.keys_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading API keys: {e}")
        return {}
    
    def _save_keys(self):
        """Save API keys to file"""
        try:
            with open(self.keys_file, 'w') as f:
                json.dump(self.api_keys, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Error saving API keys: {e}")
    
    def _create_default_keys(self):
        """Create default API keys for testing"""
        # Free tier key
        free_key = self.generate_api_key(
            name="Free Tier",
            description="Default free API key for testing",
            rate_limit=100,
            tier="free"
        )
        
        # Unlimited key
        unlimited_key = self.generate_api_key(
            name="Unlimited",
            description="Unlimited access key",
            rate_limit=999999,
            tier="unlimited"
        )
        
        logger.info(f"Created default API keys:")
        logger.info(f"  FREE: {free_key}")
        logger.info(f"  UNLIMITED: {unlimited_key}")
    
    def generate_api_key(
        self, 
        name: str, 
        description: str = "", 
        rate_limit: int = 1000,
        tier: str = "basic"
    ) -> str:
        """Generate a new API key"""
        key = f"ytdl_{secrets.token_urlsafe(32)}"
        
        self.api_keys[key] = {
            "name": name,
            "description": description,
            "tier": tier,
            "created_at": datetime.now().isoformat(),
            "rate_limit": rate_limit,
            "requests_today": 0,
            "total_requests": 0,
            "last_used": None,
            "last_reset": datetime.now().date().isoformat(),
            "active": True
        }
        
        self._save_keys()
        logger.info(f"Generated new API key for: {name} (tier: {tier})")
        return key
    
    def validate_key(self, api_key: str) -> bool:
        """Validate an API key and check rate limits"""
        if api_key not in self.api_keys:
            return False
        
        key_info = self.api_keys[api_key]
        
        # Check if key is active
        if not key_info.get("active", True):
            return False
        
        # Reset daily counter if new day
        today = datetime.now().date().isoformat()
        if key_info.get("last_reset") != today:
            key_info["requests_today"] = 0
            key_info["last_reset"] = today
        
        # Check rate limit
        if key_info["requests_today"] >= key_info["rate_limit"]:
            return False
        
        # Update usage stats
        key_info["requests_today"] += 1
        key_info["total_requests"] = key_info.get("total_requests", 0) + 1
        key_info["last_used"] = datetime.now().isoformat()
        self._save_keys()
        
        return True
    
    def get_key_info(self, api_key: str) -> Optional[Dict[str, Any]]:
        """Get information about an API key"""
        return self.api_keys.get(api_key)
    
    def list_keys(self) -> Dict[str, Dict[str, Any]]:
        """List all API keys (masked)"""
        return {
            key[:12] + "..." + key[-4:]: {
                "name": info["name"],
                "tier": info.get("tier", "basic"),
                "description": info["description"],
                "created_at": info["created_at"],
                "rate_limit": info["rate_limit"],
                "requests_today": info.get("requests_today", 0),
                "total_requests": info.get("total_requests", 0),
                "last_used": info.get("last_used"),
                "active": info.get("active", True)
            }
            for key, info in self.api_keys.items()
        }
    
    def revoke_key(self, api_key: str) -> bool:
        """Revoke an API key"""
        if api_key in self.api_keys:
            self.api_keys[api_key]["active"] = False
            self._save_keys()
            logger.info(f"Revoked API key: {api_key[:12]}...")
            return True
        return False
    
    def get_all_keys_full(self) -> Dict[str, Dict[str, Any]]:
        """Get all keys with full details (for admin only)"""
        return self.api_keys

# Global API key manager
api_key_manager = APIKeyManager()

async def verify_api_key(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    api_key: Optional[str] = Query(None, description="API key (alternative to Authorization header)")
) -> str:
    """
    Verify API key from Authorization header or query parameter
    
    Usage:
    - Header: Authorization: Bearer your_api_key
    - Query: ?api_key=your_api_key
    """
    
    # Try Authorization header first
    if credentials:
        key = credentials.credentials
        if api_key_manager.validate_key(key):
            return key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key"
        )
    
    # Try query parameter
    if api_key:
        if api_key_manager.validate_key(api_key):
            return api_key
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key"
        )
    
    # No API key provided
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="API key required. Use Authorization header or ?api_key= parameter",
        headers={"WWW-Authenticate": "Bearer"}
    )

async def verify_api_key_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    api_key: Optional[str] = Query(None)
) -> Optional[str]:
    """Optional API key verification (returns None if no key provided)"""
    
    if credentials and api_key_manager.validate_key(credentials.credentials):
        return credentials.credentials
    
    if api_key and api_key_manager.validate_key(api_key):
        return api_key
    
    return None
