# init

This directory is the stable modification layer used by `../start`.

## Layout

```text
init/
  STAGES/       # declarative stage map: STAGE_1 ... STAGE_9
  tools/        # reusable utilities and patchers
  hooks/        # executable stage hooks
  hijacking/    # controlled build-time overlay; no runtime/session hijacking
  config/       # default.env and runtime defaults
  overlays/     # complete replacement overlays used by mods/tools
```

Root-level user-authored application code belongs in:

```text
my_code/
```

`my_code/` is intentionally not applied automatically. A hook, patcher, or manifest entry must explicitly consume it.

## Staged execution

`start` now supports resumable stages:

| Stage | Label |
| --- | --- |
| `STAGE_1` | `pre-clone` |
| `STAGE_2` | `clone` |
| `STAGE_3` | `post-clone` |
| `STAGE_4` | `setup` |
| `STAGE_5` | `mods` |
| `STAGE_6` | `pre-build` |
| `STAGE_7` | `build` |
| `STAGE_8` | `post-build` |
| `STAGE_9` | `collect` |

Examples:

```bash
START_STAGE=STAGE_5 ARTIFACTS_APPROVED=1 ./start
START_STAGE=5 STOP_AFTER_STAGE=7 ARTIFACTS_APPROVED=1 ./start
```

When `START_STAGE` is greater than `STAGE_1`, `start` requires explicit approval:

```bash
ARTIFACTS_APPROVED=1
```

or an approval manifest:

```text
out/approved-artifacts.env
```

with:

```env
APPROVED=1
```

This prevents accidentally resuming from unreviewed intermediate artifacts.

## Recommended modification order

1. Put complete replacement files under `init/overlays` or `init/hijacking/overlay` when intentional replacement is required.
2. Describe deterministic file/regex/function changes in `init/mods.yml`.
3. Put procedural or parser-aware changes in `init/hooks/<stage>.d/*.sh`.
4. Put reusable utilities in `init/tools/`.

Avoid patching by line numbers unless the line patch has a strict marker or `expected_contains` guard. Upstream can move code without changing the semantic function or marker.

## Hook environment

Every hook receives at least:

```text
ROOT_DIR
WORK_DIR
OUT_DIR
UPSTREAM_REPO
UPSTREAM_REF
PATCH_MANIFEST
GRADLE_TASK
START_STAGE
STOP_AFTER_STAGE
ARTIFACTS_APPROVED
APPROVED_ARTIFACTS_MANIFEST
CURRENT_STAGE
CURRENT_STAGE_ID
CURRENT_STAGE_LABEL
RUN_BUILD
RUN_MODS
```

Hook scripts are executed with `bash`. Non-`.sh` files are executed only when they have the executable bit set in the runtime filesystem.

## Hijacking overlay

`init/hijacking/overlay` is a controlled build-time file overlay. A file placed at:

```text
init/hijacking/overlay/app/src/main/res/values/strings.xml
```

is copied to:

```text
WORK_DIR/app/src/main/res/values/strings.xml
```

by `init/tools/hijacking_overlay.py` when `HIJACKING_OVERLAY=1`.

This is not runtime, credential, browser, network, or session hijacking.

## Manifest safety

`apply_mods.py` rejects target paths escaping the upstream checkout. Patches should use `expected_contains` when possible, so a changed upstream contract fails early instead of silently producing a corrupt build.
