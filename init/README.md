# init

This directory is the stable modification layer used by `../start`.

## Recommended modification order

1. Put complete replacement files under `init/overlays`.
2. Describe deterministic file/regex/function changes in `init/mods.yml`.
3. Put procedural or parser-aware changes in `init/hooks/<stage>.d/*.sh`.

Avoid patching by line numbers. Upstream can move code without changing the
semantic function or marker.

## Hook environment

Every hook receives:

```text
ROOT_DIR
WORK_DIR
OUT_DIR
UPSTREAM_REPO
UPSTREAM_REF
PATCH_MANIFEST
GRADLE_TASK
RUN_BUILD
RUN_MODS
```

Hook scripts are executed with `bash`. Non-`.sh` files are executed only when
they have the executable bit set in the runtime filesystem.

## Manifest safety

`apply_mods.py` rejects target paths escaping the upstream checkout. Patches
should use `expected_contains` when possible, so a changed upstream contract
fails early instead of silently producing a corrupt build.
