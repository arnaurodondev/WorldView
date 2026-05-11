# Private network for pod-to-pod and node-to-node traffic
# All cluster internal communication stays on this private network
resource "hcloud_network" "main" {
  name     = "worldview-net"
  ip_range = "10.0.0.0/8"
}

resource "hcloud_network_subnet" "main" {
  network_id   = hcloud_network.main.id
  type         = "cloud"
  network_zone = "eu-central"
  ip_range     = "10.0.1.0/24"
}
