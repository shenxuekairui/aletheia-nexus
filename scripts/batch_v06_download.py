"""Backward-compatible entry point for the installed AN command-line interface."""

from aletheia_nexus.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
