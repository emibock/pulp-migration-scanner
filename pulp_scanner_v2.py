#!/usr/bin/env python3
"""Enhanced Pulp migration scanner - parses CHANGES.md and checks migration files."""

import re
import sys
import os
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, field
from packaging import version
from collections import defaultdict

import click
import requests


PULP_REPOS = {
    "pulpcore": "pulp/pulpcore",
    "pulp_rpm": "pulp/pulp_rpm",
    "pulp_container": "pulp/pulp_container",
    "pulp_ansible": "pulp/pulp_ansible",
    "pulp_file": "pulp/pulp_file",
}

# Cache configuration
CACHE_DIR = Path.home() / ".cache" / "pulp-migration-scanner"
CACHE_TTL = 24 * 60 * 60  # 24 hours in seconds


@dataclass
class MigrationFinding:
    """Migration requirement found in changelog or code."""
    version: str
    repo: str
    category: str  # migration, removal, deprecation, breaking_change
    severity: str  # critical, high, medium, low
    description: str
    source: str  # changelog, migration_file, release_notes
    url: Optional[str] = None
    migration_files: List[str] = field(default_factory=list)


def parse_version(version_str: str) -> version.Version:
    """Parse version string."""
    version_str = version_str.lstrip('v')
    try:
        return version.parse(version_str)
    except version.InvalidVersion:
        return version.Version("0.0.0")


def fetch_paginated(url: str, token: Optional[str] = None) -> List[Dict]:
    """Fetch all pages from GitHub API."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    results = []
    while url:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        results.extend(response.json())

        # Get next page URL from Link header
        link_header = response.headers.get('Link', '')
        next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
        url = next_match.group(1) if next_match else None

    return results


def get_cache_path(repo: str) -> Path:
    """Get cache file path for a repository."""
    # Use repo path as filename (replace / with -)
    cache_name = repo.replace("/", "-") + "-CHANGES.md"
    return CACHE_DIR / cache_name


def is_cache_valid(cache_path: Path) -> bool:
    """Check if cache file exists and is not expired."""
    if not cache_path.exists():
        return False

    # Check age
    age = time.time() - cache_path.stat().st_mtime
    return age < CACHE_TTL


def read_cache(cache_path: Path) -> str:
    """Read content from cache file."""
    return cache_path.read_text(encoding='utf-8')


def write_cache(cache_path: Path, content: str):
    """Write content to cache file."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(content, encoding='utf-8')


def clear_cache():
    """Remove all cached files."""
    if CACHE_DIR.exists():
        import shutil
        shutil.rmtree(CACHE_DIR)
        click.echo(f"Cache cleared: {CACHE_DIR}")
    else:
        click.echo("Cache directory does not exist")


def fetch_changelog(repo: str, token: Optional[str] = None, use_cache: bool = True) -> str:
    """Fetch CHANGES.md from repository with caching."""
    cache_path = get_cache_path(repo)

    # Try cache first
    if use_cache and is_cache_valid(cache_path):
        return read_cache(cache_path)

    # Fetch from network
    url = f"https://raw.githubusercontent.com/{repo}/main/CHANGES.md"
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code == 404:
        # Try alternate names
        for name in ["CHANGELOG.md", "HISTORY.rst", "CHANGES.rst"]:
            url = f"https://raw.githubusercontent.com/{repo}/main/{name}"
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                break

    response.raise_for_status()
    content = response.text

    # Cache the result
    if use_cache:
        write_cache(cache_path, content)

    return content


def parse_changelog_md(content: str, from_ver: version.Version, to_ver: version.Version) -> List[Dict]:
    """Parse markdown changelog between versions."""
    entries = []
    current_version = None
    current_section = None
    current_subsection = None
    current_content = []
    current_yanked = False

    for line in content.split('\n'):
        # Version header: ## 3.118.0 (2026-09-15) {: #3.118.0 }
        version_match = re.match(r'^##\s+(?:YANKED\s+)?([0-9]+\.[0-9]+\.[0-9]+)', line)
        if version_match:
            # Save previous entry
            if current_version and current_subsection and current_content:
                ver = parse_version(current_version)
                if from_ver < ver <= to_ver:
                    entries.append({
                        'version': current_version,
                        'section': current_section,
                        'subsection': current_subsection,
                        'content': '\n'.join(current_content).strip(),
                        'yanked': current_yanked
                    })

            current_version = version_match.group(1)
            current_yanked = 'YANKED' in line
            current_section = None
            current_subsection = None
            current_content = []
            continue

        if not current_version:
            continue

        # Section header: ### REST API {: #3.118.0-rest-api }
        section_match = re.match(r'^###\s+([^{]+)', line)
        if section_match:
            # Save previous subsection before changing section
            if current_content and current_subsection:
                ver = parse_version(current_version)
                if from_ver < ver <= to_ver:
                    entries.append({
                        'version': current_version,
                        'section': current_section,
                        'subsection': current_subsection,
                        'content': '\n'.join(current_content).strip(),
                        'yanked': current_yanked
                    })
            current_section = section_match.group(1).strip()
            current_subsection = None
            current_content = []
            continue

        # Subsection: #### Deprecations {: #3.118.0-plugin-api-deprecation }
        subsection_match = re.match(r'^####\s+([^{]+)', line)
        if subsection_match:
            if current_content and current_subsection:
                ver = parse_version(current_version)
                if from_ver < ver <= to_ver:
                    entries.append({
                        'version': current_version,
                        'section': current_section,
                        'subsection': current_subsection,
                        'content': '\n'.join(current_content).strip(),
                        'yanked': current_yanked
                    })
            current_subsection = subsection_match.group(1).strip()
            current_content = []
            continue

        # Collect content
        if current_subsection and line.strip():
            current_content.append(line)

    # Save final entry
    if current_version and current_subsection and current_content:
        ver = parse_version(current_version)
        if from_ver < ver <= to_ver:
            entries.append({
                'version': current_version,
                'section': current_section,
                'subsection': current_subsection,
                'content': '\n'.join(current_content).strip(),
                'yanked': current_yanked
            })

    return entries


def fetch_migration_files_between_tags(repo: str, from_tag: str, to_tag: str, token: Optional[str] = None) -> Set[str]:
    """Fetch list of migration files added between two git tags."""
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    # Get comparison between tags
    url = f"https://api.github.com/repos/{repo}/compare/{from_tag}...{to_tag}"
    response = requests.get(url, headers=headers, timeout=30)

    if response.status_code == 404:
        return set()

    response.raise_for_status()
    data = response.json()

    migration_files = set()
    for file in data.get('files', []):
        filename = file['filename']
        # Check for migration files
        if '/migrations/' in filename and filename.endswith('.py'):
            if re.search(r'/migrations/\d{4}_\w+\.py$', filename):
                migration_files.add(filename)

    return migration_files


def analyze_changelog_entry(entry: Dict) -> Optional[MigrationFinding]:
    """Analyze a changelog entry and determine severity."""
    subsection = entry['subsection'].lower()
    content = entry['content']
    version = entry['version']
    section = entry['section']
    yanked = entry.get('yanked', False)

    # Skip "No significant changes" entries
    if 'no significant changes' in content.lower():
        return None

    # Map subsections to categories and severities
    if 'removal' in subsection:
        severity = 'critical' if yanked else 'high'
        return MigrationFinding(
            version=version,
            repo='',
            category='removal',
            severity=severity,
            description=f"{section} - {entry['subsection']}: {content[:300]}",
            source='changelog'
        )

    if 'breaking' in subsection or 'incompatible' in subsection:
        return MigrationFinding(
            version=version,
            repo='',
            category='breaking_change',
            severity='high',
            description=f"{section} - {entry['subsection']}: {content[:300]}",
            source='changelog'
        )

    if 'deprecat' in subsection:  # Matches deprecation/deprecations
        return MigrationFinding(
            version=version,
            repo='',
            category='deprecation',
            severity='low',
            description=f"{section} - {entry['subsection']}: {content[:300]}",
            source='changelog'
        )

    # Check content for explicit migration requirements
    content_lower = content.lower()
    if 'migration' in content_lower or 'migrate' in content_lower:
        # High severity if it says "run migration" or "requires migration"
        if any(phrase in content_lower for phrase in ['run', 'require', 'must', 'forceful migration']):
            return MigrationFinding(
                version=version,
                repo='',
                category='migration',
                severity='critical',
                description=f"{section} - {content[:300]}",
                source='changelog'
            )
        # Medium if just mentions migration in bugfixes
        elif 'bugfix' not in subsection.lower():
            return MigrationFinding(
                version=version,
                repo='',
                category='migration',
                severity='medium',
                description=f"{section} - {content[:300]}",
                source='changelog'
            )

    return None


@click.command()
@click.argument("from_version", required=False)
@click.argument("to_version", required=False)
@click.option("--token", envvar="GITHUB_TOKEN", help="GitHub API token")
@click.option("--repo", multiple=True, help="Additional repo (name:owner/repo)")
@click.option("--check-migrations/--no-check-migrations", default=True, help="Check migration files via git diff")
@click.option("--min-severity", type=click.Choice(['low', 'medium', 'high', 'critical']), default='low', help="Minimum severity to report")
@click.option("--no-cache", is_flag=True, help="Bypass cache and fetch fresh data")
@click.option("--clear-cache", "clear_cache_opt", is_flag=True, help="Clear cache and exit")
def cli(from_version: str, to_version: str, token: str, repo: Tuple[str], check_migrations: bool, min_severity: str, no_cache: bool, clear_cache_opt: bool):
    """
    Enhanced Pulp migration scanner.

    Parses CHANGES.md and optionally checks migration files between versions.

    Example:
        pulp-scan-v2 3.85.0 3.118.0
        pulp-scan-v2 3.85.0 3.118.0 --min-severity high
        pulp-scan-v2 3.85.0 3.118.0 --no-cache
        pulp-scan-v2 --clear-cache
    """
    # Handle cache clearing
    if clear_cache_opt:
        clear_cache()
        return

    # Require version arguments for normal operation
    if not from_version or not to_version:
        raise click.UsageError("FROM_VERSION and TO_VERSION are required (unless using --clear-cache)")

    use_cache = not no_cache
    repos = dict(PULP_REPOS)
    for r in repo:
        if ':' in r:
            name, path = r.split(':', 1)
            repos[name] = path

    from_ver = parse_version(from_version)
    to_ver = parse_version(to_version)

    click.echo(f"Scanning Pulp: {from_version} → {to_version}\n")
    cache_status = "cache disabled" if no_cache else f"cache: {CACHE_DIR}"
    click.echo(f"Data sources: CHANGES.md{' + migration files' if check_migrations else ''}")
    click.echo(f"Cache: {cache_status}\n")

    all_findings = []
    severity_order = {'low': 0, 'medium': 1, 'high': 2, 'critical': 3}
    min_sev_level = severity_order[min_severity]

    for repo_name, repo_path in repos.items():
        try:
            cache_hit = use_cache and is_cache_valid(get_cache_path(repo_path))
            status = "(cached)" if cache_hit else "(fetching)"
            click.echo(f"[{repo_name}] CHANGES.md {status}...", nl=False)
            changelog = fetch_changelog(repo_path, token, use_cache)
            entries = parse_changelog_md(changelog, from_ver, to_ver)
            click.echo(f" {len(entries)} relevant entries")

            # Analyze each entry
            for entry in entries:
                finding = analyze_changelog_entry(entry)
                if finding:
                    finding.repo = repo_name
                    finding.url = f"https://github.com/{repo_path}/releases/tag/{entry['version']}"
                    all_findings.append(finding)

            # Check for migration files if requested
            if check_migrations:
                click.echo(f"[{repo_name}] Checking migration files...", nl=False)
                try:
                    migration_files = fetch_migration_files_between_tags(
                        repo_path, from_version, to_version, token
                    )
                    click.echo(f" {len(migration_files)} new migrations")

                    if migration_files:
                        # Group by likely version (this is approximate)
                        all_findings.append(MigrationFinding(
                            version=to_version,
                            repo=repo_name,
                            category='migration',
                            severity='critical',
                            description=f"Database migrations detected",
                            source='migration_file',
                            migration_files=list(migration_files)
                        ))
                except Exception as e:
                    click.echo(f" ERROR: {e}")

        except requests.RequestException as e:
            click.echo(f" ERROR: {e}", err=True)
            continue

    # Filter by severity
    findings = [
        f for f in all_findings
        if severity_order[f.severity] >= min_sev_level
    ]

    # Display results
    click.echo("\n" + "="*80)
    display_summary(findings)
    display_details(findings)
    click.echo("="*80)

    # Exit code based on critical/high findings
    critical_or_high = any(f.severity in ['critical', 'high'] for f in findings)
    sys.exit(1 if critical_or_high else 0)


def display_summary(findings: List[MigrationFinding]):
    """Display summary of findings."""
    if not findings:
        click.echo("✓ No migration issues detected")
        return

    by_severity = defaultdict(list)
    for f in findings:
        by_severity[f.severity].append(f)

    for sev in ['critical', 'high', 'medium', 'low']:
        if sev in by_severity:
            count = len(by_severity[sev])
            icon = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🔵'}[sev]
            click.echo(f"{icon} {sev.upper()}: {count} finding(s)")

    click.echo()

    # Group by category
    by_category = defaultdict(list)
    for f in findings:
        by_category[f.category].append(f)

    for cat, items in sorted(by_category.items()):
        versions = sorted(set(f.version for f in items), key=parse_version)
        click.echo(f"  • {cat.replace('_', ' ').title()}: {', '.join(versions)}")


def display_details(findings: List[MigrationFinding]):
    """Display detailed findings."""
    if not findings:
        return

    click.echo("\n" + "="*80)
    click.echo("DETAILED BREAKDOWN")
    click.echo("="*80)

    # Group by version
    by_version = defaultdict(list)
    for f in findings:
        by_version[f.version].append(f)

    for ver in sorted(by_version.keys(), key=parse_version):
        click.echo(f"\n📦 Version {ver}")
        click.echo("-" * 40)

        for finding in sorted(by_version[ver], key=lambda x: {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}[x.severity]):
            icon = {'critical': '🔴', 'high': '🟠', 'medium': '🟡', 'low': '🔵'}[finding.severity]
            click.echo(f"\n{icon} [{finding.repo}] {finding.category.replace('_', ' ').title()} ({finding.severity})")
            click.echo(f"   {finding.description}")

            if finding.migration_files:
                click.echo(f"   Migration files:")
                for mf in sorted(finding.migration_files)[:5]:
                    click.echo(f"     - {mf}")
                if len(finding.migration_files) > 5:
                    click.echo(f"     ... and {len(finding.migration_files) - 5} more")

            if finding.url:
                click.echo(f"   {finding.url}")


if __name__ == "__main__":
    cli()
