# Aletheia Nexus v0.6.1 — Installable Research Acquisition

v0.6.1 makes the first public acquisition layer easier to install, run, and extend. It does not change the frozen v0.6.0 tag or claim that every publisher or institution is supported.

## What changed

- The installed `aletheia-nexus` CLI accepts one DOI or a TXT/CSV/JSON list. `doctor` checks local setup, and `acquire DOI --public-only` provides a browser-free first run. The older batch script remains a compatibility wrapper.
- Publisher-specific article-route and page rules are separated into `publisher_adapters/`; generic native download and Chromium PDF-viewer capture are in `browser_engine/`. `browser_route.py` remains the coordinator and needs further incremental simplification. Every candidate still passes shared PDF structure, identity, main-text-role, and provenance checks before `VERIFIED`.
- The release build produces a source distribution and wheel. PyPI publishing uses GitHub Actions OIDC Trusted Publishing, a dedicated `pypi` environment, version/tag checks, and a clean wheel-install smoke test. PyPI availability must be confirmed on the [project page](https://pypi.org/project/aletheia-nexus/) and through a fresh installation; a GitHub Release alone is not enough.
- CI adds Windows 3.11 with a real local Chromium integration test alongside Linux Python 3.11, Python 3.14, and Chromium jobs. Ordinary draft commits remain runner-free; ready PRs and release preparation use the full matrix.
- An English README, contributor and security guidance, issue templates, and private GitHub vulnerability reporting provide clearer open-source entry points.

## Install after PyPI upload

```bash
python -m pip install aletheia-nexus
aletheia-nexus doctor
aletheia-nexus acquire 10.1371/journal.pone.0310216 --public-only --output-dir downloads
```

The optional authenticated browser path uses `python -m pip install "aletheia-nexus[browser]"` and `python -m playwright install chromium`. Publisher access still requires the user's own legitimate subscription or institutional entitlement.

## What remains unverified

- **Independent first-time use:** no outside user's installation feedback had been received when this release was prepared. The goal of reaching a meaningful first result within three minutes is **not yet independently verified**. Please report actual experience in [trial issue #3](https://github.com/shenxuekairui/aletheia-nexus/issues/3).
- **Institutional access qualification:** the formal positive-control study across institutions and publisher systems remains deferred. Historical cumulative DOI successes are not a certified coverage rate; site, IP, login state, and subscription all matter.
- **Architecture:** the adapter/engine split is a foundation, not a complete rewrite. The route coordinator is still substantial.

AN does not supply subscriptions, solve CAPTCHAs, or bypass access controls. `VERIFIED` describes document identity and role, not the truth of scientific claims. Live DOI access and the PyPI upload must be reported separately from deterministic and local-browser CI results.
