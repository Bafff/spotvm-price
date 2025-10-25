from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Iterable, List, Optional

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

        metrics.append(
            HistoricalMetrics(
                region=region_display,
                vm_size=sku_display,
                price_usd=_parse_float(price_entry, "latestSpotPriceUSD"),
                price_last_updated=_parse_dt(price_entry, "lastPriceUpdate"),
                eviction_rate=_parse_float(eviction_entry, "evictionRatePercent"),
                eviction_last_updated=_parse_dt(eviction_entry, "evictionLastUpdated"),
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


def _cache_key(prefix: str, payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return f"resource-graph:{prefix}:{serialized}"


def _build_price_query(config: ToolConfig) -> str:
    sku_filter = _in_expression("sku.name", config.sizes)
    region_filter = _in_expression("location", config.regions)
    os_filter = f"| where properties.osType =~ '{config.os_type}'" if config.os_type else ""
    return f"""
SpotResources
| where type =~ 'microsoft.compute/skuspotpricehistory/ostype/location'
| {sku_filter}
| {region_filter}
{os_filter}
| where array_length(properties.spotPrices) > 0
| extend latest = properties.spotPrices[0]
| project skuName = tostring(sku.name), location = tostring(location), latestSpotPriceUSD = todouble(latest.priceUSD), lastPriceUpdate = todatetime(latest.dateTime)
""".strip()


def _build_eviction_query(config: ToolConfig) -> str:
    sku_filter = _in_expression("sku.name", config.sizes)
    region_filter = _in_expression("location", config.regions)
    return f"""
SpotResources
| where type =~ 'microsoft.compute/skuspotevictionrate/location'
| {sku_filter}
| {region_filter}
| project skuName = tostring(sku.name), location = tostring(location), evictionRatePercent = todouble(properties.evictionRate), evictionLastUpdated = todatetime(properties.lastUpdatedTime)
""".strip()


def _in_expression(column: str, values: Iterable[str]) -> str:
    quoted = ", ".join(f"'{value}'" for value in values)
    return f"where {column} in~ ({quoted})"


def _parse_float(entry: Optional[dict], key: str) -> Optional[float]:
    if not entry:
        return None
    value = entry.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_dt(entry: Optional[dict], key: str) -> Optional[datetime]:
    if not entry:
        return None
    value = entry.get(key)
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.rstrip("Z"))
    except ValueError:
        return None
