# Publication / 公開手順

This file is generated for `keimag-dev/pelican-egg-7-days-to-die-arm64`; it does not prove that the repository,
Actions run, release, or Pelican import exists or works.

## Import URL / インポート URL

Recommended, only after the first successful stable release:

https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json

Alternative (unreleased `main`; not CI-gated at download time):

https://raw.githubusercontent.com/keimag-dev/pelican-egg-7-days-to-die-arm64/main/egg-7-days-to-die-arm64.json

Use the release URL as `meta.update_url`. Forks must regenerate the tracked
export with their own URL before enabling CI. CI derives the owner/repository
from `GITHUB_REPOSITORY`, not a secret. No OCI, SSH, Panel, or personal token
is needed. Only the publishing step receives the ephemeral `GITHUB_TOKEN`.

## Builder contract / ビルダー契約

The standalone repository must contain `build_egg.py`, its source files,
`tests/` (stdlib unittest), and the committed root `egg-7-days-to-die-arm64.json`. The builder
must support:

```sh
python build_egg.py --update-url https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json
```

It must write that JSON filename in the current directory, without network,
clock-dependent data, games, JARs, credentials, EULA acceptance, or git writes.
Adapt the builder CLI before enabling this workflow if it differs. The guard
rebuilds twice, compares bytes, validates the export, checks `bash -n`, and
rejects export drift. Module tests must be offline; live game install/start/
stop/reinstall-preservation testing is a separate authorized integration job.

## Release / リリース

After CI and manual isolated integration testing pass, review the exact commit.
Protect `main` and `v*` tags (rulesets) and restrict tag creation to maintainers.
Public standard `ubuntu-24.04` and `ubuntu-24.04-arm` runners run Python 3.11
and 3.13; no paid larger runner or self-hosted runner is used.

Maintainer commands (not executed by the generator):

```sh
python -m unittest discover -s tests -v
python build_egg.py --update-url https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json
python -W error scripts/publication_guard.py --verify-build
git diff --exit-code -- egg-7-days-to-die-arm64.json
git tag v1.0.0
git push origin v1.0.0
gh run list --workflow release.yml
gh run view RUN_ID --exit-status
gh release download v1.0.0 --dir downloaded --pattern egg-7-days-to-die-arm64.json --pattern SHA256SUMS
(cd downloaded && sha256sum --check SHA256SUMS)
curl --fail --location --output imported.json https://github.com/keimag-dev/pelican-egg-7-days-to-die-arm64/releases/latest/download/egg-7-days-to-die-arm64.json
```

Release publication waits for the reusable full CI matrix. Only stable
`vMAJOR.MINOR.PATCH` tags publish; no prerelease can silently replace `latest`.
Existing release assets are not overwritten. Releases contain JSON and a
SHA-256 checksum file; GitHub provides the tagged source archive separately.
Review published `latest`, checksums, and actual Pelican URL import manually;
a successful static check is not a live game or Panel import test.

公開前に CI・隔離環境での実機テストを確認してください。初回リリース前の
URL は未作成です。`latest` の取得・チェックサム・Pelican URL 直接インポートは
公開後に実確認が必要です。EULA 同意・個人認証情報は自動化しません。
