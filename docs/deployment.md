# Google Cloud Deployment & Production Architecture

This document describes the planned deployment topology and infrastructure components for hosting ResearchMind on Google Cloud Platform.

---

## 1. Cloud Infrastructure Architecture

```
Internet / User
      │
      ▼
Google Cloud Armor (DDoS & WAF Protection)
      │
      ▼
Google Cloud Run (API Gateway Service)
      ├── Autoscale: 0 -> 20 instances
      ├── Ingress: Load Balanced HTTPS
      │
      ├── Write: Google Cloud Firestore (Run state & task trees)
      ├── Publish: Google Cloud Pub/Sub (`researchmind-agent-tasks`)
      └── Read: Google Cloud Storage (Final report artifacts)

Google Cloud Pub/Sub Topic
      │
      ▼ (Push / Pull Subscription)
Google Cloud Run (Agent Worker Service / Job)
      ├── Autoscale: 0 -> 50 instances
      ├── Concurrency: Controlled per container
      │
      ├── Gemini 2.5 API (Vertex AI / Google AI Studio)
      ├── Qdrant Cloud (Vector Similarity Retrieval)
      ├── Write: Google Cloud Firestore (Evidence & Checkpoints)
      └── Write: Google Cloud Storage (`researchmind-artifacts`)
```

---

## 2. Infrastructure as Code & Service Layout

| Service | GCP Resource | Description |
| :--- | :--- | :--- |
| **API Gateway** | Cloud Run (Service) | FastAPI application exposing REST and SSE streaming endpoints. |
| **Agent Workers** | Cloud Run (Job / Worker Service) | Background consumer processing Pub/Sub task messages. |
| **Message Queue** | Cloud Pub/Sub | Distributes tasks and streams progress events. |
| **State Store** | Cloud Firestore | Manages relational-like hierarchical research states and lock leases. |
| **Vector DB** | Qdrant Cloud / Compute Engine | Stores and queries high-dimensional embeddings for RAG. |
| **Object Store** | Cloud Storage (GCS) | Holds generated markdown/PDF research reports and raw source snapshots. |
| **Secret Store** | Cloud Secret Manager | Securely stores Gemini API keys and database credentials. |

---

## 3. Deployment Workflow

1. **Container Build**: Cloud Build compiles Docker images for the API Gateway and background worker services.
2. **Infrastructure Provisioning**: Terraform / gcloud CLI scripts create Pub/Sub topics, Firestore databases, and GCS buckets.
3. **Secret Injection**: Cloud Run references secrets directly from Secret Manager via environment variable bindings.
4. **Zero-Downtime Rollout**: Cloud Run performs blue-green traffic migration for seamless updates.
