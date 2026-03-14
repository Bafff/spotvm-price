"""Integration tests for CLI argument parsing and main() entrypoint."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from spotvm.cli import _run_single_analysis, build_parser, main
from spotvm.config import ToolConfig


def _analysis_args(**overrides):
    defaults = {
        "no_color": True,
        "min_vcpu": None,
        "min_ram": None,
        "no_max_limit": False,
        "explicit_sizes": False,
        "max_price": None,
        "max_eviction": None,
        "min_performance": None,
        "csv": None,
        "results_dir": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestBuildParser:
    """Tests for argument parsing."""

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

    @patch("spotvm.cli._run_single_analysis")
    def test_pricing_only_config_accepts_default_desired_count(self, mock_run_single_analysis, tmp_path):
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
        )
        config_path = tmp_path / "spotvm.json"
        config_path.write_text(json.dumps(config.to_dict()), encoding="utf-8")

        rc = main(
            [
                "--config",
                str(config_path),
                "--no-color",
            ]
        )

        assert rc == 0
        called_config = mock_run_single_analysis.call_args.kwargs["config"]
        assert called_config.desired_count == 1
        assert called_config.enable_placement is False

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

    def test_help_describes_effective_desired_count_default(self):
        parser = build_parser()
        help_text = " ".join(parser.format_help().split())

        assert "effective default" in help_text
        assert "placement-check" in help_text


class TestToolConfigValidation:
    """Tests for ToolConfig validation logic."""

    def test_no_subscription_without_placement_succeeds(self):
        from spotvm.config import ToolConfig

        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        assert config.subscription_id == ""
        assert config.enable_placement is False

    def test_pricing_only_config_omits_placement_fields(self):
        from spotvm.config import ToolConfig

        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        payload = config.to_dict()
        assert "desired_count" not in payload
        assert "availability_zones" not in payload

    def test_placement_without_subscription_fails(self):
        from spotvm.config import ToolConfig

        with pytest.raises(ValueError, match="subscription_id is required"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], enable_placement=True)

    def test_non_default_desired_count_without_placement_fails(self):
        from spotvm.config import ToolConfig

        with pytest.raises(ValueError, match="desired_count requires enable_placement"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], desired_count=2)

    def test_availability_zones_without_placement_fails(self):
        from spotvm.config import ToolConfig

        with pytest.raises(ValueError, match="availability_zones requires enable_placement"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], availability_zones=True)

    def test_placement_with_subscription_succeeds(self):
        from spotvm.config import ToolConfig

        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            enable_placement=True,
            subscription_id="abc-123",
        )
        assert config.enable_placement is True

    def test_invalid_cpu_arch_fails(self):
        from spotvm.config import ToolConfig

        with pytest.raises(ValueError, match="cpu_arch"):
            ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], cpu_arch="mips")

    def test_valid_cpu_arch_normalizes(self):
        from spotvm.config import ToolConfig

        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], cpu_arch="X64")
        assert config.cpu_arch == "x64"


class TestMainWithMocks:
    """Tests for main() with mocked Azure API calls."""

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    def test_basic_run_returns_zero(self, mock_fetch_hist, mock_client_cls, mock_auth_cls, capsys):
        mock_fetch_hist.return_value = []
        rc = main(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
                "--no-color",
            ]
        )
        assert rc == 0
        mock_fetch_hist.assert_called_once()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_placement_scores")
    @patch("spotvm.cli.fetch_historical_metrics")
    def test_placement_not_called_without_flag(
        self, mock_fetch_hist, mock_fetch_placement, mock_client_cls, mock_auth_cls, capsys
    ):
        mock_fetch_hist.return_value = []
        rc = main(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
                "--no-color",
            ]
        )
        assert rc == 0
        mock_fetch_hist.assert_called_once()
        mock_fetch_placement.assert_not_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    def test_no_color_flag_works(self, mock_fetch_hist, mock_client_cls, mock_auth_cls, capsys):
        mock_fetch_hist.return_value = []
        rc = main(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
                "--no-color",
            ]
        )
        assert rc == 0
        captured = capsys.readouterr()
        # No ANSI escape codes in output
        assert "\033[" not in captured.out

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_placement_scores")
    @patch("spotvm.cli.fetch_historical_metrics")
    def test_placement_check_with_subscription(
        self, mock_fetch_hist, mock_fetch_placement, mock_client_cls, mock_auth_cls, capsys
    ):
        mock_fetch_hist.return_value = []
        mock_fetch_placement.return_value = []
        rc = main(
            [
                "--subscription-id",
                "00000000-0000-0000-0000-000000000000",
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D4s_v5",
                "--placement-check",
                "--no-color",
            ]
        )
        assert rc == 0
        mock_fetch_placement.assert_called_once()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_successful_run_prints_ranked_table(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = object()
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = _analysis_args()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        _run_single_analysis(
            args=args,
            config=config,
            logger=MagicMock(),
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "RANKED TABLE" in captured.out
        mock_filter_requirements.assert_called_once_with(
            [candidate],
            min_vcpu=None,
            min_ram=None,
            cpu_arch=None,
            no_max_limit=False,
        )
        mock_render_table.assert_called_once_with(
            [candidate],
            show_placement=False,
            show_baseline=False,
        )

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_explicit_sizes_bypass_bounded_hardware_window(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = object()
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = _analysis_args(min_vcpu=4, min_ram=16, explicit_sizes=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D64s_v5"])

        _run_single_analysis(
            args=args,
            config=config,
            logger=MagicMock(),
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "RANKED TABLE" in captured.out
        mock_filter_requirements.assert_called_once_with(
            [candidate],
            min_vcpu=4,
            min_ram=16,
            cpu_arch=None,
            no_max_limit=True,
        )

    @patch("spotvm.cli._run_single_analysis")
    @patch("spotvm.cli.discover_skus")
    def test_config_sizes_do_not_trigger_auto_discovery(
        self,
        mock_discover_skus,
        mock_run_single_analysis,
        tmp_path,
    ):
        config_path = tmp_path / "spotvm.json"
        config_path.write_text(
            json.dumps(
                {
                    "regions": ["centralus"],
                    "sizes": ["Standard_D4ps_v5"],
                    "cpu_arch": "arm",
                }
            ),
            encoding="utf-8",
        )
        mock_discover_skus.return_value = ["Standard_D2ps_v5"]

        rc = main(
            [
                "--config",
                str(config_path),
                "--no-color",
            ]
        )

        assert rc == 0
        mock_discover_skus.assert_not_called()
        args = mock_run_single_analysis.call_args.kwargs["args"]
        assert args.explicit_sizes is True
        config = mock_run_single_analysis.call_args.kwargs["config"]
        assert config.sizes == ["Standard_D4ps_v5"]
        assert config.cpu_arch == "arm"

    @patch("spotvm.cli._run_single_analysis")
    def test_cli_sizes_mark_run_as_explicit_for_hardware_window(
        self,
        mock_run_single_analysis,
    ):
        rc = main(
            [
                "--regions",
                "centralus",
                "--sizes",
                "Standard_D64s_v5",
                "--min-vcpu",
                "4",
                "--min-ram",
                "16",
                "--no-color",
            ]
        )

        assert rc == 0
        args = mock_run_single_analysis.call_args.kwargs["args"]
        assert args.explicit_sizes is True

    @patch("spotvm.cli._run_single_analysis")
    @patch("spotvm.cli.discover_skus")
    def test_config_cpu_arch_triggers_auto_discovery(
        self,
        mock_discover_skus,
        mock_run_single_analysis,
        tmp_path,
    ):
        config_path = tmp_path / "spotvm.json"
        config_path.write_text(
            json.dumps(
                {
                    "regions": ["centralus"],
                    "cpu_arch": "arm",
                }
            ),
            encoding="utf-8",
        )
        mock_discover_skus.return_value = ["Standard_D2ps_v5"]

        rc = main(
            [
                "--config",
                str(config_path),
                "--no-color",
            ]
        )

        assert rc == 0
        mock_discover_skus.assert_called_once_with(
            min_vcpu=None,
            min_ram=None,
            cpu_arch="arm",
        )
        config = mock_run_single_analysis.call_args.kwargs["config"]
        assert config.sizes == ["Standard_D2ps_v5"]
        assert config.cpu_arch == "arm"

    @patch("spotvm.cli._run_single_analysis")
    @patch("spotvm.cli.discover_skus")
    def test_config_cpu_arch_is_normalized_before_auto_discovery(
        self,
        mock_discover_skus,
        mock_run_single_analysis,
        tmp_path,
    ):
        config_path = tmp_path / "spotvm.json"
        config_path.write_text(
            json.dumps(
                {
                    "regions": ["centralus"],
                    "cpu_arch": "ARM",
                }
            ),
            encoding="utf-8",
        )
        mock_discover_skus.return_value = ["Standard_D2ps_v5"]

        rc = main(
            [
                "--config",
                str(config_path),
                "--no-color",
            ]
        )

        assert rc == 0
        mock_discover_skus.assert_called_once_with(
            min_vcpu=None,
            min_ram=None,
            cpu_arch="arm",
        )
        config = mock_run_single_analysis.call_args.kwargs["config"]
        assert config.cpu_arch == "arm"

    @patch("spotvm.cli._run_single_analysis")
    @patch("spotvm.cli.discover_skus")
    def test_main_passes_no_max_limit_through_to_auto_discovery(
        self,
        mock_discover_skus,
        mock_run_single_analysis,
    ):
        mock_discover_skus.return_value = ["Standard_D4as_v5"]

        rc = main(
            [
                "--regions",
                "centralus",
                "--min-vcpu",
                "4",
                "--no-max-limit",
                "--no-color",
            ]
        )

        assert rc == 0
        mock_discover_skus.assert_called_once_with(
            min_vcpu=4,
            min_ram=None,
            cpu_arch=None,
            no_max_limit=True,
        )
        config = mock_run_single_analysis.call_args.kwargs["config"]
        assert config.sizes == ["Standard_D4as_v5"]

    @patch("spotvm.cli.MAX_UNATTENDED_FAILURES", 1)
    @patch("spotvm.cli.time.sleep")
    @patch("spotvm.cli.signal.signal")
    @patch("spotvm.cli._run_single_analysis", side_effect=RuntimeError("boom"))
    def test_unattended_mode_stops_after_unexpected_failure_threshold(
        self,
        mock_run_single_analysis,
        mock_signal,
        mock_sleep,
        caplog,
        capsys,
    ):
        with caplog.at_level(logging.ERROR, logger="spotvm"):
            rc = main(
                [
                    "--regions",
                    "centralus",
                    "--sizes",
                    "Standard_D4s_v5",
                    "--run-unattended",
                    "1",
                    "--no-color",
                ]
            )

        assert rc == 1
        assert mock_run_single_analysis.call_count == 1
        mock_sleep.assert_not_called()
        assert "Unexpected error in unattended run (1/1)" in caplog.text
        assert "Stopping unattended mode after 1 consecutive unexpected errors" in caplog.text
        captured = capsys.readouterr()
        assert "Stopping monitoring after 1 consecutive unexpected errors" in captured.out

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.export_to_csv", side_effect=PermissionError("disk full"))
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_csv_export_failure_does_not_suppress_console_output(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_export_csv,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = object()
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv="results.csv",
            results_dir=None,
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        _run_single_analysis(
            args=args,
            config=config,
            logger=logger,
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "Failed to export CSV" in captured.err
        assert "RANKED TABLE" in captured.out
        logger.error.assert_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_report_write_failure_does_not_suppress_console_output(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = SimpleNamespace(
            recommendation_rank=1,
            region="centralus",
            availability_zone=None,
            vm_size="Standard_D4s_v5",
            cpu_arch="x64",
            placement_score=None,
            quota_available=None,
            price_usd=0.01,
            price_last_updated=None,
            eviction_rate=1.0,
            performance_relative=None,
            price_per_performance=None,
            coremark_score=None,
            coremark_per_vcpu=None,
            notes=None,
        )
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = MagicMock()
        config.save_report.write_text.side_effect = PermissionError("read only file system")

        _run_single_analysis(
            args=args,
            config=config,
            logger=logger,
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "Failed to save report" in captured.err
        assert "RANKED TABLE" in captured.out
        logger.error.assert_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_save_report_creates_parent_directories(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        tmp_path,
        capsys,
    ):
        candidate = SimpleNamespace(
            recommendation_rank=1,
            region="centralus",
            availability_zone=None,
            vm_size="Standard_D4s_v5",
            cpu_arch="x64",
            placement_score=None,
            quota_available=None,
            price_usd=0.01,
            price_last_updated=None,
            eviction_rate=1.0,
            performance_relative=None,
            price_per_performance=None,
            coremark_score=None,
            coremark_per_vcpu=None,
            notes=None,
        )
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = tmp_path / "reports" / "latest.json"

        _run_single_analysis(
            args=args,
            config=config,
            logger=logger,
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "Failed to save report" not in captured.err
        assert config.save_report.exists()
        report_payload = json.loads(config.save_report.read_text(encoding="utf-8"))
        assert report_payload["candidates"][0]["vmSize"] == "Standard_D4s_v5"
        assert "RANKED TABLE" in captured.out
        logger.error.assert_not_called()

    @patch("spotvm.history.save_run_results", side_effect=PermissionError("disk full"))
    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_save_results_failure_does_not_suppress_console_output(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        mock_save_results,
        capsys,
    ):
        candidate = object()
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir="results",
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        _run_single_analysis(
            args=args,
            config=config,
            logger=logger,
            save_results=True,
        )

        captured = capsys.readouterr()
        assert "Failed to save run results" in captured.err
        assert "RANKED TABLE" in captured.out
        logger.warning.assert_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_baseline_footer_explains_heuristic_marker_once(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = SimpleNamespace(
            recommendation_rank=1,
            region="centralus",
            availability_zone=None,
            vm_size="Standard_D4s_v4",
            cpu_arch="x64",
            placement_score=None,
            quota_available=None,
            price_usd=0.01,
            price_last_updated=None,
            eviction_rate=1.0,
            performance_relative=100.0,
            price_per_performance=0.0001,
            performance_basis="heuristic",
            performance_note="Perf % and Price/Perf use the vCPU/RAM heuristic because CoreMark data is unavailable for this comparison.",
            coremark_score=None,
            coremark_per_vcpu=None,
            notes="Heuristic perf*",
        )
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE\nHeuristic perf*"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )
        logger = MagicMock()
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v4"],
            baseline_sku="Standard_D4s_v5",
        )

        _run_single_analysis(
            args=args,
            config=config,
            logger=logger,
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "Heuristic perf*" in captured.out
        assert "* Heuristic perf:" in captured.out
        assert "comparable CoreMark data is unavailable" in captured.out
        assert "Some Perf % / Price/Perf values use a vCPU/RAM heuristic" not in captured.out

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost")
    @patch("spotvm.cli.enrich_with_coremark")
    @patch("spotvm.cli.enrich_with_performance")
    @patch("spotvm.cli.rank_candidates")
    @patch("spotvm.cli.filter_by_requirements")
    @patch("spotvm.cli.merge_datasets")
    @patch("spotvm.cli.summarize_top_candidates")
    @patch("spotvm.cli.render_table")
    def test_json_output_keeps_stdout_machine_readable(
        self,
        mock_render_table,
        mock_summarize,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        candidate = SimpleNamespace(
            recommendation_rank=1,
            region="centralus",
            availability_zone=None,
            vm_size="Standard_D4s_v5",
            cpu_arch="x64",
            placement_score=None,
            quota_available=None,
            price_usd=0.01,
            price_last_updated=None,
            eviction_rate=1.0,
            performance_relative=100.0,
            price_per_performance=0.0001,
            performance_basis="coremark",
            performance_note=None,
            coremark_score=67114,
            coremark_per_vcpu=16778.5,
            notes=None,
        )
        mock_fetch_hist.return_value = []
        mock_merge.return_value = [candidate]
        mock_filter_requirements.return_value = [candidate]
        mock_rank.return_value = [candidate]
        mock_enrich_performance.return_value = [candidate]
        mock_enrich_coremark.return_value = [candidate]
        mock_filter_cost.return_value = [candidate]
        mock_summarize.return_value = []
        mock_render_table.return_value = "RANKED TABLE"

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], emit_json=True)

        _run_single_analysis(
            args=args,
            config=config,
            logger=MagicMock(),
            save_results=False,
        )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["candidates"][0]["vmSize"] == "Standard_D4s_v5"
        assert payload["candidates"][0]["performanceBasis"] == "coremark"
        assert "JSON Output:" not in captured.out
        assert "RANKED TABLE" not in captured.out
        assert captured.err == ""
        mock_render_table.assert_not_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost", return_value=[])
    @patch("spotvm.cli.enrich_with_coremark", return_value=[])
    @patch("spotvm.cli.enrich_with_performance", return_value=[])
    @patch("spotvm.cli.rank_candidates", return_value=[])
    @patch("spotvm.cli.filter_by_requirements", return_value=[])
    @patch("spotvm.cli.merge_datasets", return_value=[])
    @patch("spotvm.cli.render_table")
    def test_empty_ranked_results_emit_json_outputs_empty_payload_only(
        self,
        mock_render_table,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        mock_fetch_hist.return_value = []

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )

        _run_single_analysis(
            args=args,
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], emit_json=True),
            logger=MagicMock(),
            save_results=False,
        )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["candidates"] == []
        assert captured.err == ""
        mock_render_table.assert_not_called()

    @patch("spotvm.cli.AzureAuthenticator")
    @patch("spotvm.cli.AzureRestClient")
    @patch("spotvm.cli.fetch_historical_metrics")
    @patch("spotvm.cli.filter_by_cost", return_value=[])
    @patch("spotvm.cli.enrich_with_coremark", return_value=[])
    @patch("spotvm.cli.enrich_with_performance", return_value=[])
    @patch("spotvm.cli.rank_candidates", return_value=[])
    @patch("spotvm.cli.filter_by_requirements", return_value=[])
    @patch("spotvm.cli.merge_datasets", return_value=[])
    @patch("spotvm.cli.render_table")
    def test_empty_ranked_results_print_message(
        self,
        mock_render_table,
        mock_merge,
        mock_filter_requirements,
        mock_rank,
        mock_enrich_performance,
        mock_enrich_coremark,
        mock_filter_cost,
        mock_fetch_hist,
        mock_client_cls,
        mock_auth_cls,
        capsys,
    ):
        mock_fetch_hist.return_value = []

        args = SimpleNamespace(
            no_color=True,
            min_vcpu=None,
            min_ram=None,
            max_price=None,
            max_eviction=None,
            min_performance=None,
            csv=None,
            results_dir=None,
        )

        _run_single_analysis(
            args=args,
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            logger=MagicMock(),
            save_results=False,
        )

        captured = capsys.readouterr()
        assert "No candidates match the specified filters" in captured.out
        mock_render_table.assert_not_called()
