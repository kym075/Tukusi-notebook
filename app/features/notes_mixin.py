import datetime
import os
import re
import shutil
import uuid
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
from app.core.data import IMAGES_DIR, save_data
from app.features.image_embed import IMAGE_SIZE_OPTIONS, load_resized_image, normalize_image_markers_in_text, parse_image_marker
from app.features.quiz import QuizWindow
from app.core.ui_config import DEFAULT_FONT_SIZE, FONT_COLORS, app_font


class NotesMixin:
    def refresh_category_list(self):
        for child in self.cat_scrollable.winfo_children():
            child.destroy()

        mode = ctk.get_appearance_mode().lower()
        active_btn_color = "#3a3a3a" if mode == "dark" else "#d8d8d8"
        text_color = ("#1a1a1a", "#ffffff")

        all_btn_color = active_btn_color if self.selected_category == "全て" else "transparent"
        all_btn = ctk.CTkButton(self.cat_scrollable, text="📂 全て表示", anchor="w", font=app_font(size=13), text_color=text_color, fg_color=all_btn_color, hover_color=("gray75", "gray30"), command=lambda: self.select_category("全て"))
        all_btn.pack(fill="x", pady=2)

        for cat in self.data["categories"]:
            btn_color = active_btn_color if self.selected_category == cat else "transparent"
            
            cat_frame = ctk.CTkFrame(self.cat_scrollable, fg_color="transparent")
            cat_frame.pack(fill="x", pady=1)
            cat_frame.grid_columnconfigure(0, weight=1)

            cat_btn = ctk.CTkButton(cat_frame, text=cat, anchor="w", font=app_font(size=13), text_color=text_color, fg_color=btn_color, hover_color=("gray75", "gray30"), command=lambda c=cat: self.select_category(c))
            cat_btn.grid(row=0, column=0, sticky="ew")

            rename_cat_btn = ctk.CTkButton(cat_frame, text="✎", width=24, height=20, font=app_font(size=13), fg_color="transparent", text_color="gray60", hover_color=("gray75", "gray30"), command=lambda c=cat: self.rename_category(c))
            rename_cat_btn.grid(row=0, column=1, padx=(2, 0))

            del_cat_btn = ctk.CTkButton(cat_frame, text="×", width=24, height=20, font=app_font(size=13), fg_color="transparent", text_color="gray60", hover_color="#c0392b", command=lambda c=cat: self.delete_category(c))
            del_cat_btn.grid(row=0, column=2, padx=(2, 0))

        self.apply_app_fonts(self.cat_scrollable)

    def normalize_note_metadata(self):
        """既存ノートのメタデータと画像マーカーを補正する。"""
        changed = False
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for note in self.data.get("notes", []):
            if not note.get("created_at"):
                note["created_at"] = note.get("updated_at") or now
                changed = True
            if not note.get("updated_at"):
                note["updated_at"] = note.get("created_at") or now
                changed = True

            content = note.get("content", [])
            if isinstance(content, list):
                for span in content:
                    if not isinstance(span, dict) or not isinstance(span.get("text"), str):
                        continue
                    normalized_text = normalize_image_markers_in_text(span["text"])
                    if normalized_text != span["text"]:
                        span["text"] = normalized_text
                        changed = True

        if changed:
            save_data(self.data)

    def note_display_title(self, note):
        title = note.get("title", "").strip()
        return title if title else "無題のノート"

    def note_timestamp(self, note, key):
        if key == "created_at":
            return note.get("created_at") or note.get("updated_at") or ""
        return note.get("updated_at") or note.get("created_at") or ""

    def natural_title_key(self, note):
        title = self.note_display_title(note).casefold()
        parts = []
        for part in re.split(r"(\d+)", title):
            if not part:
                continue
            if part.isdecimal():
                parts.append((0, int(part), part))
            else:
                parts.append((1, part, ""))
        return tuple(parts)

    def get_filtered_notes(self):
        return [
            note for note in self.data["notes"]
            if self.selected_category == "全て" or note.get("category") == self.selected_category
        ]

    def sort_notes(self, notes):
        sorted_notes = sorted(
            notes,
            key=lambda note: (self.natural_title_key(note), self.note_timestamp(note, "created_at"), note.get("id", ""))
        )

        sort_mode = self.note_sort_var.get()
        if sort_mode == "新しい順":
            sorted_notes.sort(key=lambda note: self.note_timestamp(note, "created_at"), reverse=True)
        elif sort_mode == "古い順":
            sorted_notes.sort(key=lambda note: self.note_timestamp(note, "created_at"))
        elif sort_mode == "更新順":
            sorted_notes.sort(key=lambda note: self.note_timestamp(note, "updated_at"), reverse=True)

        return sorted_notes

    def on_note_sort_changed(self, _selected_label=None):
        self.refresh_notes_list()

    def refresh_notes_list(self):
        for child in self.notes_scrollable.winfo_children():
            child.destroy()
        self.note_cards_by_id = {}

        self.list_title.configure(text=f"{self.selected_category} のノート")

        filtered_notes = self.sort_notes(self.get_filtered_notes())

        if not filtered_notes:
            no_note_label = ctk.CTkLabel(self.notes_scrollable, text="ノートがありません", text_color="gray60", font=app_font(size=12, slant="italic"))
            no_note_label.pack(pady=20)
            self.apply_app_fonts(self.notes_scrollable)
            return

        mode = ctk.get_appearance_mode().lower()

        for note in filtered_notes:
            note_id = note["id"]
            title = self.note_display_title(note)
            color_key = self.note_text_color_key(note)

            font_color_config = FONT_COLORS.get(color_key, FONT_COLORS["default"])
            card_text_color = font_color_config[mode]

            if self.current_note_id == note_id:
                bg_color = "#3a3a3a" if mode == "dark" else "#d0d0d0"
            else:
                bg_color = "#2a2a2a" if mode == "dark" else "#e0e0e0"
                if color_key == "default":
                    card_text_color = "#888888" if mode == "dark" else "#555555"

            note_card = ctk.CTkButton(
                self.notes_scrollable,
                text=f"{title}\n🕒 更新: {note.get('updated_at', '')[:16]}",
                anchor="w",
                font=app_font(size=13),
                fg_color=bg_color,
                text_color=card_text_color,
                hover_color=("#c5c5c5", "#4a4a4a"),
                height=50,
                command=lambda nid=note_id: self.select_note(nid)
            )
            note_card.note_id = note_id
            self.left_align_button_text(note_card)
            note_card.pack(fill="x", pady=3)
            self.note_cards_by_id[note_id] = note_card

        self.apply_app_fonts(self.notes_scrollable)

    def note_text_color_key(self, note):
        """ノート一覧に表示する文字色を決定する。title_color があれば優先し、なければ本文先頭の色を使う。"""
        if "title_color" in note:
            return note["title_color"]
        content = note.get("content", [])
        if isinstance(content, list) and len(content) > 0:
            return content[0].get("color", "default")
        return "default"

    def note_card_colors(self, note):
        mode = ctk.get_appearance_mode().lower()
        color_key = self.note_text_color_key(note)

        card_text_color = FONT_COLORS.get(color_key, FONT_COLORS["default"])[mode]

        if self.current_note_id == note.get("id"):
            bg_color = "#3a3a3a" if mode == "dark" else "#d0d0d0"
        else:
            bg_color = "#2a2a2a" if mode == "dark" else "#e0e0e0"
            if color_key == "default":
                card_text_color = "#888888" if mode == "dark" else "#555555"

        return bg_color, card_text_color

    def update_note_card(self, note_id):
        card = getattr(self, "note_cards_by_id", {}).get(note_id)
        note = next((n for n in self.data["notes"] if n["id"] == note_id), None)
        if not card or not note:
            self.refresh_notes_list()
            return

        bg_color, card_text_color = self.note_card_colors(note)
        card.configure(
            text=f"{self.note_display_title(note)}\n🕒 更新: {note.get('updated_at', '')[:16]}",
            fg_color=bg_color,
            text_color=card_text_color,
        )
        self.left_align_button_text(card)

    def select_category(self, category_name):
        self.selected_category = category_name
        self.refresh_category_list()
        self.refresh_notes_list()
        self.load_first_note()

    def load_first_note(self):
        filtered_notes = self.sort_notes(self.get_filtered_notes())
        if filtered_notes:
            self.select_note(filtered_notes[0]["id"])
        else:
            self.current_note_id = None
            self.title_entry.delete(0, "end")
            self.title_entry.configure(state="disabled")
            self.editor.delete("1.0", "end")
            self.editor.configure(state="disabled")

    def select_note(self, note_id):
        if self.auto_save_timer:
            self.after_cancel(self.auto_save_timer)
            self.auto_save_timer = None
        self.save_current_note_immediately()

        self.current_note_id = note_id
        self.keep_typing_color_var.set(False)
        self.color_target = "body"
        self.update_color_target_label()

        note_data = next((n for n in self.data["notes"] if n["id"] == note_id), None)
        if not note_data:
            return

        self.title_entry.configure(state="normal")
        self.editor.configure(state="normal")

        # タイトルのセット
        self.title_entry.delete(0, "end")
        self.title_entry.insert(0, note_data["title"])
        self.title_entry.xview_moveto(0)
        self.apply_title_color(note_data.get("title_color", "default"))

        # 新規入力の標準装飾は、既存ノートの先頭スタイルに引っ張られないよう固定する
        content_data = note_data.get("content", [])
        initial_size = DEFAULT_FONT_SIZE
        initial_color = "default"
        initial_bold = False
        initial_underline = False
        if isinstance(content_data, list) and len(content_data) > 0:
            initial_color = content_data[0].get("color", "default")
            
        self.active_typing_size = initial_size
        self.active_typing_color = initial_color
        self.active_typing_bold = initial_bold
        self.active_typing_underline = initial_underline
        self.clear_temporary_color_line()
        self.clear_temporary_style_line()
        self.update_block_style_label()
        self.update_style_buttons()
        self.update_color_swatch_buttons()

        # タグの構成を再同期
        self.configure_formatting_tags()
        self.sync_editor_input_style()

        # 本文と画像のデコード描画
        self.render_note_content(note_data["content"])
        self.clear_multi_select_ranges()
        self.editor._textbox.mark_set("insert", "1.0")
        self.editor._textbox.see("1.0")
        self.sync_editor_input_style()

        # リストハイライト更新
        self.refresh_notes_list()

    # ------------------------------------------
    # 自動保存 ＆ 削除
    # ------------------------------------------
    def trigger_auto_save(self, event=None):
        if not self.current_note_id:
            return
        if self.auto_save_timer:
            self.after_cancel(self.auto_save_timer)
        self.auto_save_timer = self.after(1000, self.auto_save_current_note)

    def auto_save_current_note(self):
        self.auto_save_timer = None
        save_result = self.save_current_note_immediately()
        if self.needs_full_refresh_after_save(save_result):
            self.refresh_notes_list()
        elif self.current_note_id:
            self.update_note_card(self.current_note_id)

    def needs_full_refresh_after_save(self, save_result):
        if not save_result:
            return False

        sort_mode = self.note_sort_var.get()
        if sort_mode == "更新順":
            return True
        if sort_mode == "名前順" and save_result.get("title_changed"):
            return True
        return False

    def save_current_note_immediately(self):
        if not self.current_note_id:
            return None

        note_data = next((n for n in self.data["notes"] if n["id"] == self.current_note_id), None)
        if note_data:
            new_title = self.title_entry.get()
            title_changed = note_data.get("title", "") != new_title
            note_data["title"] = new_title
            note_data["content"] = self.get_rich_content_spans()
            note_data["updated_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if "title_color" not in note_data:
                note_data["title_color"] = "default"
            save_data(self.data)
            return {"title_changed": title_changed}

        return None

    def add_category(self):
        dialog = ctk.CTkInputDialog(text="新しい教科（ジャンル）の名前を入力してください:", title="教科の追加", font=app_font(size=13))
        name = dialog.get_input()
        
        if name and name.strip():
            name = name.strip()
            if name in self.data["categories"]:
                messagebox.showwarning("警告", "その教科は既に存在します。")
                return
            
            self.data["categories"].append(name)
            save_data(self.data)
            
            self.selected_category = name
            self.refresh_category_list()
            self.refresh_notes_list()
            self.load_first_note()

    def rename_category(self, category_name):
        dialog = ctk.CTkInputDialog(text="新しい教科（ジャンル）の名前を入力してください:", title="教科名の変更", font=app_font(size=13))
        if hasattr(dialog, "_entry"):
            dialog._entry.insert(0, category_name)
            dialog._entry.select_range(0, "end")

        new_name = dialog.get_input()
        if new_name is None:
            return

        self.apply_category_rename(category_name, new_name)

    def apply_category_rename(self, old_name, new_name):
        new_name = new_name.strip()
        if not new_name or new_name == old_name:
            return

        if new_name in self.data["categories"]:
            messagebox.showwarning("警告", "その教科は既に存在します。")
            return

        try:
            category_index = self.data["categories"].index(old_name)
        except ValueError:
            return

        self.data["categories"][category_index] = new_name
        for note in self.data["notes"]:
            if note.get("category") == old_name:
                note["category"] = new_name

        if self.selected_category == old_name:
            self.selected_category = new_name

        save_data(self.data)
        self.refresh_category_list()
        self.refresh_notes_list()

    def delete_category(self, category_name):
        if not messagebox.askyesno("ジャンルの削除", f"「{category_name}」を削除しますか？\n(このジャンル内のメモは削除されず『未分類』へ移動します)"):
            return

        self.data["categories"].remove(category_name)
        
        for note in self.data["notes"]:
            if note.get("category") == category_name:
                note["category"] = "未分類"

        if "未分類" not in self.data["categories"] and any(n.get("category") == "未分類" for n in self.data["notes"]):
            self.data["categories"].append("未分類")

        save_data(self.data)
        
        self.selected_category = "全て"
        self.refresh_category_list()
        self.refresh_notes_list()
        self.load_first_note()

    def add_new_note(self):
        new_id = str(uuid.uuid4())
        
        initial_cat = self.selected_category
        if initial_cat == "全て":
            initial_cat = self.data["categories"][0] if self.data["categories"] else "未分類"

        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_note = {
            "id": new_id,
            "title": "",
            "title_color": "default",
            "content": [{"text": "", "color": "default", "size": DEFAULT_FONT_SIZE, "bold": False, "underline": False}],
            "category": initial_cat,
            "created_at": now,
            "updated_at": now
        }

        self.data["notes"].append(new_note)
        save_data(self.data)

        self.select_note(new_id)
        self.title_entry.focus_set()

    def delete_current_note(self):
        if not self.current_note_id:
            return

        if not messagebox.askyesno("ノートの削除", "このノートを本当に削除しますか？"):
            return

        self.data["notes"] = [n for n in self.data["notes"] if n["id"] != self.current_note_id]
        save_data(self.data)
        self.cleanup_unused_images()

        self.current_note_id = None
        self.refresh_notes_list()
        self.load_first_note()

    def referenced_image_filenames(self):
        image_names = set()
        for note in self.data.get("notes", []):
            content = note.get("content", [])
            if isinstance(content, str):
                texts = [content]
            elif isinstance(content, list):
                texts = [span.get("text", "") for span in content if isinstance(span, dict)]
            else:
                texts = []

            for text in texts:
                for line in text.split("\n"):
                    image_marker = parse_image_marker(line)
                    if image_marker:
                        image_names.add(image_marker[0])
                        continue

                    old_image_prefix = "\U0001f4f7 [画像:"
                    if (line.startswith(old_image_prefix) or line.startswith("[画像:")) and line.endswith("]"):
                        img_name = line.replace(old_image_prefix, "").replace("[画像:", "").replace("]", "").strip()
                        if img_name:
                            image_names.add(img_name)

        return image_names

    def cleanup_unused_images(self):
        if not os.path.isdir(IMAGES_DIR):
            return

        referenced_images = self.referenced_image_filenames()
        for filename in os.listdir(IMAGES_DIR):
            if filename.startswith("."):
                continue
            if os.path.splitext(filename)[1].lower() not in {".png", ".jpg", ".jpeg", ".gif", ".bmp"}:
                continue
            if filename in referenced_images:
                continue

            path = os.path.join(IMAGES_DIR, filename)
            if not os.path.isfile(path):
                continue

            try:
                os.remove(path)
            except OSError:
                pass

    def ask_image_width(self):
        selected_width = {"value": None}

        dialog = ctk.CTkToplevel(self)
        dialog.title("📷 画像サイズ")
        dialog.geometry("320x170")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        container = ctk.CTkFrame(dialog, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=20, pady=18)

        ctk.CTkLabel(
            container,
            text="挿入する画像サイズを選択してください。",
            font=app_font(size=13),
        ).pack(anchor="w", pady=(0, 16))

        button_row = ctk.CTkFrame(container, fg_color="transparent")
        button_row.pack(fill="x")

        def choose(width):
            selected_width["value"] = width
            dialog.destroy()

        for label, width in IMAGE_SIZE_OPTIONS:
            ctk.CTkButton(
                button_row,
                text=f"{label} ({width}px)",
                width=88,
                font=app_font(size=12),
                command=lambda w=width: choose(w),
            ).pack(side="left", padx=4)

        ctk.CTkButton(
            container,
            text="キャンセル",
            fg_color="gray40",
            hover_color="gray30",
            font=app_font(size=12),
            command=dialog.destroy,
        ).pack(anchor="e", pady=(18, 0))

        dialog.wait_window()
        return selected_width["value"]

    def insert_image(self):
        if not self.current_note_id:
            return

        file_path = filedialog.askopenfilename(
            title="挿入する画像を選択",
            filetypes=[("画像ファイル", "*.png *.jpg *.jpeg *.gif *.bmp")]
        )
        if not file_path:
            return

        image_width = self.ask_image_width()
        if image_width is None:
            return

        try:
            if load_resized_image(file_path, image_width) is None:
                raise ValueError("画像を読み込めませんでした。")

            ext = os.path.splitext(file_path)[1]
            unique_name = f"{uuid.uuid4()}{ext}"
            dest_path = os.path.join(IMAGES_DIR, unique_name)
            shutil.copy(file_path, dest_path)

            text_widget = self.editor._textbox
            if "image_marker" in text_widget.tag_names("insert"):
                text_widget.mark_set("insert", "insert lineend + 1c")
            text_widget.insert(tk.INSERT, "\n")
            self.insert_image_block(text_widget, unique_name, image_width)
            self.save_current_note_immediately()
            self.refresh_notes_list()

        except Exception as e:
            messagebox.showerror("エラー", f"画像の挿入に失敗しました: {e}")


    # ==========================================
    # 7. AIクイズ
    # ==========================================

    def start_ai_quiz(self):
        if not self.current_note_id:
            return

        self.save_current_note_immediately()
        
        note_data = next((n for n in self.data["notes"] if n["id"] == self.current_note_id), None)
        if not note_data:
            return
            
        plain_text = ""
        content_spans = note_data.get("content", [])
        if isinstance(content_spans, list):
            for span in content_spans:
                plain_text += span.get("text", "")
        else:
            plain_text = content_spans 
            
        if not plain_text.strip():
            messagebox.showinfo("確認", "メモの内容が空です。内容を入力してからクイズを実行してください。")
            return
            
        dialog = ctk.CTkInputDialog(
            text="作成するクイズの問題数を入力してください (1〜10問):", 
            title="問題数の選択",
            font=app_font(size=13)
        )
        input_val = dialog.get_input()
        
        if input_val is None:
            return
            
        try:
            num_questions = int(input_val.strip())
            if num_questions < 1:
                num_questions = 3
            elif num_questions > 10:
                num_questions = 10
        except ValueError:
            num_questions = 3

        QuizWindow(self, plain_text, num_questions)

