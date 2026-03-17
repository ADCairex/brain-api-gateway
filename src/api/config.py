from pydantic_settings import BaseSettings

PUBLIC_PATHS = [
    "/login",
    "/register",
    "/refresh",
]

SERVICE_MAP = {
    "/auth":    "http://brain-auth-service:8001",
    "/finance": "http://brain-finance-service:8002",
}


class Settings(BaseSettings):
    secret_key: str
    service_auth_url: str = "http://brain-auth-service:8001"
    service_finance_url: str = "http://brain-finance-service:8002"
    port: int = 8000
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    model_config = {"env_file": ".env"}


settings = Settings()
