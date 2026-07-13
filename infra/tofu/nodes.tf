resource "hcloud_ssh_key" "main" {
  name       = "worldview-key"
  public_key = var.ssh_public_key
}

# ── Cloud-init templates ──────────────────────────────────────────────────────
# The control-plane no longer depends on a floating IP (removed — Traefik's
# LoadBalancer Service is provisioned at runtime by the Hetzner CCM, see ip.tf
# history / B16). The API-server TLS SAN and kubeconfig rewrite now use the
# node's own public IP, fetched from the Hetzner metadata service at boot.
#
# Each worker gets its own rendered cloud-init carrying a distinct `node_role`
# so the k3s agent joins with `--node-label node-role=<role>`. Without this
# label every scheduled pod (which nodeSelects node-role: stateful|stateless)
# stays Pending forever (B4 — the guaranteed all-Pending failure).
locals {
  cp_user_data = templatefile("${path.module}/cloud-init/cp.yml", {
    k3s_token = var.k3s_token
    domain    = var.domain
  })

  # Worker-1 = stateful (Postgres, Kafka, MinIO, GLiNER, Valkey)
  worker1_user_data = templatefile("${path.module}/cloud-init/worker.yml", {
    k3s_token     = var.k3s_token
    cp_private_ip = "10.0.1.10"
    node_role     = "stateful"
  })

  # Worker-2 = stateless (S1–S10 app services)
  worker2_user_data = templatefile("${path.module}/cloud-init/worker.yml", {
    k3s_token     = var.k3s_token
    cp_private_ip = "10.0.1.10"
    node_role     = "stateless"
  })
}

# ── Control-plane node ────────────────────────────────────────────────────────
resource "hcloud_server" "cp" {
  name         = "worldview-cp-1"
  server_type  = var.cp_type
  image        = "ubuntu-24.04"
  location     = var.region
  ssh_keys     = [hcloud_ssh_key.main.id]
  user_data    = local.cp_user_data
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_network_subnet.main]

  lifecycle {
    # Prevent accidental recreation — that would destroy etcd state
    prevent_destroy = true
  }
}

resource "hcloud_server_network" "cp" {
  server_id  = hcloud_server.cp.id
  network_id = hcloud_network.main.id
  ip         = "10.0.1.10"
}

# ── Worker-1: stateful services (Postgres, Kafka, MinIO, GLiNER) ─────
resource "hcloud_server" "worker1" {
  name         = "worldview-worker-1"
  server_type  = var.worker1_type
  image        = "ubuntu-24.04"
  location     = var.region
  ssh_keys     = [hcloud_ssh_key.main.id]
  user_data    = local.worker1_user_data
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_server.cp, hcloud_server_network.cp]
}

resource "hcloud_server_network" "worker1" {
  server_id  = hcloud_server.worker1.id
  network_id = hcloud_network.main.id
  ip         = "10.0.1.11"
}

# ── Worker-2: stateless services (S1–S10 app services) ───────────────────────
resource "hcloud_server" "worker2" {
  name         = "worldview-worker-2"
  server_type  = var.worker2_type
  image        = "ubuntu-24.04"
  location     = var.region
  ssh_keys     = [hcloud_ssh_key.main.id]
  user_data    = local.worker2_user_data
  firewall_ids = [hcloud_firewall.main.id]
  depends_on   = [hcloud_server.cp, hcloud_server_network.cp]
}

resource "hcloud_server_network" "worker2" {
  server_id  = hcloud_server.worker2.id
  network_id = hcloud_network.main.id
  ip         = "10.0.1.12"
}
