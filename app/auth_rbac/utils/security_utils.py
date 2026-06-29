from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List
import re
import logging

logger = logging.getLogger(__name__)

class SQLSecurityError(Exception):
    """SQL security violation exception"""
    pass

def validate_sql_params(params: Dict[str, Any]) -> Dict[str, Any]:
    """Validate SQL parameters to prevent injection"""
    validated = {}
    
    for key, value in params.items():
        # Check for SQL injection patterns
        if isinstance(value, str):
            # Basic SQL injection pattern detection
            dangerous_patterns = [
                r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|UNION)\b)",
                r"(--|#|/\*|\*/)",
                r"(\b(OR|AND)\s+\d+\s*=\s*\d+)",
                r"(\bOR\s+\w+\s*=\s*\w+)",
                r"(\';|\"\;)"
            ]
            
            for pattern in dangerous_patterns:
                if re.search(pattern, value, re.IGNORECASE):
                    logger.warning(f"Potential SQL injection attempt detected in parameter '{key}': {value}")
                    raise SQLSecurityError(f"Invalid parameter value for '{key}'")
        
        validated[key] = value
    
    return validated

async def safe_execute(
    db: AsyncSession, 
    query: str, 
    params: Dict[str, Any] = None
) -> Any:
    """Safely execute SQL with parameter validation"""
    if params:
        params = validate_sql_params(params)
    
    try:
        result = await db.execute(text(query), params or {})
        return result
    except Exception as e:
        logger.error(f"SQL execution error: {e}")
        raise

def sanitize_search_term(term: str) -> str:
    """Sanitize search terms for LIKE queries"""
    if not isinstance(term, str):
        return ""
    
    # Remove dangerous characters
    sanitized = re.sub(r"[%_\\]", r"\\\g<0>", term)
    # Limit length
    sanitized = sanitized[:100]
    
    return sanitized