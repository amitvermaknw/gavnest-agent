from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dev_mode: bool = False
    gcp_project_id: str
    gcp_location: str="us-central1"

    firebase_project_id: str

    # PostgreSQL checkpointer (Cloud SQL or local for dev)
    NEON_POSTGRESQL_DB: str

    #CORS
    frontend_url: str = "http://localhost:3000"

    #For tracing
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "gavnest"

    #Rate Limit
    rate_limit_per_minute: int = 20

    #LLM Model
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"

    #FRED api key
    fred_api_key: str

    @property
    def allowed_origins(self) -> list[str]:
        origins = [o.strip() for o in self.frontend_url.split(",")]
        # Allow file:// origin (browsers send "null") in dev mode only
        if self.dev_mode and "null" not in origins:
            origins.append("null")
        return origins
    

@lru_cache
def get_setting() -> Settings:
    """Cached singleton- safe to call from anywhere"""
    return Settings()