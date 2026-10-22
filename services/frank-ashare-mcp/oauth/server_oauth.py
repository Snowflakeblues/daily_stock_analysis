"""OAuth-protected personal valuation service. Only the configured owner may read."""
import base64
import hashlib
import json
import logging
import os
from pathlib import Path

from cryptography.fernet import Fernet
from fastmcp import FastMCP
from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.github import GitHubTokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.tools import ToolResult
from key_value.aio.stores.filetree import FileTreeStore
from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
from starlette.responses import HTMLResponse, JSONResponse

from provider import SnapshotError, fetch_snapshot

BASE_URL = "https://frank-ashare-mcp.onrender.com"
OWNER_GITHUB_ID = "235202824"  # Verified public ID of Snowflakeblues; names can change.
SCOPES = ["read:user"]
CLIENT_REDIRECTS = [
    "https://chatgpt.com/connector_platform_oauth_redirect",
    "https://chatgpt.com/connector/oauth/*",
    # Codex desktop receives its authorization code on an ephemeral loopback port.
    # FastMCP validates URL components, registered paths and PKCE separately.
    "http://127.0.0.1:*/callback",
    "http://127.0.0.1:*/callback/*",
]


def required_secret(name: str, minimum: int = 1) -> str:
    value = os.environ.get(name, "").strip()
    # Render also mounts dashboard Secret Files here; never log their contents.
    if not value and name in {"GITHUB_OAUTH_CLIENT_SECRET", "ASHARE_ASSET_API_KEY"}:
        try:
            value = (Path("/etc/secrets") / name).read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            pass
        except (OSError, UnicodeError):
            raise RuntimeError(f"Unable to read the configured {name} secret file.") from None
    if len(value) < minimum or not value.isascii() or any(c.isspace() for c in value):
        raise RuntimeError(f"Configure {name} securely (minimum {minimum} ASCII characters, no whitespace).")
    return value


class OwnerGitHubVerifier(GitHubTokenVerifier):
    """Used only behind OAuthProxy, which verifies its own downstream tokens."""
    async def verify_token(self, token):
        access = await super().verify_token(token)
        if access is None or str(access.claims.get("sub", "")) != OWNER_GITHUB_ID:
            return None
        return access


def valuation_result(access, provider_key: str) -> ToolResult:
    # Defense in depth even for direct/in-process calls that bypass HTTP middleware.
    if access is None or str(access.claims.get("sub", "")) != OWNER_GITHUB_ID:
        return ToolResult(
            content="Connect the owner's GitHub account before reading private valuation data.",
            is_error=True,
            meta={"mcp/www_authenticate": f'Bearer resource_metadata="{BASE_URL}/.well-known/oauth-protected-resource/mcp", scope="read:user"'},
        )
    try:
        data = fetch_snapshot(provider_key)
    except SnapshotError as exc:
        return ToolResult(content=str(exc), is_error=True)
    except Exception:
        return ToolResult(content="Private valuation request failed; no snapshot returned.", is_error=True)
    return ToolResult(
        content=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        structured_content=data,
    )


class NoStoreMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def add_headers(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = list(message.get("headers", [])) + [(b"cache-control", b"no-store")]
            await send(message)
        await self.app(scope, receive, add_headers if scope["type"] == "http" else send)


def create_mcp(*, storage=None):
    client_id = required_secret("GITHUB_OAUTH_CLIENT_ID")
    client_secret = required_secret("GITHUB_OAUTH_CLIENT_SECRET")
    provider_key = required_secret("ASHARE_ASSET_API_KEY")
    signing_key = required_secret("OAUTH_SIGNING_KEY", minimum=32).encode("ascii")
    if len({client_secret, provider_key, signing_key.decode()}) != 3:
        raise RuntimeError("Use distinct OAuth, provider, and signing credentials.")

    if storage is None:
        state_directory = os.environ.get("OAUTH_STATE_DIR", "").strip()
        if not state_directory:
            raise RuntimeError("Set OAUTH_STATE_DIR to a private server-side state directory.")
        state_path = Path(state_directory)
        state_path.mkdir(parents=True, exist_ok=True)
        try:
            state_path.chmod(0o700)
        except OSError:
            raise RuntimeError("Unable to protect the OAuth state directory.") from None
        storage = FileTreeStore(data_directory=state_path)
    encrypted_storage = FernetEncryptionWrapper(
        key_value=storage,
        fernet=Fernet(base64.urlsafe_b64encode(hashlib.sha256(signing_key + b"/oauth-state/v1").digest())),
    )

    auth = OAuthProxy(
        upstream_authorization_endpoint="https://github.com/login/oauth/authorize",
        upstream_token_endpoint="https://github.com/login/oauth/access_token",
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=OwnerGitHubVerifier(required_scopes=SCOPES),
        base_url=BASE_URL,
        issuer_url=BASE_URL,
        redirect_path="/auth/callback",
        allowed_client_redirect_uris=CLIENT_REDIRECTS,
        valid_scopes=SCOPES,
        forward_pkce=True,
        # GitHub does not implement RFC 8707; the proxy validates its own audience.
        forward_resource=False,
        token_endpoint_auth_method="client_secret_post",
        jwt_signing_key=signing_key,
        client_storage=encrypted_storage,
        require_authorization_consent=True,
        fastmcp_access_token_expiry_seconds=900,
        fallback_refresh_token_expiry_seconds=86400,
        enable_cimd=True,
    )
    mcp = FastMCP(
        "Frank A-share valuation", version="0.3.1", auth=auth,
        instructions="Read-only configured A-share closing snapshots. Preserve all source fields and decimal strings. Verify valuation_date, freshness, usable_for_current_report, holdings and coverage before reporting current values.",
        mask_error_details=True, strict_input_validation=True,
    )

    @mcp.tool(
        name="get_ashare_valuation", title="��ȡ A �����̹�ֵ",
        annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True},
        meta={"securitySchemes": [{"type": "oauth2", "scopes": SCOPES}]},
    )
    def get_ashare_valuation() -> ToolResult:
        """Read the owner's latest dated A-share closing snapshot. No arguments. Check valuation_date, freshness, usable_for_current_report, holdings confirmation and coverage. Amounts are decimal strings in CNY; excludes cash and US holdings."""
        return valuation_result(get_access_token(), provider_key)

    @mcp.custom_route("/health", methods=["GET"])
    async def health(request):
        return JSONResponse({"status": "ok", "service": "frank-ashare-mcp", "auth": "oauth"})

    @mcp.custom_route("/", methods=["GET"])
    async def homepage(request):
        return HTMLResponse(
            '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>Frank A�ɹ�ֵ</title><main style="max-width:640px;margin:60px auto;padding:20px;font:18px/1.8 sans-serif">'
            '<h1>Frank A�ɹ�ֵ</h1><p>˽��ֻ�����̹�ֵ����</p>'
            '<p>��� ChatGPT �����������ڷ��� GitHub ��¼��Ȩ������ֻ���������õĳ������˺Ŷ�ȡ��ֵ��</p>'
            '<p>�ʲ��ӿ���Կ�ɷ�������ȫ���ã���ҳ��������Կ��</p></main></html>',
            headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'", "X-Content-Type-Options": "nosniff"},
        )
    return mcp


def create_app(*, storage=None):
    mcp = create_mcp(storage=storage)
    app = mcp.http_app(
        path="/mcp", json_response=True, stateless_http=True,
        host_origin_protection=True,
        allowed_hosts=["frank-ashare-mcp.onrender.com"],
        allowed_origins=[BASE_URL, "https://chatgpt.com"],
    )
    app.add_middleware(NoStoreMiddleware)
    return app


if __name__ == "__main__":
    import uvicorn
    logging.getLogger("fastmcp").setLevel(logging.WARNING)
    logging.getLogger("httpx2").setLevel(logging.WARNING)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), access_log=False)
