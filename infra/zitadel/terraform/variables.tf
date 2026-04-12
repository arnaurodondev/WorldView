variable "zitadel_domain" {
  description = "Zitadel Cloud instance domain (e.g. worldview.zitadel.cloud)"
  type        = string
}

variable "zitadel_org_id" {
  description = "Zitadel organisation ID (numeric string from console)"
  type        = string
}

variable "zitadel_service_account_key_file" {
  description = "Path to Zitadel service account JSON key file for provider auth"
  type        = string
  default     = "zitadel-sa-key.json"
}

variable "redirect_uris" {
  description = "OAuth2 redirect URIs — include all environments (prod + staging)"
  type        = list(string)
  default     = ["https://app.example.com/callback", "http://localhost:5173/callback"]
}

variable "frontend_url" {
  description = "Frontend origin — used as post-logout redirect URI"
  type        = string
  default     = "https://app.example.com"
}

variable "dev_mode" {
  description = "Enable Zitadel dev mode (allows http redirect URIs in non-prod)"
  type        = bool
  default     = false
}
