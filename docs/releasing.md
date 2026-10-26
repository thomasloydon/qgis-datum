# CI/CD and releasing

## Workflows

| Workflow | Trigger | Jobs |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to `main`, every PR, manual, and called by `release.yml` | **lint** (ruff + metadata check) · **Unit** on Python 3.10 and 3.13 · **QGIS** `ltr` / `stable` / `latest` containers (core tests incl. GDAL + offline smoke test; `latest` is the nightly build and advisory only) · **package** (builds the plugin zip as an artifact) |
| [`integration.yml`](../.github/workflows/integration.yml) | weekly (Mondays) and manual | end-to-end checks against the live catalogues in `qgis/qgis:stable`, kept out of PRs so third-party outages can't block merges |
| [`release.yml`](../.github/workflows/release.yml) | push of a `v*` tag | reruns CI → checks the tag matches `metadata.txt` → GitHub release with the zip → optional upload to plugins.qgis.org |

[Dependabot](../.github/dependabot.yml) opens a monthly PR to keep the workflow actions current.

## Branch and tag protection

- **`main`** only accepts changes through pull requests, and these checks must pass with the branch up to date: `lint`, `Unit (Python 3.10)`, `Unit (Python 3.13)`, `QGIS ltr`, `QGIS stable`, `package`. History stays linear (squash or rebase merges), conversations must be resolved, and force-pushes and deletion are blocked. The repository admin can bypass these rules in an emergency.
- **`v*` tags** can only be created, moved or deleted by the repository admin, so only the maintainer can trigger a release.
- **The `plugins.qgis.org` environment** only accepts deployments from `v*` tags and needs the maintainer's approval.

## Cutting a release

1. Update `datum/metadata.txt`:
   - `version=1.1.0`
   - add a line to `changelog=` (newest first)
2. Add the release to [`CHANGELOG.md`](../CHANGELOG.md).
3. Open a PR, wait for green CI, and merge it.
4. Tag the merged commit and push the tag:

   ```sh
   git switch main && git pull
   git tag v1.1.0
   git push origin v1.1.0
   ```

`release.yml` then creates the GitHub release with `datum-1.1.0.zip` attached and auto-generated notes. Tags with `-alpha`, `-beta` or `-rc` (e.g. `v1.2.0-rc1`) become **pre-releases** and are never sent to plugins.qgis.org.

If the tag and `metadata.txt` disagree, the release stops before anything is published. Delete the tag (`git push --delete origin v1.1.0`), fix the version, and tag again.

## Publishing to plugins.qgis.org

Publishing is off until you set it up:

1. Create an account at [plugins.qgis.org](https://plugins.qgis.org) (it's an OSGeo ID).
2. Put a real contact email in `metadata.txt`. The checker refuses `noreply` addresses because the plugin repository needs a way to reach the maintainer. Make sure `repository` and `tracker` are set as well.
3. Add repository secrets `OSGEO_USERNAME` and `OSGEO_PASSWORD` under **Settings › Secrets and variables › Actions**, or as environment secrets on `plugins.qgis.org`.
4. Tag a release. The `Publish to plugins.qgis.org` job waits for your approval, then uploads the zip through the plugin repository's XML-RPC API.

New plugins are reviewed by the QGIS team before they appear in the Plugin Manager.

## Building locally

```sh
make check   # validate metadata.txt
make zip     # dist/datum-<version>.zip, the same file CI builds
```
