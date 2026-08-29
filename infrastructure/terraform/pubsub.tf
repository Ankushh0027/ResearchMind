# -----------------------------------------------------------------------------
# Dead Letter Queue for Poison Pill Tasks
# -----------------------------------------------------------------------------

resource "google_pubsub_topic" "agent_tasks_dlq" {
  name       = "${local.tasks_topic_name}-dlq"
  depends_on = [google_project_service.enabled_apis]

  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
}

resource "google_pubsub_subscription" "agent_tasks_dlq_sub" {
  name  = "${local.tasks_sub_name}-dlq"
  topic = google_pubsub_topic.agent_tasks_dlq.name

  message_retention_duration = "604800s" # 7 days
  retain_acked_messages      = false
  ack_deadline_seconds       = 60
}

# -----------------------------------------------------------------------------
# Primary Asynchronous Research Tasks Topic & Subscription
# -----------------------------------------------------------------------------

resource "google_pubsub_topic" "agent_tasks" {
  name       = local.tasks_topic_name
  depends_on = [google_project_service.enabled_apis]

  message_storage_policy {
    allowed_persistence_regions = [var.region]
  }
}

resource "google_pubsub_subscription" "agent_tasks_sub" {
  name  = local.tasks_sub_name
  topic = google_pubsub_topic.agent_tasks.name

  ack_deadline_seconds       = 300 # 5 minutes per research task phase
  message_retention_duration = "86400s" # 24 hours
  retain_acked_messages      = false

  expiration_policy {
    ttl = "" # Never expire subscription
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.agent_tasks_dlq.id
    max_delivery_attempts = 5
  }
}
