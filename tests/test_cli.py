"""Integration tests for CLI argument parsing and main() entrypoint."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from spotvm_tool.cli import build_parser, main


class TestBuildParser:
    """Tests for argument parsing."""

    def test_no_args_shows_help(self, capsys):
        rc = main([])
        assert rc == 0
        captured = capsys.readouterr()
        assert "spotvm-tool" in captured.out
        assert "--regions" in captured.out

    def test_missing_regions_errors(self):
        with pytest.raises(SystemExit):
            main(["--sizes", "Standard_D4s_v5"])

    def test_missing_sizes_errors(self):
        with pytest.raises(SystemExit):
            main(["--regions", "centralus"])

    def test_placement_check_without_subscription_errors(self):
        with pytest.raises(SystemExit):
            main([
                "--regions", "centralus",
                "--sizes", "Standard_D4s_v5",
                "--placement-check",
            ])

    def test_availability_zones_without_placement_errors(self):
        with pytest.raises(SystemExit):
            main([
                "--regions", "centralus",
                "--sizes", "Standard_D4s_v5",
                "--availability-zones",
            ])

    def test_desired_count_without_placement_errors(self):
        with pytest.raises(SystemExit):
            main([
                "--regions", "centralus",
                "--sizes", "Standard_D4s_v5",
                "--desired-count", "5",
            ])

    def test_min_performance_without_baseline_errors(self):
        with pytest.raises(SystemExit):
            main([
                "--regions", "centralus",
                "--sizes", "Standard_D4s_v5",
                "--min-performance", "80",
            ])

    def test_parser_accepts_all_documented_args(self):
        parser = build_parser()
        args = parser.parse_args([
            "--regions", "centralus",
            "--sizes", "Standard_D4s_v5",
            "--os-type", "linux",
            "--no-color",
            "--baseline-sku", "Standard_D4as_v6",
            "--min-vcpu", "4",
            "--min-ram", "8",
            "--cpu-arch", "x64",
            "--max-price", "0.10",
            "--max-eviction", "10",
            "--limit", "5",
            "--verbose",
        ])
        assert args.regions == ["centralus"]
        assert args.sizes == ["Standard_D4s_v5"]
        assert args.cpu_arch == "x64"
        assert args.max_price == 0.10
        assert args.max_eviction == 10.0


class TestMainWithMocks:
    """Tests for main() with mocked Azure API calls."""

    @patch("spotvm_tool.cli.AzureAuthenticator")
    @patch("spotvm_tool.cli.AzureRestClient")
    @patch("spotvm_tool.cli.fetch_historical_metrics")
    def test_basic_run_returns_zero(
        self, mock_fetch_hist, mock_client_cls, mock_auth_cls, capsys
    ):
        mock_fetch_hist.return_value = []
        rc = main([
            "--regions", "centralus",
            "--sizes", "Standard_D4s_v5",
            "--no-color",
        ])
        assert rc == 0
        mock_fetch_hist.assert_called_once()

    @patch("spotvm_tool.cli.AzureAuthenticator")
    @patch("spotvm_tool.cli.AzureRestClient")
    @patch("spotvm_tool.cli.fetch_historical_metrics")
    def test_no_color_flag_works(
        self, mock_fetch_hist, mock_client_cls, mock_auth_cls, capsys
    ):
        mock_fetch_hist.return_value = []
        rc = main([
            "--regions", "centralus",
            "--sizes", "Standard_D4s_v5",
            "--no-color",
        ])
        assert rc == 0
        captured = capsys.readouterr()
        # No ANSI escape codes in output
        assert "\033[" not in captured.out
