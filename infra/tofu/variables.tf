variable "hcloud_token" {
  description = "Hetzner Cloud API token (Read/Write). Generate at: Project → Security → API Tokens"
  type        = string
  sensitive   = true
}

variable "region" {
  description = "Hetzner Cloud datacenter location"
  type        = string
  default     = "fsn1"  # fsn1 validated 2026-07-07 (nbg1 lacked cx53 capacity); alts: nbg1, hel1
}

variable "cp_type" {
  description = "Server type for the control-plane node"
  type        = string
  # FIX 2026-07-07: cx32/cx42/cx52 do NOT exist in the Hetzner API; the current Intel
  # shared line is cx23/cx33/cx43/cx53. cx33 = 4 vCPU / 8 GB (same as intended cx32).
  default     = "cx33"  # 4 vCPU, 8 GB RAM — sufficient for k3s control-plane
}

variable "worker1_type" {
  description = "Server type for worker-1 (stateful: Postgres, Kafka, MinIO, GLiNER)"
  type        = string
  default     = "cx53"  # 16 vCPU, 32 GB RAM (was cx52 — nonexistent)
}

variable "worker2_type" {
  description = "Server type for worker-2 (stateless: 10 app services)"
  type        = string
  default     = "cx43"  # 8 vCPU, 16 GB RAM (was cx42 — nonexistent)
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
