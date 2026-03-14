from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, cast
from urllib.parse import urlunsplit

from . import cache
from .http_client import AzureRestClient
from .models import HistoricalMetrics

logger = logging.getLogger("spotvm")

RESOURCE_GRAPH_API_VERSION = "2022-10-01"
AZURE_MANAGEMENT_HOST = "management.azure.com"
RESOURCE_GRAPH_PATH = "/providers/Microsoft.ResourceGraph/resources"
MIN_PLAUSIBLE_UNIX_TIMESTAMP = datetime(2015, 1, 1, tzinfo=timezone.utc).timestamp()
MAX_PLAUSIBLE_UNIX_TIMESTAMP = datetime(2041, 1, 1, tzinfo=timezone.utc).timestamp()


@dataclass(frozen=True)
class ResourceGraphRequest:
    regions: list[str]
    sizes: list[str]
    os_type: str
    cache_ttl_minutes: int
    retry_attempts: int
    retry_backoff_seconds: float


def fetch_historical_metrics(
    client: AzureRestClient,
    request: ResourceGraphRequest,
) -> list[HistoricalMetrics]:
    price_query = _build_price_query(request)
    eviction_query = _build_eviction_query(request)
    logger.debug(
        "Built Resource Graph queries for %d SKU filters across %d regions",
        len(request.sizes),
        len(request.regions),
    )

    price_rows = _execute_query(client, request, price_query, "price")
    eviction_rows = _execute_query(client, request, eviction_query, "eviction")

    logger.debug("Price rows returned: %d", len(price_rows))
    logger.debug("Eviction rows returned: %d", len(eviction_rows))

    price_map: dict[tuple[str, str], dict] = {}
    for row in price_rows:
        key = (
            row.get("skuName", "").lower(),
            row.get("location", "").lower(),
        )
        price_map[key] = row

    eviction_map: dict[tuple[str, str], dict] = {}
    for row in eviction_rows:
        key = (
            row.get("skuName", "").lower(),
            row.get("location", "").lower(),
        )
        eviction_map[key] = row

    metrics: list[HistoricalMetrics] = []
    keys = set(price_map.keys()) | set(eviction_map.keys())
    for sku, region in sorted(keys):
        price_entry = price_map.get((sku, region))
        eviction_entry = eviction_map.get((sku, region))
        region_display = (price_entry or {}).get("location") or (eviction_entry or {}).get("location") or region
        sku_display = (price_entry or {}).get("skuName") or (eviction_entry or {}).get("skuName") or sku

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
    request: ResourceGraphRequest,
    query: str,
    cache_prefix: str,
) -> list[dict[str, Any]]:
    # SpotResources table works differently than regular resources
    # Azure Portal uses authorizationScopeFilter to query across all accessible scopes
    payload = {
        "query": query,
        "options": {
            "resultFormat": "objectArray",
            "authorizationScopeFilter": "AtScopeAboveAndBelow",
        },
    }

    cache_key = _cache_key(cache_prefix, payload)
    cached = cache.load(cache_key, request.cache_ttl_minutes)
    if cached is not None:
        if not isinstance(cached, dict):
            logger.warning("Ignoring malformed cached %s data", cache_prefix)
        else:
            cached_data = cached.get("data", [])
            if isinstance(cached_data, list):
                logger.debug("Using cached %s data", cache_prefix)
                return cast(list[dict[str, Any]], cached_data)
            logger.warning("Ignoring malformed cached %s data", cache_prefix)

    logger.debug("Executing %s query against Resource Graph API", cache_prefix)
    response = client.post_json(
        _resource_graph_endpoint(),
        payload,
        retry_attempts=request.retry_attempts,
        retry_backoff_seconds=request.retry_backoff_seconds,
    )
    logger.debug("Response keys: %s", list(response.keys()))
    logger.debug("Response data length: %d", len(response.get("data", [])))
    cache.store(cache_key, response, request.cache_ttl_minutes)
    return cast(list[dict[str, Any]], response.get("data", []))


def _resource_graph_endpoint() -> str:
    return urlunsplit(
        (
            "https",
            AZURE_MANAGEMENT_HOST,
            RESOURCE_GRAPH_PATH,
            f"api-version={RESOURCE_GRAPH_API_VERSION}",
            "",
        )
    )


def _cache_key(prefix: str, payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True)
    return f"resource-graph:{prefix}:{serialized}"


def _build_price_query(request: ResourceGraphRequest) -> str:
    region_filter = _in_expression("location", request.regions)
    sku_list = _in_list(request.sizes)
    os_filter = f"| where osType =~ '{request.os_type}'" if request.os_type else ""
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


def _build_eviction_query(request: ResourceGraphRequest) -> str:
    region_filter = _in_expression("location", request.regions)
    sku_list = _in_list(request.sizes)
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


def _extract_latest_price(entry: dict | None) -> tuple[float | None, datetime | None]:
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
            logger.debug("Failed to decode spotPrices JSON: %r", latest)
            return None, None
    if not isinstance(latest, dict):
        logger.debug("Latest spot price entry is not an object: %r", latest)
        return None, None
    price = _to_float(latest.get("priceUSD"))
    # Field is called effectiveDate, not dateTime
    timestamp = _parse_datetime_string(latest.get("effectiveDate") or latest.get("dateTime"))
    return price, timestamp


def _extract_eviction(entry: dict | None) -> tuple[float | None, datetime | None]:
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
        if rate is None:
            logger.warning("Failed to parse eviction rate: %r", eviction_str)

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
            logger.debug("Failed to decode list JSON: %r", value)
            return []
        if isinstance(parsed, list):
            return parsed
        logger.debug("Decoded JSON value is not a list: %r", parsed)
        return []
    if isinstance(value, list):
        return value
    return []


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        if value != "":
            logger.warning("Failed to parse float value: %r", value)
        return None


def _parse_datetime_string(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        cleaned = value.rstrip("Z")
        try:
            dt = datetime.fromisoformat(cleaned)
            if dt.tzinfo is None and value.endswith("Z"):
                dt = dt.replace(tzinfo=timezone.utc)
        except ValueError:
            numeric_value = _parse_timestamp_string(value)
            if numeric_value is not None:
                return datetime.fromtimestamp(numeric_value, tz=timezone.utc)
            logger.debug("Could not parse datetime string: %r", value)
            return None
        else:
            return dt
    logger.debug("Unsupported datetime type %s: %r", type(value).__name__, value)
    return None


def _parse_timestamp_string(value: str) -> float | None:
    candidate = value.strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", candidate):
        timestamp = float(candidate)
        if MIN_PLAUSIBLE_UNIX_TIMESTAMP <= timestamp < MAX_PLAUSIBLE_UNIX_TIMESTAMP:
            return timestamp
    return None
