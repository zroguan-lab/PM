import asyncio
import unittest

from pm_btc.connectivity import ConnectivityProbe, _http_probe, _required_groups, _websocket_probe


class HttpResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None


class WebSocket:
    def __init__(self):
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def send(self, message):
        self.sent.append(message)


class ConnectivityTests(unittest.TestCase):
    def test_http_probe_reports_ok_status(self):
        calls = []

        def getter(request, timeout):
            calls.append((request.full_url, timeout))
            return HttpResponse()

        result = asyncio.run(_http_probe("gamma", "https://example.test/ok", .5, getter))

        self.assertEqual(result.status, "OK")
        self.assertEqual(result.detail, "http_status=200")
        self.assertEqual(calls[0][0], "https://example.test/ok")

    def test_websocket_probe_reports_error_without_raising(self):
        def connector(*_args, **_kwargs):
            raise OSError("blocked")

        result = asyncio.run(_websocket_probe("ws", "wss://example.test/ws", .5, connector=connector))

        self.assertEqual(result.status, "ERROR")
        self.assertIn("blocked", result.detail)

    def test_probe_serializes_to_dict(self):
        result = ConnectivityProbe("rtds", "websocket", "wss://example.test", "OK", 10.5)

        self.assertEqual(result.to_dict()["name"], "rtds")
        self.assertEqual(result.to_dict()["status"], "OK")

    def test_required_groups_allow_endpoint_fallbacks(self):
        results = [
            {"name": "binance_spot_http:0", "status": "ERROR"},
            {"name": "binance_spot_http:1", "status": "OK"},
            {"name": "binance_futures_http:0", "status": "OK"},
            {"name": "polymarket_gamma", "status": "OK"},
            {"name": "polymarket_clob", "status": "OK"},
            {"name": "polymarket_clob_ws:direct", "status": "ERROR"},
            {"name": "polymarket_clob_ws:trusted_dns", "status": "OK"},
            {"name": "polymarket_chainlink_rtds:direct", "status": "OK"},
            {"name": "binance_spot_ws:0", "status": "TIMEOUT"},
            {"name": "binance_spot_ws:1", "status": "OK"},
            {"name": "binance_futures_public_ws:0", "status": "OK"},
        ]

        self.assertTrue(all(_required_groups(results).values()))


if __name__ == "__main__":
    unittest.main()
