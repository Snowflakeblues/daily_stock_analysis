"""Persist encrypted OAuth records on the owner's existing HTTPS VPS."""
import asyncio
import json
import urllib.request
from key_value.aio.stores.base import BaseStore
from provider import NoRedirect

STATE_URL = "https://assets.stock-frankhong.com/internal/oauth-state"
MAX_BYTES = 262144


class RemoteOAuthStore(BaseStore):
    def __init__(self, api_key=None, *, rpc=None):
        super().__init__(stable_api=True)
        if rpc is None and (not api_key or len(api_key) < 32):
            raise RuntimeError("Configure OAUTH_STATE_API_KEY securely.")
        self._api_key = api_key
        self._rpc = rpc or self._request

    def _request(self, payload):
        request = urllib.request.Request(STATE_URL,
            data=json.dumps(payload, separators=(",", ":")).encode(),
            headers={"Authorization": "Bearer " + self._api_key,
                     "Content-Type": "application/json", "Accept": "application/json"}, method="POST")
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
                raw = response.read(MAX_BYTES + 1)
                if len(raw) > MAX_BYTES or not response.headers.get("Content-Type", "").startswith("application/json"):
                    raise ValueError()
                data = json.loads(raw)
                if data.get("ok") is not True:
                    raise ValueError()
                return data
        except Exception:
            # No URL, key, OAuth value or remote exception detail in application logs.
            raise RuntimeError("Persistent OAuth storage unavailable.") from None

    async def check(self):
        await asyncio.to_thread(self._rpc, {"op": "health"})

    async def _get_managed_entry(self, *, key, collection):
        result = await asyncio.to_thread(self._rpc, {"op": "get", "key": key, "collection": collection})
        return self._serialization_adapter.load_json(result["entry"]) if result["entry"] is not None else None

    async def _put_managed_entry(self, *, key, collection, managed_entry):
        await asyncio.to_thread(self._rpc, {"op": "put", "key": key, "collection": collection,
            "entry": self._serialization_adapter.dump_json(managed_entry),
            "expires_at": managed_entry.expires_at.timestamp() if managed_entry.expires_at else None})

    async def _delete_managed_entry(self, *, key, collection):
        result = await asyncio.to_thread(self._rpc, {"op": "delete", "key": key, "collection": collection})
        return result["deleted"]
