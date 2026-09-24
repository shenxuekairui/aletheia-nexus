# Security Policy

## Supported versions

Security fixes are considered for the latest public release and the current development branch. Older frozen tags are historical records, not maintained branches.

## Reporting a vulnerability

Please do **not** publish an exploit, credential, private URL, institutional session, or affected user's data in a GitHub issue or pull request. Use the repository's **Security → Report a vulnerability** private reporting flow if it is available. If private reporting is not enabled, open a minimal public issue asking for a private contact channel **without including vulnerability details**; a maintainer will arrange a secure handoff.

Useful private report details include affected version/commit, reproduction steps using synthetic data, expected versus actual behavior, and possible impact. We will acknowledge the report, assess severity and affected versions, coordinate a fix, and credit the reporter if they wish. We do not promise a fixed response or remediation deadline for this early-stage project.

## Sensitive boundaries

AN handles untrusted publisher pages, URLs, PDFs, metadata, and optional authenticated browser sessions. Relevant security issues include SSRF or local-network access, credential/cookie leakage into reports, unsafe file paths, unbounded downloads, PDF identity bypass, and cross-origin browser behavior. The project does not ask users to give maintainers their institutional credentials or article files. Never test against accounts, institutions, or systems you do not control or have authorization to use.
