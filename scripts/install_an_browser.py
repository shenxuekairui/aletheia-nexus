"""Source-checkout compatibility wrapper for the installed browser provisioner."""

from aletheia_nexus.acquire.access.browser_engine.installer import main

if __name__ == "__main__":
    raise SystemExit(main())
