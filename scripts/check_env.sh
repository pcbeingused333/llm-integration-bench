#!/bin/sh
# Report what the harness needs and whether it is present. Installs nothing.
ok=1
check() {  # name, command, minimum note
  if command -v "$2" >/dev/null 2>&1; then
    printf '  ok       %-8s %s\n' "$1" "$($2 $3 2>&1 | head -1)"
  else
    printf '  MISSING  %-8s %s\n' "$1" "$4"; ok=0
  fi
}
echo "Toolchains:"
check git     git     --version  "sudo apt install -y git"
check python3 python3 --version  "sudo apt install -y python3 python3-venv"
check gcc     gcc     --version  "sudo apt install -y build-essential  (cgo needs it)"
check go      go      version    "sudo apt install -y golang-go  (1.21 or newer; older repos pull their own toolchain)"
check uv      uv      --version  "see docs/RUNNING.md, step 2"
check node    node    --version  "see docs/RUNNING.md, step 3 (22 or newer)"
check npm     npm     --version  "comes with node"
check pnpm    pnpm    --version  "npm install -g pnpm"
echo
echo "Disk and memory:"
df -h "${1:-.}" | tail -1 | awk '{printf "  free disk here: %s (need at least 60G)\n", $4}'
awk '/MemTotal/ {printf "  memory: %.0f GB (need 8 or more for 4 workers)\n", $2/1048576}' /proc/meminfo
echo "  cpu cores: $(nproc)"
[ "$ok" = 1 ] && echo && echo "All toolchains present." || { echo; echo "Install what is MISSING, then run this again."; exit 1; }
