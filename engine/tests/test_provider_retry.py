from __future__ import annotations

import http.client
import json
import unittest
import urllib.request
from unittest import mock

from shellslatee_engine import providers
from shellslatee_engine.providers import Provider

PROVIDER = Provider(
    name="test",
    base_url="https://example.invalid/v1",
    api_key_env="TEST_KEY",
    default_model="test-model",
    api_key_file=None,
)


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc) -> None:
        return None


def _payload(text: str = '{"ok": true}') -> bytes:
    return json.dumps(
        {
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 3},
        }
    ).encode()


class RetryTest(unittest.TestCase):
    def test_remote_disconnect_is_retried(self) -> None:
        calls: list[int] = []

        def fake_urlopen(request, timeout=None):
            calls.append(1)
            if len(calls) < 3:
                raise http.client.RemoteDisconnected("Remote end closed connection")
            return _Response(_payload())

        with mock.patch.object(urllib.request, "urlopen", fake_urlopen), mock.patch.object(
            providers.time, "sleep", lambda _s: None
        ):
            content, tokens = providers.chat(PROVIDER, "m", "k", [{"role": "user", "content": "hi"}])

        self.assertEqual(content, '{"ok": true}')
        self.assertEqual(tokens, {"in": 7, "out": 3})
        self.assertEqual(len(calls), 3, "two transport resets then a success")

    def test_connection_reset_gives_up_after_max_retries(self) -> None:
        calls: list[int] = []

        def always_reset(request, timeout=None):
            calls.append(1)
            raise ConnectionResetError(104, "Connection reset by peer")

        with mock.patch.object(urllib.request, "urlopen", always_reset), mock.patch.object(
            providers.time, "sleep", lambda _s: None
        ):
            with self.assertRaises(providers.ProviderError):
                providers.chat(PROVIDER, "m", "k", [{"role": "user", "content": "hi"}])

        self.assertEqual(len(calls), providers.MAX_RETRIES + 1)


if __name__ == "__main__":
    unittest.main()
