terraform {
  required_version = "= 1.12.6"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "= 5.23.0"
    }
  }
}

provider "cloudflare" {}

module "delivery" {
  source = "../.."

  account_id              = "00000000000000000000000000000000"
  zone_id                 = "11111111111111111111111111111111"
  environment             = "fixture"
  release_bucket_name     = "searise-fixture-release"
  data_domain             = "data-fixture.example.invalid"
  approved_origins        = ["https://app-fixture.example.invalid"]
  static_worker_name      = "searise-fixture-static"
  static_assets_directory = "../static-site"
}

output "delivery_identity" {
  value = module.delivery.delivery_identity
}
