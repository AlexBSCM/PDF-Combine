"""Raw-конвертация doc/docx/rtf/xls/xlsx/ppt/pptx в PDF через COM MS Office.

Работает только на Windows с установленным MS Office.
"""
import os

try:
    import pythoncom
    import win32com.client as win32
except ImportError:
    pythoncom = None
    win32 = None

WD_FORMAT_PDF = 17
XL_TYPE_PDF = 0
PP_SAVE_AS_PDF = 32

_WORD_EXTS = {".docx", ".doc", ".rtf"}
_EXCEL_EXTS = {".xlsx", ".xls"}
_PPT_EXTS = {".pptx", ".ppt"}


class OfficeSession:
    """Сессия COM: лениво запускает Word/Excel/PowerPoint и переиспользует их.

    Приложения стартуют один раз при первой конвертации соответствующего
    формата и закрываются все разом в close() / при выходе из with-блока.
    """

    def __init__(self):
        self._apps: dict[str, object] = {}

    def __enter__(self):
        if pythoncom is not None:
            pythoncom.CoInitialize()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        if pythoncom is not None:
            pythoncom.CoUninitialize()

    def convert(self, input_path: str, output_path: str) -> None:
        ext = os.path.splitext(input_path)[1].lower()
        if ext in _WORD_EXTS:
            self._word_to_pdf(input_path, output_path)
        elif ext in _EXCEL_EXTS:
            self._excel_to_pdf(input_path, output_path)
        elif ext in _PPT_EXTS:
            self._ppt_to_pdf(input_path, output_path)
        else:
            raise ValueError(f"Формат не поддерживается: {ext}")

    def close(self):
        for app in self._apps.values():
            try:
                app.Quit()
            except Exception:
                pass
        self._apps.clear()

    def _require_com(self):
        if win32 is None or pythoncom is None:
            raise RuntimeError("pywin32 не установлен — конвертация Office недоступна")

    def _app(self, prog_id: str):
        self._require_com()
        if prog_id not in self._apps:
            app = win32.Dispatch(prog_id)
            try:
                if prog_id == "Word.Application":
                    app.DisplayAlerts = 0
                elif prog_id == "Excel.Application":
                    app.DisplayAlerts = False
                elif prog_id == "PowerPoint.Application":
                    app.DisplayAlerts = 1
            except Exception:
                pass
            if prog_id != "PowerPoint.Application":
                app.Visible = False
            self._apps[prog_id] = app
        return self._apps[prog_id]

    def _word_to_pdf(self, input_path: str, output_path: str) -> None:
        word = self._app("Word.Application")
        doc = word.Documents.Open(
            os.path.abspath(input_path), ConfirmConversions=False, ReadOnly=True
        )
        try:
            doc.SaveAs(os.path.abspath(output_path), FileFormat=WD_FORMAT_PDF)
        finally:
            doc.Close(False)

    def _excel_to_pdf(self, input_path: str, output_path: str) -> None:
        excel = self._app("Excel.Application")
        wb = excel.Workbooks.Open(os.path.abspath(input_path), ReadOnly=True)
        try:
            wb.ExportAsFixedFormat(XL_TYPE_PDF, os.path.abspath(output_path))
        finally:
            wb.Close(False)

    def _ppt_to_pdf(self, input_path: str, output_path: str) -> None:
        powerpoint = self._app("PowerPoint.Application")
        pres = powerpoint.Presentations.Open(
            os.path.abspath(input_path), ReadOnly=True, WithWindow=False
        )
        try:
            pres.SaveAs(os.path.abspath(output_path), PP_SAVE_AS_PDF)
        finally:
            pres.Close()
