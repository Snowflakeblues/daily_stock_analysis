"""Offline contract checks. No real credentials, provider login or private assets."""
import copy
import hashlib
import base64
import os
import re
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlencode, urlparse

from fastmcp.server.auth.auth import AccessToken
from key_value.aio.stores.memory import MemoryStore
from starlette.testclient import TestClient

import server_oauth as server

ENV = {
    "GITHUB_OAUTH_CLIENT_ID": "offline-client-id",
    "GITHUB_OAUTH_CLIENT_SECRET": "offline-client-secret",
    "ASHARE_ASSET_API_KEY": "offline-asset-key",
    "OAUTH_SIGNING_KEY": "offline-signing-material-000000000000000000000000",
}
SNAPSHOT = {
    "valuation_date": "2000-01-04", "freshness": "stale", "usable_for_current_report": False,
    "positions": [{"quantity_shares": "100", "close_price_cny": "1.2300"}],
    "totals": {"a_share_market_value_cny": "123.00", "unrealized_pnl_cny": None},
    "coverage": {"complete_for_all_assets": False, "not_included": ["cash", "US holdings"]},
}


def owner_token(user_id=server.OWNER_GITHUB_ID):
    return AccessToken(token="offline-github-token", client_id=str(user_id), subject=str(user_id), scopes=server.SCOPES, claims={"sub": str(user_id), "login": "Snowflakeblues"})


class OwnerChecks(unittest.IsolatedAsyncioTestCase):
    async def test_only_the_fixed_github_id_passes(self):
        verifier = server.OwnerGitHubVerifier(required_scopes=server.SCOPES)
        for upstream_result, allowed in ((None, False), (owner_token("999"), False), (owner_token(), True)):
            with patch.object(server.GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=upstream_result)):
                result = await verifier.verify_token("offline-test")
            self.assertEqual(result is not None, allowed)


class DataChecks(unittest.TestCase):
    def test_no_data_fetch_before_owner_authorization(self):
        for token in (None, owner_token("999")):
            with patch("server_oauth.fetch_snapshot") as fetch:
                result = server.valuation_result(token, "offline-asset-key")
            self.assertTrue(result.is_error)
            self.assertIn("mcp/www_authenticate", result.meta)
            fetch.assert_not_called()

    def test_snapshot_is_preserved_and_only_server_key_is_used(self):
        with patch("server_oauth.fetch_snapshot", return_value=copy.deepcopy(SNAPSHOT)) as fetch:
            result = server.valuation_result(owner_token(), "offline-asset-key")
        fetch.assert_called_once_with("offline-asset-key")
        self.assertEqual(result.structured_content, SNAPSHOT)
        self.assertFalse(result.structured_content["usable_for_current_report"])
        self.assertNotIn("offline-github-token", result.content[0].text)

    def test_errors_do_not_leak_unexpected_exception_details(self):
        with patch("server_oauth.fetch_snapshot", side_effect=RuntimeError("do-not-disclose-this-key")):
            result = server.valuation_result(owner_token(), "offline-asset-key")
        self.assertTrue(result.is_error)
        self.assertNotIn("do-not-disclose", result.content[0].text)


class SecretFileChecks(unittest.TestCase):
    def test_render_secret_file_is_supported_without_disclosure(self):
        for name in ("GITHUB_OAUTH_CLIENT_SECRET", "ASHARE_ASSET_API_KEY"):
            with patch.dict(os.environ, {name: ""}):
                with patch.object(server.Path, "read_text", return_value="offline-file-secret\n") as read:
                    self.assertEqual(server.required_secret(name), "offline-file-secret")
                    read.assert_called_once_with(encoding="utf-8")

    def test_environment_variable_takes_precedence(self):
        with patch.dict(os.environ, {"GITHUB_OAUTH_CLIENT_SECRET": "offline-env-secret"}):
            with patch.object(server.Path, "read_text") as read:
                self.assertEqual(server.required_secret("GITHUB_OAUTH_CLIENT_SECRET"), "offline-env-secret")
                read.assert_not_called()

    def test_missing_invalid_and_unreadable_files_fail_closed(self):
        with patch.dict(os.environ, {"GITHUB_OAUTH_CLIENT_SECRET": ""}):
            for failure in (FileNotFoundError(), PermissionError("private-detail"), UnicodeError("private-detail")):
                with patch.object(server.Path, "read_text", side_effect=failure):
                    with self.assertRaises(RuntimeError) as error:
                        server.required_secret("GITHUB_OAUTH_CLIENT_SECRET")
                    self.assertNotIn("private-detail", str(error.exception))
            with patch.object(server.Path, "read_text", return_value="invalid secret"):
                with self.assertRaises(RuntimeError):
                    server.required_secret("GITHUB_OAUTH_CLIENT_SECRET")


class HTTPChecks(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, ENV)
        self.env.start()
        self.client = TestClient(server.create_app(storage=MemoryStore()), base_url=server.BASE_URL)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.env.stop()

    def test_health_has_no_private_snapshot(self):
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["auth"], "oauth")
        self.assertNotIn("positions", response.text)
        self.assertIn("no-store", response.headers["cache-control"])

    def test_oauth_discovery_and_pkce(self):
        response = self.client.get("/.well-known/oauth-authorization-server")
        self.assertEqual(response.status_code, 200)
        metadata = response.json()
        self.assertEqual(metadata["issuer"], server.BASE_URL + "/")
        self.assertIn("S256", metadata["code_challenge_methods_supported"])
        self.assertEqual(metadata["authorization_endpoint"], server.BASE_URL + "/authorize")
        response = self.client.get("/.well-known/oauth-protected-resource/mcp")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["resource"], server.BASE_URL + "/mcp")

    def test_missing_and_fake_tokens_cannot_call_tools(self):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_ashare_valuation", "arguments": {}}}
        with patch("server_oauth.fetch_snapshot") as fetch:
            for headers in ({}, {"Authorization": "Bearer not-a-real-token"}):
                response = self.client.post("/mcp", json=message, headers=headers)
                self.assertEqual(response.status_code, 401)
                self.assertIn("resource_metadata=", response.headers["www-authenticate"])
        fetch.assert_not_called()

    def register_client(self, redirect):
        response = self.client.post("/register", json={
            "client_name": "Offline ChatGPT test", "redirect_uris": [redirect],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"], "token_endpoint_auth_method": "none", "scope": "read:user",
        })
        return response

    def test_redirect_allowlist_and_consent_page(self):
        self.assertGreaterEqual(self.register_client("https://attacker.invalid/callback").status_code, 400)
        redirect = server.CLIENT_REDIRECTS[0]
        registered = self.register_client(redirect)
        self.assertEqual(registered.status_code, 201, registered.text)
        verifier = "v" * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {"client_id": registered.json()["client_id"], "redirect_uri": redirect,
                  "response_type": "code", "state": "offline-client-state", "scope": "read:user",
                  "resource": server.BASE_URL + "/mcp", "code_challenge_method": "S256", "code_challenge": challenge}
        response = self.client.get("/authorize?" + urlencode(params), follow_redirects=False)
        self.assertEqual(response.status_code, 302, response.text)
        consent_url = response.headers["location"]
        self.assertEqual(urlparse(consent_url).hostname, "frank-ashare-mcp.onrender.com")
        response = self.client.get(consent_url, follow_redirects=False)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("consent", response.text.lower())

    def test_startup_requires_all_distinct_credentials(self):
        for name in ENV:
            with patch.dict(os.environ, {name: ""}), self.assertRaises(RuntimeError):
                server.create_app(storage=MemoryStore())
        with patch.dict(os.environ, {"GITHUB_OAUTH_CLIENT_SECRET": ENV["ASHARE_ASSET_API_KEY"]}), self.assertRaises(RuntimeError):
            server.create_app(storage=MemoryStore())

    def authorize_offline(self):
        redirect = server.CLIENT_REDIRECTS[0]
        registered = self.register_client(redirect).json()
        verifier = "p" * 43
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        params = {"client_id": registered["client_id"], "redirect_uri": redirect, "response_type": "code",
                  "state": "offline-state", "scope": "read:user", "resource": server.BASE_URL + "/mcp",
                  "code_challenge_method": "S256", "code_challenge": challenge}
        initial = self.client.get("/authorize?" + urlencode(params), follow_redirects=False)
        consent_url = initial.headers["location"]
        consent = self.client.get(consent_url)
        fields = dict(re.findall(r'name="([^"]+)" value="([^"]*)"', consent.text))
        fields["action"] = "approve"
        upstream = self.client.post(consent_url, data=fields, follow_redirects=False)
        self.assertEqual(upstream.status_code, 302, upstream.text)
        upstream_url = urlparse(upstream.headers["location"])
        self.assertEqual(upstream_url.hostname, "github.com")
        upstream_params = parse_qs(upstream_url.query)
        self.assertEqual(upstream_params["scope"], ["read:user"])
        self.assertNotIn("repo", upstream_params["scope"][0])
        fake_tokens = {"access_token": "offline-upstream-token", "token_type": "Bearer", "scope": "read:user", "expires_in": 3600}
        with patch("fastmcp.server.auth.oauth_proxy.upstream.AsyncOAuth2Client.fetch_token", new=AsyncMock(return_value=fake_tokens)):
            callback = self.client.get("/auth/callback?" + urlencode({"code": "offline-github-code", "state": upstream_params["state"][0]}), follow_redirects=False)
        self.assertEqual(callback.status_code, 302, callback.text)
        forwarded = urlparse(callback.headers["location"])
        self.assertEqual(forwarded.scheme + "://" + forwarded.netloc + forwarded.path, redirect)
        returned = parse_qs(forwarded.query)
        self.assertEqual(returned["state"], ["offline-state"])
        self.assertEqual(returned["iss"], [server.BASE_URL + "/"])
        return {"grant_type": "authorization_code", "client_id": registered["client_id"],
                "redirect_uri": redirect, "code": returned["code"][0], "code_verifier": verifier,
                "resource": server.BASE_URL + "/mcp"}

    def test_complete_oauth_and_tool_call_offline(self):
        grant = self.authorize_offline()
        tokens = self.client.post("/token", data=grant)
        self.assertEqual(tokens.status_code, 200, tokens.text)
        access_token = tokens.json()["access_token"]
        headers = {"Authorization": "Bearer " + access_token, "Accept": "application/json, text/event-stream"}
        with patch.object(server.GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=owner_token())):
            with patch("server_oauth.fetch_snapshot", return_value=copy.deepcopy(SNAPSHOT)) as fetch:
                response = self.client.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_ashare_valuation", "arguments": {}}}, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["result"]["structuredContent"], SNAPSHOT)
            fetch.assert_called_once_with("offline-asset-key")
        replay = self.client.post("/token", data=grant)
        self.assertGreaterEqual(replay.status_code, 400)

    def test_wrong_pkce_cannot_exchange_code(self):
        grant = self.authorize_offline()
        grant["code_verifier"] = "wrong" * 11
        response = self.client.post("/token", data=grant)
        self.assertGreaterEqual(response.status_code, 400)
        self.assertNotIn("access_token", response.json())


if __name__ == "__main__":
    unittest.main(verbosity=2)
