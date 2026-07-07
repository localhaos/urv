#!/usr/bin/env python3
"""Android resource fixer for generated URV upstream trees.

Scope:
- detect localized resources without a default value;
- add safe default string values for known URV/ReVanced resource keys;
- optionally synthesize placeholder defaults for missing locale-only strings;
- validate XML parseability for res/values*/ XML files;
- parse AAPT/resource shrinker logs and report resource diagnostics.

The tool is conservative: it only mutates default res/values XML files and does
not edit drawable/layout/style resources unless a future explicit rule is added.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.sax.saxutils import escape

RESOURCE_LOG_PATTERNS = (
    "without required default value",
    "Android resource linking failed",
    "AAPT:",
    "aapt2",
    "error: resource",
    "resource ",
    "res/values",
)

KNOWN_STRING_DEFAULTS = {
    "bundle_update_banner_collapsed": "Updating patch bundles • %1$d out of %2$d",
    "bundle_update_banner_title": "Updating patch bundles",
    "bundle_update_progress": "%1$d/%2$d bundles processed",
    "original_revanced_manager_github": "Original ReVanced Manager GitHub",
    "selected_apps_count": "%d apps selected",
}

STRING_TAGS = {"string", "string-array", "plurals"}


@dataclass
class Change:
    path: str
    rule: str
    detail: str


@dataclass
class Finding:
    path: str | None
    line: int | None
    message: str
    reason: str


def log(message: str) -> None:
    print(f"[URV][resource-fixer] {message}", flush=True)


def rel(path: Path, repo: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo.resolve()))
    except ValueError:
        return str(path)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write_if_changed(path: Path, before: str, after: str, changes: list[Change], rule: str, detail: str, repo: Path, dry_run: bool) -> None:
    if before == after:
        return
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(after, encoding="utf-8")
    changes.append(Change(rel(path, repo), rule, detail))


def values_dirs(res_dir: Path) -> list[Path]:
    if not res_dir.exists():
        return []
    return sorted(p for p in res_dir.iterdir() if p.is_dir() and p.name.startswith("values"))


def parse_resource_names(xml_path: Path, findings: list[Finding], repo: Path) -> dict[str, set[str]]:
    names: dict[str, set[str]] = {tag: set() for tag in STRING_TAGS}
    try:
        root = ET.fromstring(read(xml_path))
    except Exception as exc:
        findings.append(Finding(rel(xml_path, repo), None, f"XML parse failed: {exc}", "fix malformed resource XML manually"))
        return names
    for child in root:
        tag = child.tag.split("}")[-1]
        if tag not in STRING_TAGS:
            continue
        name = child.attrib.get("name")
        if name:
            names[tag].add(name)
    return names


def collect_resource_names(res_dir: Path, findings: list[Finding], repo: Path) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    default: dict[str, set[str]] = {tag: set() for tag in STRING_TAGS}
    localized: dict[str, set[str]] = {tag: set() for tag in STRING_TAGS}
    for vdir in values_dirs(res_dir):
        target = default if vdir.name == "values" else localized
        for xml_path in sorted(vdir.glob("*.xml")):
            names = parse_resource_names(xml_path, findings, repo)
            for tag, items in names.items():
                target[tag].update(items)
    return default, localized


def append_default_strings(strings_xml: Path, defaults: dict[str, str], changes: list[Change], repo: Path, dry_run: bool) -> None:
    before = read(strings_xml) if strings_xml.exists() else "<resources>\n</resources>\n"
    text = before
    additions = []
    for name, value in sorted(defaults.items()):
        if f'name="{name}"' not in text and f"name='{name}'" not in text:
            additions.append(f'    <string name="{escape(name)}">{escape(value)}</string>')
    if additions:
        if "</resources>" not in text:
            raise SystemExit(f"default strings.xml has no closing </resources>: {strings_xml}")
        text = text.replace("</resources>", "\n".join(additions) + "\n</resources>", 1)
    write_if_changed(strings_xml, before, text, changes, "resource-default-strings", "add missing default string resources", repo, dry_run)


def synthesize_missing_string_defaults(default: dict[str, set[str]], localized: dict[str, set[str]], enabled: bool) -> dict[str, str]:
    result = dict(KNOWN_STRING_DEFAULTS)
    if not enabled:
        return result
    missing_strings = sorted(localized["string"] - default["string"])
    for name in missing_strings:
        result.setdefault(name, name.replace("_", " ").strip().capitalize() or name)
    return result


def report_missing_non_string_defaults(default: dict[str, set[str]], localized: dict[str, set[str]], findings: list[Finding]) -> None:
    for tag in ("plurals", "string-array"):
        for name in sorted(localized[tag] - default[tag]):
            findings.append(Finding(
                path=None,
                line=None,
                message=f"localized {tag} without default value: {name}",
                reason="report-only; synthesizing plurals/arrays requires semantic items and quantities",
            ))


def fix_resources(repo: Path, changes: list[Change], findings: list[Finding], synthesize: bool, dry_run: bool) -> None:
    res_dir = repo / "app/src/main/res"
    if not res_dir.exists():
        findings.append(Finding(rel(res_dir, repo), None, "Android app resources directory missing", "resource fixer skipped"))
        return
    default, localized = collect_resource_names(res_dir, findings, repo)
    defaults = synthesize_missing_string_defaults(default, localized, synthesize)
    strings_xml = res_dir / "values/strings.xml"
    append_default_strings(strings_xml, defaults, changes, repo, dry_run)
    report_missing_non_string_defaults(default, localized, findings)


def parse_log(log_path: Path | None, findings: list[Finding]) -> None:
    if log_path is None or not log_path.exists():
        return
    for i, line in enumerate(log_path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not any(token in line for token in RESOURCE_LOG_PATTERNS):
            continue
        file_match = re.search(r"file://([^:]+):(\d+):(\d+)", line)
        findings.append(Finding(
            path=file_match.group(1) if file_match else None,
            line=i,
            message=line.strip()[:900],
            reason="resource/AAPT diagnostic captured",
        ))


def write_report(path: Path | None, changes: list[Change], findings: list[Finding]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "changed": [asdict(change) for change in changes],
        "findings": [asdict(finding) for finding in findings],
        "changed_count": len(changes),
        "finding_count": len(findings),
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Fix safe Android resource issues and report AAPT diagnostics.")
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--log", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--synthesize-missing-strings", action="store_true", help="create placeholder defaults for unknown localized-only strings")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    if not repo.is_dir():
        raise SystemExit(f"repo does not exist: {repo}")

    changes: list[Change] = []
    findings: list[Finding] = []
    fix_resources(repo, changes, findings, args.synthesize_missing_strings, args.dry_run)
    parse_log(args.log, findings)
    write_report(args.report, changes, findings)

    for change in changes[:60]:
        log(f"{change.rule}: {change.path} :: {change.detail}")
    if findings:
        log(f"resource findings: {len(findings)}")
        for finding in findings[:60]:
            log(f"finding: {finding.path or '-'}:{finding.line or '-'} :: {finding.message}")
    if not changes and not findings:
        log("no changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
