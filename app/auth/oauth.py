from authlib.integrations.starlette_client import OAuth

from app.auth.config import auth_settings

oauth = OAuth()

if auth_settings.google_client_id:
    oauth.register(
        name="google",
        client_id=auth_settings.google_client_id,
        client_secret=auth_settings.google_client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile", "timeout": 30},
    )
