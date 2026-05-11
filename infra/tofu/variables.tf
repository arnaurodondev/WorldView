variable "hcloud_token" {
  description = "Hetzner Cloud API token (Read/Write). Generate at: Project → Security → API Tokens"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Hetzner Cloud datacenter location"
  type        = string
  default     = "nbg1"  # Nuremberg; alternatives: hel1 (Helsinki), ash (Ashburn)
}

variable "cp_type" {
  description = "Server type for the control-plane node"
  type        = string
  default     = "cx32"  # 4 vCPU, 8 GB RAM — sufficient for k3s control-plane
}

variable "worker1_type" {
  description = "Server type for worker-1 (stateful: Postgres, Kafka, MinIO, Ollama)"
  type        = string
  default     = "cx52"  # 16 vCPU, 32 GB RAM
}

variable "worker2_type" {
  description = "Server type for worker-2 (stateless: 10 app services)"
  type        = string
  default     = "cx42"  # 8 vCPU, 16 GB RAM
}

variable "ssh_public_key" {
  description = "SSH public key content (e.g. contents of ~/.ssh/id_ed25519.pub)"
  type        = string
}

variable "k3s_token" {
  description = "Shared secret for k3s cluster join. Generate with: openssl rand -hex 32"
  type        = string
  sensitive   = true
}

variable "developer_ip" {
  description = "Your public IP in CIDR notation for SSH and kubectl access. e.g. '203.0.113.42/32'"
  type        = string
  # Find your IP: curl -s https://api.ipify.org && echo
}

variable "domain" {
  description = "Production domain (e.g. worldview.example.com). Used in TLS cert SANs."
  type        = string
  default     = ""  # fill when domain is purchased
}
