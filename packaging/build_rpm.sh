#!/usr/bin/env bash
# Gera o pacote .rpm (Fedora / Nobara / openSUSE) em dist/ducksvantage-<versao>-1.noarch.rpm
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VERSION="${1:-$(sed -nE 's/^APP_VERSION = "([^"]+)"/\1/p' core/mixins/extras.py | head -n1)}"
if [ -z "$VERSION" ]; then
    echo "[ERRO] Não foi possível determinar APP_VERSION em core/mixins/extras.py" >&2
    exit 1
fi

if ! command -v rpmbuild >/dev/null 2>&1; then
    echo "[ERRO] rpmbuild não encontrado. Instale o pacote 'rpm' / 'rpm-build'." >&2
    exit 1
fi

TOPDIR="$(mktemp -d)"
trap 'rm -rf "$TOPDIR"' EXIT

mkdir -p "$TOPDIR"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
STAGE_SRC="$TOPDIR/ducksvantage-${VERSION}"
mkdir -p "$STAGE_SRC"

cp -r main.py ui_main.py test_backend.py styles.qss setup_udev.sh uninstall.sh core ui assets packaging plasmoid "$STAGE_SRC/"
find "$STAGE_SRC" -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGE_SRC" -name "*.pyc" -delete

tar -czf "$TOPDIR/SOURCES/ducksvantage-${VERSION}.tar.gz" -C "$TOPDIR" "ducksvantage-${VERSION}"

rpmbuild \
    --define "_topdir $TOPDIR" \
    --define "_app_version $VERSION" \
    -bb packaging/ducksvantage.spec

mkdir -p dist
BUILT_RPM="$(find "$TOPDIR/RPMS" -name '*.rpm' | head -n1)"
if [ -z "$BUILT_RPM" ]; then
    echo "[ERRO] Nenhum .rpm gerado pelo rpmbuild." >&2
    exit 1
fi

OUT_RPM="dist/ducksvantage-${VERSION}-1.noarch.rpm"
cp "$BUILT_RPM" "$OUT_RPM"
echo "[OK] Pacote .rpm gerado em: $OUT_RPM"
