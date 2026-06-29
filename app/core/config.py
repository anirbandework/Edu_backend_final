# app/core/config.py
"""Application configuration using Pydantic."""
from pydantic_settings import BaseSettings
from typing import List

class Settings(BaseSettings):
    database_url: str
    redis_url: str
    jwt_secret_key: str

    app_version: str = '1.0.0'
    environment: str = 'development'
    log_level: str = 'info'
    # SECURITY: lock CORS down to known origins in production. '*' only for local dev.
    allowed_origins: List[str] = [
        'http://localhost:8550',
        'http://localhost:3000',
        'http://127.0.0.1:8550',
    ]

    # --- JWT / auth ---
    jwt_algorithm: str = 'HS256'
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Platform super-admin bootstrap. The first super-admin is SEEDED into the
    # super_admins table from these values (scripts/migrate_security). Login is by
    # phone+password (email also accepted). Leave password empty to skip seeding.
    super_admin_email: str = 'superadmin@eduassist.local'
    super_admin_phone: str = ''
    super_admin_password: str = ''
    super_admin_first_name: str = 'Super'
    super_admin_last_name: str = 'Admin'

    # --- DB connection pool (per engine; sized for many workers behind PgBouncer) ---
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_recycle_seconds: int = 1800

    # --- OTP (phone verification) ---
    # Dev mode: every OTP is this fixed code and is logged, no SMS sent. Set
    # otp_dev_mode=false and wire an SMS provider for production.
    otp_dev_mode: bool = True
    otp_dev_code: str = '999999'
    otp_length: int = 6
    otp_ttl_seconds: int = 300            # OTP valid for 5 minutes
    otp_max_attempts: int = 5             # wrong-code attempts before lockout
    otp_resend_cooldown_seconds: int = 30 # min gap between OTP requests

    # --- Invitations (signup links) ---
    invite_ttl_hours: int = 72
    # Base URL the signup link points at (the Flutter web app).
    app_base_url: str = 'http://localhost:8550'

    model_config = {
        'env_file': '.env',
        'extra': 'ignore'
    }

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ('production', 'prod', 'staging')

settings = Settings()
