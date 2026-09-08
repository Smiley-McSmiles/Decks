# Decks

> **Modern Spaced Repetition Flashcard Application for GNOME**  
> *Engineered with GTK 4, Libadwaita, and the Free Spaced Repetition Scheduler (FSRS).*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![GNOME HIG](https://img.shields.io/badge/Platform-GNOME%2045%2B-2ec27e.svg)](https://developer.gnome.org/hig/)
[![Algorithm](https://img.shields.io/badge/Algorithm-FSRS%20v4.5-orange.svg)](https://github.com/open-spaced-repetition/fsrs4anki)
[![Built with PyGObject](https://img.shields.io/badge/Built%20with-PyGObject%20%7C%20GTK4-4a90d9.svg)](https://pygobject.gnome.org/)

---

## 🌟 Authorship & Project Disclosure

**Decks** was created, architected, and engineered by **Antigravity (Google AI Studio)** in collaboration with the user, strictly following GNOME Human Interface Guidelines (HIG) and Libadwaita design standards.

---

## ✨ Key Features

- 🧠 **Free Spaced Repetition Scheduler (FSRS)**: Powered by the state-of-the-art FSRS memory model (Stability, Difficulty, and Retrievability) targeting a 90% optimal retention rate. Outperforms legacy SM-2 with precise intervals tailored to human memory decay.
- 🎴 **Hardware-Accelerated 3D Card Animation**: Native GSK (GTK Scene Kit) 3D perspective transforms render smooth 60fps flip transitions and vertical slide arrivals directly onto the card face.
- 🎯 **Geometric Render Centering**: Built with `Gtk.CenterBox` ensuring cards remain centered in the render stage across any window size or display scaling factor.
- 🎨 **Adaptive Libadwaita Design**: Native GNOME 45+ integration with dark/light style adaptation, rounded window corners, responsive view switchers, and standardized dialogs.
- ℹ️ **GNOME Standard About Page**: Integrated `Adw.AboutWindow` showcasing release version, MIT licensing, author attribution, and developer links.
- 📝 **Markdown & LaTeX Math Formatting**: Native, zero-dependency rendering for full Markdown (headers `#`, bold `**`, italic `*`, strikethrough `~~`, highlight `==`, code blocks, blockquotes, task lists, bullet & ordered lists) and LaTeX math (`$...$`, `$$...$$`, fractions `\frac{a}{b}`, roots `\sqrt`, Greek letters, calculus symbols, and matrices).
- 📑 **Multi-Line Card Backs & CSV Flexibility**: Import CSV files where 3rd, 4th, and subsequent columns automatically become clean, newline-separated lines on the card back. Full support for literal `\n` line breaks and multi-line card editing.
- 🔍 **Card Browser, Editor & Search**: Instant filtering across question prompts, answers, and deck collections with dedicated dialogs for card creation, multi-line editing, and progress resets.
- 📊 **Detailed Statistics & Analytics**: Real-time tracking of retention rates, daily review streaks (🔥), FSRS average difficulty, maturity breakdowns, and review audit trails.
- 💾 **Data Safety & Portability**: SQLite backend with Write-Ahead Logging (WAL) and busy timeout protection, one-click CSV/TSV card imports, and full JSON backup/restore.

---

## 🚀 Installation & Requirements

### System Dependencies

#### Ubuntu / Debian / Pop!_OS / Linux Mint
```bash
sudo apt update
sudo apt install -y python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-graphene-1.0 python3-opengl python3-pip
```

#### Fedora / RHEL
```bash
sudo dnf install -y python3-gobject gtk4 libadwaita graphene python3-pyopengl
```

#### Arch Linux / Manjaro
```bash
sudo pacman -S --noconfirm python-gobject gtk4 libadwaita graphene python-opengl
```

---

## 📦 Quick Install

Clone this repository and run the installer:

```bash
git clone https://github.com/your-username/decks.git
cd decks
chmod +x install.sh
./install.sh
```

The installer will:
1. Copy `decks.py` to `~/.local/bin/` with a `decks` command symlink.
2. Install scalable application icons into `~/.local/share/icons/hicolor/scalable/apps/`.
3. Create a `.desktop` launcher in `~/.local/share/applications/` so Decks appears directly in your GNOME Shell application overview.

### Manual Launch

You can also run Decks directly without installing:

```bash
python3 decks.py
```

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| <kbd>Space</kbd> or <kbd>Return</kbd> | Flip Flashcard (Show Answer) |
| <kbd>1</kbd> | Rate **Again** (Forgot / Repeat) |
| <kbd>2</kbd> | Rate **Hard** (Recalled with difficulty) |
| <kbd>3</kbd> | Rate **Good** (Standard recall) |
| <kbd>4</kbd> | Rate **Easy** (Effortless recall) |
| <kbd>F1</kbd> | Open About Page (`Adw.AboutWindow`) |
| <kbd>Ctrl</kbd> + <kbd>Q</kbd> | Quit Application |
| <kbd>Ctrl</kbd> + <kbd>W</kbd> | Close Window |

---

## 🔬 Spaced Repetition Algorithm (FSRS vs SM-2)

Decks implements the modern **FSRS** memory model rather than legacy SM-2:

$$\text{Retrievability: } R(t, S) = \left(1 + \frac{t}{9 \cdot S}\right)^{-1}$$

- **Stability ($S$)**: Days elapsed until retrievability drops to the desired retention threshold (90%).
- **Difficulty ($D$)**: Normalized value ($1.0 \le D \le 10.0$) dynamically adjusted per review based on recall hesitation and rating.
- **Interval Formula**: Calculates the exact review date where $R = 0.90$, reducing review overload while preventing forgetting.

---

## 📄 License

This project is open-source software licensed under the **MIT License**. See the [LICENSE](LICENSE) file for complete terms and copyright notices.

```
Copyright (c) 2026 Antigravity (Google AI Studio)
```
