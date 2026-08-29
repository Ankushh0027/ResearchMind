locals {
  service_name_prefix = "researchmind-${var.environment}"
  api_service_name    = "${local.service_name_prefix}-api"
  worker_service_name = "${local.service_name_prefix}-worker"
  tasks_topic_name    = "${local.service_name_prefix}-tasks"
  tasks_sub_name      = "${local.service_name_prefix}-tasks-sub"
  artifacts_bucket    = "${var.project_id}-${local.service_name_prefix}-artifacts"
}

resource "google_project_service" "enabled_apis" {
  for_each = toset([
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
  ])

  project            = var.project_id
  service            = each.key
  disable_on_destroy = false
}
