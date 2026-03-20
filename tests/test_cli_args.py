"""Tests for CLI argument parsing and config-building helpers."""

from __future__ import annotations

import argparse
import json
from unittest.mock import MagicMock, patch

import pytest

from spotvm.cli import (
    _add_filtering_arguments,
    _add_history_arguments,
    _build_runtime_config,
    _discover_requested_sizes,
    _resolve_effective_cpu_arch,
    _resolve_requested_sizes,
    build_parser,
    main,
)


class TestBuildParser:
    """Tests for argument parsing."""

    def test_add_filtering_arguments_accepts_hardware_and_cost_filters(self):
        parser = argparse.ArgumentParser()
        _add_filtering_arguments(parser)

        args = parser.parse_args(
            [
                "--min-vcpu",
                "4",
                "--min-ram",
                "8",
                "--no-max-limit",
                "--cpu-arch",
                "arm",
                "--max-price",
                "0.10",
                "--max-eviction",
                "15",
                "--min-performance",
                "90",
            ]
        )

        assert args.min_vcpu == 4
        assert args.min_ram == 8
        assert args.no_max_limit is True
        assert args.cpu_arch == "arm"
        assert args.max_price == 0.10
        assert args.max_eviction == 15.0
        assert args.min_performance == 90.0

    def test_add_history_arguments_accepts_history_and_export_flags(self, tmp_path):
        parser = argparse.ArgumentParser()
        _add_history_arguments(parser)
        results_dir = tmp_path / "results"
        history_output = tmp_path / "history.csv"
        csv_output = tmp_path / "results.csv"

        args = parser.parse_args(
            [
                "--save-results",
                "--run-unattended",
                "15",
                "--results-dir",
                str(results_dir),
                "--analyze-history",
                "--history-depth",
                "7",
                "--history-output",
                str(history_output),
                "--csv",
                str(csv_output),
            ]
        )

        assert args.save_results is True
        assert args.run_unattended == 15
        assert args.results_dir == results_dir
        assert args.analyze_history is True
        assert args.history_depth == 7
        assert args.history_output == history_output
        assert args.csv == csv_output

    def test_no_args_shows_help(self, capsys):
        rc = main([])
        assert rc == 0
        captured = capsys.readouterr()
        assert "spotvm" in captured.out
        assert "--regions" in captured.out

    def test_missing_regions_errors(self):
        with pytest.raises(SystemExit):
            main(["--sizes", "Standard_D4s_v5"])

    def test_missing_sizes_errors(self):
        with pytest.raises(SystemExit):
            main(["--regions", "centralus"])

    def test_placement_check_without_subscription_errors(self):
        with pytest.raises(SystemExit):
            main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4s_v5",
                    "--placement-check",
                ]
            )

    def test_availability_zones_without_placement_errors(self):
        with pytest.raises(SystemExit):
            main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4s_v5",
                    "--availability-zones",
                ]
            )

    @pytest.mark.parametrize("desired_count", [1, 5])
    def test_desired_count_without_placement_errors(self, desired_count):
        with pytest.raises(SystemExit):
            main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4s_v5",
                    "--desired-count",
                    str(desired_count),
                ]
            )

    def test_min_performance_without_baseline_errors(self):
        with pytest.raises(SystemExit):
            main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4s_v5",
                    "--min-performance",
                    "80",
                ]
            )

    @pytest.mark.parametrize(
        ("config_payload", "error_text"),
        [
            (
                {
                    "regions": ["centralus"],
                    "sizes": ["Standard_D4s_v5"],
                    "desired_count": 1,
                },
                "--desired-count requires --placement-check",
            ),
            (
                {
                    "regions": ["centralus"],
                    "sizes": ["Standard_D4s_v5"],
                    "desired_count": 5,
                },
                "--desired-count requires --placement-check",
            ),
            (
                {
                    "regions": ["centralus"],
                    "sizes": ["Standard_D4s_v5"],
                    "availability_zones": True,
                },
                "--availability-zones requires --placement-check",
            ),
        ],
    )
    def test_config_placement_fields_require_placement_mode(self, tmp_path, config_payload, error_text, capsys):
        config_path = tmp_path / "spotvm.json"
        config_path.write_text(json.dumps(config_payload), encoding="utf-8")

        with pytest.raises(SystemExit):
            main(["--config", str(config_path)])

        captured = capsys.readouterr()
        assert error_text in captured.err

    def test_build_runtime_config_accepts_pricing_only_defaults(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
            ]
        )

        config = _build_runtime_config(
            parser=parser,
            args=args,
            base_config={},
            sizes=args.sizes,
        )

        assert config.desired_count == 1
        assert config.enable_placement is False
        assert config.include_databricks_cost is False
        assert config.include_photon_cost is False

    def test_parser_accepts_databricks_pricing_flags(self):
        args = build_parser().parse_args(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4ps_v6",
                "--include-databricks-cost",
                "--include-photon-cost",
                "--refresh-databricks-catalog",
            ]
        )

        assert args.include_databricks_cost is True
        assert args.include_photon_cost is True
        assert args.refresh_databricks_catalog is True

    def test_include_photon_cost_without_databricks_errors(self):
        with pytest.raises(SystemExit):
            main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4ps_v6",
                    "--include-photon-cost",
                ]
            )

    def test_build_runtime_config_accepts_databricks_pricing_flags(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4ps_v6",
                "--include-databricks-cost",
                "--include-photon-cost",
            ]
        )

        config = _build_runtime_config(
            parser=parser,
            args=args,
            base_config={},
            sizes=args.sizes,
        )

        assert config.include_databricks_cost is True
        assert config.include_photon_cost is True

    def test_build_runtime_config_uses_config_placement_for_cli_desired_count(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--config",
                "ignored.json",
                "--desired-count",
                "5",
            ]
        )
        base_config = {
            "regions": ["centralus"],
            "sizes": ["Standard_D4s_v5"],
            "enable_placement": True,
            "subscription_id": "sub-id",
        }

        config = _build_runtime_config(
            parser=parser,
            args=args,
            base_config=base_config,
            sizes=base_config["sizes"],
        )

        assert config.enable_placement is True
        assert config.desired_count == 5

    def test_build_runtime_config_exits_when_parser_error_is_overridden(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
            ]
        )
        parser.error = MagicMock(return_value=None)

        with pytest.raises(SystemExit) as excinfo:
            _build_runtime_config(
                parser=parser,
                args=args,
                base_config={"cpu_arch": "mips"},
                sizes=args.sizes,
            )

        assert excinfo.value.code == 2
        parser.error.assert_called_once()

    def test_parser_accepts_all_documented_args(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
                "--os-type",
                "linux",
                "--no-color",
                "--baseline-sku",
                "Standard_D4as_v6",
                "--min-vcpu",
                "4",
                "--min-ram",
                "8",
                "--no-max-limit",
                "--cpu-arch",
                "x64",
                "--max-price",
                "0.10",
                "--max-eviction",
                "10",
                "--limit",
                "5",
                "--verbose",
            ]
        )
        assert args.regions == ["centralus"]
        assert args.sizes == ["Standard_D4s_v5"]
        assert args.cpu_arch == "x64"
        assert args.no_max_limit is True
        assert args.max_price == 0.10
        assert args.max_eviction == 10.0

    def test_help_describes_bounded_hardware_windows_and_escape_hatch(self):
        parser = build_parser()
        help_text = parser.format_help()

        assert "--no-max-limit" in help_text
        assert "next three distinct" in help_text
        assert "specs database" in help_text

    def test_help_describes_databricks_aware_max_price_filtering(self):
        parser = build_parser()
        help_text = " ".join(parser.format_help().split())

        assert "--max-price" in help_text
        assert "combined VM + Databricks hourly cost" in help_text

    def test_help_describes_effective_desired_count_default(self):
        parser = build_parser()
        help_text = " ".join(parser.format_help().split())

        assert "effective default" in help_text
        assert "placement-check" in help_text

    def test_help_describes_photon_as_full_rate_not_surcharge(self):
        parser = build_parser()
        help_text = " ".join(parser.format_help().split())

        assert "--include-photon-cost" in help_text
        assert "full Photon DBU rate" in help_text

    def test_resolve_effective_cpu_arch_normalizes_config_value(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "ignored.json"])

        cpu_arch = _resolve_effective_cpu_arch(
            parser=parser,
            args=args,
            base_config={"cpu_arch": "ARM"},
        )

        assert cpu_arch == "arm"

    def test_resolve_effective_cpu_arch_exits_when_parser_error_is_overridden(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "ignored.json"])
        parser.error = MagicMock(return_value=None)

        with pytest.raises(SystemExit) as excinfo:
            _resolve_effective_cpu_arch(
                parser=parser,
                args=args,
                base_config={"cpu_arch": 123},
            )

        assert excinfo.value.code == 2
        parser.error.assert_called_once()

    @patch("spotvm.cli.discover_skus", return_value=["Standard_D2ps_v5", "Standard_D4ps_v5"])
    def test_discover_requested_sizes_logs_requirements_and_summary(self, mock_discover_skus):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--min-vcpu",
                "4",
                "--min-ram",
                "16",
            ]
        )
        logger = MagicMock()

        sizes, attempted = _discover_requested_sizes(
            args=args,
            effective_cpu_arch="arm",
            logger=logger,
        )

        assert attempted is True
        assert sizes == ["Standard_D2ps_v5", "Standard_D4ps_v5"]
        mock_discover_skus.assert_called_once_with(
            min_vcpu=4,
            min_ram=16,
            cpu_arch="arm",
        )
        logger.info.assert_any_call(
            "No --sizes specified, auto-discovering SKUs matching requirements (vCPU≥4, RAM≥16 GB, arch=arm)"
        )
        logger.info.assert_any_call("Auto-discovered 2 SKUs: Standard_D2ps_v5, Standard_D4ps_v5")

    @patch("spotvm.cli.discover_skus")
    def test_resolve_requested_sizes_uses_existing_sizes_without_auto_discovery(self, mock_discover_skus):
        parser = build_parser()
        args = parser.parse_args(["--config", "ignored.json"])
        logger = MagicMock()
        base_config = {
            "regions": ["centralus"],
            "sizes": ["Standard_D4ps_v5"],
            "cpu_arch": "arm",
        }

        sizes, auto_discovery_attempted = _resolve_requested_sizes(
            parser=parser,
            args=args,
            base_config=base_config,
            logger=logger,
        )

        assert sizes == ["Standard_D4ps_v5"]
        assert auto_discovery_attempted is False
        assert args.explicit_sizes is True
        mock_discover_skus.assert_not_called()

    @patch("spotvm.cli.discover_skus", return_value=["Standard_D2ps_v5"])
    def test_resolve_requested_sizes_normalizes_config_cpu_arch_before_auto_discovery(self, mock_discover_skus):
        parser = build_parser()
        args = parser.parse_args(["--config", "ignored.json"])
        logger = MagicMock()
        base_config = {
            "regions": ["centralus"],
            "cpu_arch": "ARM",
        }

        sizes, auto_discovery_attempted = _resolve_requested_sizes(
            parser=parser,
            args=args,
            base_config=base_config,
            logger=logger,
        )

        assert sizes == ["Standard_D2ps_v5"]
        assert auto_discovery_attempted is True
        assert args.explicit_sizes is False
        mock_discover_skus.assert_called_once_with(
            min_vcpu=None,
            min_ram=None,
            cpu_arch="arm",
        )

    @patch("spotvm.cli.discover_skus", return_value=["Standard_D4as_v5"])
    def test_resolve_requested_sizes_passes_no_max_limit_to_auto_discovery(self, mock_discover_skus):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--min-vcpu",
                "4",
                "--no-max-limit",
            ]
        )
        logger = MagicMock()

        sizes, auto_discovery_attempted = _resolve_requested_sizes(
            parser=parser,
            args=args,
            base_config={},
            logger=logger,
        )

        assert sizes == ["Standard_D4as_v5"]
        assert auto_discovery_attempted is True
        mock_discover_skus.assert_called_once_with(
            min_vcpu=4,
            min_ram=None,
            cpu_arch=None,
            no_max_limit=True,
        )
