# Pulp Migration Scanner - Usage Guide

## Quick Start

```bash
# Basic scan between two versions
pulp-scan 3.85.0 3.118.0

# Adjust confidence threshold (hide low-confidence findings)
pulp-scan 3.85.0 3.118.0 --min-confidence 0.7

# Scan additional repos
pulp-scan 3.85.0 3.118.0 --repo pulp/pulp_deb --repo pulp/pulp_ostree

# Use GitHub token for higher rate limits
export GITHUB_TOKEN=ghp_your_token_here
pulp-scan 3.85.0 3.118.0
```

## Understanding Confidence Levels

The tool assigns confidence scores to findings:

- **1.0 (High)**: Explicit migration commands or requirements
  - "Run `pulpcore-manager migrate`"
  - "Database migration required"

- **0.8 (Medium-High)**: Breaking changes and schema changes
  - "Breaking change"
  - "Schema migration"
  - "Backwards incompatible"

- **0.7 (Medium)**: Feature/API removals
  - "Removed endpoint"
  - "No longer supported"

- **0.5-0.6 (Low)**: Deprecations and informational
  - API deprecations (still work but will be removed later)
  - Schema additions (non-breaking)

## Interpreting Results

### Summary Section

```
⚠  2 likely migration issue(s) found:
  • Breaking Change: 3.100.0, 3.105.0
  • Removed Feature: 3.110.0
```

This tells you:
- **Action required**: Review these versions
- **What changed**: Type of issue
- **When**: Which versions introduced the change

### Detail Section

```
Version 3.100.0
----------------------------------------

  🔴 [pulp/pulpcore] Breaking Change (confidence: 80%)
  Context: ...removed deprecated /api/v3/orphans/ endpoint...
  URL: https://github.com/pulp/pulpcore/releases/tag/3.100.0
```

Indicators:
- 🔴 High confidence (≥80%)
- 🟡 Medium confidence (60-79%)
- 🔵 Low confidence (<60%)

## Common Scenarios

### Scenario 1: Planning an Upgrade

```bash
# Check if upgrade from 3.85.0 to 3.118.0 needs migrations
pulp-scan 3.85.0 3.118.0 --min-confidence 0.7
```

**Exit codes:**
- `0`: No high-confidence issues (safe to upgrade)
- `1`: Migration issues found (review required)

### Scenario 2: Finding Breaking Changes Only

```bash
# Hide deprecation warnings, show only breaking changes
pulp-scan 3.85.0 3.118.0 --min-confidence 0.7
```

### Scenario 3: Comprehensive Audit

```bash
# See everything, including low-confidence findings
pulp-scan 3.85.0 3.118.0 --min-confidence 0.0
```

### Scenario 4: Plugin-Specific Scan

```bash
# Check only pulp_rpm for changes
pulp-scan 3.20.0 3.30.0 --repo pulp/pulp_rpm --min-confidence 0.5
```

## What to Do With Results

### High Confidence (🔴 80%+)

**Action**: Must review before upgrading

1. Click the GitHub URL to read full release notes
2. Check if your code uses removed/changed APIs
3. Plan migration steps
4. Test upgrade in staging environment

### Medium Confidence (🟡 60-79%)

**Action**: Review recommended

1. Read the context provided
2. Determine if change affects your usage
3. Update code if necessary

### Low Confidence (🔵 <60%)

**Action**: Informational only

- Deprecations: Plan to update eventually
- Schema additions: Usually non-breaking

## Limitations

### False Positives

The tool uses keyword matching and may flag:
- Bug fixes mentioning migrations
- Test-related changes
- Documentation updates

Always check the full release notes (URL provided) to confirm.

### False Negatives

The tool may miss:
- Breaking changes described with uncommon wording
- Subtle API changes without explicit warnings
- Changes only documented elsewhere (not in GitHub releases)

### Rate Limiting

GitHub API limits:
- **Without token**: 60 requests/hour
- **With token**: 5000 requests/hour

The tool scans 5 repos by default, using 5 requests per run.

## Tips

1. **Use a token** for frequent scans:
   ```bash
   export GITHUB_TOKEN=ghp_xxxxx
   ```

2. **Start with high confidence** to reduce noise:
   ```bash
   pulp-scan 3.x.0 3.y.0 --min-confidence 0.8
   ```

3. **Scan incrementally** for large version jumps:
   ```bash
   pulp-scan 3.85.0 3.100.0
   pulp-scan 3.100.0 3.118.0
   ```

4. **Check plugin compatibility** separately:
   ```bash
   # Core first
   pulp-scan 3.85.0 3.118.0 --min-confidence 0.7
   
   # Then each plugin
   pulp-scan 3.20.0 3.30.0 --repo pulp/pulp_rpm --min-confidence 0.7
   ```

## Examples of Real Findings

### Example 1: Database Migration Required

```
🔴 [pulp/pulpcore] Migration Required (confidence: 100%)
Context: After upgrade, run: pulpcore-manager migrate
```

**Action**: Schedule downtime for migration

### Example 2: API Removal

```
🔴 [pulp/pulpcore] Removed Feature (confidence: 70%)
Context: Removed deprecated /api/v3/orphans/ endpoint
```

**Action**: Update client code to use new endpoint

### Example 3: Deprecation Warning

```
🔵 [pulp/pulpcore] Deprecated Feature/API (confidence: 50%)
Context: Deprecated RepositoryVersion.content_batch_qs
```

**Action**: Note for future refactoring (still works for now)
