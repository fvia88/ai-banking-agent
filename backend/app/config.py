# backend/app/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "Banking AI Agent"
    API_V1_PREFIX: str = "/api/v1"
    DATABASE_URL: str = "sqlite:///./backend_demo.db"  # Defaults to SQLite for testing; overridden by Postgres in Docker
    DEFAULT_DEMO_USER_ID: str = "usr_demo_01"
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()