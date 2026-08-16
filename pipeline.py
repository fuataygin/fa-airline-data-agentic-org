"""
pipeline.py
------------
The orchestrator: Researcher -> Designer -> Maker -> Communicator -> Manager.

Each stage's full output becomes the next stage's input, in code (not just
in spirit) — this file is the proof that the chain is unbroken. It also:

  * writes every stage's output to outputs/, numbered in pipeline order
  * extracts FORGE's generated Python module and writes it to
    products/bers_engine.py
  * actually EXECUTES that module against the live Google Sheet, and feeds
    its real stdout into ECHO (Communicator) and ATLAS (Manager) — so the
    marketing and the executive summary are grounded in a real, live run,
    not in FORGE's promises about what the code does.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

from agents import (
    make_researcher, RESEARCH_TASK_PROMPT,
    make_designer, build_design_task_prompt,
    make_maker, build_maker_task_prompt,
    make_communicator, build_comms_task_prompt,
    make_manager, build_manager_task_prompt,
)
from config import OUTPUT_DIR

CODE_FENCE_RE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def _banner(text: str) -> None:
    line = "=" * 78
    print(f"\n{line}\n{text}\n{line}")


def _save(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"  -> saved {path}")


def _extract_code_block(text: str) -> str:
    match = CODE_FENCE_RE.search(text)
    if not match:
        raise ValueError(
            "Could not find a fenced ```python code block in FORGE's output. "
            "Check outputs/03_maker_note_and_raw_output.md for the raw response."
        )
    return match.group(1).strip() + "\n"


def _run_generated_product(repo_root: Path) -> tuple[bool, str]:
    """
    Executes products/bers_engine.py exactly the way an end user would:
    `python -m products.bers_engine`, from the repo root, so its own
    `from tools.sheets_tool import fetch_tab` import resolves correctly.
    Returns (success, combined_stdout_and_stderr).
    """
    result = subprocess.run(
        [sys.executable, "-m", "products.bers_engine"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout
    if result.returncode != 0:
        combined += "\n\n--- STDERR ---\n" + result.stderr
        return False, combined
    return True, combined


def run_pipeline() -> None:
    repo_root = Path(__file__).resolve().parent
    out_dir = repo_root / OUTPUT_DIR
    started = time.time()

    _banner("FA AIRLINE DATA — AGENTIC ORGANISATION PIPELINE STARTING")
    print("Chain: ARIA (Researcher) -> NOVA (Designer) -> FORGE (Maker) "
          "-> ECHO (Communicator) -> ATLAS (Manager)")

    # ---------------------------------------------------------------- ARIA
    _banner("STAGE 1/5 — ARIA (Researcher): querying the live sheet ...")
    researcher = make_researcher()
    research_brief = researcher.run(RESEARCH_TASK_PROMPT)
    print(f"ARIA tool calls made: {researcher.last_log.tool_calls}")
    _save(out_dir / "01_research_brief.md", research_brief)

    # ---------------------------------------------------------------- NOVA
    _banner("STAGE 2/5 — NOVA (Designer): drafting the design specification ...")
    designer = make_designer()
    design_spec = designer.run(build_design_task_prompt(research_brief))
    _save(out_dir / "02_design_spec.md", design_spec)

    # --------------------------------------------------------------- FORGE
    _banner("STAGE 3/5 — FORGE (Maker): writing the working prototype ...")
    maker = make_maker()
    maker_full_response = maker.run(build_maker_task_prompt(design_spec))
    _save(out_dir / "03_maker_note_and_raw_output.md", maker_full_response)

    maker_code = _extract_code_block(maker_full_response)
    maker_note = maker_full_response.split("```")[0].strip()
    product_path = repo_root / "products" / "bers_engine.py"
    _save(product_path, maker_code)

    print("Running FORGE's generated product live against the Google Sheet ...")
    success, maker_real_output = _run_generated_product(repo_root)
    status = "SUCCESS" if success else "FAILED (see output below for the traceback)"
    print(f"  -> execution {status}")
    _save(
        out_dir / "03b_maker_real_execution_output.txt",
        f"python -m products.bers_engine\nstatus: {status}\n\n{maker_real_output}",
    )

    if not success:
        print(
            "\n[!] The generated product failed to run. This can happen with "
            "live LLM code generation. The pipeline continues with FORGE's "
            "raw error output so ECHO and ATLAS can react to it honestly — "
            "see outputs/03b_maker_real_execution_output.txt, fix "
            "products/bers_engine.py, and re-run if you want a clean demo."
        )

    # ---------------------------------------------------------------- ECHO
    _banner("STAGE 4/5 — ECHO (Communicator): writing the go-to-market package ...")
    communicator = make_communicator()
    comms_package = communicator.run(
        build_comms_task_prompt(design_spec, maker_note, maker_real_output)
    )
    _save(out_dir / "04_gtm_package.md", comms_package)

    # --------------------------------------------------------------- ATLAS
    _banner("STAGE 5/5 — ATLAS (Manager): writing the executive summary ...")
    manager = make_manager()
    exec_summary = manager.run(
        build_manager_task_prompt(
            research_brief, design_spec, maker_note, maker_real_output, comms_package
        )
    )
    _save(out_dir / "05_executive_summary.md", exec_summary)

    elapsed = time.time() - started
    _banner(f"PIPELINE COMPLETE in {elapsed:.1f}s — see {OUTPUT_DIR}/ for every artefact")
    print(f"Working product code: products/bers_engine.py")
    print(f"Run it again anytime with:  python -m products.bers_engine")


if __name__ == "__main__":
    run_pipeline()
