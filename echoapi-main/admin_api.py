"""
Admin API Endpoints
Manage API keys, view statistics, and monitor usage
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional
from pydantic import BaseModel
from auth import api_key_manager, verify_api_key
import logging

logger = logging.getLogger(__name__)

# Create router
admin_router = APIRouter(prefix="/admin", tags=["Admin"])

# Admin master key (change this!)
ADMIN_KEY = "admin_master_key_change_me_in_production"

class CreateKeyRequest(BaseModel):
    name: str
    description: str = ""
    tier: str = "basic"
    rate_limit: int = 1000

async def verify_admin(api_key: str = Depends(verify_api_key)):
    """Verify admin access"""
    if api_key != ADMIN_KEY:
        raise HTTPException(status_code=403, detail="Admin access required")
    return api_key

@admin_router.get("/keys")
async def list_api_keys(admin_key: str = Depends(verify_admin)):
    """
    📋 List all API keys
    
    **Admin Only**: Requires admin API key
    """
    
    keys = api_key_manager.list_keys()
    
    return {
        "success": True,
        "total_keys": len(keys),
        "keys": keys
    }

@admin_router.post("/keys/create")
async def create_api_key(
    request: CreateKeyRequest,
    admin_key: str = Depends(verify_admin)
):
    """
    🔑 Create a new API key
    
    **Admin Only**: Requires admin API key
    
    Tiers:
    - free: 100 requests/day
    - basic: 1,000 requests/day
    - premium: 5,000 requests/day
    - developer: 10,000 requests/day
    - unlimited: ∞ requests/day
    """
    
    try:
        new_key = api_key_manager.generate_api_key(
            name=request.name,
            description=request.description,
            rate_limit=request.rate_limit,
            tier=request.tier
        )
        
        return {
            "success": True,
            "message": "API key created successfully",
            "api_key": new_key,
            "name": request.name,
            "tier": request.tier,
            "rate_limit": request.rate_limit,
            "warning": "⚠️ Save this key securely! It won't be shown again."
        }
        
    except Exception as e:
        logger.error(f"Error creating API key: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create API key: {str(e)}")

@admin_router.delete("/keys/revoke")
async def revoke_api_key(
    api_key: str = Query(description="API key to revoke"),
    admin_key: str = Depends(verify_admin)
):
    """
    ❌ Revoke an API key
    
    **Admin Only**: Requires admin API key
    """
    
    success = api_key_manager.revoke_key(api_key)
    
    if success:
        return {
            "success": True,
            "message": "API key revoked successfully",
            "api_key": api_key[:12] + "..." + api_key[-4:]
        }
    else:
        raise HTTPException(status_code=404, detail="API key not found")

@admin_router.get("/keys/info")
async def get_key_details(
    key: str = Query(description="API key to get details for"),
    admin_key: str = Depends(verify_admin)
):
    """
    📊 Get detailed information about an API key
    
    **Admin Only**: Requires admin API key
    
    Usage: /api/admin/keys/info?key=ytdl_xxxxx
    """
    
    key_info = api_key_manager.get_key_info(key)
    
    if not key_info:
        raise HTTPException(status_code=404, detail="API key not found")
    
    return {
        "success": True,
        "api_key": key[:12] + "..." + key[-4:],
        "details": key_info
    }

@admin_router.get("/stats")
async def get_api_stats(admin_key: str = Depends(verify_admin)):
    """
    📈 Get API usage statistics
    
    **Admin Only**: Requires admin API key
    """
    
    all_keys = api_key_manager.get_all_keys_full()
    
    total_requests = sum(k.get("total_requests", 0) for k in all_keys.values())
    active_keys = sum(1 for k in all_keys.values() if k.get("active", True))
    requests_today = sum(k.get("requests_today", 0) for k in all_keys.values())
    
    # Tier breakdown
    tier_stats = {}
    for key_info in all_keys.values():
        tier = key_info.get("tier", "unknown")
        if tier not in tier_stats:
            tier_stats[tier] = {"count": 0, "requests": 0}
        tier_stats[tier]["count"] += 1
        tier_stats[tier]["requests"] += key_info.get("total_requests", 0)
    
    return {
        "success": True,
        "statistics": {
            "total_keys": len(all_keys),
            "active_keys": active_keys,
            "revoked_keys": len(all_keys) - active_keys,
            "total_requests_all_time": total_requests,
            "requests_today": requests_today,
            "tier_breakdown": tier_stats
        }
    }
