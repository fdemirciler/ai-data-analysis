# Project Design: Conversational Agentic Data Analysis Chatbot
## GCP Free Tier Optimized Architecture (Final Version)

## 1. Project Overview & Philosophy

### 1.1. Overview
This document outlines the architecture for a production-grade, conversational data analysis chatbot built entirely within the Google Cloud Platform's free tier. The system enables users to perform natural language data analysis on uploaded CSV/Excel files through secure, AI-generated Python code execution. It is designed for personal skill development and testing with a small user base (5–10 users) while adhering to enterprise-level security, reliability, and user experience standards.

### 1.2. Core Philosophy
- **Simple & Pragmatic**: Favoring straightforward solutions that are easy to build, debug, and maintain for a solo developer.  
- **Functional & User-Friendly**: The primary goal is to deliver a fast, intuitive, and reliable user experience.  
- **Production Standards on a Budget**: Applying best practices for security, monitoring, and resilience, even within the tight constraints of the free tier.  

---

## 2. Goals & Constraints

### 2.1. Goals
- **Production-Ready within Free Tier**: Build a robust system that feels professional and reliable without incurring costs.  
- **Security-First Development**: Treat all generated code as untrusted and implement a multi-layered defense strategy.  
- **Optimal User Experience**: Deliver a fast, interactive, and transparent conversational flow with clear, continuous feedback.  
- **Maintainable & Scalable Architecture**: Design a system that is simple to manage and has a clear, logical path for future upgrades.  

### 2.2. Constraints & Strategy
- **Cloud Run**: 2M requests/month, 360,000 GB-seconds of compute.  
- **Cloud Storage**: 5GB standard storage.  
- **Firestore**: 1GB storage, 50K reads/day, 20K writes/day.  
- **Cloud Functions**: 2M invocations/month.  
- **File Size Limit**: Strict 20 MB maximum per uploaded file to ensure fast, predictable performance.  

**Core Strategy**: An aggressive focus on efficiency. We will cache data, compress files, minimize API calls, manage cold starts, and implement strict quotas to stay within limits.  

---

## 3. System Architecture

### 3.1. Core Components

| Component | Service | Role & Justification |
|-----------|---------|-----------------------|
| **Frontend** | Firebase Hosting & Auth | Provides a free, globally-distributed CDN for the UI and handles secure user authentication. |
| **File Storage** | Cloud Storage (Standard) | Stores user files with compression and aggressive lifecycle rules to manage the 5GB limit. |
| **State & Caching** | Firestore | Manages conversational history and user-specific metadata. TTL policies ensure data expires automatically. |
| **Fast Execution** | Cloud Functions | The "fast path" for 80% of queries. Handles simple, sub-second Pandas operations. |
| **Complex Execution** | Cloud Run (Sandbox) | The "heavy-duty path" for complex or long-running jobs, providing a secure, isolated sandbox. |
| **Orchestrator** | Cloud Functions (SSE) | Manages the end-to-end conversational loop, streaming real-time progress updates via Server-Sent Events. |
| **AI Generation** | Gemini API (Flash) | The free-tier model used for classifying query complexity and generating Python code. |
| **Monitoring** | Cloud Logging & Monitoring | Provides logging, dashboards, and alerting for all services within the generous free tier. |

### 3.2. Architectural Diagram

```mermaid
flowchart TD
    A[User Frontend<br/>Firebase Hosting + Auth] -->|Upload file (<20MB)| B[Cloud Storage]
    B -->|Storage Event Trigger| C[Cloud Run Preprocessing]
    C -->|Extract metadata + sample| D[Firestore]

    A -->|User Query| E[Streaming Orchestrator<br/>(Cloud Function SSE)]
    E -->|Quota Check| D
    E -->|Send Prompt with Context| F[Gemini API (Flash)]
    F -->|Return JSON {complexity, code}| E

    E -->|AST Validation| G[Validation Layer]
    G -->|Invalid| H[Safe Fallback Templates]
    G -->|Valid SIMPLE| I[Fast Execution<br/>Cloud Function]
    G -->|Valid COMPLEX| J[Complex Execution<br/>Cloud Run Sandbox]

    I -->|Failure → Retry| J
    I -->|Results| K[Post-processing & Summarization]
    J -->|Results| K
    H -->|Fallback Results| K

    K -->|Update Session| D
    K -->|Streamed Results| A

    subgraph Storage
        B
        D
    end
```

---

## 4. Key Architectural Decisions & Enhancements

### 4.1. LLM-Assisted Dual-Path Execution
- Gemini returns both code and complexity classification (SIMPLE or COMPLEX).  
- SIMPLE → Cloud Function.  
- COMPLEX → Cloud Run sandbox.  
- **Automatic Failover**: SIMPLE failures automatically rerun on Cloud Run, with SSE notifying the user.  

### 4.2. Safe Fallback Templates
- If AI-generated code fails validation or runtime execution, pre-written safe templates (e.g., dataset shape, column stats, missing values) run instead.  
- Guarantees the user always gets a result.  

### 4.3. Efficient State Management
- Use condensed summaries (via Gemini Flash) plus last two raw exchanges.  
- Controls token growth while keeping context intact.  

---

## 5. Free Tier Risk Management

### 5.1. Per-User Quotas
- 60 queries/day per user.  
- 10 queries/hour per user.  
- Enforced via Firestore counters.  
- Clear feedback when limits are exceeded.  

### 5.2. Global Usage Monitoring & Alerting
- Dashboards track usage against free tier limits.  
- Alerts at 70% and 90% thresholds.  
- Graceful degradation at 90%: only SIMPLE queries allowed.  

---

## 6. Detailed Execution Flow

### 6.1. Stage 1: File Upload & Preprocessing
1. User uploads file (<20 MB) via signed URL (Cloud Function).  
2. File compressed and stored in Cloud Storage.  
3. Cloud Storage event triggers Cloud Run preprocessing.  
4. Preprocessing extracts metadata and sample → Firestore.  
5. User notified when dataset ready.  

### 6.2. Stage 2: Streaming Conversational Analysis Loop
1. User query → Orchestrator (Cloud Function SSE).  
2. Quota check in Firestore.  
3. SSE opened: "🔍 Analyzing your request..."  
4. Gemini returns JSON {complexity, code}.  
5. AST validation. If invalid → Fallback templates.  
6. SIMPLE → Cloud Function; COMPLEX → Cloud Run. Failures rerouted.  
7. Results summarized (JSON + ≤3 charts). Optional Gemini natural language summary.  
8. Firestore updated with condensed history.  
9. Final results streamed to frontend.  

---

## 7. Security & Compliance
- Input sanitization to block prompt injection.  
- AST validation + strict library whitelist (pandas, numpy, matplotlib).  
- Runtime sandboxing with no network egress.  
- "Delete My Data" option for immediate cleanup.  
- Aggressive GCS lifecycle (3 days raw, 14 days processed).  
- Firestore TTL auto-expiration.  

---

## 8. Migration Path to Paid Services
- Replace orchestrator Cloud Function with Cloud Workflows.  
- Add Memorystore (Redis) for caching.  
- Add Cloud SQL for persistence.  
- Scale Cloud Run concurrency for higher user load.  

---

## 9. Conclusion
This design delivers a production-grade experience within free tier constraints, emphasizing security, resilience, and user experience. It ensures fast, safe, and concise conversational data analysis while providing a clear upgrade path to paid GCP services.
