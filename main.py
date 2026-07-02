import os
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
from app.core.app_logger import log_error
from app.core.data import consume_load_warning, ensure_data_location, load_data
from app.features.editor_mixin import EditorMixin
from app.features.notes_mixin import NotesMixin
from app.features.settings_mixin import SettingsMixin
from app.core.ui_config import (
    BLOCK_STYLE_LABELS,
    DEFAULT_BLOCK_STYLE_LABEL,
    DEFAULT_FONT_SIZE,
    DEFAULT_NOTE_SORT_LABEL,
    FONT_COLORS,
    NOTE_SORT_LABELS,
    app_font,
    resource_path,
)
from app.updates.update_ui import UpdateMixin


COMPACT_LAYOUT_WIDTH = 1000


class NotebookApp(UpdateMixin, EditorMixin, NotesMixin, SettingsMixin, ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # 必要なフォルダの作成と旧保存先からの移行
        ensure_data_location()

        # データの初期ロード
        self.data = load_data()
        self.load_warning_message = consume_load_warning()
        
        # 状態の管理用変数
        self.selected_category = "全て"      # 現在選択中のジャンル
        self.current_note_id = None         # 現在編集中のノートID
        self.keep_alive_images = []         # Tkinter画像GC対策
        self.auto_save_timer = None         # 自動保存用タイマーID
        self.pending_format_start_index = None
        self.pending_format_after_id = None
        self.editor_undo_stack = []
        self.editor_redo_stack = []
        self.suppress_editor_history = False
        self.pending_native_text_edit_snapshot = None
        self.compact_layout_active = None
        self.init_update_state()
        self.note_sort_var = ctk.StringVar(value=DEFAULT_NOTE_SORT_LABEL)
        self.block_style_var = ctk.StringVar(value=DEFAULT_BLOCK_STYLE_LABEL)

        # リッチテキストタイピング用のアクティブな装飾設定
        self.active_typing_color = "default"
        self.active_typing_size = DEFAULT_FONT_SIZE
        self.active_typing_bold = False
        self.active_typing_underline = False
        self.temporary_typing_color_line = None
        self.temporary_typing_style_line = None
        self.keep_typing_color_var = tk.BooleanVar(value=False)
        self.color_target = "body"            # "body" or "title"：色ボタンの適用先

        # ウィンドウの基本設定
        self.title("つくしノート")
        
        # アプリのアイコンを設定する。
        try:
            icon_path = resource_path("app_icon.ico")
            if os.path.exists(icon_path):
                self.iconbitmap(icon_path)
        except Exception as e:
            log_error("アイコン適用に失敗しました。", e)
            
        self.geometry("1100x700")
        self.minsize(620, 500)
        self.after(0, self.maximize_window)

        # 初期表示モード
        ctk.set_appearance_mode("dark")

        # 画面の分割レイアウト
        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=0, minsize=250)
        self.grid_columnconfigure(2, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.normalize_note_metadata()

        # UI構築
        self.create_sidebar()
        self.create_notes_list()
        self.create_editor()
        self.apply_app_fonts(self)

        # リッチテキスト装飾タグの初期生成
        self.configure_formatting_tags()

        # 起動時に最初のノートを選択する。
        self.refresh_category_list()
        self.refresh_notes_list()
        self.load_first_note()
        self.protocol("WM_DELETE_WINDOW", self.on_app_close)
        self.bind("<Configure>", self.on_window_resized)
        self.after_idle(self.update_responsive_layout)
        self.after(300, self.show_load_warning_if_needed)
        self.update_check_after_id = self.after(1500, self.start_update_check)

    def maximize_window(self):
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

    def show_load_warning_if_needed(self):
        warning_message = getattr(self, "load_warning_message", None)
        if not warning_message:
            return

        self.load_warning_message = None
        messagebox.showwarning("データの読み込み", warning_message)

    def on_window_resized(self, event):
        if event.widget is self:
            self.update_responsive_layout(event.width)

    def update_responsive_layout(self, width=None):
        if width is None:
            width = self.winfo_width()
        if width <= 1:
            return

        compact = width < COMPACT_LAYOUT_WIDTH
        if compact == self.compact_layout_active:
            return

        self.compact_layout_active = compact
        if compact:
            self.apply_compact_layout()
        else:
            self.apply_full_layout()

    def apply_compact_layout(self):
        self.sidebar.grid_remove()
        self.list_frame.grid_remove()
        self.editor_frame.grid(row=0, column=0, columnspan=3, sticky="nsew", padx=0, pady=0)

        self.grid_columnconfigure(0, weight=1, minsize=0)
        self.grid_columnconfigure(1, weight=0, minsize=0)
        self.grid_columnconfigure(2, weight=0, minsize=0)

    def apply_full_layout(self):
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.list_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.editor_frame.grid(row=0, column=2, columnspan=1, sticky="nsew", padx=0, pady=0)

        self.grid_columnconfigure(0, weight=0, minsize=200)
        self.grid_columnconfigure(1, weight=0, minsize=250)
        self.grid_columnconfigure(2, weight=1, minsize=0)

    def on_app_close(self):
        """終了前に保留中の保存を反映してからウィンドウを閉じる。"""
        if getattr(self, "_is_closing", False):
            return

        self._is_closing = True

        for timer_attr in ("auto_save_timer", "pending_format_after_id", "update_check_after_id"):
            timer_id = getattr(self, timer_attr, None)
            if timer_id is not None:
                try:
                    self.after_cancel(timer_id)
                except tk.TclError:
                    pass
                setattr(self, timer_attr, None)

        self.pending_format_start_index = None

        try:
            self.save_current_note_immediately()
        except tk.TclError:
            pass

        try:
            self.cleanup_unused_images()
        except (OSError, tk.TclError):
            pass

        try:
            self.quit()
        finally:
            self.destroy()

    # ------------------------------------------
    # UI構築: 各種エリア
    # ------------------------------------------
    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, corner_radius=0, width=200, fg_color=("#e8e8e8", "#161616"))
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=0, pady=0)
        self.sidebar.grid_rowconfigure(2, weight=1)

        title_label = ctk.CTkLabel(self.sidebar, text="📚 ジャンル一覧", font=app_font(size=18, weight="bold"), text_color=("#1a1a1a", "#ffffff"))
        title_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        add_cat_btn = ctk.CTkButton(self.sidebar, text="➕ 新しい教科を追加", font=app_font(size=13), fg_color=("#2980b9", "#1f538d"), hover_color=("#1f6391", "#14375e"), command=self.add_category)
        add_cat_btn.grid(row=1, column=0, padx=15, pady=10, sticky="ew")

        self.cat_scrollable = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        self.cat_scrollable.grid(row=2, column=0, padx=10, pady=5, sticky="nsew")
        
        self.theme_switch_var = ctk.StringVar(value="dark")
        self.theme_switch = ctk.CTkSwitch(
            self.sidebar, 
            text="🌙 ダークモード",
            variable=self.theme_switch_var, 
            onvalue="dark", 
            offvalue="light", 
            text_color=("#1a1a1a", "#ffffff"),
            font=app_font(size=13),
            command=self.toggle_app_theme
        )
        self.theme_switch.grid(row=3, column=0, padx=15, pady=(10, 5), sticky="ew")
        
        settings_btn = ctk.CTkButton(self.sidebar, text="⚙ Gemini API 設定", font=app_font(size=13), fg_color=("#7f8c8d", "gray30"), hover_color=("#95a5a6", "gray40"), command=self.open_settings)
        settings_btn.grid(row=4, column=0, padx=15, pady=(5, 20), sticky="ew")

    def create_notes_list(self):
        self.list_frame = ctk.CTkFrame(self, width=250, corner_radius=0, fg_color=("#f0f0f0", "#1c1c1c"))
        self.list_frame.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.list_frame.grid_rowconfigure(3, weight=1)

        self.list_title = ctk.CTkLabel(self.list_frame, text="全て のノート", font=app_font(size=16, weight="bold"), text_color=("#1a1a1a", "#ffffff"))
        self.list_title.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        new_note_btn = ctk.CTkButton(self.list_frame, text="📝 新規ノート", font=app_font(size=13), fg_color=("#27ae60", "#2b733b"), hover_color=("#219653", "#1c4b26"), command=self.add_new_note)
        new_note_btn.grid(row=1, column=0, padx=15, pady=10, sticky="ew")

        sort_row = ctk.CTkFrame(self.list_frame, fg_color="transparent")
        sort_row.grid(row=2, column=0, padx=15, pady=(0, 8), sticky="ew")
        sort_row.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(sort_row, text="並び順:", font=app_font(size=12), text_color=("#333333", "#e0e0e0")).grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.note_sort_menu = ctk.CTkOptionMenu(
            sort_row,
            values=NOTE_SORT_LABELS,
            variable=self.note_sort_var,
            font=app_font(size=12),
            dropdown_font=app_font(size=12),
            command=self.on_note_sort_changed
        )
        self.note_sort_menu.grid(row=0, column=1, sticky="ew")

        self.notes_scrollable = ctk.CTkScrollableFrame(self.list_frame, fg_color="transparent")
        self.notes_scrollable.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")

    def create_editor(self):
        self.editor_frame = ctk.CTkFrame(self, corner_radius=0, fg_color=("#f8f9fa", "#222222"))
        self.editor_frame.grid(row=0, column=2, sticky="nsew", padx=0, pady=0)
        self.editor_frame.grid_rowconfigure(2, weight=1)
        self.editor_frame.grid_columnconfigure(0, weight=1)

        toolbar = ctk.CTkFrame(self.editor_frame, height=50, fg_color="transparent")
        toolbar.grid(row=0, column=0, sticky="ew", padx=15, pady=(15, 5))

        style_label = ctk.CTkLabel(toolbar, text="スタイル:", font=app_font(size=12), text_color=("#333333", "#e0e0e0"))
        style_label.pack(side="left", padx=(5, 4))

        self.block_style_menu = ctk.CTkOptionMenu(
            toolbar,
            values=BLOCK_STYLE_LABELS,
            variable=self.block_style_var,
            width=118,
            font=app_font(size=12),
            dropdown_font=app_font(size=12),
            command=self.on_block_style_changed,
        )
        self.block_style_menu.pack(side="left", padx=(0, 10))

        ctk.CTkLabel(toolbar, text=" | ", font=app_font(size=12), text_color="gray50").pack(side="left", padx=8)

        self.bold_btn = ctk.CTkButton(toolbar, text="B", width=32, height=28, font=app_font(size=14, weight="bold"), command=self.toggle_typing_bold)
        self.bold_btn.pack(side="left", padx=3)

        self.underline_btn = ctk.CTkButton(toolbar, text="U", width=32, height=28, font=app_font(size=14, underline=True), command=self.toggle_typing_underline)
        self.underline_btn.pack(side="left", padx=3)

        self.update_style_buttons()

        ctk.CTkLabel(toolbar, text=" | ", font=app_font(size=12), text_color="gray50").pack(side="left", padx=8)

        self.color_label = ctk.CTkLabel(toolbar, text="文字色(本文):", font=app_font(size=12), text_color=("#333333", "#e0e0e0"))
        self.color_label.pack(side="left", padx=5)

        self.color_buttons = {}
        for key, name in [(color_key, config["name"]) for color_key, config in FONT_COLORS.items()]:
            hex_color = self.color_swatch_color(key)
            btn = ctk.CTkButton(toolbar, text="", width=20, height=20, corner_radius=10, font=app_font(size=12), fg_color=hex_color, hover_color=hex_color, border_width=1, border_color="white", command=lambda k=key: self.change_typing_color(k))
            btn.pack(side="left", padx=3)
            self.color_buttons[key] = btn

        self.keep_color_checkbox = ctk.CTkCheckBox(
            toolbar,
            text="色固定",
            variable=self.keep_typing_color_var,
            font=app_font(size=12),
            width=70,
            command=self.on_keep_typing_color_changed,
        )
        self.keep_color_checkbox.pack(side="left", padx=(8, 0))

        self.ai_quiz_btn = ctk.CTkButton(toolbar, text="🧠 AIクイズ", width=90, fg_color="#8a2be2", hover_color="#6a1b9a", font=app_font(weight="bold"), command=self.start_ai_quiz)
        self.ai_quiz_btn.pack(side="right", padx=5)

        self.insert_img_btn = ctk.CTkButton(toolbar, text="📷 画像挿入", width=90, font=app_font(size=13), fg_color="gray30", hover_color="gray40", command=self.insert_image)
        self.insert_img_btn.pack(side="right", padx=5)

        title_row = ctk.CTkFrame(self.editor_frame, fg_color="transparent")
        title_row.grid(row=1, column=0, sticky="ew", padx=15, pady=5)
        title_row.grid_columnconfigure(0, weight=1)

        self.title_entry = ctk.CTkEntry(
            title_row, 
            placeholder_text="タイトルを入力",
            font=app_font(size=18, weight="bold"),
            border_width=1,
            fg_color=("#ffffff", "#2b2b2b"),
            border_color=("#dcdde1", "#3f3f3f"),
            justify="left"
        )
        self.title_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.title_entry.bind("<KeyRelease>", self.trigger_auto_save)
        self.title_entry._entry.bind("<FocusIn>", self.on_title_focus_in, add="+")

        delete_note_btn = ctk.CTkButton(title_row, text="🗑 削除", width=70, font=app_font(size=13), fg_color="#c0392b", hover_color="#962d22", command=self.delete_current_note)
        delete_note_btn.grid(row=0, column=1, sticky="e")

        self.editor = ctk.CTkTextbox(
            self.editor_frame,
            font=app_font(size=DEFAULT_FONT_SIZE),
            undo=True, 
            wrap="word", 
            border_width=1,
            fg_color=("#ffffff", "#2b2b2b"),
            border_color=("#dcdde1", "#3f3f3f")
        )
        self.editor.grid(row=2, column=0, sticky="nsew", padx=15, pady=(5, 15))
        self.editor.bind("<KeyRelease>", self.trigger_auto_save)
        
        # キー入力でリアルタイム修飾
        self.editor.bind("<KeyPress>", self.on_key_pressed)
        self.editor._textbox.bind("<Control-ButtonPress-1>", self.on_multi_select_press)
        self.editor._textbox.bind("<Control-B1-Motion>", self.on_multi_select_drag)
        self.editor._textbox.bind("<Control-ButtonRelease-1>", self.on_multi_select_release)
        self.editor._textbox.bind("<ButtonPress-1>", self.on_editor_button_press, add="+")
        self.editor._textbox.bind("<ButtonRelease-1>", self.on_editor_button_release, add="+")
        self.editor._textbox.bind("<BackSpace>", self.on_delete_key_pressed, add="+")
        self.editor._textbox.bind("<Delete>", self.on_delete_key_pressed, add="+")
        self.editor._textbox.bind("<<Copy>>", self.on_copy_event, add="+")
        self.editor._textbox.bind("<<Cut>>", self.on_cut_event, add="+")
        self.editor._textbox.bind("<<Paste>>", self.on_paste_event, add="+")
        self.editor._textbox.bind("<Escape>", self.clear_multi_select_ranges, add="+")
        self.editor.bind("<Return>", self.on_return_pressed, add="+")
        self.editor.bind("<Shift-Return>", self.on_return_pressed, add="+")
        self.editor.bind("<Down>", self.on_down_pressed, add="+")
        self.editor._textbox.bind("<FocusIn>", lambda _event: self.sync_editor_input_style(), add="+")
        self.editor._textbox.bind("<FocusIn>", self.on_editor_focus_in, add="+")
        self.editor._textbox.bind("<ButtonRelease-1>", self.move_insert_out_of_image_marker, add="+")
        self.editor._textbox.bind("<KeyRelease>", self.move_insert_out_of_image_marker, add="+")
        self.editor._textbox.bind("<ButtonRelease-1>", self.reset_temporary_color_on_cursor_move, add="+")
        self.editor._textbox.bind("<KeyRelease>", self.reset_temporary_color_on_cursor_move, add="+")
        self.editor._textbox.bind("<KeyRelease>", self.ensure_insert_cursor_visible, add="+")
        self.bind_editor_shortcuts()

    def apply_app_fonts(self, widget):
        """フォント未指定のCustomTkinterウィジェットにもアプリ標準フォントを適用する"""
        font_widgets = (ctk.CTkButton, ctk.CTkLabel, ctk.CTkSwitch, ctk.CTkEntry, ctk.CTkTextbox, ctk.CTkOptionMenu)
        if isinstance(widget, font_widgets):
            try:
                current_font = widget.cget("font")
                size = current_font.cget("size") if hasattr(current_font, "cget") else 13
                weight = current_font.cget("weight") if hasattr(current_font, "cget") else "normal"
                slant = current_font.cget("slant") if hasattr(current_font, "cget") else "roman"
                underline = current_font.cget("underline") if hasattr(current_font, "cget") else False
                widget.configure(font=app_font(size=size, weight=weight, slant=slant, underline=underline))
                if isinstance(widget, ctk.CTkOptionMenu):
                    widget.configure(dropdown_font=app_font(size=size, weight=weight, slant=slant, underline=underline))
            except Exception:
                pass

        for child in widget.winfo_children():
            self.apply_app_fonts(child)

    # ==========================================
    # 4. リッチテキスト装飾
    # ==========================================


# ==========================================
# 8. アプリの起動エントリーポイント
# ==========================================

if __name__ == "__main__":
    app = NotebookApp()
    app.mainloop()
