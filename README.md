# Pulp Migration Scanner

Detect migration requirements when upgrading Pulp versions. Two scanners available:

## V2 Scanner (Recommended)

Enhanced scanner that parses structured CHANGES.md changelogs and checks migration files.

**Advantages:**
- Parses structured CHANGES.md from each repo
- Checks actual migration files added between versions (via git compare)
- Lower false positive rate
- Better categorization (removals, deprecations, migrations, breaking changes)
- Severity levels (critical, high, medium, low)

**Usage:**
```bash
# Basic scan
pulp-scan-v2 3.85.0 3.118.0

# Check migration files too (git diff)
pulp-scan-v2 3.85.0 3.118.0 --check-migrations

# Filter by severity
pulp-scan-v2 3.85.0 3.118.0 --min-severity high

# With GitHub token (for higher API rate limits)
export GITHUB_TOKEN=ghp_xxxxx
pulp-scan-v2 3.85.0 3.118.0
```

## V1 Scanner (Original)

Scans GitHub release notes with keyword matching.

**Usage:**
```bash
# Basic scan
pulp-scan 3.85.0 3.118.0

# Adjust confidence threshold
pulp-scan 3.85.0 3.118.0 --min-confidence 0.7
```

## Installation

```bash
cd pulp-migration-scanner

# Install with uv (recommended)
uv pip install .

# Or with pip
pip install .

# Or run directly without installing
pip install requests click packaging
python pulp_scanner_v2.py 3.85.0 3.118.0
```

## What V2 Scans

**Data Sources:**
- CHANGES.md from each repo (structured changelog)
- Migration files via git compare (optional with `--check-migrations`)

**Default Repositories:**
- pulp/pulpcore
- pulp/pulp_rpm
- pulp/pulp_container
- pulp/pulp_ansible
- pulp/pulp_file

**Detection Categories:**
- **Removals**: Removed features, APIs, endpoints (severity: high)
- **Breaking Changes**: Incompatible changes (severity: high)
- **Migrations**: Database migrations required (severity: critical)
- **Deprecations**: Features marked for future removal (severity: low)

## Output Example

```
Scanning Pulp: 3.85.0 → 3.118.0

[pulpcore] Fetching CHANGES.md... 187 relevant entries
[pulpcore] Checking migration files... 24 new migrations

================================================================================
🔴 CRITICAL: 6 finding(s)
🟠 HIGH: 8 finding(s)

  • Migration: 3.86.0, 3.103.4, 3.104.0
  • Removal: 3.86.0, 3.100.0, 3.115.0

================================================================================
DETAILED BREAKDOWN
================================================================================

📦 Version 3.115.0
----------------------------------------

🟠 [pulpcore] Removal (high)
   Plugin API - Removals: Made `content_ids` cache required with forceful 
   migration and removed the `/pulp/api/v3/datarepair/7465/` endpoint.
   https://github.com/pulp/pulpcore/releases/tag/3.115.0

🔴 [pulpcore] Migration (critical)
   Database migrations detected
   Migration files:
     - pulpcore/app/migrations/0152_alter_repositoryversion_content_ids.py
     - pulpcore/app/migrations/0153_taskschedule_pulp_domain.py
```

## Exit Codes

- `0`: No critical/high severity issues
- `1`: Migration issues found

## Options

### V2 Scanner

```
pulp-scan-v2 FROM_VERSION TO_VERSION [OPTIONS]

Options:
  --token TEXT                    GitHub API token (from GITHUB_TOKEN env)
  --repo TEXT                     Additional repo (name:owner/repo format)
  --check-migrations / --no-check-migrations  
                                  Check migration files via git diff (default: yes)
  --min-severity [low|medium|high|critical]
                                  Minimum severity to report (default: low)
```

### V1 Scanner

```
pulp-scan FROM_VERSION TO_VERSION [OPTIONS]

Options:
  --token TEXT                    GitHub API token
  --repo TEXT                     Additional repo (owner/name format)
  --min-confidence FLOAT          Confidence threshold 0.0-1.0 (default: 0.5)
```

## Limitations

**Both Versions:**
- Requires GitHub API access (rate limited without token)
- Only scans last 100 releases per repo (unless version found earlier)

**V2 Specific:**
- CHANGES.md format specific to Pulp (uses towncrier)
- Migration file detection shows "new files" but not details of what changed

**V1 Specific:**
- Keyword-based (may have false positives/negatives)
- Less structured output

## Tips

1. **Use GitHub token** to avoid rate limits:
   ```bash
   export GITHUB_TOKEN=ghp_xxxxx
   ```

2. **Start with high severity** to see critical issues:
   ```bash
   pulp-scan-v2 3.85.0 3.118.0 --min-severity high
   ```

3. **Disable migration checks** for faster scans:
   ```bash
   pulp-scan-v2 3.85.0 3.118.0 --no-check-migrations
   ```

4. **Scan incrementally** for large version jumps:
   ```bash
   pulp-scan-v2 3.85.0 3.100.0
   pulp-scan-v2 3.100.0 3.118.0
   ```

## Files

- `pulp_scanner_v2.py` - Enhanced scanner (recommended)
- `pulp_migration_scanner.py` - Original keyword-based scanner
- `USAGE.md` - Detailed usage guide for V1 scanner
- `pyproject.toml` - Package configuration

## Development

```bash
# Test V2 scanner
python pulp_scanner_v2.py 3.85.0 3.118.0

# Test V1 scanner
python pulp_migration_scanner.py 3.85.0 3.118.0
```
