output "delivery_identity" {
  description = "Non-secret, environment-bound delivery identity for release automation."
  value = {
    environment = var.environment
    bucket      = cloudflare_r2_bucket.release.name
    data_origin = "https://${var.data_domain}"
    worker      = cloudflare_workers_script.static_site.script_name
  }
}

output "publication_authorized" {
  description = "Infrastructure provisioning never grants data-publication authority."
  value       = false
}
