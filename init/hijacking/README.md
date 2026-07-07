# init/hijacking

Controlled build-time overlay workspace.

This folder is for intentional local source/resource overrides applied to the generated upstream tree. It does not perform runtime/session/browser hijacking.

Layout:

```text
init/hijacking/
  overlay/      # files copied into WORK_DIR with the same relative path
  manifest.json # optional metadata for review/approval
```

Example:

```text
init/hijacking/overlay/app/src/main/res/values/strings.xml
```

would replace:

```text
.work/upstream/app/src/main/res/values/strings.xml
```

The overlay is only applied by `init/tools/hijacking_overlay.py` or a hook that calls it.
