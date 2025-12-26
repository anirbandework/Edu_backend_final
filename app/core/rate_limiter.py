from fastapi import HTTPException, Request
from typing import Dict
import time

class RateLimiter:
    def __init__(self):
        self.requests: Dict[str, list] = {}
    
    async def check_rate_limit(self, request: Request, max_requests: int = 60, window: int = 60):
        """Check rate limit for endpoint"""
        client_ip = request.client.host
        endpoint = str(request.url.path)
        key = f"{client_ip}:{endpoint}"
        
        now = time.time()
        
        # Clean old requests
        if key in self.requests:
            self.requests[key] = [req_time for req_time in self.requests[key] if now - req_time < window]
        else:
            self.requests[key] = []
        
        # Check limit
        if len(self.requests[key]) >= max_requests:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
        # Add current request
        self.requests[key].append(now)

rate_limiter = RateLimiter()