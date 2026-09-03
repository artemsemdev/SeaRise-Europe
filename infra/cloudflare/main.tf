locals {
  release_expression       = "(http.host eq \"${var.data_domain}\" and starts_with(http.request.uri.path, \"/releases/\"))"
  mutable_alias_expression = "(http.host eq \"${var.data_domain}\" and http.request.uri.path eq \"/release.json\")"
}

resource "cloudflare_r2_bucket" "release" {
  account_id    = var.account_id
  name          = var.release_bucket_name
  jurisdiction  = "eu"
  location      = "weur"
  storage_class = "Standard"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket_cors" "release" {
  account_id   = var.account_id
  bucket_name  = cloudflare_r2_bucket.release.name
  jurisdiction = "eu"

  rules = [{
    id = "searise-${var.environment}-browser-read"
    allowed = {
      origins = var.approved_origins
      methods = ["GET", "HEAD"]
      headers = ["If-Match", "If-None-Match", "Range"]
    }
    expose_headers = [
      "Accept-Ranges",
      "Cache-Control",
      "Content-Length",
      "Content-Range",
      "Content-Type",
      "ETag",
    ]
    max_age_seconds = 7200
  }]

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_bucket_lifecycle" "release" {
  account_id   = var.account_id
  bucket_name  = cloudflare_r2_bucket.release.name
  jurisdiction = "eu"

  rules = [{
    id      = "abort-incomplete-multipart-after-seven-days"
    enabled = true
    conditions = {
      prefix = ""
    }
    abort_multipart_uploads_transition = {
      condition = {
        max_age = 7
        type    = "Age"
      }
    }
  }]

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_r2_custom_domain" "release" {
  account_id   = var.account_id
  bucket_name  = cloudflare_r2_bucket.release.name
  domain       = var.data_domain
  enabled      = true
  zone_id      = var.zone_id
  jurisdiction = "eu"
  min_tls      = "1.2"

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_ruleset" "release_cache" {
  zone_id     = var.zone_id
  name        = "SeaRise ${var.environment} release cache policy"
  description = "Immutable versioned releases and an uncached mutable discovery alias."
  kind        = "zone"
  phase       = "http_request_cache_settings"

  rules = [
    {
      ref         = "searise_${var.environment}_mutable_alias_no_store"
      description = "The unversioned release discovery alias is never cached."
      expression  = local.mutable_alias_expression
      action      = "set_cache_settings"
      action_parameters = {
        cache = false
      }
    },
    {
      ref         = "searise_${var.environment}_immutable_release"
      description = "Cache every versioned release object and respect strong ETags."
      expression  = local.release_expression
      action      = "set_cache_settings"
      action_parameters = {
        cache = true
        browser_ttl = {
          mode = "respect_origin"
        }
        edge_ttl = {
          mode    = "override_origin"
          default = 31536000
        }
        respect_strong_etags = true
      }
    },
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_ruleset" "release_headers" {
  zone_id     = var.zone_id
  name        = "SeaRise ${var.environment} release response headers"
  description = "Response-only security and role-specific cache headers."
  kind        = "zone"
  phase       = "http_response_headers_transform"

  rules = [
    {
      ref         = "searise_${var.environment}_immutable_headers"
      description = "Set immutable and security headers on every versioned release object."
      expression  = local.release_expression
      action      = "rewrite"
      action_parameters = {
        headers = {
          "Cache-Control" = {
            operation = "set"
            value     = "public, max-age=31536000, immutable"
          }
          "Referrer-Policy" = {
            operation = "set"
            value     = "no-referrer"
          }
          "X-Content-Type-Options" = {
            operation = "set"
            value     = "nosniff"
          }
        }
      }
    },
    {
      ref         = "searise_${var.environment}_mutable_alias_headers"
      description = "Prevent persistence of the unversioned release discovery alias."
      expression  = local.mutable_alias_expression
      action      = "rewrite"
      action_parameters = {
        headers = {
          "Cache-Control" = {
            operation = "set"
            value     = "no-store"
          }
          "Referrer-Policy" = {
            operation = "set"
            value     = "no-referrer"
          }
          "X-Content-Type-Options" = {
            operation = "set"
            value     = "nosniff"
          }
        }
      }
    },
  ]

  lifecycle {
    prevent_destroy = true
  }
}

resource "cloudflare_workers_script" "static_site" {
  account_id  = var.account_id
  script_name = var.static_worker_name
  assets = {
    directory = var.static_assets_directory
    config = {
      headers            = file("${path.module}/static-assets.headers")
      html_handling      = "auto-trailing-slash"
      not_found_handling = "single-page-application"
      run_worker_first   = false
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}
