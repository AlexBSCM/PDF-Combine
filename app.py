"""PDF Converter — точка входа и GUI (tkinter)."""
import json
import logging
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from PIL import Image, ImageOps, ImageTk

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND_AVAILABLE = True
except ImportError:
    DND_FILES = None
    TkinterDnD = None
    _DND_AVAILABLE = False

from converters.htmlpdf import find_browser, html_to_pdf
from converters.images import images_to_pdf
from converters.office import OfficeSession
from converters.preview import render_compressed
from converters.text import text_to_pdf
from gs_installer import install_ghostscript
from gs_locator import find_ghostscript
from merge import merge_pdfs, parse_pages, split_pdf
from optimize import QualitySettings, optimize_pdf

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
OFFICE_EXTS = {".docx", ".doc", ".rtf", ".xlsx", ".xls", ".pptx", ".ppt"}
HTML_EXTS = {".html", ".htm"}
TEXT_EXTS = {".txt", ".md"}
SUPPORTED_EXTS = IMAGE_EXTS | OFFICE_EXTS | HTML_EXTS | TEXT_EXTS

PRESETS = ["screen", "ebook", "printer", "prepress", "custom"]

# Палитра дизайн-системы "Aura PDF" (DESIGN.md / code.html)
COLORS = {
    "surface": "#f8f9ff",
    "surface_lowest": "#ffffff",
    "surface_low": "#eff4ff",
    "surface_high": "#dce9ff",
    "surface_container": "#e5eeff",
    "on_surface": "#0b1c30",
    "on_surface_variant": "#3d4947",
    "outline": "#6d7a77",
    "outline_variant": "#94a3b8",
    "primary": "#0D9488",
    "primary_hover": "#0f766e",
    "on_primary": "#ffffff",
    "secondary": "#565e74",
    "secondary_container": "#dae2fd",
    "on_secondary_container": "#5c647a",
    "error": "#ba1a1a",
    "log_fg": "#3d4947",
}

_APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "pdfconv")
_SETTINGS_PATH = os.path.join(_APPDATA_DIR, "settings.json")
_LOG_DIR = os.path.join(_APPDATA_DIR, "logs")

_DND_BASE = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk


class Card(tk.Frame):
    """Карточка со скруглёнными углами (canvas + вложенный фрейм)."""

    def __init__(self, master, radius=16, bg=COLORS["surface_lowest"],
                 border=COLORS["outline_variant"], pad=14, **kw):
        super().__init__(master, bg=master.cget("background"), bd=0, highlightthickness=0, **kw)
        self._radius = radius
        self._card_bg = bg
        self._card_border = border
        self._pad = pad
        self._canvas = tk.Canvas(self, bg=self.cget("background"), highlightthickness=0, bd=0)
        self._canvas.pack(fill="both", expand=True)
        self.inner = tk.Frame(self._canvas, bg=bg, bd=0, highlightthickness=0)
        self._win = self._canvas.create_window(pad, pad, window=self.inner, anchor="nw")
        self._canvas.bind("<Configure>", self._redraw)

    def _redraw(self, _event=None):
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if w < 2 or h < 2:
            return
        r = self._radius
        pad = self._pad
        self._canvas.delete("card")
        self._rr(self._canvas, 0, 0, w, h, r, self._card_border)
        self._rr(self._canvas, 2, 2, w - 4, h - 4, max(0, r - 2), self._card_bg)
        iw = max(1, w - 2 * pad)
        ih = max(1, h - 2 * pad)
        self._canvas.coords(self._win, pad, pad)
        self._canvas.itemconfig(self._win, width=iw, height=ih)

    @staticmethod
    def _rr(c, x1, y1, x2, y2, r, color):
        c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=color, outline=color, tags="card")
        c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=color, outline=color, tags="card")
        c.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=color, outline=color, tags="card")
        c.create_oval(x2 - 2 * r, y1, x2, y1 + 2 * r, fill=color, outline=color, tags="card")
        c.create_oval(x1, y2 - 2 * r, x1 + 2 * r, y2, fill=color, outline=color, tags="card")
        c.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=color, outline=color, tags="card")



def _setup_logging() -> logging.Logger:
    logger = logging.getLogger("pdfconv")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
        fh = logging.FileHandler(
            os.path.join(_LOG_DIR, time.strftime("app_%Y%m%d.log")), encoding="utf-8"
        )
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(fh)
    except Exception:
        pass
    return logger


log = _setup_logging()


def _sys_excepthook(tp, val, tb):
    log.error("Необработанное исключение: %s", val, exc_info=(tp, val, tb))
    sys.__excepthook__(tp, val, tb)


def _thread_excepthook(args):
    log.error(
        "Крэш потока %s: %s", args.thread.name if args.thread else "?",
        args.exc_value,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )


sys.excepthook = _sys_excepthook
threading.excepthook = _thread_excepthook


def build_jobs(files: list[str]) -> list[tuple]:
    """Раскладывает файлы по порядку списка; картинки группируются
    в один PDF на позиции первого изображения."""
    jobs: list[tuple] = []
    image_files: list[str] = []
    for f in files:
        ext = os.path.splitext(f)[1].lower()
        if ext in IMAGE_EXTS:
            if not any(j[0] == "images" for j in jobs):
                image_files = []
                jobs.append(("images", image_files))
            image_files.append(f)
        else:
            jobs.append(("file", f))
    return jobs


def unique_pdf_path(out_dir: str, stem: str) -> str:
    candidate = os.path.join(out_dir, f"{stem}.pdf")
    counter = 2
    while os.path.exists(candidate):
        candidate = os.path.join(out_dir, f"{stem}_{counter}.pdf")
        counter += 1
    return candidate


def fmt_size(num_bytes: float) -> str:
    if num_bytes >= 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.1f} МБ"
    return f"{num_bytes / 1024:.0f} КБ"


class App(_DND_BASE):
    def __init__(self):
        super().__init__()
        self.title("PDF Converter")
        self._apply_window_icon()
        self._apply_theme()

        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        w = min(1080, max(820, sw - 60))
        h = min(760, max(600, sh - 60))
        self.geometry(f"{w}x{h}")
        self.minsize(760, 560)

        self.settings = self._load_settings()
        self.files: list[str] = []
        self.gs_path = find_ghostscript()
        self.browser_path = find_browser()
        self.msg_queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()

        self._build_ui()
        self._toggle_custom()
        self.after(100, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        if not self.gs_path:
            self.after(600, self._offer_gs_install)

    def _apply_window_icon(self):
        icon = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico")
        if not os.path.exists(icon):
            return
        try:
            self.iconbitmap(icon)
        except tk.TclError:
            pass

    def _apply_theme(self):
        """Применяет палитру/типографику дизайн-системы 'Aura PDF' к ttk-виджетам."""
        import tkinter.font as tkfont

        try:
            avail = [f.lower() for f in tkfont.families()]
            ui = "Inter" if "inter" in avail else "Segoe UI"
            mono = "JetBrains Mono" if "jetbrains mono" in avail else "Consolas"
        except Exception:
            ui, mono = "Segoe UI", "Consolas"
        self._ui_font = ui
        self._mono_font = mono

        self.configure(background=COLORS["surface"])
        style = ttk.Style()
        style.theme_use("clam")
        C = COLORS

        style.configure(".", font=(ui, 10))
        style.configure("TFrame", background=C["surface"])
        style.configure(
            "TLabel",
            background=C["surface"],
            foreground=C["on_surface"],
            font=(ui, 11),
        )
        style.configure(
            "Header.TLabel",
            font=(ui, 15, "bold"),
            foreground=C["primary"],
            background=C["surface"],
        )
        style.configure(
            "TLabelFrame",
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            bordercolor=C["outline_variant"],
            borderwidth=1,
            relief="flat",
            labelmargins=(8, 6),
            font=(ui, 11, "bold"),
        )
        style.configure("Card.TFrame", background=C["surface_lowest"])
        style.configure(
            "Card.TLabel",
            background=C["surface_low"],
            foreground=C["on_surface_variant"],
            font=(ui, 11),
            relief="solid",
            borderwidth=1,
            padding=(5, 3),
            lightcolor=C["outline_variant"],
            darkcolor=C["outline_variant"],
        )
        style.configure(
            "CardTitle.TLabel",
            background=C["surface_low"],
            foreground=C["primary"],
            font=(ui, 13, "bold"),
            relief="solid",
            borderwidth=1,
            padding=(8, 5),
            lightcolor=C["outline_variant"],
            darkcolor=C["outline_variant"],
        )
        style.configure(
            "Card.TCheckbutton",
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            font=(ui, 10),
        )
        style.map("Card.TCheckbutton", indicatorcolor=[("selected", C["primary"])])
        style.configure(
            "TButton",
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            bordercolor=C["outline_variant"],
            borderwidth=1,
            relief="solid",
            font=(ui, 10, "bold"),
            padding=(10, 6),
        )
        style.map(
            "TButton",
            background=[("active", C["surface_low"]), ("pressed", C["surface_low"])],
        )
        style.configure(
            "Accent.TButton",
            background=C["primary"],
            foreground=C["on_primary"],
            borderwidth=0,
            relief="flat",
            font=(ui, 11, "bold"),
            padding=(14, 8),
        )
        style.map(
            "Accent.TButton",
            background=[("active", C["primary_hover"]), ("pressed", C["primary_hover"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=C["surface_lowest"],
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            bordercolor=C["outline_variant"],
            relief="flat",
            borderwidth=1,
            padding=5,
        )
        style.configure(
            "TCombobox",
            fieldbackground=C["surface_lowest"],
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            bordercolor=C["outline_variant"],
            relief="flat",
            borderwidth=1,
            padding=5,
            arrowssize=12,
        )
        style.map("TCombobox", fieldbackground=[("readonly", C["surface_lowest"])])
        style.configure(
            "TCheckbutton",
            background=C["surface_lowest"],
            foreground=C["on_surface"],
            font=(ui, 10),
        )
        style.map("TCheckbutton", indicatorcolor=[("selected", C["primary"])])
        style.configure(
            "Horizontal.TScale",
            background=C["primary"],
            troughcolor=C["surface_high"],
            sliderrelief="flat",
            sliderlength=18,
            borderwidth=0,
        )
        style.map(
            "Horizontal.TScale",
            background=[("active", C["primary_hover"]), ("disabled", C["outline_variant"])],
        )
        style.configure(
            "TProgressbar", troughcolor=C["surface_high"], background=C["primary"], borderwidth=0
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=C["surface_high"],
            background=C["primary"],
            borderwidth=0,
        )

    @staticmethod
    def _load_settings() -> dict:
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _save_settings(data: dict) -> None:
        try:
            os.makedirs(os.path.dirname(_SETTINGS_PATH), exist_ok=True)
            with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log.warning("Не удалось сохранить настройки: %s", e)

    def _collect_settings(self) -> dict:
        try:
            dpi = int(round(float(self.dpi_var.get())))
        except Exception:
            dpi = 150
        preset = self.preset_var.get()
        if preset not in PRESETS:
            preset = "ebook"
        try:
            jpeg_quality = int(round(float(self.jpeg_var.get())))
        except Exception:
            jpeg_quality = 75
        return {
            "out_dir": self.out_dir_var.get(),
            "preset": preset,
            "dpi": max(30, min(300, dpi)),
            "jpeg_quality": max(10, min(95, jpeg_quality)),
            "grayscale": bool(self.grayscale_var.get()),
            "merge": bool(self.merge_var.get()),
        }

    def _persist_settings(self):
        self.settings.update(self._collect_settings())
        self._save_settings(self.settings)

    def _offer_gs_install(self):
        choice = self.settings.get("gs_auto_install")
        if choice == "no":
            return
        if choice != "yes":
            answer = messagebox.askyesno(
                "Ghostscript",
                "Ghostscript не найден — сжатие PDF будет отключено.\n\n"
                "Скачать и установить автоматически (~62 МБ,\n"
                "потребуется подтвердить запрос Windows)?",
            )
            self.settings["gs_auto_install"] = "yes" if answer else "no"
            self._persist_settings()
            if not answer:
                return
        threading.Thread(target=self._install_gs_worker, daemon=True).start()

    def _install_gs_worker(self):
        try:
            path = install_ghostscript(
                progress_cb=lambda p: self.msg_queue.put(("gs_progress", p)),
                status_cb=self._queue_log,
            )
        except Exception as e:
            log.error("Автоустановка Ghostscript не удалась: %s", e, exc_info=True)
            self.msg_queue.put(("gs_result", ("error", str(e))))
            return
        self.msg_queue.put(("gs_result", ("ok", path)))

    def _build_ui(self):
        s = self.settings
        default_out = os.path.expanduser("~\\Desktop")
        saved_out = s.get("out_dir")
        out_dir_default = (
            saved_out if isinstance(saved_out, str) and os.path.isdir(saved_out) else default_out
        )
        saved_preset = s.get("preset") if s.get("preset") in PRESETS else "ebook"

        self._init_quality_vars(s, saved_preset, out_dir_default)
        self._preview_window = None

        # Верхняя панель вкладок (отдельные плашки)
        tabbar = tk.Frame(self, bg=COLORS["surface"])
        tabbar.pack(fill="x", padx=10, pady=(8, 4))
        self._nav_buttons = {}
        for key, label in (("files", "Файлы"), ("settings", "Настройки"), ("log", "Лог")):
            b = tk.Button(
                tabbar, text=label, relief="flat", bd=0,
                bg=COLORS["surface"], fg=COLORS["on_surface"],
                activebackground=COLORS["surface_low"], font=(self._ui_font, 11),
                padx=18, pady=8, cursor="hand2",
                highlightbackground=COLORS["outline_variant"], highlightthickness=1,
                command=lambda k=key: self._show_section(k),
            )
            b.pack(side="left", padx=4)
            self._nav_buttons[key] = b

        content = tk.Frame(self, bg=COLORS["surface"])
        content.pack(fill="both", expand=True, padx=10, pady=(0, 8))

        self.sections = {}
        self.sections["files"] = self._build_files_card(content, s)
        self.sections["settings"] = self._build_settings_card(content, s)
        self.sections["log"] = self._build_log_card(content)

        # Нижний блок (всегда видимый): статус + прогресс + Конвертировать
        footer = tk.Frame(self, bg=COLORS["surface"])
        footer.pack(fill="x", side="bottom", padx=10, pady=(2, 8))
        self.gs_label = ttk.Label(
            footer, text=self._gs_status_text(),
            foreground=(COLORS["on_surface_variant"] if self.gs_path else COLORS["error"]),
            font=(self._mono_font, 9),
        )
        self.gs_label.pack(side="left", padx=2)
        self.progress = ttk.Progressbar(footer, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=8)
        self.progress_lbl = ttk.Label(footer, text="", width=10, anchor="e")
        self.progress_lbl.pack(side="right", padx=(6, 0))
        self.convert_btn = ttk.Button(
            footer, text="Конвертировать", command=self.start_convert, style="Accent.TButton"
        )
        self.convert_btn.pack(side="right", padx=(6, 0))

        self._show_section("files")

    def _gs_status_text(self) -> str:
        return (
            f"Ghostscript: {self.gs_path}"
            if self.gs_path
            else "Ghostscript не найден — сжатие будет пропущено"
        )

    def _show_section(self, key: str):
        for k, sec in self.sections.items():
            if k == key:
                sec.pack(in_=sec.master, fill="both", expand=True, padx=0, pady=0)
            else:
                sec.pack_forget()
        for k, b in self._nav_buttons.items():
            if k == key:
                b.configure(
                    bg=COLORS["secondary_container"], fg=COLORS["on_secondary_container"],
                    activebackground=COLORS["secondary_container"],
                )
            else:
                b.configure(
                    bg=COLORS["surface"], fg=COLORS["on_surface"],
                    activebackground=COLORS["surface_low"],
                )

    def _init_quality_vars(self, s, saved_preset, out_dir_default):
        self.out_dir_var = tk.StringVar(value=out_dir_default)
        self.preset_var = tk.StringVar(value=saved_preset)
        dpi_saved = s.get("dpi", 150)
        try:
            dpi_saved = float(dpi_saved)
        except (TypeError, ValueError):
            dpi_saved = 150.0
        self.dpi_var = tk.DoubleVar(value=max(30, min(300, dpi_saved)))
        jpeg_saved = s.get("jpeg_quality", 75)
        try:
            jpeg_saved = int(jpeg_saved)
        except (TypeError, ValueError):
            jpeg_saved = 75
        self.jpeg_var = tk.IntVar(value=max(10, min(95, jpeg_saved)))
        self.grayscale_var = tk.BooleanVar(value=bool(s.get("grayscale", False)))
        self.merge_var = tk.BooleanVar(value=bool(s.get("merge", False)))

    def _build_files_card(self, master, s):
        card = Card(master, pad=16)
        inner = card.inner
        ttk.Label(inner, text="Файлы", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        h = tk.Frame(inner, bg=COLORS["surface_lowest"])
        h.pack(fill="both", expand=True)

        frm = tk.Frame(h, bg=COLORS["surface_lowest"])
        frm.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.listbox = tk.Listbox(
            frm, selectmode=tk.EXTENDED,
            bg=COLORS["surface_lowest"], fg=COLORS["on_surface"],
            selectbackground=COLORS["primary"], selectforeground=COLORS["on_primary"],
            font=(self._ui_font, 10), borderwidth=1, relief="flat",
            highlightthickness=0, activestyle="none",
        )
        self.listbox.pack(fill="both", expand=True, side="left", padx=4, pady=4)
        btns = tk.Frame(frm, bg=COLORS["surface_lowest"])
        btns.pack(side="right", fill="y", padx=4, pady=4)
        ttk.Button(btns, text="Добавить...", command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(btns, text="Убрать выбранное", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btns, text="Разделить PDF...", command=self.split_selected).pack(fill="x", pady=2)
        row_order = tk.Frame(btns, bg=COLORS["surface_lowest"])
        row_order.pack(fill="x", pady=2)
        ttk.Button(row_order, text="↑", width=3, command=self.move_up).pack(
            side="left", fill="x", expand=True
        )
        ttk.Button(row_order, text="↓", width=3, command=self.move_down).pack(
            side="right", fill="x", expand=True
        )
        if _DND_AVAILABLE:
            hint = "Перетащите файлы или папки в окно (папки сканируются рекурсивно)"
            self.drop_target_register(DND_FILES)
            self.listbox.drop_target_register(DND_FILES)
            self.dnd_bind("<<Drop>>", self._on_drop)
            self.listbox.dnd_bind("<<Drop>>", self._on_drop)
        else:
            hint = "Drag'n'drop недоступен: не установлен пакет tkinterdnd2"
        ttk.Label(frm, text=hint, style="Card.TLabel",
                  foreground=COLORS["on_surface_variant"]).pack(anchor="w", padx=4, pady=(4, 0))

        row_preview = tk.Frame(inner, bg=COLORS["surface_lowest"])
        row_preview.pack(fill="x", pady=(8, 0))
        ttk.Button(row_preview, text="Живой предпросмотр", command=self.open_preview).pack(side="left")
        ttk.Label(
            row_preview, text="Смотрите размер/качество до и после в реальном времени",
            style="Card.TLabel", foreground=COLORS["on_surface_variant"],
        ).pack(side="left", padx=6)
        return card

    def _build_settings_card(self, master, s):
        card = Card(master, pad=16)
        inner = card.inner
        ttk.Label(inner, text="Настройки", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))

        ttk.Label(inner, text="Папка вывода", style="Card.TLabel").pack(anchor="w", pady=(2, 2))
        frm_out = tk.Frame(inner, bg=COLORS["surface_lowest"])
        frm_out.pack(fill="x", pady=(0, 10))
        ttk.Entry(frm_out, textvariable=self.out_dir_var).pack(
            side="left", fill="x", expand=True, padx=5, pady=5
        )
        btns_out = tk.Frame(frm_out, bg=COLORS["surface_lowest"])
        btns_out.pack(side="right", padx=5, pady=5)
        ttk.Button(btns_out, text="Обзор...", command=self.choose_out_dir).pack(side="left", padx=2)
        ttk.Button(btns_out, text="Открыть папку", command=self.open_out_dir).pack(side="left", padx=2)

        ttk.Label(inner, text="Качество / размер", style="Card.TLabel").pack(anchor="w", pady=(8, 2))
        row_q = tk.Frame(inner, bg=COLORS["surface_lowest"])
        row_q.pack(fill="x", pady=(0, 6))
        self.params_info_lbl = ttk.Label(
            row_q, text="", style="Card.TLabel", foreground=COLORS["on_surface_variant"]
        )
        self.params_info_lbl.pack(side="left", padx=6)
        self._refresh_params_info()
        ttk.Button(row_q, text="Параметры сжатия...", command=self.open_compression_dialog).pack(side="right", padx=6, pady=4)

        ttk.Checkbutton(
            inner, text="Объединить всё в один PDF", variable=self.merge_var, style="Card.TCheckbutton"
        ).pack(anchor="w", padx=6, pady=(4, 2))
        return card

    def _refresh_params_info(self):
        if getattr(self, "params_info_lbl", None) is None:
            return
        self.params_info_lbl.configure(
            text=f"Пресет: {self.preset_var.get()}, DPI: {int(round(self.dpi_var.get()))}, "
                 f"JPEG: {int(round(self.jpeg_var.get()))}, "
                 f"Ч/Б: {'да' if self.grayscale_var.get() else 'нет'}"
        )

    def _build_log_card(self, master):
        card = Card(master, pad=16)
        inner = card.inner
        ttk.Label(inner, text="Лог выполнения", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 8))
        row_log = tk.Frame(inner, bg=COLORS["surface_lowest"])
        row_log.pack(fill="x", pady=(0, 4))
        self.copy_log_btn = ttk.Button(row_log, text="Копировать лог", command=self.copy_log)
        self.copy_log_btn.pack(side="right")
        self.log = tk.Text(
            inner, height=12,
            bg=COLORS["surface_lowest"], fg=COLORS["log_fg"],
            font=(self._mono_font, 9), borderwidth=1, relief="flat",
            selectbackground=COLORS["primary"], selectforeground=COLORS["on_primary"],
            padx=6, pady=6, insertbackground=COLORS["on_surface"],
        )
        self.log.pack(fill="both", expand=True)
        self.log.bind("<Control-c>", self._log_ctrl_c)
        return card

    def copy_log(self):
        text = self.log.get("1.0", "end-1c")
        if text.strip():
            self.clipboard_clear()
            self.clipboard_append(text)
            self.copy_log_btn.configure(text="Скопировано")
        else:
            self.copy_log_btn.configure(text="Лог пуст")
        self.after(1500, lambda: self.copy_log_btn.configure(text="Копировать лог"))

    def _log_ctrl_c(self, _event=None):
        if self.log.tag_ranges("sel"):
            self.log.event_generate("<<Copy>>")
        else:
            self.clipboard_clear()
            self.clipboard_append(self.log.get("1.0", "end-1c"))
        return "break"

    def _toggle_custom(self, _event=None):
        # Ползунки предпросмотра всегда активны (привязаны к настройкам)
        pass

    def _apply_preview_settings(self):
        self.preset_var.set("custom")
        self._persist_settings()
        self._refresh_params_info()

    def open_compression_dialog(self):
        CompressionDialog(
            self, self.preset_var, self.dpi_var, self.jpeg_var, self.grayscale_var,
            self._on_compression_applied,
        )

    def _on_compression_applied(self):
        self._persist_settings()
        self._refresh_params_info()

    def add_files(self):
        paths = filedialog.askopenfilenames(
            title="Выберите файлы",
            filetypes=[
                ("Все поддерживаемые", "*.jpg *.jpeg *.png *.bmp *.webp *.docx *.doc *.rtf "
                                       "*.xlsx *.xls *.pptx *.ppt *.html *.htm *.txt *.md"),
                ("Все файлы", "*.*"),
            ],
        )
        self._add_paths(paths)

    def _on_drop(self, event):
        try:
            paths = self.tk.splitlist(event.data)
        except Exception:
            return
        added = self._add_paths(paths)
        if added:
            self._queue_log(f"Добавлено файлов: {added}")

    def _add_paths(self, paths) -> int:
        added = 0
        for p in paths:
            p = os.path.normpath(p)
            if os.path.isdir(p):
                for root, _dirs, names in os.walk(p):
                    for entry in sorted(names):
                        full = os.path.join(root, entry)
                        if (
                            os.path.splitext(entry)[1].lower() in SUPPORTED_EXTS
                            and full not in self.files
                        ):
                            self.files.append(full)
                            self.listbox.insert(tk.END, full)
                            added += 1
                continue
            if p not in self.files:
                self.files.append(p)
                self.listbox.insert(tk.END, p)
                added += 1
        pw = getattr(self, "_preview_window", None)
        if pw is not None and pw.winfo_exists():
            pw.panel.refresh_images()
        return added

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            del self.files[i]
            self.listbox.delete(i)
        pw = getattr(self, "_preview_window", None)
        if pw is not None and pw.winfo_exists():
            pw.panel.refresh_images()

    def move_up(self):
        sel = self.listbox.curselection()
        if sel and sel[0] > 0:
            self._move(sel[0], -1)

    def move_down(self):
        sel = self.listbox.curselection()
        if sel and sel[0] < len(self.files) - 1:
            self._move(sel[0], 1)

    def _move(self, index: int, delta: int):
        new_index = index + delta
        self.files[index], self.files[new_index] = self.files[new_index], self.files[index]
        text = self.listbox.get(index)
        self.listbox.delete(index)
        self.listbox.insert(new_index, text)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(new_index)
        self.listbox.activate(new_index)

    def choose_out_dir(self):
        d = filedialog.askdirectory()
        if d:
            self.out_dir_var.set(d)

    def open_out_dir(self):
        d = self.out_dir_var.get()
        if os.path.isdir(d):
            os.startfile(d)
        else:
            messagebox.showwarning("Нет папки", f"Папка не существует:\n{d}")

    def split_selected(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("Нет выбора", "Выберите PDF в списке.")
            return
        path = self.files[sel[0]]
        if os.path.splitext(path)[1].lower() != ".pdf":
            messagebox.showwarning("Не PDF", "Выбранный элемент не является PDF.")
            return
        try:
            from pypdf import PdfReader
            total = len(PdfReader(path).pages)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прочитать PDF:\n{e}")
            return
        spec = simpledialog.askstring(
            "Разделить PDF",
            f"Какие страницы извлечь? Всего {total}.\nПример: 1-3,5",
            parent=self,
        )
        if not spec or not spec.strip():
            return
        try:
            pages = parse_pages(spec, total)
        except ValueError as e:
            messagebox.showerror("Ошибка", str(e))
            return
        stem = os.path.splitext(os.path.basename(path))[0]
        safe_spec = re.sub(r"[^\w\-]+", "_", spec.strip())
        target = unique_pdf_path(self.out_dir_var.get(), f"{stem}_p{safe_spec}")
        try:
            count = split_pdf(path, pages, target)
        except Exception as e:
            log.error("Ошибка разделения %s: %s", path, e)
            messagebox.showerror("Ошибка", f"Не удалось разделить PDF:\n{e}")
            return
        log.info("Split %s -> %s (%d стр.)", path, target, count)
        self._queue_log(f"Сохранено: {target}")
        messagebox.showinfo("Готово", f"Извлечено страниц: {count}\n{target}")

    def _queue_log(self, msg: str):
        self.msg_queue.put(("log", msg))

    def _poll_queue(self):
        was_cancelled = False
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.log.insert(tk.END, payload + "\n")
                    self.log.see(tk.END)
                elif kind == "progress":
                    done, total = payload
                    self.progress.configure(maximum=total, value=done)
                    self.progress_lbl.configure(text=f"{done} / {total}")
                elif kind == "enable":
                    self.convert_btn.configure(text="Конвертировать", command=self.start_convert)
                    self.convert_btn.state(["!disabled"])
                    self.progress.configure(value=0)
                    self.progress_lbl.configure(text="")
                elif kind == "gs_progress":
                    self.progress.configure(maximum=100, value=payload)
                    self.progress_lbl.configure(text=f"GS {payload}%")
                elif kind == "gs_result":
                    status, payload = payload
                    if status == "ok":
                        self.gs_path = payload
                        self.gs_label.configure(
                            text=f"Ghostscript: {payload}", foreground="black"
                        )
                        self._queue_log(f"Ghostscript установлен: {payload}")
                        log.info("Ghostscript установлен: %s", payload)
                        messagebox.showinfo(
                            "Готово", f"Ghostscript установлен:\n{payload}"
                        )
                    else:
                        self.gs_label.configure(
                            text="Ghostscript не найден — сжатие будет пропущено",
                            foreground="red",
                        )
                        messagebox.showwarning(
                            "Ошибка установки",
                            f"Не удалось установить Ghostscript:\n{payload}\n\n"
                            "Сжатие будет пропущено. Установите вручную с "
                            "https://ghostscript.com/releases/gsdnld.html",
                        )
                    self.progress.configure(value=0)
                    self.progress_lbl.configure(text="")
                elif kind == "cancelled":
                    was_cancelled = True
                elif kind == "summary":
                    if payload:
                        messagebox.showwarning("Готово с ошибками", payload)
                    elif was_cancelled:
                        messagebox.showinfo("Остановлено", "Конвертация остановлена пользователем.")
                    else:
                        messagebox.showinfo("Готово", "Конвертация завершена успешно.")
                    was_cancelled = False
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def start_convert(self):
        if not self.files:
            messagebox.showwarning("Нет файлов", "Сначала добавьте файлы.")
            return
        settings = self._collect_settings()
        self._persist_settings()
        log.info(
            "Старт конвертации: %d файлов, preset=%s, merge=%s",
            len(self.files), settings["preset"], settings["merge"],
        )
        self.cancel_event.clear()
        self.convert_btn.configure(text="Стоп", command=self._request_cancel)
        threading.Thread(target=self._convert_all, daemon=True).start()

    def _request_cancel(self):
        self.cancel_event.set()
        self.convert_btn.state(["disabled"])

    def _convert_all(self):
        errors: list[str] = []
        cancelled = False
        try:
            out_dir = self.out_dir_var.get()
            os.makedirs(out_dir, exist_ok=True)
            settings = QualitySettings(
                preset=self.preset_var.get(),
                dpi=int(round(float(self.dpi_var.get()))),
                grayscale=self.grayscale_var.get(),
                jpeg_quality=int(round(float(self.jpeg_var.get()))),
            )

            jobs = build_jobs(self.files)
            produced: list[str] = []

            with OfficeSession() as office, tempfile.TemporaryDirectory() as tmp:
                total = len(jobs)
                for idx, job in enumerate(jobs, 1):
                    if self.cancel_event.is_set():
                        cancelled = True
                        self._queue_log("Остановлено пользователем.")
                        break
                    self.msg_queue.put(("progress", (idx - 1, total)))

                    if job[0] == "images":
                        _, image_files = job
                        raw_path = os.path.join(tmp, "images_raw.pdf")
                        self._queue_log(f"Собираю {len(image_files)} изображений в PDF...")
                        try:
                            if settings.preset == "custom":
                                images_to_pdf(
                                    image_files, raw_path, work_dir=tmp,
                                    dpi=settings.dpi, jpeg_quality=settings.jpeg_quality,
                                    grayscale=settings.grayscale,
                                )
                                final_path = unique_pdf_path(out_dir, "images")
                                shutil.move(raw_path, final_path)
                                self._queue_log(
                                    f"  -> {os.path.basename(final_path)} "
                                    f"(сжато: {fmt_size(os.path.getsize(final_path))})"
                                )
                                produced.append(final_path)
                            else:
                                images_to_pdf(image_files, raw_path, work_dir=tmp)
                                produced.append(
                                    self._optimize_and_place(raw_path, "images", out_dir, tmp, settings)
                                )
                        except Exception as e:
                            msg = f"Ошибка при конвертации изображений: {e}"
                            log.error("%s", msg, exc_info=True)
                            self._queue_log(msg)
                            errors.append(msg)
                        continue

                    _, path = job
                    ext = os.path.splitext(path)[1].lower()
                    name = os.path.splitext(os.path.basename(path))[0]
                    raw_path = os.path.join(tmp, f"{name}_raw.pdf")
                    try:
                        self._queue_log(f"Конвертирую: {os.path.basename(path)}")
                        if ext in OFFICE_EXTS:
                            office.convert(path, raw_path)
                        elif ext in HTML_EXTS:
                            html_to_pdf(path, raw_path, browser_path=self.browser_path)
                        elif ext in TEXT_EXTS:
                            text_to_pdf(path, raw_path)
                        else:
                            self._queue_log(f"  пропущено (формат не поддерживается): {ext}")
                            continue
                        produced.append(
                            self._optimize_and_place(raw_path, name, out_dir, tmp, settings)
                        )
                    except Exception as e:
                        msg = f"Ошибка ({os.path.basename(path)}): {e}"
                        log.error("%s", msg, exc_info=True)
                        self._queue_log(msg)
                        errors.append(msg)

                if not cancelled:
                    self.msg_queue.put(("progress", (total, total)))
                    if self.merge_var.get() and len(produced) > 1:
                        merged_path = unique_pdf_path(out_dir, "merged")
                        try:
                            merge_pdfs(produced, merged_path)
                            self._queue_log(f"Объединено в: {merged_path}")
                        except Exception as e:
                            msg = f"Ошибка объединения: {e}"
                            log.error("%s", msg, exc_info=True)
                            self._queue_log(msg)
                            errors.append(msg)
        except Exception as e:
            errors.append(f"Критическая ошибка: {e}")
            log.critical("Критическая ошибка конвертации", exc_info=True)
            self._queue_log(f"Критическая ошибка: {e}")
        finally:
            if errors:
                self._queue_log("Готово (с ошибками).")
                summary = "Во время конвертации возникли ошибки:\n" + "\n".join(errors)
            elif cancelled:
                self._queue_log("Остановлено.")
                summary = ""
                self.msg_queue.put(("cancelled", None))
            else:
                self._queue_log("Готово.")
                summary = ""
            self.msg_queue.put(("summary", summary))
            self.msg_queue.put(("enable", None))

    def _optimize_and_place(
        self, raw_path: str, name: str, out_dir: str, tmp: str, settings: QualitySettings
    ) -> str:
        before = os.path.getsize(raw_path)
        final_path = unique_pdf_path(out_dir, name)
        if self.gs_path:
            optimized_tmp = os.path.join(tmp, f"{name}_opt_{len(os.listdir(tmp))}.pdf")
            optimize_pdf(self.gs_path, raw_path, optimized_tmp, settings)
            shutil.move(optimized_tmp, final_path)
            self._queue_log(
                f"  -> {os.path.basename(final_path)} ({fmt_size(before)} -> {fmt_size(os.path.getsize(final_path))})"
            )
        else:
            shutil.copy(raw_path, final_path)
            self._queue_log(
                f"  -> {os.path.basename(final_path)} ({fmt_size(before)}, без сжатия — Ghostscript не найден)"
            )
        log.info("Готово: %s (%s)", final_path, fmt_size(os.path.getsize(final_path)))
        return final_path

    def _on_close(self):
        self._persist_settings()
        log.info("Приложение закрыто")
        self.destroy()

    def open_preview(self):
        if not any(os.path.splitext(f)[1].lower() in IMAGE_EXTS for f in self.files):
            messagebox.showwarning(
                "Нет изображений",
                "Добавьте в список хотя бы одно изображение (jpg/png/...), "
                "чтобы открыть предпросмотр сжатия.",
            )
            return

        provider = lambda: [f for f in self.files if os.path.splitext(f)[1].lower() in IMAGE_EXTS]

        def apply():
            self.preset_var.set("custom")
            self._persist_settings()
            self._refresh_params_info()

        if self._preview_window is not None and self._preview_window.winfo_exists():
            self._preview_window.lift()
            self._preview_window.panel.refresh_images()
            return
        self._preview_window = PreviewWindow(self, provider, self.dpi_var, self.jpeg_var, self.grayscale_var, apply)


class PreviewPanel(tk.Frame):
    """Встраиваемая панель живого предпросмотра сжатия изображения."""

    DEBOUNCE_MS = 160

    def __init__(self, master, image_provider, dpi_var, jpeg_var, gray_var, on_apply, **kw):
        super().__init__(master, **kw)
        self.image_provider = image_provider
        self.dpi_var = dpi_var
        self.jpeg_var = jpeg_var
        self.gray_var = gray_var
        self.on_apply = on_apply
        self._after_id = None
        self._photo_orig = None
        self._photo_comp = None

        top = ttk.Frame(self)
        top.pack(fill="x", padx=6, pady=4)
        ttk.Label(top, text="Изображение:", style="Card.TLabel").pack(side="left")
        self.var_image = tk.StringVar()
        self.combo = ttk.Combobox(top, textvariable=self.var_image, state="readonly", width=26)
        self.combo.pack(side="left", padx=6)
        self.combo.bind("<<ComboboxSelected>>", lambda _e: self._schedule())

        frm = tk.Frame(self, bg=COLORS["surface"])
        frm.pack(fill="both", expand=True, padx=6)
        left = Card(frm, radius=12, pad=10)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        right = Card(frm, radius=12, pad=10)
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        ttk.Label(left.inner, text="Оригинал", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 4))
        ttk.Label(right.inner, text="Сжатая версия", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 4))
        self.lbl_orig_img = ttk.Label(left.inner, style="Card.TLabel")
        self.lbl_orig_img.pack(expand=True)
        self.lbl_orig_info = ttk.Label(left.inner, style="Card.TLabel")
        self.lbl_orig_info.pack(pady=4)
        self.lbl_comp_img = ttk.Label(right.inner, style="Card.TLabel")
        self.lbl_comp_img.pack(expand=True)
        self.lbl_comp_info = ttk.Label(right.inner, style="Card.TLabel")
        self.lbl_comp_info.pack(pady=4)

        ctrls = Card(self, radius=12, pad=10)
        ctrls.pack(fill="x", padx=6, pady=4)
        ttk.Label(ctrls.inner, text="Параметры сжатия", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 4))
        r1 = tk.Frame(ctrls.inner, bg=COLORS["surface_lowest"])
        r1.pack(fill="x", padx=6, pady=3)
        ttk.Label(r1, text="DPI:").pack(side="left")
        ttk.Scale(r1, from_=30, to=300, variable=self.dpi_var, orient="horizontal").pack(
            side="left", fill="x", expand=True, padx=6
        )
        self.dpi_lbl = ttk.Label(r1, text=str(int(round(self.dpi_var.get()))), width=5, style="Card.TLabel")
        self.dpi_lbl.pack(side="left")
        r2 = tk.Frame(ctrls.inner, bg=COLORS["surface_lowest"])
        r2.pack(fill="x", padx=6, pady=3)
        ttk.Label(r2, text="JPEG:").pack(side="left")
        ttk.Scale(r2, from_=10, to=95, variable=self.jpeg_var, orient="horizontal").pack(
            side="left", fill="x", expand=True, padx=6
        )
        self.q_lbl = ttk.Label(r2, text=str(int(round(self.jpeg_var.get()))), width=5, style="Card.TLabel")
        self.q_lbl.pack(side="left")
        r3 = tk.Frame(ctrls.inner, bg=COLORS["surface_lowest"])
        r3.pack(fill="x", padx=6, pady=3)
        ttk.Checkbutton(
            r3, text="Ч/Б (grayscale)", variable=self.gray_var, command=self._schedule,
            style="Card.TCheckbutton",
        ).pack(side="left")
        self.est_lbl = ttk.Label(r3, text="", foreground="blue")
        self.est_lbl.pack(side="left", padx=10)

        bottom = ttk.Frame(self)
        bottom.pack(fill="x", padx=6, pady=4)
        self.status_lbl = ttk.Label(bottom, text="", foreground=COLORS["primary"], style="Card.TLabel")
        self.status_lbl.pack(side="left", padx=4)
        self.apply_btn = ttk.Button(bottom, text="Применить к настройкам", command=self._apply)
        self.apply_btn.pack(side="right")

        self.dpi_var.trace_add("write", self._on_change)
        self.jpeg_var.trace_add("write", self._on_change)
        self.refresh_images()
        self._update()

    def _on_change(self, *_a):
        self.dpi_lbl.configure(text=str(int(round(self.dpi_var.get()))))
        self.q_lbl.configure(text=str(int(round(self.jpeg_var.get()))))
        self._schedule()

    def refresh_images(self):
        names = [os.path.basename(p) for p in self.image_provider()]
        self.combo.configure(values=names)
        if names and self.var_image.get() not in names:
            self.var_image.set(names[0])
        elif not names:
            self.var_image.set("")
        has = bool(names)
        try:
            self.apply_btn.state(["!disabled"] if has else ["disabled"])
        except Exception:
            pass
        self._schedule()

    def _schedule(self):
        if self._after_id:
            self.after_cancel(self._after_id)
        self._after_id = self.after(self.DEBOUNCE_MS, self._update)

    def _current_path(self):
        paths = self.image_provider()
        if not paths:
            return None
        idx = self.combo.current()
        if idx < 0:
            idx = 0
        return paths[idx]

    def _update(self):
        path = self._current_path()
        if not path:
            self.lbl_orig_info.configure(text="Нет изображений")
            self.lbl_comp_info.configure(text="")
            self.est_lbl.configure(text="")
            return
        try:
            with Image.open(path) as im:
                base = ImageOps.exif_transpose(im)
            orig_bytes = os.path.getsize(path)
        except Exception as e:
            self.lbl_comp_info.configure(text=f"Ошибка: {e}")
            return

        disp = base.copy()
        disp.thumbnail((200, 200))
        self._photo_orig = ImageTk.PhotoImage(disp)
        self.lbl_orig_img.configure(image=self._photo_orig)
        self.lbl_orig_info.configure(text=f"{base.width}x{base.height}, {fmt_size(orig_bytes)}")

        dpi = int(round(self.dpi_var.get()))
        q = int(round(self.jpeg_var.get()))
        gray = self.gray_var.get()
        try:
            comp, size = render_compressed(path, dpi, q, gray)
        except Exception as e:
            self.lbl_comp_info.configure(text=f"Ошибка: {e}")
            return
        disp2 = comp.copy()
        disp2.thumbnail((200, 200))
        self._photo_comp = ImageTk.PhotoImage(disp2)
        self.lbl_comp_img.configure(image=self._photo_comp)
        mode = "Ч/Б" if gray else "цвет"
        self.lbl_comp_info.configure(
            text=f"{comp.width}x{comp.height}, ~{fmt_size(size)} на стр.\nDPI {dpi}, q{q}, {mode}"
        )
        self.est_lbl.configure(text=f"Оценка: {fmt_size(orig_bytes)} -> ~{fmt_size(size)}")

    def _apply(self):
        try:
            self.on_apply()
        except Exception as e:
            messagebox.showerror("Ошибка применения", str(e))
            return
        dpi = int(round(self.dpi_var.get()))
        q = int(round(self.jpeg_var.get()))
        self.status_lbl.configure(text=f"✓ Применено: custom, DPI {dpi}, JPEG {q}")
        self.after(2600, lambda: self.status_lbl.configure(text=""))


class PreviewWindow(tk.Toplevel):
    """Отдельное окно предпросмотра (обёртка над PreviewPanel)."""

    def __init__(self, master, image_provider, dpi_var, jpeg_var, gray_var, on_apply):
        super().__init__(master)
        self.title("Предпросмотр сжатия")
        self.geometry("760x560")
        self.transient(master)
        self.configure(background=COLORS["surface"])
        self.panel = PreviewPanel(
            self, image_provider, dpi_var, jpeg_var, gray_var, on_apply
        )
        self.panel.pack(fill="both", expand=True, padx=8, pady=8)
        self.lbl_orig_info = self.panel.lbl_orig_info
        self.lbl_comp_info = self.panel.lbl_comp_info
        self.var_gray = self.panel.gray_var
        self._update = self.panel._update


class CompressionDialog(tk.Toplevel):
    """Выпадающее окно параметров сжатия."""

    def __init__(self, master, preset_var, dpi_var, jpeg_var, gray_var, on_apply):
        super().__init__(master)
        self.title("Параметры сжатия")
        self.geometry("420x320")
        self.transient(master)
        self.grab_set()
        self.configure(background=COLORS["surface"])
        self.on_apply = on_apply

        body = Card(self, pad=14)
        body.pack(fill="both", expand=True, padx=10, pady=10)
        inner = body.inner

        ttk.Label(inner, text="Пресет:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=5, pady=5
        )
        self.var_preset = tk.StringVar(value=preset_var.get())
        preset_combo = ttk.Combobox(
            inner, textvariable=self.var_preset, values=PRESETS, state="readonly", width=18
        )
        preset_combo.grid(row=0, column=1, sticky="w", padx=5, pady=5)

        ttk.Label(inner, text="DPI:", style="Card.TLabel").grid(
            row=1, column=0, sticky="w", padx=5, pady=5
        )
        self.var_dpi = tk.DoubleVar(value=dpi_var.get())
        ttk.Scale(inner, from_=30, to=300, variable=self.var_dpi, orient="horizontal").grid(
            row=1, column=1, sticky="we", padx=5, pady=5
        )
        self.dpi_val = ttk.Label(inner, text=str(int(round(self.var_dpi.get()))), width=5, style="Card.TLabel")
        self.dpi_val.grid(row=1, column=2, padx=2, pady=5)
        self.var_dpi.trace_add("write", lambda *_a: self.dpi_val.configure(
            text=str(int(round(self.var_dpi.get())))
        ))

        ttk.Label(inner, text="JPEG качество:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=5, pady=5
        )
        self.var_jpeg = tk.IntVar(value=jpeg_var.get())
        ttk.Scale(inner, from_=10, to=95, variable=self.var_jpeg, orient="horizontal").grid(
            row=2, column=1, sticky="we", padx=5, pady=5
        )
        self.jpeg_val = ttk.Label(inner, text=str(int(round(self.var_jpeg.get()))), width=5, style="Card.TLabel")
        self.jpeg_val.grid(row=2, column=2, padx=2, pady=5)
        self.var_jpeg.trace_add("write", lambda *_a: self.jpeg_val.configure(
            text=str(int(round(self.var_jpeg.get())))
        ))

        self.var_gray = tk.BooleanVar(value=bool(gray_var.get()))
        ttk.Checkbutton(
            inner, text="Ч/Б (grayscale)", variable=self.var_gray, style="Card.TCheckbutton"
        ).grid(row=3, column=0, columnspan=3, sticky="w", padx=5, pady=5)

        inner.columnconfigure(1, weight=1)

        frm_btns = tk.Frame(inner, bg=COLORS["surface_lowest"])
        frm_btns.grid(row=4, column=0, columnspan=3, sticky="e", pady=(10, 0))
        ttk.Button(frm_btns, text="Отмена", command=self.destroy).pack(side="right", padx=4)
        ttk.Button(frm_btns, text="Применить", command=self._apply, style="Accent.TButton").pack(side="right", padx=4)

        self.preset_var = preset_var
        self.dpi_var = dpi_var
        self.jpeg_var = jpeg_var
        self.gray_var = gray_var

    def _apply(self):
        self.preset_var.set(self.var_preset.get())
        self.dpi_var.set(int(round(self.var_dpi.get())))
        self.jpeg_var.set(int(round(self.var_jpeg.get())))
        self.gray_var.set(bool(self.var_gray.get()))
        if self.on_apply:
            self.on_apply()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
