from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from . import cache
from .config import ToolConfig
from .http_client import AzureRestClient
from .models import HistoricalMetrics

logger = logging.getLogger("spotvm-tool")

RESOURCE_GRAPH_API_VERSION = "2022-10-01"
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

    logger.debug("Price query: %s", price_query)
    logger.debug("Eviction query: %s", eviction_query)

    price_rows = _execute_query(client, config, price_query, "price")
    eviction_rows = _execute_query(client, config, eviction_query, "eviction")

    logger.debug("Price rows returned: %d", len(price_rows))
    logger.debug("Eviction rows returned: %d", len(eviction_rows))

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
    # SpotResources table works differently than regular resources
    # Azure Portal uses authorizationScopeFilter to query across all accessible scopes
    payload = {
        "query": query,
        "options": {
            "resultFormat": "objectArray",
            "authorizationScopeFilter": "AtScopeAboveAndBelow",
        },
    }

    logger.debug("Executing query with authorizationScopeFilter=AtScopeAboveAndBelow")

    cache_key = _cache_key(cache_prefix, payload)
    cached = cache.load(cache_key, config.cache_ttl_minutes)
    if cached:
        logger.debug("Using cached %s data", cache_prefix)
        return cached.get("data", [])

    logger.debug("Executing %s query against Resource Graph API", cache_prefix)
    response = client.post_json(
        RESOURCE_GRAPH_ENDPOINT,
        payload,
        retry_attempts=config.retry_attempts,
        retry_backoff_seconds=config.retry_backoff_seconds,
    )
    logger.debug("Response keys: %s", list(response.keys()))
    logger.debug("Response data length: %d", len(response.get("data", [])))
    if response.get("data"):
        logger.debug("Sample data item: %s", response["data"][0] if response["data"] else "N/A")
    cache.store(cache_key, response, config.cache_ttl_minutes)
    return response.get("data", [])


def _cache_key(prefix: str, payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return f"resource-graph:{prefix}:{serialized}"


def _build_price_query(config: ToolConfig) -> str:
    region_filter = _in_expression("location", config.regions)
    sku_list = _in_list(config.sizes)
    os_filter = f"| where osType =~ '{config.os_type}'" if config.os_type else ""
    return (
        "spotresources\n"
        "| where type =~ 'microsoft.compute/skuspotpricehistory/ostype/location'\n"
        "| extend skuName = tostring(sku.name),"
        " osType = tostring(properties.osType),"
        " spotPrices = todynamic(properties.spotPrices)\n"
        f"| where sku.name in~ ({sku_list})\n"
        f"| {region_filter}\n"
        f"{os_filter}\n"
        "| project skuName, location = tostring(location), spotPrices"
    )


def _build_eviction_query(config: ToolConfig) -> str:
    region_filter = _in_expression("location", config.regions)
    sku_list = _in_list(config.sizes)
    return (
        "spotresources\n"
        "| where type =~ 'microsoft.compute/skuspotevictionrate/location'\n"
        f"| where sku.name in~ ({sku_list})\n"
        f"| {region_filter}\n"
        # Note: Azure SpotResources API doesn't provide lastUpdatedTime for eviction rates
        # See: https://learn.microsoft.com/en-us/azure/virtual-machines/spot-vms
        "| project skuName = tostring(sku.name), location = tostring(location),"
        " spotEvictionRate = tostring(properties.evictionRate)"
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
    # Field is called effectiveDate, not dateTime
    timestamp = _parse_datetime_string(latest.get("effectiveDate") or latest.get("dateTime"))
    return price, timestamp


def _extract_eviction(entry: Optional[dict]) -> tuple[Optional[float], Optional[datetime]]:
    if not entry:
        return None, None

    # Azure returns evictionRate as string like "5", "10", "20", or ranges like "0-5", "5-10"
    eviction_str = entry.get("spotEvictionRate") or entry.get("evictionRate")
    rate = None

    if eviction_str:
        # Try to parse as direct number first
        rate = _to_float(eviction_str)

        # If that fails, try to extract from range (e.g., "5-10" -> 10, "0-5" -> 5)
        if rate is None and isinstance(eviction_str, str):
            # Extract upper bound from range like "5-10" -> 10
            match = re.search(r"-(\d+(?:\.\d+)?)", eviction_str)
            if match:
                rate = _to_float(match.group(1))
            else:
                # Try single number like "5" -> 5
                match = re.search(r"^(\d+(?:\.\d+)?)", eviction_str)
                if match:
                    rate = _to_float(match.group(1))

    # Azure SpotResources API doesn't provide lastUpdatedTime for eviction rates
    # This is a known limitation - eviction rates are updated every ~30 minutes but
    # the timestamp is not exposed in the API
    timestamp = None
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
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        cleaned = value.rstrip("Z")
        try:
            return datetime.fromisoformat(cleaned)
        except ValueError:
            return None
    return None


