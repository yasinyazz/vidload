# Maintainer: Yasin <yasinyazz>
pkgname=vidload
pkgver=1.0.0
pkgrel=1
pkgdesc="TUI video downloader powered by yt-dlp and Textual"
arch=('any')
url="https://github.com/yasinyazz/vidload"
license=('MIT')
depends=('python' 'python-pip' 'ffmpeg')
makedepends=()
source=("vidload.py"
        "vidload.desktop"
        "vidload.png")   # optional icon — drop a 256x256 PNG next to PKGBUILD
sha256sums=('SKIP' 'SKIP' 'SKIP')

prepare() {
    # nothing to extract — sources are plain files
    true
}

build() {
    true
}

package() {
    # install the script
    install -Dm755 "$srcdir/vidload.py" "$pkgdir/usr/bin/vidload"

    # install the .desktop entry
    install -Dm644 "$srcdir/vidload.desktop" \
        "$pkgdir/usr/share/applications/vidload.desktop"

    # install icon (optional — skip if file is missing)
    if [[ -f "$srcdir/vidload.png" ]]; then
        install -Dm644 "$srcdir/vidload.png" \
            "$pkgdir/usr/share/pixmaps/vidload.png"
    fi
}

# ── post-install helper ────────────────────────────────────────────
# Run `pip install textual yt-dlp --break-system-packages` after install
# or add python-textual and python-yt-dlp to `depends` if you have
# those in your repos / AUR.
