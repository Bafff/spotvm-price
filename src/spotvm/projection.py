from __future__ import annotations

from typing import Any

from .models import CandidateInsight


def project_for_history(candidate: CandidateInsight) -> dict[str, Any]:
    """Project a candidate to a dictionary for historical JSON storage."""
    return {
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


def project_for_report(candidate: CandidateInsight, json_serializer: Any, merge_notes: Any) -> dict[str, Any]:
    """Project a candidate to a dictionary for JSON reporting output."""
    return {
        "rank": candidate.recommendation_rank,
        "region": candidate.region,
        "availabilityZone": candidate.availability_zone,
        "vmSize": candidate.vm_size,
        "cpuArchitecture": candidate.cpu_arch,
        "placementScore": candidate.placement_score,
        "quotaAvailable": candidate.quota_available,
        "priceUSDPerHour": candidate.price_usd,
        "priceLastUpdated": json_serializer(candidate.price_last_updated),
        "evictionRatePercent": candidate.eviction_rate,
        "performanceRelativePercent": candidate.performance_relative,
        "pricePerPerformance": candidate.price_per_performance,
        "performanceBasis": getattr(candidate, "performance_basis", None),
        "performanceNote": getattr(candidate, "performance_note", None),
        "coremarkScore": candidate.coremark_score,
        "coremarkPerVCPU": candidate.coremark_per_vcpu,
        "notes": merge_notes(candidate.notes, getattr(candidate, "performance_note", None)),
    }


def project_for_csv(
    candidate: CandidateInsight,
    vendor_text: str,
    formatters: dict[str, Any],
    format_notes: Any,
) -> dict[str, str]:
    """Project a candidate to a dictionary for CSV output."""
    return {
        "Rank": str(candidate.recommendation_rank) if candidate.recommendation_rank is not None else "",
        "Region": candidate.region or "",
        "Availability Zone": candidate.availability_zone or "",
        "VM Size": candidate.vm_size or "",
        "CPU Vendor": vendor_text,
        "Placement Score": candidate.placement_score or (candidate.notes or "N/A"),
        "Quota Available": formatters["quota"](candidate.quota_available),
        "Price (USD/hr)": formatters["price"](candidate.price_usd),
        "Eviction Rate (%)": formatters["percentage"](candidate.eviction_rate),
        "Performance (%)": formatters["performance"](candidate.performance_relative),
        "Price per Performance": formatters["price_per_perf"](candidate.price_per_performance),
        "CoreMark Score": formatters["coremark"](candidate.coremark_score),
        "CoreMark per vCPU": formatters["coremark_per_vcpu"](candidate.coremark_per_vcpu),
        "Price Last Updated": formatters["datetime"](candidate.price_last_updated),
        "Notes": format_notes(candidate),
    }
