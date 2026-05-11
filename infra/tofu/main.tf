terraform {
  required_version = ">= 1.8"

  required_providers {
    hcloud = {
      source  = "registry.opentofu.org/providers/hetznercloud/hcloud"
      version = "~> 1.49"
    }
  }

  # ── Hetzner Object Storage S3-compatible backend ────────────────────────────
  # Stores Terraform state remotely so multiple machines can collaborate and
  # state is never lost with a local disk failure.
  #
  # Setup (one-time):
  #   1. Log in to Hetzner Cloud Console → Object Storage → Create Bucket
  #      Name: worldview-tfstate  |  Location: nbg1  |  Visibility: Private
  #   2. Create S3-compatible Access Key:
  #      Console → Security → S3 Credentials → Generate access key
  #   3. Create ~/.config/tofu/hetzner-s3.tfbackend (gitignored):
  #        access_key = "<S3_ACCESS_KEY>"
  #        secret_key = "<S3_SECRET_KEY>"
  #   4. Init with backend: tofu init -backend-config=~/.config/tofu/hetzner-s3.tfbackend
  #
  # Hetzner S3 endpoint: https://nbg1.your-objectstorage.com
  # Hetzner docs: https://docs.hetzner.com/storage/object-storage/
  backend "s3" {
    bucket = "worldview-tfstate"
    key    = "prod/terraform.tfstate"
    region = "us-east-1"  # Hetzner S3 requires a region value; any string works

    # Hetzner S3 endpoint for Nuremberg region
    endpoint = "https://nbg1.your-objectstorage.com"

    # Required for Hetzner S3 compatibility
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    force_path_style            = true

    # Credentials injected at init time via -backend-config flag
    # Never hardcode access_key / secret_key here
  }
}

provider "hcloud" {
  token = var.hcloud_token
}
