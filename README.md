# URV bootstrap

Repo contains a reproducible bootstrap layer for building a modified copy of
`Jman-Github/Universal-ReVanced-Manager` or another compatible Android/Gradle
project.

Main entrypoint:

```bash
./start
./start https://github.com/Jman-Github/universal-revanced-manager.git dev
./start https://github.com/MorpheApp/morphe-cli.git branchid
```

When no repository or branch/ref is provided, the bootstrap uses:

```text
UPSTREAM_REPO=https://github.com/Jman-Github/universal-revanced-manager.git
UPSTREAM_REF=dev
```

## Layout

```text
start                          root bootstrap runner
.github/workflows/start.yml    GitHub Actions pipeline
init/config/*.env              reusable presets
init/mods.yml                  overlay / patch manifest
init/overlays/                 complete files copied into upstream checkout
init/hooks/<stage>.d/*.sh      update-resistant hook points
init/tools/apply_mods.py       deterministic patch engine
init/tools/urvm_workarounds.py URVM-specific source workarounds
init/tools/add_vineflower_gradle.py Vineflower Gradle dependency injector
```

## URVM workarounds

`init/hooks/post-mods.d/20-urvm-app-list-and-update-workarounds.sh` runs
after generic overlays/patches and applies `init/tools/urvm_workarounds.py`.

Current workarounds:

```text
1. Patch PM.appList so the app selector does not collapse to an empty list while
   bundle metadata is empty, disabled, loading or transiently broken.
2. Inject PreferencesManager into PM and use disableUniversalPatchCheck as the
   switch for installed-app universal fallback.
3. Expose all bundle metadata through bundleInfoFlow for UI reads while keeping
   enabledBundlesInfoFlow available for strict patching/version logic.
4. Make optional runtime modules conditional in settings.gradle.kts when the
   upstream branch does not ship the same module set.
```

## Vineflower

`init/hooks/post-mods.d/30-add-vineflower-gradle.sh` injects Vineflower through
Gradle instead of vendoring a JAR. It patches:

```text
gradle/libs.versions.toml
app/build.gradle.kts
```

Default Maven coordinate:

```text
org.vineflower:vineflower:1.12.0
```

Override the version with:

```bash
VINEFLOWER_VERSION=1.12.0 ./start
```

or with the `vineflower_version` input in the GitHub Actions workflow.

## Patch model

Prefer hooks and overlays over line-number patches. The upstream app can change,
so modifications should be anchored to stable files, markers, symbols or
functions.

Supported stages:

```text
pre-clone
post-clone
pre-setup
post-setup
pre-mods
post-mods
pre-build
post-build
pre-upload
post-upload
```

Supported manifest operations:

```text
overlays: full file/directory replace, append or prepend
patches: literal, regex, marker, function
```

`function` patching is intended for Kotlin/Java/JS/TS-style brace-delimited
functions. For complex rewrites, use a hook script and a parser-aware tool.

## GitHub Actions

Use **Actions → URV Bootstrap / Sync / Build**.

Important inputs:

```text
upstream_repo          upstream Git URL; empty means default
branch_id              branch, tag or commit; empty means dev
gradle_task            default: assembleRelease
vineflower_version     default: 1.12.0
run_build              whether to run Gradle build
run_emulator_wtf       optional emulator.wtf test step
upload_generated_tree  force-push modified upstream tree to generated/<run_number>
```

Artifacts are uploaded from `out/` by `actions/upload-artifact@v4`.

## Secrets

Optional:

```text
EW_API_TOKEN           emulator.wtf token
GITHUB_TOKEN           injected automatically by GitHub Actions
```

For GitHub Packages dependencies, the workflow passes `GITHUB_TOKEN` and
`GITHUB_ACTOR` into Gradle, which matches the upstream `settings.gradle.kts`
credential fallback.
