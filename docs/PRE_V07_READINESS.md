# Before v0.7: acquisition closure and parsing readiness

This is a forward-looking checklist, not a claim that v0.7 parsing already exists. The frozen `v0.6.1` release remains the installable acquisition baseline. Any later fixes belong to a new release; never rewrite the tag or silently change the evidence behind its published test numbers.

## Current evidence and open gates

| Area | Current state | What closes it |
| --- | --- | --- |
| v0.6.1 packaging and CI | PyPI wheel/sdist published; Linux Python 3.11/3.14, Linux Chromium, and Windows Chromium passed on the release commit. | Preserve the run links and fresh-install smoke in release history. |
| Authorized access acceptance | **Passed for one institution on the post-v0.6.1 source commit `7c91c89`**, not on the frozen PyPI release. The fixed 20-paper stress set yielded 18 `VERIFIED`; three manually confirmed controls across ACS and Wiley were 3/3 `VERIFIED`; runner errors were zero. | Preserve the private raw report and manual review, and publish only aggregate, privacy-checked evidence. Do not generalize this result to another institution or a later publisher session. |
| Browser-attributable institution claim | Strict offline machine gate passed: a clean recorded commit, AN-started direct-connection Edge, isolated profile, public base path and Elsevier API excluded for all three controls. Three saved main-article PDFs had matching hashes, titles and visible first-page body text. | Keep the local user entitlement attestation and PDF review alongside the machine result. Browser provenance and user confirmation are evidence, not independent proof of a subscription contract. |
| Cross-institution generalization | Not established; the project owner explicitly chose single-institution qualification for this milestone. | A later, separately authorized second institution would require its own profile, controls and complete report. Do not label the current milestone “cross-institution validated.” |
| Independent onboarding | [First-time trial](https://github.com/shenxuekairui/aletheia-nexus/issues/3) is open; no independent three-minute evidence at v0.6.1 publication. | Record at least one genuine new user's OS, Python version, install time, first result, and confusing steps; fix any reproducible defect. |
| Security and privacy | CI uses synthetic browser fixtures and no institutional credentials. The successful local report had no detected Windows user path, email address, cookie/authorization header, or unredacted signed-query token in a focused scan; raw reports, PDFs, controls and browser profile remain Git-ignored. | Publish aggregate, redacted results only. Repeat the privacy scan before any future public evidence update. |

The single-institution and cross-institution claims are deliberately different. A report that passes the former must **not** be described as the latter. OA/public-fallback files are valuable acquisition evidence but do not prove subscription entitlement.

The successful 2026-09-24 run is a **single-institution, post-release source-branch qualification**. It processed 22 unique DOI records because one of the three controls also belongs to the unchanged 20-paper stress set; this is 20 stress cases plus three controls, not a reduced stress corpus. The stress results were 5/20 through the public base path and 18/20 after browser recovery, with 15 browser recoveries overall and no runner errors. The two non-success stress records remained `ENTITLEMENT_REQUIRED` and `INTERACTION_REQUIRED`. The strict verifier found all three controls browser-verified and no issues. The three first pages were visually reviewed as main articles, with 8, 10 and 8 pages respectively, and each saved PDF SHA-256 matched its acquisition sidecar. The institution-specific control list, raw report, manual attestation, signed URLs, browser profile and copyrighted PDFs stay local and uncommitted.

The first complete attempt did **not** pass: its presumed Elsevier control was `INTERACTION_REQUIRED`, and the user confirmed that institution had no subscription for that title. That report is retained locally as a failure, not relabeled. A different, user-confirmed ACS control was fixed *before* the successful whole-corpus rerun. This prevents after-the-fact denominator changes or pooling successes from separate runs.

The 2026-09-24 UCAS trial was interrupted after 9/23 cases while investigating repeated ScienceDirect/RSC challenge pages. Its partial local report contains 7 `VERIFIED`, 1 `EXHAUSTED`, 1 `INTERACTION_REQUIRED`, and **zero completed entitled controls**. It is diagnostic evidence only, not an acceptance result. The subsequent challenge-state and request-order regression fixes passed deterministic and local Chromium tests but still need a fresh, user-assisted live run before changing the gate above.

In later **single-DOI diagnostics**, AN's Playwright-launched Edge continued to loop on an RSC challenge even after opting into the Windows system proxy, while ordinary Edge could open the PDF. A dedicated Edge started normally with a loopback CDP endpoint and the same trusted system proxy produced a verified RSC main PDF (`10.1039/D6TA02244H`) and a verified ScienceDirect main PDF (`10.1016/j.desal.2023.117146`). The ScienceDirect attempt still observed repeated challenge states; these two cases are not the three entitled controls and do not close the institutional gate. The CDP browser was closed after testing, leaving its local profile intact.

A subsequent **direct-connection** retest used AN's own dedicated CDP Edge with `--no-proxy-server` and the same isolated profile. RSC `10.1039/D6TA02244H` yielded a 20-page `VERIFIED` main PDF. The first ScienceDirect attempt was incorrectly marked `VERIFIED`: it was a one-page corrigendum that cited the requested original DOI. The identity validator now rejects a correction explicitly labeled with the original article DOI; after this regression fix, the direct retest resumed from an Elsevier SSO pause and obtained the 26-page original main PDF, `VERIFIED`. The earlier one-page result must not be counted. These single-paper diagnostics show that the dedicated browser can work without the system proxy, but they do not prove that direct connection is generally more reliable or close the institutional gate.

The strict verifier now accepts a report from an AN-started dedicated CDP browser but still rejects attachment to an already-running endpoint. The report records its launch mode and source commit; a dirty or unidentifiable checkout cannot pass. This is useful machine evidence of the launch path, **not cryptographic proof of the institution's subscription or the PDF's contents**. Manual same-session entitlement and PDF review remain mandatory. The successful CDP single-paper diagnostics above are still not a passing qualification.

## Live qualification protocol

1. In the intended institution, manually confirm the **main article PDF** of at least three non-open-access DOI controls across two publisher/access families in the same account, network and browser environment. The access family and exact title belong in the git-ignored local benchmark; do not submit credentials or session files.
2. Use a fresh, institution-specific AN browser profile and a clean recorded code commit. Run the fixed 20-paper stress corpus and controls with `--require-entitled-controls`, `--no-elsevier-api`, visible Edge/Chromium, and enough interaction time for legitimate SSO/MFA/CAPTCHA. On Windows, a dedicated loopback CDP Edge can be started by the runner with `--cdp-endpoint http://127.0.0.1:9222 --cdp-navigate`; use `--browser-use-system-proxy` only if the trusted current system proxy is part of the intended access environment. Ensure the endpoint is free before starting: attachment to an existing browser deliberately fails the strict verifier. AN waits for a usable page and resumes automatically; do not try to automate or bypass the challenge itself.
3. Preserve the raw report and PDF outputs under `downloads/`, which Git ignores. Run the strict offline verifier, for example:

   ```powershell
   python scripts/verify_institutional_acceptance.py `
     downloads/<run>/report.json `
     --institution-id <safe-label> `
     --expected-profile <exact-profile-name> `
     --output downloads/<run>/institution-review.json
   ```

4. Inspect each entitled control's saved PDF title, DOI, main-text role and hash/sidecar, plus a sample of non-success classifications. The verifier reports `manual_pdf_and_session_review: pending` even when its machine gate passes; document this human check separately. Treat a failed control as a defect or an entitlement uncertainty to investigate, not as a removable denominator.
5. Record the exact AN version/commit, date, institution pseudonym, network context category, benchmark hash, profile name, report hash, all machine-gate outcomes, manual-review result, and limitations. Do not publish the actual authenticated profile, raw report, signed URLs or copyrighted PDFs.

The legacy acceptance runner tests *one* institution per run. A second institution must use a separate profile, local control file, output directory, and report. Compare results per institution; do not reuse a PDF/checkpoint created under another institution to claim access.

## v0.7 design entry

v0.7 may begin a **scientific content parsing layer** under the [versioned parsing entry contract](V07_PARSING_CONTRACT.md). Its input must be a locally existing `VERIFIED` main-article PDF with a matching SHA-256 and provenance sidecar. Parsing must not silently upgrade an `EXHAUSTED`, `INTERACTION_REQUIRED`, or unverified file into trusted input. The contract is written; the rights-cleared fixture set and parser implementation are not yet complete.

Define a small versioned output schema before implementation: document identity, section hierarchy, text blocks, page/span anchors, bibliography links, tables/figures as referenced objects, extraction method, uncertainty, and errors. Source anchors must let a researcher navigate back to the PDF passage. “Parsed” is not “scientifically true”; inference and claim verification are later, separate layers.

Before selecting a parser or model, build a rights-cleared fixture set spanning native PDFs, multi-column layouts, equations, tables, scanned/low-text pages, and supporting-information traps. Measure identity/anchor correctness, section/table recall, false associations, runtime and memory on Windows and Linux. Do not commit third-party full-text PDFs without redistribution rights. Keep the acquisition result schema stable and add parser output as a new artifact rather than overwriting the original evidence.

Knowledge graphs, autonomous research agents, and scientific truth assessment remain **planned**. Their public capability label must not be promoted merely because the parsing design or prototype exists.
