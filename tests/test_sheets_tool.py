"""
tests/test_sheets_tool.py
----------------------------
A live smoke test — this genuinely hits Google Sheets over the network
(no mocking), because the entire point of this tool is that it queries
live data. Run with: `pytest tests/test_sheets_tool.py -v`

Requires network access to docs.google.com. If you're running this in a
sandboxed CI environment without outbound internet, skip it or mock
`requests.get` yourself.
"""

import pandas as pd
import pytest

from tools.sheets_tool import fetch_tab, fetch_summary, SheetFetchError
from config import SHEET_TABS


@pytest.mark.parametrize("tab_name", SHEET_TABS)
def test_fetch_tab_returns_nonempty_dataframe(tab_name):
    df = fetch_tab(tab_name)
    assert isinstance(df, pd.DataFrame)
    assert len(df) > 0
    assert len(df.columns) > 0


def test_fetch_summary_has_expected_keys():
    summary = fetch_summary("aviation_incidents", max_rows_preview=5)
    assert summary["tab"] == "aviation_incidents"
    assert summary["row_count"] > 0
    assert "airline" in [c.lower() for c in summary["columns"]]


def test_unknown_tab_raises():
    with pytest.raises(SheetFetchError):
        fetch_tab("not_a_real_tab")
