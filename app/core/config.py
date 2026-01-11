import os

from pydantic_settings import BaseSettings
from pydantic_settings import SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file_encoding="utf-8")
    API_V1_STR: str = "/api/v1"
    PROJECT_NAME: str = "SailingRoutes"


class DevSettings(Settings):
    model_config = SettingsConfigDict(env_file=".env.dev", env_file_encoding="utf-8")
    SQLALCHEMY_DATABASE_URI: str
    DEBUG: bool = True


class ProdSettings(Settings):
    SQLALCHEMY_DATABASE_URI: str
    DEBUG: bool = False


class TestSettings(Settings):
    SQLALCHEMY_DATABASE_URI: str = "sqlite+aiosqlite:///:memory:"
    DEBUG: bool = True


env = os.getenv("ENV_TYPE", "development")
if env == "production":
    settings = ProdSettings()
elif env == "test":
    settings = TestSettings()
else:
    settings = DevSettings()

print(f"Environment: {env}, Settings: {type(settings).__name__}")