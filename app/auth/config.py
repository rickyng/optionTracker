import secrets

from pydantic_settings import BaseSettings


class AuthSettings(BaseSettings):
    google_client_id: str = ""
    google_client_secret: str = ""
    oauth_redirect_url: str = ""
    session_secret: str = ""
    session_max_age_seconds: int = 7 * 24 * 3600  # 7 days
    allowed_emails: str = ""  # comma-separated allowlist; empty = any Google account
    internal_api_key: str = ""

    model_config = {"env_prefix": "IBKR_", "env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context):
        if not self.session_secret:
            self.session_secret = secrets.token_urlsafe(32)
        if not self.internal_api_key:
            self.internal_api_key = secrets.token_urlsafe(32)


auth_settings = AuthSettings()
