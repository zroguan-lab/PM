import asyncio
import io
import json
import unittest

from pm_btc.trusted_dns import TrustedDnsResolver


class Response:
    def __init__(self, payload):
        self.body = io.BytesIO(json.dumps(payload).encode())

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def read(self):
        return self.body.read()


class TrustedDnsTests(unittest.TestCase):
    def test_websocket_target_preserves_tls_hostname_and_rotates_addresses(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, request.headers.get("Accept"), timeout))
            return Response({
                "Status": 0,
                "Answer": [
                    {"type": 1, "data": "104.18.34.205", "TTL": 60},
                    {"type": 1, "data": "172.64.153.51", "TTL": 60},
                ],
            })

        resolver = TrustedDnsResolver(opener=opener)
        first = asyncio.run(resolver.resolve_websocket(
            "wss://ws-live-data.polymarket.com"
        ))
        second = asyncio.run(resolver.resolve_websocket(
            "wss://ws-live-data.polymarket.com"
        ))
        self.assertEqual(first.address, "104.18.34.205")
        self.assertEqual(second.address, "172.64.153.51")
        self.assertEqual(len(calls), 1, "the DNS answer should be cached for its TTL")
        self.assertEqual(first.connection_kwargs(), {
            "host": "104.18.34.205",
            "port": 443,
            "server_hostname": "ws-live-data.polymarket.com",
            "proxy": None,
        })

    def test_private_or_non_address_answers_are_rejected(self):
        def opener(*_args, **_kwargs):
            return Response({
                "Status": 0,
                "Answer": [
                    {"type": 1, "data": "127.0.0.1", "TTL": 60},
                    {"type": 5, "data": "alias.example", "TTL": 60},
                ],
            })

        resolver = TrustedDnsResolver(opener=opener)
        with self.assertRaisesRegex(RuntimeError, "no public IPv4"):
            asyncio.run(resolver.resolve_websocket("wss://example.com/socket"))


if __name__ == "__main__":
    unittest.main()
