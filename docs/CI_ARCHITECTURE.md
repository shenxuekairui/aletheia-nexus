# CI architecture / 持续集成架构

CI verifies deterministic code behavior. It never logs into a publisher, uses a
personal browser profile, or treats a live publisher response as a release test.
The authenticated live-acceptance program remains a separate, user-operated
step. For the first public v0.6.0 release, its formal qualification is deferred
by the project owner and must be disclosed; CI success does not imply that
institutional access has been certified.

## Execution tiers

| Event | Python 3.11 fast suite | Python 3.14 compatibility | Linux Chromium | Windows 3.11 + Chromium |
|---|---:|---:|---:|---:|
| Draft PR, ordinary commits | no runner | no runner | no runner | no runner |
| Draft PR, newly applied `ci:full` label | yes | yes | yes | yes |
| PR marked ready, including later commits | yes | yes | yes | yes |
| Label applied to ready PR | yes | yes | yes | yes |
| `main` push or merge queue | yes | yes | yes | yes |
| Manual `workflow_dispatch`, `fast` | yes | no | no | no |
| Manual `workflow_dispatch`, `full` | yes | yes | yes | yes |

The fast job runs `pip check`, Ruff format/lint, compilation, and the complete
deterministic pytest suite. The compatibility job reruns that suite on Python
3.14. The browser job installs the optional Playwright extra and Chromium, then
runs only `test_browser_integration.py`: the fast suite already covered the
other access-layer tests. The Windows job checks the installed CLI, runs the
deterministic suite, and repeats the local Chromium integration on the user's
primary platform. Browser, Windows, and compatibility jobs wait for the fast
job, so a simple failure does not spend time setting up Chromium.

This is a **cost policy**, not a reduced release standard. A draft PR cannot be
merged. GitHub still records ordinary draft PR events, but jobs are skipped
before runner allocation; a skipped check is **not** proof that tests passed.
GitHub can display a skipped job as a successful required check, so release
review must inspect the actual job conclusion (`success`, not `skipped`) and
the head SHA, rather than trusting a green PR badge alone.
For an early cloud check on a specific draft head, apply the `ci:full` label
to the PR: that **label event** runs the complete matrix once. To repeat it on
a later draft head, remove and reapply the label. A label left on the PR does
not cause every draft commit to run CI. Applying any other label **to a draft**
does not allocate a runner; labels on a ready PR run the full gate, avoiding a
new skipped check that could be mistaken for a real pass. A one-shot draft check
is useful when changing shared PDF
identity validation, dependencies, platform/browser behavior, or architecture
that cannot be reproduced locally. It is also appropriate before requesting
review on a high-risk change. Do not withhold these checks merely to save
minutes. Conversely, do not label every intermediate typo or documentation
commit.

Marking the PR ready triggers the complete gate, and every subsequent PR commit reruns it.
A full run is also triggered after merge to `main` and for a merge queue.
The workflow keeps stable check names: `test (3.11)`, `test
(3.14)`, `browser-extra`, and `windows (3.11 + Chromium)`. If branch
protection/rulesets are configured, require these four on the protected release branch and enable the merge-group
event when using a merge queue. Do not make a path-filtered workflow a required
check: GitHub can leave that check pending when the workflow is skipped.

The test workflow grants only `contents: read`, uses standard Ubuntu and Windows runners, caches pip by
`pyproject.toml`, sets bounded job timeouts, and cancels superseded PR/main runs.
It does not upload artifacts by default. There is no scheduled full matrix or
real-network job consuming minutes while nobody is preparing a release.

## Release procedure

1. Keep development PRs in draft while iterating. Ordinary draft pushes do not
   consume cloud runner minutes. Run deterministic checks locally with
   `scripts/verify_v06_rc.ps1`; add `-Browser` if Chromium is installed. Run it
   under both supported Python versions for a full local compatibility check.
   If the change has significant cross-platform or browser risk, apply
   `ci:full` once to run the complete hosted matrix on that draft head. Record
   the run URL and commit. If Actions quota is exhausted, report the missing
   cloud evidence explicitly; local success does not waive the release gate.
2. For the first public v0.6.0 release, explicitly disclose that the formal
   entitled positive-control and fixed-corpus live acceptance is deferred.
   Historical cumulative live observations are useful evidence but do not
   satisfy that qualification. Complete it later in the intended institutional
   environment as defined in `docs/v0.6-acquisition-maximization.md`, recording
   results without credentials.
3. Make the final release commit, then mark the PR ready for review. Wait for
   all four CI jobs to conclude `success` **on that commit**. If a subsequent
   commit lands,
   repeat the full gate. Never treat a skipped draft job as a green release gate.
4. If development used stacked PRs, consolidate them into one complete
   `main`-targeted release PR before the final gate. Do not merge a superseded
   base PR separately or infer that its old checks validate the combined diff.
   Merge only after the mandatory code/CI gates pass and the deferred live
   qualification is prominently disclosed; tag the merged `main` commit, not
   an unmerged PR commit.

`workflow_dispatch` is available once the workflow file exists on the default
branch. The `fast`/`full` input belongs to the v0.6 workflow and may not appear
in the Actions UI until that version is on `main`; do not rely on it for an
unmerged PR. Once present, it is useful for a manual recheck of `main`, but
does not replace PR checks on an unmerged release commit. On a draft PR, use
the one-shot `ci:full` label for an attached PR check instead.

## Quota and future scaling

Private-repository GitHub-hosted jobs consume the account's Actions allowance.
An exhausted allowance means GitHub may allocate **no runner at all**; changing
YAML or deleting old run logs cannot recover already-used minutes. Wait for the
billing-cycle reset, configure billing deliberately, or use a dedicated,
isolated self-hosted runner if its security and maintenance are acceptable.
Never put a self-hosted runner that handles untrusted PR code on the personal
machine/browser profile used for institutional access.

The first public release uses a new, clean-history public repository rather
than exposing the prior private repository's commit metadata and Actions logs.
Standard GitHub-hosted runners are free for public repositories; the full
release matrix remains mandatory even though ordinary draft updates are
still skipped to avoid needless work. This does not make larger runners free.

The original allowance depletion was dominated by branch `push` plus PR
triggering the same Tests workflow for the same commit, multiplied by two or
three concurrent jobs. Branch pushes are now restricted to `main`; all active
v0.6/v0.6.1 PR branches must carry this policy. Ordinary draft updates skip every
cloud job, while `ci:full` remains an intentional full-cloud escape hatch.

Review usage by event, branch, job count and runner start time when the monthly
allowance changes unexpectedly; a high number of workflow records is not by
itself equivalent to billable runner minutes. Do not disable the mandatory
ready-PR/main gates to make a release appear green. If usage grows, first
measure job setup/test duration and duplicate triggers, then change only the
expensive tier. Keep audit evidence for any policy change.

If the deterministic suite grows, first measure per-test time. Split slow
deterministic tests into explicit test groups only when that is cheaper and
clearer than the current one-job suite. Keep the always-on PR check stable;
add expensive integration matrices only to the full tier. Publisher-network
tests remain outside automatic CI because authentication, entitlements and
rate limits are environment-dependent.

## v0.6.1 package publishing

`.github/workflows/publish-pypi.yml` is separate from ordinary Tests and runs
only when a non-prerelease GitHub Release is published. It rejects a tag that
does not match `pyproject.toml` exactly, reruns deterministic tests, builds and
checks the sdist/wheel, and smokes the wheel's installed CLI in a clean virtual
environment. A separate `pypi` environment job receives only OIDC
`id-token: write` and uploads through PyPI Trusted Publishing; no long-lived
PyPI secret is stored in GitHub. The PyPI account owner must register the
matching pending/trusted publisher before the first upload, and should protect
the `pypi` environment and release tags. Publishing a GitHub Release is not a
substitute for checking all four Tests jobs on the final commit.
