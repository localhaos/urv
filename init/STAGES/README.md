# URV staged bootstrap pipeline

`start` can run the bootstrap pipeline from a selected stage to avoid repeating already-approved work.

Stages:

| Stage | Name | Purpose |
| --- | --- | --- |
| `STAGE_1` | `pre-clone` | pre-clone hooks |
| `STAGE_2` | `clone` | clone or checkout upstream into `WORK_DIR` |
| `STAGE_3` | `post-clone` | post-clone hooks |
| `STAGE_4` | `setup` | local.properties, gradlew, Gradle version smoke test |
| `STAGE_5` | `mods` | pre-mods, manifest mods, post-mods |
| `STAGE_6` | `pre-build` | pre-build patchers and hooks |
| `STAGE_7` | `build` | Gradle build and log-driven patch retry |
| `STAGE_8` | `post-build` | post-build hooks |
| `STAGE_9` | `collect` | pre-upload hooks, output collection, post-upload hooks |

Resume controls:

```bash
START_STAGE=STAGE_5 ARTIFACTS_APPROVED=1 ./start
START_STAGE=5 STOP_AFTER_STAGE=7 ARTIFACTS_APPROVED=1 ./start
```

When `START_STAGE` is greater than `STAGE_1`, `start` requires either:

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

This avoids accidentally resuming from unverified intermediate artifacts.
