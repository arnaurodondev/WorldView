# Hetzner Cloud Firewall
# Policy: minimal open surface. Only ports 80, 443 are open to the internet.
# SSH and Kubernetes API are restricted to the developer IP.
# All internal cluster traffic is allowed via the private network CIDR.
resource "hcloud_firewall" "main" {
  name = "worldview-fw"

  # ── Inbound rules ──────────────────────────────────────────────────────────
  # HTTP — needed for Let's Encrypt HTTP-01 challenge (redirects to HTTPS)
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTP ingress (ACME challenge + redirect)"
  }

  # HTTPS — public API and Grafana
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTPS ingress"
  }

  # Kubernetes API — restricted to developer IP only
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "6443"
    source_ips = [var.developer_ip]
    description = "k3s API server — developer only"
  }

  # SSH — restricted to developer IP only
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = [var.developer_ip]
    description = "SSH — developer only"
  }

  # Internal cluster traffic — all TCP on the private network
  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "any"
    source_ips = ["10.0.0.0/8"]
    description = "Internal cluster TCP"
  }

  # Internal cluster traffic — all UDP on the private network (Flannel VXLAN)
  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "any"
    source_ips = ["10.0.0.0/8"]
    description = "Internal cluster UDP (Flannel)"
  }

  # ── Outbound rules ──────────────────────────────────────────────────────────
  # Allow all outbound — nodes need to pull images, reach Let's Encrypt, etc.
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
    description     = "All outbound TCP"
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "any"
    destination_ips = ["0.0.0.0/0", "::/0"]
    description     = "All outbound UDP"
  }
}
