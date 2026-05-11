terraform {
  required_version = ">= 1.6"
  required_providers {
    zitadel = {
      source  = "zitadel/zitadel"
      version = "~> 1.0"
    }
  }
}

provider "zitadel" {
  domain           = var.zitadel_domain
  insecure         = false
  port             = "443"
  jwt_profile_file = var.zitadel_service_account_key_file
}

# ── Project ───────────────────────────────────────────────────────────────────

resource "zitadel_project" "worldview" {
  name   = "worldview"
  org_id = var.zitadel_org_id

  project_role_assertion  = false
  project_role_check      = false
  has_project_check       = false
  private_labeling_setting = "PRIVATE_LABELING_SETTING_UNSPECIFIED"
}

# ── Web Application (PKCE — no client secret) ─────────────────────────────────

resource "zitadel_application_oidc" "worldview_web" {
  project_id = zitadel_project.worldview.id
  org_id     = var.zitadel_org_id
  name       = "worldview-web"

  # PKCE flow — public client, no client secret
  auth_method_type = "OIDC_AUTH_METHOD_TYPE_NONE"
  response_types   = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types      = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]

  redirect_uris           = var.redirect_uris
  post_logout_redirect_uris = [var.frontend_url]

  # RS256 JWT access tokens
  access_token_type             = "OIDC_TOKEN_TYPE_JWT"
  id_token_userinfo_assertion   = true

  clock_skew = "1s"
  dev_mode   = var.dev_mode
}
