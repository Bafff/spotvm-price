from pathlib import Path

from spotvm_tool.analysis import merge_datasets, rank_candidates
from spotvm_tool.config import ToolConfig
from spotvm_tool.reporting import render_table
from spotvm_tool.resource_graph import fetch_historical_metrics


class DummyClient:
    """Stub for AzureRestClient when using sample data."""

    def __init__(self) -> None:  # pragma: no cover - no behavior required
        pass


def test_sample_graph_data_populates_table():
    config = ToolConfig(
        subscription_id="demo-sub",
        regions=["centralus", "eastus", "northcentralus"],
        sizes=[
            "Standard_D2as_v6",
            "Standard_D4as_v5",
            "Standard_E4s_v5",
            "Standard_F4s_v2",
            "Standard_DS3_v2",
        ],
        desired_count=10,
        enable_placement=False,
        resource_graph_sample=Path("tests/data/sample_graph.json"),
    )

    historical = fetch_historical_metrics(DummyClient(), config)
    combined = merge_datasets([], historical)
    ranked = rank_candidates(combined)
    table = render_table(ranked)

    assert len(ranked) == 5
    assert "Standard_D2as_v6" in table
    assert "Standard_DS3_v2" in table
    assert "$0.0540" in table
    assert "2.9%" in table
    assert "N/A" in table  # placement column without scores
