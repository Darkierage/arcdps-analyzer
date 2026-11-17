"""Download pinned external tools into ./bin (and optionally the LLM model).

Usage:
  uv run python scripts/setup_tools.py            # Elite Insights CLI
  uv run python scripts/setup_tools.py --llm      # + llama-server and the default model
  uv run python scripts/setup_tools.py --force    # re-download
"""

from __future__ import annotations

import argparse
import logging
import sys

from wvw_analyzer import tools
from wvw_analyzer.config import LlmSettings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    parser.add_argument("--llm", action="store_true", help="also fetch llama-server + model")
    parser.add_argument("--model", default=LlmSettings().model_file)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    d = tools.setup_ei(args.force)
    print(f"Elite Insights {tools.EI_VERSION}: {d}")
    if args.llm:
        print(f"llama-server ({tools.LLAMA_BUILD}): {tools.setup_llama(args.force)}")
        last = [-1]

        def progress(done: int, total: int) -> None:
            pct = int(100 * done / total) if total else 0
            if pct != last[0] and pct % 5 == 0:
                last[0] = pct
                print(f"  model {pct}%", flush=True)

        print(f"model: {tools.download_model(args.model, progress)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
