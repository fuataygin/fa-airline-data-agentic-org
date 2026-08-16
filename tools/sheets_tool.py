"""
tools/sheets_tool.py
---------------------
The ONE live external data connection required by the brief.

This module hits Google Sheets' public CSV export endpoint *at call time*.
Nothing about the dataset is hardcoded, cached, or copy-pasted anywhere in
this codebase or in any agent's prompt — every number an agent reasons
about is fetched fresh, live, from the FA Airline Data workbook, the
moment it is needed.

It is exposed two ways:
  1. `fetch_tab()` / `fetch_summary()` — plain Python functions any agent
     or script can call directly (used by the Maker's generated product).
  2. `SHEET_TOOL_SCHEMA` + `make_tool_impl()` — a Gemini Interactions API
     function-tool definition, so the Researcher agent can call it as a
     genuine model function call (the model decides which tab to query
     and when).

Swap-in note: if you'd rather go through the official Google Sheets API
(for a private, non-link-shared workbook) you only need to change the
inside of `fetch_tab()` — every caller in this repo goes through this
one function.
"""

from __future__ import annotations

import io
import urllib.parse

import pandas as pd
import requests

from config import GOOGLE_SHEET_ID, SHEET_TABS


class SheetFetchError(RuntimeError):
    """Raised when the live Google Sheet cannot be read."""


def _csv_export_url(sheet_id: str, tab_name: str) -> str:
    """Google's gviz endpoint returns a single named tab as CSV, live."""
    encoded_tab = urllib.parse.quote(tab_name)
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={encoded_tab}"
    )


def fetch_tab(tab_name: str, sheet_id: str = GOOGLE_SHEET_ID, timeout: int = 20) -> pd.DataFrame:
    """
    LIVE fetch of a single tab from the FA Airline Data Google Sheet.

    Queried at the moment of use — every call performs a fresh HTTP GET
    against Google Sheets. Raises SheetFetchError with a helpful message
    if the tab name is wrong or the sheet isn't shared as "Anyone with
    the link can view".
    """
    if tab_name not in SHEET_TABS:
        raise SheetFetchError(
            f"Unknown tab '{tab_name}'. Expected one of: {', '.join(SHEET_TABS)}"
        )

    url = _csv_export_url(sheet_id, tab_name)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise SheetFetchError(f"Live fetch of tab '{tab_name}' failed: {exc}") from exc

    text = resp.text
    if text.strip().startswith("<"):
        raise SheetFetchError(
            f"Got an HTML page instead of CSV for tab '{tab_name}'. "
            "The sheet is probably no longer shared as "
            "'Anyone with the link can view'."
        )

    df = pd.read_csv(io.StringIO(text))
    df.attrs["source_url"] = url
    df.attrs["fetched_tab"] = tab_name
    return df


def fetch_summary(
    tab_name: str,
    sheet_id: str = GOOGLE_SHEET_ID,
    max_rows_preview: int = 15,
) -> dict:
    """
    A model-friendly, token-cheap summary of a live tab: shape, columns,
    a CSV preview, and numeric stats. This is what gets handed back to
    Gemini when it calls the sheet tool.
    """
    df = fetch_tab(tab_name, sheet_id)

    summary: dict = {
        "tab": tab_name,
        "source_url": df.attrs.get("source_url"),
        "row_count": len(df),
        "columns": list(df.columns),
        "preview_csv": df.head(max_rows_preview).to_csv(index=False),
    }

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if numeric_cols:
        summary["numeric_stats"] = (
            df[numeric_cols].describe().round(2).to_dict()
        )

    return summary


def summary_to_text(summary: dict) -> str:
    """Render a fetch_summary() dict as compact text for a tool_result block."""
    lines = [
        f"LIVE DATA — tab: {summary['tab']}",
        f"source: {summary['source_url']}",
        f"rows: {summary['row_count']}",
        f"columns: {', '.join(summary['columns'])}",
        "",
        f"preview (first rows, CSV):",
        summary["preview_csv"].strip(),
    ]
    if "numeric_stats" in summary:
        lines.append("")
        lines.append("numeric column stats:")
        lines.append(str(summary["numeric_stats"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gemini Interactions API tool wiring
# ---------------------------------------------------------------------------
# The Interactions API (client.interactions.create) takes function tools as
# plain dicts: {"type": "function", "name":, "description":, "parameters":}
# where `parameters` is a JSON-Schema-shaped dict. See
# https://ai.google.dev/gemini-api/docs/function-calling

SHEET_TOOL_NAME = "fetch_faairlinedata_tab"

SHEET_TOOL_SCHEMA = {
    "type": "function",
    "name": SHEET_TOOL_NAME,
    "description": (
        "Live-queries one tab of the FA Airline Data Google Sheet — a public "
        "aviation dataset covering 30 airlines, Boeing/Airbus/COMAC fleet "
        "orders, regional passenger traffic, top global routes, and major "
        "aviation incidents, 2010-2026. This performs a real HTTP request to "
        "Google Sheets at the moment it is called: results are never cached, "
        "pre-loaded, or hardcoded. Call it whenever you need real numbers "
        "instead of guessing."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tab_name": {
                "type": "string",
                "enum": SHEET_TABS,
                "description": "Which tab of the workbook to query.",
            },
            "max_rows_preview": {
                "type": "integer",
                "description": "How many preview rows to return (default 15, max ~50).",
            },
        },
        "required": ["tab_name"],
    },
}


def make_tool_impl():
    """
    Returns the local Python function the Agent's tool loop calls whenever
    Gemini emits a `fetch_faairlinedata_tab` function_call step.
    """

    def _impl(tab_name: str, max_rows_preview: int = 15) -> str:
        try:
            summary = fetch_summary(tab_name, max_rows_preview=max_rows_preview)
            return summary_to_text(summary)
        except SheetFetchError as exc:
            return f"ERROR fetching '{tab_name}': {exc}"

    return _impl


if __name__ == "__main__":
    # Quick manual smoke test: `python -m tools.sheets_tool`
    for tab in SHEET_TABS:
        try:
            s = fetch_summary(tab, max_rows_preview=3)
            print(f"[OK] {tab}: {s['row_count']} rows, columns={s['columns']}")
        except SheetFetchError as e:
            print(f"[FAIL] {tab}: {e}")
