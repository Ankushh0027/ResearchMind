# Security Architecture & Baseline Policies

This document establishes the security guidelines, access controls, data handling practices, and threat mitigation strategies for ResearchMind.

---

## 1. Secrets Management & Configuration Safety

- **No Secrets in Code**: API keys, service account credentials, database passwords, and private tokens must **never** be committed to Git.
- **Environment-Driven Configuration**: Runtime settings are injected via environment variables and secret stores (e.g., Google Cloud Secret Manager).
- **Automated Scanning & Hygiene**: Pre-commit hooks, CI checks, and `.gitignore` enforce that secret files (e.g., `.env`, `credentials.json`, `*.pem`) are excluded from tracking.

---

## 2. Input Validation & API Defense

- **Strict Schema Enforcement**: All incoming client payloads are validated at the API perimeter using Pydantic models with type bounds, length constraints, and allowed enum values.
- **Rate Limiting & Quotas**: Protects backend resources and external LLM APIs from denial-of-service or runaway costs.
- **Sanitization**: Query inputs are sanitized against SQL injection, command injection, and SSRF attacks before invoking tools.

---

## 3. Tool Permission Boundaries & Agent Isolation

- **Scoped Tool Capabilities**: Agents have access only to explicitly declared tool interfaces necessary for their specific domain.
  - *Researcher Agent*: Read-only web query and document retrieval tools. No filesystem write or code execution privileges.
  - *Planner / Analyst / Verifier*: Pure reasoning and data transformation; no direct external network egress.
  - *Reporter Agent*: Read-only access to verified findings; write access only to designated GCS output prefixes.
- **Sandboxed Execution**: Any dynamic parsing or untrusted data processing runs in isolated container contexts with restricted system calls and no root privileges.

---

## 4. Cloud IAM & Least Privilege Access

- **Service Account Segregation**: Separate Google Cloud Service Accounts are provisioned for:
  - *API Gateway*: Minimal permissions to write to Firestore and publish to Pub/Sub.
  - *Worker Nodes*: Permissions to read/write Firestore, pull from Pub/Sub, read/write specific Cloud Storage buckets, and invoke Gemini APIs.
- **Resource-Level IAM**: Bucket policies restrict access so workers cannot overwrite or delete historical research archives.

---

## 5. Untrusted Document Handling & Prompt Injection Defense

- **External Content as Untrusted Data**: Web content, scraped HTML, PDFs, and uploaded documents are treated as untrusted and potentially hostile.
- **Prompt Injection Defense**:
  - Raw source text is quarantined in structured data delimiters (e.g., `<evidence_snippet>` XML tags) distinct from system instructions.
  - System prompts explicitly instruct models to ignore instructions, overrides, or commands contained within ingested documents.
  - Verifier and Evaluator agents inspect intermediate claims to ensure no prompt injection payload influences report generation.

---

## 6. Observability & Privacy Protection

- **PII & Credential Scrubbing**: Log formatters and telemetry pipelines automatically sanitize headers, authorization tokens, and user PII before shipping logs to Google Cloud Logging.
- **Encrypted in Transit & at Rest**: All communications between microservices, databases, and LLM endpoints use TLS 1.3. Data at rest in Firestore, GCS, and Qdrant is encrypted using customer-managed or cloud-managed encryption keys.
