# app/core/logging.py
"""Logging configuration."""
import logging
import sys
from .config import settings

def setup_logging():
    log_level = getattr(settings, 'log_level', 'INFO').upper()
    app_name = getattr(settings, 'app_name', 'edu_backend')
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

logger = logging.getLogger('edu_backend')
setup_logging()
