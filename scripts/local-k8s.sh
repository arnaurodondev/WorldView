#!/usr/bin/env bash
# scripts/local-k8s.sh — Manage a local k3s cluster via k3d for pre-deployment validation.
#
# Prerequisites:
#   brew install k3d kubectl helm
#   helm plugin install https://github.com/jkroepke/helm-secrets
#
# Workflow:
#   1. Build images:    ./scripts/test-docker-builds.sh
#   2. Create cluster:  ./scripts/local-k8s.sh create
#   3. Deploy infra:    ./scripts/local-k8s.sh deploy-infra
#   4. Deploy service:  ./scripts/local-k8s.sh deploy-service api-gateway
#   5. Run tests:       ./scripts/local-k8s.sh run-smoke-tests
#   6. Tear down:       ./scripts/local-k8s.sh destroy
#
# The cluster uses k3d port mappings so:
#   HTTP  → localhost:8080
#   HTTPS → localhost:8443
#   You can test Traefik ingress without a domain using the Host header.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

CLUSTER_NAME="${K3D_CLUSTER:-worldview-local}"
IMAGE_TAG="${IMAGE_TAG:-test}"

# Check required tools
require_tool() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: $1 is not installed."
        echo "Install: $2"
        exit 1
    fi
}

set_kubeconfig() {
    export KUBECONFIG
    KUBECONFIG="$(k3d kubeconfig write "$CLUSTER_NAME" 2>/dev/null || true)"
    if [[ -z "$KUBECONFIG" ]]; then
        echo "ERROR: Cluster '$CLUSTER_NAME' not found. Run: $0 create"
        exit 1
    fi
}

cmd="${1:-help}"

case "$cmd" in

  # ─────────────────────────────────────────────────────────────────────────
  create)
    require_tool k3d "brew install k3d"
    require_tool kubectl "brew install kubectl"

    echo "Creating k3d cluster: $CLUSTER_NAME"
    k3d cluster create "$CLUSTER_NAME" \
        --agents 2 \
        --k3s-arg "--disable=traefik@server:0" \
        --k3s-arg "--disable=servicelb@server:0" \
        --k3s-arg "--disable=local-storage@server:0" \
        --port "8080:80@loadbalancer" \
        --port "8443:443@loadbalancer" \
        --port "8081:8081@loadbalancer" \
        --wait

    echo ""
    echo "Cluster ready. Export kubeconfig:"
    echo "  export KUBECONFIG=\$(k3d kubeconfig write $CLUSTER_NAME)"
    echo ""
    echo "Next steps:"
    echo "  $0 deploy-infra    — install cert-manager, Traefik, Postgres, Kafka"
    echo "  $0 deploy-service <name>  — deploy a worldview service"
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  destroy)
    require_tool k3d "brew install k3d"
    echo "Destroying cluster: $CLUSTER_NAME"
    k3d cluster delete "$CLUSTER_NAME"
    echo "Done."
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  deploy-infra)
    require_tool helm "brew install helm"
    set_kubeconfig

    echo "=== Creating namespaces ==="
    for ns in traefik cert-manager infra worldview monitoring argocd; do
        kubectl create namespace "$ns" 2>/dev/null || echo "  namespace $ns already exists"
    done

    echo ""
    echo "=== Installing cert-manager (for TLS) ==="
    helm repo add jetstack https://charts.jetstack.io 2>/dev/null || true
    helm repo update
    helm upgrade --install cert-manager jetstack/cert-manager \
        -n cert-manager \
        --version v1.17.2 \
        --set installCRDs=true \
        --wait --timeout 120s

    # Create self-signed ClusterIssuer for local testing
    kubectl apply -f - <<'EOF'
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: selfsigned
spec:
  selfSigned: {}
EOF

    echo ""
    echo "=== Installing Traefik (ingress) ==="
    helm repo add traefik https://traefik.github.io/charts 2>/dev/null || true
    helm repo update
    helm upgrade --install traefik traefik/traefik \
        -n traefik \
        --version 34.4.1 \
        --set service.type=LoadBalancer \
        --set ports.web.port=80 \
        --set "ports.websecure.port=443" \
        --set ingressClass.enabled=true \
        --set ingressClass.isDefaultClass=true \
        --wait --timeout 120s

    echo ""
    echo "=== Installing Valkey (Redis-compatible cache) ==="
    helm repo add bitnami https://charts.bitnami.com/bitnami 2>/dev/null || true
    helm repo update
    helm upgrade --install valkey bitnami/valkey \
        -n infra \
        --version 3.0.10 \
        --set auth.enabled=false \
        --set persistence.enabled=false \
        --wait --timeout 120s

    echo ""
    echo "Infrastructure deployed successfully."
    echo ""
    echo "Note: Postgres, Kafka, MinIO require their custom images."
    echo "To deploy a stateful stack, use a full Docker Compose run instead."
    echo "The local k8s cluster is best for testing app service Helm charts + ingress."
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  import-image)
    require_tool k3d "brew install k3d"
    svc="${2:-}"
    if [[ -z "$svc" ]]; then
        echo "Usage: $0 import-image <service-name>"
        exit 1
    fi

    echo "Importing worldview-$svc:$IMAGE_TAG into cluster $CLUSTER_NAME..."
    k3d image import "worldview-$svc:$IMAGE_TAG" -c "$CLUSTER_NAME"
    echo "Done."
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  deploy-service)
    require_tool helm "brew install helm"
    set_kubeconfig
    svc="${2:-}"

    if [[ -z "$svc" ]]; then
        echo "Usage: $0 deploy-service <service-name>"
        echo "Available services:"
        ls "$ROOT_DIR/infra/helm/values/" | sed 's/.yaml//' | sed 's/^/  /'
        exit 1
    fi

    values_file="$ROOT_DIR/infra/helm/values/$svc.yaml"
    if [[ ! -f "$values_file" ]]; then
        echo "ERROR: No values file at $values_file"
        exit 1
    fi

    # Import local image into cluster
    echo "Importing image worldview-$svc:$IMAGE_TAG into cluster..."
    k3d image import "worldview-$svc:$IMAGE_TAG" -c "$CLUSTER_NAME" 2>/dev/null || \
        echo "  WARN: Image import failed — ensure you ran ./scripts/test-docker-builds.sh first"

    echo "Deploying $svc..."
    helm upgrade --install "$svc" "$ROOT_DIR/infra/helm/worldview-service" \
        -f "$values_file" \
        --set "image.repository=worldview-$svc" \
        --set "image.tag=$IMAGE_TAG" \
        --set "image.pullPolicy=Never" \
        -n worldview \
        --wait --timeout 90s \
        || { echo "FAIL: $svc deployment failed — check: kubectl -n worldview describe pod"; exit 1; }

    echo ""
    echo "=== $svc deployed ==="
    kubectl -n worldview get pods -l "app.kubernetes.io/name=$svc"
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  test-ingress)
    set_kubeconfig
    echo "Testing Traefik ingress with self-signed TLS..."

    # Create a minimal test deployment + ingress
    kubectl apply -f - <<'EOF' -n worldview
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ingress-test
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ingress-test
  template:
    metadata:
      labels:
        app: ingress-test
    spec:
      containers:
        - name: echo
          image: mendhak/http-https-echo:34
          ports:
            - containerPort: 8080
---
apiVersion: v1
kind: Service
metadata:
  name: ingress-test
spec:
  selector:
    app: ingress-test
  ports:
    - port: 8080
      targetPort: 8080
---
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ingress-test
  annotations:
    cert-manager.io/cluster-issuer: selfsigned
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - test.localhost
      secretName: ingress-test-tls
  rules:
    - host: test.localhost
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: ingress-test
                port:
                  number: 8080
EOF

    echo "Waiting for pod..."
    kubectl -n worldview rollout status deployment/ingress-test --timeout=60s

    echo ""
    echo "Test ingress:"
    echo "  curl -k -H 'Host: test.localhost' https://localhost:8443/"
    echo "  curl -H 'Host: test.localhost' http://localhost:8080/"
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  run-smoke-tests)
    echo "Running Kubernetes smoke tests..."

    # Run the deployment readiness tests against port-forwarded services
    python3 -m pytest \
        "$ROOT_DIR/tests/e2e/test_deployment_readiness.py" \
        -v \
        --tb=short \
        -m "e2e" \
        2>&1 || true
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  validate-helm)
    require_tool helm "brew install helm"
    echo "=== Helm chart validation ==="

    echo "Linting worldview-service chart..."
    helm lint "$ROOT_DIR/infra/helm/worldview-service"

    if [[ ! -d "$ROOT_DIR/infra/helm/values" ]]; then
        echo "No values directory yet — skipping per-service render"
        exit 0
    fi

    echo ""
    echo "Rendering per-service values..."
    FAIL=0
    for values_file in "$ROOT_DIR"/infra/helm/values/*.yaml; do
        svc=$(basename "$values_file" .yaml)
        if helm template "$svc" "$ROOT_DIR/infra/helm/worldview-service" \
               -f "$values_file" \
               --set "image.tag=test" \
               > /dev/null 2>&1; then
            echo "  OK: $svc"
        else
            echo "  FAIL: $svc"
            helm template "$svc" "$ROOT_DIR/infra/helm/worldview-service" \
                -f "$values_file" \
                --set "image.tag=test"
            ((FAIL++)) || true
        fi
    done

    [[ $FAIL -eq 0 ]] || exit 1
    echo "All Helm validations PASSED."
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  validate-manifests)
    echo "=== Kubernetes manifest validation ==="

    if ! command -v kubeconform &>/dev/null; then
        echo "kubeconform not installed — install with: brew install kubeconform"
        echo "Falling back to basic YAML syntax check..."

        python3 -c "
import yaml, pathlib, sys
failed = []
for f in sorted(pathlib.Path('infra/argocd').glob('**/*.yaml')):
    try:
        list(yaml.safe_load_all(f.read_text()))
        print(f'  OK: {f}')
    except yaml.YAMLError as e:
        print(f'  FAIL: {f}: {e}')
        failed.append(str(f))
for f in sorted(pathlib.Path('infra/k8s').glob('**/*.yaml')):
    if 'secrets' in str(f):
        continue  # skip SOPS-encrypted files
    try:
        list(yaml.safe_load_all(f.read_text()))
        print(f'  OK: {f}')
    except yaml.YAMLError as e:
        print(f'  FAIL: {f}: {e}')
        failed.append(str(f))
if failed:
    print(f'FAILED: {failed}')
    sys.exit(1)
"
        exit $?
    fi

    # Use kubeconform for strict k8s schema validation
    echo "Validating ArgoCD manifests..."
    find "$ROOT_DIR/infra/argocd" -name "*.yaml" | \
        kubeconform \
            -ignore-missing-schemas \
            -summary \
            -kubernetes-version 1.31.0 \
            -schema-location default \
            -schema-location 'https://raw.githubusercontent.com/datreeio/CRDs-catalog/main/{{.Group}}/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json'

    echo "Validating k8s manifests (excluding secrets)..."
    find "$ROOT_DIR/infra/k8s" -name "*.yaml" ! -path "*/secrets/*" | \
        kubeconform \
            -ignore-missing-schemas \
            -summary \
            -kubernetes-version 1.31.0

    echo "All manifest validations PASSED."
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  status)
    set_kubeconfig
    echo "=== Cluster nodes ==="
    kubectl get nodes -o wide
    echo ""
    echo "=== worldview namespace ==="
    kubectl get pods -n worldview 2>/dev/null || echo "  (namespace not found)"
    echo ""
    echo "=== infra namespace ==="
    kubectl get pods -n infra 2>/dev/null || echo "  (namespace not found)"
    echo ""
    echo "=== traefik namespace ==="
    kubectl get pods -n traefik 2>/dev/null || echo "  (namespace not found)"
    echo ""
    echo "=== cert-manager namespace ==="
    kubectl get pods -n cert-manager 2>/dev/null || echo "  (namespace not found)"
    ;;

  # ─────────────────────────────────────────────────────────────────────────
  help|*)
    cat <<EOF
Usage: $0 <command> [args]

Commands:
  create                     Create local k3d cluster (k3s in Docker)
  destroy                    Destroy the cluster
  deploy-infra               Install cert-manager + Traefik + Valkey
  import-image <service>     Import local Docker image into cluster
  deploy-service <service>   Deploy a service via Helm (uses local image)
  test-ingress               Deploy an echo server and test Traefik ingress + TLS
  run-smoke-tests            Run deployment readiness E2E tests
  validate-helm              Lint Helm chart + render all per-service values
  validate-manifests         Validate ArgoCD + k8s YAML with kubeconform
  status                     Show cluster pod status

Environment:
  K3D_CLUSTER=<name>   Cluster name (default: worldview-local)
  IMAGE_TAG=<tag>      Docker image tag (default: test)

Example workflow:
  ./scripts/test-docker-builds.sh
  ./scripts/local-k8s.sh create
  ./scripts/local-k8s.sh deploy-infra
  ./scripts/local-k8s.sh deploy-service api-gateway
  ./scripts/local-k8s.sh test-ingress
  ./scripts/local-k8s.sh status
  ./scripts/local-k8s.sh destroy
EOF
    ;;
esac
