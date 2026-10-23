import asyncio
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from remote_store import RemoteOAuthStore
from state_service import StateApplication, STATE_PATH
from test_oauth import HTTPChecks, ENV, SNAPSHOT, owner_token
import server_oauth as server

KEY = "offline-storage-key-which-is-at-least-32-characters"


def rpc_for(app, key=KEY):
    def rpc(data):
        raw = json.dumps(data).encode()
        env = {"PATH_INFO": STATE_PATH, "REQUEST_METHOD": "POST", "CONTENT_TYPE": "application/json",
               "CONTENT_LENGTH": str(len(raw)), "HTTP_AUTHORIZATION": "Bearer " + key, "wsgi.input": io.BytesIO(raw)}
        statuses = []
        result = json.loads(b"".join(app(env, lambda status, headers: statuses.append(status))))
        if statuses != ["200 OK"]:
            raise RuntimeError(statuses[0])
        return result
    return rpc


class PersistenceChecks(HTTPChecks):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dbpath = Path(self.tmp.name) / "state.sqlite3"
        self.env = patch.dict("os.environ", ENV)
        self.env.start()
        self.reopen()

    def reopen(self):
        self.app = StateApplication(self.dbpath, hashlib.sha256(KEY.encode()).hexdigest())
        store = RemoteOAuthStore(rpc=rpc_for(self.app))
        self.client = TestClient(server.create_app(storage=store), base_url=server.BASE_URL)
        self.client.__enter__()

    def tearDown(self):
        super().tearDown()
        self.tmp.cleanup()

    def test_oauth_grant_survives_app_and_database_restart(self):
        self.upstream_tokens = {"access_token":"offline-upstream-token", "refresh_token":"offline-upstream-refresh", "scope":"read:user", "token_type":"Bearer", "expires_in":3600}
        grant = self.authorize_offline()
        self.client.__exit__(None, None, None)
        self.reopen()
        tokens = self.client.post("/token", data=grant)
        self.assertEqual(tokens.status_code, 200, tokens.text)
        old_refresh = tokens.json()["refresh_token"]
        access = tokens.json()["access_token"]
        self.client.__exit__(None, None, None)
        self.reopen()
        with patch.object(server.GitHubTokenVerifier, "verify_token", new=AsyncMock(return_value=owner_token())):
            with patch("server_oauth.fetch_snapshot", return_value=copy.deepcopy(SNAPSHOT)):
                response = self.client.post("/mcp", headers={"Authorization": "Bearer " + access, "Accept": "application/json, text/event-stream"}, json={"jsonrpc":"2.0", "id":1, "method":"tools/call", "params":{"name":"get_ashare_valuation", "arguments":{}}})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["result"]["structuredContent"], SNAPSHOT)
            with patch("fastmcp.server.auth.oauth_proxy.proxy.AsyncOAuth2Client.refresh_token", new=AsyncMock(return_value=self.upstream_tokens)):
                refreshed = self.client.post("/token", data={"grant_type":"refresh_token", "client_id":grant["client_id"], "refresh_token":old_refresh})
            self.assertEqual(refreshed.status_code, 200, refreshed.text)
        self.assertNotIn(b"offline-upstream-token", self.dbpath.read_bytes())
        self.assertNotIn(b"offline-upstream-token", Path(str(self.dbpath)+"-wal").read_bytes() if Path(str(self.dbpath)+"-wal").exists() else b"")

    def test_github_without_refresh_token_has_bounded_week_session(self):
        grant = self.authorize_offline()
        self.client.__exit__(None, None, None)
        self.reopen()
        response = self.client.post("/token", data=grant)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["expires_in"], 7 * 86400)
        self.assertFalse(response.json().get("refresh_token"))

    def test_storage_auth_plaintext_rejection_and_namespaces(self):
        with self.assertRaisesRegex(RuntimeError, "401"):
            rpc_for(self.app, "wrong")({"op":"health"})
        with self.assertRaisesRegex(RuntimeError, "400"):
            rpc_for(self.app)({"op":"put", "key":"x", "collection":"c", "entry":json.dumps({"value":{"token":"plaintext"}})})
        with self.assertRaisesRegex(RuntimeError, "400"):
            rpc_for(self.app)({"op":"list"})

    def test_storage_expiry_and_delete(self):
        from cryptography.fernet import Fernet
        from key_value.aio.wrappers.encryption import FernetEncryptionWrapper
        store = FernetEncryptionWrapper(RemoteOAuthStore(rpc=rpc_for(self.app)), fernet=Fernet(Fernet.generate_key()))
        async def exercise():
            await store.put("same", {"v":1}, collection="a")
            await store.put("same", {"v":2}, collection="b")
            self.assertEqual(await store.get("same", collection="a"), {"v":1})
            self.assertEqual(await store.get("same", collection="b"), {"v":2})
            self.assertTrue(await store.delete("same", collection="a"))
            self.assertFalse(await store.delete("same", collection="a"))
            await store.put("old", {"v":3}, ttl=0.001)
            await asyncio.sleep(0.01)
            self.assertIsNone(await store.get("old"))
        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
