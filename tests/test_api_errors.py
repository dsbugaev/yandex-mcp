"""Direct API returns errors as HTTP 200 + {"error": {...}} body.

The client must surface these instead of letting write-tools report
false success (empty UpdateResults -> "updated successfully").
"""

import json

import httpx
import pytest

from yandex_mcp.client import YandexAPIError, api_client
from yandex_mcp.utils import handle_api_error

ERROR_BODY = {
    "error": {
        "request_id": "12345",
        "error_code": 8000,
        "error_string": "Некорректный запрос",
        "error_detail": "Поле TextCampaign недопустимо для кампании типа UNIFIED_CAMPAIGN",
    }
}


def _mock_transport(body: dict, status_code: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(
        lambda request: httpx.Response(status_code, json=body)
    )


@pytest.fixture
def patch_httpx(monkeypatch):
    """Route httpx.AsyncClient traffic to a canned Direct API response."""

    def _patch(body: dict, status_code: int = 200):
        # api_client is instantiated at import time, before conftest's env fixture
        monkeypatch.setattr(api_client, "unified_token", "test-token")
        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(body, status_code)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)

    return _patch


@pytest.mark.asyncio
async def test_direct_request_raises_on_error_body(patch_httpx):
    patch_httpx(ERROR_BODY)
    with pytest.raises(YandexAPIError) as exc_info:
        await api_client.direct_request("campaigns", "update", {"Campaigns": []})
    assert exc_info.value.error_code == 8000
    assert "Некорректный запрос" in str(exc_info.value)


@pytest.mark.asyncio
async def test_direct_request_passes_through_success(patch_httpx):
    patch_httpx({"result": {"UpdateResults": [{"Id": 1}]}})
    result = await api_client.direct_request("campaigns", "update", {"Campaigns": []})
    assert result["result"]["UpdateResults"] == [{"Id": 1}]


def test_handle_api_error_formats_yandex_error():
    err = YandexAPIError(
        error_code=8000,
        error_string="Некорректный запрос",
        error_detail="Поле TextCampaign недопустимо",
        request_id="12345",
    )
    message = handle_api_error(err)
    assert "8000" in message
    assert "Некорректный запрос" in message
    assert "TextCampaign" in message
    assert "successfully" not in message


@pytest.mark.asyncio
async def test_update_campaign_tool_reports_api_error(patch_httpx, mcp_instance):
    """End-to-end: the tool must not report success on an API error body."""
    patch_httpx(ERROR_BODY)
    result = await mcp_instance.call_tool(
        "direct_update_campaign",
        {"params": {"campaign_id": 710591141, "name": "x"}},
    )
    text = json.dumps([getattr(c, "text", "") for c in result[0]], ensure_ascii=False)
    assert "successfully" not in text
    assert "Некорректный запрос" in text
