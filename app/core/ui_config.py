import os
import sys
from pathlib import Path
import customtkinter as ctk


APP_VERSION = "1.2.3"

FONT_COLORS = {
    "default": {
        "name": "標準",
        "dark": "#ffffff",
        "light": "#1e293b",
    },
    "rose": {
        "name": "サクラ",
        "dark": "#ff8fa3",
        "light": "#e11d48",
    },
    "ocean": {
        "name": "オーシャン",
        "dark": "#70a1ff",
        "light": "#2563eb",
    },
    "sage": {
        "name": "セージ",
        "dark": "#2ed573",
        "light": "#16a34a",
    },
    "amber": {
        "name": "サニー",
        "dark": "#ffa502",
        "light": "#d97706",
    },
    "purple": {
        "name": "ラベンダー",
        "dark": "#d6a2e8",
        "light": "#9333ea",
    },
}

DEFAULT_FONT_SIZE = 20
FONT_SIZE_VALUES = range(12, 33, 2)
EDITOR_FONT_FAMILY = "Yu Gothic UI"

DEFAULT_NOTE_SORT_LABEL = "名前順"
NOTE_SORT_LABELS = ["名前順", "新しい順", "古い順", "更新順"]

DEFAULT_BLOCK_STYLE_LABEL = "本文"
BLOCK_STYLES = {
    "本文": {"size": 20, "bold": False},
    "見出し1（大）": {"size": 32, "bold": True},
    "見出し2（中）": {"size": 28, "bold": True},
    "見出し3（小）": {"size": 24, "bold": True},
}
BLOCK_STYLE_LABELS = list(BLOCK_STYLES.keys())


def app_font(**kwargs):
    return ctk.CTkFont(family=EDITOR_FONT_FAMILY, **kwargs)


def resource_path(relative_path):
    """PyInstaller同梱時とソース実行時で同じ書き方でファイルを参照する。"""
    base_path = getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])
    return os.path.join(base_path, relative_path)
