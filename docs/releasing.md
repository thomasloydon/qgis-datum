# CI/CD and releasing

## Workflows

| Workflow | Trigger | Jobs |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to `main`, every PR, manual, and called by `release.yml` | **lint** (ruff + metadata check) · **Unit** on Python 3.10 and 3.13 · **QGIS** `ltr` / `stable` / `latest` containers (core tests incl. GDAL + offline smoke test; `latest` is the nightly build and advisory only) · **package** (builds the plugin zip as an artifact) |
| [`integration.yml`](../.github/workflows/integration.yml) | weekly (Mondays) and manual | end-to-end checks against the live catalogues in `qgis/qgis:stable`, kept out of PRs so third-party outages can't block merges |
| [`release.yml`](../.github/workflows/release.yml) | push of a `v*` tag | reruns CI → checks the tag matches `metadata.txt` → GitHub release with the zip → upload to plugins.qgis.org (token or OSGeo ID; skipped if neither is set) |

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

The release workflow uploads to plugins.qgis.org once it has credentials. There are two ways to authenticate.

### With an upload token (works when you sign in with GitHub)

plugins.qgis.org issues **per-plugin upload tokens**. They're bound to one plugin and don't expire until you delete them. A token can only be created once the plugin exists on the site, so the **first version is uploaded by hand**:

1. Sign in at [plugins.qgis.org](https://plugins.qgis.org) (signing in with GitHub is fine).
2. Build the zip (`make zip`, or download `datum-<version>.zip` from the GitHub release) and upload it at [plugins.qgis.org/plugins/add](https://plugins.qgis.org/plugins/add/). The QGIS team reviews new plugins before they're listed.
3. On the plugin's page, click **Tokens** (or go to `https://plugins.qgis.org/plugins/datum/tokens/`), then **Generate a New Token**, and copy the **Access token**. Store it straight away as a secret (next step), and add a description such as *GitHub Actions* so you can tell tokens apart.
4. In GitHub, go to **Settings › Environments › plugins.qgis.org › Environment secrets › Add environment secret**, with name `QGIS_PLUGIN_TOKEN` and the token as the value.

From then on, every `v*` tag publishes automatically after you approve the job. The workflow posts the zip to `https://plugins.qgis.org/plugins/api/datum/version/add/` with `Authorization: Bearer <token>`. To rotate the token, generate a new one, update the secret, and delete the old token on the site.

### With an OSGeo ID (username and password)

If you have an [OSGeo ID](https://id.osgeo.org), add `OSGEO_USERNAME` and `OSGEO_PASSWORD` as environment secrets instead. The workflow uses the XML-RPC API, which can also create the plugin on its first upload. If both are set, the token wins.

### Either way

- `metadata.txt` needs a real contact `email`, plus `repository` and `tracker`. The release check enforces this.
- Pre-release tags (`-alpha`, `-beta`, `-rc`) are never published.
- New versions of an existing plugin may also be held for review if your account isn't yet trusted to approve its own uploads.

## Building locally

```sh
make check   # validate metadata.txt
make zip     # dist/datum-<version>.zip, the same file CI builds
```
