"""Integration tests for CLI argument parsing and main() entrypoint."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import spotvm.cli as cli
from spotvm.cli import (
    AnalysisRunRequest,
    _build_cli_logger,
    _build_ranked_candidates,
    _emit_report_if_requested,
    _fetch_analysis_inputs,
    _persist_analysis_outputs,
    _prepare_analysis_execution,
    _render_analysis_results,
    _run_analysis_mode,
    _run_history_analysis,
    _run_history_mode_if_requested,
    _run_single_analysis,
    _run_unattended_monitoring,
    _save_run_results_if_requested,
    build_parser,
    main,
)
from spotvm.config import ToolConfig
from spotvm.databricks_catalog import DatabricksCatalogError
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


class TestMainWithMocks:
    """Tests for main() with mocked Azure API calls."""

    @patch("spotvm.cli.initialize_color_output")
    @patch("spotvm.cli.logging.getLogger")
    @patch("spotvm.cli.logging.basicConfig")
    def test_build_cli_logger_configures_logging_and_color_output(
        self,
        mock_basic_config,
        mock_get_logger,
        mock_initialize_color_output,
    ):
        parser = build_parser()
        args = parser.parse_args(["--regions", "centralus", "--sizes", "Standard_D4s_v5"])
        logger = MagicMock()
        mock_get_logger.return_value = logger

        returned_logger = _build_cli_logger(args)

        assert returned_logger is logger
        mock_basic_config.assert_called_once_with(
            level=logging.WARNING,
            format="%(asctime)s %(levelname)s %(message)s",
        )
        mock_get_logger.assert_called_once_with("spotvm")
        logger.setLevel.assert_called_once_with(logging.INFO)
        mock_initialize_color_output.assert_called_once_with()

    def test_run_history_mode_if_requested_delegates_to_history_helper(self, tmp_path):
        results_dir = tmp_path / "results"
        history_output = tmp_path / "custom-history.csv"
        parser = build_parser()
        args = parser.parse_args(
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
        logger = MagicMock()
        run_history_analysis = MagicMock(return_value=0)

        rc = _run_history_mode_if_requested(
            args=args,
            logger=logger,
            run_history_analysis=run_history_analysis,
        )

        assert rc == 0
        run_history_analysis.assert_called_once()
        kwargs = run_history_analysis.call_args.kwargs
        assert kwargs["results_dir"] == results_dir
        assert kwargs["depth"] == 7
        assert kwargs["history_output"] == history_output

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

    @patch("spotvm.cli.config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES", 1)
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

    @patch("spotvm.cli.config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES", 1)
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

    @patch("spotvm.cli.config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES", 2)
    def test_run_unattended_iteration_stops_after_failure_threshold(self, capsys):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock(side_effect=RuntimeError("boom"))

        unexpected_error_count, exit_code = cli._run_unattended_iteration(
            request=request,
            config=config,
            logger=logger,
            run_single_analysis=run_single_analysis,
            unexpected_error_count=1,
            emit=_stdout_emitter,
        )

        assert unexpected_error_count == 2
        assert exit_code == 1
        logger.exception.assert_called_once_with(
            "Unexpected error in unattended run (%d/%d)",
            2,
            2,
        )
        logger.error.assert_called_once_with(
            "Stopping unattended mode after %d consecutive unexpected errors",
            2,
        )
        captured = capsys.readouterr()
        assert "Stopping monitoring after 2 consecutive unexpected errors" in captured.out

    @patch("spotvm.cli.config_defaults.DEFAULT_MAX_UNATTENDED_FAILURES", 2)
    def test_run_unattended_iteration_resets_error_count_after_azure_http_error(self):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])
        run_single_analysis = MagicMock(side_effect=AzureHttpError("https://example.test", 429, "busy"))

        unexpected_error_count, exit_code = cli._run_unattended_iteration(
            request=request,
            config=config,
            logger=logger,
            run_single_analysis=run_single_analysis,
            unexpected_error_count=1,
            emit=_stdout_emitter,
        )

        assert unexpected_error_count == 0
        assert exit_code is None
        logger.exception.assert_not_called()
        logger.error.assert_called_once_with(
            "Azure API request failed: Azure API request failed (429) for https://example.test: busy"
        )
        logger.info.assert_called_once_with("Continuing despite error...")

    def test_run_unattended_iteration_resets_error_count_after_databricks_catalog_error(self):
        logger = MagicMock()
        request = _analysis_args(no_color=True, results_dir=Path("results"), save_results=True)
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            include_databricks_cost=True,
        )
        run_single_analysis = MagicMock(side_effect=DatabricksCatalogError("broken catalog"))

        unexpected_error_count, exit_code = cli._run_unattended_iteration(
            request=request,
            config=config,
            logger=logger,
            run_single_analysis=run_single_analysis,
            unexpected_error_count=1,
            emit=_stdout_emitter,
        )

        assert unexpected_error_count == 0
        assert exit_code is None
        logger.exception.assert_not_called()
        logger.error.assert_called_once()
        assert logger.error.call_args.args[0] == "Databricks pricing catalog failed: %s"
        assert str(logger.error.call_args.args[1]) == "broken catalog"
        logger.info.assert_called_once_with("Continuing despite error...")

    def test_sleep_until_next_run_emits_schedule_and_stops_early(self, capsys):
        logger = MagicMock()
        slept: list[int] = []
        should_stop_calls = iter([False, False, True])

        def should_stop() -> bool:
            return next(should_stop_calls)

        cli._sleep_until_next_run(
            interval_minutes=1,
            logger=logger,
            emit=_stdout_emitter,
            sleep=lambda seconds: slept.append(seconds),
            should_stop=should_stop,
            now=lambda: datetime(2025, 1, 1, 12, 0, 0),
        )

        assert slept == [1, 1]
        logger.info.assert_called_once_with("Next run at 12:01:00")
        captured = capsys.readouterr()
        assert "Sleeping for 1 minutes..." in captured.out
        assert "Next run at: 12:01:00" in captured.out

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

    def test_run_analysis_mode_returns_two_for_databricks_catalog_error(self):
        logger = MagicMock()
        request = _analysis_args()
        config = ToolConfig(
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            include_databricks_cost=True,
        )
        error = DatabricksCatalogError("broken catalog")

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
        logger.error.assert_called_once_with("Databricks pricing catalog failed: %s", error)

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

    def test_fetch_analysis_inputs_requests_placement_and_history_data(self, monkeypatch):
        placement_marker = object()
        historical_metric = _historical_metric("Standard_D4s_v5")
        seen = _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[historical_metric],
            placement_scores=[placement_marker],
        )
        config = ToolConfig(
            subscription_id="sub-id",
            regions=["centralus"],
            sizes=["Standard_D4s_v5"],
            enable_placement=True,
        )

        placement_scores, historical_metrics = _fetch_analysis_inputs(
            client=object(),
            config=config,
        )

        assert placement_scores == [placement_marker]
        assert historical_metrics == [historical_metric]
        placement_request = seen["placement_request"]
        assert isinstance(placement_request, PlacementScoreRequest)
        assert placement_request.subscription_id == "sub-id"
        historical_request = seen["historical_request"]
        assert isinstance(historical_request, ResourceGraphRequest)
        assert historical_request.sizes == ["Standard_D4s_v5"]

    def test_build_ranked_candidates_applies_filters_and_result_limit(self):
        ranked = _build_ranked_candidates(
            placement_scores=[],
            historical_metrics=[
                _historical_metric("Standard_D4s_v5", price_usd=0.08, eviction_rate=5.0),
                _historical_metric("Standard_D2s_v5", price_usd=0.04, eviction_rate=5.0),
                _historical_metric("Standard_D8s_v5", price_usd=0.20, eviction_rate=5.0),
                _historical_metric("Standard_D16s_v5", price_usd=0.09, eviction_rate=20.0),
            ],
            request=_analysis_args(
                max_price=0.10,
                max_eviction=10.0,
                min_performance=90.0,
            ),
            config=ToolConfig(
                regions=["centralus"],
                sizes=["Standard_D4s_v5", "Standard_D2s_v5", "Standard_D8s_v5", "Standard_D16s_v5"],
                baseline_sku="Standard_D4s_v5",
                result_limit=1,
            ),
        )

        assert [candidate.vm_size for candidate in ranked] == ["Standard_D4s_v5"]
        assert ranked[0].performance_relative == 100.0

    def test_build_ranked_candidates_uses_total_databricks_cost_for_price_filtering(self, monkeypatch):
        monkeypatch.setattr(
            "spotvm.analysis.load_catalog",
            lambda: SimpleNamespace(
                captured_at="2026-03-19T00:00:00Z",
                pricing_profile=SimpleNamespace(dbu_unit_price_usd=0.15, photon_dbu_unit_price_usd=0.15),
            ),
        )

        pricing_rows = {
            "Standard_D4s_v4": SimpleNamespace(dbu_per_hour=1.0, photon_capable=True),
            "Standard_E4s_v4": SimpleNamespace(dbu_per_hour=2.0, photon_capable=True),
        }
        monkeypatch.setattr(
            "spotvm.analysis.lookup_azure_node_type_pricing",
            lambda sku: pricing_rows.get(sku),
        )

        ranked = _build_ranked_candidates(
            placement_scores=[],
            historical_metrics=[
                _historical_metric("Standard_D4s_v4", price_usd=0.05, eviction_rate=5.0),
                _historical_metric("Standard_E4s_v4", price_usd=0.05, eviction_rate=5.0),
            ],
            request=_analysis_args(max_price=0.30),
            config=ToolConfig(
                regions=["centralus"],
                sizes=["Standard_D4s_v4", "Standard_E4s_v4"],
                include_databricks_cost=True,
            ),
        )

        assert [candidate.vm_size for candidate in ranked] == ["Standard_D4s_v4"]
        assert ranked[0].compute_price_usd == 0.05
        assert ranked[0].databricks_dbu_cost_usd == 0.15
        assert ranked[0].total_price_usd == 0.20

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

    def test_prepare_analysis_execution_builds_config_and_request(self, tmp_path):
        parser = build_parser()
        args = parser.parse_args(
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
                str(tmp_path / "out.csv"),
                "--results-dir",
                str(tmp_path / "results"),
                "--no-color",
            ]
        )
        logger = MagicMock()

        config, request = _prepare_analysis_execution(
            parser=parser,
            args=args,
            logger=logger,
        )

        assert config.sizes == ["Standard_D64s_v5"]
        assert config.baseline_sku == "Standard_D4as_v6"
        assert request.no_color is True
        assert request.min_vcpu == 4
        assert request.min_ram == 16
        assert request.no_max_limit is True
        assert request.explicit_sizes is True
        assert request.max_price == 0.10
        assert request.max_eviction == 10.0
        assert request.min_performance == 80.0
        assert request.csv == tmp_path / "out.csv"
        assert request.results_dir == tmp_path / "results"
        assert request.save_results is True

    @patch("spotvm.cli.discover_skus", return_value=[])
    def test_prepare_analysis_execution_returns_one_when_auto_discovery_finds_no_sizes(
        self,
        mock_discover_skus,
    ):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--regions",
                "centralus",
                "--min-vcpu",
                "4",
            ]
        )
        logger = MagicMock()

        rc = _prepare_analysis_execution(
            parser=parser,
            args=args,
            logger=logger,
        )

        assert rc == 1
        mock_discover_skus.assert_called_once_with(
            min_vcpu=4,
            min_ram=None,
            cpu_arch=None,
        )
        logger.error.assert_called_once_with("No SKUs found matching specified requirements")

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

    @patch("spotvm.history.save_run_results", side_effect=ValueError("not serializable"))
    def test_save_run_results_if_requested_reports_serialization_failure_without_raising(
        self, mock_save_results, capsys
    ):
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

    @patch("spotvm.cli.export_to_csv", side_effect=PermissionError("disk full"))
    def test_csv_export_failure_does_not_suppress_console_output(
        self,
        mock_export_csv,
        monkeypatch,
        capsys,
    ):
        _stub_analysis_fetches(
            monkeypatch,
            historical_metrics=[_historical_metric("Standard_D4s_v5", price_usd=0.08, eviction_rate=5.0)],
        )
        logger = MagicMock()
        config = ToolConfig(regions=["centralus"], sizes=["Standard_D4s_v5"])

        _run_single_analysis(
            request=_analysis_args(csv=Path("results.csv")),
            config=config,
            logger=logger,
        )

        captured = capsys.readouterr()
        assert "Failed to export CSV" in captured.err
        assert "Standard_D4s_v5" in captured.out
        logger.error.assert_called()
