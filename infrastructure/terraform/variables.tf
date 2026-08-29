variable "project_id" {
  type        = string
  description = "Target Google Cloud Project ID"
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Primary Google Cloud Region for Cloud Run, Pub/Sub, and GCS resources"
}

variable "environment" {
  type        = string
  default     = "production"
  description = "Deployment environment name (e.g. production, staging, dev)"
}

variable "api_image" {
  type        = string
  default     = "gcr.io/google-samples/hello-app:1.0"
  description = "Container image URI for ResearchMind API Gateway"
}

variable "worker_image" {
  type        = string
  default     = "gcr.io/google-samples/hello-app:1.0"
  description = "Container image URI for ResearchMind Background Worker"
}

variable "api_min_instances" {
  type        = number
  default     = 0
  description = "Minimum active instances for Cloud Run API Service (0 for serverless scale-to-zero)"
}

variable "api_max_instances" {
  type        = number
  default     = 10
  description = "Maximum active instances for Cloud Run API Service"
}

variable "worker_min_instances" {
  type        = number
  default     = 0
  description = "Minimum active instances for Cloud Run Worker Service"
}

variable "worker_max_instances" {
  type        = number
  default     = 20
  description = "Maximum active instances for Cloud Run Worker Service"
}

variable "worker_concurrency" {
  type        = number
  default     = 4
  description = "Asynchronous task concurrency per worker container"
}

variable "max_orchestration_concurrency" {
  type        = number
  default     = 8
  description = "Maximum parallel agent subtasks within a single research DAG"
}

variable "qdrant_url" {
  type        = string
  default     = ""
  description = "External Qdrant Cloud or VM vector database endpoint URL"
}

variable "gemini_model" {
  type        = string
  default     = "gemini-2.5-pro"
  description = "Primary Gemini intelligence model"
}
