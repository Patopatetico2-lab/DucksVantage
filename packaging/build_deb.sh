#!/usr/bin/env bash
# Gera o pacote .deb nativo do DucksVantage em dist/ducksvantage_<versao>_all.deb
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VERSION="${1:-$(sed -nE 's/^APP_VERSION = "([^"]+)"/\1/p' core/mixins/extras.py | head -n1)}"
if [ -z "$VERSION" ]; then
    echo "[ERRO] Não foi possível determinar APP_VERSION em core/mixins/extras.py" >&2
    exit 1
fi

if ! command -v dpkg-deb >/dev/null 2>&1; then
    echo "[ERRO] dpkg-deb não encontrado. Instale o pacote 'dpkg' para gerar .deb." >&2
    exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

STAGE="$WORK_DIR/ducksvantage_${VERSION}_all"
mkdir -p \
    "$STAGE/DEBIAN" \
    "$STAGE/opt/ducksvantage" \
    "$STAGE/usr/bin" \
    "$STAGE/usr/share/applications" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps" \
    "$STAGE/etc/udev/rules.d"

cp -r main.py ui_main.py test_backend.py setup_udev.sh uninstall.sh styles.qss core ui assets packaging plasmoid "$STAGE/opt/ducksvantage/"
find "$STAGE/opt/ducksvantage" -name "__pycache__" -prune -exec rm -rf {} +
find "$STAGE/opt/ducksvantage" -name "*.pyc" -delete
chmod -R a+rX "$STAGE/opt/ducksvantage"
chmod 0755 "$STAGE/opt/ducksvantage/main.py" "$STAGE/opt/ducksvantage/setup_udev.sh" "$STAGE/opt/ducksvantage/uninstall.sh"

cat << 'EOF' > "$STAGE/usr/bin/ducksvantage"
#!/usr/bin/env bash
cd /opt/ducksvantage
exec python3 /opt/ducksvantage/main.py "$@"
EOF
chmod 0755 "$STAGE/usr/bin/ducksvantage"

install -Dm644 assets/app_icon.svg "$STAGE/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg"
install -Dm644 packaging/ducksvantage.desktop "$STAGE/usr/share/applications/ducksvantage.desktop"
install -Dm644 packaging/99-ducksvantage.rules "$STAGE/etc/udev/rules.d/99-ducksvantage.rules"

sed "s/@VERSION@/${VERSION}/g" packaging/debian/control.in > "$STAGE/DEBIAN/control"
chmod 0644 "$STAGE/DEBIAN/control"
install -Dm755 packaging/debian/postinst "$STAGE/DEBIAN/postinst"
install -Dm755 packaging/debian/postrm "$STAGE/DEBIAN/postrm"

mkdir -p dist
OUT_DEB="dist/ducksvantage_${VERSION}_all.deb"

if dpkg-deb --help 2>&1 | grep -q -- '--root-owner-group'; then
    dpkg-deb --root-owner-group --build "$STAGE" "$OUT_DEB"
else
    dpkg-deb --build "$STAGE" "$OUT_DEB"
fi

echo "[OK] Pacote .deb gerado em: $OUT_DEB"
