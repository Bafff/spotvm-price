from __future__ import annotations

from spotvm.vm_specs import (
    VM_SPECIFICATIONS,
    _NORMALIZED_VM_SPECIFICATIONS,
    detect_cpu_architecture,
    detect_cpu_vendor,
    get_vm_spec,
)


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
