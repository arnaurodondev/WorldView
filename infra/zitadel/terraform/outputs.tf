output "project_id" {
  description = "Zitadel project ID for the worldview project"
  value       = zitadel_project.worldview.id
}

output "client_id" {
  description = "OIDC client ID — set as API_GATEWAY_OIDC_CLIENT_ID and API_GATEWAY_OIDC_AUDIENCE"
  value       = zitadel_application_oidc.worldview_web.client_id
}

output "issuer_url" {
  description = "OIDC issuer URL — set as API_GATEWAY_OIDC_ISSUER_URL"
  value       = "https://${var.zitadel_domain}"
}
