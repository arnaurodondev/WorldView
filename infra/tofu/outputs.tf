output "cp_ip" {
  description = "Control-plane public IP — use for kubectl and SSH"
  value       = hcloud_server.cp.ipv4_address
}

output "worker1_ip" {
  description = "Worker-1 public IP (stateful services)"
  value       = hcloud_server.worker1.ipv4_address
}

output "worker2_ip" {
  description = "Worker-2 public IP (stateless services)"
  value       = hcloud_server.worker2.ipv4_address
}

output "floating_ip" {
  description = "Floating IP — point your DNS A record here"
  value       = hcloud_floating_ip.main.ip_address
}

output "postgres_volume_device" {
  description = "Hetzner Volume Linux device path for Postgres"
  value       = hcloud_volume.postgres.linux_device
}

output "kafka_volume_device" {
  description = "Hetzner Volume Linux device path for Kafka"
  value       = hcloud_volume.kafka.linux_device
}

output "minio_volume_device" {
  description = "Hetzner Volume Linux device path for MinIO"
  value       = hcloud_volume.minio.linux_device
}

output "kubeconfig_command" {
  description = "Command to retrieve kubeconfig from the control-plane node"
  value       = "ssh root@${hcloud_server.cp.ipv4_address} 'cat /tmp/kubeconfig' > ~/.kube/config-worldview"
}

output "ssh_cp_command" {
  description = "SSH to control-plane"
  value       = "ssh root@${hcloud_server.cp.ipv4_address}"
}
