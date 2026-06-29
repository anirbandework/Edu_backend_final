# app/models/__init__.py
"""Import all models here, if needed for Alembic migration."""
from .base import Base

# Note: Individual model imports are commented out to avoid circular imports
# Models are imported directly where needed in the application
# For Alembic migrations, models are discovered through their module imports

# This ensures the Base class is available when importing models
