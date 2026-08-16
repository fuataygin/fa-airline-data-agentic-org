"""
main.py
--------
Entry point. Loads environment variables (.env) and runs the full
five-agent pipeline end to end.

Usage:
    python main.py
"""

import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv is in requirements.txt; if it's genuinely missing we
    # still try to run — the user may have exported GEMINI_API_KEY
    # directly in their shell / CI environment instead of using a .env file.
    pass

from pipeline import run_pipeline

if __name__ == "__main__":
    try:
        run_pipeline()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(1)
