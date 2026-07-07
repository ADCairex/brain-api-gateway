from pydantic import field_validator
from pydantic_settings import BaseSettings

# These are full request paths that bypass gateway JWT validation because they
# belong to the auth service's public credential endpoints.
PUBLIC_AUTH_PATHS = [
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
]


class Settings(BaseSettings):
    secret_key: str
    service_auth_url: str = "http://brain-auth-service:8001"
    service_finance_url: str = "http://brain-finance-service:8002"
    service_calendar_url: str = "http://brain-calendar-service:8003"
    service_ocr_url: str = "http://brain-ocr-service:8004"
    proxy_timeout_seconds: float = 10.0
    service_ocr_timeout_seconds: float = 60.0
    port: int = 8000
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    @field_validator("proxy_timeout_seconds", "service_ocr_timeout_seconds")
    @classmethod
    def validate_timeout_seconds(cls, value: float) -> float:
        if value <= 0 or value > 300:
            raise ValueError("timeout settings must be greater than 0 and no more than 300 seconds")
        return value

    model_config = {"env_file": ".env"}


settings = Settings()

SERVICE_MAP = {
    "/auth": settings.service_auth_url,
    "/finance": settings.service_finance_url,
    "/calendar": settings.service_calendar_url,
    "/ocr": settings.service_ocr_url,
}
