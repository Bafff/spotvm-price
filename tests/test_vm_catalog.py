from __future__ import annotations

import pytest

from spotvm.vm_catalog import VM_SPECIFICATIONS, VMSpec, get_vm_spec


def test_compute_score_weights_vcpu_more_heavily_than_ram():
    spec = VMSpec(vcpus=4, ram_gb=16)

    assert spec.compute_score == pytest.approx(480.0)


def test_coremark_per_vcpu_returns_ratio_when_available():
    spec = VMSpec(vcpus=4, ram_gb=16, coremark_score=64_000)

    assert spec.coremark_per_vcpu == pytest.approx(16_000.0)


def test_coremark_per_vcpu_returns_none_without_benchmark_or_vcpus():
    assert VMSpec(vcpus=0, ram_gb=16, coremark_score=64_000).coremark_per_vcpu is None
    assert VMSpec(vcpus=4, ram_gb=16).coremark_per_vcpu is None


def test_get_vm_spec_looks_up_exact_and_normalized_skus():
    expected = VM_SPECIFICATIONS["Standard_D4as_v5"]

    assert get_vm_spec("Standard_D4as_v5") is expected
    assert get_vm_spec("standard_d4as_v5") is expected
    assert get_vm_spec("standardd4asv5") is expected


def test_get_vm_spec_returns_none_for_unknown_sku():
    assert get_vm_spec("Standard_NotReal_v999") is None
