from datetime import datetime

from spotvm_tool.models import CandidateInsight
from spotvm_tool.reporting import render_table


def test_render_table_formats_columns():
    candidates = [
        CandidateInsight(
            region="eastus",
            vm_size="Standard_D2s_v4",
            placement_score="High",
            quota_available=True,
            price_usd=0.0456,
            price_last_updated=datetime(2025, 10, 24, 12, 0),
            eviction_rate=3.2,
            eviction_last_updated=datetime(2025, 10, 20, 8, 0),
            recommendation_rank=1,
        ),
        CandidateInsight(
            region="westus",
            vm_size="Standard_D4s_v4",
            placement_score="Medium",
            quota_available=False,
            price_usd=None,
            price_last_updated=None,
            eviction_rate=None,
            eviction_last_updated=None,
            availability_zone="2",
            recommendation_rank=2,
            notes="Data not found",
        ),
    ]

    table = render_table(candidates)

    assert "eastus" in table
    assert "Standard_D4s_v4" in table
    assert "Data not found" in table
    assert table.count("\n") > 2
