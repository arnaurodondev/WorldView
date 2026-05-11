# Alert System Enhancement Strategy

> **Status (2026-05-02): PARTIAL — superseded by PRD-0034 §13 for MVP scope.**
>
> Only the **LLM-generated alert explanation field** from §3.1 is accepted into MVP launch (PRD-0034 W10). The custom rule builder (§3.2), action recommendations (§3.4), one-click broker actions, mobile push, and email digest scheduling are **deferred to Phase-2 post-launch**, possibly indefinitely. Reasoning:
> - Builds rule plumbing on top of an empty signal pipeline (`relation_evidence` = 0 rows, `article_impact_windows` = 0 rows as of 2026-05-02).
> - Custom rule adoption realistically tracks 5–10% in early-stage products, not the 60% claimed here.
> - One-click broker actions presuppose SnapTrade integration (PRD-0022) which is blocked.
> - Phase-1 4-week budget = entire MVP launch budget; opportunity cost is catastrophic.
>
> This document is **kept on file**, not deleted, because the Phase-2 design thinking is still useful when alerts are revisited after MVP traction is established. Do not implement from this doc directly — read PRD-0034 first.

## Executive Summary

**Market Relevance**: Financial alerts are CRITICAL revenue drivers for market intelligence platforms. Users demand:
- **Real-time, contextual notifications** (not just raw data)
- **AI-generated explanations** (why this matters?)
- **Custom, flexible rules** (I define what I care about)
- **Action enablement** (what do I do now?)

This document proposes a **Phase 1 enhancement** roadmap focusing on LLM-powered alert explanations, custom rule builder, and actionable recommendations.

---

## 1. Market Analysis — Why Alerts Matter

### 1.1 Current Market Landscape

**Platforms Winning with Alerts:**

| Platform | Alert Model | User Engagement | Revenue Model |
|----------|------------|-----------------|---------------|
| **TradingView** | Multi-signal + custom screeners | ~100M users; alerts a primary feature | Subscription ($15-60/mo) |
| **Bloomberg Terminal** | Enterprise alerts (news, price, fundamental) | Institutional traders | $24K/year |
| **Seeking Alpha** | Editorial + AI sentiment + price | 20M+ monthly; alerts drive retention | Subscription + affiliate |
| **MarketWatch** | News-triggered + earnings dates | 10M+ monthly | Ad-supported |
| **eToro/Robinhood** | Social + price + news | Gen-Z retail; alerts for FOMO | Freemium (commission-free + premium) |

### 1.2 The "Alert Fatigue" Problem

**Current worldview behavior:**
- ✅ User gets 3 signal alerts (BULLISH guidance + negative news + confidence drop)
- ❌ User sees: "HIGH CRITICAL CRITICAL"
- ❌ User doesn't understand:
  - *Why* are there 3 alerts?
  - *How* do they conflict?
  - *What's* my position risk?
  - *When* should I act?

**Result**: Users snooze alerts → stop watching → churn

**What Winning Platforms Do:**
- Aggregate signals into **single, contextualized alerts**
- **Generate natural language explanations** (why this alert now?)
- **Provide immediate actions** (buy signal → "set buy limit at $X")
- **Learn user preferences** (I only care about 20% swings, not 2%)

### 1.3 Market Demands (From Web Research)

**From TradingView/Seeking Alpha/MarketWatch trends:**

1. **Sentiment-driven alerts** (90% of active traders)
   - News tone shifts (positive → negative)
   - Analyst rating changes
   - Insider buying/selling spikes

2. **Fundamental change alerts** (institutional investors)
   - Dividend announcements
   - Earnings guidance misses
   - Debt/credit rating changes
   - Insider transaction volumes

3. **Technical + sentiment hybrid** (retail traders)
   - Price breaks support + negative news (compounding risk)
   - Volume + sentiment divergence (potential reversal)

4. **Portfolio-level alerts** (portfolio managers)
   - "Your NASDAQ holdings are at risk (correlation spike)"
   - "Sector rotation: defensive outweighs growth"

5. **AI-generated explanations** (CRITICAL for retention)
   - "Apple up 3% on better-than-expected iPhone sales guidance"
   - "Tesla warned on competition; down 2% after hours"

---

## 2. Current Worldview Alert System (Baseline)

### 2.1 What We Have

**Alert Types (S10 currently):**
```
AlertType.SIGNAL
  ├─ Claim type (forward_guidance, factual, projection, opinion)
  ├─ Polarity (positive, negative)
  └─ Market impact score (0.0–1.0)

AlertType.GRAPH_CHANGE
  └─ Relation pattern changed (new evidence, confidence update, invalidation)

AlertType.CONTRADICTION
  └─ New claim contradicts existing claim for same entity
```

**Current Limitations:**
- ❌ No user-configurable rules
- ❌ No explanation generation
- ❌ No fundamental/price-based alerts
- ❌ No cross-signal aggregation
- ❌ No action suggestions
- ❌ Alert fatigue (users get flooded)

### 2.2 Current UX

```
[Pending Alerts List]
├─ AAPL: CRITICAL signal
├─ AAPL: HIGH graph change
├─ MSFT: MEDIUM signal
└─ [Snooze|Ack|Ignore]
```

**User confusion**: "All I see is severity badges. Why is this important?"

---

## 3. Enhancement Strategy — Phase 1 (MVP)

### 3.1 Stream 1: LLM-Generated Alert Explanations

**Goal**: Transform alerts from "bare events" into "understandable insights"

**Architecture:**

```
AlertFanoutUseCase
  └─ Create Alert (entity, type, severity, payload)
       └─ [NEW] GenerateAlertExplanationUseCase
            ├─ Extract payload context (claim_type, polarity, entities, market_impact_score)
            ├─ Query S7 for entity canonical name + sector
            ├─ Call S8 (LLM) with prompt:
            │   "Explain this market signal in 1–2 sentences for a retail investor"
            │   Input: AAPL forward_guidance positive, market_impact=0.82
            │   Output: "Apple signaled strong iPhone demand ahead. This is bullish."
            ├─ Cache result in Valkey (alert_id → explanation)
            └─ Store explanation_text on Alert row (nullable, forward-compatible)
       └─ Broadcast to WebSocket + Kafka with explanation
```

**API Changes:**
```typescript
// Before
interface Alert {
  alert_id: UUID;
  title: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  payload: Record<string, unknown>;
}

// After
interface Alert {
  alert_id: UUID;
  title: string;
  severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
  explanation: string | null;  // NEW: "Apple signaled strong demand..."
  payload: Record<string, unknown>;
}
```

**Frontend Rendering:**
```tsx
<AlertCard>
  <h3>{alert.title}</h3>
  <Badge severity={alert.severity} />
  {alert.explanation && (
    <p className="text-sm text-neutral-300">{alert.explanation}</p>
  )}
  <ActionButtons />
</AlertCard>
```

**Fallback**: If S8 is unavailable, explanation = null (no alert blocking)

**Time Budget**: 5–10s for explanation generation (async, not blocking user reception)

**Cost**: ~$0.0001 per explanation (small LLM call)

### 3.2 Stream 2: Custom Alert Rules (User Configuration)

**Goal**: Users define "I only care about alerts if..."

**New Database Schema (S10 + S1 if needed):**

```python
@dataclass
class AlertRule:
    rule_id: UUID
    user_id: UUID
    tenant_id: UUID
    name: str  # "Big AAPL moves"

    # Filter conditions (ALL must match for alert to fire)
    conditions: List[AlertRuleCondition] = field(default_factory=list)
    # Operator: AND (all match) or OR (any match)
    condition_operator: Literal["AND", "OR"] = "AND"

    # Actions
    notify_channels: List[DeliveryChannel]  # [WEBSOCKET, EMAIL]
    suppress_below_severity: AlertSeverity = AlertSeverity.LOW  # "don't notify if LOW"
    snooze_after_n: int | None = None  # Snooze after 5 alerts

    created_at: datetime
    enabled: bool = True


@dataclass
class AlertRuleCondition:
    rule_id: UUID
    condition_order: int

    # Condition type
    condition_type: Literal[
        "entity_ticker",          # AAPL, MSFT, etc.
        "alert_type",             # SIGNAL, GRAPH_CHANGE, CONTRADICTION
        "severity_threshold",     # >= MEDIUM
        "signal_polarity",        # positive, negative
        "claim_type",             # forward_guidance, factual, projection, opinion
        "market_impact_range",    # score >= 0.7
        "time_of_day",            # only 9:30–16:00 ET
        "entity_sector",          # Technology, Healthcare, etc.
    ]

    # Value(s)
    operator: Literal["=", ">=", "<=", "in", "between"]
    value: str | float | List[str | float]

    created_at: datetime
```

**Example Rule:**
```json
{
  "name": "Apple Big Bullish Signals",
  "conditions": [
    {"condition_type": "entity_ticker", "operator": "=", "value": "AAPL"},
    {"condition_type": "signal_polarity", "operator": "=", "value": "positive"},
    {"condition_type": "market_impact_range", "operator": ">=", "value": 0.75},
    {"condition_type": "time_of_day", "operator": "between", "value": ["09:30", "16:00"]}
  ],
  "condition_operator": "AND",
  "notify_channels": ["WEBSOCKET", "EMAIL"],
  "suppress_below_severity": "MEDIUM"
}
```

**API Endpoints (S9 → S10):**

```
POST   /api/v1/alert-rules                      # Create rule
GET    /api/v1/alert-rules                      # List user's rules
PATCH  /api/v1/alert-rules/{rule_id}            # Update rule
DELETE /api/v1/alert-rules/{rule_id}            # Delete rule
POST   /api/v1/alert-rules/{rule_id}/test       # Dry-run: test against last 100 alerts
```

**Implementation in AlertFanoutUseCase:**

```python
async def execute(self, event: dict, topic: str, ...) -> AlertFanoutResult:
    # ... existing logic ...
    alert = self._create_alert(...)

    # [NEW] Evaluate user rules
    for rule in user_rules:
        if self._rule_matches(alert, rule):
            # Only notify if rule matches
            pending_alerts_for_rule_watcher.append(...)
            outbox_events_for_rule_watcher.append(...)

    return result
```

**Frontend (S9 → worldview-web):**

```tsx
<AlertRuleBuilder>
  <RuleNameInput />
  <ConditionBuilder>
    <Select label="Entity" options={["AAPL", "MSFT", ...]} />
    <Select label="Signal Polarity" options={["Positive", "Negative"]} />
    <Slider label="Market Impact" min={0} max={1} />
    <TimeRangeSelect />
  </ConditionBuilder>
  <CheckboxGroup label="Notify me via">
    <Checkbox label="WebSocket (instant)" />
    <Checkbox label="Email (daily digest)" />
  </CheckboxGroup>
  <PreviewButton>Test on past alerts</PreviewButton>
  <SaveButton />
</AlertRuleBuilder>
```

### 3.3 Stream 3: New Alert Types (Future, not Phase 1)

**Planned but deferred to Phase 2:**
- `AlertType.PRICE_BREACH` — stock hit $X limit
- `AlertType.DIVIDEND_ANNOUNCED` — upcoming dividend
- `AlertType.EARNINGS_ANNOUNCEMENT` — earnings date/miss
- `AlertType.FUNDAMENTAL_CHANGE` — P/E ratio swing, debt increase, etc.
- `AlertType.INSIDER_TRANSACTION` — insider buying/selling spike

### 3.4 Stream 4: Actionable Recommendations

**Goal**: Alert → Immediate next steps

**Example:**
```
ALERT: Apple bullish guidance (CRITICAL)
├─ Explanation: "Apple signaled strong Q2 demand; market impact 0.84"
├─ Current Price: $185
├─ Recommendation:
│   ├─ ACTION: "Set buy limit at $183 (2% dip) for entry"
│   ├─ STOP: "Liquidate if price breaches $170 (8% stop-loss)"
│   ├─ TARGET: "Take profit at $195 (5% target)"
│   └─ [One-Click → Create order in your broker]
```

**Implementation (Phase 2):** S8 generates action suggestions based on alert + user portfolio context

---

## 4. Technical Design

### 4.1 Required Changes by Service

#### S10 (Alert Service)

**New Tables:**
- `alert_rules` — user rule definitions
- `alert_rule_conditions` — rule conditions
- `alert_explanations` — cache of LLM-generated explanations (optional; can be ephemeral)

**New Use Cases:**
- `CreateAlertRuleUseCase`
- `ListAlertRulesUseCase`
- `GenerateAlertExplanationUseCase`
- `EvaluateAlertRulesUseCase`

**Modified Use Cases:**
- `AlertFanoutUseCase` — call rule evaluator before fan-out

**New Routes:**
```python
POST /api/v1/alert-rules
GET  /api/v1/alert-rules
PATCH /api/v1/alert-rules/{rule_id}
DELETE /api/v1/alert-rules/{rule_id}
POST /api/v1/alert-rules/{rule_id}/test
```

#### S8 (RAG/Chat Service)

**New Internal Endpoint:**
```
POST /internal/v1/alert-explanations
  Input: {event_type, payload, market_impact_score, entity_name}
  Output: {explanation_text}
```

**Prompt Template:**
```
You are a financial alert explanation assistant. Explain this market signal
in 1–2 sentences for a retail investor. Be factual and concise.

Signal: {signal_type}
Entity: {entity_name}
Claim Type: {claim_type}
Polarity: {polarity}
Market Impact: {market_impact_score} (0–1)
Payload: {payload}

Explanation:
```

#### S9 (API Gateway)

**New Routes (proxy to S10):**
```python
router.post("/v1/alert-rules", ...)
router.get("/v1/alert-rules", ...)
# etc.
```

#### Frontend (worldview-web)

**New Pages:**
- `/alerts/rules` — rule management UI
- `/alerts/preferences` — alert notification settings

**New Components:**
- `<AlertExplanation />` — render explanation text
- `<AlertRuleBuilder />` — rule CRUD
- `<ActionButtons />` — one-click actions

### 4.2 Database Schema (S10 Alembic)

```python
class AlertRule(Base):
    __tablename__ = "alert_rules"

    rule_id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    user_id: UUID = Column(UUID(as_uuid=True), nullable=False, index=True)
    tenant_id: UUID = Column(UUID(as_uuid=True), nullable=False, index=True)
    name: str = Column(String(255), nullable=False)
    description: str | None = Column(String(1000))
    condition_operator: str = Column(String(10), default="AND")  # AND | OR

    notify_channels: List[str] = Column(JSON, default=[])  # ["websocket", "email"]
    suppress_below_severity: str = Column(String(20), default="LOW")
    snooze_after_n: int | None = Column(Integer)

    enabled: bool = Column(Boolean, default=True)
    created_at: datetime = Column(DateTime(timezone=True), default=utc_now)
    updated_at: datetime = Column(DateTime(timezone=True), onupdate=utc_now)
    deleted_at: datetime | None = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_alert_rules_user_tenant", "user_id", "tenant_id"),
        Index("ix_alert_rules_enabled", "enabled"),
    )


class AlertRuleCondition(Base):
    __tablename__ = "alert_rule_conditions"

    condition_id: UUID = Column(UUID(as_uuid=True), primary_key=True, default=uuid7)
    rule_id: UUID = Column(UUID(as_uuid=True), ForeignKey("alert_rules.rule_id"), index=True)
    condition_order: int = Column(Integer, nullable=False)

    condition_type: str = Column(String(50), nullable=False)  # entity_ticker, severity_threshold, etc.
    operator: str = Column(String(20), nullable=False)  # =, >=, <=, in, between
    value: str | float | List = Column(JSON, nullable=False)

    created_at: datetime = Column(DateTime(timezone=True), default=utc_now)
```

**Alert table change (forward-compatible):**
```python
# In existing Alert model
explanation: str | None = Column(String(2000), nullable=True, default=None)
```

---

## 5. Rollout Plan (Phase 1, 4 weeks)

### Week 1: Infrastructure
- [ ] Create Alembic migration (alert_rules + alert_rule_conditions tables)
- [ ] Add `explanation` column to alerts table (nullable)
- [ ] Unit tests for schema + repositories

### Week 2: Core Logic
- [ ] Implement `GenerateAlertExplanationUseCase` (calls S8)
- [ ] Implement `EvaluateAlertRulesUseCase`
- [ ] Modify `AlertFanoutUseCase` to call evaluator
- [ ] Integration tests + E2E test

### Week 3: APIs + Frontend
- [ ] S10 new routes (create/list/update/delete rules, test rule)
- [ ] S9 proxy routes
- [ ] Frontend: `<AlertRuleBuilder />`, rule CRUD pages
- [ ] Frontend: render `explanation` on alert cards

### Week 4: Polish + Testing
- [ ] Full integration test (signal → rule evaluation → explanation → WebSocket)
- [ ] Load test (1000 rules, 100 concurrent users)
- [ ] Documentation + runbook
- [ ] User acceptance testing

---

## 6. Success Metrics

| Metric | Target | How to Measure |
|--------|--------|----------------|
| **Alert clarity** | 80% of users rate explanation "helpful or better" | Post-alert survey |
| **Rule adoption** | 60% of active users create >= 1 rule | Analytics tracking |
| **Alert fatigue reduction** | Avg alerts per user/day ↓ 40% | A/B test: rules vs. no rules |
| **Engagement** | Avg alert acknowledgement time ↑ 25% | Funnel metrics |
| **Retention** | 30-day churn ↓ 15% | Cohort analysis |

---

## 7. Competitive Differentiation

| Feature | TradingView | Bloomberg | **Worldview** |
|---------|------------|-----------|---------------|
| Custom alert rules | ✅ (screeners) | ✅ | ✅ *NEW* |
| AI-generated explanations | ❌ | ❌ | ✅ *NEW* |
| Knowledge graph context | ❌ | ❌ | ✅ (S7) |
| Free tier | ✅ | ❌ | ✅ |
| Hybrid retrieval (vector + KG) | ❌ | ❌ | ✅ (S8) |

**Unique Value Prop**: "Intelligent alerts that explain themselves + context from your holdings"

---

## 8. Phase 2 & Beyond (Future)

**Not in scope for thesis, but on the roadmap:**

- **Price/fundamental alerts**: AlertType.PRICE_BREACH, .DIVIDEND_ANNOUNCED, .EARNINGS_ANNOUNCEMENT
- **Sentiment aggregation**: Combine NLP signals + insider data + analyst ratings into 1 alert
- **Cross-signal contradiction detection**: "Alert says bullish but insider selling spike" → flag
- **Portfolio-level alerts**: Correlation spike across holdings, sector rotation, etc.
- **One-click actions**: "Set buy limit" → create order in connected broker (Alpaca, etc.)
- **Mobile push notifications**: Native iOS/Android push (not just WebSocket)
- **Email digest scheduling**: "Send me a summary every Monday 8am"
- **Alerting API** (for power users): `/api/v1/alerts/query?entity_id=X&severity>=HIGH` → programmatic access

---

## 9. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| **S8 unavailability** | Explanation = null; alert still fires (best-effort) |
| **Rule evaluation latency** | Async evaluation; cache rule matches in Valkey |
| **High rule complexity (1000s)** | Index user_id + enabled in DB; shard by user if needed |
| **LLM hallucination** (wrong explanation) | Add explanation review step (Phase 2); flag low-confidence |
| **User overwhelm** (too many options) | Progressive disclosure; start with 3 pre-built rule templates |

---

## 10. Conclusion

Alerts are the **gateway to user engagement** in market intelligence platforms. By adding AI-generated explanations and user-configurable rules, Worldview can:

1. **Reduce alert fatigue** → Higher engagement
2. **Enable power users** → Custom alert workflows
3. **Differentiate from competitors** → Free tier with intelligent explanations
4. **Increase retention** → Users come back because alerts are *useful*

**Next Steps**: Prioritize Phase 1 implementation. Start with LLM explanations (Week 1–2), then layer in custom rules (Week 2–3) for maximum impact within the thesis timeline.
