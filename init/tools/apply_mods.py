#!/usr/bin/env python3
"""
Deterministic overlay/patch engine for the URV bootstrap repository.

The manifest is YAML when PyYAML is available. A JSON manifest is also accepted
because JSON is a YAML subset. This keeps CI reproducible while allowing local
usage without custom build tooling when PyYAML is already installed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class PatchError(RuntimeError):
    """Raised for deterministic, user-actionable patch failures."""


@dataclass(frozen=True)
class Context:
    repo: Path
    manifest: Path
    root: Path


def load_manifest(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")

    try:
        import yaml  # type: ignore

        data = yaml.safe_load(raw)
    except ModuleNotFoundError:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PatchError(
                "Manifest requires PyYAML unless it is valid JSON. "
                "Install with: python3 -m pip install PyYAML"
            ) from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise PatchError("Manifest root must be a mapping/object.")
    return data


def safe_repo_path(repo: Path, relative: str) -> Path:
    if not relative or not isinstance(relative, str):
        raise PatchError("Target path must be a non-empty string.")

    candidate = (repo / relative).resolve()
    repo_resolved = repo.resolve()

    try:
        candidate.relative_to(repo_resolved)
    except ValueError as exc:
        raise PatchError(f"Target path escapes repository: {relative}") from exc

    return candidate


def source_path(ctx: Context, source: str) -> Path:
    if not source or not isinstance(source, str):
        raise PatchError("Source path must be a non-empty string.")

    path = Path(source)
    if not path.is_absolute():
        path = ctx.root / path

    resolved = path.resolve()
    root_resolved = ctx.root.resolve()

    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PatchError(f"Source path escapes bootstrap root: {source}") from exc

    return resolved


def read_replacement(ctx: Context, operation: dict[str, Any]) -> str:
    if "replace_from" in operation:
        src = source_path(ctx, str(operation["replace_from"]))
        if not src.is_file():
            raise PatchError(f"replace_from is not a file: {src}")
        return src.read_text(encoding="utf-8")

    replace = operation.get("replace", "")
    if not isinstance(replace, str):
        raise PatchError("replace must be a string.")
    return os.path.expandvars(replace)


def ensure_expected(text: str, operation: dict[str, Any]) -> None:
    expected = operation.get("expected_contains")
    if expected is None:
        return
    if not isinstance(expected, str):
        raise PatchError("expected_contains must be a string.")
    if expected not in text:
        raise PatchError(f"Expected anchor is missing: {expected!r}")


def copy_overlay(ctx: Context, operation: dict[str, Any]) -> None:
    source = source_path(ctx, str(operation.get("source", "")))
    target = safe_repo_path(ctx.repo, str(operation.get("target", "")))
    mode = str(operation.get("mode", "replace"))

    if not source.exists():
        raise PatchError(f"Overlay source does not exist: {source}")

    if source.is_dir():
        if mode != "replace":
            raise PatchError("Directory overlays only support mode=replace.")
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)
        return

    target.parent.mkdir(parents=True, exist_ok=True)

    if mode == "replace":
        shutil.copy2(source, target)
    elif mode in {"append", "prepend"}:
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        incoming = source.read_text(encoding="utf-8")
        target.write_text(
            existing + incoming if mode == "append" else incoming + existing,
            encoding="utf-8",
        )
    else:
        raise PatchError(f"Unsupported overlay mode: {mode}")


def apply_literal(text: str, operation: dict[str, Any], replacement: str) -> tuple[str, int]:
    needle = operation.get("find")
    if not isinstance(needle, str) or not needle:
        raise PatchError("literal patch requires non-empty find string.")

    count = int(operation.get("count", 1))
    if count < 0:
        raise PatchError("count must be >= 0.")

    occurrences = text.count(needle)
    changed = occurrences if count == 0 else min(occurrences, count)
    return text.replace(needle, replacement, count), changed


def apply_regex(text: str, operation: dict[str, Any], replacement: str) -> tuple[str, int]:
    pattern = operation.get("find")
    if not isinstance(pattern, str) or not pattern:
        raise PatchError("regex patch requires non-empty find pattern.")

    flags = 0
    for flag_name in operation.get("flags", []) or []:
        if flag_name == "MULTILINE":
            flags |= re.MULTILINE
        elif flag_name == "DOTALL":
            flags |= re.DOTALL
        elif flag_name == "IGNORECASE":
            flags |= re.IGNORECASE
        else:
            raise PatchError(f"Unsupported regex flag: {flag_name}")

    count = int(operation.get("count", 1))
    if count < 0:
        raise PatchError("count must be >= 0.")

    return re.subn(pattern, replacement, text, count=count, flags=flags)


def apply_marker(text: str, operation: dict[str, Any], replacement: str) -> tuple[str, int]:
    begin = operation.get("begin")
    end = operation.get("end")
    include_markers = bool(operation.get("include_markers", False))

    if not isinstance(begin, str) or not begin:
        raise PatchError("marker patch requires begin.")
    if not isinstance(end, str) or not end:
        raise PatchError("marker patch requires end.")

    start = text.find(begin)
    if start < 0:
        raise PatchError(f"Begin marker not found: {begin!r}")

    finish = text.find(end, start + len(begin))
    if finish < 0:
        raise PatchError(f"End marker not found: {end!r}")

    if include_markers:
        replace_start = start
        replace_end = finish + len(end)
    else:
        replace_start = start + len(begin)
        replace_end = finish

    return text[:replace_start] + replacement + text[replace_end:], 1


def skip_string_or_comment(text: str, index: int) -> int:
    ch = text[index]

    if ch in {'"', "'", "`"}:
        quote = ch
        index += 1
        while index < len(text):
            if text[index] == "\\":
                index += 2
                continue
            if text[index] == quote:
                return index + 1
            index += 1
        return index

    if text.startswith("//", index):
        newline = text.find("\n", index + 2)
        return len(text) if newline < 0 else newline + 1

    if text.startswith("/*", index):
        end = text.find("*/", index + 2)
        return len(text) if end < 0 else end + 2

    return index


def find_balanced_block_end(text: str, open_brace: int) -> int:
    depth = 0
    index = open_brace

    while index < len(text):
        skipped = skip_string_or_comment(text, index)
        if skipped != index:
            index = skipped
            continue

        ch = text[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1

    raise PatchError("Unbalanced braces while scanning function body.")


def find_function_bounds(text: str, name: str) -> tuple[int, int]:
    escaped = re.escape(name)
    patterns = [
        rf"(?m)^[ \t]*(?:@\w+(?:\([^)]*\))?\s*)*(?:(?:public|private|protected|internal|open|override|suspend|inline|operator|tailrec|static|final|abstract)\s+)*fun\s+{escaped}\s*(?:<[^>]+>)?\s*\(",
        rf"(?m)^[ \t]*(?:(?:public|private|protected|static|final|abstract|synchronized|native)\s+)*(?:[\w<>\[\],.?]+\s+)+{escaped}\s*\(",
        rf"(?m)^[ \t]*(?:export\s+)?(?:async\s+)?function\s+{escaped}\s*\(",
        rf"(?m)^[ \t]*(?:export\s+)?(?:const|let|var)\s+{escaped}\s*=\s*(?:async\s*)?(?:\([^)]*\)|[^=]+)\s*=>\s*\{{",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue

        open_brace = text.find("{", match.end())
        if open_brace < 0:
            raise PatchError(f"Function declaration found without body: {name}")

        line_start = text.rfind("\n", 0, match.start()) + 1
        end = find_balanced_block_end(text, open_brace)
        return line_start, end

    raise PatchError(f"Function not found: {name}")


def apply_function(text: str, operation: dict[str, Any], replacement: str) -> tuple[str, int]:
    name = operation.get("name")
    if not isinstance(name, str) or not name:
        raise PatchError("function patch requires name.")

    start, end = find_function_bounds(text, name)

    if not replacement.endswith("\n"):
        replacement += "\n"

    return text[:start] + replacement + text[end:], 1


def apply_patch(ctx: Context, operation: dict[str, Any]) -> None:
    target = safe_repo_path(ctx.repo, str(operation.get("target", "")))
    if not target.is_file():
        raise PatchError(f"Patch target is not a file: {target}")

    text = target.read_text(encoding="utf-8")
    ensure_expected(text, operation)

    replacement = read_replacement(ctx, operation)
    strategy = str(operation.get("strategy", ""))

    if strategy == "literal":
        new_text, changed = apply_literal(text, operation, replacement)
    elif strategy == "regex":
        new_text, changed = apply_regex(text, operation, replacement)
    elif strategy == "marker":
        new_text, changed = apply_marker(text, operation, replacement)
    elif strategy == "function":
        new_text, changed = apply_function(text, operation, replacement)
    else:
        raise PatchError(f"Unsupported patch strategy: {strategy}")

    must_change = bool(operation.get("must_change", True))
    if must_change and changed == 0:
        raise PatchError(f"Patch made no changes: {operation.get('id', target)}")

    if new_text != text:
        target.write_text(new_text, encoding="utf-8")


def enabled_operations(items: Any) -> Iterable[dict[str, Any]]:
    if items is None:
        return []
    if not isinstance(items, list):
        raise PatchError("overlays/patches must be lists.")

    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise PatchError("Each operation must be a mapping/object.")
        if bool(item.get("enabled", True)):
            result.append(item)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Apply URV bootstrap overlays and patches.")
    parser.add_argument("--repo", required=True, type=Path, help="Cloned upstream repository path.")
    parser.add_argument("--manifest", required=True, type=Path, help="YAML/JSON manifest path.")
    parser.add_argument("--root", required=True, type=Path, help="Bootstrap repository root.")
    args = parser.parse_args(argv)

    ctx = Context(
        repo=args.repo.resolve(),
        manifest=args.manifest.resolve(),
        root=args.root.resolve(),
    )

    if not ctx.repo.is_dir():
        raise PatchError(f"Repo path does not exist: {ctx.repo}")
    if not ctx.manifest.is_file():
        raise PatchError(f"Manifest does not exist: {ctx.manifest}")

    manifest = load_manifest(ctx.manifest)

    for operation in enabled_operations(manifest.get("overlays")):
        op_id = operation.get("id", operation.get("target", "<overlay>"))
        print(f"[mods] overlay: {op_id}", flush=True)
        copy_overlay(ctx, operation)

    for operation in enabled_operations(manifest.get("patches")):
        op_id = operation.get("id", operation.get("target", "<patch>"))
        print(f"[mods] patch: {op_id}", flush=True)
        apply_patch(ctx, operation)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except PatchError as exc:
        print(f"[mods][ERR] {exc}", file=sys.stderr)
        raise SystemExit(2)
