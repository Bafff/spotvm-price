from __future__ import annotations

import logging

from spotvm_tool.placement_score import _parse_response


def test_parse_response_logs_items_without_vm_size(caplog):
    payload = {
        "placementScores": [
            {
                "scoresByLocation": [
                    {"location": "eastus", "score": "High", "isQuotaAvailable": True}
                ]
            }
        ]
    }

    with caplog.at_level(logging.DEBUG, logger="spotvm-tool"):
        results = _parse_response(payload)

    assert results == []
    assert "Skipping placement score item without VM size" in caplog.text
