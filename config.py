"""
config.py
---------
Central configuration for the FA Airline Data agentic organisation.

Nothing in here is a secret. The Gemini API key is read from the
environment (GEMINI_API_KEY) by the SDK itself — see .env.example.
"""

import os

# The live, public FA Airline Data Google Sheet.
# "Anyone with the link can view" must stay enabled for the tool calls to work.
GOOGLE_SHEET_ID = os.environ.get(
    "FAAD_SHEET_ID", "1VdQONMwSTiBg0w6XUq7DX6HMG6xp9d9DVO03nrl-Tfk"
)

# The five tabs that exist in the live workbook.
SHEET_TABS = [
    "airline_financials",   # 30 airlines x 17 years: revenue, margins, pax, load factor, fleet
    "fleet_orders",          # Boeing vs Airbus vs COMAC orders/deliveries/backlog by family
    "passenger_traffic",     # 6 regions x monthly RPK/ASK/load factor, 2010-2026
    "route_performance",     # 40 top global routes x multi-year pax, fares, revenue
    "aviation_incidents",    # Major accidents/incidents 2010-2026
]

# Model used by every agent unless overridden per-agent.
# Google's current lineup (via the Interactions API) includes
# gemini-3.7-flash, gemini-3.6-flash (GA, stable), gemini-3.5-flash,
# gemini-3.1-pro-preview, and gemini-2.5-pro/flash. gemini-3.6-flash is
# the default here: GA (not preview), and a good quality/cost/speed
# balance for a five-agent pipeline. Bump to gemini-3.1-pro-preview via
# GEMINI_MODEL if you want stronger reasoning for the Designer/Manager
# stages and don't mind preview status + no free tier.
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.6-flash")

# Where each stage of the pipeline writes its artefact.
OUTPUT_DIR = os.environ.get("FAAD_OUTPUT_DIR", "outputs")

# Company identity — used inside every agent's system prompt so the whole
# org speaks with one consistent brand voice.
COMPANY_NAME = "FA Airline Data"
COMPANY_DESCRIPTION = (
    "FA Airline Data is an aviation analytics company that turns a live, "
    "continuously-updated dataset spanning 30 global airlines, Boeing/Airbus/"
    "COMAC fleet orders, regional passenger traffic, top global routes, and "
    "major aviation incidents (2010-2026) into decision-grade intelligence "
    "for equity analysts, aviation researchers, journalists, and airline "
    "strategy teams."
)
