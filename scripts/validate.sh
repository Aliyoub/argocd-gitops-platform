#!/usr/bin/env bash
# Valide les manifestes du dépôt sans aucun accès au cluster.
# Exécuté à l'identique en local et dans GitHub Actions.
#
# Prérequis : kustomize, kubeconform, yamllint, curl, python3 avec PyYAML.
# Usage : scripts/validate.sh   (depuis n'importe quel répertoire du dépôt)
set -euo pipefail

KUBERNETES_VERSION="1.32.0"
BOOTSTRAP="argocd/bootstrap"
# Répertoires Kustomize rendus puis validés.
KUSTOMIZE_DIRS=("apps/podinfo/base" "argocd" "$BOOTSTRAP")
# Manifestes appliqués tels quels (hors Kustomize).
PLAIN_MANIFESTS=("argocd/root-app.yaml")
# Applications soumises aux règles de scripts/check-policies.py.
POLICY_DIRS=("apps/podinfo/base")

cd "$(git rev-parse --show-toplevel)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
failures=0

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '  ÉCHEC : %s\n' "$1"; failures=$((failures + 1)); }
# sha256sum sous Linux (CI), shasum sous macOS.
sha256() {
  if command -v sha256sum >/dev/null; then sha256sum; else shasum -a 256; fi | awk '{print $1}'
}

step "Outils"
for tool in kustomize kubeconform yamllint curl python3; do
  command -v "$tool" >/dev/null || { echo "outil manquant : $tool"; exit 2; }
done
python3 -c 'import yaml' 2>/dev/null || { echo "module Python manquant : PyYAML"; exit 2; }
echo "  kustomize $(kustomize version), kubeconform $(kubeconform -v), $(yamllint --version)"

step "yamllint"
yamllint --strict . || fail "yamllint"

step "Intégrité du manifeste Argo CD épinglé"
# L'URL et l'empreinte attendue sont lues dans argocd/bootstrap/kustomization.yaml.
url="$(grep -Eo 'https://raw\.githubusercontent\.com/[^ ]+/install\.yaml' "$BOOTSTRAP/kustomization.yaml")"
expected="$(grep -Eo 'SHA-256 du fichier : [0-9a-f]{64}' "$BOOTSTRAP/kustomization.yaml" | awk '{print $NF}')"
actual="$(curl -fsSL "$url" | sha256)" || actual="téléchargement impossible"
if [ -n "$expected" ] && [ "$actual" = "$expected" ]; then
  echo "  SHA-256 conforme : $actual"
else
  fail "SHA-256 du manifeste Argo CD : attendu $expected, obtenu $actual"
fi

step "Rendu Kustomize"
for dir in "${KUSTOMIZE_DIRS[@]}"; do
  out="$work/$(echo "$dir" | tr '/' '_').yaml"
  if kustomize build "$dir" > "$out"; then
    echo "  $dir : $(grep -c '^kind:' "$out") ressource(s)"
  else
    fail "kustomize build $dir"
  fi
done

step "Schémas des CRDs Argo CD (depuis le manifeste épinglé)"
python3 scripts/crd-schemas.py "$work/schemas" < "$work/$(echo "$BOOTSTRAP" | tr '/' '_').yaml" \
  || fail "génération des schémas"

step "kubeconform (Kubernetes $KUBERNETES_VERSION, mode strict)"
# Les objets CustomResourceDefinition eux-mêmes n'ont pas de schéma dans le
# catalogue par défaut : l'API server les valide à l'installation.
kubeconform -strict -summary -kubernetes-version "$KUBERNETES_VERSION" \
  -schema-location default \
  -schema-location "$work/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json" \
  -skip CustomResourceDefinition \
  "$work"/*.yaml "${PLAIN_MANIFESTS[@]}" || fail "kubeconform"

step "Règles de sécurité des applications"
for dir in "${POLICY_DIRS[@]}"; do
  echo "  $dir"
  python3 scripts/check-policies.py < "$work/$(echo "$dir" | tr '/' '_').yaml" || fail "règles : $dir"
done

if [ "$failures" -gt 0 ]; then
  printf '\nValidation échouée : %d contrôle(s) en erreur.\n' "$failures"
  exit 1
fi
printf '\nValidation réussie.\n'
