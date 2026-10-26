# Security policy

## Supported versions

Security fixes go into the latest release. Please upgrade to it before reporting.

## Reporting a vulnerability

**Please don't open a public issue for security problems.**

Report them privately through GitHub's [private vulnerability reporting](https://github.com/thomasloydon/qgis-datum/security/advisories/new) (the **Security** tab, then **Report a vulnerability**). Please include:

- what the issue is and what an attacker could do with it,
- steps to reproduce, or a proof of concept,
- the Datum and QGIS versions affected.

You can expect an acknowledgement within a week. Once a fix is ready it ships in a new release, and the advisory is published with credit to you, unless you'd rather stay anonymous.

## Scope

Datum runs inside QGIS with the user's permissions. It downloads and opens data from remote catalogues, and it uploads release zips from CI. Examples of issues worth reporting:

- crafted catalogue or service responses that cause code execution, file writes outside the chosen folders, or credential leaks,
- problems in the release pipeline (`.github/workflows`, `scripts/release.py`) that could let someone publish a tampered plugin.

Vulnerabilities in QGIS, GDAL or the third-party data services themselves should go to those projects.
