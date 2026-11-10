"""Entry point for frozen (PyInstaller) builds: launches the desktop app."""
import sys

from seed_vault.qt.app import main

if __name__ == "__main__":
    sys.exit(main())
