# -----------------------------------------------------------------------------
# Google Cloud Firestore (Native Mode) State Database
# -----------------------------------------------------------------------------

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = var.region
  type        = "FIRESTORE_NATIVE"

  concurrency_mode                = "OPTIMISTIC"
  app_engine_integration_mode     = "DISABLED"
  point_in_time_recovery_enablement = "POINT_IN_TIME_RECOVERY_ENABLED"
  delete_protection_state         = "DELETE_PROTECTION_ENABLED"

  depends_on = [google_project_service.enabled_apis]
}
