"""
Keying by uid (not IP) is correct for an authenticated API:
- A user behind a corporate NAT shares one IP with thousands of people.
- A single bad actor using multiple IPs (VPN) is caught by uid.
 
Usage on a route:
    @router.post("/api/gavvy")
    @limiter.limit("20/minute")
    async def gavvy(request: Request, ...):
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

def _get_uid_or_ip(request)-> str:
    """
    Key function for slowapi.
    Uses the Firebase uid stored on request.state by the auth dependency.
    Falls back to IP address during health checks.
    """
    uid = getattr(request.state, "uid", None)
    return uid if uid else get_remote_address(request)


limiter = Limiter(key_func=_get_uid_or_ip, default_limits=["20/minute"])