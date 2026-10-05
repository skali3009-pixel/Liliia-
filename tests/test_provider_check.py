import asyncio

import httpx

from services.provider_check import check_anthropic


def probe(env, responder):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(responder)) as client:
            return await check_anthropic(env, client)
    return asyncio.run(run())


def test_rejected_key_is_not_exposed_and_stops_second_request():
    calls = []
    def responder(request):
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "secret-value", "type": "authentication_error"}})
    result = probe({"ANTHROPIC_API_KEY": "secret-value"}, responder)
    assert "secret-value" not in str(result)
    assert len(calls) == 1
    assert result["models"]["VISION_MODEL"]["status"] == "authentication_rejected"


def test_both_models_are_checked_without_generating_messages():
    calls = []
    def responder(request):
        calls.append(request)
        return httpx.Response(200, json={"id": request.url.path.split("/")[-1]})
    result = probe({"ANTHROPIC_API_KEY": "private", "VISION_MODEL": "sonnet", "BUILD_MODEL": "opus"}, responder)
    assert len(calls) == 2
    assert all(r.method == "GET" and r.url.path.startswith("/v1/models/") for r in calls)
    assert all(m["status"] == "available" for m in result["models"].values())


def test_missing_key_does_not_call_provider():
    def responder(request):
        raise AssertionError("No network expected")
    assert probe({}, responder)["status"] == "missing_key"


def test_transport_exception_does_not_leak_details():
    def responder(request):
        raise httpx.ConnectError("private-key-in-error", request=request)
    result = probe({"ANTHROPIC_API_KEY": "private"}, responder)
    assert "private" not in str(result)
    assert result["models"]["VISION_MODEL"]["status"] == "connection_failed"
