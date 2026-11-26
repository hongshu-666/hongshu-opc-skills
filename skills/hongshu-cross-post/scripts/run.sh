#!/bin/sh
set -eu
base=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
versions="${HOME}/.workbuddy/binaries/node/versions"
if [ -f "$versions/current" ]; then
  version=$(tr -d '\r\n' < "$versions/current")
  case "$version" in ''|*[!a-zA-Z0-9._-]*|.*) ;; *) node_bin="$versions/$version/bin/node";; esac
fi
for candidate in "${node_bin:-}" "$(command -v node || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ] && "$candidate" -e 'const p=require("node:path"),fs=require("node:fs");process.exit(parseInt(process.versions.node)>=20 && fs.existsSync(p.resolve(p.dirname(process.execPath),"../lib/node_modules/npm/bin/npm-cli.js")) ? 0 : 1)'; then
    if [ "${1:-}" = env ] && [ "${2:-}" = status ]; then exec "$candidate" "$base/environment.js"; fi
    exec "$candidate" "$base/publish.js" "$@"
  fi
done
if [ "${1:-}" = env ] && [ "${2:-}" = status ]; then
  if [ -x "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] || [ -x "$HOME/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" ] || command -v google-chrome >/dev/null 2>&1; then echo '已发现 Chrome'; else echo '未找到正式版 Chrome，官网下载 https://www.google.cn/chrome/'; fi
fi
echo '需要带 npm 的 Node.js 20 或以上版本。安装官方 LTS 后继续。' >&2
exit 1
