#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# One-shot, idempotent installer for graphrag.dorianlovichi.com on k3s.
#
#   curl -sfL https://raw.githubusercontent.com/LovichiDorian/GraphRag/main/deploy/scripts/install.sh \
#     | sudo GEMINI_API_KEY=xxxx bash
#
# What it does (each step is skipped when already done, so it is safe to re-run
# on a cluster that already hosts other apps):
#   1. installs k3s if missing (Traefik ingress + local-path storage included)
#   2. creates the `graphrag` namespace and the `graphrag-secrets` secret
#      (Gemini key, generated Neo4j password, optional GitHub token)
#   3. installs cert-manager + a Let's Encrypt ClusterIssuer if missing
#   4. GitOps mode (default): installs Argo CD if missing and registers the app —
#      from then on every push to main deploys itself.
#      Local mode (--local-build): builds both images on this machine, imports
#      them into k3s and applies the manifests directly (no registry needed).
#
# Options / environment:
#   GEMINI_API_KEY   Google AI Studio key (required on first install)
#   GITHUB_TOKEN     optional, raises GitHub API limits (public read-only scope)
#   ACME_EMAIL       Let's Encrypt account e-mail   (default: dorian@dorianlovichi.com)
#   GHCR_TOKEN       optional, read:packages token if the GHCR packages are private
#   ENV_FILE         file with KEY=value lines to load (used by the GitHub Action)
#   --local-build    build images locally instead of pulling them from GHCR
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/LovichiDorian/GraphRag.git}"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/LovichiDorian/GraphRag/main}"
BRANCH="${BRANCH:-main}"
NAMESPACE="graphrag"
DOMAIN="graphrag.dorianlovichi.com"
ACME_EMAIL="${ACME_EMAIL:-dorian@dorianlovichi.com}"
CERT_MANAGER_VERSION="v1.21.2"
ARGOCD_VERSION="v3.5.3"
MODE="gitops"

for arg in "$@"; do
  case "$arg" in
    --local-build) MODE="local" ;;
    -h | --help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if [[ -n "${ENV_FILE:-}" && -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck source=/dev/null
  . "$ENV_FILE"
  set +a
fi

bold=$'\033[1m'; green=$'\033[32m'; yellow=$'\033[33m'; red=$'\033[31m'; dim=$'\033[2m'; reset=$'\033[0m'
step() { echo; echo "${bold}▸ $*${reset}"; }
ok() { echo "  ${green}✓${reset} $*"; }
warn() { echo "  ${yellow}!${reset} $*"; }
die() { echo "  ${red}✗ $*${reset}" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (pipe into 'sudo bash')"

# ── 1. k3s ────────────────────────────────────────────────────────────────────
step "Kubernetes (k3s)"
if ! command -v k3s >/dev/null 2>&1 && ! command -v kubectl >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | sh -
  ok "k3s installed"
fi
if command -v kubectl >/dev/null 2>&1; then KUBECTL=(kubectl); else KUBECTL=(k3s kubectl); fi
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
k() { "${KUBECTL[@]}" "$@"; }
k wait --for=condition=Ready node --all --timeout=180s >/dev/null
ok "cluster ready: $(k get nodes -o jsonpath='{.items[*].metadata.name}') ($(k version -o json 2>/dev/null | grep -o '"gitVersion": *"[^"]*"' | tail -1 | cut -d'"' -f4))"
arch=$(k get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}')
ok "node architecture: $arch (images are published for amd64 and arm64)"

# ── 2. namespace + secrets ────────────────────────────────────────────────────
step "Namespace and secrets"
k get namespace "$NAMESPACE" >/dev/null 2>&1 || k create namespace "$NAMESPACE" >/dev/null
existing_key=""
existing_password=""
if k -n "$NAMESPACE" get secret graphrag-secrets >/dev/null 2>&1; then
  existing_key=$(k -n "$NAMESPACE" get secret graphrag-secrets -o jsonpath='{.data.GEMINI_API_KEY}' | base64 -d || true)
  existing_password=$(k -n "$NAMESPACE" get secret graphrag-secrets -o jsonpath='{.data.NEO4J_PASSWORD}' | base64 -d || true)
fi
GEMINI_API_KEY="${GEMINI_API_KEY:-$existing_key}"
if [[ -z "$GEMINI_API_KEY" ]]; then
  if [[ -t 0 ]]; then read -rsp "  Gemini API key: " GEMINI_API_KEY; echo; else die "GEMINI_API_KEY is required"; fi
fi
# Neo4j only reads its password on first boot: never rotate it implicitly.
NEO4J_PASSWORD="${existing_password:-$(head -c 32 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 32)}"
k -n "$NAMESPACE" create secret generic graphrag-secrets \
  --from-literal=GEMINI_API_KEY="$GEMINI_API_KEY" \
  --from-literal=NEO4J_PASSWORD="$NEO4J_PASSWORD" \
  --from-literal=NEO4J_AUTH="neo4j/$NEO4J_PASSWORD" \
  --from-literal=GITHUB_TOKEN="${GITHUB_TOKEN:-}" \
  --dry-run=client -o yaml | k apply -f - >/dev/null
ok "secret graphrag-secrets up to date (Neo4j password ${existing_password:+kept}${existing_password:-generated})"

# Images live on GHCR. Public packages need nothing; private ones need a token.
if [[ -n "${GHCR_TOKEN:-}" ]]; then
  k -n "$NAMESPACE" create secret docker-registry ghcr-pull --docker-server=ghcr.io \
    --docker-username="${GHCR_USER:-lovichidorian}" --docker-password="$GHCR_TOKEN" \
    --dry-run=client -o yaml | k apply -f - >/dev/null
  k -n "$NAMESPACE" patch serviceaccount default -p '{"imagePullSecrets":[{"name":"ghcr-pull"}]}' >/dev/null
  ok "GHCR pull secret configured"
elif [[ "$MODE" == "gitops" ]]; then
  token=$(curl -sf "https://ghcr.io/token?scope=repository:lovichidorian/graphrag-api:pull" | sed -n 's/.*"token":"\([^"]*\)".*/\1/p' || true)
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${token}" \
    -H 'Accept: application/vnd.oci.image.index.v1+json' \
    https://ghcr.io/v2/lovichidorian/graphrag-api/manifests/latest || true)
  if [[ "$code" == "200" ]]; then
    ok "images are publicly pullable from ghcr.io"
  else
    warn "ghcr.io/lovichidorian/graphrag-api is not pullable anonymously yet (HTTP $code)."
    warn "Make both packages public (GitHub → Packages → Package settings → Change visibility),"
    warn "or re-run with GHCR_TOKEN=<token with read:packages>, or use --local-build."
  fi
fi

# ── 3. TLS: cert-manager + Let's Encrypt ──────────────────────────────────────
step "TLS (cert-manager + Let's Encrypt)"
if ! k get crd clusterissuers.cert-manager.io >/dev/null 2>&1; then
  k apply -f "https://github.com/cert-manager/cert-manager/releases/download/${CERT_MANAGER_VERSION}/cert-manager.yaml" >/dev/null
  k -n cert-manager rollout status deploy/cert-manager-webhook --timeout=300s >/dev/null
  ok "cert-manager ${CERT_MANAGER_VERSION} installed"
else
  ok "cert-manager already installed"
fi
if ! k get clusterissuer letsencrypt-prod >/dev/null 2>&1; then
  for attempt in 1 2 3 4 5 6; do
    cat <<EOF | k apply -f - >/dev/null 2>&1 && break
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ${ACME_EMAIL}
    privateKeySecretRef:
      name: letsencrypt-prod-account
    solvers:
      - http01:
          ingress:
            ingressClassName: traefik
EOF
    sleep $((attempt * 5))
  done
  k get clusterissuer letsencrypt-prod >/dev/null 2>&1 || die "could not create the ClusterIssuer"
  ok "ClusterIssuer letsencrypt-prod created ($ACME_EMAIL)"
else
  ok "ClusterIssuer letsencrypt-prod already present (reused)"
fi

# ── 4a. GitOps with Argo CD ───────────────────────────────────────────────────
if [[ "$MODE" == "gitops" ]]; then
  step "GitOps (Argo CD)"
  if ! k get namespace argocd >/dev/null 2>&1; then
    k create namespace argocd >/dev/null
    k apply -n argocd --server-side --force-conflicts \
      -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml" >/dev/null
    ok "Argo CD ${ARGOCD_VERSION} installed"
  else
    ok "Argo CD already installed"
  fi
  for deployment in argocd-repo-server argocd-server; do
    k -n argocd rollout status "deploy/$deployment" --timeout=300s >/dev/null
  done
  k -n argocd rollout status statefulset/argocd-application-controller --timeout=300s >/dev/null
  if [[ -f "$(dirname "$0")/../argocd/application.yaml" ]]; then
    k apply -f "$(dirname "$0")/../argocd/application.yaml" >/dev/null
  else
    curl -sfL "$REPO_RAW/deploy/argocd/application.yaml" | k apply -f - >/dev/null
  fi
  ok "application 'graphrag' registered — Argo CD now syncs deploy/k8s/overlays/prod from $BRANCH"
  echo "  ${dim}waiting for the first sync (pulling images, starting Neo4j)…${reset}"
  for _ in $(seq 1 60); do
    status=$(k -n argocd get application graphrag -o jsonpath='{.status.sync.status}/{.status.health.status}' 2>/dev/null || true)
    [[ "$status" == "Synced/Healthy" ]] && break
    sleep 10
  done
  ok "argo status: ${status:-unknown}"
fi

# ── 4b. Local build (no registry) ─────────────────────────────────────────────
if [[ "$MODE" == "local" ]]; then
  step "Local build"
  command -v docker >/dev/null 2>&1 || die "docker is required for --local-build"
  workdir=$(mktemp -d)
  git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$workdir/repo" >/dev/null 2>&1
  cd "$workdir/repo"
  tag="local-$(git rev-parse --short HEAD)"
  docker build -f apps/api/Dockerfile -t "graphrag-api:$tag" .
  docker build -t "graphrag-web:$tag" apps/web
  docker save "graphrag-api:$tag" "graphrag-web:$tag" | k3s ctr images import - >/dev/null
  ok "images built and imported into k3s ($tag)"
  mkdir -p deploy/k8s/overlays/local
  cat >deploy/k8s/overlays/local/kustomization.yaml <<EOF
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources:
  - ../../base
images:
  - name: ghcr.io/lovichidorian/graphrag-api
    newName: docker.io/library/graphrag-api
    newTag: "$tag"
  - name: ghcr.io/lovichidorian/graphrag-web
    newName: docker.io/library/graphrag-web
    newTag: "$tag"
EOF
  k -n "$NAMESPACE" delete job graphrag-ingest-sync --ignore-not-found >/dev/null
  k apply -k deploy/k8s/overlays/local >/dev/null
  ok "manifests applied"
  k -n "$NAMESPACE" rollout status statefulset/graphrag-neo4j --timeout=600s >/dev/null
  k -n "$NAMESPACE" rollout status deploy/graphrag-api --timeout=300s >/dev/null
  k -n "$NAMESPACE" rollout status deploy/graphrag-web --timeout=300s >/dev/null
  cd /; rm -rf "$workdir"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
step "Done"
k -n "$NAMESPACE" get pods -o wide 2>/dev/null | sed 's/^/  /' || true
cat <<EOF

  ${bold}https://${DOMAIN}${reset}   (DNS A record → this server; the TLS certificate appears within ~2 min)

  Useful commands:
    kubectl -n ${NAMESPACE} get pods,ingress,certificate
    kubectl -n ${NAMESPACE} logs -f deploy/graphrag-api
    kubectl -n ${NAMESPACE} logs -l app.kubernetes.io/component=ingest --tail=100
    kubectl -n ${NAMESPACE} create job --from=cronjob/graphrag-ingest ingest-now     # rebuild the graph now
EOF
if [[ "$MODE" == "gitops" ]]; then
  cat <<EOF
    kubectl -n argocd get applications
    kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d   # Argo CD UI password
    kubectl -n argocd port-forward svc/argocd-server 8080:443                                          # then https://localhost:8080
EOF
fi
