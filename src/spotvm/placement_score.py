from __future__ import annotations

import itertools
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass

from . import cache
from .http_client import AzureRestClient
from .models import PlacementScoreResult

logger = logging.getLogger("spotvm")

PLACEMENT_API_VERSION = "2025-06-05"
PLACEMENT_ENDPOINT_TEMPLATE = (
    "https://management.azure.com/subscriptions/{subscription_id}"
    "/providers/Microsoft.Compute/locations/{location}/placementScores/spot/generate"
    "?api-version=" + PLACEMENT_API_VERSION
)


@dataclass(frozen=True)
class PlacementScoreRequest:
    subscription_id: str
    regions: list[str]
    sizes: list[str]
    desired_count: int
    availability_zones: bool
    cache_ttl_minutes: int
    max_sizes_per_request: int
    max_regions_per_request: int
    retry_attempts: int
    retry_backoff_seconds: float


def fetch_placement_scores(
    client: AzureRestClient,
    request: PlacementScoreRequest,
) -> list[PlacementScoreResult]:
    """Fetch placement scores, observing Azure's batching limits."""

    results: list[PlacementScoreResult] = []
    for region_batch in _batched(request.regions, request.max_regions_per_request):
        for size_batch in _batched(request.sizes, request.max_sizes_per_request):
            payload = _build_payload(region_batch, size_batch, request)
            cache_key = _cache_key("placement", payload, request.subscription_id)
            cached = cache.load(cache_key, request.cache_ttl_minutes)
            if cached is not None:
                if not isinstance(cached, dict):
                    logger.warning("Ignoring malformed cached placement data for %s", region_batch[0])
                else:
                    results.extend(_parse_response(cached))
                    continue
            endpoint = PLACEMENT_ENDPOINT_TEMPLATE.format(
                subscription_id=request.subscription_id,
                location=region_batch[0],
            )
            response = client.post_json(
                endpoint,
                payload,
                retry_attempts=request.retry_attempts,
                retry_backoff_seconds=request.retry_backoff_seconds,
            )
            cache.store(cache_key, response, request.cache_ttl_minutes)
            results.extend(_parse_response(response))
    return results


def _build_payload(regions: list[str], sizes: list[str], request: PlacementScoreRequest) -> dict:
    return {
        "desiredLocations": regions,
        "desiredSizes": [{"sku": size} for size in sizes],
        "desiredCount": request.desired_count,
        "availabilityZones": request.availability_zones,
    }


def _parse_response(payload: dict) -> list[PlacementScoreResult]:
    placement_scores = payload.get("placementScores")
    if placement_scores is None:
        placement_scores = payload.get("properties", {}).get("placementScores", [])
    results: list[PlacementScoreResult] = []
    for item in placement_scores:
        vm_size = item.get("sku") or item.get("vmSize") or item.get("name")
        if not vm_size:
            logger.debug("Skipping placement score item without VM size: %r", item)
            continue
        scores = item.get("scoresByLocation")
        if scores:
            for score_entry in scores:
                results.append(_build_result(vm_size, score_entry))
        else:
            results.append(_build_result(vm_size, item))
    return results


def _cache_key(prefix: str, payload: dict, subscription_id: str) -> str:
    normalized = json.dumps(payload, sort_keys=True)
    return f"{prefix}:{subscription_id}:{normalized}"


def _build_result(vm_size: str, entry: dict) -> PlacementScoreResult:
    raw_region = entry.get("location") or entry.get("region")
    region = raw_region if isinstance(raw_region, str) else ""
    score = entry.get("score")
    quota = entry.get("isQuotaAvailable")
    availability_zone = entry.get("availabilityZone") or entry.get("zone")
    message = entry.get("statusMessage") or entry.get("message") or entry.get("status") or entry.get("code")
    return PlacementScoreResult(
        region=region,
        vm_size=vm_size,
        placement_score=score,
        quota_available=quota,
        availability_zone=availability_zone,
        error_detail=message,
    )


def _batched(values: Iterable[str], batch_size: int) -> Iterable[list[str]]:
    iterator = iter(values)
    while True:
        chunk = list(itertools.islice(iterator, batch_size))
        if not chunk:
            return
        yield chunk
