# Contributing to Datum

Thanks for helping make open data easier to use in QGIS. Every kind of contribution is useful, including bug reports, data-source suggestions, documentation fixes and code.

## Ways to help

- **Report a bug.** Use the [bug report form](https://github.com/thomasloydon/qgis-datum/issues/new?template=bug_report.yml). Include your QGIS version and OS, what you searched or added, and the log from **View › Panels › Log Messages › Datum**.
- **Suggest a data source.** Use the [data source form](https://github.com/thomasloydon/qgis-datum/issues/new?template=data_source.yml). A link to the service or catalogue API makes it quick to add.
- **Request a feature** with the [feature form](https://github.com/thomasloydon/qgis-datum/issues/new?template=feature_request.yml).
- **Fix something.** Issues labelled `good first issue` are a good place to start.

For security problems, don't open an issue. Follow [SECURITY.md](SECURITY.md) instead.

## Making a change

1. Fork the repository and create a branch from `main`.
2. Set up the plugin for development: see [docs/development.md](docs/development.md).
3. Make your change, with tests where it makes sense. Provider and URL logic is easy to unit-test with a fake `http` (see `tests/test_core.py`).
4. Check it locally:

   ```sh
   make lint          # ruff
   make test          # unit tests (no QGIS needed)
   make test-smoke    # headless QGIS checks, if you have QGIS installed
   ```

5. Open a pull request against `main` and fill in the template.

`main` is protected: every change goes through a PR, and CI must pass (lint, unit tests, and the headless QGIS LTR and stable checks). PRs are squash-merged, so the PR title becomes the commit message. Please make it a clear, imperative summary, e.g. *Add Yukon open data portal*.

## Guidelines

- Keep `datum/core/` free of Qt widgets. Keep the pure modules (`models`, `sniff`, `providers`, `catalog`, `dem` planning) free of QGIS imports, so they stay unit-testable.
- Do network and GDAL work in a `QgsTask` (`core.tasks.run`), never on the UI thread.
- Route every "add this to the map" through `DataActions.add` so all tabs behave the same.
- Write code that works under both Qt5 and Qt6: use fully qualified enums such as `Qt.AlignmentFlag.AlignLeft`.
- Before adding a quick-add layer or source URL, check that it works, and record its licence in [docs/data-sources.md](docs/data-sources.md).
- Keep user-facing text short, in sentence case, and free of jargon where possible.

## Licence

By contributing, you agree that your contribution is licensed under the project's [GPL-2.0-or-later](LICENSE) licence.

## Code of conduct

Everyone taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).
