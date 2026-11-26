#!/usr/bin/env bash
# Gera o pacote portátil DucksVantage-<versao>-x86_64.AppImage em dist/
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

VERSION="${1:-$(sed -nE 's/^APP_VERSION = "([^"]+)"/\1/p' core/mixins/extras.py | head -n1)}"
if [ -z "$VERSION" ]; then
    echo "[ERRO] Não foi possível determinar APP_VERSION em core/mixins/extras.py" >&2
    exit 1
fi

if ! command -v pyinstaller >/dev/null 2>&1 && ! python3 -m PyInstaller --version >/dev/null 2>&1; then
    echo "[ERRO] PyInstaller não encontrado. Instale com: pip install pyinstaller" >&2
    exit 1
fi

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

DIST_TMP="$WORK_DIR/pyi-dist"
BUILD_TMP="$WORK_DIR/pyi-build"
SPEC_TMP="$WORK_DIR/pyi-spec"

python3 -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --name ducksvantage \
    --paths "$REPO_ROOT" \
    --distpath "$DIST_TMP" \
    --workpath "$BUILD_TMP" \
    --specpath "$SPEC_TMP" \
    --add-data "$REPO_ROOT/styles.qss:." \
    --add-data "$REPO_ROOT/assets:assets" \
    --add-data "$REPO_ROOT/packaging:packaging" \
    --add-data "$REPO_ROOT/plasmoid:plasmoid" \
    --collect-submodules core \
    --collect-submodules ui \
    --hidden-import pynvml \
    --hidden-import test_backend \
    --hidden-import PyQt6.QtSvg \
    --hidden-import PyQt6.QtDBus \
    "$REPO_ROOT/main.py"

APPDIR="$WORK_DIR/AppDir"
mkdir -p \
    "$APPDIR/usr/lib" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps"

cp -a "$DIST_TMP/ducksvantage" "$APPDIR/usr/lib/ducksvantage"

cat << 'EOF' > "$APPDIR/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/lib/ducksvantage/ducksvantage" "$@"
EOF
chmod 0755 "$APPDIR/AppRun"

sed -e 's|^Exec=.*|Exec=ducksvantage|' \
    -e 's|^Icon=.*|Icon=ducksvantage|' \
    packaging/ducksvantage.desktop > "$APPDIR/ducksvantage.desktop"
cp "$APPDIR/ducksvantage.desktop" "$APPDIR/usr/share/applications/ducksvantage.desktop"
cp assets/app_icon.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/ducksvantage.svg"

if command -v rsvg-convert >/dev/null 2>&1; then
    rsvg-convert -w 256 -h 256 assets/app_icon.svg -o "$APPDIR/ducksvantage.png"
elif command -v convert >/dev/null 2>&1; then
    convert -background none -resize 256x256 assets/app_icon.svg "$APPDIR/ducksvantage.png"
elif command -v inkscape >/dev/null 2>&1; then
    inkscape assets/app_icon.svg -w 256 -h 256 -o "$APPDIR/ducksvantage.png"
else
    echo "[ERRO] Instale 'librsvg2-bin' (rsvg-convert), ImageMagick ou Inkscape para converter o ícone SVG do AppImage." >&2
    exit 1
fi
ln -sf ducksvantage.png "$APPDIR/.DirIcon"

APPIMAGETOOL="${APPIMAGETOOL_PATH:-/tmp/appimagetool-x86_64.AppImage}"
if [ ! -x "$APPIMAGETOOL" ]; then
    echo "[INFO] Baixando appimagetool-x86_64.AppImage..."
    curl -fsSL \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage" \
        -o "$APPIMAGETOOL"
    chmod 0755 "$APPIMAGETOOL"
fi

mkdir -p dist
OUT_FILE="dist/DucksVantage-${VERSION}-x86_64.AppImage"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$APPIMAGETOOL" "$APPDIR" "$OUT_FILE"
chmod 0755 "$OUT_FILE"

APPIMAGE_EXTRACT_AND_RUN=1 "$OUT_FILE" --help >/dev/null
echo "[OK] AppImage gerado em: $OUT_FILE"
