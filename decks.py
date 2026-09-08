#!/usr/bin/env python3
"""
Decks - Modern Spaced Repetition Flashcard Application for GNOME
Engineered with GTK4, Libadwaita, and the Free Spaced Repetition Scheduler (FSRS).
Created by Antigravity (Google AI Studio).
Released under the MIT License.
"""

import sys
import os
import math
import time
import json
import sqlite3
import csv
import io
import re
import html
import ctypes
import random
import warnings
from typing import List, Dict, Optional, Tuple

# Prefer GTK's native OpenGL renderer over Vulkan when GtkGLArea is used.
# Modern GTK 4.14+ uses 'gl' (previously 'ngl')
if "GSK_RENDERER" not in os.environ:
    os.environ["GSK_RENDERER"] = "gl"

# Suppress deprecation warnings from Libadwaita 1.5+ transitions
warnings.filterwarnings("ignore", category=DeprecationWarning)

try:
    import gi
    gi.require_version('Gtk', '4.0')
    gi.require_version('Adw', '1')
    from gi.repository import Gtk, Adw, GLib, Gio, Gdk, Pango
except (ImportError, ValueError) as e:
    sys.stderr.write(
        "\n❌ Error: Decks requires GTK 4 and Libadwaita (PyGObject).\n"
        f"Missing dependency: {e}\n\n"
        "To install required packages:\n"
        "  • Ubuntu / Debian / Pop!_OS / Mint:\n"
        "      sudo apt install python3-gi python3-gi-cairo gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-graphene-1.0 python3-opengl\n"
        "  • Fedora / RHEL:\n"
        "      sudo dnf install python3-gobject gtk4 libadwaita graphene python3-pyopengl\n"
        "  • Arch Linux / Manjaro:\n"
        "      sudo pacman -S python-gobject gtk4 libadwaita graphene python-opengl\n\n"
    )
    sys.exit(1)

try:
    gi.require_version('Gsk', '4.0')
    gi.require_version('Graphene', '1.0')
    from gi.repository import Gsk, Graphene
    GSK_TRANSFORM_AVAILABLE = True
except Exception:
    GSK_TRANSFORM_AVAILABLE = False

DB_DIR = os.path.expanduser("~/.local/share/decks")
DB_PATH = os.path.join(DB_DIR, "decks.db")


# ==============================================================================
# Database Schema, Robust Connection & Automated Migration
# ==============================================================================

def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection with WAL mode and 10s timeout to prevent locking."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 10000")
    return conn


def init_database():
    """Initializes and migrates the SQLite database schema automatically."""
    os.makedirs(DB_DIR, exist_ok=True)

    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS decks (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                deck_id TEXT NOT NULL,
                front TEXT NOT NULL,
                back TEXT NOT NULL,
                notes TEXT,
                ease_factor REAL DEFAULT 2.5,
                interval REAL DEFAULT 0.0,
                repetitions INTEGER DEFAULT 0,
                lapses INTEGER DEFAULT 0,
                state TEXT DEFAULT 'new',
                due_date REAL,
                stability REAL DEFAULT 0.0,
                difficulty REAL DEFAULT 0.0,
                last_review REAL DEFAULT 0.0,
                FOREIGN KEY (deck_id) REFERENCES decks(id) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS review_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_id TEXT,
                rating INTEGER,
                old_interval REAL,
                new_interval REAL,
                old_ease REAL,
                new_ease REAL,
                timestamp REAL
            )
        """)

        # Automated Schema Migration for existing databases
        cur.execute("PRAGMA table_info(review_logs)")
        existing_log_cols = [r[1] for r in cur.fetchall()]
        if "deck_name" not in existing_log_cols:
            cur.execute("ALTER TABLE review_logs ADD COLUMN deck_name TEXT DEFAULT ''")
        if "card_front" not in existing_log_cols:
            cur.execute("ALTER TABLE review_logs ADD COLUMN card_front TEXT DEFAULT ''")

        cur.execute("PRAGMA table_info(cards)")
        existing_card_cols = [r[1] for r in cur.fetchall()]
        if "notes" not in existing_card_cols:
            cur.execute("ALTER TABLE cards ADD COLUMN notes TEXT DEFAULT ''")
        if "stability" not in existing_card_cols:
            cur.execute("ALTER TABLE cards ADD COLUMN stability REAL DEFAULT 0.0")
        if "difficulty" not in existing_card_cols:
            cur.execute("ALTER TABLE cards ADD COLUMN difficulty REAL DEFAULT 0.0")
        if "last_review" not in existing_card_cols:
            cur.execute("ALTER TABLE cards ADD COLUMN last_review REAL DEFAULT 0.0")

        # Key-Value preferences table for daily goal baseline and limits
        cur.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # Seed initial sample decks and cards if empty
        cur.execute("SELECT COUNT(*) FROM decks")
        if cur.fetchone()[0] == 0:
            seed_default_data(cur)

        conn.commit()


def set_db_preference(key: str, val: str):
    """Store application preference key-value in database."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("INSERT OR REPLACE INTO preferences (key, value) VALUES (?, ?)", (key, val))
            conn.commit()
    except Exception as e:
        print("Preference save error:", e)


def get_db_preference(key: str, default: Optional[str] = None) -> Optional[str]:
    """Retrieve application preference value from database."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT value FROM preferences WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default
    except Exception:
        return default


def seed_default_data(cur, now: Optional[float] = None):
    """Populates fresh default collections, cards, and realistic review audit trail."""
    if now is None:
        now = time.time()

    cur.execute("INSERT INTO decks (id, name, description) VALUES ('deck-sd', 'System Design', 'Distributed systems & scalability')")
    cur.execute("INSERT INTO decks (id, name, description) VALUES ('deck-gnome', 'Linux & GNOME Dev', 'GTK4, Libadwaita, and Wayland architecture')")
    cur.execute("INSERT INTO decks (id, name, description) VALUES ('deck-japanese', 'Hiragana', 'Japanese syllabary characters')")

    sample_cards = [
        ('c1', 'deck-sd', 'What is the CAP Theorem in distributed data stores?', 
         'Consistency, Availability, and Partition Tolerance: A distributed network can only provide at most two of these guarantees simultaneously during network partitions.', 
         'Key foundation of modern NoSQL vs Relational architectural decisions', 2.5, 0.0, 0, 0, 'new', now, 0.4, 5.0, 0.0),
        ('c2', 'deck-sd', 'What is Consistent Hashing and why is it used?', 
         'A partitioning technique using a circular hash ring so adding/removing nodes only rebalances K/N keys rather than all keys.', 
         'Used in DynamoDB, Cassandra, and Memcached clusters', 2.6, 1.0, 1, 0, 'learning', now - 3600, 1.2, 4.5, now - 3600),
        ('c3', 'deck-gnome', 'What GTK4 widget handles hardware-accelerated 3D rendering?', 
         'Gtk.GLArea connects directly to OpenGL / OpenGL ES via modern shader pipelines and GSK rendering nodes.', 
         'Core Profile 3.2+ replaces deprecated legacy pipelines', 2.5, 3.0, 2, 0, 'review', now - 1800, 3.2, 5.0, now - 1800),
        ('c4', 'deck-japanese', 'い', 'i', 'Hiragana vowel character', 2.5, 0.0, 0, 0, 'new', now, 0.4, 5.0, 0.0),
        ('c5', 'deck-japanese', 'あ', 'a', 'First character of the Hiragana alphabet', 2.5, 1.0, 1, 0, 'learning', now - 3600, 1.2, 4.5, now - 3600),
    ]
    cur.executemany("""
        INSERT INTO cards (
            id, deck_id, front, back, notes, ease_factor, interval, repetitions,
            lapses, state, due_date, stability, difficulty, last_review
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, sample_cards)



def reset_database_to_fresh():
    """Wipes all collections, cards, and review audit history, then reseeds default data."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM review_logs")
        cur.execute("DELETE FROM cards")
        cur.execute("DELETE FROM decks")
        cur.execute("DELETE FROM preferences")
        seed_default_data(cur)
        conn.commit()


def calculate_streak_from_db() -> Tuple[int, int, bool]:
    """Calculate current consecutive study days, best streak, and whether studied today."""
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT DISTINCT date(timestamp, 'unixepoch', 'localtime') as day
                FROM review_logs
                ORDER BY day DESC
            """)
            days = [r[0] for r in cur.fetchall()]

        if not days:
            return 0, 0, False

        today_str = time.strftime("%Y-%m-%d")
        yesterday_time = time.time() - 86400
        yesterday_str = time.strftime("%Y-%m-%d", time.localtime(yesterday_time))

        studied_today = (today_str in days)
        date_set = set(days)

        current_streak = 0
        cur_t = time.time() if studied_today else yesterday_time
        while True:
            d_str = time.strftime("%Y-%m-%d", time.localtime(cur_t))
            if d_str in date_set:
                current_streak += 1
                cur_t -= 86400
            else:
                break

        # Calculate best historic streak
        sorted_days = sorted(list(date_set))
        best_streak = current_streak
        temp_streak = 1
        for i in range(1, len(sorted_days)):
            t1 = time.mktime(time.strptime(sorted_days[i-1], "%Y-%m-%d"))
            t2 = time.mktime(time.strptime(sorted_days[i], "%Y-%m-%d"))
            if abs(t2 - t1 - 86400) < 3600:
                temp_streak += 1
                if temp_streak > best_streak:
                    best_streak = temp_streak
            else:
                temp_streak = 1

        return current_streak, max(current_streak, best_streak), studied_today
    except Exception as e:
        print("Streak calculation notice:", e)
        return 0, 0, False


# ==============================================================================
# FSRS (Free Spaced Repetition Scheduler) Engine & Interval Formatter
# ==============================================================================

def format_interval(days: float) -> str:
    """Format an interval in days into a concise, human-readable string."""
    if days < (1.0 / 1440.0) * 1.5:
        return "< 1 min"
    minutes = days * 1440.0
    if minutes < 60:
        return f"{int(round(minutes))} min"
    hours = minutes / 60.0
    if hours < 24:
        return f"{int(round(hours))} hr"
    if days < 30:
        d = int(round(days))
        return f"{d} day" if d == 1 else f"{d} days"
    months = days / 30.0
    if months < 12:
        return f"{months:.1f} mo"
    return f"{(days / 365.0):.1f} yr"


class FSRSEngine:
    """
    FSRS (Free Spaced Repetition Scheduler) modern algorithm engine.
    Calculates Stability (S), Difficulty (D), and Retrievability (R).
    Optimized for high retention (default 90%).
    """
    w = [0.40255, 1.18385, 3.173, 15.691, 7.1949, 0.5345, 1.4604, 0.0046,
         1.5457, 0.1192, 1.0192, 1.9395, 0.11, 0.296, 0.2269, 0.5698, 2.8532]
    DESIRED_RETENTION = 0.90

    @classmethod
    def init_stability(cls, rating: int) -> float:
        rating = max(1, min(4, rating))
        return cls.w[rating - 1]

    @classmethod
    def init_difficulty(cls, rating: int) -> float:
        rating = max(1, min(4, rating))
        d = cls.w[4] - math.exp(cls.w[5] * (rating - 1)) + 1.0
        return max(1.0, min(10.0, d))

    @classmethod
    def retrievability(cls, elapsed_days: float, stability: float) -> float:
        if stability <= 0:
            return 0.0
        return (1.0 + elapsed_days / (9.0 * stability)) ** -1.0

    @classmethod
    def next_difficulty(cls, d: float, rating: int) -> float:
        delta = -cls.w[6] * (rating - 3)
        d_good = cls.init_difficulty(3)
        new_d = cls.w[7] * d_good + (1.0 - cls.w[7]) * (d + delta)
        return max(1.0, min(10.0, new_d))

    @classmethod
    def next_stability(cls, s: float, d: float, r: float, rating: int) -> float:
        s = max(0.1, s)
        d = max(1.0, min(10.0, d))
        r = max(0.01, min(1.0, r))
        if rating == 1:
            s_forget = cls.w[11] * (d ** -cls.w[12]) * (((s + 1.0) ** cls.w[13]) - 1.0) * math.exp(cls.w[14] * (1.0 - r))
            return max(0.1, min(s_forget, s))
        else:
            hard_penalty = cls.w[15] if rating == 2 else 1.0
            easy_bonus = cls.w[16] if rating == 4 else 1.0
            s_recall = s * (1.0 + math.exp(cls.w[8]) * (11.0 - d) * (s ** -cls.w[9]) * (math.exp(cls.w[10] * (1.0 - r)) - 1.0) * hard_penalty * easy_bonus)
            return max(0.1, s_recall)

    @classmethod
    def next_interval(cls, stability: float) -> float:
        interval = stability * (cls.DESIRED_RETENTION ** -1.0 - 1.0) / (0.90 ** -1.0 - 1.0)
        return max(1.0, round(interval, 1))


class MarkdownMathParser:
    """
    High-performance Markdown and LaTeX Math parser that converts
    Markdown and LaTeX math markup into native Pango Markup for GTK4.
    Supports:
    - Multi-line card backs with automatic paragraph & line break handling
    - Markdown headers (#, ##, ###, ####), bold, italics, bold-italics, strikethrough,
      highlights (==text==), underlines, inline code, code blocks, blockquotes,
      bullet lists, numbered lists, task lists, and horizontal rules
    - Full LaTeX math ($...$, $$...$$, \\[...\\], \\(...\\), [latex]...[/latex], [$]...[/$])
      including fractions, roots, Greek letters, operators, subscripts, superscripts,
      calculus symbols, set theory, arrows, and matrices.
    """

    GREEK = {
        'alpha': 'α', 'beta': 'β', 'gamma': 'γ', 'delta': 'δ', 'epsilon': 'ε',
        'varepsilon': 'ε', 'zeta': 'ζ', 'eta': 'η', 'theta': 'θ', 'vartheta': 'ϑ',
        'iota': 'ι', 'kappa': 'κ', 'lambda': 'λ', 'mu': 'μ', 'nu': 'ν',
        'xi': 'ξ', 'pi': 'π', 'varpi': 'ϖ', 'rho': 'ρ', 'varrho': 'ϱ',
        'sigma': 'σ', 'varsigma': 'ς', 'tau': 'τ', 'upsilon': 'υ', 'phi': 'φ',
        'varphi': 'ϕ', 'chi': 'χ', 'psi': 'ψ', 'omega': 'ω',
        'Gamma': 'Γ', 'Delta': 'Δ', 'Theta': 'Θ', 'Lambda': 'Λ', 'Xi': 'Ξ',
        'Pi': 'Π', 'Sigma': 'Σ', 'Upsilon': 'Υ', 'Phi': 'Φ', 'Psi': 'Ψ', 'Omega': 'Ω',
    }

    SYMBOLS = {
        'pm': '±', 'mp': '∓', 'times': '×', 'div': '÷', 'cdot': '·', 'bullet': '•', 'circ': '°',
        'leq': '≤', 'le': '≤', 'geq': '≥', 'ge': '≥', 'neq': '≠', 'ne': '≠',
        'approx': '≈', 'equiv': '≡', 'sim': '∼', 'simeq': '≃', 'cong': '≅', 'propto': '∝',
        'infty': '∞', 'partial': '∂', 'nabla': '∇', 'hbar': 'ℏ', 'ell': 'ℓ',
        'in': '∈', 'notin': '∉', 'subset': '⊂', 'subseteq': '⊆', 'supset': '⊃', 'supseteq': '⊇',
        'cup': '∪', 'cap': '∩', 'setminus': '∖', 'emptyset': '∅',
        'forall': '∀', 'exists': '∃', 'nexists': '∄',
        'to': '→', 'rightarrow': '→', 'leftarrow': '←', 'Rightarrow': '⇒', 'Leftarrow': '⇐',
        'iff': '⇔', 'Leftrightarrow': '⇔', 'mapsto': '↦', 'nearrow': '↗', 'searrow': '↘',
        'land': '∧', 'lor': '∨', 'neg': '¬', 'oplus': '⊕', 'otimes': '⊗',
        'angle': '∠', 'parallel': '∥', 'perp': '⟂',
        'int': '∫', 'iint': '∬', 'iiint': '∭', 'oint': '∮',
        'sum': '∑', 'prod': '∏',
        'mathbb{R}': 'ℝ', 'mathbb{C}': 'ℂ', 'mathbb{N}': 'ℕ', 'mathbb{Z}': 'ℤ', 'mathbb{Q}': 'ℚ',
        'dots': '…', 'cdots': '…', 'ldots': '…', 'ddots': '⋱', 'vdots': '⋮',
    }

    ACCENTS = {
        'hat': '\u0302', 'bar': '\u0304', 'vec': '\u20D7', 'dot': '\u0307',
        'ddot': '\u0308', 'tilde': '\u0303'
    }

    FUNCTIONS = [
        'sin', 'cos', 'tan', 'arcsin', 'arccos', 'arctan', 'sinh', 'cosh', 'tanh',
        'ln', 'log', 'exp', 'det', 'dim', 'deg', 'gcd', 'hom', 'ker',
        'min', 'max', 'sup', 'inf', 'lim', 'arg'
    ]

    @staticmethod
    def _extract_braced_arg(s: str, start_pos: int):
        """Extracts {argument} from string with balanced brace support."""
        i = start_pos
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s) or s[i] != '{':
            return None, start_pos
        start = i + 1
        depth = 1
        i += 1
        while i < len(s) and depth > 0:
            if s[i] == '{' and (i == 0 or s[i-1] != '\\'):
                depth += 1
            elif s[i] == '}' and (i == 0 or s[i-1] != '\\'):
                depth -= 1
                if depth == 0:
                    return s[start:i], i + 1
            i += 1
        return None, start_pos

    @staticmethod
    def _extract_bracket_arg(s: str, start_pos: int):
        """Extracts [argument] from string."""
        i = start_pos
        while i < len(s) and s[i].isspace():
            i += 1
        if i >= len(s) or s[i] != '[':
            return None, start_pos
        start = i + 1
        depth = 1
        i += 1
        while i < len(s) and depth > 0:
            if s[i] == '[' and (i == 0 or s[i-1] != '\\'):
                depth += 1
            elif s[i] == ']' and (i == 0 or s[i-1] != '\\'):
                depth -= 1
                if depth == 0:
                    return s[start:i], i + 1
            i += 1
        return None, start_pos

    @classmethod
    def render_latex_expression(cls, expr: str) -> str:
        """Converts a single LaTeX math expression into styled Pango markup."""
        s = expr.strip()
        if not s:
            return ""

        # Delimiter cleanup
        s = re.sub(r'\\left\s*([(\[{|])', r'\1', s)
        s = re.sub(r'\\right\s*([)\]}|])', r'\1', s)
        s = re.sub(r'\\left\s*\\([{}])', r'\1', s)
        s = re.sub(r'\\right\s*\\([{}])', r'\1', s)
        s = re.sub(r'\\left\.', '', s)
        s = re.sub(r'\\right\.', '', s)

        # Spacing
        s = re.sub(r'\\(?:[,;:! ]|quad|qquad)', ' ', s)

        # Text wrappers
        s = re.sub(r'\\(?:text|mathrm|operatorname)\{([^}]+)\}', r'\1', s)
        s = re.sub(r'\\mathbf\{([^}]+)\}', r'<b>\1</b>', s)
        s = re.sub(r'\\mathit\{([^}]+)\}', r'<i>\1</i>', s)
        s = re.sub(r'\\mathtt\{([^}]+)\}', r'<tt>\1</tt>', s)

        # Chemical / Math arrows
        s = re.sub(r'\\xrightarrow\{([^}]+)\}', r'─(\1)→', s)
        s = re.sub(r'\\xleftarrow\{([^}]+)\}', r'←(\1)─', s)

        # Fractions with balanced brace parsing
        out = []
        i = 0
        while i < len(s):
            if s.startswith(r'\frac', i) or s.startswith(r'\dfrac', i):
                cmd_len = 6 if s.startswith(r'\dfrac', i) else 5
                num, next_pos = cls._extract_braced_arg(s, i + cmd_len)
                if num is not None:
                    den, end_pos = cls._extract_braced_arg(s, next_pos)
                    if den is not None:
                        rend_num = cls.render_latex_expression(num)
                        rend_den = cls.render_latex_expression(den)
                        out.append(f"<sup>{rend_num}</sup>⁄<sub>{rend_den}</sub>")
                        i = end_pos
                        continue
            elif s.startswith(r'\sqrt', i):
                next_pos = i + 5
                n_arg, after_n = cls._extract_bracket_arg(s, next_pos)
                if n_arg is not None:
                    rad_arg, end_pos = cls._extract_braced_arg(s, after_n)
                    if rad_arg is not None:
                        rend_n = cls.render_latex_expression(n_arg)
                        rend_rad = cls.render_latex_expression(rad_arg)
                        out.append(f"<sup>{rend_n}</sup>√({rend_rad})")
                        i = end_pos
                        continue
                else:
                    rad_arg, end_pos = cls._extract_braced_arg(s, next_pos)
                    if rad_arg is not None:
                        rend_rad = cls.render_latex_expression(rad_arg)
                        out.append(f"√({rend_rad})")
                        i = end_pos
                        continue

            out.append(s[i])
            i += 1
        s = ''.join(out)

        # Accents like \hat{x}, \vec{v}
        for acc_cmd, comb in cls.ACCENTS.items():
            pattern = re.escape('\\' + acc_cmd) + r'\{([a-zA-Z0-9])\}'
            s = re.sub(pattern, lambda m, c=comb: m.group(1) + c, s)

        # Greek letters
        for name, sym in cls.GREEK.items():
            pattern = re.escape('\\' + name) + r'(?![a-zA-Z])'
            s = re.sub(pattern, sym, s)

        # Mathematical symbols
        for name, sym in cls.SYMBOLS.items():
            pattern = re.escape('\\' + name) + r'(?![a-zA-Z])'
            s = re.sub(pattern, sym, s)

        # Limits / Sum / Int bounds
        s = re.sub(r'\\lim_\{([^}]+)\}', r'lim<sub>\1</sub>', s)
        s = re.sub(r'\\lim_([a-zA-Z0-9]+)', r'lim<sub>\1</sub>', s)

        # Subscripts & Superscripts
        s = re.sub(r'\^\{([^}]+)\}', r'<sup>\1</sup>', s)
        s = re.sub(r'\^([a-zA-Z0-9+\-*=])', r'<sup>\1</sup>', s)
        s = re.sub(r'_\{([^}]+)\}', r'<sub>\1</sub>', s)
        s = re.sub(r'_([a-zA-Z0-9+\-*=])', r'<sub>\1</sub>', s)

        # Function names
        for f in cls.FUNCTIONS:
            pattern = re.escape('\\' + f) + r'(?![a-zA-Z])'
            s = re.sub(pattern, f, s)

        return s

    @classmethod
    def render_markdown_and_math(cls, text: str, is_dark: bool = True) -> str:
        """
        Parses Markdown text with embedded LaTeX math ($...$, $$...$$, \\[...\\], \\(...\\))
        and produces clean Pango markup suitable for GTK4 Labels.
        """
        if not text:
            return ""

        raw = text.replace('\r\n', '\n').replace('\r', '\n')

        # 1. Protect & Extract Math Blocks
        math_placeholders = []

        def save_math(m, display=False):
            content = m.group(1)
            rendered = cls.render_latex_expression(content)
            idx = len(math_placeholders)
            if display:
                rendered = f"\n<span size='large' weight='bold'>{rendered}</span>\n"
            math_placeholders.append(rendered)
            return f"@@MATH_{idx}@@"

        raw = re.sub(r'\$\$([\s\S]+?)\$\$', lambda m: save_math(m, display=True), raw)
        raw = re.sub(r'\\\[([\s\S]+?)\\\]', lambda m: save_math(m, display=True), raw)
        raw = re.sub(r'\[latex\]([\s\S]+?)\[/latex\]', lambda m: save_math(m, display=True), raw)
        raw = re.sub(r'\[\$\]([\s\S]+?)\[/\$\]', lambda m: save_math(m, display=False), raw)
        raw = re.sub(r'\\\(([\s\S]+?)\\\)', lambda m: save_math(m, display=False), raw)
        raw = re.sub(r'(?<!\\)\$([^\$\n]+?)(?<!\\)\$', lambda m: save_math(m, display=False), raw)

        # 2. Extract & Protect Code Blocks
        code_placeholders = []
        def save_code_block(m):
            code_content = m.group(2)
            escaped = html.escape(code_content.strip())
            bg_color = "#2a2a2a" if is_dark else "#e4e4e4"
            fg_color = "#f6f5f4" if is_dark else "#222222"
            block = f"<tt><span font_family='monospace' background='{bg_color}' foreground='{fg_color}'>\n{escaped}\n</span></tt>"
            idx = len(code_placeholders)
            code_placeholders.append(block)
            return f"@@CODE_BLOCK_{idx}@@"

        raw = re.sub(r'```([a-zA-Z0-9_\-]+)?\n([\s\S]+?)```', save_code_block, raw)

        # 3. Extract & Protect Inline Code
        inline_code_placeholders = []
        def save_inline_code(m):
            code_content = m.group(1)
            escaped = html.escape(code_content)
            bg_color = "#333333" if is_dark else "#ebebeb"
            fg_color = "#e0e0e0" if is_dark else "#1a1a1a"
            inline = f"<tt><span font_family='monospace' background='{bg_color}' foreground='{fg_color}'> {escaped} </span></tt>"
            idx = len(inline_code_placeholders)
            inline_code_placeholders.append(inline)
            return f"@@INLINE_CODE_{idx}@@"

        raw = re.sub(r'`([^`\n]+)`', save_inline_code, raw)

        # 4. Parse Line-by-Line Markdown Elements
        lines = raw.split('\n')
        out_lines = []

        quote_color = "#78aeed" if is_dark else "#1c71d8"
        dim_color = "#9a9996" if is_dark else "#77767b"

        for line in lines:
            stripped = line.strip()

            if re.match(r'^(?:---|\*\*\*|___)$', stripped):
                out_lines.append(f"<span color='{dim_color}'>────────────────────────────────</span>")
                continue

            h1_m = re.match(r'^#\s+(.+)$', stripped)
            if h1_m:
                h_text = html.escape(h1_m.group(1))
                out_lines.append(f"<span size='xx-large' weight='bold'>{h_text}</span>")
                continue

            h2_m = re.match(r'^##\s+(.+)$', stripped)
            if h2_m:
                h_text = html.escape(h2_m.group(1))
                out_lines.append(f"<span size='x-large' weight='bold'>{h_text}</span>")
                continue

            h3_m = re.match(r'^###\s+(.+)$', stripped)
            if h3_m:
                h_text = html.escape(h3_m.group(1))
                out_lines.append(f"<span size='large' weight='bold'>{h_text}</span>")
                continue

            h4_m = re.match(r'^####\s+(.+)$', stripped)
            if h4_m:
                h_text = html.escape(h4_m.group(1))
                out_lines.append(f"<span weight='bold'>{h_text}</span>")
                continue

            quote_m = re.match(r'^>\s*(.+)$', stripped)
            if quote_m:
                q_text = html.escape(quote_m.group(1))
                out_lines.append(f"<span color='{quote_color}'>▎</span> <i>{q_text}</i>")
                continue

            task_m = re.match(r'^[*\-+]\s+\[([ xX])\]\s+(.+)$', stripped)
            if task_m:
                checked = task_m.group(1).lower() == 'x'
                bullet = "☑" if checked else "☐"
                item_text = html.escape(task_m.group(2))
                out_lines.append(f"  {bullet} {item_text}")
                continue

            ul_m = re.match(r'^[*\-+]\s+(.+)$', stripped)
            if ul_m:
                item_text = html.escape(ul_m.group(1))
                out_lines.append(f"  • {item_text}")
                continue

            ol_m = re.match(r'^(\d+)\.\s+(.+)$', stripped)
            if ol_m:
                num = ol_m.group(1)
                item_text = html.escape(ol_m.group(2))
                out_lines.append(f"  {num}. {item_text}")
                continue

            out_lines.append(html.escape(line))

        result = '\n'.join(out_lines)

        # 5. Inline Formatting
        result = re.sub(r'\*\*\*([^\*\n]+?)\*\*\*', r'<b><i>\1</i></b>', result)
        result = re.sub(r'___([^_\n]+?)___', r'<b><i>\1</i></b>', result)
        result = re.sub(r'\*\*\_([^\*\_\n]+?)\_\*\*', r'<b><i>\1</i></b>', result)
        result = re.sub(r'\_\*\*([^\*\_\n]+?)\*\*\_', r'<b><i>\1</i></b>', result)

        result = re.sub(r'\*\*([^\*\n]+?)\*\*', r'<b>\1</b>', result)
        result = re.sub(r'(?<![a-zA-Z0-9])__([^_\n]+?)__(?![a-zA-Z0-9])', r'<b>\1</b>', result)

        result = re.sub(r'(?<!\*)\*([^\*\n]+?)\*(?!\*)', r'<i>\1</i>', result)
        result = re.sub(r'(?<![a-zA-Z0-9_])_([^_\n]+?)_(?![a-zA-Z0-9_])', r'<i>\1</i>', result)

        result = re.sub(r'~~([^~\n]+?)~~', r'<s>\1</s>', result)

        hl_bg = "#f6d32d" if is_dark else "#f9f06b"
        result = re.sub(r'==([^=\n]+?)==', f"<span background='{hl_bg}' foreground='#111111'><b> \\1 </b></span>", result)

        result = re.sub(r'&lt;u&gt;([\s\S]+?)&lt;/u&gt;', r'<u>\1</u>', result)
        result = re.sub(r'&lt;br\s*/?&gt;', '\n', result)

        # 6. Restore Placeholders
        for i, placeholder in enumerate(inline_code_placeholders):
            result = result.replace(f"@@INLINE_CODE_{i}@@", placeholder)

        for i, placeholder in enumerate(code_placeholders):
            result = result.replace(f"@@CODE_BLOCK_{i}@@", placeholder)

        for i, placeholder in enumerate(math_placeholders):
            result = result.replace(f"@@MATH_{i}@@", placeholder)

        # 7. Also handle any remaining raw standalone LaTeX math expressions without dollar signs
        if r'\frac' in result or r'\sqrt' in result or bool(re.search(r'\\[a-zA-Z]+', result)):
            # Check for standalone LaTeX commands
            for name, sym in cls.GREEK.items():
                pattern = re.escape('\\' + name) + r'(?![a-zA-Z])'
                result = re.sub(pattern, sym, result)
            for name, sym in cls.SYMBOLS.items():
                pattern = re.escape('\\' + name) + r'(?![a-zA-Z])'
                result = re.sub(pattern, sym, result)

        return result


class FSRSCard:
    def __init__(self, card_id: str, deck_id: str, front: str, back: str, notes: str,
                 ease_factor: float, interval: float, repetitions: int, lapses: int,
                 state: str, due_date: float, stability: float = 0.0, difficulty: float = 0.0,
                 last_review: float = 0.0):
        self.card_id = card_id
        self.deck_id = deck_id
        self.front = front
        self.back = back
        self.notes = notes or ""
        self.interval = float(interval or 0.0)
        self.repetitions = int(repetitions or 0)
        self.lapses = int(lapses or 0)
        self.state = state or "new"
        self.due_date = float(due_date or 0.0)

        # FSRS variables
        self.stability = float(stability) if (stability and stability > 0.0) else max(0.1, self.interval)
        if difficulty and 1.0 <= difficulty <= 10.0:
            self.difficulty = float(difficulty)
        elif ease_factor and ease_factor > 0:
            self.difficulty = max(1.0, min(10.0, 11.0 - (ease_factor * 2.4)))
        else:
            self.difficulty = 5.0
        self.ease_factor = ease_factor if (ease_factor and ease_factor >= 1.3) else 2.5
        self.last_review = float(last_review or 0.0)
        if self.last_review <= 0.0 and self.interval > 0.0 and self.due_date > 0.0:
            self.last_review = self.due_date - (self.interval * 86400.0)

    def get_next_intervals(self) -> Dict[int, str]:
        """Calculates precise human-readable intervals for Again, Hard, Good, Easy buttons under FSRS."""
        if self.state in ("new", "learning", "relearning"):
            ivl_good = FSRSEngine.next_interval(FSRSEngine.init_stability(3))
            ivl_easy = FSRSEngine.next_interval(FSRSEngine.init_stability(4))
            return {
                1: "< 1 min",
                2: "10 min",
                3: format_interval(ivl_good),
                4: format_interval(ivl_easy),
            }
        else:
            now = time.time()
            elapsed = max(0.1, (now - self.last_review) / 86400.0) if self.last_review > 0 else max(0.1, self.interval)
            r = FSRSEngine.retrievability(elapsed, self.stability)

            d_hard = FSRSEngine.next_difficulty(self.difficulty, 2)
            s_hard = FSRSEngine.next_stability(self.stability, d_hard, r, 2)
            ivl_hard = FSRSEngine.next_interval(s_hard)

            d_good = FSRSEngine.next_difficulty(self.difficulty, 3)
            s_good = FSRSEngine.next_stability(self.stability, d_good, r, 3)
            ivl_good = FSRSEngine.next_interval(s_good)

            d_easy = FSRSEngine.next_difficulty(self.difficulty, 4)
            s_easy = FSRSEngine.next_stability(self.stability, d_easy, r, 4)
            ivl_easy = FSRSEngine.next_interval(s_easy)

            return {
                1: "< 1 min",
                2: format_interval(ivl_hard),
                3: format_interval(ivl_good),
                4: format_interval(ivl_easy),
            }

    def schedule(self, rating: int, deck_name: str = ""):
        """
        FSRS spaced repetition algorithm.
        rating: 1 (Again), 2 (Hard), 3 (Good), 4 (Easy)
        """
        now = time.time()
        old_interval = self.interval
        old_difficulty = self.difficulty

        if self.state in ("new", "learning", "relearning"):
            if rating == 1:
                self.stability = FSRSEngine.init_stability(1)
                self.difficulty = FSRSEngine.init_difficulty(1)
                self.interval = 1.0 / 1440.0  # 1 minute
                self.lapses += 1
                self.state = "learning"
                self.due_date = now + 60.0
            elif rating == 2:
                self.stability = FSRSEngine.init_stability(2)
                self.difficulty = FSRSEngine.init_difficulty(2)
                self.interval = 10.0 / 1440.0 # 10 minutes
                self.state = "learning"
                self.due_date = now + 600.0
            elif rating == 3:
                self.stability = FSRSEngine.init_stability(3)
                self.difficulty = FSRSEngine.init_difficulty(3)
                self.repetitions = max(1, self.repetitions + 1)
                self.state = "review"
                self.interval = FSRSEngine.next_interval(self.stability)
                self.due_date = now + (self.interval * 86400.0)
            elif rating == 4:
                self.stability = FSRSEngine.init_stability(4)
                self.difficulty = FSRSEngine.init_difficulty(4)
                self.repetitions = max(1, self.repetitions + 1)
                self.state = "review"
                self.interval = FSRSEngine.next_interval(self.stability)
                self.due_date = now + (self.interval * 86400.0)
        else:
            elapsed = max(0.1, (now - self.last_review) / 86400.0) if self.last_review > 0 else max(0.1, self.interval)
            retrievability = FSRSEngine.retrievability(elapsed, self.stability)

            self.difficulty = FSRSEngine.next_difficulty(self.difficulty, rating)
            self.stability = FSRSEngine.next_stability(self.stability, self.difficulty, retrievability, rating)

            if rating == 1:
                self.lapses += 1
                self.repetitions = 0
                self.state = "relearning"
                self.interval = 1.0 / 1440.0
                self.due_date = now + 60.0
            else:
                self.repetitions += 1
                self.interval = FSRSEngine.next_interval(self.stability)
                self.due_date = now + (self.interval * 86400.0)

        self.last_review = now
        self.ease_factor = max(1.3, min(3.0, (11.0 - self.difficulty) / 2.4))

        # Persist to SQLite
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    UPDATE cards 
                    SET ease_factor = ?, interval = ?, repetitions = ?, lapses = ?, state = ?, due_date = ?,
                        stability = ?, difficulty = ?, last_review = ?
                    WHERE id = ?
                """, (self.ease_factor, self.interval, self.repetitions, self.lapses, self.state, self.due_date,
                      self.stability, self.difficulty, self.last_review, self.card_id))
                cur.execute("""
                    INSERT INTO review_logs (card_id, deck_name, card_front, rating, old_interval, new_interval, old_ease, new_ease, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (self.card_id, deck_name, self.front, rating, old_interval, self.interval, old_difficulty, self.difficulty, now))
                conn.commit()
        except Exception as e:
            print("Database save notice:", e)


# Compatibility alias
SM2Card = FSRSCard


# ==============================================================================
# Hardware-Accelerated 3D Flashcard Stage (Native GTK4 & GSK)
# ==============================================================================

class CardStage(Gtk.CenterBox):
    """
    Unified 3D Flashcard Stage container with hardware-accelerated 3D perspective transforms.
    Ensures:
      1. Content is rendered ON the card itself (single unified display system).
      2. Strict viewport clipping prevents card content or geometry from bleeding into
         the headerbar, window buttons, or rating buttons during translation/resizing.
      3. Smooth 60fps timer-driven 3D flip rotation and vertical arrival/departure slides.
      4. Geometric centering both vertically and horizontally in the render area.
    """
    def __init__(self, on_halfway_callback=None, on_settle_callback=None, on_resize_callback=None):
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_vexpand(True)
        self.set_hexpand(True)
        self.set_valign(Gtk.Align.FILL)
        self.set_halign(Gtk.Align.FILL)
        self.add_css_class("card-stage")

        self.rotation_y = 0.0
        self.target_rotation = 0.0
        self.offset_y = 0.0
        self.target_offset_y = 0.0
        self.is_flipped = False
        self.halfway_swapped = False
        self.depart_callback = None
        self.arrive_callback = None
        self.is_departing = False
        self.anim_timer = None
        self.on_halfway_callback = on_halfway_callback
        self.on_settle_callback = on_settle_callback
        self.on_resize_callback = on_resize_callback

        self._last_w = 0
        self._last_h = 0
        self.card_box = None

    def set_card_box(self, card_box: Gtk.Widget):
        self.card_box = card_box
        self.card_box.set_halign(Gtk.Align.CENTER)
        self.card_box.set_valign(Gtk.Align.CENTER)
        self.set_center_widget(card_box)

    def start_animation(self):
        if self.anim_timer is None:
            self.anim_timer = GLib.timeout_add(16, self._anim_tick)

    def flip(self):
        self.is_flipped = not self.is_flipped
        self.target_rotation = 180.0 if self.is_flipped else 0.0
        self.halfway_swapped = False
        self.start_animation()

    def reset_flip(self):
        if self.anim_timer is not None:
            GLib.source_remove(self.anim_timer)
            self.anim_timer = None
        self.is_flipped = False
        self.rotation_y = 0.0
        self.target_rotation = 0.0
        self.offset_y = 0.0
        self.target_offset_y = 0.0
        self.is_departing = False
        self.halfway_swapped = False
        self.queue_draw()

    def start_exit_down_animation(self, on_departed=None, on_arrived=None):
        """Animates card smoothly down out of the viewport."""
        self.depart_callback = on_departed
        self.arrive_callback = on_arrived
        self.is_departing = True
        h = max(250, self.get_height())
        self.target_offset_y = float(h + 80)
        self.start_animation()

    def start_enter_top_animation(self):
        """Teleports card above viewport and animates down to center."""
        h = max(250, self.get_height())
        self.offset_y = -float(h + 80)
        self.target_offset_y = 0.0
        self.start_animation()

    def _anim_tick(self):
        try:
            diff_r = self.target_rotation - self.rotation_y
            diff_y = self.target_offset_y - self.offset_y

            needs_draw = False

            # 1. Rotation animation step
            if abs(diff_r) > 0.1:
                step_r = diff_r * 0.22
                if abs(step_r) < 0.8:
                    step_r = 0.8 if diff_r > 0 else -0.8
                if abs(step_r) > abs(diff_r):
                    step_r = diff_r
                self.rotation_y += step_r
                needs_draw = True

                # Midpoint notification for front/back content swap
                if not self.halfway_swapped:
                    if (self.is_flipped and self.rotation_y >= 90.0) or (not self.is_flipped and self.rotation_y <= 90.0):
                        self.halfway_swapped = True
                        if self.on_halfway_callback:
                            try:
                                self.on_halfway_callback(self.is_flipped)
                            except Exception as ex:
                                print(f"Error in on_halfway_callback: {ex}")
            else:
                if self.rotation_y != self.target_rotation:
                    self.rotation_y = self.target_rotation
                    needs_draw = True

            # 2. Vertical slide animation step (exit down / enter top)
            if abs(diff_y) > 1.0:
                step_y = diff_y * 0.24
                if abs(step_y) < 2.0:
                    step_y = 2.0 if diff_y > 0 else -2.0
                if abs(step_y) > abs(diff_y):
                    step_y = diff_y
                self.offset_y += step_y
                needs_draw = True

                # Handle departure completion when card is well offscreen
                if self.is_departing and self.offset_y > (max(250, self.get_height()) * 0.65):
                    self.is_departing = False
                    if self.depart_callback:
                        cb = self.depart_callback
                        self.depart_callback = None
                        try:
                            cb()
                        except Exception as ex:
                            print(f"Error in depart_callback: {ex}")
                    self.start_enter_top_animation()
            else:
                if self.offset_y != self.target_offset_y:
                    self.offset_y = self.target_offset_y
                    needs_draw = True

                if self.arrive_callback and abs(self.target_offset_y) < 0.1 and abs(self.offset_y) < 2.0:
                    cb = self.arrive_callback
                    self.arrive_callback = None
                    try:
                        cb()
                    except Exception as ex:
                        print(f"Error in arrive_callback: {ex}")

            if needs_draw:
                self.queue_draw()

            # Check if all animation goals have settled
            settled_r = abs(self.target_rotation - self.rotation_y) < 0.05
            settled_y = abs(self.target_offset_y - self.offset_y) < 0.5
            if settled_r and settled_y and not self.is_departing:
                self.rotation_y = self.target_rotation
                self.offset_y = self.target_offset_y
                self.anim_timer = None
                self.queue_draw()
                if self.on_settle_callback:
                    try:
                        self.on_settle_callback(self.rotation_y, self.offset_y)
                    except Exception:
                        try:
                            self.on_settle_callback(self.is_flipped)
                        except Exception:
                            pass
                return GLib.SOURCE_REMOVE

            return GLib.SOURCE_CONTINUE
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.anim_timer = None
            return GLib.SOURCE_REMOVE

    def do_snapshot(self, snapshot):
        w = self.get_width()
        h = self.get_height()
        if w <= 0 or h <= 0 or not self.card_box:
            return

        if (w, h) != (self._last_w, self._last_h):
            self._last_w = w
            self._last_h = h
            if self.on_resize_callback:
                self.on_resize_callback(w, h)

        # 1. HARD VIEWPORT CLIPPING:
        # Crucial for preventing animated cards or oversized widgets from rendering
        # on top of the Libadwaita HeaderBar or bottom rating buttons!
        clip_rect = Graphene.Rect().init(0.0, 0.0, float(w), float(h))
        snapshot.push_clip(clip_rect)

        # 2. Fade opacity gracefully as card slides far offscreen
        dist_y = abs(self.offset_y)
        opacity = 1.0
        if dist_y > 20.0:
            opacity = max(0.0, min(1.0, 1.0 - ((dist_y - 20.0) / 240.0)))

        has_opacity = opacity < 0.999
        if has_opacity:
            snapshot.push_opacity(opacity)

        # 3. 3D Perspective + Vertical Slide Transform
        if GSK_TRANSFORM_AVAILABLE:
            cx = float(w) / 2.0
            cy = float(h) / 2.0

            snapshot.save()
            t = Gsk.Transform()
            if abs(self.offset_y) > 0.1:
                t = t.translate(Graphene.Point().init(0.0, float(self.offset_y)))

            t = t.translate(Graphene.Point().init(cx, cy))
            t = t.perspective(1000.0)
            vec_y = Graphene.Vec3().init(0.0, 1.0, 0.0)
            rot = self.rotation_y
            if rot <= 90.0:
                t = t.rotate_3d(rot, vec_y)
            else:
                t = t.rotate_3d(rot - 180.0, vec_y)

            t = t.translate(Graphene.Point().init(-cx, -cy))
            snapshot.transform(t)

            self.snapshot_child(self.card_box, snapshot)
            snapshot.restore()
        else:
            self.snapshot_child(self.card_box, snapshot)

        if has_opacity:
            snapshot.pop()

        snapshot.pop()


# ==============================================================================
# GNOME Libadwaita Main Application Window
# ==============================================================================

class DecksWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Decks - Spaced Repetition Flashcards")
        self.set_default_size(1060, 760)

        self.decks: List[Dict[str, str]] = []
        self.current_deck_id: Optional[str] = None
        self.active_study_queue: List[FSRSCard] = []
        self.current_card: Optional[FSRSCard] = None
        self.showing_answer: bool = False
        self.is_animating_card: bool = False
        self.current_card_w: int = 640
        self.current_card_h: int = 400
        self._resize_timer: Optional[int] = None
        self.rating_buttons: Dict[int, Gtk.Button] = {}

        # Daily goal configuration (Cards graduated into Good/Easy pile & daily limit)
        self.daily_goal: int = int(get_db_preference("daily_goal", "20"))
        self.daily_card_limit: int = int(get_db_preference("daily_card_limit", "50"))
        self.graduated_today: int = 0
        raw_reset_ts = get_db_preference("goal_tally_reset_timestamp", None)
        self.goal_tally_reset_timestamp: Optional[float] = float(raw_reset_ts) if raw_reset_ts else None

        # Setup Dynamic Libadwaita Theme Listener (Dark vs Light mode)
        self.style_manager = Adw.StyleManager.get_default()
        self.is_dark_mode: bool = self.style_manager.get_dark()

        # Initialize CSS provider
        self.css_provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            self.css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
        self.apply_custom_css(self.is_dark_mode)

        # Connect theme toggle listener so window dynamically updates when GNOME theme changes
        self.style_manager.connect("notify::dark", self.on_theme_changed)

        # Window action for closing with Ctrl+W
        action_close = Gio.SimpleAction.new("close-window", None)
        action_close.connect("activate", lambda a, p: self.close())
        self.add_action(action_close)

        self.setup_ui()
        self.load_decks_from_db()
        self.update_streak_badge()
        self.update_goal_progress()

    def on_theme_changed(self, style_manager, pspec):
        is_dark = style_manager.get_dark()
        if self.is_dark_mode == is_dark:
            return
        self.is_dark_mode = is_dark
        self.apply_custom_css(is_dark)
        if hasattr(self, 'card_stage') and self.card_stage:
            self.card_stage.queue_draw()
        if self.current_card:
            self.update_card_ui_content(self.showing_answer)

    def apply_custom_css(self, is_dark: bool = True):
        custom_css = f"""
        .card-stage {{
            background-color: {"#1e1e1e" if is_dark else "#fafafa"};
        }}
        .study-card {{
            background-color: {"#252528" if is_dark else "#ffffff"};
            border: {"1px solid rgba(255, 255, 255, 0.12)" if is_dark else "1px solid rgba(0, 0, 0, 0.10)"};
            border-radius: 16px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, {"0.35" if is_dark else "0.10"});
            padding: 24px 36px;
        }}
        .study-card.card-back {{
            background-color: {"#1a2434" if is_dark else "#f0f6ff"};
            border: {"1px solid rgba(53, 132, 228, 0.35)" if is_dark else "1px solid rgba(53, 132, 228, 0.25)"};
        }}
        .card-text-scroll, .card-text-scroll viewport {{
            background: transparent;
            border: none;
            box-shadow: none;
            outline: none;
        }}
        .card-badge {{
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 9999px;
            letter-spacing: 0.5px;
            background: {"rgba(255, 255, 255, 0.14)" if is_dark else "rgba(0, 0, 0, 0.07)"};
            color: {"#dddddd" if is_dark else "#2e3436"};
        }}
        .touch-action-button {{
            min-height: 56px;
            border-radius: 14px;
            font-size: 15px;
            font-weight: bold;
            padding: 10px 24px;
        }}
        .btn-again {{
            background: {"rgba(237, 51, 59, 0.22)" if is_dark else "rgba(237, 51, 59, 0.12)"};
            color: {"#ff7b63" if is_dark else "#c01c28"};
            border: 1px solid {"rgba(237, 51, 59, 0.50)" if is_dark else "rgba(237, 51, 59, 0.38)"};
        }}
        .btn-again:hover {{
            background: {"rgba(237, 51, 59, 0.35)" if is_dark else "rgba(237, 51, 59, 0.22)"};
        }}
        .btn-hard {{
            background: {"rgba(245, 194, 17, 0.20)" if is_dark else "rgba(245, 194, 17, 0.15)"};
            color: {"#f8e45c" if is_dark else "#8f6100"};
            border: 1px solid {"rgba(245, 194, 17, 0.50)" if is_dark else "rgba(245, 194, 17, 0.40)"};
        }}
        .btn-hard:hover {{
            background: {"rgba(245, 194, 17, 0.32)" if is_dark else "rgba(245, 194, 17, 0.25)"};
        }}
        .btn-good {{
            background: {"rgba(87, 227, 137, 0.22)" if is_dark else "rgba(46, 194, 126, 0.14)"};
            color: {"#57e389" if is_dark else "#1b7a44"};
            border: 1px solid {"rgba(87, 227, 137, 0.50)" if is_dark else "rgba(46, 194, 126, 0.38)"};
        }}
        .btn-good:hover {{
            background: {"rgba(87, 227, 137, 0.35)" if is_dark else "rgba(46, 194, 126, 0.24)"};
        }}
        .btn-easy {{
            background: {"rgba(53, 132, 228, 0.22)" if is_dark else "rgba(53, 132, 228, 0.12)"};
            color: {"#78aeed" if is_dark else "#1c71d8"};
            border: 1px solid {"rgba(53, 132, 228, 0.50)" if is_dark else "rgba(53, 132, 228, 0.38)"};
        }}
        .btn-easy:hover {{
            background: {"rgba(53, 132, 228, 0.35)" if is_dark else "rgba(53, 132, 228, 0.22)"};
        }}
        .streak-pill {{
            background: {"rgba(255, 120, 0, 0.16)" if is_dark else "rgba(255, 120, 0, 0.12)"};
            color: {"#ff9933" if is_dark else "#b84800"};
            border: 1px solid {"rgba(255, 120, 0, 0.35)" if is_dark else "rgba(255, 120, 0, 0.30)"};
            font-weight: bold;
            border-radius: 9999px;
            padding: 4px 12px;
        }}
        .stat-card {{
            background-color: {"#242424" if is_dark else "#ffffff"};
            border: 1px solid {"#383838" if is_dark else "#dfdfdf"};
            border-radius: 16px;
            padding: 18px;
            box-shadow: { "none" if is_dark else "0 1px 3px rgba(0, 0, 0, 0.05)" };
        }}
        progressbar.top-progress-bar trough {{
            min-height: 4px;
            border-radius: 0;
            background-color: {"#252525" if is_dark else "#e4e4e4"};
            border: none;
        }}
        progressbar.top-progress-bar progress {{
            background-color: #3584e4;
            border-radius: 0;
        }}
        preferencesgroup {{
            margin-top: 10px;
            margin-bottom: 20px;
        }}
        actionrow {{
            min-height: 54px;
            padding-top: 6px;
            padding-bottom: 6px;
        }}
        """
        self.css_provider.load_from_data(custom_css.encode('utf-8'))

    def setup_ui(self):
        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root_box)

        # ----------------------------------------------------------------------
        # 1. HeaderBar with ViewSwitcher, Streak Counter & Deck Selector
        # ----------------------------------------------------------------------
        header = Adw.HeaderBar()
        root_box.append(header)

        # Deck Selector Dropdown
        self.deck_dropdown = Gtk.DropDown()
        self.deck_dropdown.connect("notify::selected-item", self.on_deck_changed)
        header.pack_start(self.deck_dropdown)

        # Add Deck Button
        btn_add_deck = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Create New Deck")
        btn_add_deck.connect("clicked", self.on_add_deck_clicked)
        header.pack_start(btn_add_deck)

        # Import CSV Button
        btn_import = Gtk.Button(icon_name="document-open-symbolic", tooltip_text="Import Cards (CSV/TSV)")
        btn_import.connect("clicked", self.on_import_csv)
        header.pack_start(btn_import)

        # Export Current Deck to CSV Button
        self.btn_export_deck = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Export Current Deck to CSV")
        self.btn_export_deck.connect("clicked", self.on_export_current_deck_csv)
        header.pack_start(self.btn_export_deck)

        # Delete Current Deck Button
        btn_del_deck = Gtk.Button(icon_name="user-trash-symbolic", tooltip_text="Delete Current Deck")
        btn_del_deck.connect("clicked", self.on_delete_current_deck_clicked)
        header.pack_start(btn_del_deck)

        # View Switcher in the Center of HeaderBar
        self.view_stack = Adw.ViewStack()
        self.view_switcher = Adw.ViewSwitcher(stack=self.view_stack, policy=Adw.ViewSwitcherPolicy.WIDE)
        header.set_title_widget(self.view_switcher)

        # Top Right Action Buttons:
        # In GTK4 pack_end, widgets are positioned from right to left.
        # 1. About Decks Button (Rightmost)
        btn_about = Gtk.Button(icon_name="help-about-symbolic", tooltip_text="About Decks")
        btn_about.connect("clicked", self.show_about_dialog)
        header.pack_end(btn_about)

        # Settings Button (Preferences & Daily Goals)
        self.btn_settings = Gtk.Button(icon_name="emblem-system-symbolic", tooltip_text="Preferences & Daily Goals")
        self.btn_settings.connect("clicked", self.on_open_preferences_dialog)
        header.pack_end(self.btn_settings)

        # Study Streak Badge (Leftmost in top-right group)
        self.btn_streak = Gtk.Button()
        self.btn_streak.add_css_class("streak-pill")
        self.btn_streak.set_tooltip_text("Continuous Daily Study Streak")
        self.btn_streak.connect("clicked", lambda b: self.view_stack.set_visible_child_name("stats"))
        header.pack_end(self.btn_streak)

        # ----------------------------------------------------------------------
        # Daily Goal Progress Bar (Spanning entire top width, label centered underneath)
        # ----------------------------------------------------------------------
        self.goal_progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.goal_progress_box.set_margin_start(0)
        self.goal_progress_box.set_margin_end(0)
        self.goal_progress_box.set_margin_top(0)
        self.goal_progress_box.set_margin_bottom(6)
        self.goal_progress_box.set_hexpand(True)

        self.goal_progress_bar = Gtk.ProgressBar()
        self.goal_progress_bar.set_hexpand(True)
        self.goal_progress_bar.set_show_text(False)
        self.goal_progress_bar.add_css_class("top-progress-bar")
        self.goal_progress_box.append(self.goal_progress_bar)

        self.lbl_goal_status = Gtk.Label(
            label="Daily Goal: 0/20 graduated (Good/Easy) • 0%", 
            halign=Gtk.Align.CENTER
        )
        self.lbl_goal_status.set_css_classes(["caption", "dim-label"])
        self.lbl_goal_status.set_hexpand(True)
        self.lbl_goal_status.set_justify(Gtk.Justification.CENTER)
        self.goal_progress_box.append(self.lbl_goal_status)

        root_box.append(self.goal_progress_box)

        # ----------------------------------------------------------------------
        # 2. ViewStack Pages: Study, Browse, and Stats
        # ----------------------------------------------------------------------
        root_box.append(self.view_stack)

        # Page 1: Study View
        self.page_study = self.build_study_view()
        self.view_stack.add_titled(self.page_study, "study", "Study").set_icon_name("media-playback-start-symbolic")

        # Page 2: Browse Cards View
        self.page_browse = self.build_browse_view()
        self.view_stack.add_titled(self.page_browse, "browse", "Browse").set_icon_name("view-list-symbolic")

        # Page 3: Statistics View
        self.page_stats = self.build_stats_view()
        self.view_stack.add_titled(self.page_stats, "stats", "Stats").set_icon_name("utilities-system-monitor-symbolic")

        # Connect stack change to refresh views
        self.view_stack.connect("notify::visible-child-name", self.on_view_changed)

        # Global Keyboard Controller (Space/Enter to flip, 1-4 to rate)
        key_controller = Gtk.EventControllerKey()
        key_controller.connect("key-pressed", self.on_key_pressed)
        self.add_controller(key_controller)

    # ==========================================================================
    # Study View Implementation (Unified 3D Card + Perspective Content Mapping)
    # ==========================================================================

    def build_study_view(self) -> Gtk.Widget:
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_vexpand(True)

        # 3D Card Presentation Stage
        self.card_stage = CardStage(
            on_halfway_callback=self.on_halfway_flip,
            on_settle_callback=self.on_stage_settle,
            on_resize_callback=self.on_stage_resized
        )

        # Stage click gesture: allows clicking outside the card box on the stage to flip
        stage_gesture = Gtk.GestureClick()
        stage_gesture.connect("pressed", self.on_stage_clicked)
        self.card_stage.add_controller(stage_gesture)

        # The Flashcard Widget itself (Single unified widget with native CSS card styling)
        self.card_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.card_box.add_css_class("study-card")
        self.card_box.set_halign(Gtk.Align.CENTER)
        self.card_box.set_valign(Gtk.Align.CENTER)
        self.card_box.set_hexpand(False)
        self.card_box.set_vexpand(False)
        self.card_box.set_size_request(self.current_card_w, self.current_card_h)

        # Primary card surface click gesture
        card_gesture = Gtk.GestureClick()
        card_gesture.connect("pressed", self.on_card_clicked_to_flip)
        self.card_box.add_controller(card_gesture)

        # Top Bar inside Card: Badge + Copy Question Button
        card_top_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        card_top_bar.set_hexpand(True)

        self.badge_side = Gtk.Label(label="QUESTION")
        self.badge_side.add_css_class("pill")
        self.badge_side.add_css_class("card-badge")
        card_top_bar.append(self.badge_side)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        card_top_bar.append(spacer)

        # Copy Question Text Button
        self.btn_copy_question = Gtk.Button(label="Copy Question", icon_name="edit-copy-symbolic")
        self.btn_copy_question.set_tooltip_text("Copy question text to clipboard for research")
        self.btn_copy_question.connect("clicked", self.on_copy_question_clicked)
        card_top_bar.append(self.btn_copy_question)

        self.card_box.append(card_top_bar)

        content_w = max(240, self.current_card_w - 60)
        content_h = max(80, self.current_card_h - 110)

        # Main Question / Answer text wrapped in transparent ScrolledWindow for large contents
        self.card_scroll = Gtk.ScrolledWindow()
        self.card_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.card_scroll.set_hexpand(False)
        self.card_scroll.set_vexpand(True)
        self.card_scroll.set_propagate_natural_height(False)
        self.card_scroll.set_propagate_natural_width(False)
        self.card_scroll.set_size_request(content_w, content_h)
        self.card_scroll.add_css_class("card-text-scroll")

        self.label_card_text = Gtk.Label(label="Loading collection...", wrap=True, justify=Gtk.Justification.CENTER)
        self.label_card_text.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.label_card_text.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
        self.label_card_text.set_hexpand(False)
        self.label_card_text.set_vexpand(True)
        self.label_card_text.set_halign(Gtk.Align.CENTER)
        self.label_card_text.set_valign(Gtk.Align.CENTER)
        self.label_card_text.set_xalign(0.5)
        self.label_card_text.set_yalign(0.5)
        self.label_card_text.set_size_request(content_w, -1)
        self.card_scroll.set_child(self.label_card_text)
        self.card_box.append(self.card_scroll)

        # Subtext & SM-2 status
        self.label_subtext = Gtk.Label(label="", wrap=True, justify=Gtk.Justification.CENTER)
        self.label_subtext.add_css_class("caption")
        self.card_box.append(self.label_subtext)

        self.card_stage.set_card_box(self.card_box)
        container.append(self.card_stage)

        # Rating & Flip Bottom Controls Bar
        bottom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        bottom_box.set_margin_bottom(24)
        bottom_box.set_margin_top(8)

        # Large Touch-friendly "Show Answer" Button
        self.btn_flip = Gtk.Button(label="Show Answer (Space)", icon_name="view-reveal-symbolic")
        self.btn_flip.add_css_class("suggested-action")
        self.btn_flip.add_css_class("touch-action-button")
        self.btn_flip.set_halign(Gtk.Align.CENTER)
        self.btn_flip.set_size_request(280, 56)
        self.btn_flip.connect("clicked", lambda b: self.do_flip())
        bottom_box.append(self.btn_flip)

        # 4 Large SM-2 Rating Buttons (Again, Hard, Good, Easy)
        self.rating_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        self.rating_box.set_halign(Gtk.Align.CENTER)

        ratings_spec = [
            ("Again (1)\n< 1 min", 1, "btn-again"),
            ("Hard (2)\n6 min",   2, "btn-hard"),
            ("Good (3)\n1 day",   3, "btn-good"),
            ("Easy (4)\n4 days",  4, "btn-easy"),
        ]
        self.rating_buttons = {}
        for label, rating_val, css_cls in ratings_spec:
            btn = Gtk.Button(label=label)
            btn.add_css_class(css_cls)
            btn.add_css_class("touch-action-button")
            btn.set_size_request(140, 56)
            btn.connect("clicked", lambda b, r=rating_val: self.on_rate(r))
            self.rating_buttons[rating_val] = btn
            self.rating_box.append(btn)

        bottom_box.append(self.rating_box)
        container.append(bottom_box)

        return container

    def on_card_clicked_to_flip(self, gesture, n_press, x, y):
        # 1. Coordinate bounds check: Ignore click if it happened inside btn_copy_question
        try:
            ok, rect = self.btn_copy_question.compute_bounds(self.card_box)
            if ok:
                bx = rect.origin.x
                by = rect.origin.y
                bw = rect.size.width
                bh = rect.size.height
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    return
        except Exception:
            pass

        # 2. Hierarchy check: Ignore click if picked widget is btn_copy_question or child
        try:
            picked = self.card_box.pick(x, y, 0)
            w = picked
            while w and w != self.card_box:
                if w == self.btn_copy_question:
                    return
                w = w.get_parent()
        except Exception:
            pass

        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        self.do_flip()

    def on_stage_clicked(self, gesture, n_press, x, y):
        try:
            ok, rect = self.card_box.compute_bounds(self.card_stage)
            if ok:
                bx = rect.origin.x
                by = rect.origin.y
                bw = rect.size.width
                bh = rect.size.height
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    # Inside the card box: let card_gesture handle it
                    return
        except Exception:
            pass
        self.do_flip()

    def on_stage_resized(self, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        if self._resize_timer is not None:
            GLib.source_remove(self._resize_timer)
        self._resize_timer = GLib.timeout_add(35, self._debounced_resize, width, height)

    def _debounced_resize(self, width: int, height: int):
        self._resize_timer = None
        self.recompute_card_layout(width, height)
        return GLib.SOURCE_REMOVE

    def recompute_card_layout(self, width: int, height: int):
        if width <= 0 or height <= 0:
            return
        available_h = max(140, height - 32)
        target_h = max(140, min(int(available_h * 0.86), 480))
        target_w = min(int(target_h * 1.54), max(260, width - 48))
        target_h = min(target_h, max(140, int(target_w / 1.40)))

        target_w = (target_w // 2) * 2
        target_h = (target_h // 2) * 2

        self.current_card_w = target_w
        self.current_card_h = target_h

        content_w = max(240, target_w - 60)
        content_h = max(80, target_h - 110)

        self.card_box.set_size_request(target_w, target_h)
        self.card_scroll.set_size_request(content_w, content_h)
        self.label_card_text.set_size_request(content_w, -1)

        if self.current_card:
            text = self.current_card.back if self.showing_answer else self.current_card.front
            has_multiline = "\n" in text or bool(re.search(r'^[*\-+]\s|^#|\$\$|```', text, re.MULTILINE))
            if has_multiline:
                self.label_card_text.set_justify(Gtk.Justification.LEFT)
                self.label_card_text.set_xalign(0.0)
            else:
                self.label_card_text.set_justify(Gtk.Justification.CENTER)
                self.label_card_text.set_xalign(0.5)
            self.label_card_text.set_markup(self.get_card_font_markup(text))

        return GLib.SOURCE_REMOVE

    # ==========================================================================
    # Browse Cards View Implementation
    # ==========================================================================

    def build_browse_view(self) -> Gtk.Widget:
        container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        container.set_vexpand(True)
        container.set_hexpand(True)

        # Persistent Top Header Bar / Sticky Toolbar
        # Remains stationary at the top while the list of cards scrolls beneath it
        header_bar_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        header_bar_box.set_margin_top(16)
        header_bar_box.set_margin_bottom(12)
        header_bar_box.set_margin_start(24)
        header_bar_box.set_margin_end(24)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

        self.search_entry = Gtk.SearchEntry()
        self.search_entry.set_property("placeholder-text", "Search questions, answers, notes...")
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("search-changed", self.on_search_changed)
        toolbar.append(self.search_entry)

        # New Card Button
        btn_new_card = Gtk.Button(label="New Card", icon_name="list-add-symbolic")
        btn_new_card.add_css_class("suggested-action")
        btn_new_card.connect("clicked", self.on_new_card_dialog)
        toolbar.append(btn_new_card)

        # Edit Selected Card Button
        self.btn_edit_card = Gtk.Button(label="Edit Card", icon_name="document-edit-symbolic")
        self.btn_edit_card.set_sensitive(False)
        self.btn_edit_card.connect("clicked", self.on_edit_selected_card)
        toolbar.append(self.btn_edit_card)

        # Reset Card Progress Button
        self.btn_reset_card = Gtk.Button(label="Reset Progress", icon_name="view-refresh-symbolic")
        self.btn_reset_card.set_tooltip_text("Reset interval and repetitions for selected card(s)")
        self.btn_reset_card.connect("clicked", self.on_reset_selected_card)
        toolbar.append(self.btn_reset_card)

        # Delete Selected Card Button
        self.btn_del_card = Gtk.Button(label="Delete Card", icon_name="user-trash-symbolic")
        self.btn_del_card.add_css_class("destructive-action")
        self.btn_del_card.connect("clicked", self.on_delete_selected_card)
        toolbar.append(self.btn_del_card)

        header_bar_box.append(toolbar)

        # Total count label
        self.lbl_browse_count = Gtk.Label(label="Showing 0 cards • Hold Ctrl+M1 to multi-select, Shift+M1 for range", halign=Gtk.Align.START)
        self.lbl_browse_count.add_css_class("dim-label")
        header_bar_box.append(self.lbl_browse_count)

        # Divider separating sticky header from scrollable list
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        header_bar_box.append(sep)

        container.append(header_bar_box)

        # Scrollable Cards List Area
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        list_wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_wrap.set_margin_start(24)
        list_wrap.set_margin_end(24)
        list_wrap.set_margin_bottom(24)

        # Cards List Box: selection controlled via GestureClick
        # Requires Ctrl+M1 to toggle multi-selection and Shift+M1 for range selection
        self.browse_list_box = Gtk.ListBox()
        self.browse_list_box.set_selection_mode(Gtk.SelectionMode.MULTIPLE)
        self.browse_list_box.connect("selected-rows-changed", self.on_browse_selection_changed)
        self.browse_list_box.add_css_class("boxed-list")

        self.browse_last_selected_index: Optional[int] = None

        click_controller = Gtk.GestureClick.new()
        click_controller.set_button(1)
        click_controller.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click_controller.connect("pressed", self.on_browse_list_click)
        self.browse_list_box.add_controller(click_controller)

        list_wrap.append(self.browse_list_box)

        scrolled.set_child(list_wrap)
        container.append(scrolled)

        return container

    def on_browse_list_click(self, gesture, n_press, x, y):
        row = self.browse_list_box.get_row_at_y(int(y))
        if not row:
            return

        current_idx = row.get_index()
        state = gesture.get_current_event_state()
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        is_shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if is_shift and self.browse_last_selected_index is not None:
            # Shift+M1: Select a contiguous range of rows
            start = min(self.browse_last_selected_index, current_idx)
            end = max(self.browse_last_selected_index, current_idx)
            self.browse_list_box.unselect_all()
            for i in range(start, end + 1):
                r = self.browse_list_box.get_row_at_index(i)
                if r:
                    self.browse_list_box.select_row(r)
        elif is_ctrl:
            # Ctrl+M1: Toggle selection on this specific row
            if row.is_selected():
                self.browse_list_box.unselect_row(row)
            else:
                self.browse_list_box.select_row(row)
            self.browse_last_selected_index = current_idx
        else:
            # Plain M1 click (no Ctrl or Shift):
            # Select ONLY this row, clearing any other multi-selected rows
            self.browse_list_box.unselect_all()
            self.browse_list_box.select_row(row)
            self.browse_last_selected_index = current_idx

        # Claim gesture so default multiple auto-toggle does not fire
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    # ==========================================================================
    # Statistics View Implementation
    # ==========================================================================

    def build_stats_view(self) -> Gtk.Widget:
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_hexpand(True)

        # Responsive Adw.Clamp ensures fluid scaling across any window dimensions
        clamp = Adw.Clamp()
        clamp.set_maximum_size(980)
        clamp.set_tightening_threshold(680)
        clamp.set_hexpand(True)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        box.set_margin_top(24)
        box.set_margin_bottom(36)
        box.set_margin_start(20)
        box.set_margin_end(20)
        clamp.set_child(box)
        scrolled.set_child(clamp)

        # Header Title
        lbl_stats_title = Gtk.Label(label="Spaced Repetition Analytics", halign=Gtk.Align.START)
        lbl_stats_title.add_css_class("title-2")
        box.append(lbl_stats_title)

        # Responsive 3-column x 2-row Grid for Metric Cards
        metrics_grid = Gtk.Grid()
        metrics_grid.set_column_spacing(14)
        metrics_grid.set_row_spacing(14)
        metrics_grid.set_column_homogeneous(True)
        metrics_grid.set_row_homogeneous(False)
        metrics_grid.set_hexpand(True)

        # 1. Streak Card
        self.card_streak_val = Gtk.Label(label="0 days")
        self.card_streak_val.add_css_class("title-1")
        card_streak = self.create_stat_card("STUDY STREAK", self.card_streak_val, "Consecutive daily sessions")
        metrics_grid.attach(card_streak, 0, 0, 1, 1)

        # 2. Today Reviews
        self.card_today_val = Gtk.Label(label="0")
        self.card_today_val.add_css_class("title-1")
        card_today = self.create_stat_card("TODAY REVIEWS", self.card_today_val, "Reviews completed today")
        metrics_grid.attach(card_today, 1, 0, 1, 1)

        # 3. Retention Rate
        self.card_retention_val = Gtk.Label(label="95%")
        self.card_retention_val.add_css_class("title-1")
        card_retention = self.create_stat_card("RETENTION RATE", self.card_retention_val, "Recall accuracy (Good / Easy)")
        metrics_grid.attach(card_retention, 2, 0, 1, 1)

        # 4. Mature Cards
        self.card_mature_val = Gtk.Label(label="0")
        self.card_mature_val.add_css_class("title-1")
        card_mature = self.create_stat_card("MATURE CARDS", self.card_mature_val, "21+ days interval retention")
        metrics_grid.attach(card_mature, 0, 1, 1, 1)

        # 5. Average Difficulty (FSRS)
        self.card_ease_val = Gtk.Label(label="5.0 / 10")
        self.card_ease_val.add_css_class("title-1")
        card_ease = self.create_stat_card("AVG DIFFICULTY", self.card_ease_val, "FSRS memory difficulty (1.0–10.0)")
        metrics_grid.attach(card_ease, 1, 1, 1, 1)

        # 6. Total Cards in Deck
        self.card_total_val = Gtk.Label(label="0")
        self.card_total_val.add_css_class("title-1")
        card_total = self.create_stat_card("COLLECTION SIZE", self.card_total_val, "Total active flashcards")
        metrics_grid.attach(card_total, 2, 1, 1, 1)

        box.append(metrics_grid)

        # Card Maturity Breakdown
        lbl_breakdown = Gtk.Label(label="Card Maturity Breakdown", halign=Gtk.Align.START)
        lbl_breakdown.add_css_class("title-4")
        box.append(lbl_breakdown)

        self.box_breakdown = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.box_breakdown.add_css_class("boxed-list")
        box.append(self.box_breakdown)

        # Recent Review Audit Trail
        lbl_audit = Gtk.Label(label="Recent Review Audit Trail", halign=Gtk.Align.START)
        lbl_audit.add_css_class("title-4")
        box.append(lbl_audit)

        self.box_audit_logs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.box_audit_logs.add_css_class("boxed-list")
        box.append(self.box_audit_logs)

        return scrolled

    def create_stat_card(self, title: str, val_widget: Gtk.Widget, subtitle: str) -> Gtk.Widget:
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        c.add_css_class("stat-card")
        c.set_hexpand(True)

        lbl_t = Gtk.Label(label=title, halign=Gtk.Align.START)
        lbl_t.add_css_class("caption")
        lbl_t.add_css_class("dim-label")
        c.append(lbl_t)

        val_widget.set_halign(Gtk.Align.START)
        c.append(val_widget)

        lbl_s = Gtk.Label(label=subtitle, halign=Gtk.Align.START)
        lbl_s.set_wrap(True)
        lbl_s.set_wrap_mode(Pango.WrapMode.WORD)
        lbl_s.add_css_class("caption")
        c.append(lbl_s)
        return c

    # ==========================================================================
    # State Synchronization & Database Operations
    # ==========================================================================

    def load_decks_from_db(self):
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, name, description FROM decks ORDER BY name")
            rows = cur.fetchall()

        self.decks = [{"id": r[0], "name": r[1], "desc": r[2]} for r in rows]
        string_list = Gtk.StringList()
        for d in self.decks:
            string_list.append(d["name"])
        self.deck_dropdown.set_model(string_list)

        if self.decks:
            self.current_deck_id = self.decks[0]["id"]
            self.load_cards_for_deck(self.current_deck_id)
        else:
            self.current_deck_id = None
        if hasattr(self, 'btn_export_deck'):
            self.btn_export_deck.set_sensitive(bool(self.decks))

    def on_deck_changed(self, dropdown, param):
        idx = dropdown.get_selected()
        if 0 <= idx < len(self.decks):
            self.current_deck_id = self.decks[idx]["id"]
            self.load_cards_for_deck(self.current_deck_id)
            if self.view_stack.get_visible_child_name() == "browse":
                self.refresh_browse_view()
        if hasattr(self, 'btn_export_deck'):
            self.btn_export_deck.set_sensitive(bool(self.current_deck_id))

    def load_cards_for_deck(self, deck_id: str):
        now = time.time()
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, deck_id, front, back, notes, ease_factor, interval, repetitions, lapses, state, due_date, stability, difficulty, last_review
                FROM cards WHERE deck_id = ?
            """, (deck_id,))
            rows = cur.fetchall()

        all_cards = [FSRSCard(*r) for r in rows]

        # Prioritize study queues with randomness:
        # 1. Learning cards that are due first (due_date ASC)
        learning_cards = [c for c in all_cards if c.state in ("learning", "relearning")]
        learning_cards.sort(key=lambda c: c.due_date)

        # 2. Due review cards (due now or today) - shuffled randomly for varied review order!
        due_reviews = [c for c in all_cards if c.state == "review" and c.due_date <= (now + 300)]
        random.shuffle(due_reviews)

        # 3. New cards (never reviewed) - randomized with random.shuffle so presentation isn't static
        new_cards = [c for c in all_cards if c.state == "new" or c.repetitions == 0]
        random.shuffle(new_cards)

        # Primary session queue
        queue = learning_cards + due_reviews + new_cards

        # If all due cards are completed, load entire deck in random order for open practice
        if not queue and all_cards:
            queue = list(all_cards)
            random.shuffle(queue)

        # Apply daily study card limit if configured (> 0)
        if self.daily_card_limit > 0 and len(queue) > self.daily_card_limit:
            queue = queue[:self.daily_card_limit]

        self.active_study_queue = queue
        self.showing_answer = False
        if hasattr(self, 'card_stage'):
            self.card_stage.reset_flip()
        self.next_study_card()

    def next_study_card(self):
        self.showing_answer = False
        if hasattr(self, 'card_stage'):
            self.card_stage.reset_flip()

        if not self.active_study_queue:
            self.current_card = None
            self.update_card_ui_content(is_back=False)
            return

        self.current_card = self.active_study_queue.pop(0)
        self.update_card_ui_content(is_back=False)

    def practice_deck_again(self):
        if not self.current_deck_id:
            return
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, deck_id, front, back, notes, ease_factor, interval, repetitions, lapses, state, due_date, stability, difficulty, last_review
                FROM cards WHERE deck_id = ?
            """, (self.current_deck_id,))
            rows = cur.fetchall()
        if not rows:
            return
        all_cards = [FSRSCard(*r) for r in rows]
        random.shuffle(all_cards)
        self.active_study_queue = all_cards
        self.next_study_card()

    def update_streak_badge(self):
        streak, best_streak, studied_today = calculate_streak_from_db()
        streak_text = f"🔥 {streak} Days" if streak > 0 else "🔥 0 Days"
        self.btn_streak.set_label(streak_text)
        if hasattr(self, 'card_streak_val'):
            self.card_streak_val.set_text(f"{streak} days (Best: {best_streak})")

    def on_view_changed(self, stack, param):
        name = stack.get_visible_child_name()
        if name == "browse":
            self.refresh_browse_view()
        elif name == "stats":
            self.refresh_stats_view()

    # ==========================================================================
    # Study Loop & Unified Card Flip Handling
    # ==========================================================================

    def do_flip(self):
        if self.is_animating_card:
            return
        if not self.current_card:
            self.practice_deck_again()
            return
        self.card_stage.flip()

    def on_halfway_flip(self, is_back: bool):
        self.showing_answer = is_back
        self.update_card_ui_content(is_back)

    def on_stage_settle(self, *args, **kwargs):
        pass

    def _on_card_departed(self):
        self.next_study_card()

    def _on_card_arrived(self):
        self.is_animating_card = False
        self.btn_flip.set_sensitive(True)
        if self.current_card:
            self.rating_box.set_sensitive(True)

    def _safety_unlock_ui(self):
        if self.is_animating_card:
            self._on_card_arrived()
        return GLib.SOURCE_REMOVE

    def get_card_font_markup(self, text: str) -> str:
        """
        Dynamically scales card font size in Pango units based on text length,
        character density, and card box bounds:
        - Single/few characters (e.g. Japanese kana/kanji like 'ぞ', 'だ', 'た'):
          Displays prominently (56pt-68pt) with crisp contrast.
        - Longer multi-line answers with Markdown headers, bullet points, code blocks,
          and LaTeX formulas: auto-scales progressively so content fits comfortably
          within the card boundary while preserving formatting.
        """
        clean_text = text.strip() if text else ""
        if not clean_text:
            return ""

        available_w = max(260, self.current_card_w - 72)
        available_h = max(130, self.current_card_h - 130)
        char_count = len(clean_text)

        # Count effective lines
        lines = clean_text.splitlines()

        # Baseline point size by character length and line count
        if len(lines) > 4 or char_count > 140:
            pt = 16
        elif len(lines) > 2 or char_count > 80:
            pt = 19
        elif char_count <= 3:
            pt = 66
        elif char_count <= 8:
            pt = 46
        elif char_count <= 18:
            pt = 34
        elif char_count <= 35:
            pt = 26
        elif char_count <= 70:
            pt = 22
        elif char_count <= 120:
            pt = 18
        else:
            pt = 16

        # Progressively auto-scale down until the text fits cleanly
        while pt > 11:
            total_wraps = 0
            for line in lines:
                if not line:
                    total_wraps += 1
                    continue
                # Strip Markdown/LaTeX markers for metric estimation
                stripped_line = re.sub(r'[*_#`~=\$\\\<>]', '', line)
                cjk_chars = sum(1 for c in stripped_line if ord(c) > 0x2E80)
                latin_chars = len(stripped_line) - cjk_chars
                line_pixels = (cjk_chars * pt * 1.20) + (latin_chars * pt * 0.60)
                wraps = max(1, math.ceil(line_pixels / max(220, available_w - 16)))
                total_wraps += wraps

            line_height = pt * 1.45
            total_height = total_wraps * line_height

            if len(lines) <= 4:
                if total_wraps <= 4 and total_height <= available_h:
                    break
            else:
                if total_height <= available_h:
                    break
            pt -= 1

        pango_size = pt * 1024

        # Render Markdown and LaTeX math
        rendered_content = MarkdownMathParser.render_markdown_and_math(clean_text, is_dark=self.is_dark_mode)

        has_rich = bool(re.search(r'[*_#`~=\$\\\<]', clean_text)) or "\n" in clean_text
        if char_count <= 8 and not has_rich:
            final_markup = f"<span size='{pango_size}' weight='bold'>{rendered_content}</span>"
        else:
            final_markup = f"<span size='{pango_size}'>{rendered_content}</span>"

        # Verify markup validity with Pango
        try:
            ok, _, _, _ = Pango.parse_markup(final_markup, -1, '\0')
            if ok:
                return final_markup
        except Exception:
            pass

        # Safe fallback in case of malformed custom tags
        escaped = GLib.markup_escape_text(clean_text)
        return f"<span size='{pango_size}'>{escaped}</span>"

    def update_card_ui_content(self, is_back: bool):
        dim_color = "#5e5c64" if not self.is_dark_mode else "#aaaaaa"
        if not self.current_card:
            self.badge_side.set_visible(False)
            self.btn_copy_question.set_visible(False)
            self.label_card_text.set_markup(
                "<span size='24000' weight='bold'>🎉 Deck Complete!</span>\n\n"
                f"<span size='14000' color='{dim_color}'>You have reviewed all due cards for this deck today.</span>"
            )
            self.label_subtext.set_text("Great job! Click below to practice the deck again in random order.")
            self.btn_flip.set_label("Practice Deck Again (Random Shuffle)")
            self.btn_flip.set_sensitive(True)
            self.rating_box.set_sensitive(False)
            return

        self.badge_side.set_visible(True)
        self.btn_copy_question.set_visible(True)
        self.btn_flip.set_sensitive(True)
        self.rating_box.set_sensitive(True)

        card = self.current_card

        # Update dynamic SM-2 intervals on rating buttons
        intervals = card.get_next_intervals()
        if hasattr(self, 'rating_buttons') and self.rating_buttons:
            if 1 in self.rating_buttons:
                self.rating_buttons[1].set_label(f"Again (1)\n{intervals[1]}")
            if 2 in self.rating_buttons:
                self.rating_buttons[2].set_label(f"Hard (2)\n{intervals[2]}")
            if 3 in self.rating_buttons:
                self.rating_buttons[3].set_label(f"Good (3)\n{intervals[3]}")
            if 4 in self.rating_buttons:
                self.rating_buttons[4].set_label(f"Easy (4)\n{intervals[4]}")

        if is_back:
            self.badge_side.set_text("ANSWER")
            self.card_box.add_css_class("card-back")
            has_multiline = "\n" in card.back or bool(re.search(r'^[*\-+]\s|^#|\$\$|```', card.back, re.MULTILINE))
            if has_multiline:
                self.label_card_text.set_justify(Gtk.Justification.LEFT)
                self.label_card_text.set_xalign(0.0)
            else:
                self.label_card_text.set_justify(Gtk.Justification.CENTER)
                self.label_card_text.set_xalign(0.5)
            self.label_card_text.set_markup(self.get_card_font_markup(card.back))
            stats_raw = f"Repetitions: {card.repetitions}  •  Ease: {card.ease_factor:.2f}x  •  Interval: {format_interval(card.interval)}"
            stats_escaped = GLib.markup_escape_text(stats_raw)
            notes_str = f"\n<span color='{dim_color}'>{GLib.markup_escape_text(card.notes)}</span>" if card.notes else ""
            self.label_subtext.set_markup(f"{stats_escaped}{notes_str}")
            self.btn_flip.set_label("Flip Back to Question")
        else:
            self.badge_side.set_text("QUESTION")
            self.card_box.remove_css_class("card-back")
            has_multiline = "\n" in card.front or bool(re.search(r'^[*\-+]\s|^#|\$\$|```', card.front, re.MULTILINE))
            if has_multiline:
                self.label_card_text.set_justify(Gtk.Justification.LEFT)
                self.label_card_text.set_xalign(0.0)
            else:
                self.label_card_text.set_justify(Gtk.Justification.CENTER)
                self.label_card_text.set_xalign(0.5)
            self.label_card_text.set_markup(self.get_card_font_markup(card.front))
            self.label_subtext.set_text("Click card or press Space to reveal answer")
            self.btn_flip.set_label("Show Answer (Space)")

    def on_copy_question_clicked(self, button):
        if not self.current_card:
            return
        card = self.current_card
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(card.front)

        # Temporary visual feedback
        self.btn_copy_question.set_label("Copied!")
        self.btn_copy_question.set_icon_name("object-select-symbolic")
        GLib.timeout_add_seconds(2, self.reset_copy_btn)

    def reset_copy_btn(self):
        self.btn_copy_question.set_label("Copy Question")
        self.btn_copy_question.set_icon_name("edit-copy-symbolic")
        return GLib.SOURCE_REMOVE

    def on_rate(self, rating: int):
        if not self.current_card or self.is_animating_card:
            return

        card = self.current_card
        deck_name = ""
        for d in self.decks:
            if d["id"] == self.current_deck_id:
                deck_name = d["name"]
                break

        card.schedule(rating, deck_name)
        self.update_streak_badge()
        self.update_goal_progress()

        # Spaced repetition session queue adjustment:
        # Rating 1 (Again): Card failed, re-insert 1-3 cards ahead so user sees it again soon
        if rating == 1:
            pos = min(len(self.active_study_queue), max(1, min(3, len(self.active_study_queue))))
            self.active_study_queue.insert(pos, card)
        # Rating 2 (Hard) while in learning: re-insert 2-5 cards ahead
        elif rating == 2 and card.state in ("learning", "relearning"):
            pos = min(len(self.active_study_queue), max(2, min(5, len(self.active_study_queue))))
            self.active_study_queue.insert(pos, card)
        else:
            # Good, Easy, or mature review graduated:
            # It has been scheduled for tomorrow/future days and is completed for this session!
            pass

        # Trigger smooth downward departure animation; next card enters from top once offscreen
        self.is_animating_card = True
        self.btn_flip.set_sensitive(False)
        self.rating_box.set_sensitive(False)
        self.card_stage.start_exit_down_animation(
            on_departed=self._on_card_departed,
            on_arrived=self._on_card_arrived
        )
        # Safety fallback: re-enable UI controls if animation completes or times out
        GLib.timeout_add(1000, self._safety_unlock_ui)

    # ==========================================================================
    # Browse Cards View Management
    # ==========================================================================

    def on_search_changed(self, entry):
        self.refresh_browse_view()

    def refresh_browse_view(self):
        # Clear existing rows
        while child := self.browse_list_box.get_first_child():
            self.browse_list_box.remove(child)

        query = self.search_entry.get_text().strip().lower()
        with get_db_connection() as conn:
            cur = conn.cursor()
            if self.current_deck_id:
                cur.execute("""
                    SELECT c.id, c.front, c.back, c.notes, c.ease_factor, c.interval, c.state, d.name
                    FROM cards c JOIN decks d ON c.deck_id = d.id
                    WHERE c.deck_id = ?
                    ORDER BY c.due_date ASC
                """, (self.current_deck_id,))
            else:
                cur.execute("""
                    SELECT c.id, c.front, c.back, c.notes, c.ease_factor, c.interval, c.state, d.name
                    FROM cards c JOIN decks d ON c.deck_id = d.id
                    ORDER BY c.due_date ASC
                """)
            rows = cur.fetchall()

        filtered_count = 0
        for r in rows:
            c_id, front, back, notes, ease, interval, state, deck_name = r
            if query and query not in front.lower() and query not in back.lower() and query not in (notes or "").lower():
                continue

            filtered_count += 1
            row = Adw.ActionRow()
            row.card_id = c_id
            safe_front = GLib.markup_escape_text(front.replace('\n', ' '))
            row.set_title(safe_front)
            safe_back = GLib.markup_escape_text(back.replace('\n', ' ↵ '))
            row.set_subtitle(f"Answer: {safe_back}  •  Interval: {interval:.1f}d  •  Ease: {ease:.2f}x")

            # State badge
            badge = Gtk.Label(label=state.upper())
            badge.add_css_class("pill")
            row.add_suffix(badge)

            self.browse_list_box.append(row)

        self.lbl_browse_count.set_text(f"Showing {filtered_count} cards in active collection")

    def on_new_card_dialog(self, button):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Create New Flashcard",
            body="Enter the prompt and answer (multi-line, Markdown & LaTeX math supported):"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save Card")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)

        entry_front = Gtk.Entry(placeholder_text="Question / Prompt (supports Markdown & $LaTeX$)")

        lbl_back = Gtk.Label(label="Answer / Card Back (Multi-line, Markdown, LaTeX supported):", halign=Gtk.Align.START)
        lbl_back.add_css_class("dim-label")

        scroll_back = Gtk.ScrolledWindow()
        scroll_back.set_min_content_height(120)
        scroll_back.set_vexpand(True)

        text_back = Gtk.TextView()
        text_back.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll_back.set_child(text_back)

        entry_notes = Gtk.Entry(placeholder_text="Optional Study Notes")

        vbox.append(entry_front)
        vbox.append(lbl_back)
        vbox.append(scroll_back)
        vbox.append(entry_notes)
        dialog.set_extra_child(vbox)

        def on_resp(dlg, resp):
            if resp == "save":
                front = entry_front.get_text().strip()
                buf = text_back.get_buffer()
                back = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
                notes = entry_notes.get_text().strip()
                if front and back and self.current_deck_id:
                    new_id = f"c-{int(time.time())}"
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("""
                            INSERT INTO cards (
                                id, deck_id, front, back, notes, ease_factor, interval,
                                repetitions, lapses, state, due_date, stability, difficulty, last_review
                            ) VALUES (?, ?, ?, ?, ?, 2.5, 0.0, 0, 0, 'new', ?, 0.4, 5.0, 0.0)
                        """, (new_id, self.current_deck_id, front, back, notes, time.time()))
                        conn.commit()

                    self.load_cards_for_deck(self.current_deck_id)
                    self.refresh_browse_view()
            dlg.close()

        dialog.connect("response", on_resp)
        dialog.present()

    def on_edit_selected_card(self, button):
        selected_rows = self.browse_list_box.get_selected_rows()
        if not selected_rows:
            return
        card_id = getattr(selected_rows[0], 'card_id', None)
        if not card_id:
            return

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT front, back, notes FROM cards WHERE id = ?", (card_id,))
            row = cur.fetchone()
        if not row:
            return
        front_val, back_val, notes_val = row

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Edit Flashcard",
            body="Update question and answer (multi-line, Markdown & LaTeX supported):"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("save", "Save Changes")
        dialog.set_response_appearance("save", Adw.ResponseAppearance.SUGGESTED)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)

        entry_front = Gtk.Entry(placeholder_text="Question / Prompt")
        entry_front.set_text(front_val or "")

        lbl_back = Gtk.Label(label="Answer / Card Back (Multi-line, Markdown, LaTeX supported):", halign=Gtk.Align.START)
        lbl_back.add_css_class("dim-label")

        scroll_back = Gtk.ScrolledWindow()
        scroll_back.set_min_content_height(120)
        scroll_back.set_vexpand(True)

        text_back = Gtk.TextView()
        text_back.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        text_back.get_buffer().set_text(back_val or "")
        scroll_back.set_child(text_back)

        entry_notes = Gtk.Entry(placeholder_text="Optional Study Notes")
        entry_notes.set_text(notes_val or "")

        vbox.append(entry_front)
        vbox.append(lbl_back)
        vbox.append(scroll_back)
        vbox.append(entry_notes)
        dialog.set_extra_child(vbox)

        def on_resp(dlg, resp):
            if resp == "save":
                new_front = entry_front.get_text().strip()
                buf = text_back.get_buffer()
                new_back = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False).strip()
                new_notes = entry_notes.get_text().strip()
                if new_front and new_back:
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("""
                            UPDATE cards
                            SET front = ?, back = ?, notes = ?
                            WHERE id = ?
                        """, (new_front, new_back, new_notes, card_id))
                        conn.commit()

                    self.load_cards_for_deck(self.current_deck_id)
                    self.refresh_browse_view()
                    if self.current_card and self.current_card.card_id == card_id:
                        self.current_card.front = new_front
                        self.current_card.back = new_back
                        self.current_card.notes = new_notes
                        self.update_card_ui_content(self.showing_answer)
            dlg.close()

        dialog.connect("response", on_resp)
        dialog.present()

    def on_browse_selection_changed(self, box):
        selected_rows = box.get_selected_rows()
        count = len(selected_rows)
        if hasattr(self, 'btn_edit_card'):
            self.btn_edit_card.set_sensitive(count == 1)
        if count > 1:
            self.btn_del_card.set_label(f"Delete ({count}) Cards")
            self.btn_reset_card.set_label(f"Reset ({count}) Cards")
        else:
            self.btn_del_card.set_label("Delete Card")
            self.btn_reset_card.set_label("Reset Progress")

    def on_reset_selected_card(self, button):
        selected_rows = self.browse_list_box.get_selected_rows()
        if not selected_rows:
            return

        card_ids = [r.card_id for r in selected_rows if hasattr(r, 'card_id')]
        if not card_ids:
            return

        now = time.time()
        with get_db_connection() as conn:
            cur = conn.cursor()
            for cid in card_ids:
                cur.execute("""
                    UPDATE cards
                    SET state = 'new', ease_factor = 2.5, interval = 0.0, repetitions = 0, lapses = 0, due_date = ?
                    WHERE id = ?
                """, (now, cid))
            conn.commit()

        self.load_cards_for_deck(self.current_deck_id)
        self.refresh_browse_view()
        self.update_goal_progress()

    def on_delete_selected_card(self, button):
        selected_rows = self.browse_list_box.get_selected_rows()
        if not selected_rows:
            return

        card_ids = [r.card_id for r in selected_rows if hasattr(r, 'card_id')]
        if not card_ids:
            return

        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.executemany("DELETE FROM cards WHERE id = ?", [(cid,) for cid in card_ids])
            conn.commit()

        self.load_cards_for_deck(self.current_deck_id)
        self.refresh_browse_view()
        self.update_goal_progress()

    def update_goal_progress(self):
        try:
            today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
            effective_start = today_start
            if self.goal_tally_reset_timestamp and self.goal_tally_reset_timestamp > today_start:
                effective_start = self.goal_tally_reset_timestamp

            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT COUNT(*) FROM review_logs
                    WHERE timestamp >= ? AND rating IN (3, 4)
                """, (effective_start,))
                graduated = cur.fetchone()[0]
        except Exception:
            graduated = 0

        self.graduated_today = graduated
        fraction = min(1.0, graduated / max(1, self.daily_goal))
        pct = int(fraction * 100)

        if hasattr(self, 'goal_progress_bar'):
            self.goal_progress_bar.set_fraction(fraction)
        if hasattr(self, 'lbl_goal_status'):
            self.lbl_goal_status.set_text(
                f"Daily Goal: {graduated}/{self.daily_goal} graduated (Good/Easy) • {pct}%"
            )

    def show_about_dialog(self, *args):
        """Displays GNOME About window complying with GNOME HIG and Adw conventions."""
        about = Adw.AboutWindow()
        about.set_transient_for(self)
        about.set_modal(True)
        about.set_application_name("Decks")
        about.set_developer_name("WOOSAH & Antigravity (Google AI Studio)")
        about.set_version("1.0")
        about.set_application_icon("decks")
        about.set_website("https://github.com/Smiley-McSmiles/Decks")
        about.set_support_url("https://github.com/Smiley-McSmiles/Decks")
        about.set_issue_url("https://github.com/Smiley-McSmiles/Decks/issues")
        about.set_comments("Modern spaced repetition flashcards with FSRS algorithm and hardware-accelerated 3D animations.")
        about.add_link("Troubleshooting", "https://gemini.google.com")
        about.set_developers([
            "Antigravity (Google AI Studio) - Lead Architect & Creator",
            "WOOSAH"
        ])
        about.set_designers([
            "Antigravity (Google AI Studio)",
            "WOOSAH"
        ])
        about.set_documenters([
            "Antigravity (Google AI Studio)",
            "WOOSAH"
        ])
        about.set_copyright("© 2026 WOOSAH")
        about.set_license_type(Gtk.License.MIT_X11)
        about.present()

    def on_open_preferences_dialog(self, button):
        pref_win = Adw.PreferencesWindow()
        pref_win.set_transient_for(self)
        pref_win.set_modal(True)
        pref_win.set_title("Preferences")
        pref_win.set_default_size(680, 720)
        pref_win.set_search_enabled(False)

        page = Adw.PreferencesPage()
        page.set_title("General")
        page.set_icon_name("preferences-other-symbolic")

        # ----------------------------------------------------------------------
        # Group 1: Daily Goals and Limits (uses 'and' to prevent Pango markup errors)
        # ----------------------------------------------------------------------
        grp_goals = Adw.PreferencesGroup()
        grp_goals.set_title("Daily Goals and Limits")
        grp_goals.set_description("Configure target daily card graduations and study queue limits.")

        # 1. Graduation Goal (1 day/Good or 4 days/Easy pile)
        row_goal = Adw.ActionRow(
            title="Daily Graduation Goal (Good/Easy)",
            subtitle="Target cards to graduate into 1-day or 4-day retention piles today"
        )
        row_goal.set_title_lines(0)
        row_goal.set_subtitle_lines(0)
        spin_goal = Gtk.SpinButton.new_with_range(1, 200, 1)
        spin_goal.set_value(self.daily_goal)
        spin_goal.set_valign(Gtk.Align.CENTER)

        def on_goal_val_changed(sb):
            self.daily_goal = int(sb.get_value())
            set_db_preference("daily_goal", str(self.daily_goal))
            self.update_goal_progress()

        spin_goal.connect("value-changed", on_goal_val_changed)
        row_goal.add_suffix(spin_goal)
        grp_goals.add(row_goal)

        # 2. Daily Study Card Limit
        row_limit = Adw.ActionRow(
            title="Daily Study Card Limit",
            subtitle="Maximum due cards to load into a single study session (0 = unlimited)"
        )
        row_limit.set_title_lines(0)
        row_limit.set_subtitle_lines(0)
        spin_limit = Gtk.SpinButton.new_with_range(0, 500, 5)
        spin_limit.set_value(self.daily_card_limit)
        spin_limit.set_valign(Gtk.Align.CENTER)

        def on_limit_val_changed(sb):
            self.daily_card_limit = int(sb.get_value())
            set_db_preference("daily_card_limit", str(self.daily_card_limit))
            if self.current_deck_id:
                self.load_cards_for_deck(self.current_deck_id)

        spin_limit.connect("value-changed", on_limit_val_changed)
        row_limit.add_suffix(spin_limit)
        grp_goals.add(row_limit)

        page.add(grp_goals)

        # ----------------------------------------------------------------------
        # Group 2: Database and Backup (JSON)
        # ----------------------------------------------------------------------
        grp_db = Adw.PreferencesGroup()
        grp_db.set_title("Database and Backup (JSON)")
        grp_db.set_description("Backup, restore, or reset SQLite spaced repetition flashcards and review logs.")

        # Export Database JSON
        row_export = Adw.ActionRow(
            title="Export Database (JSON)",
            subtitle="Backup all collections, cards, and review audit history to JSON"
        )
        row_export.set_title_lines(0)
        row_export.set_subtitle_lines(0)
        btn_export = Gtk.Button(label="Export JSON", icon_name="document-save-symbolic")
        btn_export.set_valign(Gtk.Align.CENTER)
        btn_export.connect("clicked", lambda b: self.on_export_backup_json(b))
        row_export.add_suffix(btn_export)
        grp_db.add(row_export)

        # Import Database JSON
        row_import = Adw.ActionRow(
            title="Import Database (JSON)",
            subtitle="Restore collections, cards, and review history from a JSON backup file"
        )
        row_import.set_title_lines(0)
        row_import.set_subtitle_lines(0)
        btn_import = Gtk.Button(label="Import JSON", icon_name="document-open-symbolic")
        btn_import.set_valign(Gtk.Align.CENTER)
        btn_import.connect("clicked", lambda b: self.on_import_backup_json(b, pref_win))
        row_import.add_suffix(btn_import)
        grp_db.add(row_import)

        # Reset Database and Start Fresh
        row_reset = Adw.ActionRow(
            title="Reset Database and Start Fresh",
            subtitle="Wipe all cards and review history back to clean default seed collections"
        )
        row_reset.set_title_lines(0)
        row_reset.set_subtitle_lines(0)
        btn_reset = Gtk.Button(label="Reset Database", icon_name="edit-delete-symbolic")
        btn_reset.add_css_class("destructive-action")
        btn_reset.set_valign(Gtk.Align.CENTER)
        btn_reset.connect("clicked", lambda b: self.on_reset_database_clicked(b, pref_win))
        row_reset.add_suffix(btn_reset)
        grp_db.add(row_reset)

        page.add(grp_db)

        # ----------------------------------------------------------------------
        # Group 3: Session Controls
        # ----------------------------------------------------------------------
        grp_session = Adw.PreferencesGroup()
        grp_session.set_title("Session Controls")
        grp_session.set_description("Manage active study queues and daily goal progress tracking.")

        # Reset Today's Goal Tally
        row_reset_tally = Adw.ActionRow(
            title="Reset Today's Goal Tally",
            subtitle="Reset today's graduated counter and progress bar back to 0% for extra practice"
        )
        row_reset_tally.set_title_lines(0)
        row_reset_tally.set_subtitle_lines(0)
        btn_reset_tally = Gtk.Button(label="Reset Tally", icon_name="view-refresh-symbolic")
        btn_reset_tally.set_valign(Gtk.Align.CENTER)

        def do_reset_tally(b):
            now = time.time()
            self.goal_tally_reset_timestamp = now
            set_db_preference("goal_tally_reset_timestamp", str(now))
            self.update_goal_progress()
            b.set_label("✓ Reset!")
            GLib.timeout_add_seconds(2, lambda: (b.set_label("Reset Tally"), False)[1])

        btn_reset_tally.connect("clicked", do_reset_tally)
        row_reset_tally.add_suffix(btn_reset_tally)
        grp_session.add(row_reset_tally)

        # Make Cards Due for Immediate Practice
        row_practice = Adw.ActionRow(
            title="Make Deck Cards Due for Practice",
            subtitle="Schedule all cards in the current deck for immediate review"
        )
        row_practice.set_title_lines(0)
        row_practice.set_subtitle_lines(0)
        btn_practice = Gtk.Button(label="Make Due", icon_name="media-playback-start-symbolic")
        btn_practice.set_valign(Gtk.Align.CENTER)

        def do_make_due(b):
            if not self.current_deck_id:
                return
            now = time.time()
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("UPDATE cards SET due_date = ? WHERE deck_id = ?", (now - 10, self.current_deck_id))
                conn.commit()
            self.load_cards_for_deck(self.current_deck_id)
            b.set_label("✓ Ready!")
            GLib.timeout_add_seconds(2, lambda: (b.set_label("Make Due"), False)[1])

        btn_practice.connect("clicked", do_make_due)
        row_practice.add_suffix(btn_practice)
        grp_session.add(row_practice)

        page.add(grp_session)

        # ----------------------------------------------------------------------
        # Group 4: About & Legal
        # ----------------------------------------------------------------------
        grp_about = Adw.PreferencesGroup()
        grp_about.set_title("About")
        row_about = Adw.ActionRow(
            title="About Decks",
            subtitle="Application credits, contributor details, and MIT license"
        )
        row_about.set_activatable(True)
        btn_open_about = Gtk.Button(icon_name="help-about-symbolic")
        btn_open_about.set_valign(Gtk.Align.CENTER)
        btn_open_about.connect("clicked", lambda b: self.show_about_dialog())
        row_about.add_suffix(btn_open_about)
        row_about.connect("activated", lambda r: self.show_about_dialog())
        grp_about.add(row_about)

        page.add(grp_about)

        pref_win.add(page)
        pref_win.present()

    def on_reset_database_clicked(self, button, parent_dlg=None):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Reset Database and Start Fresh?",
            body="Warning: This will permanently erase all custom cards and review history, resetting your database back to fresh default collections."
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("reset", "Reset Database")
        dialog.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(dlg, resp):
            if resp == "reset":
                reset_database_to_fresh()
                self.goal_tally_reset_timestamp = None
                self.load_decks_from_db()
                self.update_goal_progress()
                self.update_streak_badge()
                if parent_dlg:
                    parent_dlg.close()
            dlg.close()

        dialog.connect("response", on_resp)
        dialog.present()

    def on_import_backup_json(self, button, parent_dlg=None):
        try:
            dialog = Gtk.FileDialog(title="Import JSON Database Backup")
            filter_json = Gtk.FileFilter()
            filter_json.set_name("JSON Files (*.json)")
            filter_json.add_pattern("*.json")
            filters = Gio.ListStore.new(Gtk.FileFilter)
            filters.append(filter_json)
            dialog.set_filters(filters)
            dialog.open(self, None, lambda d, res: self.on_import_backup_json_finish(d, res, parent_dlg))
        except Exception:
            # Fallback for GTK < 4.10
            dialog = Gtk.FileChooserNative.new("Import JSON Database Backup", self, Gtk.FileChooserAction.OPEN, "Import", "Cancel")
            f_filter = Gtk.FileFilter()
            f_filter.set_name("JSON Files")
            f_filter.add_pattern("*.json")
            dialog.add_filter(f_filter)
            def on_fc_resp(dlg, resp):
                if resp == Gtk.ResponseType.ACCEPT:
                    path = dlg.get_file().get_path()
                    self.perform_json_import(path, parent_dlg)
                dlg.destroy()
            dialog.connect("response", on_fc_resp)
            dialog.show()

    def on_import_backup_json_finish(self, dialog, result, parent_dlg=None):
        try:
            file = dialog.open_finish(result)
            if file:
                path = file.get_path()
                self.perform_json_import(path, parent_dlg)
        except Exception as e:
            print("Import finish notice:", e)

    def perform_json_import(self, path: str, parent_dlg=None):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            decks = data.get("decks", [])
            cards = data.get("cards", [])
            logs = data.get("reviewLogs", [])

            if not decks and not cards:
                msg = Adw.MessageDialog(
                    transient_for=self,
                    heading="Invalid Backup",
                    body="The selected JSON file does not contain valid decks or cards."
                )
                msg.add_response("ok", "OK")
                msg.present()
                return

            with get_db_connection() as conn:
                cur = conn.cursor()
                for d in decks:
                    cur.execute("""
                        INSERT OR REPLACE INTO decks (id, name, description)
                        VALUES (?, ?, ?)
                    """, (d.get("id"), d.get("name", "Untitled Deck"), d.get("description", "")))

                for c in cards:
                    cur.execute("""
                        INSERT OR REPLACE INTO cards (
                            id, deck_id, front, back, notes,
                            ease_factor, interval, repetitions, lapses, state, due_date,
                            stability, difficulty, last_review
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        c.get("id"), c.get("deckId", c.get("deck_id")),
                        c.get("front", ""), c.get("back", ""), c.get("notes", ""),
                        float(c.get("easeFactor", c.get("ease_factor", 2.5))),
                        float(c.get("interval", 0.0)),
                        int(c.get("repetitions", 0)),
                        int(c.get("lapses", 0)),
                        str(c.get("state", "new")),
                        float(c.get("dueDate", c.get("due_date", time.time()))),
                        float(c.get("stability", 0.4)),
                        float(c.get("difficulty", 5.0)),
                        float(c.get("lastReview", c.get("last_review", 0.0)))
                    ))

                for l in logs:
                    cur.execute("""
                        INSERT INTO review_logs (
                            card_id, deck_name, card_front, rating,
                            old_interval, new_interval, old_ease, new_ease, timestamp
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        l.get("cardId", l.get("card_id")),
                        l.get("deckName", l.get("deck_name", "")),
                        l.get("cardFront", l.get("card_front", "")),
                        int(l.get("rating", 3)),
                        float(l.get("oldInterval", l.get("old_interval", 0.0))),
                        float(l.get("newInterval", l.get("new_interval", 1.0))),
                        float(l.get("oldEase", l.get("old_ease", 2.5))),
                        float(l.get("newEase", l.get("new_ease", 2.5))),
                        float(l.get("timestamp", time.time()))
                    ))
                conn.commit()

            self.load_decks_from_db()
            self.update_goal_progress()
            self.update_streak_badge()
            if parent_dlg:
                parent_dlg.close()

            msg = Adw.MessageDialog(
                transient_for=self,
                heading="Database Restored",
                body=f"Successfully imported {len(decks)} decks and {len(cards)} flashcards from JSON backup."
            )
            msg.add_response("ok", "OK")
            msg.present()
        except Exception as e:
            msg = Adw.MessageDialog(
                transient_for=self,
                heading="Import Failed",
                body=f"Could not parse JSON backup file:\n{str(e)}"
            )
            msg.add_response("ok", "OK")
            msg.present()

    # ==========================================================================
    # Statistics View Management (Safe SQL with fallback)
    # ==========================================================================

    def refresh_stats_view(self):
        with get_db_connection() as conn:
            cur = conn.cursor()

            # Count cards by state
            cur.execute("SELECT state, COUNT(*) FROM cards GROUP BY state")
            state_counts = dict(cur.fetchall())
            new_cnt = state_counts.get("new", 0)
            learn_cnt = state_counts.get("learning", 0) + state_counts.get("relearning", 0)

            cur.execute("SELECT COUNT(*) FROM cards WHERE state = 'review' AND interval < 21")
            young_cnt = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM cards WHERE state = 'review' AND interval >= 21")
            mature_cnt = cur.fetchone()[0]

            # Average FSRS difficulty
            cur.execute("SELECT AVG(difficulty) FROM cards WHERE difficulty > 0")
            avg_diff = cur.fetchone()[0]
            if avg_diff is None:
                cur.execute("SELECT AVG(ease_factor) FROM cards")
                raw_ease = cur.fetchone()[0] or 2.5
                avg_diff = max(1.0, min(10.0, 11.0 - (raw_ease * 2.4)))

            # Reviews today count
            today_start = time.mktime(time.strptime(time.strftime("%Y-%m-%d"), "%Y-%m-%d"))
            cur.execute("SELECT COUNT(*) FROM review_logs WHERE timestamp >= ?", (today_start,))
            reviewed_today = cur.fetchone()[0]

            # Retention rate
            cur.execute("SELECT rating, COUNT(*) FROM review_logs GROUP BY rating")
            rating_map = dict(cur.fetchall())
            total_reviews = sum(rating_map.values())
            good_easy = rating_map.get(3, 0) + rating_map.get(4, 0)
            retention = round((good_easy / total_reviews) * 100) if total_reviews > 0 else 92

            # Total cards in entire collection
            cur.execute("SELECT COUNT(*) FROM cards")
            total_collection_cnt = cur.fetchone()[0]

            # Recent 30 review logs (safe column selection)
            cur.execute("PRAGMA table_info(review_logs)")
            cols = [r[1] for r in cur.fetchall()]
            has_front = "card_front" in cols
            has_deck = "deck_name" in cols

            front_col = "card_front" if has_front else "card_id"
            deck_col = "deck_name" if has_deck else "''"

            cur.execute(f"""
                SELECT {front_col}, {deck_col}, rating, old_interval, new_interval, timestamp
                FROM review_logs ORDER BY timestamp DESC LIMIT 30
            """)
            recent_logs = cur.fetchall()

        # Update KPI widgets
        self.update_streak_badge()
        self.card_today_val.set_text(str(reviewed_today))
        self.card_retention_val.set_text(f"{retention}%")
        self.card_mature_val.set_text(str(mature_cnt))
        self.card_ease_val.set_text(f"{avg_diff:.1f} / 10")
        self.card_total_val.set_text(str(total_collection_cnt))

        # Update Maturity Breakdown Box
        while child := self.box_breakdown.get_first_child():
            self.box_breakdown.remove(child)

        maturity_items = [
            ("New Cards", f"{new_cnt} cards", "Not yet reviewed", "#3584e4"),
            ("Learning / Relearning", f"{learn_cnt} cards", "Graduating through initial intervals", "#f5c211"),
            ("Young Cards", f"{young_cnt} cards", "Under 21 days retention interval", "#57e389"),
            ("Mature Cards", f"{mature_cnt} cards", "21+ days long-term memory", "#9141ac"),
        ]
        for name, cnt_str, desc, color in maturity_items:
            row = Adw.ActionRow()
            row.set_title(GLib.markup_escape_text(name))
            row.set_subtitle(GLib.markup_escape_text(desc))
            badge = Gtk.Label(label=cnt_str)
            badge.add_css_class("pill")
            row.add_suffix(badge)
            self.box_breakdown.append(row)

        # Update Review Audit Trail Box
        while child := self.box_audit_logs.get_first_child():
            self.box_audit_logs.remove(child)

        rating_labels = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
        for log in recent_logs:
            front, d_name, rating, old_int, new_int, ts = log
            time_str = time.strftime("%b %d, %H:%M", time.localtime(ts))
            row = Adw.ActionRow()
            row.set_title(GLib.markup_escape_text(front or "Card"))
            row.set_subtitle(GLib.markup_escape_text(f"{d_name or 'Collection'}  •  {time_str}  •  Interval: {old_int:.1f}d → {new_int:.1f}d"))

            badge = Gtk.Label(label=rating_labels.get(rating, str(rating)))
            badge.add_css_class("pill")
            row.add_suffix(badge)
            self.box_audit_logs.append(row)

    # ==========================================================================
    # Deck & Backup Dialogs
    # ==========================================================================

    def on_add_deck_clicked(self, button):
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Create New Deck",
            body="Enter a name for the new flashcard collection:"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("create", "Create Deck")
        dialog.set_response_appearance("create", Adw.ResponseAppearance.SUGGESTED)

        entry = Gtk.Entry(placeholder_text="Deck Name")
        entry.set_margin_start(16)
        entry.set_margin_end(16)
        dialog.set_extra_child(entry)

        def on_response(dlg, resp):
            if resp == "create":
                name = entry.get_text().strip()
                if name:
                    new_id = f"deck-{int(time.time())}"
                    with get_db_connection() as conn:
                        cur = conn.cursor()
                        cur.execute("INSERT INTO decks VALUES (?, ?, ?)", (new_id, name, ""))
                        conn.commit()
                    self.load_decks_from_db()
            dlg.close()

        dialog.connect("response", on_response)
        dialog.present()

    def on_delete_current_deck_clicked(self, button):
        if not self.current_deck_id:
            return

        current_name = "this deck"
        for d in self.decks:
            if d["id"] == self.current_deck_id:
                current_name = d["name"]
                break

        dialog = Adw.MessageDialog(
            transient_for=self,
            heading="Delete Deck?",
            body=f"Are you sure you want to permanently delete '{current_name}' and all its cards?"
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete Deck")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)

        def on_resp(dlg, resp):
            if resp == "delete":
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("DELETE FROM cards WHERE deck_id = ?", (self.current_deck_id,))
                    cur.execute("DELETE FROM decks WHERE id = ?", (self.current_deck_id,))
                    conn.commit()
                self.load_decks_from_db()
            dlg.close()

        dialog.connect("response", on_resp)
        dialog.present()

    def on_import_csv(self, button):
        dialog = Gtk.FileDialog(title="Import CSV Flashcards")
        dialog.open(self, None, self.on_file_selected)

    def on_file_selected(self, dialog, result):
        try:
            file = dialog.open_finish(result)
        except Exception as e:
            # User dismissed or closed the file chooser (e.g. exit button or cancel)
            err_str = str(e).lower()
            if "dismissed" in err_str or "cancel" in err_str:
                return
            err_dlg = Adw.MessageDialog(
                transient_for=self,
                heading="Import Failed",
                body=f"An error occurred while opening the file dialog:\n{e}"
            )
            err_dlg.add_response("ok", "OK")
            err_dlg.present()
            return

        if not file or not self.current_deck_id:
            return

        try:
            path = file.get_path()
            count = 0

            # Robust multi-encoding reader (UTF-8, UTF-8 with BOM, Latin-1)
            content = None
            for enc in ['utf-8-sig', 'utf-8', 'latin-1']:
                try:
                    with open(path, 'r', encoding=enc) as f:
                        content = f.read()
                    break
                except UnicodeDecodeError:
                    continue

            if content is None:
                raise ValueError("Could not decode CSV file with supported encodings (UTF-8 / Latin-1).")

            # Detect delimiter (comma, tab, semicolon)
            sample = content[:4096]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=',\t;')
            except Exception:
                dialect = csv.excel

            with get_db_connection() as conn:
                cur = conn.cursor()
                reader = csv.reader(io.StringIO(content), dialect)
                for row in reader:
                    if not row or not any(col.strip() for col in row):
                        continue
                    if len(row) >= 2:
                        front = row[0].strip()
                        # Columns from index 1 onwards are concatenated with \n for the back
                        back_cols = list(row[1:])
                        # Strip trailing empty columns
                        while back_cols and not back_cols[-1].strip():
                            back_cols.pop()
                        if not back_cols:
                            continue

                        # Convert literal '\\n' sequences into actual newlines, then join columns with '\n'
                        back_lines = [col.replace('\\n', '\n').strip() for col in back_cols]
                        back = "\n".join(back_lines)

                        c_id = f"c-{int(time.time())}-{count}"
                        cur.execute("""
                            INSERT INTO cards (
                                id, deck_id, front, back, notes, ease_factor, interval,
                                repetitions, lapses, state, due_date, stability, difficulty, last_review
                            ) VALUES (?, ?, ?, ?, '', 2.5, 0.0, 0, 0, 'new', ?, 0.4, 5.0, 0.0)
                        """, (c_id, self.current_deck_id, front, back, time.time()))
                        count += 1
                conn.commit()

            self.load_cards_for_deck(self.current_deck_id)
            self.refresh_browse_view()

            # Native confirmation dialog
            msg = Adw.MessageDialog(
                transient_for=self,
                heading="Import Complete",
                body=f"Successfully imported {count} flashcard(s) into this deck.\n\n"
                     "• Columns 2+ are formatted as multi-line answers\n"
                     "• Markdown formatting is active\n"
                     "• LaTeX math expressions are rendered"
            )
            msg.add_response("ok", "Done")
            msg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            msg.present()
        except Exception as e:
            print("Import error:", e)
            err_dlg = Adw.MessageDialog(
                transient_for=self,
                heading="Import Failed",
                body=f"An error occurred while importing the CSV:\n{e}"
            )
            err_dlg.add_response("ok", "OK")
            err_dlg.present()

    def on_export_current_deck_csv(self, button):
        if not self.current_deck_id:
            return

        deck_name = "deck"
        for d in self.decks:
            if d["id"] == self.current_deck_id:
                deck_name = d["name"]
                break

        safe_name = re.sub(r'[/\\?%*:|"<>]', '_', deck_name).strip() or "deck"
        initial_filename = f"{safe_name}.csv"

        dialog = Gtk.FileDialog(title=f"Export '{deck_name}' to CSV")
        dialog.set_initial_name(initial_filename)
        dialog.save(self, None, self.on_export_csv_selected)

    def on_export_csv_selected(self, dialog, result):
        try:
            file = dialog.save_finish(result)
        except Exception as e:
            # User dismissed or closed file chooser
            err_str = str(e).lower()
            if "dismissed" in err_str or "cancel" in err_str:
                return
            err_dlg = Adw.MessageDialog(
                transient_for=self,
                heading="Export Failed",
                body=f"An error occurred while choosing the save location:\n{e}"
            )
            err_dlg.add_response("ok", "OK")
            err_dlg.present()
            return

        if not file or not self.current_deck_id:
            return

        try:
            path = file.get_path()
            if not path:
                return
            if not path.lower().endswith(".csv"):
                path += ".csv"

            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("""
                    SELECT front, back, notes FROM cards
                    WHERE deck_id = ?
                    ORDER BY rowid ASC
                """, (self.current_deck_id,))
                rows = cur.fetchall()

            count = len(rows)
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                for front, back, notes in rows:
                    back_lines = [line.strip() for line in (back or "").splitlines() if line.strip()]
                    if not back_lines:
                        back_lines = [(back or "").strip()]
                    row = [(front or "").strip()] + back_lines
                    if notes and notes.strip():
                        row.append(notes.strip())
                    writer.writerow(row)

            deck_title = "Selected Deck"
            for d in self.decks:
                if d["id"] == self.current_deck_id:
                    deck_title = d["name"]
                    break

            msg = Adw.MessageDialog(
                transient_for=self,
                heading="Export Complete",
                body=f"Successfully exported {count} card(s) from '{deck_title}' to:\n\n{os.path.basename(path)}"
            )
            msg.add_response("ok", "Done")
            msg.set_response_appearance("ok", Adw.ResponseAppearance.SUGGESTED)
            msg.present()
        except Exception as e:
            print("Export error:", e)
            err_dlg = Adw.MessageDialog(
                transient_for=self,
                heading="Export Failed",
                body=f"An error occurred while exporting the deck:\n{e}"
            )
            err_dlg.add_response("ok", "OK")
            err_dlg.present()

    def on_export_backup_json(self, button):
        try:
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT id, name, description FROM decks")
                decks = [{"id": r[0], "name": r[1], "description": r[2]} for r in cur.fetchall()]

                cur.execute("""
                    SELECT id, deck_id, front, back, notes, ease_factor, interval, repetitions,
                           lapses, state, due_date, stability, difficulty, last_review
                    FROM cards
                """)
                cards = [{
                    "id": r[0], "deckId": r[1], "front": r[2], "back": r[3], "notes": r[4],
                    "easeFactor": r[5], "interval": r[6], "repetitions": r[7], "lapses": r[8],
                    "state": r[9], "dueDate": r[10], "stability": r[11], "difficulty": r[12], "lastReview": r[13]
                } for r in cur.fetchall()]

                cur.execute("SELECT card_id, deck_name, card_front, rating, old_interval, new_interval, old_ease, new_ease, timestamp FROM review_logs")
                logs = [{
                    "cardId": r[0], "deckName": r[1], "cardFront": r[2], "rating": r[3],
                    "oldInterval": r[4], "newInterval": r[5], "oldEase": r[6], "newEase": r[7],
                    "timestamp": r[8]
                } for r in cur.fetchall()]

            backup = {
                "exportTimestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "app": "Decks",
                "version": "50.3",
                "decks": decks,
                "cards": cards,
                "reviewLogs": logs
            }

            backup_path = os.path.expanduser(f"~/Downloads/decks_backup_{time.strftime('%Y%m%d')}.json")
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            with open(backup_path, "w", encoding="utf-8") as f:
                json.dump(backup, f, indent=2)

            msg = Adw.MessageDialog(
                transient_for=self,
                heading="Backup Saved",
                body=f"Your full database backup has been saved to:\n{backup_path}"
            )
            msg.add_response("ok", "OK")
            msg.present()
        except Exception as e:
            print("Backup notice:", e)

    # ==========================================================================
    # Global Keyboard Shortcuts
    # ==========================================================================

    def on_key_pressed(self, controller, keyval, keycode, state):
        # Global application shortcuts: Ctrl+Q and Ctrl+W to close
        is_ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        if is_ctrl and keyval in (Gdk.KEY_q, Gdk.KEY_Q, Gdk.KEY_w, Gdk.KEY_W):
            self.close()
            return True

        current_view = self.view_stack.get_visible_child_name()
        if current_view != "study":
            return False

        if keyval in (Gdk.KEY_space, Gdk.KEY_Return):
            self.do_flip()
            return True
        elif keyval in (Gdk.KEY_1, Gdk.KEY_KP_1):
            self.on_rate(1); return True
        elif keyval in (Gdk.KEY_2, Gdk.KEY_KP_2):
            self.on_rate(2); return True
        elif keyval in (Gdk.KEY_3, Gdk.KEY_KP_3):
            self.on_rate(3); return True
        elif keyval in (Gdk.KEY_4, Gdk.KEY_KP_4):
            self.on_rate(4); return True
        return False


class DecksApp(Adw.Application):
    def __init__(self):
        GLib.set_prgname("decks")
        GLib.set_application_name("Decks")
        super().__init__(application_id=None, flags=Gio.ApplicationFlags.FLAGS_NONE)
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda a, p: self.quit())
        self.add_action(quit_action)

        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self.on_app_about)
        self.add_action(about_action)

    def on_app_about(self, action, param):
        win = self.props.active_window
        if win and hasattr(win, "show_about_dialog"):
            win.show_about_dialog()

    def do_activate(self):
        init_database()

        # Register local SVG icon paths with GtkIconTheme
        try:
            display = Gdk.Display.get_default()
            if display:
                theme = Gtk.IconTheme.get_for_display(display)
                script_dir = os.path.dirname(os.path.abspath(__file__))
                theme.add_search_path(script_dir)
                theme.add_search_path(os.path.join(script_dir, "icons"))
                theme.add_search_path(os.path.join(script_dir, "icons", "hicolor", "scalable", "apps"))
                theme.add_search_path(os.path.expanduser("~/.local/share/icons"))
                theme.add_search_path(os.path.expanduser("~/.local/share/icons/hicolor"))
                Gtk.Window.set_default_icon_name("decks")
        except Exception as e:
            print("Icon setup notice:", e)

        self.set_accels_for_action("app.quit", ["<Control>q"])
        self.set_accels_for_action("win.close-window", ["<Control>w"])
        self.set_accels_for_action("app.about", ["F1"])
        win = self.props.active_window or DecksWindow(self)
        win.present()


if __name__ == "__main__":
    app = DecksApp()
    sys.exit(app.run(sys.argv))