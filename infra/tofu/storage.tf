# Hetzner Volumes — persistent storage for stateful services
# All volumes are attached to worker-1 (the stateful node)
# StorageClass hcloud-volumes maps PVCs to these volumes via the CSI driver

resource "hcloud_volume" "postgres" {
  name     = "worldview-postgres"
  size     = 100  # GB
  location = var.region
  format   = "ext4"

  lifecycle {
    prevent_destroy = true  # never destroy data volumes
  }
}

resource "hcloud_volume_attachment" "postgres" {
  volume_id = hcloud_volume.postgres.id
  server_id = hcloud_server.worker1.id
  automount = true
}

resource "hcloud_volume" "kafka" {
  name     = "worldview-kafka"
  size     = 50
  location = var.region
  format   = "ext4"

  lifecycle {
    prevent_destroy = true
  }
}

resource "hcloud_volume_attachment" "kafka" {
  volume_id = hcloud_volume.kafka.id
  server_id = hcloud_server.worker1.id
  automount = true
}

resource "hcloud_volume" "minio" {
  name     = "worldview-minio"
  size     = 100
  location = var.region
  format   = "ext4"

  lifecycle {
    prevent_destroy = true
  }
}

resource "hcloud_volume_attachment" "minio" {
  volume_id = hcloud_volume.minio.id
  server_id = hcloud_server.worker1.id
  automount = true
}

resource "hcloud_volume" "valkey" {
  name     = "worldview-valkey"
  size     = 10
  location = var.region
  format   = "ext4"
}

resource "hcloud_volume_attachment" "valkey" {
  volume_id = hcloud_volume.valkey.id
  server_id = hcloud_server.worker1.id
  automount = true
}

resource "hcloud_volume" "ollama" {
  name     = "worldview-ollama"
  size     = 30  # Ollama models: qwen2.5:3b ~2GB, nomic-embed-text ~270MB, bge-* ~1.5GB each
  location = var.region
  format   = "ext4"
}

resource "hcloud_volume_attachment" "ollama" {
  volume_id = hcloud_volume.ollama.id
  server_id = hcloud_server.worker1.id
  automount = true
}

# ── Object Storage for Tofu state backend ─────────────────────────────────────
# The S3 bucket itself cannot be managed by Tofu (chicken-and-egg problem —
# you need remote state to manage the state bucket). Create it manually:
#
#   Hetzner Cloud Console → Object Storage → Create Bucket
#   Name: worldview-tfstate  |  Location: nbg1  |  Visibility: Private
#
# This is documented here as a reminder; it is NOT a Terraform resource.
