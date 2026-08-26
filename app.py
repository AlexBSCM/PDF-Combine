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

_APPDATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "pdfconv")
_SETTINGS_PATH = os.path.join(_APPDATA_DIR, "settings.json")
_LOG_DIR = os.path.join(_APPDATA_DIR, "logs")

_DND_BASE = TkinterDnD.Tk if _DND_AVAILABLE else tk.Tk


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
        self.geometry("640x580")
        self._apply_window_icon()

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
        return {
            "out_dir": self.out_dir_var.get(),
            "preset": preset,
            "dpi": max(72, min(300, dpi)),
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

        frm_files = ttk.LabelFrame(self, text="Файлы")
        frm_files.pack(fill="both", expand=True, padx=10, pady=10)

        self.listbox = tk.Listbox(frm_files, selectmode=tk.EXTENDED)
        self.listbox.pack(fill="both", expand=True, side="left", padx=5, pady=5)

        btns = ttk.Frame(frm_files)
        btns.pack(side="right", fill="y", padx=5, pady=5)
        ttk.Button(btns, text="Добавить...", command=self.add_files).pack(fill="x", pady=2)
        ttk.Button(btns, text="Убрать выбранное", command=self.remove_selected).pack(fill="x", pady=2)
        ttk.Button(btns, text="Разделить PDF...", command=self.split_selected).pack(fill="x", pady=2)
        row_order = ttk.Frame(btns)
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
        ttk.Label(frm_files, text=hint, foreground="gray").pack(side="bottom")

        frm_out = ttk.LabelFrame(self, text="Папка вывода")
        frm_out.pack(fill="x", padx=10, pady=5)
        self.out_dir_var = tk.StringVar(value=out_dir_default)
        ttk.Entry(frm_out, textvariable=self.out_dir_var).pack(
            side="left", fill="x", expand=True, padx=5, pady=5
        )
        btns_out = ttk.Frame(frm_out)
        btns_out.pack(side="right", padx=5, pady=5)
        ttk.Button(btns_out, text="Обзор...", command=self.choose_out_dir).pack(side="left", padx=2)
        ttk.Button(btns_out, text="Открыть папку", command=self.open_out_dir).pack(side="left", padx=2)

        frm_quality = ttk.LabelFrame(self, text="Качество / размер")
        frm_quality.pack(fill="x", padx=10, pady=5)

        ttk.Label(frm_quality, text="Пресет:").grid(row=0, column=0, sticky="w", padx=5, pady=5)
        self.preset_var = tk.StringVar(value=saved_preset)
        preset_combo = ttk.Combobox(
            frm_quality, textvariable=self.preset_var, values=PRESETS, state="readonly"
        )
        preset_combo.grid(row=0, column=1, sticky="w", padx=5, pady=5)
        preset_combo.bind("<<ComboboxSelected>>", self._toggle_custom)

        ttk.Label(frm_quality, text="DPI (custom):").grid(row=0, column=2, sticky="w", padx=5, pady=5)
        dpi_saved = s.get("dpi", 150)
        try:
            dpi_saved = float(dpi_saved)
        except (TypeError, ValueError):
            dpi_saved = 150.0
        self.dpi_var = tk.DoubleVar(value=max(72, min(300, dpi_saved)))
        self.dpi_scale = ttk.Scale(
            frm_quality, from_=72, to=300, variable=self.dpi_var, orient="horizontal"
        )
        self.dpi_scale.grid(row=0, column=3, sticky="we", padx=5, pady=5)

        self.grayscale_var = tk.BooleanVar(value=bool(s.get("grayscale", False)))
        ttk.Checkbutton(frm_quality, text="Ч/Б (grayscale)", variable=self.grayscale_var).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=5, pady=5
        )

        self.merge_var = tk.BooleanVar(value=bool(s.get("merge", False)))
        ttk.Checkbutton(frm_quality, text="Объединить всё в один PDF", variable=self.merge_var).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=5, pady=5
        )

        frm_quality.columnconfigure(3, weight=1)

        gs_status = (
            f"Ghostscript: {self.gs_path}"
            if self.gs_path
            else "Ghostscript не найден — сжатие будет пропущено"
        )
        self.gs_label = ttk.Label(
            self, text=gs_status, foreground=("black" if self.gs_path else "red")
        )
        self.gs_label.pack(anchor="w", padx=12)

        self.convert_btn = ttk.Button(self, text="Конвертировать", command=self.start_convert)
        self.convert_btn.pack(pady=8)

        frm_progress = ttk.Frame(self)
        frm_progress.pack(fill="x", padx=10)
        self.progress = ttk.Progressbar(frm_progress, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_lbl = ttk.Label(frm_progress, text="", width=10, anchor="e")
        self.progress_lbl.pack(side="right", padx=(6, 0))

        self.log = tk.Text(self, height=9)
        self.log.pack(fill="both", expand=True, padx=10, pady=(6, 10))

    def _toggle_custom(self, _event=None):
        if self.preset_var.get() == "custom":
            self.dpi_scale.state(["!disabled"])
        else:
            self.dpi_scale.state(["disabled"])

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
        return added

    def remove_selected(self):
        for i in reversed(self.listbox.curselection()):
            del self.files[i]
            self.listbox.delete(i)

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


if __name__ == "__main__":
    App().mainloop()
