# Disaster Recovery & Backup

> **Goal**: Recover the full worldview platform from a total server loss in < 2 hours.
> **Backup frequency**: Database nightly, MinIO nightly, certs weekly.

---

## What to Back Up

| Data | Location | Backup Target | Frequency |
|------|----------|--------------|-----------|
| All Postgres DBs (9 databases) | `worldview_postgres_data` volume | `/opt/backups/` + offsite | Daily (3am) |
| MinIO objects (bronze/silver/gold) | `worldview_minio_data` volume | Backblaze B2 or S3 | Daily |
| Let's Encrypt certs | `traefik_letsencrypt` volume | `env/prod/certs-backup.tar` | Weekly |
| Grafana dashboards | `worldview_grafana_data` volume | Git in worldview-gitops | After changes |
| Production env files | `worldview-gitops/env/prod/` | Already in Git (private) | On change |

---

## Database Backup

### Manual backup

```bash
docker exec worldview-postgres-1 pg_dumpall -U postgres \
  | gzip > /opt/backups/worldview-$(date +%Y%m%d-%H%M).sql.gz
```

### Automated daily backup (crontab)

```cron
# Nightly DB backup at 3:00 AM
0 3 * * * docker exec worldview-postgres-1 pg_dumpall -U postgres | gzip > /opt/backups/worldview-$(date +\%Y\%m\%d).sql.gz

# Rotate — keep 7 days locally
15 3 * * * find /opt/backups -name "worldview-*.sql.gz" -mtime +7 -delete
```

### Verify backup

```bash
# Check file exists and is non-empty:
ls -lh /opt/backups/worldview-*.sql.gz | tail -5

# Test restore to a temporary DB (non-destructive):
docker exec -i worldview-postgres-1 psql -U postgres -d postgres \
  <<< "CREATE DATABASE worldview_restore_test;"
zcat /opt/backups/worldview-latest.sql.gz | \
  docker exec -i worldview-postgres-1 psql -U postgres
```

### Restore from backup

```bash
# DESTRUCTIVE — drops and recreates all databases
docker compose -f infra/compose/docker-compose.yml \
               -f infra/compose/docker-compose.prod.yml \
               --profile infra stop

# Restore data:
docker exec -i worldview-postgres-1 psql -U postgres \
  <<< "$(zcat /opt/backups/worldview-20260503.sql.gz)"

# Restart:
make prod
```

---

## MinIO Object Storage Backup

MinIO stores article content (bronze/silver), extracted entities (gold), feedback screenshots,
and ML model artifacts. Back it up to Backblaze B2 or another S3-compatible target.

### Setup mc (MinIO client) on backup server

```bash
wget https://dl.min.io/client/mc/release/linux-amd64/mc -O /usr/local/bin/mc
chmod +x /usr/local/bin/mc
mc alias set prod-minio http://localhost:7480 minioadmin <MINIO_SECRET_KEY>
mc alias set b2 https://s3.us-west-004.backblazeb2.com <B2_KEY_ID> <B2_APP_KEY>
```

### Mirror buckets to Backblaze (add to crontab)

```cron
# Nightly MinIO mirror at 3:30 AM
30 3 * * * /usr/local/bin/mc mirror --overwrite prod-minio/worldview-bronze b2/worldview-prod-bronze
35 3 * * * /usr/local/bin/mc mirror --overwrite prod-minio/worldview-silver b2/worldview-prod-silver
40 3 * * * /usr/local/bin/mc mirror --overwrite prod-minio/worldview-gold b2/worldview-prod-gold
```

---

## Let's Encrypt Certificate Backup

**WARNING**: Let's Encrypt rate-limits certificate issuance to **5 duplicate certificates
per domain per week**. If you exceed this, you must wait up to 7 days or switch to the
staging server. Back up certs before any risky operations.

### Backup certificates

```bash
docker run --rm \
  -v traefik_letsencrypt:/data \
  busybox tar cvf - /data \
  > /opt/worldview/worldview-gitops/env/prod/letsencrypt-backup-$(date +%Y%m%d).tar
# Commit to worldview-gitops
```

### Restore certificates

```bash
# Stop Traefik first:
docker stop worldview-traefik-1

# Restore:
docker run --rm \
  -v traefik_letsencrypt:/data \
  busybox tar xvf - \
  < /opt/worldview/worldview-gitops/env/prod/letsencrypt-backup-20260503.tar

# Restart:
docker start worldview-traefik-1
```

### If rate-limited (staging server)

Edit `docker-compose.prod.yml` Traefik command, replace:
```
- --certificatesresolvers.le.acme.storage=/letsencrypt/acme.json
```
Add staging CA:
```
- --certificatesresolvers.le.acme.caServer=https://acme-staging-v02.api.letsencrypt.org/directory
```
Once you confirm cert acquisition works, switch back to the production CA.

---

## Full Server Recovery (Total Loss)

Steps to recover from a complete server loss (new Hetzner instance):

1. **Provision new server** — follow `hetzner-setup.md` (bootstrap, DNS update, deploy key)

2. **Clone repos**:
   ```bash
   cd /opt/worldview
   git clone git@github.com:your-org/worldview.git worldview
   git clone git@github.com:your-org/worldview-gitops.git worldview-gitops
   ```

3. **Copy production env files**:
   ```bash
   cd worldview-gitops && ./scripts/setup-prod.sh
   ```

4. **Restore database** from most recent backup:
   ```bash
   make prod   # start stack (empty databases)
   # Wait for postgres to be healthy, then restore:
   zcat /opt/backups/worldview-latest.sql.gz | \
     docker exec -i worldview-postgres-1 psql -U postgres
   ```

5. **Restore MinIO** (if needed):
   ```bash
   mc mirror b2/worldview-prod-bronze prod-minio/worldview-bronze
   mc mirror b2/worldview-prod-silver prod-minio/worldview-silver
   mc mirror b2/worldview-prod-gold prod-minio/worldview-gold
   ```

6. **Restore Let's Encrypt certs** (if backup is < 60 days old; otherwise let Traefik re-issue):
   ```bash
   # Follow certificate restore steps above
   ```

7. **Update DNS** to point to new server IP.

8. **Run health checks**:
   ```bash
   DOMAIN=worldview.example.com ./scripts/verify-prod-health.sh
   ```

**Target RTO**: < 2 hours (depends on DB restore size and Let's Encrypt cert issuance).
**Target RPO**: < 24 hours (nightly backup).
