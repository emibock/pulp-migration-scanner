# Implemented Improvements

This document describes the enhancements made to the Pulp migration scanner.

## Summary

Created `pulp_scanner_v2.py` with significant improvements over the original keyword-based scanner:

1. ✅ **Parse CHANGES.md from repos** - Structured changelog parsing
2. ✅ **Add GitHub API pagination** - Fetch all releases, not just 100
3. ✅ **Parse migration files directly** - Git diff on migrations/ directory
4. ⏳ **LLM post-filter** - Not yet implemented (see Future Improvements)

## 1. CHANGES.md Parsing

**Why:** Pulp uses towncrier to generate structured CHANGES.md files with clear sections:
- Features
- Bugfixes
- **Removals** ← Critical for migration planning
- **Deprecations** ← Warnings
- Improved Documentation

**Implementation:**
- Fetch CHANGES.md from `https://raw.githubusercontent.com/{repo}/main/CHANGES.md`
- Parse markdown structure:
  - `## 3.115.0` = version header
  - `### REST API` = section header
  - `#### Removals` = subsection header
- Track yanked releases (`## YANKED 3.117.0`)

**Benefits:**
- More accurate than keyword matching on release notes
- Consistent format across all Pulp repos
- Contains all historical versions (not limited to 100)

## 2. GitHub API Pagination

**Original:** `GET /repos/{owner}/{repo}/releases?per_page=100` → 100 releases max

**Improved:** Follow `Link` header for pagination:
```python
while url:
    response = requests.get(url)
    results.extend(response.json())
    
    link_header = response.headers.get('Link', '')
    next_match = re.search(r'<([^>]+)>;\s*rel="next"', link_header)
    url = next_match.group(1) if next_match else None
```

**Benefits:**
- Can scan entire version history
- No arbitrary 100-release limit

## 3. Migration File Detection

**Implementation:**
```python
# Compare two tags via GitHub API
GET /repos/{owner}/{repo}/compare/{from_tag}...{to_tag}

# Filter for migration files
files = [f for f in data['files'] if 
         '/migrations/' in f['filename'] and 
         re.search(r'/migrations/\d{4}_\w+\.py$', f['filename'])]
```

**Example Output:**
```
[pulpcore] Checking migration files... 24 new migrations
  Migration files:
    - pulpcore/app/migrations/0152_alter_repositoryversion_content_ids.py
    - pulpcore/app/migrations/0153_taskschedule_pulp_domain.py
```

**Benefits:**
- **Definitive answer** on database migrations (not just keywords)
- Shows actual migration file names
- Django migration naming convention: `####_description.py`

## Severity Classification

V2 scanner assigns severity based on change type:

| Category | Severity | Exit Code Impact |
|----------|----------|------------------|
| Migration (explicit) | **Critical** | Exit 1 |
| Removal | **High** | Exit 1 |
| Breaking Change | **High** | Exit 1 |
| Migration (mentioned) | Medium | Exit 0 |
| Deprecation | Low | Exit 0 |

## Comparison: V1 vs V2

| Feature | V1 (Original) | V2 (Enhanced) |
|---------|---------------|---------------|
| Data source | GitHub releases | CHANGES.md + migration files |
| Detection method | Keyword patterns | Structured parsing + git diff |
| False positives | Medium-High | Low |
| Removals detection | Pattern match | Section-based (accurate) |
| Migration detection | Keywords | Actual migration files |
| Pagination | ✅ (100 max) | ✅ (unlimited) |
| Confidence scoring | ✅ | Replaced with severity |
| Output format | Confidence-based | Severity-based |

## False Positive Reduction

**V1 Issues:**
```
🟡 [pulp/pulpcore] Database Migration (confidence: 60%)
Context: Fixed post-migrate hooks to prevent failing...
```
^ This is a bug fix, not a migration requirement

**V2 Fix:**
- Parses section headers (`#### Bugfixes`)
- Skips "No significant changes"
- Uses git diff for definitive migration detection

## Example Output Comparison

### V1 Output
```
⚠ 8 potential migration issue(s) found:
  • Database Migration: 3.85.31, 3.105.20
  • Deprecation: 3.118.0
```

### V2 Output
```
🔴 CRITICAL: 6 finding(s)
🟠 HIGH: 8 finding(s)

  • Migration: 3.86.0, 3.103.4, 3.104.0
  • Removal: 3.86.0, 3.100.0, 3.115.0
  • Deprecation: 3.88.0, 3.118.0
```

## Performance

**API Calls:**
- V1: 5 calls (5 repos × 1 releases endpoint)
- V2: 10-15 calls (5 repos × CHANGES.md + compare endpoint)

**Rate Limits:**
- Without token: 60 req/hour (V2 might hit limit on large scans)
- With token: 5000 req/hour (no issues)

## Future Improvements

### 1. LLM Post-Filter (Not Implemented)

**Concept:**
```python
for finding in high_severity_findings:
    prompt = f"""
    Does this indicate a required migration action for upgrading?
    
    Context: {finding.description}
    
    Answer: YES / NO / MAYBE
    Reason: <one sentence>
    """
    
    verdict = call_claude_haiku(prompt)
    if verdict == "NO":
        finding.severity = "low"
```

**Benefits:**
- Further reduce false positives
- Natural language understanding of context

**Costs:**
- API calls to Claude (Haiku: ~$0.0001 per finding)
- Latency (100-300ms per finding)

**When to Add:**
- If false positives still too high
- Use `--llm-refine` flag for opt-in

### 2. Check Docs Site Directly

**Current:** Docs site is JS-rendered, can't scrape easily

**Options:**
- Playwright/Selenium (heavy dependency)
- Find static source (might exist in docs/ directory)
- Check if docs have JSON API

**When to Add:**
- If CHANGES.md doesn't have enough detail
- If docs have additional migration guides

### 3. Plugin Dependency Resolution

**Concept:**
- Check which plugin versions are compatible with core versions
- Warn about plugin upgrades needed

**Implementation:**
- Parse `setup.py` or `pyproject.toml` from plugin repos
- Check `pulpcore>=X.Y` constraints

**When to Add:**
- For comprehensive upgrade planning
- Multi-repo dependency analysis

### 4. Generate Upgrade Plan

**Concept:**
```
Upgrade Plan: 3.85.0 → 3.118.0

Step 1: Upgrade to 3.100.0
  - Run migrations: 0140-0145
  - Breaking change: /api/v3/orphans removed
  - Action: Update client code

Step 2: Upgrade to 3.115.0
  - Run migrations: 0146-0153
  - Removal: Django 4 support dropped
  - Action: Ensure Django 5+ installed

Step 3: Upgrade to 3.118.0
  - Run migrations: 0154-0160
  - Deprecation: RepositoryVersion.content_batch_qs
  - Action: Plan refactor for future version
```

**When to Add:**
- User feedback requests this
- Have enough data to order steps correctly

## Testing

Tested on:
- pulpcore: 3.85.0 → 3.118.0 (33 versions, 187 changelog entries, 24 migrations)
- Output: 17 findings (6 critical, 8 high, 1 medium, 2 low)

## Recommended Usage

```bash
# Daily: Quick check for critical issues
pulp-scan-v2 3.100.0 3.120.0 --min-severity high

# Planning upgrade: Comprehensive scan
pulp-scan-v2 3.85.0 3.118.0 --check-migrations

# CI/CD: Fast check without migration files
pulp-scan-v2 ${CURRENT} ${TARGET} --no-check-migrations --min-severity critical
```
