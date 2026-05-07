#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/skills"
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
TARGET_DIR="$CODEX_HOME_DIR/skills"

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "No repo-local skills directory found: $SOURCE_DIR" >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"

for skill_dir in "$SOURCE_DIR"/*; do
  [[ -d "$skill_dir" ]] || continue
  skill_name="$(basename "$skill_dir")"
  if [[ ! -f "$skill_dir/SKILL.md" ]]; then
    echo "Skipping $skill_name: missing SKILL.md" >&2
    continue
  fi
  rm -rf "$TARGET_DIR/$skill_name"
  cp -R "$skill_dir" "$TARGET_DIR/$skill_name"
  find "$TARGET_DIR/$skill_name" \( -name "__pycache__" -o -name ".pytest_cache" \) -type d -prune -exec rm -rf {} +
  find "$TARGET_DIR/$skill_name" -name "*.pyc" -type f -delete
  echo "Installed skill: $skill_name"
done

echo "Repo-local skills installed to $TARGET_DIR"
