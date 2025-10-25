from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from . import cache
from .config import ToolConfig
from .http_client import AzureRestClient
from .models import HistoricalMetrics

RESOURCE_GRAPH_API_VERSION = "2021-03-01"
RESOURCE_GRAPH_ENDPOINT = (
    "https://management.azure.com/providers/Microsoft.ResourceGraph/resources"
    f"?api-version={RESOURCE_GRAPH_API_VERSION}"
)


def fetch_historical_metrics(
    client: AzureRestClient,
    config: ToolConfig,
) -> List[HistoricalMetrics]:
    if config.resource_graph_sample:
        sample = json.loads(config.resource_graph_sample.read_text(encoding="utf-8"))
        price_rows = _extract_sample_rows(sample, "price")
        eviction_rows = _extract_sample_rows(sample, "eviction")
    else:
        price_query = _build_price_query(config)
        eviction_query = _build_eviction_query(config)

        price_rows = _execute_query(client, config, price_query, "price")
        eviction_rows = _execute_query(client, config, eviction_query, "eviction")

    price_map: Dict[tuple[str, str], dict] = {}
    for row in price_rows:
        key = (
            row.get("skuName", "").lower(),
            row.get("location", "").lower(),
        )
        price_map[key] = row

    eviction_map: Dict[tuple[str, str], dict] = {}
    for row in eviction_rows:
        key = (
            row.get("skuName", "").lower(),
            row.get("location", "").lower(),
        )
        eviction_map[key] = row

    metrics: List[HistoricalMetrics] = []
    keys = set(price_map.keys()) | set(eviction_map.keys())
    for sku, region in sorted(keys):
        price_entry = price_map.get((sku, region))
        eviction_entry = eviction_map.get((sku, region))
        region_display = (
            (price_entry or {}).get("location")
            or (eviction_entry or {}).get("location")
            or region
        )
        sku_display = (
            (price_entry or {}).get("skuName")
            or (eviction_entry or {}).get("skuName")
            or sku
        )

        price_usd, price_dt = _extract_latest_price(price_entry)
        eviction_rate, eviction_dt = _extract_eviction(eviction_entry)

        metrics.append(
            HistoricalMetrics(
                region=region_display,
                vm_size=sku_display,
                price_usd=price_usd,
                price_last_updated=price_dt,
                eviction_rate=eviction_rate,
                eviction_last_updated=eviction_dt,
            )
        )
    return metrics


def _execute_query(
    client: AzureRestClient,
    config: ToolConfig,
    query: str,
    cache_prefix: str,
) -> List[dict]:
    payload = {
        "subscriptions": [config.subscription_id],
        "query": query,
        "options": {"resultFormat": "objectArray"},
    }
    cache_key = _cache_key(cache_prefix, payload)
    cached = cache.load(cache_key, config.cache_ttl_minutes)
    if cached:
        return cached.get("data", [])

    response = client.post_json(
        RESOURCE_GRAPH_ENDPOINT,
        payload,
        retry_attempts=config.retry_attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
    )
    cache.store(cache_key, response, config.cache_ttl_minutes)
    return response.get("data", [])


def _extract_sample_rows(sample: dict, key: str) -> List[dict]:
    block = sample.get(key)
    if block is None:
        return []
    if isinstance(block, dict):
        data = block.get("data")
        if isinstance(data, list):
            return data
    if isinstance(block, list):
        return block
    return []


def _cache_key(prefix: str, payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return f"resource-graph:{prefix}:{serialized}"


def _build_price_query(config: ToolConfig) -> str:
    region_filter = _in_expression("location", config.regions)
    sku_list = _in_list(config.sizes)
    os_filter = f"| where osType =~ '{config.os_type}'" if config.os_type else ""
    return (
        "SpotResources\n"
        "| where type =~ 'microsoft.compute/skuspotpricehistory/ostype/location'\n"
        "| extend skuName = tostring(properties.skuName),"
        " osType = tostring(properties.osType),"
        " spotPrices = todynamic(properties.spotPrices)\n"
        f"| where skuName in~ ({sku_list})\n"
        f"| {region_filter}\n"
        f"{os_filter}\n"
        "| project skuName, location = tostring(location), spotPrices"
    )


def _build_eviction_query(config: ToolConfig) -> str:
    region_filter = _in_expression("location", config.regions)
    sku_list = _in_list(config.sizes)
    return (
        "SpotResources\n"
        "| where type =~ 'microsoft.compute/skuspotevictionrate/location'\n"
        "| extend skuName = tostring(properties.skuName)\n"
        f"| where skuName in~ ({sku_list})\n"
        f"| {region_filter}\n"
        "| project skuName, location = tostring(location),"
        " evictionRate = todouble(properties.evictionRate),"
        " evictionLastUpdated = tostring(properties.lastUpdatedTime)"
    )


def _in_expression(column: str, values: Iterable[str]) -> str:
    quoted = _in_list(values)
    return f"where {column} in~ ({quoted})"


def _in_list(values: Iterable[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _extract_latest_price(entry: Optional[dict]) -> tuple[Optional[float], Optional[datetime]]:
    if not entry:
        return None, None
    raw_prices = entry.get("spotPrices")
    spot_prices = _ensure_list(raw_prices)
    if not spot_prices:
        return None, None
    latest = spot_prices[0]
    if isinstance(latest, str):
        try:
            latest = json.loads(latest)
        except json.JSONDecodeError:
            return None, None
    if not isinstance(latest, dict):
        return None, None
    price = _to_float(latest.get("priceUSD"))
    timestamp = _parse_datetime_string(latest.get("dateTime"))
    return price, timestamp


def _extract_eviction(entry: Optional[dict]) -> tuple[Optional[float], Optional[datetime]]:
    if not entry:
        return None, None
    rate = _to_float(entry.get("evictionRate"))
    timestamp = _parse_datetime_string(
        entry.get("evictionLastUpdated") or entry.get("lastUpdatedTime")
    )
    return rate, timestamp


def _ensure_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
        return []
    if isinstance(value, list):
        return value
    return []


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_datetime_string(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value)
    if isinstance(value, str):
        cleaned = value.rstrip("Z")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None
    return None
