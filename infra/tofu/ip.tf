# ── Public ingress IP — NOT managed by tofu (B16) ─────────────────────────────
#
# The floating-IP resource that used to live here has been REMOVED.
#
# Why: Traefik is deployed as a Kubernetes Service of type: LoadBalancer.
# The Hetzner Cloud Controller Manager (hcloud-ccm) watches that Service and
# provisions a *Hetzner Load Balancer* at runtime to front it. That LB — with
# its own public IP — is the platform's public ingress. A tofu-managed
# floating IP assigned to cp-1 was never wired to anything (Traefik does not
# bind it) and only created confusion in the DNS guidance.
#
# The ingress IP is therefore created at runtime by the CCM, not by tofu.
# After bootstrap, retrieve it with:
#
#   kubectl -n traefik get svc traefik \
#     -o jsonpath='{.status.loadBalancer.ingress[0].ip}'
#
# Point your DNS A record for ${domain} at that IP. See outputs.tf
# (ingress_ip_command) for the exact command.
