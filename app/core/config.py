import os

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "SailingRoutes"


class DevSettings(Settings):
    SQLALCHEMY_DATABASE_URI: str
    DEBUG: bool


class ProdSettings(Settings):
    SQLALCHEMY_DATABASE_URI: str
    DEBUG: bool


class TestSettings(Settings):
    SQLALCHEMY_DATABASE_URI: str = "sqlite+aiosqlite:///:memory:"
    DEBUG: bool = True


env = os.getenv("ENV_TYPE", "development")
if env == "production":
    settings = ProdSettings()
if env == "test":
    settings = TestSettings()
else:
    settings = DevSettings(_env_file=".env.dev", _env_file_encoding="utf-8")

print("Current settings:", settings)
