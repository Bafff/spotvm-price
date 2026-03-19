from __future__ import annotations

from datetime import datetime
from typing import Any

from .models import DATABRICKS_OPTIONAL_FIELDS, CandidateInsight, effective_price_usd


def project_for_history(candidate: CandidateInsight) -> dict[str, Any]:
    """Project a candidate to a dictionary for historical JSON storage.

    The snapshot keeps ``price_usd`` as the raw Azure VM price so historical
    runs remain comparable regardless of whether Databricks enrichment was
    enabled. Databricks-aware totals, when present, are recorded separately in
    ``total_price_usd`` and related Databricks fields.
    """
    payload = {
        "vm_size": candidate.vm_size,
        "region": candidate.region,
        "availability_zone": candidate.availability_zone,
        "price_usd": candidate.price_usd,
        "eviction_rate": candidate.eviction_rate,
        "placement_score": candidate.placement_score,
        "quota_available": candidate.quota_available,
        "performance_relative": candidate.performance_relative,
        "price_per_performance": candidate.price_per_performance,
        "recommendation_rank": candidate.recommendation_rank,
        "notes": candidate.notes,
    }
    for field in DATABRICKS_OPTIONAL_FIELDS:
        value = getattr(candidate, field, None)
        if value is not None:
            if isinstance(value, datetime):
                payload[field] = value.isoformat()
                continue
            payload[field] = value
    return payload


def project_for_report(
    candidate: CandidateInsight,
    json_serializer: Any,
    merge_notes: Any,
    *,
    show_databricks: bool = False,
    show_photon: bool = False,
) -> dict[str, Any]:
    """Project a candidate to a dictionary for JSON reporting output."""
    payload = {
        "rank": candidate.recommendation_rank,
        "region": candidate.region,
        "availabilityZone": candidate.availability_zone,
        "vmSize": candidate.vm_size,
        "cpuArchitecture": candidate.cpu_arch,
        "placementScore": candidate.placement_score,
        "quotaAvailable": candidate.quota_available,
        "priceUSDPerHour": effective_price_usd(candidate),
        "priceLastUpdated": json_serializer(candidate.price_last_updated),
        "evictionRatePercent": candidate.eviction_rate,
        "performanceRelativePercent": candidate.performance_relative,
        "pricePerPerformance": candidate.price_per_performance,
        "performanceBasis": candidate.performance_basis,
        "performanceNote": candidate.performance_note,
        "coremarkScore": candidate.coremark_score,
        "coremarkPerVCPU": candidate.coremark_per_vcpu,
        "notes": merge_notes(candidate.notes, candidate.performance_note),
    }
    if show_databricks:
        payload["computePriceUSDPerHour"] = candidate.compute_price_usd
        payload["databricksDBUPerHour"] = candidate.databricks_dbu_per_hour
        payload["databricksCostUSDPerHour"] = candidate.databricks_dbu_cost_usd
        payload["totalPriceUSDPerHour"] = candidate.total_price_usd
        payload["databricksCatalogUpdated"] = json_serializer(candidate.databricks_catalog_updated)
    if show_databricks and show_photon:
        payload["photonDBUPerHour"] = candidate.databricks_photon_dbu_per_hour
        payload["photonCostUSDPerHour"] = candidate.databricks_photon_cost_usd
    return payload


def project_for_csv(
    candidate: CandidateInsight,
    vendor_text: str,
    formatters: dict[str, Any],
    format_notes: Any,
    *,
    show_databricks: bool = False,
    show_photon: bool = False,
) -> dict[str, str]:
    """Project a candidate to a dictionary for CSV output."""
    payload = {
        "Rank": str(candidate.recommendation_rank) if candidate.recommendation_rank is not None else "",
        "Region": candidate.region or "",
        "Availability Zone": candidate.availability_zone or "",
        "VM Size": candidate.vm_size or "",
        "CPU Vendor": vendor_text,
        "Placement Score": candidate.placement_score or (candidate.notes or "N/A"),
        "Quota Available": formatters["quota"](candidate.quota_available),
        "Price (USD/hr)": formatters["price"](effective_price_usd(candidate)),
        "Eviction Rate (%)": formatters["percentage"](candidate.eviction_rate),
        "Performance (%)": formatters["performance"](candidate.performance_relative),
        "Price per Performance": formatters["price_per_perf"](candidate.price_per_performance),
        "CoreMark Score": formatters["coremark"](candidate.coremark_score),
        "CoreMark per vCPU": formatters["coremark_per_vcpu"](candidate.coremark_per_vcpu),
        "Price Last Updated": formatters["datetime"](candidate.price_last_updated),
        "Notes": format_notes(candidate),
    }
    if show_databricks:
        payload["VM Price (USD/hr)"] = formatters["numeric"](candidate.compute_price_usd)
        payload["DBU per Hour"] = formatters["numeric"](candidate.databricks_dbu_per_hour)
        payload["Databricks Cost (USD/hr)"] = formatters["numeric"](candidate.databricks_dbu_cost_usd)
        payload["Total Cost (USD/hr)"] = formatters["numeric"](candidate.total_price_usd)
        payload["Databricks Catalog Updated"] = formatters["datetime"](candidate.databricks_catalog_updated)
    if show_databricks and show_photon:
        payload["Photon DBU per Hour"] = formatters["numeric"](candidate.databricks_photon_dbu_per_hour)
        payload["Photon Cost (USD/hr)"] = formatters["numeric"](candidate.databricks_photon_cost_usd)
    return payload
