# init/templates

Fast build-time template overlay workspace.

Place generated/replacement template files under:

```text
init/templates/overlay/
```

They are copied into `WORK_DIR` with the same relative path by `post-mods.d/38-template-overlay.sh`.

The overlay tool uses a cache manifest, so unchanged template files are skipped instead of being recopied every run.

Example:

```text
init/templates/overlay/app/src/main/res/values/template_strings.xml
```

is applied to:

```text
WORK_DIR/app/src/main/res/values/template_strings.xml
```

Set `TEMPLATE_OVERLAY=0` to disable this stage.
