#!/usr/bin/env python3
"""Scan Pulp releases for migration requirements between versions."""

import re
import sys
from typing import Dict, List, Tuple
from dataclasses import dataclass
from packaging import version

import click
import requests


PULP_REPOS = [
    "pulp/pulpcore",
    "pulp/pulp_rpm",
    "pulp/pulp_container",
    "pulp/pulp_ansible",
    "pulp/pulp_file",
]

MIGRATION_PATTERNS = [
    # High confidence - explicit migration commands
    (r"(?i)run.*pulpcore-manager\s+migrate", "Migration Required", 1.0),
    (r"(?i)database\s+migration\s+required", "Migration Required", 1.0),
    (r"(?i)requires?\s+(?:a\s+)?(?:database\s+)?migration", "Migration Required", 1.0),

    # Medium-high - schema changes
    (r"(?i)schema\s+(?:change|migration)", "Schema Change", 0.8),
    (r"(?i)database\s+schema", "Schema Change", 0.7),
    (r"(?i)added?\s+(?:database|db)\s+(?:field|column|table|index)", "Schema Addition", 0.6),

    # Medium - breaking changes and removals
    (r"(?i)####\s*Removals?\s*\n", "Removed Feature/API", 0.75),
    (r"(?i)breaking\s+change", "Breaking Change", 0.8),
    (r"(?i)removed\s+(?:feature|endpoint|api|field|parameter)", "Removed Feature", 0.7),
    (r"(?i)backwards?\s*incompatible", "Breaking Change", 0.8),
    (r"(?i)no\s+longer\s+support", "Breaking Change", 0.7),

    # Medium-low - deprecations (warnings, not blockers)
    (r"(?i)####\s*Deprecations?\s*\n", "Deprecated Feature/API", 0.5),
    (r"(?i)deprecat(?:ed|ion)", "Deprecation Warning", 0.4),
]

# Negative patterns - exclude these matches
EXCLUDE_PATTERNS = [
    r"(?i)fixed.*migration",  # Bug fixes for migrations
    r"(?i)migration.*(?:bug|fix|issue)",  # Migration bug fixes
    r"(?i)test.*migration",  # Test-related
    r"(?i)migration.*test",
]


@dataclass
class MigrationIssue:
    """Represents a migration issue found in release notes."""
    version: str
    repo: str
    issue_type: str
    context: str
    url: str
    confidence: float  # 0.0-1.0


def fetch_github_releases(repo: str, token: str = None) -> List[Dict]:
    """Fetch releases from GitHub API."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def parse_version(version_str: str) -> version.Version:
    """Parse version string, handling various formats."""
    # Strip 'v' prefix if present
    version_str = version_str.lstrip('v')
    try:
        return version.parse(version_str)
    except version.InvalidVersion:
        # Fallback for malformed versions
        return version.Version("0.0.0")


def scan_release_notes(releases: List[Dict], from_version: str, to_version: str, repo: str) -> List[MigrationIssue]:
    """Scan release notes for migration indicators."""
    issues = []

    from_ver = parse_version(from_version)
    to_ver = parse_version(to_version)

    for release in releases:
        rel_version = parse_version(release.get("tag_name", ""))

        # Only check releases between from and to (exclusive of from, inclusive of to)
        if rel_version <= from_ver or rel_version > to_ver:
            continue

        body = release.get("body", "")
        if not body:
            continue

        # Check each pattern
        for pattern, issue_type, confidence in MIGRATION_PATTERNS:
            matches = re.finditer(pattern, body, re.MULTILINE)
            for match in matches:
                # Extract context (line containing match)
                line_start = body.rfind('\n', 0, match.start()) + 1
                line_end = body.find('\n', match.end())
                if line_end == -1:
                    line_end = len(body)
                context_line = body[line_start:line_end].strip()

                # Check exclusion patterns
                excluded = False
                for excl_pattern in EXCLUDE_PATTERNS:
                    if re.search(excl_pattern, context_line):
                        excluded = True
                        break

                if excluded:
                    continue

                # Get wider context for display
                start = max(0, match.start() - 150)
                end = min(len(body), match.end() + 150)
                context = body[start:end].strip()
                if len(context) > 250:
                    context = context[:250] + "..."

                issues.append(MigrationIssue(
                    version=release["tag_name"],
                    repo=repo,
                    issue_type=issue_type,
                    context=context,
                    url=release["html_url"],
                    confidence=confidence
                ))

    return issues


def format_summary(issues: List[MigrationIssue]) -> str:
    """Format migration summary."""
    if not issues:
        return "✓ No migration issues detected"

    # Separate high confidence (>= 0.7) from low
    high_conf = [i for i in issues if i.confidence >= 0.7]
    low_conf = [i for i in issues if i.confidence < 0.7]

    lines = []

    if high_conf:
        lines.append(f"⚠  {len(high_conf)} likely migration issue(s) found:\n")
        by_type = {}
        for issue in high_conf:
            by_type.setdefault(issue.issue_type, []).append(issue)
        for issue_type, type_issues in sorted(by_type.items()):
            versions = sorted(set(i.version for i in type_issues), key=parse_version)
            lines.append(f"  • {issue_type}: {', '.join(versions)}")

    if low_conf:
        lines.append(f"\nℹ  {len(low_conf)} informational finding(s) (review recommended):\n")
        by_type = {}
        for issue in low_conf:
            by_type.setdefault(issue.issue_type, []).append(issue)
        for issue_type, type_issues in sorted(by_type.items()):
            versions = sorted(set(i.version for i in type_issues), key=parse_version)
            lines.append(f"  • {issue_type}: {', '.join(versions)}")

    return "\n".join(lines)


def format_details(issues: List[MigrationIssue]) -> str:
    """Format detailed migration breakdown."""
    if not issues:
        return ""

    lines = ["\n" + "="*80, "DETAILED BREAKDOWN", "="*80 + "\n"]

    # Group by version
    by_version = {}
    for issue in issues:
        by_version.setdefault(issue.version, []).append(issue)

    for ver in sorted(by_version.keys(), key=parse_version):
        lines.append(f"\nVersion {ver}")
        lines.append("-" * 40)

        # Sort by confidence (high to low)
        for issue in sorted(by_version[ver], key=lambda x: x.confidence, reverse=True):
            conf_indicator = "🔴" if issue.confidence >= 0.8 else "🟡" if issue.confidence >= 0.6 else "🔵"
            lines.append(f"\n  {conf_indicator} [{issue.repo}] {issue.issue_type} (confidence: {issue.confidence:.0%})")
            lines.append(f"  Context: {issue.context}")
            lines.append(f"  URL: {issue.url}")

    return "\n".join(lines)


@click.command()
@click.argument("from_version")
@click.argument("to_version")
@click.option("--token", envvar="GITHUB_TOKEN", help="GitHub API token (optional, for higher rate limits)")
@click.option("--repo", multiple=True, help="Additional Pulp repo to scan (format: owner/name)")
@click.option("--min-confidence", type=float, default=0.5, help="Minimum confidence threshold (0.0-1.0, default: 0.5)")
def cli(from_version: str, to_version: str, token: str, repo: Tuple[str], min_confidence: float):
    """
    Scan Pulp releases for migration requirements.

    FROM_VERSION: Starting version (e.g., 3.21.0)
    TO_VERSION: Target version (e.g., 3.28.0)

    Example:
        pulp-scan 3.85.0 3.118.0
        pulp-scan 3.85.0 3.118.0 --min-confidence 0.7
    """
    repos = list(PULP_REPOS)
    if repo:
        repos.extend(repo)

    click.echo(f"Scanning Pulp releases: {from_version} → {to_version}\n")

    all_issues = []

    for repo_name in repos:
        try:
            click.echo(f"Fetching releases from {repo_name}...", nl=False)
            releases = fetch_github_releases(repo_name, token)
            click.echo(f" ({len(releases)} releases)")

            issues = scan_release_notes(releases, from_version, to_version, repo_name)
            all_issues.extend(issues)

        except requests.RequestException as e:
            click.echo(f" ERROR: {e}", err=True)
            continue

    # Filter by confidence
    filtered_issues = [i for i in all_issues if i.confidence >= min_confidence]

    # Output
    click.echo("\n" + "="*80)
    click.echo(format_summary(filtered_issues))
    click.echo(format_details(filtered_issues))
    click.echo("\n" + "="*80)

    if filtered_issues != all_issues:
        filtered_count = len(all_issues) - len(filtered_issues)
        click.echo(f"\n({filtered_count} low-confidence finding(s) hidden, use --min-confidence to adjust)")

    # Exit 1 if high-confidence issues found
    high_conf_issues = [i for i in filtered_issues if i.confidence >= 0.7]
    sys.exit(1 if high_conf_issues else 0)


if __name__ == "__main__":
    cli()
