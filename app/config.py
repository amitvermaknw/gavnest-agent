from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gcp_project_id: str
    gcp_location: str="us-central1"

    firebase_project_id: str

    # PostgreSQL checkpointer (Cloud SQL or local for dev)
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/gavnest"

    #CORS
    frontend_url: str = "http://localhost:3000"

    #For tracing
    langchain_tracing_v2: bool = False
    langchain_api_key: str = ""
    langchain_project: str = "gavnest"

    #Rate Limit
    rate_limit_per_minute: int = 20

    #LLM Model
    vertex_model: str = ""

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.frontend_url.split(",")]
    

@lru_cache
def get_setting() -> Settings:
    """Cached singleton- safe to call from anywhere"""
    return Settings()