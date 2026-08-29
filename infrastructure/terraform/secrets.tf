# -----------------------------------------------------------------------------
# Google Cloud Secret Manager Declarations
# (Secret values are managed out-of-band to prevent state file leakage)
# -----------------------------------------------------------------------------

resource "google_secret_manager_secret" "researchmind_api_key" {
  secret_id = "${local.service_name_prefix}-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "gemini_api_key" {
  secret_id = "${local.service_name_prefix}-gemini-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "tavily_api_key" {
  secret_id = "${local.service_name_prefix}-tavily-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}

resource "google_secret_manager_secret" "qdrant_api_key" {
  secret_id = "${local.service_name_prefix}-qdrant-api-key"

  replication {
    auto {}
  }

  depends_on = [google_project_service.enabled_apis]
}
