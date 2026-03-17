from __future__ import annotations

import pytest

from spotvm.vm_specs import (
    _NORMALIZED_VM_SPECIFICATIONS,
    VM_SPECIFICATIONS,
    calculate_relative_performance_details,
    detect_cpu_architecture,
    detect_cpu_vendor,
    discover_skus,
    get_vm_spec,
    hardware_window_tiers,
    known_hardware_tiers,
    matches_hardware_constraint,
)


def test_vm_catalog_exposes_same_lookup_surface():
    from spotvm.vm_catalog import VM_SPECIFICATIONS as catalog_specs
    from spotvm.vm_catalog import get_vm_spec as catalog_get_vm_spec

    assert catalog_specs["Standard_D4as_v5"] == VM_SPECIFICATIONS["Standard_D4as_v5"]
    assert catalog_get_vm_spec("standard_d4as_v5") == get_vm_spec("standard_d4as_v5")


def test_get_vm_spec_normalizes_case_and_underscores():
    canonical = get_vm_spec("Standard_D4as_v5")

    assert canonical is not None
    assert get_vm_spec("standard_d4as_v5") == canonical
    assert get_vm_spec("standardd4asv5") == canonical


def test_get_vm_spec_returns_none_for_unknown_sku():
    assert get_vm_spec("NotARealSKU") is None


def test_normalized_vm_specifications_do_not_have_key_collisions():
    normalized_keys = [sku.lower().replace("_", "") for sku in VM_SPECIFICATIONS]

    assert len(normalized_keys) == len(set(normalized_keys))
    assert set(_NORMALIZED_VM_SPECIFICATIONS) == set(normalized_keys)


def test_detect_cpu_architecture_and_vendor_use_additive_feature_block():
    assert detect_cpu_architecture("Standard_D4ps_v5") == "arm"
    assert detect_cpu_vendor("Standard_D4ps_v5") == "arm"
    assert detect_cpu_architecture("Standard_D4as_v5") == "x64"
    assert detect_cpu_vendor("Standard_D4as_v5") == "amd"


def test_known_hardware_tiers_and_windows_are_sorted_distinct_values():
    known_hardware_tiers.cache_clear()

    assert known_hardware_tiers("vcpu")[:4] == (1.0, 2.0, 4.0, 8.0)
    assert hardware_window_tiers(4, dimension="vcpu") == (4.0, 8.0, 16.0)
    assert hardware_window_tiers(16, dimension="ram") == (16.0, 28.0, 32.0)


def test_matches_hardware_constraint_uses_bounded_windows_unless_disabled():
    assert matches_hardware_constraint(16, 4, dimension="vcpu") is True
    assert matches_hardware_constraint(32, 4, dimension="vcpu") is False
    assert matches_hardware_constraint(32, 4, dimension="vcpu", no_max_limit=True) is True


def test_calculate_relative_performance_details_reports_heuristic_arm_bonus():
    performance, basis = calculate_relative_performance_details("Standard_D4ps_v6", "Standard_D4as_v6")

    assert performance == pytest.approx(115.0)
    assert basis == "heuristic"


def test_discover_skus_filters_by_architecture_and_sorts_by_compute_score():
    skus = discover_skus(min_vcpu=4, min_ram=16, cpu_arch="arm")

    assert skus[0] == "Standard_D4ps_v6"
    assert "Standard_D8ps_v6" in skus
    assert "Standard_D16ps_v6" not in skus
    assert all(detect_cpu_architecture(sku) == "arm" for sku in skus)
