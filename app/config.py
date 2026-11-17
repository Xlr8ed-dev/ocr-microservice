from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    # --- database -------------------------------------------------
    DATABASE_HOST: str = "localhost"
    DATABASE_PORT: int = 5432
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    # --- JWT (SSO-issued RS256) -----------------------------------
    JWT_JWKS_URL: str
    JWT_ISSUER: str = "sso-service"
    JWT_AUDIENCE: str = "ocr-visitor-service"
    JWT_ALGORITHM: str = "RS256"

    # --- SSO service (user + package + quota) ---------------------
    SSO_BASE_URL: str
    SSO_SERVICE_TOKEN: str
    SSO_TIMEOUT: float = 5.0

    # --- Central auth service (nexby-auth-service) -----------------
    # Base URL of the auth service, WITHOUT a trailing slash. On QA this is
    # https://qa-apis.nexby.ai/auth -- the API itself is under /api/v1.
    # Falls back to SSO_BASE_URL when unset, so an older deployment keeps
    # working unchanged.
    AUTH_SERVICE_URL: str | None = None
    AUTH_SERVICE_TIMEOUT: float = 5.0
    AUTH_SERVICE_API_PREFIX: str = "/api/v1"

    # Emails that should get SUPER_ADMIN access in this service. Comma
    # separated, case-insensitive. Everyone else is mapped from their
    # organization role: owner/admin -> ADMIN, member -> AGENT.
    SUPER_ADMIN_EMAILS: str = ""

    # Salt for the stable integer IDs derived from auth-service UUIDs. Keep
    # the same value on every instance; changing it remaps all stored rows.
    AUTH_ID_HASH_SALT: str = ""

    # --- AI service (vision, STT, summarize) ----------------------
    AI_SERVICE_URL: str
    AI_SERVICE_API_KEY: str
    AI_SERVICE_TIMEOUT: float = 120.0

    # --- Email service (stub for now) -----------------------------
    EMAIL_SERVICE_URL: str | None = None
    EMAIL_SERVICE_TOKEN: str | None = None

    # --- WhatsApp service (stub for now) --------------------------
    WHATSAPP_SERVICE_URL: str | None = None
    WHATSAPP_SERVICE_TOKEN: str | None = None

    # --- Internal callback (OCR worker -> this service) -----------
    OCR_CALLBACK_URL: str
    SERVICE_TOKEN: str

    # --- Celery ---------------------------------------------------
    CELERY_TASK_ALWAYS_EAGER: bool = False
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # --- App ------------------------------------------------------
    APP_NAME: str = "ocr-visitor-service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "local"          # local | staging | production
    AUTH_MODE: str = "jwt"              # "jwt" | "mock"
    TESSERACT_CMD: str | None = None    # path to tesseract.exe if not on PATH

    # --- Admin ----------------------------------------------------
    ADMIN_SECRET_KEY: str = "change-me-in-production"
    ADMIN_USERNAME: str = "admin"
    ADMIN_PASSWORD: str = "admin"

    # --- S3 -------------------------------------------------------
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    AWS_STORAGE_BUCKET_NAME: str
    AWS_S3_REGION_NAME: str = "ap-south-1"

    S3_PRESIGN_EXPIRES_SECONDS: int = 3600
    S3_UPLOAD_MAX_MB: int = 50

    @model_validator(mode="after")
    def _check_auth_mode(self):
        if self.ENVIRONMENT == "production" and self.AUTH_MODE == "mock":
            raise ValueError(
                "AUTH_MODE='mock' is not allowed when ENVIRONMENT='production'. "
                "Refusing to start."
            )
        return self

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://"
            f"{self.DATABASE_USER}:{self.DATABASE_PASSWORD}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/"
            f"{self.DATABASE_NAME}"
        )

    @property
    def auth_service_base_url(self) -> str:
        return (self.AUTH_SERVICE_URL or self.SSO_BASE_URL).rstrip("/")

    @property
    def auth_service_root(self) -> str:
        prefix = self.AUTH_SERVICE_API_PREFIX.strip()
        if prefix and not prefix.startswith("/"):
            prefix = "/" + prefix
        return prefix.rstrip("/")

    @property
    def super_admin_emails(self) -> set[str]:
        return {
            email.strip().lower()
            for email in self.SUPER_ADMIN_EMAILS.split(",")
            if email.strip()
        }

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
    )


settings = Settings()