# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

class Settings(BaseSettings):
    PROJECT_NAME: str = "Banking AI Agent"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./backend_demo.db"  # Defaults to SQLite for testing; overridden by Postgres in Docker
    DEFAULT_DEMO_USER_ID: str = "usr_demo_01"

    @field_validator('DATABASE_URL', mode='before')
    @classmethod
    def use_installed_postgres_driver(cls, value):
        # Neon supplies a standard PostgreSQL URL. Pin our installed psycopg2
        # driver instead of relying on SQLAlchemy's version-dependent default.
        if isinstance(value, str):
            for prefix in ('postgresql://', 'postgres://'):
                if value.startswith(prefix):
                    return 'postgresql+psycopg2://' + value[len(prefix):]
        return value
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
