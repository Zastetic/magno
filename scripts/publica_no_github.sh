#!/usr/bin/env bash
# Publica o Barbearia Magno no GitHub: confere a autenticação, cria o repositório privado,
# empurra o histórico e VERIFICA o que chegou do outro lado.
#
# Uso:  ./scripts/publica_no_github.sh [usuario/repositorio]
#
# Pré-requisito: gh autenticado (gh auth status tem que passar).
set -euo pipefail

REPO="${1:-Zastetic/magno}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

# 1. autenticação
if ! gh auth status >/dev/null 2>&1; then
  echo "ERRO: gh sem autenticação válida. Rode: gh auth login --with-token < arquivo-com-o-token" >&2
  exit 1
fi
echo "autenticado como: $(gh api user --jq .login)"

# 2. o repositório local precisa ter o que subir
git -C "$DIR" rev-parse --verify HEAD >/dev/null || { echo "ERRO: nada commitado" >&2; exit 1; }
if [ -n "$(git -C "$DIR" status --porcelain)" ]; then
  echo "AVISO: há alterações não commitadas:" >&2
  git -C "$DIR" status --short >&2
fi

# 3. criar o repositório (privado) apontando para esta pasta
if gh repo view "$REPO" >/dev/null 2>&1; then
  echo "repositório já existe: $REPO — só adicionando o remote"
  git -C "$DIR" remote get-url origin >/dev/null 2>&1 || \
    git -C "$DIR" remote add origin "https://github.com/$REPO.git"
else
  # sem -q: gh repo create não aceita --quiet
  gh repo create "$REPO" --private --source "$DIR" --remote origin --push
fi

# 4. empurrar (idempotente)
git -C "$DIR" push -u origin main

# 5. verificação de verdade: quem sou eu lá, o repo existe e quantos arquivos chegaram
echo "--- verificação ---"
gh repo view "$REPO" --json nameWithOwner,visibility,url,defaultBranchRef
echo -n "arquivos na árvore remota: "
gh api "repos/$REPO/git/trees/main?recursive=1" --jq '[.tree[] | select(.type=="blob")] | length'
echo -n "commits: "
gh api "repos/$REPO/commits?per_page=100" --jq 'length'
