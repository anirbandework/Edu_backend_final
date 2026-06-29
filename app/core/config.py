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

    model_config = {
        'env_file': '.env',
        'extra': 'ignore'
    }

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in ('production', 'prod', 'staging')

    @property
    def otp_dev_mode_active(self) -> bool:
        """Whether the DEV OTP path is active — i.e. every code is the fixed
        ``otp_dev_code`` ('999999'), logged instead of SMS'd, and echoed in the response.

        ⚠️ TEMPORARY (product decision 2026-06-30): the dev OTP is intentionally kept ON
        in EVERY environment, including production, because no SMS provider is wired yet
        and the team wants the constant 999999 to work in prod too for now. This is a
        known account-takeover risk (anyone who knows a phone can reset that password).
        **Before public launch, restore the production gate**:
        ``return self.otp_dev_mode and not self.is_production`` and integrate an SMS provider.
        Single switch-point so re-hardening is a one-line change."""
        return self.otp_dev_mode

settings = Settings()
