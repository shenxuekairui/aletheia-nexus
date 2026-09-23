# CI architecture / 持续集成架构

CI verifies deterministic code behavior. It never logs into a publisher, uses a
personal browser profile, or treats a live publisher response as a release test.
The authenticated live-acceptance gate remains a separate, user-operated step.

## Execution tiers

| Event | Python 3.11 fast suite | Python 3.14 compatibility | Local Chromium integration |
|---|---:|---:|---:|
| Draft PR, including new commits | no runner | no runner | no runner |
| PR marked ready, including later commits | yes | yes | yes |
| `main` push or merge queue | yes | yes | yes |
| Manual `workflow_dispatch`, `fast` | yes | no | no |
| Manual `workflow_dispatch`, `full` | yes | yes | yes |

The fast job runs `pip check`, Ruff format/lint, compilation, and the complete
deterministic pytest suite. The compatibility job reruns that suite on Python
3.14. The browser job installs the optional Playwright extra and Chromium, then
runs only `test_browser_integration.py`: the fast suite already covered the
other access-layer tests. Browser and compatibility jobs wait for the fast job,
so a simple failure does not spend time setting up Chromium.

This is a **cost policy**, not a reduced release standard. A draft PR cannot be
merged. GitHub still records PR events, but all jobs are skipped before runner
allocation; a skipped check is **not** proof that tests passed. Marking the PR
ready triggers the complete gate, and every subsequent PR commit reruns it.
A full run is also triggered after merge to `main` and for a merge queue.
The workflow keeps stable check names: `test (3.11)`, `test
(3.14)`, and `browser-extra`. If branch protection/rulesets are configured,
require these three on the protected release branch and enable the merge-group
event when using a merge queue. Do not make a path-filtered workflow a required
check: GitHub can leave that check pending when the workflow is skipped.

The workflow grants only `contents: read`, uses Ubuntu runners, caches pip by
`pyproject.toml`, sets bounded job timeouts, and cancels superseded PR/main runs.
It does not upload artifacts by default. There is no scheduled full matrix or
real-network job consuming minutes while nobody is preparing a release.

## Release procedure

1. Keep development PRs in draft while iterating. Draft pushes do not consume
   cloud runner minutes. Run deterministic checks locally with
   `scripts/verify_v06_rc.ps1`; add `-Browser` if Chromium is installed. Run it
   under both supported Python versions for a full local compatibility check.
2. Complete the entitled positive-control and fixed-corpus live acceptance in
   the intended institutional environment, as defined in
   `docs/v0.6-acquisition-maximization.md`. Record results without credentials.
3. Make the final release commit, then mark the PR ready for review. Wait for
   all three CI jobs to pass **on that commit**. If a subsequent commit lands,
   repeat the full gate. Never treat a skipped draft job as a green release gate.
4. Merge only after CI and live acceptance both pass; tag the merged `main`
   commit, not an unmerged PR commit.

`workflow_dispatch` is available once the workflow file exists on the default
branch. It is useful for a manual recheck of `main`; it is not a replacement for
the PR checks on an unmerged release commit.

## Quota and future scaling

Private-repository GitHub-hosted jobs consume the account's Actions allowance.
An exhausted allowance means GitHub may allocate **no runner at all**; changing
YAML or deleting old run logs cannot recover already-used minutes. Wait for the
billing-cycle reset, configure billing deliberately, or use a dedicated,
isolated self-hosted runner if its security and maintenance are acceptable.
Never put a self-hosted runner that handles untrusted PR code on the personal
machine/browser profile used for institutional access.

The original allowance depletion was dominated by branch `push` plus PR
triggering the same Tests workflow for the same commit, multiplied by two or
three concurrent jobs. Branch pushes are now restricted to `main`; all active
v0.6 PR branches must carry this policy. Draft PRs skip every cloud job.

If the deterministic suite grows, first measure per-test time. Split slow
deterministic tests into explicit test groups only when that is cheaper and
clearer than the current one-job suite. Keep the always-on PR check stable;
add expensive integration matrices only to the full tier. Publisher-network
tests remain outside automatic CI because authentication, entitlements and
rate limits are environment-dependent.
