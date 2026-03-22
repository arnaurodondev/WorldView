# Worldview Project Overview

> **Scope**: High-level explanation of the Worldview platform, its architecture, services, and infrastructure. Intended for developers, reviewers, and stakeholders seeking to understand the system at a conceptual level.

---

## 1. The Main Idea

**Worldview** is a **market intelligence platform** designed for a university thesis. It bridges the gap between traditional quantitative financial data (stock prices, fundamentals) and qualitative unstructured data (news, sentiment, relationships).

The core innovation is fusion: rather than treating news and prices separately, Worldview links them via a **Knowledge Graph** and makes them accessible through an **LLM-powered Chatbot (RAG)**. Users can ask questions like *"Why did NVIDIA drop today?"* and receive answers grounded in both price action and recent news events.

---

## 2. System Architecture

The project is a **Python + TypeScript Monorepo** built on a **Clean/Hexagonal Architecture**. It consists of **9 independent microservices** that communicate asynchronously via Kafka events and synchronously via REST APIs (orchestrated by an API Gateway).

### Key Architectural Patterns
- **Microservices**: Decomposed by domain (Market Data vs. Content vs. Portfolio).
- **Event-Driven**: Services emit events (e.g., `market.dataset.fetched`, `content.article.stored`) to trigger downstream processing.
- **Polyglot Persistence**: Different databases for different needs (TimescaleDB for time-series, pgvector for embeddings, Apache AGE for graphs).
- **Outbox Pattern**: Ensures reliable event publishing without distributed transactions.
- **Claim-Check Pattern**: Large payloads (HTML, JSON dumps) are stored in MinIO; Kafka messages contain only references/IDs.

---

## 3. Service Breakdown (The 9 Microservices)

The backend is divided into 9 services (S1–S9), each with its own database schema and responsibility.

### **Core Domain Services**

| Service | Role | Database | Key Responsibility |
|:---|:---|:---|:---|
| **S1 · Portfolio** | User Context | `portfolio_db` | Manages user portfolios, holdings, and watchlists. Subscribes to market events to update valuations. |
| **S2 · Market Ingestion** | EODHD Gateway | `market_ingestion_db` | Polls the EODHD API for market data. Stores raw responses in MinIO and signals availability via Kafka. |
| **S3 · Market Data** | Analytics Engine | `market_data_db` | Consumes raw market data, processes it into efficient time-series (OHLCV) and structured fundamentals (Financial Statements). Serves charts. |
| **S4 · Content Ingestion** | News Gateway | `content_ingestion_db` | Polls RSS feeds and news APIs. Stores raw HTML/JSON in MinIO and signals new articles via Kafka. |
| **S5 · Content Store** | Article Repository | `content_store_db` | Cleans, normalizes, and deduplicates news articles. Acts as the canonical source of truth for text content. |
| **S6 · NLP Pipeline** | AI Enrichment | `nlp_db` | Runs ML models on articles: Sentiment Analysis, Named Entity Recognition (NER), and Embedding generation (for vector search). |
| **S7 · Knowledge Graph** | Relationship Engine | `kg_db` | Maps relationships between entities (e.g., `NVDA` -(supplies)-> `MSFT`). Enables graph-based reasoning. |
| **S8 · RAG / Chat** | Intelligence Layer | (Stateless) | The "Brain". Orchestrates LLM queries using Retrieval-Augmented Generation (RAG) by fetching context from S3, S6, and S7. |
| **S9 · API Gateway** | Frontend Entrypoint | (Stateless) | A "Backend-for-Frontend" (BFF). Aggregates data from internal services and presents a unified GraphQL/REST API to the UI. |

---

## 4. Infrastructure & Tech Stack

The entire platform runs locally using Docker Compose, simulating a production-grade cloud environment.

### **Compute & Language**
- **Backend**: Python 3.12, FastAPI, SQLAlchemy (Async), Pydantic.
- **Frontend**: TypeScript, React, Vite, TanStack Query.
- **Orchestration**: Docker Compose.

### **Data & Messaging**
- **Apache Kafka**: The central nervous system. Handles all inter-service communication ensuring loose coupling.
- **MinIO (S3 Compatible)**: Object storage for large raw data (JSON dumps, HTML files) to keep the database light.
- **Valkey (Redis Fork)**: High-performance caching for API responses and rate limiting.

### **Databases (PostgreSQL Ecosystem)**
We use a single Postgres instance with powerful extensions to handle diverse data types:
- **TimescaleDB**: Optimizes storage and queries for time-series financial data (OHLCV).
- **pgvector**: Stores vector embeddings for semantic search in the RAG pipeline.
- **Apache AGE**: Enables graph queries (Cypher) within Postgres for the Knowledge Graph.
- **Standard Postgres**: Used for relational data (User portfolios, metadata).

---

## 5. Data Flow Workflows

How data moves through the interactions of these services.

### **A. Structured Data Pipeline (Market Data)**
1. **S2 (Ingestion)** wakes up (scheduler) and fetches raw prices/fundamentals from EODHD.
2. Raw data is saved to **MinIO** (Bronze Layer).
3. S2 emits a `market.dataset.fetched` event to **Kafka**.
4. **S3 (Market Data)** consumes this event, downloads the file from MinIO, parses it, and inserts clean records into **TimescaleDB**.
5. The Frontend requests a chart; **S9 (Gateway)** fetches it from **S3**.

### **B. Unstructured Data Pipeline (News & Insights)**
1. **S4 (Ingestion)** detects a new RSS item and saves raw HTML to **MinIO**.
2. S4 emits `content.article.raw`.
3. **S5 (Store)** consumes it, cleans the HTML, deduplicates it, and saves the text. Emits `content.article.stored`.
4. **S6 (NLP)** consumes the stored article. It runs:
   - **Sentiment Model**: Is this good or bad news?
   - **NER Model**: Whic companies are mentioned? (e.g., "Apple", "Tim Cook").
   - **Embedding Model**: Converts text to vectors.
5. S6 stores these insights in **pgvector** and emits `nlp.article.enriched`.
6. **S7 (Graph)** links the mentioned entities in the **Knowledge Graph**.

### **C. The User Interaction (RAG Chat)**
1. User asks: *"How does Apple's news affect its stock?"*
2. **S8 (Chat)** receives the query.
3. S8 searches **S6 (Vector DB)** for relevant news.
4. S8 queries **S3 (Market Data)** for recent price changes.
5. S8 synthesizes an answer using an LLM (e.g., Llama 3 via Ollama) citeing specific articles and price movements.
6. **S9 (Gateway)** delivers the streaming response to the Frontend.

---

## 6. Directory Structure

- `apps/frontend`: React Application.
- `services/`: The 9 microservices folders.
- `libs/`: Shared Python code (Messaging, Storage, Observability) used by all services to ensure consistency.
- `infra/`: Infrastructure definitions (Docker Compose, Kafka schemas, Database initialization).
- `docs/`: Comprehensive documentation.

---

## Summary

Worldview is a modern, event-driven platform that demonstrates how to build complex financial systems. It separates concerns strictly (Ingestion vs. Storage vs. Presentation) while unifying data through a shared event bus and a clever multi-modal database strategy.
