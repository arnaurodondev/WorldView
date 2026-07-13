terraform {
  required_version = ">= 1.8"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
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
  #
  # FIRST-DEPLOY (2026-07-07): using LOCAL state (terraform.tfstate in this dir) to
  # skip the Object Storage bucket + S3 credential setup. terraform.tfstate is
  # git-ignored. MIGRATE TO REMOTE STATE before relying on this long-term: create the
  # `worldview-tfstate` bucket + S3 creds (steps above), uncomment the backend below,
  # and run `tofu init -migrate-state -backend-config=~/.config/tofu/hetzner-s3.tfbackend`.
  # A laptop disk loss now = lost state → orphaned Hetzner resources, so back up
  # terraform.tfstate (or migrate) once the cluster is stable.
  #
  # backend "s3" {
  #   bucket = "worldview-tfstate"
  #   key    = "prod/terraform.tfstate"
  #   region = "us-east-1"
  #   endpoint = "https://nbg1.your-objectstorage.com"
  #   skip_credentials_validation = true
  #   skip_metadata_api_check     = true
  #   skip_region_validation      = true
  #   force_path_style            = true
  # }
}

provider "hcloud" {
  token = var.hcloud_token
}
