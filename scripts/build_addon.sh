#!/usr/bin/env bash
# Build the in-game overlay addon (a Nexus addon DLL) from WSL/Linux and copy it to bin/addon/.
#
# Needs: rustup with the x86_64-pc-windows-msvc target, cargo-xwin, and clang-cl + lld-link
# (LLVM 18+). Set LLVM_BIN if they are not on PATH, e.g. LLVM_BIN=/usr/lib/llvm-21/bin.
# cargo-xwin downloads the MSVC CRT and Windows SDK on first use (Microsoft's license applies).
set -euo pipefail
cd "$(dirname "$0")/.."

export PATH="$HOME/.cargo/bin:$PATH"
if [[ -n "${LLVM_BIN:-}" ]]; then
    export PATH="$LLVM_BIN:$PATH"
    export LD_LIBRARY_PATH="${LLVM_LIB:-$LLVM_BIN/../lib}:${LD_LIBRARY_PATH:-}"
fi
command -v clang-cl >/dev/null || { echo "clang-cl not found (set LLVM_BIN)"; exit 1; }

cd addon
cargo xwin build --release --target x86_64-pc-windows-msvc "$@"
mkdir -p ../bin/addon
cp target/x86_64-pc-windows-msvc/release/WvWAnalyzer.dll ../bin/addon/WvWAnalyzer.dll
# The DLL embeds Inter; its license ships next to it (the installer bundles bin/addon).
cp assets/fonts/OFL.txt ../bin/addon/Inter-OFL.txt
echo "built bin/addon/WvWAnalyzer.dll"
