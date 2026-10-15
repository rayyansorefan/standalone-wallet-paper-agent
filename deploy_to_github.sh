#!/usr/bin/env bash
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")" && pwd)"
TARGET="https://github.com/rayyansorefan/standalone-wallet-paper-agent.git"
DIR="${HOME}/standalone-wallet-paper-agent"
if ! command -v git >/dev/null; then echo 'Git is required. Install Xcode command line tools or Git.' >&2; exit 1; fi
if ! command -v python3 >/dev/null; then echo 'Python 3 is required.' >&2; exit 1; fi
if [ ! -d "$DIR/.git" ]; then
  if [ -e "$DIR" ]; then echo "Refusing to overwrite existing non-Git folder: $DIR" >&2; exit 1; fi
  git clone "$TARGET" "$DIR"
fi
cd "$DIR"
if [ "$(git remote get-url origin)" != "$TARGET" ] && [ "$(git remote get-url origin)" != "https://github.com/rayyansorefan/standalone-wallet-paper-agent" ]; then
  echo 'Origin repository differs; refusing to modify.' >&2; exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo 'Working tree has uncommitted changes; refusing to overwrite. Commit or stash them first.' >&2; exit 1
fi
git checkout main
git pull --ff-only origin main
# Include dotfiles and .github workflow, exclude packaging script's source metadata.
cp -R "$SOURCE/agent" "$DIR/"
cp -R "$SOURCE/tests" "$DIR/"
cp -R "$SOURCE/docs" "$DIR/"
mkdir -p "$DIR/.github"
cp -R "$SOURCE/.github/workflows" "$DIR/.github/"
cp "$SOURCE/.gitignore" "$SOURCE/README.md" "$DIR/"
python3 -m unittest discover -s tests -v
git add README.md .gitignore agent tests docs .github/workflows
if git diff --cached --quiet; then
  echo 'No changed files to deploy.'
else
  git commit -m 'Add standalone paper-only wallet research and auto-refresh dashboard'
  git push origin main
fi
printf '\nDeployment commit: '
git rev-parse --short HEAD
printf 'Check GitHub Actions: https://github.com/rayyansorefan/standalone-wallet-paper-agent/actions\n'
