from __future__ import annotations

import pytest

from spotvm.models import DATABRICKS_OPTIONAL_FIELDS, CandidateInsight, effective_price_usd


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (
            CandidateInsight(
                region="eastus",
                vm_size="Standard_D4as_v5",
                placement_score=None,
                quota_available=None,
                price_usd=0.10,
                total_price_usd=0.25,
                price_last_updated=None,
                eviction_rate=None,
                eviction_last_updated=None,
            ),
            0.25,
        ),
        (
            CandidateInsight(
                region="eastus",
                vm_size="Standard_D4as_v5",
                placement_score=None,
                quota_available=None,
                price_usd=0.0,
                total_price_usd=0.0,
                price_last_updated=None,
                eviction_rate=None,
                eviction_last_updated=None,
            ),
            0.0,
        ),
        (
            CandidateInsight(
                region="eastus",
                vm_size="Standard_D4as_v5",
                placement_score=None,
                quota_available=None,
                price_usd=1,
                total_price_usd=None,
                price_last_updated=None,
                eviction_rate=None,
                eviction_last_updated=None,
            ),
            1.0,
        ),
        (
            CandidateInsight(
                region="eastus",
                vm_size="Standard_D4as_v5",
                placement_score=None,
                quota_available=None,
                price_usd=1,
                compute_price_usd=1,
                total_price_usd=None,
                price_last_updated=None,
                eviction_rate=None,
                eviction_last_updated=None,
            ),
            None,
        ),
        (
            CandidateInsight(
                region="eastus",
                vm_size="Standard_D4as_v5",
                placement_score=None,
                quota_available=None,
                price_usd=None,
                total_price_usd=None,
                price_last_updated=None,
                eviction_rate=None,
                eviction_last_updated=None,
            ),
            None,
        ),
    ],
)
def test_effective_price_usd_uses_total_then_raw_price(candidate, expected):
    assert effective_price_usd(candidate) == expected


def test_candidate_insight_exposes_effective_price_as_property():
    candidate = CandidateInsight(
        region="eastus",
        vm_size="Standard_D4as_v5",
        placement_score=None,
        quota_available=None,
        price_usd=1.0,
        compute_price_usd=1.0,
        total_price_usd=None,
        price_last_updated=None,
        eviction_rate=None,
        eviction_last_updated=None,
    )

    assert candidate.effective_price_usd is None


def test_databricks_optional_fields_are_candidate_insight_attributes():
    """Prevent drift between DATABRICKS_OPTIONAL_FIELDS and CandidateInsight."""
    dataclass_fields = set(CandidateInsight.__dataclass_fields__)
    for field in DATABRICKS_OPTIONAL_FIELDS:
        assert field in dataclass_fields, (
            f"{field!r} listed in DATABRICKS_OPTIONAL_FIELDS but missing from CandidateInsight"
        )


def test_candidate_insight_databricks_fields_are_listed_in_optional_fields():
    databricks_fields = {
        field_name
        for field_name in CandidateInsight.__dataclass_fields__
        if field_name.startswith("databricks_") or field_name in {"compute_price_usd", "total_price_usd"}
    }

    assert databricks_fields == set(DATABRICKS_OPTIONAL_FIELDS)
