# Floating IP — static IP for Traefik LoadBalancer Service
# The Hetzner Cloud Controller Manager (hcloud-ccm) assigns this IP to
# the LoadBalancer Service created by Traefik.
#
# NOTE: The floating IP is assigned to cp-1 by OpenTofu. The hcloud-ccm
# then manages reassignment if the node changes or fails.
resource "hcloud_floating_ip" "main" {
  type          = "ipv4"
  home_location = var.region
  description   = "worldview ingress — Traefik LoadBalancer"

  lifecycle {
    prevent_destroy = true  # losing the IP breaks DNS; must be intentional
  }
}

resource "hcloud_floating_ip_assignment" "main" {
  floating_ip_id = hcloud_floating_ip.main.id
  server_id      = hcloud_server.cp.id
}
