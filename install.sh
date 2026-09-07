#!/usr/bin/env bash
# ==============================================================================
# Decks - Native GNOME 45+ Desktop Installer
# Installs GTK4, Libadwaita, FSRS algorithm flashcards and creates desktop launcher
# ==============================================================================

set -e

echo "📦 Installing Decks (GTK4 + Libadwaita + FSRS)..."

# 1. Install System Packages
SUDO=""
if [ "$(id -u)" -ne 0 ] && command -v sudo &>/dev/null; then
    SUDO="sudo"
fi

if command -v apt-get &> /dev/null; then
    echo "Detected Debian / Ubuntu / Pop!_OS / Mint"
    $SUDO apt-get update -y || true
    $SUDO apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-graphene-1.0 python3-opengl python3-pip || true
elif command -v dnf &> /dev/null; then
    echo "Detected Fedora / RHEL"
    $SUDO dnf install -y python3-gobject gtk4 libadwaita graphene python3-pyopengl || true
elif command -v pacman &> /dev/null; then
    echo "Detected Arch Linux / Manjaro"
    $SUDO pacman -S --noconfirm python-gobject gtk4 libadwaita graphene python-opengl || true
else
    echo "⚠️ Unknown package manager. Please ensure PyGObject, GTK4, Libadwaita, Graphene, and PyOpenGL are installed."
fi

# 2. Python OpenGL accelerate (supports PEP 668 on modern distros)
pip install --user --break-system-packages PyOpenGL PyOpenGL_accelerate 2>/dev/null || \
pip install --user PyOpenGL PyOpenGL_accelerate 2>/dev/null || true

# Resolve directory where this script lives
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Standard XDG user directories
LOCAL_BIN="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"
ICONS_BASE="$HOME/.local/share/icons"
HICOLOR_DIR="$ICONS_BASE/hicolor"

mkdir -p "$LOCAL_BIN" "$APPS_DIR" "$ICONS_BASE" "$HICOLOR_DIR"

# 1️⃣ Install Python script & CLI launcher
cp "$SCRIPT_DIR/decks.py" "$LOCAL_BIN/decks.py"
chmod +x "$LOCAL_BIN/decks.py"
ln -sf "$LOCAL_BIN/decks.py" "$LOCAL_BIN/decks"
echo "✅ Installed python script to $LOCAL_BIN/decks.py (executable command: decks)"

# 2️⃣ Install icons (Scalable SVG + Multi-resolution PNGs)
if [ -d "$SCRIPT_DIR/icons/hicolor" ]; then
    cp -r "$SCRIPT_DIR/icons/hicolor"/* "$HICOLOR_DIR/"
    echo "✅ Installed full hicolor icon hierarchy (scalable SVG + 48px, 64px, 128px, 256px, 512px PNGs)"
fi

# Also place direct unthemed fallback icon in ~/.local/share/icons/
if [ -f "$SCRIPT_DIR/icons/hicolor/scalable/apps/decks.svg" ]; then
    cp "$SCRIPT_DIR/icons/hicolor/scalable/apps/decks.svg" "$ICONS_BASE/decks.svg"
fi
# Clean up any legacy org.gnome.Decks icons
rm -f "$ICONS_BASE/org.gnome.Decks.svg"
find "$HICOLOR_DIR" -name "*org.gnome.Decks*" -delete 2>/dev/null || true

# Ensure hicolor has an index.theme (required for gtk-update-icon-cache and GNOME theme resolution)
if [ ! -f "$HICOLOR_DIR/index.theme" ]; then
    if [ -f "/usr/share/icons/hicolor/index.theme" ]; then
        cp "/usr/share/icons/hicolor/index.theme" "$HICOLOR_DIR/index.theme"
    else
        cat > "$HICOLOR_DIR/index.theme" << 'EOF'
[Icon Theme]
Name=Hicolor
Comment=Fallback icon theme
Hidden=true
Directories=scalable/apps,48x48/apps,64x64/apps,128x128/apps,256x256/apps,512x512/apps

[scalable/apps]
Size=48
Type=Scalable
MinSize=16
MaxSize=512
Context=Applications

[48x48/apps]
Size=48
Type=Fixed
Context=Applications

[64x64/apps]
Size=64
Type=Fixed
Context=Applications

[128x128/apps]
Size=128
Type=Fixed
Context=Applications

[256x256/apps]
Size=256
Type=Fixed
Context=Applications

[512x512/apps]
Size=512
Type=Fixed
Context=Applications
EOF
    fi
fi

# 3️⃣ Generate single Desktop Entry (decks.desktop)
# Clean up any leftover org.gnome.Decks.desktop if previously generated
rm -f "$APPS_DIR/org.gnome.Decks.desktop"

DESKTOP_FILE="$APPS_DIR/decks.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Decks
GenericName=Flashcards
Comment=Modern spaced repetition flashcards with FSRS algorithm and 3D animations
Exec=python3 "$LOCAL_BIN/decks.py"
Icon=decks
Terminal=false
Categories=Utility;Education;
StartupWMClass=decks
StartupNotify=true
Keywords=anki;flashcards;spaced;repetition;fsrs;study;decks;
EOF
chmod +x "$DESKTOP_FILE"
echo "✅ Installed desktop entry to $DESKTOP_FILE"

# 4️⃣ Update icon cache & desktop database
if command -v gtk-update-icon-cache &>/dev/null; then
    echo "🔄 Updating GTK icon cache..."
    gtk-update-icon-cache -f -t "$HICOLOR_DIR" 2>/dev/null || true
fi

if command -v update-desktop-database &>/dev/null; then
    echo "🔄 Updating desktop database..."
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

# Touch desktop file to notify GNOME Shell file monitor immediately
touch "$DESKTOP_FILE" 2>/dev/null || true

# Optional: Warn if ~/.local/bin isn't in PATH (common on fresh Fedora setups)
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "⚠️  Note: ~/.local/bin is not in your \$PATH. You may need to log out/in or run:"
    echo "   export PATH=\$HOME/.local/bin:\$PATH"
fi

echo ""
echo "🎉 Installation complete! Decks should now appear in your application menu."