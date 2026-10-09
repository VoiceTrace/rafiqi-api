from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/rafiqi"
    # Sync URL used only by Alembic (migrations run sync)
    DATABASE_URL_SYNC: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/rafiqi"

    SECRET_KEY: str = "change-me-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    ENVIRONMENT: str = "development"
    NOTIFICATION_INBOX_ENABLED: bool = True
    NOTIFICATION_PUSH_ENABLED: bool = False
    FIREBASE_PROJECT_ID: str = "rafiki-1c4d9"
    GOOGLE_APPLICATION_CREDENTIALS: str = ""
    NOTIFICATION_TOKEN_KEY: str = ""
    NOTIFICATION_WEB_ORIGIN: str = "http://localhost:3000"
    NOTIFICATION_PUSH_LIMIT: int = 10
    NOTIFICATION_PUSH_WINDOW_SECONDS: int = 600
    MEDIA_DIR: str = "media"
    RESOURCE_STORAGE_DIR: str = "private_resources"
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # LLM gateway (OpenRouter — OpenAI-compatible API, model chosen by string id
    # so the cheap-tier model can be swapped without a code change)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    CAVE_CHAT_MODEL: str = "moonshotai/kimi-k2"
    SAFETY_CLASSIFIER_MODEL: str = "moonshotai/kimi-k2"
    PROFILE_EXTRACTION_MODEL: str = "moonshotai/kimi-k2"


settings = Settings()
