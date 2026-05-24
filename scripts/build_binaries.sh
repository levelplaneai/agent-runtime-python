#!/usr/bin/env bash
# Build the agent-runtime binary for all supported platforms and place them in agent_runtime/bin/.
# Run from the agent-runtime-python repo root.
# Requires Go to be installed and the agent-runtime Go source to be at ../agent-runtime.
set -euo pipefail

GO_SRC="../agent-runtime/cmd/agent-runtime"
OUT="agent_runtime/bin"

mkdir -p "$OUT"

for target in darwin/arm64 darwin/amd64 linux/amd64 linux/arm64 windows/amd64; do
  os="${target%/*}"
  arch="${target#*/}"
  suffix=""
  [[ "$os" == "windows" ]] && suffix=".exe"
  out_file="$OUT/agent-runtime-$os-$arch$suffix"
  echo "Building $out_file ..."
  GOOS="$os" GOARCH="$arch" go build -o "$out_file" "$GO_SRC"
done

chmod +x "$OUT"/agent-runtime-darwin-* "$OUT"/agent-runtime-linux-*
echo "Done. Binaries written to $OUT/"
