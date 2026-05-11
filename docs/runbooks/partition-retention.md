# Partition Retention Runbook

## Overview

The `intelligence_db` uses PostgreSQL RANGE partitioning by month on three tables:
- `relation_evidence` (immutable evidence rows)
- `claims` (extracted claims)
- `events` (extracted events)

**Retention policy (D-004 decision): 24 months.**

Partitions older than 24 months are detached and dropped by the retention script.

## Partition Naming Convention

Each monthly partition follows the pattern: `{table}_{YYYY}_{MM}`

Examples:
- `relation_evidence_2024_01` (January 2024)
- `claims_2024_06` (June 2024)
- `events_2025_12` (December 2025)

## Retention Script

**Location:** `scripts/partition_retention.py`

### Dry Run (default)

List partitions that would be dropped without making any changes:

```bash
python scripts/partition_retention.py
```

### Execute

Actually detach and drop old partitions:

```bash
python scripts/partition_retention.py --execute
```

### Custom Retention Period

Override the default 24-month retention:

```bash
python scripts/partition_retention.py --retention-months 12 --execute
```

### Custom Database URL

```bash
python scripts/partition_retention.py \
  --database-url "postgresql+asyncpg://user:pass@host:5432/intelligence_db" \
  --execute
```

Or via environment variable:

```bash
export INTELLIGENCE_DB_URL="postgresql+asyncpg://user:pass@host:5432/intelligence_db"
python scripts/partition_retention.py --execute
```

## Monthly Cron Job Setup

### Crontab (Linux/macOS)

Run at 03:00 UTC on the 1st of each month:

```cron
0 3 1 * * cd /path/to/worldview && /path/to/python scripts/partition_retention.py --execute >> /var/log/partition_retention.log 2>&1
```

### Kubernetes CronJob

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: partition-retention
  namespace: worldview
spec:
  schedule: "0 3 1 * *"  # 1st of each month at 03:00 UTC
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: retention
              image: worldview/intelligence-migrations:latest
              command: ["python", "scripts/partition_retention.py", "--execute"]
              env:
                - name: INTELLIGENCE_DB_URL
                  valueFrom:
                    secretKeyRef:
                      name: intelligence-db-credentials
                      key: url
          restartPolicy: OnFailure
```

## What Happens to Dropped Partitions

1. **DETACH**: The partition is detached from the parent table. It becomes a standalone table that no longer receives queries via the parent. Ongoing queries on the parent table are not affected.

2. **DROP**: The detached standalone table is dropped with `CASCADE`. All data is permanently deleted.

If you need to archive data before dropping, modify the script to:
1. Export the partition to a Parquet file (via `COPY ... TO`)
2. Upload to S3/MinIO archival bucket
3. Then detach and drop

## In-Service Partition Management

The `MonthlyPartitionWorker` (Worker 13G) in `services/knowledge-graph/src/knowledge_graph/infrastructure/workers/partitions.py` also manages partitions at runtime:
- Creates current + next 2 months ahead of time
- Prunes partitions older than 24 months on each run

The standalone script serves as a safety net and operational tool for:
- Manual runs after extended downtime
- Verifying partition state (dry run)
- Custom retention overrides

## Composite PK Requirement

`relation_evidence` has a composite primary key: `(evidence_id, evidence_date)`.

PostgreSQL requires the partition key in the PK for RANGE-partitioned tables. This means:
- **All WHERE clauses** that look up specific evidence rows must include `evidence_date` for partition pruning.
- Lookups by `evidence_id` alone will scan all partitions (expensive).
- Use the `relation_id` or `doc_id` indexes for typical access patterns.
