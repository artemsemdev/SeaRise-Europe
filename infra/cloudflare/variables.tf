variable "account_id" {
  description = "Cloudflare account identifier supplied by the protected environment."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.account_id))
    error_message = "account_id must be a lowercase 32-character Cloudflare identifier."
  }
}

variable "zone_id" {
  description = "Cloudflare zone identifier that owns the reviewed data hostname."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{32}$", var.zone_id))
    error_message = "zone_id must be a lowercase 32-character Cloudflare identifier."
  }
}

variable "environment" {
  description = "Isolated delivery environment."
  type        = string

  validation {
    condition     = contains(["fixture", "staging", "production"], var.environment)
    error_message = "environment must be fixture, staging, or production."
  }
}

variable "release_bucket_name" {
  description = "Environment-exclusive R2 release bucket."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$", var.release_bucket_name))
    error_message = "release_bucket_name must be a valid explicit R2 bucket name."
  }
}

variable "data_domain" {
  description = "Environment-exclusive canonical R2 custom domain."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$", var.data_domain))
    error_message = "data_domain must be one explicit lowercase hostname."
  }
}

variable "approved_origins" {
  description = "Exact browser origins permitted by R2 CORS. Wildcards are forbidden."
  type        = list(string)

  validation {
    condition = (
      length(var.approved_origins) > 0 &&
      length(var.approved_origins) == length(toset(var.approved_origins)) &&
      alltrue([
        for origin in var.approved_origins :
        can(regex("^https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?:\\:[0-9]{2,5})?$", origin)) &&
        !strcontains(origin, "*")
      ])
    )
    error_message = "approved_origins must contain unique explicit HTTPS origins without wildcards."
  }
}

variable "static_worker_name" {
  description = "Environment-exclusive Workers Static Assets script name."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,62}$", var.static_worker_name))
    error_message = "static_worker_name must be an explicit lowercase Worker name."
  }
}

variable "static_assets_directory" {
  description = "Reviewed static app directory; release objects are never placed here."
  type        = string

  validation {
    condition     = !strcontains(var.static_assets_directory, "candidate-v7") && !strcontains(var.static_assets_directory, ".tar")
    error_message = "private Candidate-v7 and TAR paths are forbidden."
  }
}
