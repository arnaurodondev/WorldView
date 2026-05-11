# Runbook: Sentry Alert Rules

> **Owner**: On-call engineer
> **Last updated**: 2026-05-04 (PLAN-0065 T-E-04)
> **Related**: `docs/runbooks/error-observability.md`, PRD-0034 §3 FR-T3-1

---

## Overview

Four Sentry issue-alert rules are configured to email `arnaurodondev@gmail.com`
when significant error events occur. These rules complement the Grafana
error-observability dashboard by providing push notification without requiring
active monitoring of dashboards.

---

## Alert Rules

### Rule 1 — New Issue Created

- **Name**: `New issue — email arnaurodondev`
- **Trigger**: A new issue is created (fires once per new fingerprint)
- **Action**: Send email to `arnaurodondev@gmail.com`
- **Environments**: All (including prod and staging)
- **Frequency**: Maximum 1 email per issue (Sentry deduplicates by fingerprint)
- **Why**: First time a new exception class appears, you want to know immediately.
  The `before_send` rate-limiter means Sentry only sees ≤10 events/fingerprint/hour
  so this alert will not spam for a repeating known error.

### Rule 2 — Issue Regression

- **Name**: `Regression — email arnaurodondev`
- **Trigger**: An issue that has been resolved is seen again
- **Action**: Send email to `arnaurodondev@gmail.com`
- **Why**: A previously-fixed bug reappearing is high-signal and warrants immediate attention.

### Rule 3 — Error Spike

- **Name**: `Error spike — email arnaurodondev`
- **Trigger**: An issue occurs more than 50 times in 1 hour
- **Action**: Send email to `arnaurodondev@gmail.com`
- **Why**: Complements Rule 1 for cases where a known error suddenly spikes
  (e.g. a config change makes an existing error much more frequent).

### Rule 4 — Monthly Quota 80%

- **Name**: `Sentry quota 80%`
- **Trigger**: Monthly event usage > 80%
- **Location**: Organisation settings → Subscription → Usage alerts (not in project alert rules)
- **Action**: Email `arnaurodondev@gmail.com`
- **Why**: Worldview is on the free tier (5,000 events/month). At 80% usage,
  review whether the rate-limiter should be tightened or a paid plan is needed.

---

## How to Configure the Rules (UI Path)

1. Log into Sentry (sentry.io)
2. Navigate to: **Project** → **Alerts** → **Issue Alerts** → **Create Alert Rule**
3. Configure each rule as described above
4. Confirm each rule shows **"Active"** status in the Alerts list

For Rule 4 (quota): **Organisation settings** → **Subscription** → **Usage Alerts**

---

## Updating the Alert Email Address

The recipient email is configured in Sentry's UI (not in code or env vars).
To change it:

1. Open Sentry → Project → Alerts → Issue Alerts
2. Edit each of the 4 rules and update the email recipient
3. No code change or redeployment needed

**Future**: When a company ops email is created (e.g. `ops@meshx.io`),
update all 4 rules to use it instead of the personal dev address.

---

## Escalation Ladder

| Event | First response | If not resolved in 30 min |
|-------|---------------|--------------------------|
| Rule 1 (New Issue) | Investigate root cause in Sentry + Grafana | Check if service restart clears the issue; escalate if data corruption is suspected |
| Rule 2 (Regression) | Check recent deployments — roll back the last deploy | File a hotfix ticket; apply `/fix-bug` if root cause is clear |
| Rule 3 (Error Spike) | Identify the repeating exception; check if a config change caused it | Consider increasing `SENTRY_FINGERPRINT_RATE_LIMIT` temporarily to preserve more events in Sentry for debugging |
| Rule 4 (80% quota) | Review Sentry issues list for noisy exceptions; tighten rate-limit if needed | Consider upgrading to a paid Sentry plan if 5K/month is consistently insufficient |

---

## Notes

- **Free tier limit**: Sentry free tier supports 1 email recipient per rule. If you need
  multiple recipients, each rule must be duplicated (or upgrade to a paid plan with team channels).
- **WhatsApp / Slack**: Not configured for MVP. Sentry free tier supports email and limited Slack.
  A Slack ops channel can be added in the future via Sentry → Project → Alerts → integrations.
- **No hardcoded emails in code**: Alert destinations are configured only in Sentry UI.
  There are no email addresses hardcoded in the codebase for this purpose.
