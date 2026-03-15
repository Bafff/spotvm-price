"""Integration tests for CLI argument parsing and main() entrypoint."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from spotvm.cli import (
    AnalysisRunRequest,
    _add_filtering_arguments,
    _add_history_arguments,
    _build_runtime_config,
    _emit_report_if_requested,
    _persist_analysis_outputs,
    _render_analysis_results,
    _resolve_requested_sizes,
    _run_analysis_mode,
    _run_history_analysis,
    _run_single_analysis,
    _run_unattended_monitoring,
    _save_run_results_if_requested,
    build_parser,
    main,
)
from spotvm.config import ToolConfig
from spotvm.http_client import AzureHttpError
from spotvm.models import HistoricalMetrics
from spotvm.placement_score import PlacementScoreRequest
from spotvm.reporting import RenderOptions
from spotvm.resource_graph import ResourceGraphRequest


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
        "results_dir": Path("./results"),
        "save_results": False,
    }
    defaults.update(overrides)
    return AnalysisRunRequest(**defaults)


def _historical_metric(
    vm_size: str,
    *,
    region: str = "centralus",
    price_usd: float = 0.08,
    eviction_rate: float = 5.0,
) -> HistoricalMetrics:
    timestamp = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return HistoricalMetrics(
        region=region,
        vm_size=vm_size,
        price_usd=price_usd,
        price_last_updated=timestamp,
        eviction_rate=eviction_rate,
        eviction_last_updated=timestamp,
    )


def _stdout_emitter(*values, **kwargs):
    print(*values, **kwargs)  # noqa: T201


def _stderr_emitter(*values, **kwargs):
    print(*values, file=sys.stderr, **kwargs)  # noqa: T201


def _stub_analysis_fetches(monkeypatch, *, historical_metrics, placement_scores=None):
    seen: dict[str, object] = {}

    monkeypatch.setattr("spotvm.cli.AzureAuthenticator", lambda: object())
    monkeypatch.setattr("spotvm.cli.AzureRestClient", lambda authenticator: object())

    def fake_fetch_historical_metrics(client, request):
        seen["historical_request"] = request
        return list(historical_metrics)

    def fake_fetch_placement_scores(client, request):
        seen["placement_request"] = request
        return list(placement_scores or [])

    monkeypatch.setattr("spotvm.cli.fetch_historical_metrics", fake_fetch_historical_metrics)
    monkeypatch.setattr("spotvm.cli.fetch_placement_scores", fake_fetch_placement_scores)
    return seen


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

    def test_help_describes_effective_desired_count_default(self):
        parser = build_parser()
        help_text = " ".join(parser.format_help().split())

        assert "effective default" in help_text
        assert "placement-check" in help_text

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

    @patch("spotvm.cli._run_single_analysis")
    @patch("spotvm.cli._run_history_analysis", return_value=0)
    def test_main_analyze_history_delegates_and_skips_single_run(
        self,
        mock_run_history_analysis,
        mock_run_single_analysis,
        tmp_path,
    ):
        results_dir = tmp_path / "results"
        history_output = tmp_path / "custom-history.csv"

        rc = main(
            [
                "--analyze-history",
                "--results-dir",
                str(results_dir),
                "--history-depth",
                "7",
                "--history-output",
                str(history_output),
                "--no-color",
            ]
        )

        assert rc == 0
        mock_run_history_analysis.assert_called_once()
        kwargs = mock_run_history_analysis.call_args.kwargs
        assert kwargs["results_dir"] == results_dir
        assert kwargs["depth"] == 7
        assert kwargs["history_output"] == history_output
        mock_run_single_analysis.assert_not_called()

    @patch("spotvm.history.analyze_history", return_value=(3, 9, Path("/tmp/history.csv")))
    def test_run_history_analysis_uses_default_output_path_and_prints_summary(
        self,
        mock_analyze_history,
        tmp_path,
        capsys,
    ):
        results_dir = tmp_path / "results"
        logger = MagicMock()

        rc = _run_history_analysis(
            results_dir=results_dir,
            depth=None,
            history_output=None,
            logger=logger,
            emit=_stdout_emitter,
        )

        assert rc == 0
        mock_analyze_history.assert_called_once_with(
            results_dir=results_dir,
            depth=None,
            output_path=results_dir / "history.csv",
        )
        logger.info.assert_called_once_with("Analyzing historical data from %s", results_dir)
        captured = capsys.readouterr()
        assert "Historical Analysis Complete:" in captured.out
        assert "Runs analyzed: 3" in captured.out
        assert "Data points: 9" in captured.out
        assert "Python: pd.read_csv('/tmp/history.csv')" in captured.out

    @patch("spotvm.cli.MAX_UNATTENDED_FAILURES", 1)
    @patch("spotvm.cli.time.sleep")
    @patch("spotvm.cli.signal.signal")
    def test_run_unattended_monitoring_stops_after_unexpected_failure_threshold(
        self,
        mock_signal,
        mock_sleep,
        capsys,
    ):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock(side_effect=RuntimeError("boom"))

        rc = _run_unattended_monitoring(
            request=request,
            config=config,
            logger=logger,
            interval_minutes=1,
            run_single_analysis=run_single_analysis,
            emit=_stdout_emitter,
        )

        assert rc == 1
        assert run_single_analysis.call_count == 1
        mock_sleep.assert_not_called()
        logger.exception.assert_called_once()
        logger.error.assert_called_once_with(
            "Stopping unattended mode after %d consecutive unexpected errors",
            1,
        )
        captured = capsys.readouterr()
        assert "Stopping monitoring after 1 consecutive unexpected errors" in captured.out

    @patch("spotvm.cli.MAX_UNATTENDED_FAILURES", 1)
    @patch("spotvm.cli.signal.signal")
    def test_run_unattended_monitoring_treats_azure_http_errors_as_non_fatal(
        self,
        mock_signal,
        capsys,
    ):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock(
            side_effect=[
                AzureHttpError("https://example.test", 429, "busy"),
                RuntimeError("boom"),
            ]
        )
        should_stop_calls = iter([False, False, False])

        def should_stop() -> bool:
            return next(should_stop_calls)

        rc = _run_unattended_monitoring(
            request=request,
            config=config,
            logger=logger,
            interval_minutes=0,
            run_single_analysis=run_single_analysis,
            emit=_stdout_emitter,
            sleep=lambda seconds: None,
            should_stop=should_stop,
        )

        assert rc == 1
        assert run_single_analysis.call_count == 2
        mock_signal.assert_called()
        logger.exception.assert_called_once()
        logger.error.assert_any_call(
            "Azure API request failed: Azure API request failed (429) for https://example.test: busy"
        )
        logger.error.assert_any_call(
            "Stopping unattended mode after %d consecutive unexpected errors",
            1,
        )
        captured = capsys.readouterr()
        assert "Stopping monitoring after 1 consecutive unexpected errors" in captured.out

    @patch("spotvm.cli.signal.signal")
    def test_run_unattended_monitoring_returns_zero_after_single_success_when_stop_requested(
        self,
        mock_signal,
        capsys,
    ):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        def fake_run_single_analysis(*, request, config, logger):
            return None

        should_stop_calls = iter([False, True, True])

        def should_stop() -> bool:
            return next(should_stop_calls)

        rc = _run_unattended_monitoring(
            request=request,
            config=config,
            logger=logger,
            interval_minutes=1,
            run_single_analysis=fake_run_single_analysis,
            emit=_stdout_emitter,
            sleep=lambda seconds: None,
            install_signal_handlers=False,
            should_stop=should_stop,
        )

        assert rc == 0
        mock_signal.assert_not_called()
        captured = capsys.readouterr()
        assert "Monitoring mode started" in captured.out
        assert "Monitoring stopped after 1 run(s)" in captured.out

    @patch("spotvm.cache.clear")
    def test_run_analysis_mode_clears_cache_before_single_run(self, mock_clear):
        logger = MagicMock()
        request = _analysis_args(save_results=False)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock()
        run_unattended_monitoring = MagicMock()

        rc = _run_analysis_mode(
            request=request,
            config=config,
            logger=logger,
            clear_cache=True,
            interval_minutes=None,
            run_single_analysis=run_single_analysis,
            run_unattended_monitoring=run_unattended_monitoring,
        )

        assert rc == 0
        mock_clear.assert_called_once_with()
        logger.info.assert_called_once_with("Cache cleared")
        run_unattended_monitoring.assert_not_called()
        run_single_analysis.assert_called_once_with(
            request=request,
            config=config,
            logger=logger,
        )

    def test_run_analysis_mode_delegates_to_unattended_and_forces_save_results(self):
        logger = MagicMock()
        request = _analysis_args(save_results=False)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock()
        run_unattended_monitoring = MagicMock(return_value=1)

        rc = _run_analysis_mode(
            request=request,
            config=config,
            logger=logger,
            clear_cache=False,
            interval_minutes=5,
            run_single_analysis=run_single_analysis,
            run_unattended_monitoring=run_unattended_monitoring,
        )

        assert rc == 1
        run_single_analysis.assert_not_called()
        kwargs = run_unattended_monitoring.call_args.kwargs
        assert kwargs["interval_minutes"] == 5
        assert kwargs["request"].save_results is True
        assert kwargs["config"] == config
        assert kwargs["logger"] == logger

    def test_run_analysis_mode_returns_two_for_single_run_azure_http_error(self):
        logger = MagicMock()
        request = _analysis_args()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        error = AzureHttpError("https://example.test", 429, "busy")

        rc = _run_analysis_mode(
            request=request,
            config=config,
            logger=logger,
            clear_cache=False,
            interval_minutes=None,
            run_single_analysis=MagicMock(side_effect=error),
            run_unattended_monitoring=MagicMock(),
        )

        assert rc == 2
        logger.error.assert_called_once_with("Azure API request failed: %s", error)

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
                "--availability-zones",
                "--desired-count",
                "5",
                "--no-color",
            ]
        )
        assert rc == 0
        mock_fetch_placement.assert_called_once()
        placement_request = mock_fetch_placement.call_args.args[1]
        assert isinstance(placement_request, PlacementScoreRequest)
        assert placement_request.subscription_id == "00000000-0000-0000-0000-000000000000"
        assert placement_request.desired_count == 5
        assert placement_request.availability_zones is True

    def test_successful_run_prints_ranked_table(self, monkeypatch, capsys):
        _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[_historical_metric("Standard_D4s_v5")],
        )

        _run_single_analysis(
            request=_analysis_args(),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            logger=logging.getLogger("test-cli"),
        )

        captured = capsys.readouterr()
        assert "Standard_D4s_v5" in captured.out
        assert "centralus" in captured.out
        assert "Placement" not in captured.out

    def test_explicit_sizes_bypass_bounded_hardware_window(self, monkeypatch, capsys):
        _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[_historical_metric("Standard_D64s_v5", price_usd=0.80)],
        )
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D64s_v5"])

        _run_single_analysis(
            request=_analysis_args(min_vcpu=4, min_ram=16),
            config=config,
            logger=logging.getLogger("test-cli"),
        )

        bounded = capsys.readouterr()
        assert "No candidates match the specified filters" in bounded.out

        _run_single_analysis(
            request=_analysis_args(min_vcpu=4, min_ram=16, explicit_sizes=True),
            config=config,
            logger=logging.getLogger("test-cli"),
        )

        explicit = capsys.readouterr()
        assert "Standard_D64s_v5" in explicit.out

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
        request = mock_run_single_analysis.call_args.kwargs["request"]
        assert request.explicit_sizes is True

    @patch("spotvm.cli._run_single_analysis")
    def test_analysis_run_request_copies_cli_execution_fields(
        self,
        mock_run_single_analysis,
        tmp_path,
    ):
        csv_path = tmp_path / "out.csv"
        results_dir = tmp_path / "results"

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
                "--max-price",
                "0.10",
                "--max-eviction",
                "10",
                "--min-performance",
                "80",
                "--baseline-sku",
                "Standard_D4as_v6",
                "--no-max-limit",
                "--save-results",
                "--csv",
                str(csv_path),
                "--results-dir",
                str(results_dir),
                "--no-color",
            ]
        )

        assert rc == 0
        request = mock_run_single_analysis.call_args.kwargs["request"]
        assert request.no_color is True
        assert request.min_vcpu == 4
        assert request.min_ram == 16
        assert request.no_max_limit is True
        assert request.explicit_sizes is True
        assert request.max_price == 0.10
        assert request.max_eviction == 10.0
        assert request.min_performance == 80.0
        assert request.csv == csv_path
        assert request.results_dir == results_dir
        assert request.save_results is True

    def test_run_single_analysis_uses_analysis_run_request(self, monkeypatch, capsys, tmp_path):
        seen = _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[
                _historical_metric("Standard_D4s_v5", price_usd=0.08, eviction_rate=5.0),
                _historical_metric("Standard_D2s_v5", price_usd=0.04, eviction_rate=5.0),
                _historical_metric("Standard_D8s_v5", price_usd=0.20, eviction_rate=5.0),
                _historical_metric("Standard_D16s_v5", price_usd=0.09, eviction_rate=20.0),
            ],
        )

        request = _analysis_args(
            max_price=0.10,
            max_eviction=10.0,
            min_performance=90.0,
            results_dir=tmp_path / "results",
        )
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5", "Standard_D2s_v5", "Standard_D8s_v5", "Standard_D16s_v5"],
            os_type="windows",
            cache_ttl_minutes=30,
            retry_attempts=6,
            retry_backoff_seconds=3.5,
            baseline_sku="Standard_D4s_v5",
        )

        _run_single_analysis(
            request=request,
            config=config,
            logger=logging.getLogger("test-cli"),
        )

        captured = capsys.readouterr()
        assert "Standard_D4s_v5" in captured.out
        assert "Standard_D2s_v5" not in captured.out
        assert "Standard_D8s_v5" not in captured.out
        assert "Standard_D16s_v5" not in captured.out
        hist_request = seen["historical_request"]
        assert isinstance(hist_request, ResourceGraphRequest)
        assert hist_request.regions == ["centralus"]
        assert hist_request.sizes == ["Standard_D4s_v5", "Standard_D2s_v5", "Standard_D8s_v5", "Standard_D16s_v5"]
        assert hist_request.os_type == "windows"
        assert hist_request.cache_ttl_minutes == 30
        assert hist_request.retry_attempts == 6
        assert hist_request.retry_backoff_seconds == 3.5
        assert "placement_request" not in seen

    def test_persist_analysis_outputs_keeps_stdout_machine_readable_for_json(self, capsys):
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
        handled = _persist_analysis_outputs(
            [candidate],
            request=_analysis_args(),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], emit_json=True),
            logger=MagicMock(),
            emit=_stdout_emitter,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert handled is True
        assert payload["candidates"][0]["vmSize"] == "Standard_D4s_v5"
        assert payload["candidates"][0]["performanceBasis"] == "coremark"
        assert captured.err == ""

    @patch("spotvm.cli.export_to_csv", side_effect=PermissionError("disk full"))
    def test_persist_analysis_outputs_reports_csv_failure_without_raising(self, mock_export_csv, capsys):
        handled = _persist_analysis_outputs(
            [object()],
            request=_analysis_args(csv=Path("results.csv")),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            logger=MagicMock(),
            emit=_stdout_emitter,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        assert handled is False
        assert "Failed to export CSV" in captured.err
        mock_export_csv.assert_called_once()

    def test_persist_analysis_outputs_emits_empty_json_payload_only(self, capsys):
        handled = _persist_analysis_outputs(
            [],
            request=_analysis_args(),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"], emit_json=True),
            logger=MagicMock(),
            emit=_stdout_emitter,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert handled is True
        assert payload["candidates"] == []
        assert captured.err == ""

    @patch("spotvm.history.save_run_results", side_effect=PermissionError("disk full"))
    def test_save_run_results_if_requested_reports_failure_without_raising(self, mock_save_results, capsys):
        logger = MagicMock()

        _save_run_results_if_requested(
            [object()],
            request=_analysis_args(results_dir=Path("results"), save_results=True),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            logger=logger,
            emit=_stdout_emitter,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        assert "Failed to save run results" in captured.err
        logger.warning.assert_called_once()
        mock_save_results.assert_called_once()

    def test_emit_report_if_requested_reports_save_failure_without_raising(self, tmp_path, monkeypatch, capsys):
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
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = tmp_path / "reports" / "latest.json"
        original_replace = Path.replace

        def raising_replace(self: Path, target: Path):
            if self.parent == config.save_report.parent:
                raise PermissionError("read only file system")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", raising_replace)

        handled = _emit_report_if_requested(
            [candidate],
            request=_analysis_args(),
            config=config,
            logger=logger,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        assert handled is False
        assert "Failed to save report" in captured.err
        logger.error.assert_called_once()

    def test_emit_report_if_requested_creates_parent_directories(self, tmp_path, capsys):
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
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = tmp_path / "reports" / "latest.json"

        handled = _emit_report_if_requested(
            [candidate],
            request=_analysis_args(),
            config=config,
            logger=logger,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        assert handled is False
        assert captured.err == ""
        assert config.save_report.exists()
        report_payload = json.loads(config.save_report.read_text(encoding="utf-8"))
        assert report_payload["candidates"][0]["vmSize"] == "Standard_D4s_v5"
        logger.error.assert_not_called()

    def test_emit_report_if_requested_does_not_depend_on_path_write_text(self, tmp_path, monkeypatch, capsys):
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
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = tmp_path / "reports" / "latest.json"

        def raising_write_text(self: Path, *args, **kwargs):
            raise PermissionError("write_text disabled")

        monkeypatch.setattr(Path, "write_text", raising_write_text)

        handled = _emit_report_if_requested(
            [candidate],
            request=_analysis_args(),
            config=config,
            logger=logger,
            emit_error=_stderr_emitter,
        )

        captured = capsys.readouterr()
        assert handled is False
        assert captured.err == ""
        assert config.save_report.exists()
        logger.error.assert_not_called()

    def test_report_write_failure_does_not_suppress_console_output(self, monkeypatch, capsys, tmp_path):
        _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[_historical_metric("Standard_D4s_v5", price_usd=0.08, eviction_rate=5.0)],
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        config.save_report = tmp_path / "reports" / "latest.json"
        original_replace = Path.replace

        def raising_replace(self: Path, target: Path):
            if self.parent == config.save_report.parent:
                raise PermissionError("read only file system")
            return original_replace(self, target)

        monkeypatch.setattr(Path, "replace", raising_replace)

        _run_single_analysis(
            request=_analysis_args(),
            config=config,
            logger=logger,
        )

        captured = capsys.readouterr()
        assert "Failed to save report" in captured.err
        assert "Standard_D4s_v5" in captured.out
        logger.error.assert_called_once()

    @patch("spotvm.history.save_run_results", side_effect=PermissionError("disk full"))
    def test_save_results_failure_does_not_suppress_console_output(self, mock_save_results, monkeypatch, capsys):
        _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[_historical_metric("Standard_D4s_v5", price_usd=0.08, eviction_rate=5.0)],
        )
        logger = MagicMock()

        _run_single_analysis(
            request=_analysis_args(results_dir=Path("results"), save_results=True),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            logger=logger,
        )

        captured = capsys.readouterr()
        assert "Failed to save run results" in captured.err
        assert "Standard_D4s_v5" in captured.out
        logger.warning.assert_called_once()
        mock_save_results.assert_called_once()

    @patch("spotvm.cli.render_table")
    def test_render_analysis_results_prints_empty_message_without_rendering(self, mock_render_table, capsys):
        _render_analysis_results(
            [],
            request=_analysis_args(),
            config=ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"]),
            render_options=RenderOptions(colors_enabled=False),
            emit=_stdout_emitter,
        )

        captured = capsys.readouterr()
        assert "No candidates match the specified filters" in captured.out
        mock_render_table.assert_not_called()

    @patch("spotvm.cli.summarize_top_candidates", return_value=[])
    @patch("spotvm.cli.render_table")
    def test_render_analysis_results_explains_heuristic_marker_once(
        self,
        mock_render_table,
        mock_summarize,
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
        mock_render_table.return_value = "RANKED TABLE\nHeuristic perf*"

        _render_analysis_results(
            [candidate],
            request=_analysis_args(),
            config=ToolConfig(
                regions=["centralus"],
                sizes=["Standard_D4s_v4"],
                baseline_sku="Standard_D4s_v5",
            ),
            render_options=RenderOptions(colors_enabled=False),
            emit=_stdout_emitter,
        )

        captured = capsys.readouterr()
        assert "Heuristic perf*" in captured.out
        assert "* Heuristic perf:" in captured.out
        assert "comparable CoreMark data is unavailable" in captured.out
        assert "Some Perf % / Price/Perf values use a vCPU/RAM heuristic" not in captured.out
        mock_summarize.assert_called_once_with([candidate])

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

        args = _analysis_args(csv=Path("results.csv"))
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        _run_single_analysis(
            request=args,
            config=config,
            logger=logger,
        )

        captured = capsys.readouterr()
        assert "Failed to export CSV" in captured.err
        assert "RANKED TABLE" in captured.out
        logger.error.assert_called()
