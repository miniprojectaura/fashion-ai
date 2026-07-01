from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_secret_key: str = "dev-secret-change-in-production"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:3000,http://localhost:8080"

    database_url: str = "sqlite+aiosqlite:///./fashionai.db"
    redis_url: str = "redis://localhost:6379/0"

    groq_api_key: str = ""
    huggingface_api_key: str = ""
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""

    # Optional hosted DB/auth — not required; SQLite + guest JWT work without card
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_jwt_secret: str = ""

    # local | minio — never cloudflare R2 (requires card)
    storage_backend: str = "local"
    storage_local_path: str = "./storage"

    litellm_proxy_url: str = "http://localhost:4000"
    ollama_base_url: str = "http://localhost:11434"
    llm_primary_model: str = "groq/llama-3.3-70b-versatile"
    llm_fast_model: str = "groq/llama-3.1-8b-instant"
    llm_fallback_model: str = "ollama/llama3.2"

    hf_inference_url: str = "https://api-inference.huggingface.co"
    fashionclip_model: str = "patrickjohncyh/fashion-clip"
    photo_retention_days: int = 30

    # Sarvam AI — voice (ASR Saarika + TTS Bulbul)
    sarvam_api_key: str = ""

    # Stylist persona model — change this one var post-finetune
    llm_stylist_model: str = "groq/llama-3.3-70b-versatile"

    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    rate_limit_user_rpm: int = 30
    rate_limit_ip_rpm: int = 100

    s3_endpoint: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "fashion-ai"

    # Observability — Langfuse (free: 50K observations/month)
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "https://cloud.langfuse.com"

    # Analytics — PostHog (free: 1M events/month)
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"

    # Push Notifications — Firebase
    firebase_server_key: str = ""

    # VLM models
    vlm_primary_model: str = "llama-3.2-90b-vision-preview"
    vlm_fallback_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
