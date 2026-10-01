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
#   --diagnose       read-only status report (pods, ingress, TLS, firewall, logs)
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
    --diagnose) MODE="diagnose" ;;
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

if command -v kubectl >/dev/null 2>&1; then KUBECTL=(kubectl); else KUBECTL=(k3s kubectl); fi
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
k() { "${KUBECTL[@]}" "$@"; }

# Checks the site through Traefik (TLS included) from this host, without depending on DNS:
# the request goes to Traefik's ClusterIP, or to localhost if Traefik is installed elsewhere.
probe() {
  local ip
  ip=$(k -n kube-system get svc traefik -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
  curl -sS -o /dev/null -m 10 -w '%{http_code}' --resolve "${DOMAIN}:${2:-443}:${ip:-127.0.0.1}" "$1" 2>/dev/null || true
}

# ── Read-only report, for troubleshooting (no secrets are printed) ────────────
if [[ "$MODE" == "diagnose" ]]; then
  section() { echo; echo "${bold}── $* ──${reset}"; }
  section "Host"
  uname -srm; nproc; free -h 2>/dev/null | head -2; df -h / 2>/dev/null | tail -1
  section "Listening on 80/443"
  ss -ltnp 2>/dev/null | grep -E ':(80|443) ' || echo "nothing"
  section "Firewall (iptables INPUT / FORWARD)"
  iptables -S INPUT 2>/dev/null | head -20 || true
  iptables -S FORWARD 2>/dev/null | head -12 || true
  section "Cluster"
  k get nodes -o wide 2>&1 || true
  k get ingressclass 2>&1 || true
  k -n kube-system get pods -o wide 2>&1 | grep -Ei 'traefik|svclb|coredns|NAME' || true
  section "graphrag"
  k -n "$NAMESPACE" get pods,svc,ingress,pvc -o wide 2>&1 || true
  k -n "$NAMESPACE" get certificate,certificaterequest,order,challenge 2>&1 || true
  section "Argo CD"
  k -n argocd get applications -o wide 2>&1 || true
  k -n argocd get application graphrag -o jsonpath='{range .status.conditions[*]}{.type}: {.message}{"\n"}{end}' 2>/dev/null || true
  section "Recent warnings"
  k -n "$NAMESPACE" get events --field-selector type=Warning --sort-by=.lastTimestamp 2>&1 | tail -25 || true
  section "Logs: api"
  k -n "$NAMESPACE" logs deploy/graphrag-api --tail=40 2>&1 || true
  section "Logs: latest ingestion"
  k -n "$NAMESPACE" logs -l app.kubernetes.io/component=ingest --tail=40 --prefix 2>&1 | tail -40 || true
  section "HTTP checks through Traefik on this host"
  echo "http  → $(probe "http://${DOMAIN}/" 80)"
  echo "https → $(probe "https://${DOMAIN}/")  (000 = TLS not ready or route missing)"
  echo "api   → $(probe "https://${DOMAIN}/api/stats")"
  exit 0
fi

# ── 1. k3s ────────────────────────────────────────────────────────────────────
step "Kubernetes (k3s)"
if ! command -v k3s >/dev/null 2>&1 && ! command -v kubectl >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | sh -
  ok "k3s installed"
  if command -v kubectl >/dev/null 2>&1; then KUBECTL=(kubectl); else KUBECTL=(k3s kubectl); fi
fi
k wait --for=condition=Ready node --all --timeout=180s >/dev/null
ok "cluster ready: $(k get nodes -o jsonpath='{.items[*].metadata.name}') ($(k version -o json 2>/dev/null | grep -o '"gitVersion": *"[^"]*"' | tail -1 | cut -d'"' -f4))"
arch=$(k get nodes -o jsonpath='{.items[0].status.nodeInfo.architecture}')
ok "node architecture: $arch (images are published for amd64 and arm64)"
mem_mb=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if ((mem_mb < 3500)); then
  warn "only ${mem_mb} MB of RAM: Neo4j + API + web + Argo CD want ~3 GB (consider --local-build, which skips Argo CD)"
else
  ok "memory: ${mem_mb} MB"
fi
if k get ingressclass traefik >/dev/null 2>&1; then
  ok "ingress controller: Traefik"
else
  warn "no 'traefik' IngressClass found — this app's Ingresses and Middlewares target Traefik (the k3s default)"
fi

# Oracle Cloud (and some other) images ship iptables rules that reject everything
# except SSH: open HTTP/HTTPS and let pod traffic through, then persist the rules.
if command -v iptables >/dev/null 2>&1; then
  changed=""
  if iptables -S INPUT 2>/dev/null | grep -q -- '-j REJECT'; then
    for port in 80 443; do
      if ! iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null; then
        iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
        changed=1
      fi
    done
  fi
  if iptables -S FORWARD 2>/dev/null | grep -q -- '-j REJECT'; then
    for cidr in 10.42.0.0/16 10.43.0.0/16; do
      for dir in -s -d; do
        if ! iptables -C FORWARD "$dir" "$cidr" -j ACCEPT 2>/dev/null; then
          iptables -I FORWARD 1 "$dir" "$cidr" -j ACCEPT
          changed=1
        fi
      done
    done
  fi
  if [[ -n "$changed" ]]; then
    command -v netfilter-persistent >/dev/null 2>&1 && netfilter-persistent save >/dev/null 2>&1 || true
    ok "host firewall: opened 80/443 and pod forwarding (REJECT rules were present)"
  fi
fi
warn "cloud firewall: ports 80 and 443 must also be open to the internet (Oracle Cloud: VCN security list)"

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

# ── Verification ──────────────────────────────────────────────────────────────
step "Verification"
for _ in $(seq 1 36); do
  [[ "$(k -n "$NAMESPACE" get certificate graphrag-tls -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" == "True" ]] && break
  sleep 5
done
if [[ "$(k -n "$NAMESPACE" get certificate graphrag-tls -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" == "True" ]]; then
  ok "TLS certificate issued by Let's Encrypt"
else
  warn "TLS certificate not ready yet — Let's Encrypt must reach http://${DOMAIN}/.well-known/acme-challenge/ (DNS + port 80)"
  k -n "$NAMESPACE" get challenge -o custom-columns=DOMAIN:.spec.dnsName,STATE:.status.state,REASON:.status.reason 2>/dev/null | sed 's/^/    /' || true
fi
for _ in $(seq 1 30); do
  [[ "$(probe "https://${DOMAIN}/api/stats")" == "200" ]] && break
  sleep 10
done
web_code=$(probe "https://${DOMAIN}/")
api_code=$(probe "https://${DOMAIN}/api/stats")
if [[ "$web_code" == "200" && "$api_code" == "200" ]]; then
  ok "https://${DOMAIN} answers (web ${web_code}, api ${api_code})"
else
  warn "local check through Traefik: web ${web_code}, api ${api_code} — run this script with --diagnose for details"
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
