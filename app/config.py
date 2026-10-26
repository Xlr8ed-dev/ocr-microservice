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

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        extra="ignore",
    )


settings = Settings()