"""direct_update_campaign must route type-specific fields by campaign type.

ЕПК (UNIFIED_CAMPAIGN) updates were built with a TextCampaign subobject and
sent to the v5 endpoint — the API rejects both. Strategy sub-params passed
without bidding_strategy_type were silently ignored.
"""

import json

import httpx
import pytest

from yandex_mcp.client import api_client


def _campaign_type_response(campaign_type: str) -> dict:
    return {
        "result": {
            "Campaigns": [{"Id": 710591141, "Type": campaign_type}]
        }
    }


UPDATE_OK = {"result": {"UpdateResults": [{"Id": 710591141}]}}


@pytest.fixture
def direct_api(monkeypatch):
    """Mock Direct API: campaigns.get returns a fixed type, update is captured."""

    captured = {"updates": []}

    def _install(campaign_type: str = "UNIFIED_CAMPAIGN"):
        monkeypatch.setattr(api_client, "unified_token", "test-token")

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode())
            if body["method"] == "get":
                return httpx.Response(200, json=_campaign_type_response(campaign_type))
            if body["method"] == "update":
                captured["updates"].append(
                    {"url": str(request.url), "campaign": body["params"]["Campaigns"][0]}
                )
                return httpx.Response(200, json=UPDATE_OK)
            return httpx.Response(200, json={"result": {}})

        original_init = httpx.AsyncClient.__init__

        def patched_init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original_init(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
        return captured

    return _install


async def _call_update(mcp_instance, **fields):
    result = await mcp_instance.call_tool(
        "direct_update_campaign",
        {"params": {"campaign_id": 710591141, **fields}},
    )
    return json.dumps([getattr(c, "text", "") for c in result[0]], ensure_ascii=False)


@pytest.mark.asyncio
async def test_unified_campaign_fields_go_to_unified_subobject(direct_api, mcp_instance):
    captured = direct_api("UNIFIED_CAMPAIGN")
    text = await _call_update(mcp_instance, counter_ids=[93988076], add_metrica_tag=True)
    assert "successfully" in text
    assert len(captured["updates"]) == 1
    update = captured["updates"][0]
    assert "UnifiedCampaign" in update["campaign"]
    assert "TextCampaign" not in update["campaign"]
    assert update["campaign"]["UnifiedCampaign"]["CounterIds"] == {"Items": [93988076]}
    assert "/v501/" in update["url"]


@pytest.mark.asyncio
async def test_text_campaign_fields_stay_in_text_subobject(direct_api, mcp_instance):
    captured = direct_api("TEXT_CAMPAIGN")
    text = await _call_update(mcp_instance, counter_ids=[93988076])
    assert "successfully" in text
    update = captured["updates"][0]
    assert "TextCampaign" in update["campaign"]
    assert "UnifiedCampaign" not in update["campaign"]
    assert "/v5/" in update["url"]


@pytest.mark.asyncio
async def test_strategy_update_merges_with_other_fields(direct_api, mcp_instance):
    """BiddingStrategy assignment must not clobber counters/settings."""
    captured = direct_api("UNIFIED_CAMPAIGN")
    await _call_update(
        mcp_instance,
        counter_ids=[93988076],
        bidding_strategy_type="WB_MAXIMUM_CLICKS",
        bid_ceiling=200,
    )
    sub = captured["updates"][0]["campaign"]["UnifiedCampaign"]
    assert sub["CounterIds"] == {"Items": [93988076]}
    assert sub["BiddingStrategy"]["Search"]["BiddingStrategyType"] == "WB_MAXIMUM_CLICKS"
    assert sub["BiddingStrategy"]["Search"]["WbMaximumClicks"]["BidCeiling"] == 200_000_000


@pytest.mark.asyncio
async def test_bid_ceiling_without_strategy_type_is_an_error(direct_api, mcp_instance):
    captured = direct_api("UNIFIED_CAMPAIGN")
    text = await _call_update(mcp_instance, bid_ceiling=200)
    assert "successfully" not in text
    assert "bidding_strategy_type" in text
    assert captured["updates"] == []


@pytest.mark.asyncio
async def test_name_only_update_needs_no_type_lookup(direct_api, mcp_instance):
    """Campaign-level fields must not trigger an extra campaigns.get."""
    captured = direct_api("UNIFIED_CAMPAIGN")
    text = await _call_update(mcp_instance, name="renamed")
    assert "successfully" in text
    update = captured["updates"][0]
    assert update["campaign"] == {"Id": 710591141, "Name": "renamed"}
