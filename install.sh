#!/usr/bin/env bash
# ==============================================================================
# Decks - Native GNOME 45+ Desktop Installer
# Installs GTK4, Libadwaita, FSRS algorithm flashcards and creates desktop launcher
# ==============================================================================

set -e

echo "📦 Installing Decks (GTK4 + Libadwaita + FSRS)..."

# 1. Install System Packages
if command -v apt-get &> /dev/null; then
    echo "Detected Debian / Ubuntu / Pop!_OS / Mint"
    sudo apt-get update -y || true
    sudo apt-get install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-graphene-1.0 python3-opengl python3-pip
elif command -v dnf &> /dev/null; then
    echo "Detected Fedora / RHEL"
    sudo dnf install -y python3-gobject gtk4 libadwaita graphene python3-pyopengl
elif command -v pacman &> /dev/null; then
    echo "Detected Arch Linux / Manjaro"
    sudo pacman -S --noconfirm python-gobject gtk4 libadwaita graphene python-opengl
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
ICONS_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"

mkdir -p "$LOCAL_BIN" "$APPS_DIR" "$ICONS_DIR"

# 1️⃣ Install Python script & CLI launcher
cp "$SCRIPT_DIR/decks.py" "$LOCAL_BIN/decks.py"
chmod +x "$LOCAL_BIN/decks.py"
ln -sf "$LOCAL_BIN/decks.py" "$LOCAL_BIN/decks"
echo "✅ Installed python script to $LOCAL_BIN/decks.py (executable command: decks)"

# 2️⃣ Install SVG icon from icons directory
ICON_SRC=""
if [ -f "$SCRIPT_DIR/icons/hicolor/scalable/apps/decks.svg" ]; then
    ICON_SRC="$SCRIPT_DIR/icons/hicolor/scalable/apps/decks.svg"
elif [ -f "$SCRIPT_DIR/icons/decks.svg" ]; then
    ICON_SRC="$SCRIPT_DIR/icons/decks.svg"
fi

if [ -n "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$ICONS_DIR/decks.svg"
    ln -sf "$ICONS_DIR/decks.svg" "$ICONS_DIR/org.gnome.Decks.svg"
    echo "✅ Installed icon to $ICONS_DIR/decks.svg (with org.gnome.Decks.svg symlink)"
else
    echo "⚠️ Icon decks.svg not found in icons directory, skipping icon copy."
fi

# 3️⃣ Generate Desktop Entry with correct absolute path
DESKTOP_FILE="$APPS_DIR/decks.desktop"
cat > "$DESKTOP_FILE" << EOF
[Desktop Entry]
Type=Application
Name=Decks
Comment=Modern spaced repetition flashcards with FSRS algorithm and 3D animations
Exec=python3 "$LOCAL_BIN/decks.py"
Icon=decks
Terminal=false
Categories=Utility;Education;
StartupNotify=true
EOF
chmod +x "$DESKTOP_FILE"
echo "✅ Installed desktop entry to $DESKTOP_FILE"

# 4️⃣ Update icon cache & desktop database (if tools are present)
if command -v gtk-update-icon-cache &>/dev/null; then
    echo "🔄 Updating icon cache..."
    gtk-update-icon-cache -f "$HOME/.local/share/icons/hicolor/" 2>/dev/null || true
fi

if command -v update-desktop-database &>/dev/null; then
    echo "🔄 Updating desktop database..."
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi

# Optional: Warn if ~/.local/bin isn't in PATH (common on fresh Fedora setups)
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo "⚠️  Note: ~/.local/bin is not in your \$PATH. You may need to log out/in or run:"
    echo "   export PATH=\$HOME/.local/bin:\$PATH"
fi

echo ""
echo "🎉 Installation complete! Decks should now appear in your application menu."