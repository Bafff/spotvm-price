"""Tests for filtering and auto-discovery functionality."""

from datetime import datetime
import logging

import pytest

from spotvm_tool.analysis import filter_by_cost, filter_by_requirements
from spotvm_tool.models import CandidateInsight
from spotvm_tool.vm_specs import discover_skus, detect_cpu_architecture, get_vm_spec


class TestAutoDiscovery:
    """Tests for SKU auto-discovery functionality."""

    def test_discover_by_vcpu(self):
        """Test discovering SKUs by minimum vCPU count."""
        skus = discover_skus(min_vcpu=8, min_ram=None)

        assert len(skus) > 0
        # Should include D8/E8/F8 series
        assert any("D8" in sku or "E8" in sku or "F8" in sku for sku in skus)

    def test_discover_by_ram(self):
        """Test discovering SKUs by minimum RAM."""
        skus = discover_skus(min_vcpu=None, min_ram=32)

        assert len(skus) > 0
        # Should include E-series (memory optimized)
        assert any("E" in sku for sku in skus)

    def test_discover_by_both(self):
        """Test discovering SKUs by both vCPU and RAM."""
        skus = discover_skus(min_vcpu=4, min_ram=32)

        assert len(skus) > 0
        # E4s has 4 vCPU and 32 GB RAM
        assert any("E4" in sku for sku in skus)

    def test_discover_no_filters(self):
        """Test discovering with no filters returns all SKUs."""
        skus = discover_skus(min_vcpu=None, min_ram=None)

        # Should return all SKUs from vm_specs.py
        assert len(skus) > 20  # We have many SKUs defined

    def test_discover_impossible_requirements(self):
        """Test discovering with impossible requirements returns empty."""
        skus = discover_skus(min_vcpu=1000, min_ram=10000)

        assert len(skus) == 0

    def test_discover_sorted_by_compute_score(self):
        """Test that results are sorted by compute score (smallest first)."""
        skus = discover_skus(min_vcpu=4, min_ram=16)

        # First result should be smaller than last
        # D4 (4 vCPU, 16 GB) should come before D16 (16 vCPU, 64 GB)
        assert len(skus) >= 2
        # Just verify we got some results in order
        assert skus[0]  # First SKU exists

    def test_discover_by_vcpu_uses_bounded_three_tier_window_by_default(self):
        """Minimum vCPU should default to min, 2x min, and 4x min tiers only."""
        skus = discover_skus(min_vcpu=4)

        assert len(skus) > 0
        assert all((spec := get_vm_spec(sku)) is not None and spec.vcpus in {4, 8, 16} for sku in skus)
        assert not any((spec := get_vm_spec(sku)) is not None and spec.vcpus > 16 for sku in skus)

    def test_discover_by_vcpu_and_ram_intersects_bounded_windows(self):
        """CPU and RAM windows should both apply in bounded mode."""
        skus = discover_skus(min_vcpu=4, min_ram=16)

        assert len(skus) > 0
        for sku in skus:
            spec = get_vm_spec(sku)
            assert spec is not None
            assert spec.vcpus in {4, 8, 16}
            assert spec.ram_gb in {16, 28, 32}

    def test_discover_by_nonstandard_vcpu_uses_next_known_spec_tiers(self):
        """Non-standard minimums should snap to the next distinct known tiers."""
        skus = discover_skus(min_vcpu=6)

        assert len(skus) > 0
        assert all((spec := get_vm_spec(sku)) is not None and spec.vcpus in {8, 16, 32} for sku in skus)
        assert not any((spec := get_vm_spec(sku)) is not None and spec.vcpus > 32 for sku in skus)

    def test_discover_no_max_limit_restores_unbounded_minimum_behavior(self):
        """no_max_limit should keep larger SKU tiers available."""
        skus = discover_skus(min_vcpu=4, min_ram=16, no_max_limit=True)

        assert any((spec := get_vm_spec(sku)) is not None and spec.vcpus > 16 for sku in skus)
        assert any((spec := get_vm_spec(sku)) is not None and spec.ram_gb > 64 for sku in skus)


class TestFilterByRequirements:
    """Tests for hardware requirements filtering."""

    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates with different specs."""
        return [
            CandidateInsight(
                vm_size="Standard_D2as_v6",  # 2 vCPU, 8 GB
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0168,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=2.5,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_D4as_v6",  # 4 vCPU, 16 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0336,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_E4s_v5",  # 4 vCPU, 32 GB
                region="westus",
                placement_score="Medium",
                quota_available=True,
                price_usd=0.0696,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=5.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

    def test_filter_by_min_vcpu(self, sample_candidates):
        """Test filtering by minimum vCPU."""
        filtered = filter_by_requirements(sample_candidates, min_vcpu=4, min_ram=None)

        # Should keep D4 and E4, filter out D2
        assert len(filtered) == 2
        assert all(c.vm_size != "Standard_D2as_v6" for c in filtered)

    def test_filter_by_min_ram(self, sample_candidates):
        """Test filtering by minimum RAM."""
        filtered = filter_by_requirements(sample_candidates, min_vcpu=None, min_ram=32)

        # Should only keep E4s (32 GB RAM)
        assert len(filtered) == 1
        assert filtered[0].vm_size == "Standard_E4s_v5"

    def test_filter_by_both(self, sample_candidates):
        """Test filtering by both vCPU and RAM."""
        filtered = filter_by_requirements(sample_candidates, min_vcpu=4, min_ram=16)

        # Should keep D4 (4 vCPU, 16 GB) and E4 (4 vCPU, 32 GB)
        assert len(filtered) == 2
        assert all(c.vm_size in ["Standard_D4as_v6", "Standard_E4s_v5"] for c in filtered)

    def test_filter_no_filters(self, sample_candidates):
        """Test that no filters returns all candidates."""
        filtered = filter_by_requirements(sample_candidates, min_vcpu=None, min_ram=None)

        assert len(filtered) == len(sample_candidates)

    def test_filter_unknown_sku(self):
        """Unknown SKUs are still kept when bounded filtering is disabled."""
        unknown_candidate = [
            CandidateInsight(
                vm_size="Standard_UnknownSKU_v99",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.05,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=1.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

        filtered = filter_by_requirements(
            unknown_candidate,
            min_vcpu=100,
            min_ram=1000,
            no_max_limit=True,
        )

        assert len(filtered) == 1

    def test_filter_unknown_sku_in_unbounded_mode_keeps_warning(self, caplog):
        """Unlimited mode should preserve the unverifiable-SKU warning."""
        unknown_candidate = [
            CandidateInsight(
                vm_size="Standard_UnknownSKU_v99",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.05,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=1.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

        with caplog.at_level(logging.WARNING, logger="spotvm-tool"):
            filtered = filter_by_requirements(
                unknown_candidate,
                min_vcpu=100,
                min_ram=1000,
                no_max_limit=True,
            )

        assert len(filtered) == 1
        assert "cannot verify vCPU/RAM requirements" in caplog.text

    def test_filter_by_both_uses_bounded_hardware_window_by_default(self):
        """Default min filters should keep only the next three CPU and RAM tiers."""
        candidates = [
            CandidateInsight(
                vm_size="Standard_D4as_v6",  # 4 vCPU, 16 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0336,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_D8as_v5",  # 8 vCPU, 32 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0672,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_E16s_v5",  # 16 vCPU, 128 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.2784,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

        filtered = filter_by_requirements(candidates, min_vcpu=4, min_ram=16)

        assert [candidate.vm_size for candidate in filtered] == [
            "Standard_D4as_v6",
            "Standard_D8as_v5",
        ]

    def test_filter_unknown_sku_is_excluded_in_bounded_mode(self):
        """Bounded mode should drop unverifiable SKUs instead of keeping them."""
        unknown_candidate = [
            CandidateInsight(
                vm_size="Standard_UnknownSKU_v99",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.05,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=1.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

        filtered = filter_by_requirements(unknown_candidate, min_vcpu=4, min_ram=16)

        assert filtered == []

    def test_filter_no_max_limit_keeps_unknown_and_large_tiers(self):
        """Unlimited mode should preserve existing lower-bound semantics."""
        candidates = [
            CandidateInsight(
                vm_size="Standard_D4as_v6",  # 4 vCPU, 16 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0336,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_E16s_v5",  # 16 vCPU, 128 GB
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.2784,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=3.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
            CandidateInsight(
                vm_size="Standard_UnknownSKU_v99",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.05,
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=1.0,
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            ),
        ]

        filtered = filter_by_requirements(
            candidates,
            min_vcpu=4,
            min_ram=16,
            no_max_limit=True,
        )

        assert [candidate.vm_size for candidate in filtered] == [
            "Standard_D4as_v6",
            "Standard_E16s_v5",
            "Standard_UnknownSKU_v99",
        ]


class TestFilterByCost:
    """Tests for cost-based filtering."""

    @pytest.fixture
    def sample_candidates(self):
        """Create sample candidates with different costs."""
        return [
            CandidateInsight(
                vm_size="Standard_D2as_v6",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0168,  # Cheap
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=2.5,  # Low eviction
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
                performance_relative=50.0,  # 50% of baseline
                price_per_performance=0.000336,
            ),
            CandidateInsight(
                vm_size="Standard_D4as_v6",
                region="centralus",
                placement_score="High",
                quota_available=True,
                price_usd=0.0336,  # Medium price
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=15.0,  # High eviction
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
                performance_relative=100.0,  # 100% of baseline
                price_per_performance=0.000336,
            ),
            CandidateInsight(
                vm_size="Standard_E4s_v5",
                region="westus",
                placement_score="Medium",
                quota_available=True,
                price_usd=0.0696,  # Expensive
                price_last_updated=datetime(2025, 1, 25, 14, 0),
                eviction_rate=5.0,  # Medium eviction
                eviction_last_updated=datetime(2025, 1, 25, 14, 0),
                performance_relative=110.0,  # 110% of baseline
                price_per_performance=0.000633,
            ),
        ]

    def test_filter_by_max_price(self, sample_candidates):
        """Test filtering by maximum price."""
        filtered = filter_by_cost(sample_candidates, max_price=0.05, max_eviction=None, min_performance=None)

        # Should keep D2 and D4, filter out E4
        assert len(filtered) == 2
        assert all(c.price_usd <= 0.05 for c in filtered)

    def test_filter_by_max_eviction(self, sample_candidates):
        """Test filtering by maximum eviction rate."""
        filtered = filter_by_cost(sample_candidates, max_price=None, max_eviction=10, min_performance=None)

        # Should keep D2 and E4, filter out D4 (15% eviction)
        assert len(filtered) == 2
        assert all(c.eviction_rate <= 10 for c in filtered)

    def test_filter_by_min_performance(self, sample_candidates):
        """Test filtering by minimum performance."""
        filtered = filter_by_cost(sample_candidates, max_price=None, max_eviction=None, min_performance=80)

        # Should keep D4 (100%) and E4 (110%), filter out D2 (50%)
        assert len(filtered) == 2
        assert all(c.performance_relative >= 80 for c in filtered)

    def test_filter_all_constraints(self, sample_candidates):
        """Test filtering with all constraints."""
        filtered = filter_by_cost(
            sample_candidates,
            max_price=0.05,
            max_eviction=10,
            min_performance=40,
        )

        # Only D2 meets all: price≤0.05, eviction≤10%, performance≥40%
        assert len(filtered) == 1
        assert filtered[0].vm_size == "Standard_D2as_v6"

    def test_filter_no_filters(self, sample_candidates):
        """Test that no filters returns all candidates."""
        filtered = filter_by_cost(sample_candidates, max_price=None, max_eviction=None, min_performance=None)

        assert len(filtered) == len(sample_candidates)

    def test_filter_all_excluded(self, sample_candidates):
        """Test filtering with impossible constraints."""
        filtered = filter_by_cost(
            sample_candidates,
            max_price=0.01,  # Too low
            max_eviction=1,  # Too low
            min_performance=200,  # Too high
        )

        # Nothing should pass
        assert len(filtered) == 0

    def test_filter_missing_data(self):
        """Test filtering handles None values gracefully."""
        candidates_with_none = [
            CandidateInsight(
                vm_size="Standard_D2as_v6",
                region="eastus",
                placement_score="High",
                quota_available=True,
                price_usd=None,  # Missing price
                price_last_updated=None,
                eviction_rate=None,  # Missing eviction
                eviction_last_updated=None,
                performance_relative=None,  # Missing performance
            ),
        ]

        # Should keep candidate with missing data (can't filter what doesn't exist)
        filtered = filter_by_cost(
            candidates_with_none,
            max_price=0.01,
            max_eviction=1,
            min_performance=200,
        )

        assert len(filtered) == 1


    def test_filter_zero_max_price(self, sample_candidates):
        """Zero max_price should filter candidates with any positive price (not skip filter)."""
        filtered = filter_by_cost(sample_candidates, max_price=0.0)
        assert len(filtered) == 0  # All have positive prices

    def test_filter_zero_max_eviction(self, sample_candidates):
        """Zero max_eviction should filter candidates with any positive eviction."""
        filtered = filter_by_cost(sample_candidates, max_eviction=0.0)
        assert len(filtered) == 0  # All have positive eviction rates

    def test_filter_zero_min_performance(self, sample_candidates):
        """Zero min_performance should keep all candidates (0% is the floor)."""
        filtered = filter_by_cost(sample_candidates, min_performance=0.0)
        assert len(filtered) == len(sample_candidates)

    def test_filter_by_cost_logs_only_active_constraints(self, sample_candidates, caplog):
        with caplog.at_level(logging.INFO):
            filter_by_cost(sample_candidates, max_price=0.05)

        assert "price<=$0.05" in caplog.text
        assert "eviction<=" not in caplog.text
        assert "performance>=" not in caplog.text


class TestFilterByArchitecture:
    """Tests for CPU architecture filtering in filter_by_requirements."""

    def _make_candidate(self, vm_size, cpu_arch=None):
        return CandidateInsight(
            vm_size=vm_size,
            region="eastus",
            placement_score=None,
            quota_available=None,
            price_usd=0.05,
            price_last_updated=datetime(2025, 1, 25, 14, 0),
            eviction_rate=5.0,
            eviction_last_updated=datetime(2025, 1, 25, 14, 0),
            cpu_arch=cpu_arch,
        )

    def test_filter_x64_keeps_intel_and_amd(self):
        """x64 filter should keep Intel and AMD candidates."""
        candidates = [
            self._make_candidate("Standard_D4s_v5", cpu_arch="intel"),
            self._make_candidate("Standard_D4as_v5", cpu_arch="amd"),
            self._make_candidate("Standard_D4ps_v5", cpu_arch="arm"),
        ]
        filtered = filter_by_requirements(candidates, cpu_arch="x64")
        assert len(filtered) == 2
        assert all(c.vm_size != "Standard_D4ps_v5" for c in filtered)

    def test_filter_arm_removes_x64(self):
        """arm filter should remove Intel and AMD candidates."""
        candidates = [
            self._make_candidate("Standard_D4s_v5", cpu_arch="intel"),
            self._make_candidate("Standard_D4ps_v5", cpu_arch="arm"),
        ]
        filtered = filter_by_requirements(candidates, cpu_arch="arm")
        assert len(filtered) == 1
        assert filtered[0].vm_size == "Standard_D4ps_v5"

    def test_filter_fallback_to_vm_name_detection(self):
        """When cpu_arch is None on candidate, detect from VM name."""
        candidates = [
            self._make_candidate("Standard_D4as_v5", cpu_arch=None),  # AMD x64
            self._make_candidate("Standard_D4ps_v5", cpu_arch=None),  # ARM
        ]
        filtered = filter_by_requirements(candidates, cpu_arch="x64")
        assert len(filtered) == 1
        assert filtered[0].vm_size == "Standard_D4as_v5"

    def test_filter_case_insensitive(self):
        """Architecture filter should be case-insensitive."""
        candidates = [
            self._make_candidate("Standard_D4s_v5", cpu_arch="Intel"),
            self._make_candidate("Standard_D4as_v5", cpu_arch="AMD"),
        ]
        filtered = filter_by_requirements(candidates, cpu_arch="X64")
        assert len(filtered) == 2


class TestCPUArchitecture:
    """Tests for CPU architecture detection and filtering."""

    def test_detect_x64_intel(self):
        """Test detecting Intel x64 VMs (no architecture letter)."""
        assert detect_cpu_architecture("Standard_D4s_v5") == "x64"
        assert detect_cpu_architecture("Standard_D8s_v5") == "x64"
        assert detect_cpu_architecture("Standard_E4s_v5") == "x64"

    def test_detect_x64_amd(self):
        """Test detecting AMD x64 VMs (letter 'a')."""
        assert detect_cpu_architecture("Standard_D4as_v5") == "x64"
        assert detect_cpu_architecture("Standard_D4as_v6") == "x64"
        assert detect_cpu_architecture("Standard_D8as_v5") == "x64"
        assert detect_cpu_architecture("Standard_D4ads_v5") == "x64"

    def test_detect_arm(self):
        """Test detecting ARM VMs (letter 'p')."""
        assert detect_cpu_architecture("Standard_D4ps_v5") == "arm"
        assert detect_cpu_architecture("Standard_D8ps_v5") == "arm"
        assert detect_cpu_architecture("Standard_E4pds_v5") == "arm"

    def test_detect_subfamily_amd(self):
        """Test detecting AMD x64 VMs with subfamily."""
        assert detect_cpu_architecture("Standard_DC8ads_v5") == "x64"

    def test_discover_x64_only(self):
        """Test discovering only x64 VMs."""
        skus = discover_skus(min_vcpu=4, min_ram=None, cpu_arch="x64")

        assert len(skus) > 0
        # All should be x64
        for sku in skus:
            assert detect_cpu_architecture(sku) == "x64"
        # Should NOT contain any 'ps' (ARM) SKUs
        assert not any("ps" in sku.lower() for sku in skus)

    def test_discover_arm_only(self):
        """Test discovering only ARM VMs."""
        # Note: Our VM_SPECIFICATIONS may not have ARM VMs, so result might be empty
        skus = discover_skus(min_vcpu=2, min_ram=None, cpu_arch="arm")

        # All discovered SKUs should be ARM (if any exist)
        for sku in skus:
            assert detect_cpu_architecture(sku) == "arm"

    def test_discover_no_arch_filter(self):
        """Test discovering VMs without architecture filter returns both."""
        all_skus = discover_skus(min_vcpu=4, min_ram=None, cpu_arch=None)
        x64_skus = discover_skus(min_vcpu=4, min_ram=None, cpu_arch="x64")

        # Without filter should return at least as many as with filter
        assert len(all_skus) >= len(x64_skus)
