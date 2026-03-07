# Architecture Diagrams

> Mermaid diagrams for the Worldview platform.
> See `docs/MASTER_PLAN.md` for full context.

---

## Component Diagram

```mermaid
graph TB
    subgraph "Client Layer"
        UI[Web Frontend<br/>React / Vite]
    end

    subgraph "Gateway Layer"
        GW[API Gateway / BFF<br/>FastAPI + Valkey]
    end

    subgraph "Domain Services"
        S1[S1 · Portfolio<br/>FastAPI :8001]
        S2[S2 · Market Ingestion<br/>FastAPI + Scheduler :8002]
        S3[S3 · Market Data<br/>FastAPI + Consumers :8003]
        S4[S4 · Content Ingestion<br/>FastAPI + Pollers :8004]
        S5[S5 · Content Store<br/>FastAPI + Consumers :8005]
        S6[S6 · NLP Pipeline<br/>FastAPI + Workers :8006]
        S7[S7 · Knowledge Graph<br/>FastAPI + AGE :8007]
        S8[S8 · RAG / Chat<br/>FastAPI + SSE :8008]
    end

    subgraph "Infrastructure"
        KAFKA[Apache Kafka<br/>+ Schema Registry]
        PG[(PostgreSQL 16<br/>+ TimescaleDB<br/>+ pgvector<br/>+ Apache AGE)]
        MINIO[(MinIO<br/>Object Storage)]
        VALKEY[(Valkey / Redis<br/>Cache + Rate Limits)]
        LLM_EXT[LLM Providers<br/>Ollama / Groq / OpenRouter]
    end

    subgraph "External Data"
        EODHD[EODHD API]
        RSS[RSS Feeds + News APIs]
    end

    UI --> GW
    GW --> S1 & S3 & S5 & S6 & S7 & S8

    S2 --> EODHD
    S4 --> RSS

    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> PG
    S2 & S4 --> MINIO
    S3 & GW --> VALKEY
    S8 --> LLM_EXT

    S1 & S2 & S3 & S4 & S5 & S6 & S7 --> KAFKA

    S8 -.->|vector search| S6
    S8 -.->|graph query| S7
    S8 -.->|SQL query| S3
    S8 -.->|articles| S5
```

## Dataflow Diagram

```mermaid
flowchart LR
    subgraph "Structured Data Flow"
        EODHD[EODHD API] -->|poll| S2[Market Ingestion]
        S2 -->|raw + canonical| MINIO[(MinIO)]
        S2 -->|market.dataset.fetched| KAFKA{Kafka}
        KAFKA -->|claim-check consume| S3[Market Data]
        S3 -->|materialize| PG_MD[(market_data_db)]
        S3 -->|instrument events| KAFKA
        KAFKA -->|instrument.created| S1[Portfolio]
        S1 --> PG_PF[(portfolio_db)]
    end

    subgraph "Unstructured Data Flow"
        RSS[RSS / News APIs] -->|poll + relay| S4[S4 · Content Ingestion]
        S4 -->|raw HTML| MINIO
        S4 -->|content.article.raw.v1| KAFKA
        KAFKA -->|consume| S5[S5 · Content Store]
        S5 -->|dedup + clean| PG_CS[(content_store_db)]
        S5 -->|content.article.stored.v1| KAFKA
        KAFKA -->|consume| S6[S6 · NLP Pipeline]
        S6 -->|embeddings| PG_VEC[(nlp_db / pgvector)]
        S6 -->|entities/events| PG_KG[(kg_db / AGE)]
        S6 -->|nlp.article.enriched.v1| KAFKA
    end

    subgraph "Query / Chat Flow"
        UI[Frontend :5173] -->|REST| GW[S9 · API Gateway :8000]
        GW --> S3_Q[S3] & S5_Q[S5] & S6_Q[S6]
        GW -->|chat| S8[S8 · RAG Service]
        S8 -->|vector search| PG_VEC
        S8 -->|graph traversal| PG_KG
        S8 -->|SQL| PG_MD
        S8 -->|LLM| LLM[Ollama / Groq]
    end
```

## Event Flow Sequence — Market Data Pipeline

```mermaid
sequenceDiagram
    participant SCH as Scheduler
    participant ING as Market Ingestion
    participant MIO as MinIO
    participant OBX as Outbox Dispatcher
    participant KFK as Kafka
    participant CON as Market Data Consumer
    participant DB as market_data_db

    SCH->>ING: create ingestion_task
    ING->>ING: worker claims task (lease)
    ING->>EODHD: fetch OHLCV data
    EODHD-->>ING: JSON response
    ING->>MIO: PUT raw (bronze)
    ING->>ING: normalize → canonical
    ING->>MIO: PUT canonical (silver)
    ING->>ING: write outbox_event (same txn as task_status=completed)
    OBX->>KFK: publish market.dataset.fetched (pointer event)
    KFK->>CON: deliver event
    CON->>CON: check idempotency (event_id)
    CON->>MIO: GET canonical data
    CON->>DB: UPSERT ohlcv_bars
    CON->>DB: UPSERT instruments (if new)
    opt new instrument
        CON->>KFK: market.instrument.created
    end
```

## Knowledge Graph Schema

```mermaid
graph LR
    Company -->|HAS_EXECUTIVE| Person
    Company -->|IN_SECTOR| Sector
    Company -->|INVOLVED_IN| Event
    Company -->|SUBSIDIARY_OF| Company2[Company]
    Company -->|PARTNER_OF| Company3[Company]
    Company -->|COMPETES_WITH| Company4[Company]
    Article -->|MENTIONS| Company
    Article -->|REPORTS_ON| Event
    Article -->|ABOUT_TOPIC| Topic
    Person -->|MOVED_TO| Company5[Company]
    Event -->|CAUSED_BY| Event2[Event]
```
