import os
import ctypes
import unicodedata
import tkinter as tk
import customtkinter as ctk
from PIL import ImageTk
from app.core.app_logger import log_error
from app.core.data import IMAGES_DIR
from app.features.image_embed import DEFAULT_IMAGE_WIDTH, image_marker_text, load_resized_image, parse_image_marker
from app.core.platform_ime import LOGFONTW, imm32, wintypes
from app.core.ui_config import BLOCK_STYLES, DEFAULT_BLOCK_STYLE_LABEL, DEFAULT_FONT_SIZE, FONT_COLORS, FONT_SIZE_VALUES, app_font


class EditorMixin:
    MAX_EDITOR_HISTORY = 100

    BRACKET_PAIRS = {
        "(": ")",
        "（": "）",
        "[": "]",
        "［": "］",
        "{": "}",
        "｛": "｝",
        "「": "」",
        "『": "』",
        "【": "】",
        "“": "”",
        "\"": "\"",
    }

    def configure_formatting_tags(self):
        """文字色とフォントサイズ用の全タグの配色とフォントを現在のテーマに合わせて動的適用する"""
        text_widget = self.editor._textbox
        mode = ctk.get_appearance_mode().lower() # "dark" or "light"
        
        # 1. 文字色タグの適用
        for color_key, color_config in FONT_COLORS.items():
            tag_name = f"color_{color_key}"
            text_hex = color_config[mode]
            text_widget.tag_configure(tag_name, foreground=text_hex)
            
        # 2. フォントサイズ・太字・下線タグの適用
        for size in FONT_SIZE_VALUES:
            text_widget.tag_configure(self.font_tag_name(size, False), font=self.scaled_editor_font(size=size))
            text_widget.tag_configure(self.font_tag_name(size, True), font=self.scaled_editor_font(size=size, weight="bold"))
        text_widget.tag_configure("underline", underline=True)
        text_widget.tag_configure("image_marker", elide=True)
        multi_select_bg = "#b8d8ff" if mode == "light" else "#315a83"
        text_widget.tag_configure("multi_select", background=multi_select_bg)
        text_widget.tag_configure("multi_select_preview", background=multi_select_bg)

    def scaled_editor_font(self, size=DEFAULT_FONT_SIZE, weight="normal", slant="roman", underline=False):
        """Tk Textタグ用に、CTkTextboxと同じスケーリング済みフォントタプルを返す。"""
        return self.editor._apply_font_scaling(app_font(size=size, weight=weight, slant=slant, underline=underline))

    def sync_editor_input_style(self):
        """IME変換中の文字も現在の入力スタイルで表示されるよう、本文の基準スタイルを同期する。"""
        if not hasattr(self, "editor"):
            return

        weight = "bold" if self.active_typing_bold else "normal"
        mode = ctk.get_appearance_mode().lower()
        default_text_hex = FONT_COLORS["default"][mode]
        cursor_color_config = FONT_COLORS.get(self.active_typing_color, FONT_COLORS["default"])
        cursor_hex = cursor_color_config[mode]

        self.editor.configure(
            font=app_font(
                size=self.active_typing_size,
                weight=weight,
                underline=False,
            ),
            text_color=default_text_hex,
        )
        self.editor._textbox.configure(insertbackground=cursor_hex)
        self.sync_windows_ime_font(weight)

    def on_title_focus_in(self, _event=None):
        """タイトル入力欄にフォーカスが移ったら、色ボタンの適用先をタイトルにする。"""
        self.color_target = "title"
        self.update_color_target_label()
        self.update_color_swatch_buttons()

    def on_editor_focus_in(self, _event=None):
        """本文エディタにフォーカスが移ったら、色ボタンの適用先を本文に戻す。"""
        self.color_target = "body"
        self.update_color_target_label()
        self.update_color_swatch_buttons()

    def apply_title_color(self, color_key):
        """タイトル入力欄の文字色を指定した色に変更する。"""
        if not hasattr(self, "title_entry"):
            return
        mode = ctk.get_appearance_mode().lower()
        color_config = FONT_COLORS.get(color_key, FONT_COLORS["default"])
        self.title_entry.configure(text_color=color_config[mode])

    def update_color_target_label(self):
        """色ボタンの対象（タイトル／本文）をラベルに表示する。"""
        if not hasattr(self, "color_label"):
            return
        if getattr(self, "color_target", "body") == "title":
            self.color_label.configure(text="文字色(タイトル):")
        else:
            self.color_label.configure(text="文字色(本文):")

    def sync_editor_cursor_color(self):
        mode = ctk.get_appearance_mode().lower()
        color_config = FONT_COLORS.get(self.active_typing_color, FONT_COLORS["default"])
        self.editor._textbox.configure(insertbackground=color_config[mode])

    def sync_windows_ime_font(self, weight="normal"):
        """Windows IMEの変換中文字にも、現在の入力フォントサイズを反映する。"""
        if imm32 is None or not hasattr(self, "editor"):
            return

        text_widget = self.editor._textbox
        try:
            hwnd = wintypes.HWND(text_widget.winfo_id())
            himc = imm32.ImmGetContext(hwnd)
            if not himc:
                return

            scaled_font = self.scaled_editor_font(
                size=self.active_typing_size,
                weight=weight,
                underline=False,
            )

            logfont = LOGFONTW()
            logfont.lfHeight = int(scaled_font[1])
            logfont.lfWeight = 700 if weight == "bold" else 400
            logfont.lfUnderline = 0
            logfont.lfCharSet = 1
            logfont.lfQuality = 5
            logfont.lfFaceName = str(scaled_font[0])[:31]
            imm32.ImmSetCompositionFontW(himc, ctypes.byref(logfont))
        except Exception:
            pass
        finally:
            try:
                if "himc" in locals() and himc:
                    imm32.ImmReleaseContext(hwnd, himc)
            except Exception:
                pass

    def color_swatch_color(self, color_key):
        mode = ctk.get_appearance_mode().lower()
        return FONT_COLORS.get(color_key, FONT_COLORS["default"])[mode]

    def _ring_border_color(self, swatch_hex):
        r = int(swatch_hex[1:3], 16)
        g = int(swatch_hex[3:5], 16)
        b = int(swatch_hex[5:7], 16)
        if b > r + 30 and b > g + 30:
            return "#ffa502"
        if r > b + 50 and g > b + 30:
            return "#4A9EFF"
        return "#4A9EFF"

    def update_color_swatch_buttons(self):
        if not hasattr(self, "color_buttons"):
            return
        if getattr(self, "color_target", "body") == "title" and self.current_note_id:
            note_data = next((n for n in self.data["notes"] if n["id"] == self.current_note_id), None)
            active_color_key = note_data.get("title_color", "default") if note_data else "default"
        else:
            active_color_key = getattr(self, "active_typing_color", "default")
        dark_mode = ctk.get_appearance_mode().lower() == "dark"
        for color_key, button in self.color_buttons.items():
            color = self.color_swatch_color(color_key)
            is_active = (color_key == active_color_key)
            if is_active:
                button.configure(
                    width=28, height=28, corner_radius=14,
                    fg_color=color, hover_color=color,
                    border_width=0,
                )
            else:
                w = 20
                bw = 1
                if color_key == "default" and dark_mode:
                    bc = "#777777"
                else:
                    bc = "white"
                button.configure(
                    width=w, height=w, corner_radius=w // 2,
                    fg_color=color, hover_color=color,
                    border_width=bw, border_color=bc,
                )

    def font_tag_name(self, size, bold):
        return f"bold_size_{size}" if bold else f"size_{size}"

    def get_text_style_at(self, index):
        tags = self.editor._textbox.tag_names(index)
        color = "default"
        size = DEFAULT_FONT_SIZE
        bold = False
        underline = False

        for tag in tags:
            if tag.startswith("color_"):
                color = tag.split("_", 1)[1]
            elif tag.startswith("bold_size_"):
                try:
                    size = int(tag.split("_")[2])
                    bold = True
                except (IndexError, ValueError):
                    pass
            elif tag.startswith("size_"):
                try:
                    size = int(tag.split("_")[1])
                    bold = False
                except (IndexError, ValueError):
                    pass
            elif tag == "underline":
                underline = True

        return color, size, bold, underline

    def set_active_typing_style(self, size=None, bold=None, underline=None, color=None):
        if size is not None:
            self.active_typing_size = int(size)
        if bold is not None:
            self.active_typing_bold = bool(bold)
        if underline is not None:
            self.active_typing_underline = bool(underline)
        if color is not None:
            self.active_typing_color = color
            self.update_color_swatch_buttons()

        if bold is not None or underline is not None:
            self.update_temporary_style_line()

        self.update_block_style_label()
        self.update_style_buttons()
        self.sync_editor_input_style()

    def update_block_style_label(self):
        self.block_style_var.set(self.block_style_label_for(self.active_typing_size, self.active_typing_bold))

    def block_style_label_for(self, size, bold=False):
        for label, config in BLOCK_STYLES.items():
            if config["size"] == size and config["bold"] == bool(bold):
                return label

        if size == BLOCK_STYLES[DEFAULT_BLOCK_STYLE_LABEL]["size"]:
            return DEFAULT_BLOCK_STYLE_LABEL

        for label, config in BLOCK_STYLES.items():
            if config["size"] == size:
                return label

        return DEFAULT_BLOCK_STYLE_LABEL

    def style_probe_index_at_insert(self):
        text_widget = self.editor._textbox
        try:
            insert = text_widget.index("insert")
            column = int(insert.split(".")[1])
            if text_widget.compare(insert, "<", "end-1c"):
                char = text_widget.get(insert, f"{insert} + 1c")
                if char != "\n":
                    return insert
            if column == 0:
                return None
            if text_widget.compare(insert, ">", "1.0"):
                return text_widget.index(f"{insert} - 1c")
        except (tk.TclError, ValueError):
            return None

        return None

    def refresh_current_style_display(self):
        probe_index = self.style_probe_index_at_insert()
        if probe_index is None:
            body_style = BLOCK_STYLES[DEFAULT_BLOCK_STYLE_LABEL]
            self.active_typing_size = body_style["size"]
            self.active_typing_bold = body_style["bold"]
            self.active_typing_underline = False
            self.block_style_var.set(DEFAULT_BLOCK_STYLE_LABEL)
            self.update_style_buttons()
            self.update_color_swatch_buttons()
            self.sync_editor_input_style()
            return

        color, size, bold, underline = self.get_text_style_at(probe_index)
        self.block_style_var.set(self.block_style_label_for(size, bold))
        self.active_typing_color = color
        self.active_typing_size = size
        self.active_typing_bold = bold
        self.active_typing_underline = underline
        self.update_style_buttons()
        self.update_color_swatch_buttons()
        self.sync_editor_input_style()

    def is_control_pressed(self, event):
        return bool(getattr(event, "state", 0) & 0x0004)

    def is_shift_pressed(self, event):
        return bool(getattr(event, "state", 0) & 0x0001)

    def on_editor_button_press(self, event):
        if self.select_line_if_margin_clicked(event):
            return "break"
        if not self.is_control_pressed(event):
            self.clear_multi_select_ranges()
        return None

    def on_editor_button_release(self, event):
        if not self.is_control_pressed(event):
            return None

        self.add_current_selection_to_multi_select()
        return None

    def current_insert_line(self):
        try:
            return int(self.editor._textbox.index("insert").split(".")[0])
        except (tk.TclError, ValueError):
            return None

    def color_is_locked(self):
        color_var = getattr(self, "keep_typing_color_var", None)
        return bool(color_var and color_var.get())

    def remember_temporary_color_line(self):
        self.temporary_typing_color_line = self.current_insert_line()

    def clear_temporary_color_line(self):
        self.temporary_typing_color_line = None

    def remember_temporary_style_line(self):
        self.temporary_typing_style_line = self.current_insert_line()

    def clear_temporary_style_line(self):
        self.temporary_typing_style_line = None

    def update_temporary_style_line(self):
        if self.active_typing_bold or self.active_typing_underline:
            self.remember_temporary_style_line()
        else:
            self.clear_temporary_style_line()

    def on_keep_typing_color_changed(self):
        if self.color_is_locked() or self.active_typing_color == "default":
            self.clear_temporary_color_line()
            return
        self.remember_temporary_color_line()

    def reset_temporary_color_on_cursor_move(self, _event=None):
        self.apply_temporary_typing_reset_if_needed()
        return None

    def apply_temporary_typing_reset_if_needed(self):
        self.apply_temporary_color_reset_if_needed()
        self.apply_temporary_style_reset_if_needed()
        self.refresh_current_style_display()

    def apply_temporary_color_reset_if_needed(self):
        if self.color_is_locked():
            return
        if self.active_typing_color == "default":
            self.clear_temporary_color_line()
            return

        color_line = getattr(self, "temporary_typing_color_line", None)
        current_line = self.current_insert_line()
        if color_line is None or current_line is None:
            return
        if current_line != color_line:
            self.reset_typing_color_to_default()

    def apply_temporary_style_reset_if_needed(self):
        if not self.active_typing_bold and not self.active_typing_underline:
            self.clear_temporary_style_line()
            return

        style_line = getattr(self, "temporary_typing_style_line", None)
        current_line = self.current_insert_line()
        if current_line is None:
            return
        if style_line is None:
            self.remember_temporary_style_line()
            return
        if current_line != style_line:
            self.reset_typing_emphasis_to_default()

    def reset_typing_color_to_default(self):
        self.active_typing_color = "default"
        self.update_color_swatch_buttons()
        self.clear_temporary_color_line()
        self.sync_editor_input_style()

    def reset_typing_emphasis_to_default(self):
        self.active_typing_bold = False
        self.active_typing_underline = False
        self.clear_temporary_style_line()
        self.update_block_style_label()
        self.update_style_buttons()
        self.sync_editor_input_style()

    def text_index_at_event(self, event):
        return self.editor._textbox.index(f"@{event.x},{event.y}")

    def line_range_at_event(self, event):
        index = self.text_index_at_event(event)
        line = index.split(".")[0]
        return f"{line}.0", f"{line}.end"

    def select_line_if_margin_clicked(self, event):
        if getattr(event, "x", 999) > 8:
            return False

        text_widget = self.editor._textbox
        try:
            start, end = self.line_range_at_event(event)
            text_widget.tag_remove("sel", "1.0", "end")

            if self.is_control_pressed(event):
                text_widget.tag_remove("multi_select_preview", "1.0", "end")
                self.add_multi_select_range(start, end)
            else:
                self.clear_multi_select_ranges()
                text_widget.tag_add("sel", start, end)

            text_widget.mark_set("insert", end)
            text_widget.focus_set()
            return True
        except tk.TclError:
            return False

    def ordered_text_range(self, start, end):
        text_widget = self.editor._textbox
        if text_widget.compare(start, "==", end):
            return None
        if text_widget.compare(start, ">", end):
            start, end = end, start
        return text_widget.index(start), text_widget.index(end)

    def add_multi_select_range(self, start, end):
        text_range = self.ordered_text_range(start, end)
        if text_range is None:
            return False

        self.editor._textbox.tag_add("multi_select", text_range[0], text_range[1])
        return True

    def on_multi_select_press(self, event):
        text_widget = self.editor._textbox
        self.add_current_selection_to_multi_select()
        text_widget.tag_remove("multi_select_preview", "1.0", "end")

        try:
            if getattr(event, "x", 999) <= 8:
                start, end = self.line_range_at_event(event)
                self.add_multi_select_range(start, end)
                text_widget.tag_remove("sel", "1.0", "end")
                self.multi_select_anchor = None
                text_widget.mark_set("insert", end)
                text_widget.focus_set()
                return "break"

            self.multi_select_anchor = self.text_index_at_event(event)
            text_widget.mark_set("insert", self.multi_select_anchor)
        except tk.TclError:
            self.multi_select_anchor = None

        return "break"

    def on_multi_select_drag(self, event):
        anchor = getattr(self, "multi_select_anchor", None)
        if anchor is None:
            return "break"

        text_widget = self.editor._textbox
        text_widget.tag_remove("multi_select_preview", "1.0", "end")

        try:
            current = self.text_index_at_event(event)
            text_range = self.ordered_text_range(anchor, current)
            if text_range is not None:
                text_widget.tag_add("multi_select_preview", text_range[0], text_range[1])
        except tk.TclError:
            pass

        return "break"

    def on_multi_select_release(self, event):
        anchor = getattr(self, "multi_select_anchor", None)
        if anchor is None:
            return "break"

        text_widget = self.editor._textbox
        text_widget.tag_remove("multi_select_preview", "1.0", "end")

        try:
            current = self.text_index_at_event(event)
            self.add_multi_select_range(anchor, current)
        except tk.TclError:
            pass

        self.multi_select_anchor = None
        text_widget.tag_remove("sel", "1.0", "end")
        return "break"

    def add_current_selection_to_multi_select(self):
        text_widget = self.editor._textbox
        try:
            if not text_widget.tag_ranges("sel"):
                return
            start = text_widget.index("sel.first")
            end = text_widget.index("sel.last")
            self.add_multi_select_range(start, end)
            text_widget.tag_remove("sel", "1.0", "end")
        except tk.TclError:
            return

    def clear_multi_select_ranges(self, _event=None):
        if hasattr(self, "editor"):
            try:
                self.editor._textbox.tag_remove("multi_select", "1.0", "end")
                self.editor._textbox.tag_remove("multi_select_preview", "1.0", "end")
                self.multi_select_anchor = None
            except tk.TclError:
                pass
        return None

    def selected_text_ranges(self):
        text_widget = self.editor._textbox
        ranges = []

        tag_ranges = text_widget.tag_ranges("multi_select")
        for i in range(0, len(tag_ranges), 2):
            ranges.append((text_widget.index(tag_ranges[i]), text_widget.index(tag_ranges[i + 1])))

        try:
            if text_widget.tag_ranges("sel"):
                ranges.append((text_widget.index("sel.first"), text_widget.index("sel.last")))
        except tk.TclError:
            pass

        normalized_ranges = []
        for start, end in ranges:
            if text_widget.compare(start, "==", end):
                continue
            if text_widget.compare(start, ">", end):
                start, end = end, start
            normalized_ranges.append((text_widget.index(start), text_widget.index(end)))

        return normalized_ranges

    def has_multi_select_ranges(self):
        try:
            return bool(self.editor._textbox.tag_ranges("multi_select"))
        except tk.TclError:
            return False

    def selected_plain_text_for_clipboard(self):
        ranges = self.normalized_text_ranges(self.selected_text_ranges())
        if not ranges:
            return None

        text_widget = self.editor._textbox
        return "\n".join(text_widget.get(start, end) for start, end in ranges)

    def copy_multi_select_to_clipboard(self):
        selected_text = self.selected_plain_text_for_clipboard()
        if selected_text is None:
            return False

        self.clipboard_clear()
        self.clipboard_append(selected_text)
        return True

    def delete_selected_text_ranges(self, record_history=True, trigger_save=True):
        ranges = self.normalized_text_ranges(self.selected_text_ranges())
        if not ranges:
            return None

        text_widget = self.editor._textbox
        first_start = ranges[0][0]
        before_style_snapshot = self.capture_style_snapshot(ranges) if record_history else []
        if record_history:
            try:
                text_widget.edit_separator()
            except tk.TclError:
                pass

        for start, end in reversed(ranges):
            text_widget.delete(start, end)

        text_widget.tag_remove("sel", "1.0", "end")
        self.clear_multi_select_ranges()
        text_widget.mark_set("insert", first_start)

        if record_history:
            self.mark_undo_separator(record_text_history=False)
            self.record_compound_text_history(
                undo_steps=1,
                redo_steps=1,
                before_style_snapshot=before_style_snapshot,
                after_style_snapshot=[],
            )
        if trigger_save:
            self.trigger_auto_save()
        return first_start

    def apply_text_style_to_selected_ranges(self, color=None, size=None, bold=None, underline=None, before_state=None):
        ranges = self.selected_text_ranges()
        if not ranges:
            return False

        target_ranges = []
        for start, end in ranges:
            target_ranges.extend(self.text_style_target_ranges(start, end, underline=underline))
        target_ranges = self.normalized_text_ranges(target_ranges)
        if not target_ranges:
            return True

        before_state = before_state or self.capture_active_typing_state()
        before_snapshot = self.capture_style_snapshot(target_ranges)
        for range_start, range_end in target_ranges:
            self.apply_text_style_range(range_start, range_end, color=color, size=size, bold=bold, underline=underline)
        after_snapshot = self.capture_style_snapshot(target_ranges)
        after_state = self.capture_active_typing_state()

        if self.record_style_history(before_snapshot, after_snapshot, before_state, after_state):
            self.trigger_auto_save()
        return True

    def current_block_style_target_ranges(self):
        start_line, end_line = self.selected_block_lines()
        ranges = []
        for line in range(start_line, end_line + 1):
            line_start = f"{line}.0"
            line_end = f"{line}.end"
            try:
                if self.editor._textbox.compare(line_start, "!=", line_end):
                    ranges.append((line_start, line_end))
            except tk.TclError:
                continue
        return self.normalized_text_ranges(ranges)

    def apply_style_operation_to_ranges(self, ranges, apply_callback, before_state=None):
        target_ranges = self.normalized_text_ranges(ranges)
        before_state = before_state or self.capture_active_typing_state()
        before_snapshot = self.capture_style_snapshot(target_ranges)

        apply_callback(target_ranges)

        after_snapshot = self.capture_style_snapshot(target_ranges)
        after_state = self.capture_active_typing_state()
        changed = self.record_style_history(before_snapshot, after_snapshot, before_state, after_state)
        if changed:
            self.trigger_auto_save()
        return changed

    def text_style_target_ranges(self, start, end, underline=None):
        text_widget = self.editor._textbox
        if underline is not True:
            return [(start, end)]

        target_ranges = []
        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])

        for line in range(start_line, end_line + 1):
            line_start = f"{line}.0"
            line_end = f"{line}.end"
            range_start = start if line == start_line else line_start
            range_end = end if line == end_line else line_end

            if text_widget.compare(range_start, ">=", range_end):
                continue
            if text_widget.compare(range_start, "==", line_start):
                range_start = self.skip_line_indent(range_start, range_end)
            if text_widget.compare(range_start, "<", range_end):
                target_ranges.append((text_widget.index(range_start), text_widget.index(range_end)))

        return target_ranges

    def skip_line_indent(self, start, end):
        text_widget = self.editor._textbox
        current = start
        while text_widget.compare(current, "<", end):
            char = text_widget.get(current, f"{current} + 1c")
            if char not in (" ", "\t", "\u3000"):
                break
            current = text_widget.index(f"{current} + 1c")
        return current

    def ensure_editor_history_state(self):
        if not hasattr(self, "editor_undo_stack"):
            self.editor_undo_stack = []
        if not hasattr(self, "editor_redo_stack"):
            self.editor_redo_stack = []
        if not hasattr(self, "suppress_editor_history"):
            self.suppress_editor_history = False

    def record_editor_history(self, entry):
        self.ensure_editor_history_state()
        if self.suppress_editor_history:
            return
        self.editor_undo_stack.append(entry)
        if len(self.editor_undo_stack) > self.MAX_EDITOR_HISTORY:
            del self.editor_undo_stack[:len(self.editor_undo_stack) - self.MAX_EDITOR_HISTORY]
        self.editor_redo_stack.clear()

    def mark_undo_separator(self, record_text_history=True):
        try:
            self.editor._textbox.edit_separator()
        except tk.TclError:
            pass

        if record_text_history:
            self.record_editor_history({"type": "text"})

    def reset_editor_undo_history(self):
        try:
            self.editor._textbox.edit_reset()
        except tk.TclError:
            pass
        self.ensure_editor_history_state()
        self.editor_undo_stack.clear()
        self.editor_redo_stack.clear()

    def capture_active_typing_state(self):
        return {
            "color": self.active_typing_color,
            "size": self.active_typing_size,
            "bold": self.active_typing_bold,
            "underline": self.active_typing_underline,
        }

    def restore_active_typing_state(self, state):
        self.active_typing_color = state.get("color", "default")
        self.active_typing_size = int(state.get("size", DEFAULT_FONT_SIZE))
        self.active_typing_bold = bool(state.get("bold", False))
        self.active_typing_underline = bool(state.get("underline", False))
        self.update_block_style_label()
        self.update_style_buttons()
        self.update_color_swatch_buttons()
        self.sync_editor_input_style()

    def normalized_text_ranges(self, ranges):
        text_widget = self.editor._textbox
        normalized = []
        for start, end in ranges:
            try:
                if text_widget.compare(start, "==", end):
                    continue
                if text_widget.compare(start, ">", end):
                    start, end = end, start
                normalized.append((text_widget.index(start), text_widget.index(end)))
            except tk.TclError:
                continue

        def sort_key(item):
            count_result = text_widget.count("1.0", item[0], "chars")
            return count_result[0] if count_result else 0

        normalized.sort(key=sort_key)
        merged = []
        for start, end in normalized:
            if not merged:
                merged.append([start, end])
                continue
            prev_start, prev_end = merged[-1]
            if text_widget.compare(start, "<=", prev_end):
                if text_widget.compare(end, ">", prev_end):
                    merged[-1][1] = end
            else:
                merged.append([start, end])

        return [(start, end) for start, end in merged]

    def capture_style_snapshot(self, ranges):
        text_widget = self.editor._textbox
        snapshot = []
        for start, end in self.normalized_text_ranges(ranges):
            count_result = text_widget.count(start, end, "chars")
            char_count = count_result[0] if count_result else 0
            if char_count <= 0:
                continue

            segments = []
            segment_start = start
            previous_style = None
            for i in range(char_count):
                char_idx = text_widget.index(f"{start} + {i} chars")
                style = self.get_text_style_at(char_idx)
                if previous_style is None:
                    previous_style = style
                elif style != previous_style:
                    segment_end = text_widget.index(f"{start} + {i} chars")
                    segments.append({
                        "start": text_widget.index(segment_start),
                        "end": text_widget.index(segment_end),
                        "style": previous_style,
                    })
                    segment_start = segment_end
                    previous_style = style

            segments.append({
                "start": text_widget.index(segment_start),
                "end": text_widget.index(end),
                "style": previous_style,
            })
            snapshot.append({"start": start, "end": end, "segments": segments})

        return snapshot

    def style_snapshot_equal(self, left, right):
        return left == right

    def restore_style_snapshot(self, snapshot):
        previous_suppress = getattr(self, "suppress_editor_history", False)
        self.suppress_editor_history = True
        try:
            for item in snapshot:
                start = item["start"]
                end = item["end"]
                for color_key in FONT_COLORS.keys():
                    self.editor._textbox.tag_remove(f"color_{color_key}", start, end)
                for font_size in FONT_SIZE_VALUES:
                    self.editor._textbox.tag_remove(self.font_tag_name(font_size, False), start, end)
                    self.editor._textbox.tag_remove(self.font_tag_name(font_size, True), start, end)
                self.editor._textbox.tag_remove("underline", start, end)

                for segment in item["segments"]:
                    color, size, bold, underline = segment["style"]
                    self.editor._textbox.tag_add(f"color_{color}", segment["start"], segment["end"])
                    self.editor._textbox.tag_add(self.font_tag_name(size, bold), segment["start"], segment["end"])
                    if underline:
                        self.editor._textbox.tag_add("underline", segment["start"], segment["end"])
        finally:
            self.suppress_editor_history = previous_suppress

    def record_style_history(self, before_snapshot, after_snapshot, before_state, after_state):
        if self.style_snapshot_equal(before_snapshot, after_snapshot) and before_state == after_state:
            return False

        self.record_editor_history({
            "type": "style",
            "before": before_snapshot,
            "after": after_snapshot,
            "before_state": before_state,
            "after_state": after_state,
        })
        return True

    def record_compound_text_history(self, undo_steps, redo_steps, before_style_snapshot=None, after_style_snapshot=None):
        self.record_editor_history({
            "type": "compound_text",
            "undo_steps": undo_steps,
            "redo_steps": redo_steps,
            "before_style": before_style_snapshot or [],
            "after_style": after_style_snapshot or [],
        })
        return True

    def track_native_text_edit(self, _event=None):
        if getattr(self, "suppress_editor_history", False):
            return None
        if getattr(self, "pending_native_text_edit_snapshot", None) is not None:
            return None

        try:
            text_widget = self.editor._textbox
            self.pending_native_text_edit_snapshot = text_widget.get("1.0", "end-1c")
            text_widget.edit_separator()
            self.after_idle(self.finish_native_text_edit_tracking)
        except tk.TclError:
            self.pending_native_text_edit_snapshot = None
        return None

    def finish_native_text_edit_tracking(self):
        before_text = getattr(self, "pending_native_text_edit_snapshot", None)
        self.pending_native_text_edit_snapshot = None
        if before_text is None:
            return

        try:
            after_text = self.editor._textbox.get("1.0", "end-1c")
        except tk.TclError:
            return

        if before_text != after_text:
            self.mark_undo_separator()

    def insert_text_with_active_style(self, text, record_history=True, trigger_save=True):
        text_widget = self.editor._textbox
        start = text_widget.index("insert")
        text_widget.insert("insert", text)
        end = text_widget.index("insert")

        for range_start, range_end in self.text_style_target_ranges(start, end, underline=self.active_typing_underline):
            self.apply_text_style_range(
                range_start,
                range_end,
                color=self.active_typing_color,
                size=self.active_typing_size,
                bold=self.active_typing_bold,
                underline=self.active_typing_underline,
            )

        self.mark_undo_separator(record_text_history=record_history)
        self.ensure_insert_cursor_visible()
        if trigger_save:
            self.trigger_auto_save()
        return start, end

    def ensure_insert_cursor_visible(self, _event=None):
        try:
            self.editor._textbox.see("insert")
        except tk.TclError:
            pass
        return None

    def line_bullet_prefix_before_insert(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert")
        indent = line_text[:len(line_text) - len(line_text.lstrip(" \t\u3000"))]
        rest = line_text[len(indent):]
        if not rest.startswith("・"):
            return None

        after_bullet = rest[1:]
        spaces = after_bullet[:len(after_bullet) - len(after_bullet.lstrip(" \t\u3000"))]
        return f"{indent}・{spaces or ' '}"

    def line_bullet_continuation_indent_before_insert(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert")
        indent = line_text[:len(line_text) - len(line_text.lstrip(" \t\u3000"))]
        rest = line_text[len(indent):]
        if not rest.startswith("・"):
            return None

        after_bullet = rest[1:]
        spaces = after_bullet[:len(after_bullet) - len(after_bullet.lstrip(" \t\u3000"))]
        return f"{indent}  {spaces}"

    def parse_numbered_list_prefix(self, line_text):
        indent = line_text[:len(line_text) - len(line_text.lstrip(" \t\u3000"))]
        rest = line_text[len(indent):]
        marker_candidates = [(rest.find(marker), marker) for marker in ("．", "：")]
        marker_candidates = [(index, marker) for index, marker in marker_candidates if index > 0]
        if not marker_candidates:
            return None

        marker_index, marker = min(marker_candidates, key=lambda item: item[0])

        number_text = rest[:marker_index]
        if not all(char.isdecimal() for char in number_text):
            return None

        number = 0
        for char in number_text:
            number = number * 10 + unicodedata.decimal(char)

        uses_fullwidth_digits = all("０" <= char <= "９" for char in number_text)
        return indent, number, uses_fullwidth_digits, marker, rest[marker_index + 1:]

    def format_list_number(self, number, uses_fullwidth_digits):
        number_text = str(number)
        if uses_fullwidth_digits:
            return number_text.translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        return number_text

    def line_numbered_prefix_before_insert(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert")
        parsed_prefix = self.parse_numbered_list_prefix(line_text)
        if parsed_prefix is None:
            return None

        indent, number, uses_fullwidth_digits, marker, after_marker = parsed_prefix
        spaces = after_marker[:len(after_marker) - len(after_marker.lstrip(" \t\u3000"))]
        return f"{indent}{self.format_list_number(number + 1, uses_fullwidth_digits)}{marker}{spaces}"

    def visual_indent_for_text(self, text):
        width = 0
        for char in text:
            width += 2 if unicodedata.east_asian_width(char) in ("F", "W") else 1
        return "\u3000" * (width // 2) + " " * (width % 2)

    def line_marker_continuation_indent_before_insert(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert")
        indent = line_text[:len(line_text) - len(line_text.lstrip(" \t\u3000"))]
        rest = line_text[len(indent):]

        marker_candidates = []
        for marker in ("．", "："):
            marker_index = rest.find(marker)
            if marker_index >= 0:
                marker_candidates.append((marker_index, marker))
        if not marker_candidates:
            return None

        marker_index, marker = min(marker_candidates, key=lambda item: item[0])
        marker_prefix = rest[:marker_index]
        if not marker_prefix or len(marker_prefix) > 12:
            return None
        if len(marker_prefix) > 4 and not any(char.isdigit() for char in marker_prefix):
            return None
        if any(char in " \t\u3000" for char in marker_prefix):
            return None

        after_marker = rest[marker_index + len(marker):]
        spaces = after_marker[:len(after_marker) - len(after_marker.lstrip(" \t\u3000"))]
        return f"{indent}{self.visual_indent_for_text(rest[:marker_index + len(marker)])}{spaces}"

    def current_line_indent_before_insert(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert lineend")
        return line_text[:len(line_text) - len(line_text.lstrip(" \t\u3000"))]

    def current_line_has_only_bullet(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert lineend")
        return line_text.strip(" \t\u3000") == "・"

    def current_line_has_only_numbered_prefix(self):
        text_widget = self.editor._textbox
        line_text = text_widget.get("insert linestart", "insert lineend")
        parsed_prefix = self.parse_numbered_list_prefix(line_text)
        if parsed_prefix is None:
            return False
        return not parsed_prefix[4].strip(" \t\u3000")

    def insert_new_line_without_bullet(self):
        continuation_indent = self.line_bullet_continuation_indent_before_insert()
        if continuation_indent is None:
            continuation_indent = self.line_marker_continuation_indent_before_insert()
        if continuation_indent is None:
            self.insert_text_with_active_style(f"\n{self.current_line_indent_before_insert()}")
        else:
            self.insert_text_with_active_style(f"\n{continuation_indent}")

        self.after_idle(self.reset_new_block_to_body)
        return "break"

    def insert_new_line_like_return(self):
        text_widget = self.editor._textbox
        bullet_prefix = self.line_bullet_prefix_before_insert()
        numbered_prefix = self.line_numbered_prefix_before_insert()

        if numbered_prefix and self.current_line_has_only_numbered_prefix():
            text_widget.delete("insert linestart", "insert lineend")
            self.insert_text_with_active_style("\n")
        elif numbered_prefix:
            self.insert_text_with_active_style(f"\n{numbered_prefix}")
        elif bullet_prefix and self.current_line_has_only_bullet():
            text_widget.delete("insert linestart", "insert lineend")
            self.insert_text_with_active_style("\n")
        elif bullet_prefix:
            self.insert_text_with_active_style(f"\n{bullet_prefix}")
        else:
            self.insert_text_with_active_style("\n")

        self.after_idle(self.reset_new_block_to_body)
        return "break"

    def selected_block_lines(self):
        text_widget = self.editor._textbox
        try:
            if text_widget.tag_ranges("sel"):
                start = text_widget.index("sel.first")
                end = text_widget.index("sel.last")
            else:
                start = text_widget.index("insert")
                end = start
        except tk.TclError:
            start = text_widget.index("insert")
            end = start

        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])
        if text_widget.compare(end, "==", f"{end_line}.0") and end_line > start_line:
            end_line -= 1
        return start_line, end_line

    def on_block_style_changed(self, style_label):
        if style_label not in BLOCK_STYLES:
            return

        before_state = self.capture_active_typing_state()
        config = BLOCK_STYLES[style_label]
        self.set_active_typing_style(size=config["size"], bold=config["bold"])
        selected_ranges = self.selected_text_ranges()
        if selected_ranges:
            target_ranges = self.normalized_text_ranges(selected_ranges)

            def apply_selected_style(resolved_ranges):
                for start, end in resolved_ranges:
                    self.apply_text_style_range(start, end, size=config["size"], bold=config["bold"])

            self.apply_style_operation_to_ranges(target_ranges, apply_selected_style, before_state=before_state)
            return

        target_ranges = self.current_block_style_target_ranges()

        def apply_block_style(resolved_ranges):
            for start, end in resolved_ranges:
                self.apply_text_style_range(start, end, size=config["size"], bold=config["bold"])

        self.apply_style_operation_to_ranges(target_ranges, apply_block_style, before_state=before_state)

    def handle_bracket_autocomplete(self, event):
        char = getattr(event, "char", "")
        if not char:
            return None

        text_widget = self.editor._textbox
        closing_chars = set(self.BRACKET_PAIRS.values())
        if char in closing_chars:
            try:
                next_char = text_widget.get("insert", "insert + 1c")
                if next_char == char:
                    text_widget.mark_set("insert", "insert + 1c")
                    return "break"
            except tk.TclError:
                return None

        closing_char = self.BRACKET_PAIRS.get(char)
        if closing_char is None:
            return None

        try:
            if text_widget.tag_ranges("sel"):
                start = text_widget.index("sel.first")
                end = text_widget.index("sel.last")
                text_widget.tag_remove("sel", "1.0", "end")
                text_widget.insert(end, closing_char)
                text_widget.insert(start, char)
                self.apply_text_style_range(
                    start,
                    f"{end} + 2c",
                    color=self.active_typing_color,
                    size=self.active_typing_size,
                    bold=self.active_typing_bold,
                    underline=self.active_typing_underline,
                )
                text_widget.mark_set("insert", f"{end} + 2c")
                self.mark_undo_separator()
                self.trigger_auto_save()
                return "break"

            self.insert_text_with_active_style(f"{char}{closing_char}")
            text_widget.mark_set("insert", "insert - 1c")
            return "break"
        except tk.TclError:
            return None

    def handle_bracket_pair_deletion(self, event):
        text_widget = self.editor._textbox
        keysym = getattr(event, "keysym", "")
        try:
            if keysym == "BackSpace":
                prev_idx = text_widget.index("insert - 1c")
                if text_widget.compare(prev_idx, "<", "1.0"):
                    return None
                open_char = text_widget.get(prev_idx, "insert")
                close_char = text_widget.get("insert", "insert + 1c")
                expected_close = self.BRACKET_PAIRS.get(open_char)
                if expected_close and expected_close == close_char:
                    text_widget.delete(prev_idx, "insert + 1c")
                    text_widget.mark_set("insert", prev_idx)
                    self.mark_undo_separator()
                    self.trigger_auto_save()
                    return "break"
            elif keysym == "Delete":
                open_char = text_widget.get("insert", "insert + 1c")
                close_char = text_widget.get("insert + 1c", "insert + 2c")
                expected_close = self.BRACKET_PAIRS.get(open_char)
                if expected_close and expected_close == close_char:
                    text_widget.delete("insert", "insert + 2c")
                    self.mark_undo_separator()
                    self.trigger_auto_save()
                    return "break"
        except tk.TclError:
            return None
        return None

    def handle_manual_bullet_autospace(self, event):
        if getattr(event, "char", "") != "・":
            return None

        text_widget = self.editor._textbox
        try:
            if text_widget.tag_ranges("sel"):
                insert_index = text_widget.index("sel.first")
            else:
                insert_index = text_widget.index("insert")

            line_before = text_widget.get(f"{insert_index} linestart", insert_index)
            if line_before.strip(" \t\u3000"):
                return None

            if text_widget.tag_ranges("sel"):
                start = text_widget.index("sel.first")
                end = text_widget.index("sel.last")
                text_widget.delete(start, end)
                text_widget.mark_set("insert", start)

            self.insert_text_with_active_style("・ ")
            return "break"
        except tk.TclError:
            return None

    def apply_text_style_range(self, start, end, color=None, size=None, bold=None, underline=None):
        text_widget = self.editor._textbox
        if text_widget.compare(start, "==", end):
            return
        if text_widget.compare(start, ">", end):
            start, end = end, start

        count_result = text_widget.count(start, end, "chars")
        char_count = count_result[0] if count_result else 0
        if char_count <= 0:
            return

        segments = []
        segment_start = start
        previous_style = None

        for i in range(char_count):
            char_idx = text_widget.index(f"{start} + {i} chars")
            current_style = self.get_text_style_at(char_idx)
            next_style = (
                color if color is not None else current_style[0],
                size if size is not None else current_style[1],
                bold if bold is not None else current_style[2],
                underline if underline is not None else current_style[3],
            )

            if previous_style is None:
                previous_style = next_style
            elif next_style != previous_style:
                segment_end = text_widget.index(f"{start} + {i} chars")
                segments.append((segment_start, segment_end, previous_style))
                segment_start = segment_end
                previous_style = next_style

        segments.append((segment_start, end, previous_style))

        for color_key in FONT_COLORS.keys():
            text_widget.tag_remove(f"color_{color_key}", start, end)
        for font_size in FONT_SIZE_VALUES:
            text_widget.tag_remove(self.font_tag_name(font_size, False), start, end)
            text_widget.tag_remove(self.font_tag_name(font_size, True), start, end)
        text_widget.tag_remove("underline", start, end)

        for segment_start, segment_end, style in segments:
            segment_color, segment_size, segment_bold, segment_underline = style
            text_widget.tag_add(f"color_{segment_color}", segment_start, segment_end)
            text_widget.tag_add(self.font_tag_name(segment_size, segment_bold), segment_start, segment_end)
            if segment_underline:
                text_widget.tag_add("underline", segment_start, segment_end)

    def on_key_pressed(self, event):
        bracket_result = self.handle_bracket_autocomplete(event)
        if bracket_result:
            return bracket_result

        bullet_result = self.handle_manual_bullet_autospace(event)
        if bullet_result:
            return bullet_result

        if getattr(event, "keysym", "") == "Return":
            return None

        if event.char and (event.char.isprintable() or event.char in ("\r", "\n", "\t")):
            try:
                text_widget = self.editor._textbox
                self.move_insert_out_of_image_marker()
                if text_widget.tag_ranges("sel"):
                    start_idx = text_widget.index("sel.first")
                else:
                    start_idx = text_widget.index("insert")

                if self.pending_format_start_index is None:
                    self.pending_format_start_index = start_idx

                if self.pending_format_after_id is None:
                    self.pending_format_after_id = self.after_idle(self.apply_formatting_to_pending_insert)
            except tk.TclError:
                pass

    def clear_pending_formatting(self):
        if self.pending_format_after_id is not None:
            try:
                self.after_cancel(self.pending_format_after_id)
            except Exception:
                pass
        self.pending_format_after_id = None
        self.pending_format_start_index = None

    def apply_formatting_to_pending_insert(self):
        try:
            self.pending_format_after_id = None
            if self.pending_format_start_index is None:
                return

            text_widget = self.editor._textbox
            start_idx = self.pending_format_start_index
            end_idx = text_widget.index("insert")
            self.pending_format_start_index = None

            if text_widget.compare(start_idx, "==", end_idx):
                return
            if text_widget.compare(start_idx, ">", end_idx):
                start_idx, end_idx = end_idx, start_idx

            for range_start, range_end in self.text_style_target_ranges(
                start_idx,
                end_idx,
                underline=self.active_typing_underline,
            ):
                self.apply_text_style_range(
                    range_start,
                    range_end,
                    color=self.active_typing_color,
                    size=self.active_typing_size,
                    bold=self.active_typing_bold,
                    underline=self.active_typing_underline,
                )
            self.mark_undo_separator()
        except Exception as e:
            log_error("タイピングフォーマット適用に失敗しました。", e)

    def image_marker_range_containing_index(self, index):
        text_widget = self.editor._textbox
        try:
            normalized_index = text_widget.index(index)
            ranges = text_widget.tag_prevrange("image_marker", f"{normalized_index} + 1c")
            if not ranges:
                return None

            marker_start, marker_end = ranges
            if text_widget.compare(marker_start, "<=", normalized_index) and text_widget.compare(normalized_index, "<", marker_end):
                return marker_start, marker_end
        except tk.TclError:
            return None

        return None

    def image_block_range_from_marker(self, marker_start, marker_end):
        text_widget = self.editor._textbox
        block_start = text_widget.index(marker_start)
        block_end = text_widget.index(marker_end)

        try:
            block_end = text_widget.index(f"{block_end} + 1c")
        except tk.TclError:
            return block_start, block_end

        for _ in range(2):
            try:
                next_char = text_widget.get(block_end, f"{block_end} + 1c")
                if next_char != "\n":
                    break
                block_end = text_widget.index(f"{block_end} + 1c")
            except tk.TclError:
                break

        return block_start, block_end

    def move_insert_out_of_image_marker(self, _event=None):
        try:
            marker_range = self.image_marker_range_containing_index("insert")
            if not marker_range:
                return None

            _, block_end = self.image_block_range_from_marker(marker_range[0], marker_range[1])
            self.editor._textbox.mark_set("insert", block_end)
        except tk.TclError:
            return None

        return None

    def image_marker_range_near_delete_cursor(self, keysym):
        text_widget = self.editor._textbox
        try:
            insert = text_widget.index("insert")
        except tk.TclError:
            return None

        for index in (insert, f"{insert} - 1c", f"{insert} + 1c"):
            marker_range = self.image_marker_range_containing_index(index)
            if marker_range:
                return marker_range

        if keysym == "BackSpace":
            ranges = text_widget.tag_prevrange("image_marker", insert)
            if ranges:
                block_start, block_end = self.image_block_range_from_marker(ranges[0], ranges[1])
                if text_widget.compare(block_start, "<", insert) and text_widget.compare(insert, "<=", block_end):
                    return ranges

        if keysym == "Delete":
            ranges = text_widget.tag_nextrange("image_marker", insert)
            if ranges:
                block_start, block_end = self.image_block_range_from_marker(ranges[0], ranges[1])
                if text_widget.compare(block_start, "<=", insert) and text_widget.compare(insert, "<", block_end):
                    return ranges

        return None

    def on_delete_key_pressed(self, event):
        self.clear_pending_formatting()

        if getattr(event, "keysym", "") not in ("BackSpace", "Delete"):
            return None

        if self.has_multi_select_ranges():
            self.delete_selected_text_ranges()
            return "break"

        bracket_delete_result = self.handle_bracket_pair_deletion(event)
        if bracket_delete_result:
            return bracket_delete_result

        marker_range = self.image_marker_range_near_delete_cursor(event.keysym)
        if not marker_range:
            self.track_native_text_edit()
            return None

        text_widget = self.editor._textbox
        block_start, block_end = self.image_block_range_from_marker(marker_range[0], marker_range[1])
        try:
            text_widget.delete(block_start, block_end)
            text_widget.mark_set("insert", block_start)
            self.mark_undo_separator()
            self.trigger_auto_save()
            return "break"
        except tk.TclError:
            return None

    def on_return_pressed(self, event):
        if self.is_shift_pressed(event):
            return self.insert_new_line_without_bullet()
        return self.insert_new_line_like_return()

    def on_down_pressed(self, _event):
        text_widget = self.editor._textbox
        try:
            current_line = int(text_widget.index("insert").split(".")[0])
            last_line = int(text_widget.index("end-1c").split(".")[0])
        except (tk.TclError, ValueError):
            return None

        if current_line >= last_line:
            return self.insert_new_line_like_return()
        return None

    def bind_editor_shortcuts(self):
        shortcuts = {
            "<Control-b>": self.shortcut_toggle_bold,
            "<Control-B>": self.shortcut_toggle_bold,
            "<Control-u>": self.shortcut_toggle_underline,
            "<Control-U>": self.shortcut_toggle_underline,
            "<Control-s>": self.shortcut_save_note,
            "<Control-S>": self.shortcut_save_note,
            "<Control-n>": self.shortcut_new_note,
            "<Control-N>": self.shortcut_new_note,
            "<Control-i>": self.shortcut_insert_image,
            "<Control-I>": self.shortcut_insert_image,
            "<Control-z>": self.shortcut_undo,
            "<Control-Z>": self.shortcut_undo,
            "<Control-y>": self.shortcut_redo,
            "<Control-Y>": self.shortcut_redo,
            "<Control-Shift-Z>": self.shortcut_redo,
        }
        for sequence, handler in shortcuts.items():
            self.bind_all(sequence, handler)

    def editor_has_focus(self):
        try:
            return self.focus_get() == self.editor._textbox
        except tk.TclError:
            return False

    def shortcut_toggle_bold(self, _event=None):
        if not self.editor_has_focus():
            return None
        self.toggle_typing_bold()
        return "break"

    def shortcut_toggle_underline(self, _event=None):
        if not self.editor_has_focus():
            return None
        self.toggle_typing_underline()
        return "break"

    def shortcut_save_note(self, _event=None):
        self.save_current_note_immediately()
        return "break"

    def shortcut_new_note(self, _event=None):
        self.add_new_note()
        return "break"

    def shortcut_insert_image(self, _event=None):
        if not self.editor_has_focus():
            return None
        self.insert_image()
        return "break"

    def on_copy_event(self, _event=None):
        if not self.has_multi_select_ranges():
            return None
        self.copy_multi_select_to_clipboard()
        return "break"

    def on_cut_event(self, _event=None):
        if not self.has_multi_select_ranges():
            self.track_native_text_edit()
            return None
        if self.copy_multi_select_to_clipboard():
            self.delete_selected_text_ranges()
        return "break"

    def on_paste_event(self, _event=None):
        if not self.has_multi_select_ranges():
            self.track_native_text_edit()
            return None

        try:
            clipboard_text = self.clipboard_get()
        except tk.TclError:
            return "break"

        text_widget = self.editor._textbox
        ranges = self.normalized_text_ranges(self.selected_text_ranges())
        before_style_snapshot = self.capture_style_snapshot(ranges)
        try:
            text_widget.edit_separator()
        except tk.TclError:
            pass

        insert_index = self.delete_selected_text_ranges(record_history=False, trigger_save=False)
        if insert_index is not None:
            text_widget.mark_set("insert", insert_index)
            insert_start, insert_end = self.insert_text_with_active_style(
                clipboard_text,
                record_history=False,
                trigger_save=False,
            )
            after_style_snapshot = self.capture_style_snapshot([(insert_start, insert_end)])
            self.record_compound_text_history(
                undo_steps=2,
                redo_steps=2,
                before_style_snapshot=before_style_snapshot,
                after_style_snapshot=after_style_snapshot,
            )
            self.trigger_auto_save()
        return "break"

    def shortcut_undo(self, _event=None):
        if not self.editor_has_focus():
            return None
        self.run_editor_undo_redo("undo")
        return "break"

    def shortcut_redo(self, _event=None):
        if not self.editor_has_focus():
            return None
        self.run_editor_undo_redo("redo")
        return "break"

    def run_editor_undo_redo(self, action):
        self.ensure_editor_history_state()
        source_stack = self.editor_undo_stack if action == "undo" else self.editor_redo_stack
        target_stack = self.editor_redo_stack if action == "undo" else self.editor_undo_stack

        if source_stack:
            entry = source_stack.pop()
            if entry.get("type") == "style":
                self.apply_style_history_entry(entry, action)
                target_stack.append(entry)
                return

            if entry.get("type") == "compound_text":
                if self.apply_compound_text_history_entry(entry, action):
                    target_stack.append(entry)
                return

            if entry.get("type") == "text":
                if self.apply_text_history_entry(action):
                    target_stack.append(entry)
                return

        if action == "undo":
            self.apply_text_history_entry(action)

    def apply_text_history_entry(self, action):
        previous_suppress = getattr(self, "suppress_editor_history", False)
        self.suppress_editor_history = True
        try:
            if action == "undo":
                self.editor._textbox.edit_undo()
            else:
                self.editor._textbox.edit_redo()
            self.after_idle(self.normalize_after_undo_redo)
            return True
        except tk.TclError:
            return False
        finally:
            self.suppress_editor_history = previous_suppress

    def apply_compound_text_history_entry(self, entry, action):
        steps_key = "undo_steps" if action == "undo" else "redo_steps"
        style_key = "before_style" if action == "undo" else "after_style"
        previous_suppress = getattr(self, "suppress_editor_history", False)
        self.suppress_editor_history = True
        try:
            edit_command = self.editor._textbox.edit_undo if action == "undo" else self.editor._textbox.edit_redo
            for _ in range(max(1, int(entry.get(steps_key, 1)))):
                edit_command()

            style_snapshot = entry.get(style_key, [])
            if style_snapshot:
                self.restore_style_snapshot(style_snapshot)

            self.after_idle(self.normalize_after_undo_redo)
            return True
        except (tk.TclError, ValueError, TypeError):
            return False
        finally:
            self.suppress_editor_history = previous_suppress

    def apply_style_history_entry(self, entry, action):
        snapshot_key = "before" if action == "undo" else "after"
        state_key = "before_state" if action == "undo" else "after_state"
        previous_suppress = getattr(self, "suppress_editor_history", False)
        self.suppress_editor_history = True
        try:
            self.restore_style_snapshot(entry.get(snapshot_key, []))
            self.restore_active_typing_state(entry.get(state_key, {}))
            if entry.get(snapshot_key):
                self.refresh_current_style_display()
            self.trigger_auto_save()
        finally:
            self.suppress_editor_history = previous_suppress

    def normalize_after_undo_redo(self):
        self.normalize_missing_formatting_tags()
        self.refresh_current_style_display()
        self.trigger_auto_save()

    def normalize_missing_formatting_tags(self):
        text_widget = self.editor._textbox
        try:
            end = text_widget.index("end-1c")
            if text_widget.compare("1.0", ">=", end):
                return

            current_start = None
            current_end = None
            char_count = text_widget.count("1.0", end, "chars")
            total_chars = char_count[0] if char_count else 0
            for i in range(total_chars):
                index = text_widget.index(f"1.0 + {i} chars")
                char = text_widget.get(index, f"{index} + 1c")
                if char == "\n":
                    if current_start is not None:
                        self.apply_default_text_style_range(current_start, current_end)
                        current_start = None
                    continue

                tags = text_widget.tag_names(index)
                has_size_tag = any(tag.startswith("size_") or tag.startswith("bold_size_") for tag in tags)
                has_color_tag = any(tag.startswith("color_") for tag in tags)
                if has_size_tag and has_color_tag:
                    if current_start is not None:
                        self.apply_default_text_style_range(current_start, current_end)
                        current_start = None
                    continue

                if current_start is None:
                    current_start = index
                current_end = text_widget.index(f"{index} + 1c")

            if current_start is not None:
                self.apply_default_text_style_range(current_start, current_end)
        except tk.TclError:
            return

    def apply_default_text_style_range(self, start, end):
        self.apply_text_style_range(
            start,
            end,
            color="default",
            size=DEFAULT_FONT_SIZE,
            bold=False,
            underline=False,
        )

    def reset_new_block_to_body(self):
        body_style = BLOCK_STYLES[DEFAULT_BLOCK_STYLE_LABEL]
        self.set_active_typing_style(size=body_style["size"], bold=body_style["bold"], underline=False)
        self.reset_temporary_color_on_cursor_move()

    def change_typing_color(self, color_key):
        if getattr(self, "color_target", "body") == "title":
            self.change_title_color(color_key)
            return

        before_state = self.capture_active_typing_state()
        self.active_typing_color = color_key
        self.update_color_swatch_buttons()
        if color_key == "default" or self.color_is_locked():
            self.clear_temporary_color_line()
        else:
            self.remember_temporary_color_line()
        self.sync_editor_cursor_color()

        if self.apply_text_style_to_selected_ranges(before_state=before_state, color=color_key):
            return

        after_state = self.capture_active_typing_state()
        self.record_style_history([], [], before_state, after_state)

    def change_title_color(self, color_key):
        """タイトルの色を変更し、ノート一覧にも即座に反映する。"""
        if not self.current_note_id:
            return
        note_data = next((n for n in self.data["notes"] if n["id"] == self.current_note_id), None)
        if not note_data:
            return

        note_data["title_color"] = color_key
        self.apply_title_color(color_key)
        self.save_current_note_immediately()
        self.update_note_card(self.current_note_id)
        self.update_color_swatch_buttons()

    def toggle_typing_bold(self):
        before_state = self.capture_active_typing_state()
        self.active_typing_bold = not self.active_typing_bold
        self.update_temporary_style_line()
        self.update_block_style_label()
        self.update_style_buttons()
        self.sync_editor_input_style()
        if not self.apply_text_style_to_selected_ranges(before_state=before_state, bold=self.active_typing_bold):
            after_state = self.capture_active_typing_state()
            self.record_style_history([], [], before_state, after_state)

    def toggle_typing_underline(self):
        before_state = self.capture_active_typing_state()
        self.active_typing_underline = not self.active_typing_underline
        self.update_temporary_style_line()
        self.update_block_style_label()
        self.update_style_buttons()
        self.sync_editor_input_style()
        if not self.apply_text_style_to_selected_ranges(before_state=before_state, underline=self.active_typing_underline):
            after_state = self.capture_active_typing_state()
            self.record_style_history([], [], before_state, after_state)

    def update_style_buttons(self):
        active_color = ("#d8d8d8", "#3a3a3a")
        inactive_color = ("#f1f1f1", "#2b2b2b")
        if hasattr(self, "bold_btn"):
            self.bold_btn.configure(fg_color=active_color if self.active_typing_bold else inactive_color, text_color=("#111111", "#ffffff"))
        if hasattr(self, "underline_btn"):
            self.underline_btn.configure(fg_color=active_color if self.active_typing_underline else inactive_color, text_color=("#111111", "#ffffff"))

    def toggle_app_theme(self):
        """表示テーマを切り替える。"""
        theme = self.theme_switch_var.get()
        if theme == "dark":
            ctk.set_appearance_mode("dark")
            self.theme_switch.configure(text="🌙 ダークモード")
        else:
            ctk.set_appearance_mode("light")
            self.theme_switch.configure(text="☀ ライトモード")
            
        self.configure_formatting_tags()
        self.update_color_swatch_buttons()
        
        if self.current_note_id:
            note_data = next((n for n in self.data["notes"] if n["id"] == self.current_note_id), None)
            if note_data:
                self.apply_title_color(note_data.get("title_color", "default"))

        self.sync_editor_input_style()
                
        self.update_ui_widget_colors_instantly()

    def update_ui_widget_colors_instantly(self):
        """テーマ変更後にリスト周辺の配色を更新する。"""
        mode = ctk.get_appearance_mode().lower()
        active_btn_color = "#3a3a3a" if mode == "dark" else "#d8d8d8"
        text_color = ("#1a1a1a", "#ffffff")
        
        # ジャンルリストの配色を更新する。
        for child in self.cat_scrollable.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                for sub_child in child.winfo_children():
                    if isinstance(sub_child, ctk.CTkButton):
                        if int(sub_child.grid_info().get("column", -1)) != 0:
                            continue
                        cat_name = sub_child.cget("text")
                        if cat_name:
                            is_active = (self.selected_category == cat_name)
                            bg = active_btn_color if is_active else "transparent"
                            sub_child.configure(fg_color=bg, text_color=text_color, hover_color=("gray75", "gray30"))
            elif isinstance(child, ctk.CTkButton):
                is_active = (self.selected_category == "全て")
                bg = active_btn_color if is_active else "transparent"
                child.configure(fg_color=bg, text_color=text_color, hover_color=("gray75", "gray30"))

        # ノートリストの配色を更新する。
        for child in self.notes_scrollable.winfo_children():
            if isinstance(child, ctk.CTkButton):
                note_id = getattr(child, "note_id", None)
                note_data = next((n for n in self.data["notes"] if n.get("id") == note_id), None)
                if note_data:
                    bg_color, card_text_color = self.note_card_colors(note_data)
                    child.configure(fg_color=bg_color, text_color=card_text_color, hover_color=("#c5c5c5", "#4a4a4a"))
                self.left_align_button_text(child)

    def left_align_button_text(self, button):
        """CTkButtonの複数行テキストを左揃えにする"""
        text_label = getattr(button, "_text_label", None)
        if text_label is not None:
            text_label.configure(anchor="w", justify="left")

    # ==========================================
    # 5. リッチテキストJSONシリアライザ (保存・復元)
    # ==========================================

    def get_rich_content_spans(self):
        """エディタ内の全テキストと装飾状態を解析し、JSON保存可能なリッチスパンのリストとして抽出する"""
        text_widget = self.editor._textbox
        text_str = text_widget.get("1.0", "end-1c")
        if not text_str:
            return []
            
        spans = []
        current_chars = []
        current_color = "default"
        current_size = DEFAULT_FONT_SIZE
        current_bold = False
        current_underline = False
        
        total_chars = len(text_str)
        for i in range(total_chars):
            char_idx = f"1.0 + {i} chars"
            char = text_widget.get(char_idx)
            
            tags = text_widget.tag_names(char_idx)
            color = "default"
            size = DEFAULT_FONT_SIZE
            bold = False
            underline = False
            for tag in tags:
                if tag.startswith("color_"):
                    color = tag.split("_", 1)[1]
                elif tag.startswith("bold_size_"):
                    try:
                        size = int(tag.split("_")[2])
                        bold = True
                    except (IndexError, ValueError):
                        pass
                elif tag.startswith("size_"):
                    try:
                        size = int(tag.split("_")[1])
                        bold = False
                    except (IndexError, ValueError):
                        pass
                elif tag == "underline":
                    underline = True
            
            if i == 0:
                current_chars = [char]
                current_color = color
                current_size = size
                current_bold = bold
                current_underline = underline
            elif color == current_color and size == current_size and bold == current_bold and underline == current_underline:
                current_chars.append(char)
            else:
                spans.append({
                    "text": "".join(current_chars),
                    "color": current_color,
                    "size": current_size,
                    "bold": current_bold,
                    "underline": current_underline
                })
                current_chars = [char]
                current_color = color
                current_size = size
                current_bold = bold
                current_underline = underline
                
        if current_chars:
            spans.append({
                "text": "".join(current_chars),
                "color": current_color,
                "size": current_size,
                "bold": current_bold,
                "underline": current_underline
            })
            
        for span in spans:
            lines = span["text"].split("\n")
            processed_lines = []
            for line in lines:
                old_image_prefix = "\U0001f4f7 [画像:"
                image_marker = parse_image_marker(line)
                if image_marker:
                    img_name, image_width = image_marker
                    processed_lines.append(image_marker_text(img_name, image_width))
                    continue
                if (line.startswith(old_image_prefix) or line.startswith("[画像:")) and line.endswith("]"):
                    img_name = line.replace(old_image_prefix, "").replace("[画像:", "").replace("]", "").strip()
                    processed_lines.append(f"[image:{img_name}]")
                elif line.strip() == "\ufffc":
                    continue
                else:
                    processed_lines.append(line)
            span["text"] = "\n".join(processed_lines)
            
        return spans

    def insert_image_block(self, text_widget, img_filename, width=DEFAULT_IMAGE_WIDTH):
        img_path = os.path.join(IMAGES_DIR, img_filename)
        if not os.path.exists(img_path):
            text_widget.insert(tk.INSERT, f"[画像が見つかりません: {img_filename}]\n")
            return

        try:
            pil_img = load_resized_image(img_path, width)
            if pil_img is None:
                text_widget.insert(tk.INSERT, f"[画像の描画失敗: {img_filename}]\n")
                return

            tk_img = ImageTk.PhotoImage(pil_img)
            self.keep_alive_images.append(tk_img)

            marker = image_marker_text(img_filename, width)
            text_widget.insert(tk.INSERT, f"{marker}\n", ("image_marker",))
            text_widget.image_create(tk.INSERT, image=tk_img)
            text_widget.insert(tk.INSERT, "\n\n")
        except Exception as e:
            text_widget.insert(tk.INSERT, f"[画像の描画失敗: {img_filename}]\n")
            log_error("画像の描画に失敗しました。", e)

    def render_note_content(self, spans_or_string):
        """保存データをエディタに復元し、画像をインライン表示する。"""
        self.editor.configure(state="normal")
        self.editor.delete("1.0", "end")
        self.keep_alive_images.clear()
        
        if isinstance(spans_or_string, str):
            spans = [{"text": spans_or_string, "color": "default", "size": DEFAULT_FONT_SIZE, "bold": False, "underline": False}]
        else:
            spans = spans_or_string
            
        text_widget = self.editor._textbox
        
        for span in spans:
            text = span.get("text", "")
            color = span.get("color", "default")
            size = span.get("size", DEFAULT_FONT_SIZE)
            bold = span.get("bold", False)
            underline = span.get("underline", False)
            
            color_tag = f"color_{color}"
            size_tag = self.font_tag_name(size, bold)
            text_tags = (color_tag, size_tag, "underline") if underline else (color_tag, size_tag)
            
            lines = text.split("\n")
            for idx, line in enumerate(lines):
                image_marker = parse_image_marker(line)
                if image_marker:
                    img_filename, image_width = image_marker
                    self.insert_image_block(text_widget, img_filename, image_width)
                else:
                    start_pos = text_widget.index(tk.INSERT)
                    text_widget.insert(tk.INSERT, line)
                    end_pos = text_widget.index(tk.INSERT)
                    
                    for tag in text_tags:
                        text_widget.tag_add(tag, start_pos, end_pos)
                    
                    if idx < len(lines) - 1:
                        start_nl = text_widget.index(tk.INSERT)
                        text_widget.insert(tk.INSERT, "\n")
                        end_nl = text_widget.index(tk.INSERT)
                        for tag in text_tags:
                            text_widget.tag_add(tag, start_nl, end_nl)

        self.reset_editor_undo_history()

    # ==========================================
    # 6. リスト更新 ＆ ノート読込・保存
    # ==========================================

