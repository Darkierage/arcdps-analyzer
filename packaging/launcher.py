"""PyInstaller entry point (absolute import so the package's relative imports work)."""

import multiprocessing

from wvw_analyzer.main import main

if __name__ == "__main__":
    multiprocessing.freeze_support()  # analysis worker processes in the frozen exe
    main()
