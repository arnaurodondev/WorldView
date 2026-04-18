# Traefik: Masking WebSocket JWT Tokens from Access Logs

> **Status**: Research reference (2026-04-18)
> **Applies to**: Traefik v2.x / v3.x deployed via Helm in the worldview k3s cluster
> **Problem**: The alert WebSocket endpoint authenticates via `?token=eyJ...` in the URL.
> Traefik logs the full `RequestPath` (including query string), leaking short-lived JWTs into access logs.

---

## 1. The Problem

Browser WebSocket API (`new WebSocket(url)`) cannot set custom HTTP headers.
The worldview frontend therefore passes a 30-second short-lived JWT as a query parameter:

```
ws://api-gateway:8000/api/v1/alerts/stream?token=eyJhbGciOiJSUzI1NiIs...
```

The S9 endpoint `GET /v1/auth/ws-token` issues this token (see `services/api-gateway/src/api_gateway/routes/auth.py`).

Traefik's `RequestPath` access log field includes the full URI (path + query string).
This means every WebSocket connection logs the JWT in plaintext, which is a security concern even though the token has a 30-second TTL.

---

## 2. Traefik Native Access Log Field Configuration

Traefik access logs support per-field control via three modes: **keep**, **drop**, and **redact**.

### Available request fields (Traefik v3.x)

| Field             | Description                                              |
|-------------------|----------------------------------------------------------|
| `StartUTC`        | Request start time (UTC)                                 |
| `StartLocal`      | Request start time (local)                               |
| `Duration`        | Total processing time (ns)                               |
| `RouterName`      | Traefik router name                                      |
| `ServiceName`     | Traefik backend service name                             |
| `ServiceURL`      | Backend URL                                              |
| `ServiceAddr`     | Backend IP:port                                          |
| `ClientAddr`      | Remote address (IP:port)                                 |
| `ClientHost`      | Remote IP                                                |
| `RequestHost`     | HTTP Host header (no port)                               |
| `RequestPort`     | TCP port from Host                                       |
| `RequestMethod`   | HTTP method                                              |
| `RequestPath`     | URI path **including query string** (the problem field)  |
| `RequestProtocol` | HTTP version                                             |
| `RequestScheme`   | `http` or `https`                                        |
| `RequestLine`     | `RequestMethod` + `RequestPath` + `RequestProtocol`      |
| `OriginDuration`  | Backend response time (ns)                               |
| `OriginContentSize` | Backend Content-Length                                 |
| `OriginStatus`    | Backend HTTP status code                                 |

### YAML configuration (traefik.yml / Helm values)

```yaml
# Static configuration
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  fields:
    defaultMode: keep
    names:
      ClientUsername: drop
    headers:
      defaultMode: drop
      names:
        User-Agent: keep
        Content-Type: keep
        Authorization: redact   # Redact Bearer tokens in headers
        X-Internal-JWT: drop    # Never log internal JWT header
```

### Docker Compose labels equivalent

```yaml
labels:
  - "traefik.accesslog=true"
  - "traefik.accesslog.format=json"
  - "traefik.accesslog.fields.defaultmode=keep"
  - "traefik.accesslog.fields.headers.defaultmode=drop"
  - "traefik.accesslog.fields.headers.names.Authorization=redact"
  - "traefik.accesslog.fields.headers.names.X-Internal-JWT=drop"
```

### CLI flags equivalent

```bash
--accesslog=true
--accesslog.format=json
--accesslog.fields.defaultmode=keep
--accesslog.fields.headers.defaultmode=drop
--accesslog.fields.headers.names.Authorization=redact
--accesslog.fields.headers.names.X-Internal-JWT=drop
```

---

## 3. Core Limitation: No Native Query Parameter Redaction (pre-v3.3)

**Traefik does NOT natively support masking individual query parameters within the `RequestPath` field in v3.0 through v3.2.**

The `RequestPath` field contains the full URI including query string (e.g., `/api/v1/alerts/stream?token=eyJ...`).
The field-level control only allows you to keep, drop, or redact the **entire** `RequestPath` field -- not specific query parameters within it.

- Setting `RequestPath: drop` removes the path entirely from logs (unacceptable -- you lose all routing information).
- Setting `RequestPath: redact` replaces the entire value with "REDACTED" (also unacceptable -- same reason).
- There is no `RequestQueryString` or per-parameter filter.

This is tracked in two open GitHub issues:
- [traefik/traefik#8515](https://github.com/traefik/traefik/issues/8515) -- "Filter query parameters from access logs" (Oct 2021)
- [traefik/traefik#10735](https://github.com/traefik/traefik/issues/10735) -- "filter query params from logs" (May 2024, P2 enhancement)

---

## 4. New `RequestQuery` Field (Traefik v3.3+)

PR [traefik/traefik#11140](https://github.com/traefik/traefik/pull/11140) separates query parameters from `RequestPath` into a new **`RequestQuery`** access log field. This was introduced in the Traefik v3.3 release cycle.

With this change:
- `RequestPath` contains only the path (e.g., `/api/v1/alerts/stream`)
- `RequestQuery` contains only the query string (e.g., `token=eyJ...`)

### Recommended configuration (Traefik >= v3.3)

```yaml
# traefik.yml (static configuration)
accessLog:
  filePath: "/var/log/traefik/access.log"
  format: json
  fields:
    defaultMode: keep
    names:
      # Drop the query string entirely -- prevents JWT token leakage
      RequestQuery: drop
    headers:
      defaultMode: drop
      names:
        User-Agent: keep
        Content-Type: keep
        Authorization: redact
        X-Internal-JWT: drop
```

### Helm values override (worldview k3s deployment)

The project installs Traefik via Helm chart v34.4.1 (see `scripts/local-k8s.sh`).
Add the following to the Helm values:

```yaml
# infra/helm/values/traefik.yaml (or inline --set flags)
additionalArguments:
  - "--accesslog=true"
  - "--accesslog.format=json"
  - "--accesslog.fields.names.RequestQuery=drop"
  - "--accesslog.fields.headers.defaultmode=drop"
  - "--accesslog.fields.headers.names.User-Agent=keep"
  - "--accesslog.fields.headers.names.Authorization=redact"
  - "--accesslog.fields.headers.names.X-Internal-JWT=drop"
```

Or equivalently via the `logs` key in the Traefik Helm chart:

```yaml
logs:
  access:
    enabled: true
    format: json
    fields:
      general:
        defaultmode: keep
        names:
          RequestQuery: drop
      headers:
        defaultmode: drop
        names:
          User-Agent: keep
          Content-Type: keep
          Authorization: redact
          X-Internal-JWT: drop
```

---

## 5. Workarounds for Traefik < v3.3

If you are running a Traefik version that does not have the `RequestQuery` field, use one of these approaches (ordered by recommendation):

### Option A: Upgrade Traefik to >= v3.3 (Recommended)

The simplest solution. The worldview Helm chart already pins `traefik/traefik` chart v34.4.1 which ships Traefik v3.3+. Verify the actual Traefik image version and upgrade if needed.

### Option B: Traefik middleware plugin -- strip query parameters before backend

Use the community plugin [traefik-remove-query-parameters-by-regex](https://github.com/Thijmen/traefik-remove-query-parameters-by-regex) to strip the `token` parameter from the request URL *before* it reaches Traefik's access log writer.

```yaml
# Dynamic configuration (middleware)
http:
  middlewares:
    strip-ws-token:
      plugin:
        traefik-remove-query-parameters-by-regex:
          parameters:
            - "^token$"

  routers:
    alert-ws:
      rule: "PathPrefix(`/api/v1/alerts/stream`)"
      middlewares:
        - strip-ws-token
      service: alert-service
```

**Caveat**: Middleware plugins modify the *forwarded request*, not just the log entry.
The `token` query parameter would be stripped before reaching the backend service.
This means the backend would NOT receive the `?token=` parameter.
You would need to restructure token passing (e.g., the plugin can copy the token to a header before stripping it from the URL) or use a different plugin that only affects logging.

**Important**: Community plugins that access the Traefik access log writer directly are not well-supported. A Traefik community forum post confirms that accessing `accesslog.GetLogData` from middleware plugins is not possible.

### Option C: Post-processing log pipeline

Use a log shipper (Alloy/Fluentd/Vector) to redact tokens from the log stream before storage:

```alloy
// Grafana Alloy config — redact ?token= from Traefik access logs
loki.process "traefik_redact" {
  stage.regex {
    expression = "(?P<before>.*)token=eyJ[A-Za-z0-9_-]+\\.eyJ[A-Za-z0-9_-]+\\.[A-Za-z0-9_-]+(?P<after>.*)"
  }
  stage.template {
    source   = "before"
    template = "{{ .before }}token=REDACTED{{ .after }}"
  }
  forward_to = [loki.write.default.receiver]
}
```

The worldview stack already runs Grafana Alloy (`infra/alloy/config.alloy`) for log collection.
This approach:
- Does NOT modify the request to the backend (token still arrives at S10)
- Redacts the token from the persisted log
- Works with any Traefik version
- Adds processing overhead to the log pipeline

### Option D: Avoid query parameter entirely

Redesign the WebSocket auth flow to avoid passing tokens in the URL:
1. **Subprotocol header**: Pass the JWT via the `Sec-WebSocket-Protocol` header.
   The browser WebSocket API supports this: `new WebSocket(url, [token])`.
   The backend reads it from the protocol negotiation.
   **Caveat**: The token appears in the `Sec-WebSocket-Protocol` response header (visible in browser DevTools) and Traefik may log `Sec-WebSocket-Protocol` headers (controllable via `headers.names`).
2. **Cookie-based auth**: Set the JWT in an httpOnly cookie before opening the WebSocket.
   Cookies are automatically sent with WebSocket upgrade requests.
   **Caveat**: Requires careful CSRF protection and SameSite settings.
3. **First-message auth**: Connect without auth, then send the JWT as the first WebSocket message.
   The server validates and drops the connection if invalid.
   **Caveat**: Brief unauthenticated window; more complex server-side logic.

---

## 6. Recommended Approach for Worldview

**Primary**: Use `RequestQuery: drop` in Traefik access log config (Section 4). The Helm chart version (34.4.1) ships Traefik v3.3+ which should include the `RequestQuery` field.

**Secondary**: Add Alloy log redaction (Section 5, Option C) as defense-in-depth. Even with `RequestQuery: drop`, other log sources (application logs, load balancer logs) may still capture the URL.

**Tertiary**: Consider migrating to `Sec-WebSocket-Protocol` auth (Section 5, Option D) in a future wave. This eliminates the problem at the protocol level and is the cleanest long-term solution, but requires changes to both frontend (`apps/worldview-web/`) and backend (`services/alert/`).

### Implementation checklist

- [ ] Verify the Traefik image version deployed supports `RequestQuery` field (>= v3.3)
- [ ] Add `RequestQuery: drop` to Traefik Helm values (or `additionalArguments`)
- [ ] Add `Authorization: redact` and `X-Internal-JWT: drop` to header field config
- [ ] Add Alloy log redaction stage for `?token=` patterns as defense-in-depth
- [ ] Validate by checking access logs after a WebSocket connection: token should not appear

---

## 7. Existing Project Configuration

The worldview project currently:

- **Does NOT have a dedicated Traefik config file** (no `traefik.yml` or `traefik.toml`).
- **Installs Traefik via Helm** in `scripts/local-k8s.sh` using chart version 34.4.1 with minimal flags:
  ```bash
  helm upgrade --install traefik traefik/traefik \
      -n traefik \
      --version 34.4.1 \
      --set service.type=LoadBalancer \
      --set ports.web.port=80 \
      --set "ports.websecure.port=443" \
      --set ingressClass.enabled=true \
      --set ingressClass.isDefaultClass=true
  ```
- **Disables the built-in k3s Traefik** in cloud-init (`--disable traefik` in `infra/tofu/cloud-init/cp.yml`).
- **Runs Grafana Alloy** for log collection (`infra/alloy/config.alloy`).
- **No Helm values directory** exists yet at `infra/helm/values/`.

The Traefik Helm values should be added either as a values file or inline `--set` flags in `scripts/local-k8s.sh`.

---

## References

- [Traefik Access Logs Documentation (latest)](https://doc.traefik.io/traefik/observe/logs-and-access-logs/)
- [Traefik v3.5 Access Logs](https://doc.traefik.io/traefik/v3.5/observe/logs-and-access-logs/)
- [Traefik v3.4 Access Logs](https://doc.traefik.io/traefik/v3.4/observability/access-logs/)
- [Traefik Access Log Reference Config](https://doc.traefik.io/traefik/reference/install-configuration/observability/logs-and-accesslogs/)
- [GitHub Issue #8515: Filter query parameters from access logs](https://github.com/traefik/traefik/issues/8515)
- [GitHub Issue #10735: filter query params from logs](https://github.com/traefik/traefik/issues/10735)
- [GitHub PR #11140: Support filtering query params in the accesslog](https://github.com/traefik/traefik/pull/11140)
- [Traefik Plugin: Remove query parameters by regex](https://github.com/Thijmen/traefik-remove-query-parameters-by-regex)
- [Traefik Plugin Catalog: Query Parameter Modification](https://plugins.traefik.io/plugins/628c9f24ffc0cd18356a97bd/query-paramter-modification)
- [Traefik Community Forum: Redacting or Dropping Logged Headers](https://community.traefik.io/t/redacting-or-dropping-logged-headers/27919)
- [Traefik Community Forum: Accesslog modification from plugin middleware](https://community.traefik.io/t/accesslog-modification-from-plugin-middleware/20655)
