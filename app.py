import ctypes
import hashlib
import os
import shutil
import sys
import tempfile
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable

FONT_FAMILY = "Vazirmatn"


def _resource_path(relative_path: str) -> Path:
    bundle_directory = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(bundle_directory) / relative_path


def _register_bundled_fonts() -> None:
    if os.name != "nt":
        raise OSError("فونت همراه برنامه فقط در ویندوز بارگذاری می‌شود.")

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    add_font = gdi32.AddFontResourceExW
    add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
    add_font.restype = ctypes.c_int

    for filename in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"):
        font_path = _resource_path(f"assets/fonts/{filename}")
        if not font_path.is_file():
            raise FileNotFoundError(f"فایل فونت همراه برنامه پیدا نشد: {font_path}")
        if not add_font(str(font_path), 0x10, None):  # FR_PRIVATE
            raise ctypes.WinError(ctypes.get_last_error())


def _icon_filename(icon_path: Path, folder_path: Path) -> str:
    digest = hashlib.sha256(icon_path.read_bytes()).hexdigest()[:12]
    stem = f"folder_icon_{digest}"
    candidate = folder_path / f"{stem}.ico"
    suffix = 1
    while candidate.exists() and candidate.resolve() != icon_path.resolve():
        if hashlib.sha256(candidate.read_bytes()).hexdigest()[:12] == digest:
            break
        candidate = folder_path / f"{stem}_{suffix}.ico"
        suffix += 1
    return candidate.name


def _read_desktop_ini(path: Path) -> tuple[str, str]:
    if not path.exists():
        return "", "cp1252"

    content = path.read_bytes()
    if content.startswith(b"\xff\xfe"):
        return content.decode("utf-16"), "utf-16"
    if content.startswith(b"\xfe\xff"):
        return content.decode("utf-16"), "utf-16"
    if content.startswith(b"\xef\xbb\xbf"):
        return content.decode("utf-8-sig"), "utf-8-sig"
    try:
        return content.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return content.decode("cp1252"), "cp1252"


def _updated_desktop_ini(content: str, icon_filename: str) -> str:
    newline = "\r\n" if "\r\n" in content else "\n"
    lines = content.splitlines()
    section_start = None
    section_end = len(lines)

    for index, line in enumerate(lines):
        if line.strip().lower() == "[.shellclassinfo]":
            section_start = index
            for next_index in range(index + 1, len(lines)):
                if lines[next_index].strip().startswith("["):
                    section_end = next_index
                    break
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(["[.ShellClassInfo]", f"IconResource={icon_filename},0"])
    else:
        section_lines = lines[section_start + 1 : section_end]
        updated_section = []
        icon_resource_written = False
        for line in section_lines:
            key = line.partition("=")[0].strip().lower()
            if key == "iconresource":
                if not icon_resource_written:
                    updated_section.append(f"IconResource={icon_filename},0")
                    icon_resource_written = True
            elif key not in {"iconfile", "iconindex"}:
                updated_section.append(line)
        if not icon_resource_written:
            updated_section.append(f"IconResource={icon_filename},0")
        lines[section_start + 1 : section_end] = updated_section

    return newline.join(lines).rstrip("\r\n") + newline


def _set_windows_attributes(path: Path, attributes_to_add: int) -> None:
    kernel32 = ctypes.windll.kernel32
    get_attributes = kernel32.GetFileAttributesW
    get_attributes.argtypes = [ctypes.c_wchar_p]
    get_attributes.restype = ctypes.c_uint32
    set_attributes = kernel32.SetFileAttributesW
    set_attributes.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    set_attributes.restype = ctypes.c_int

    current = get_attributes(str(path))
    invalid_attributes = 0xFFFFFFFF
    if current == invalid_attributes:
        raise ctypes.WinError()
    if not set_attributes(str(path), current | attributes_to_add):
        raise ctypes.WinError()


def apply_folder_icon(folder: Path, icon: Path) -> None:
    if os.name != "nt":
        raise OSError("تغییر آیکون پوشه فقط در ویندوز پشتیبانی می‌شود.")

    folder = folder.resolve(strict=True)
    icon = icon.resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("مسیر انتخاب‌شده پوشه نیست.")
    if not icon.is_file() or icon.suffix.lower() != ".ico":
        raise ValueError("لطفاً یک فایل آیکون با پسوند .ico انتخاب کنید.")
    if icon.read_bytes()[:4] != b"\x00\x00\x01\x00":
        raise ValueError("فایل انتخاب‌شده، یک فایل آیکون معتبر (.ico) نیست.")

    icon_name = _icon_filename(icon, folder)
    local_icon = folder / icon_name
    if icon != local_icon.resolve():
        shutil.copy2(icon, local_icon)
    _set_windows_attributes(local_icon, 0x02)  # hidden

    ini_path = folder / "desktop.ini"
    content, encoding = _read_desktop_ini(ini_path)
    updated_content = _updated_desktop_ini(content, icon_name)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding=encoding,
            newline="",
            dir=folder,
            prefix=".desktop_ini_",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated_content)
        os.replace(temporary_path, ini_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()

    _set_windows_attributes(ini_path, 0x02 | 0x04)  # hidden | system
    _set_windows_attributes(folder, 0x01)  # read-only marks it as customized

    shell32 = ctypes.windll.shell32
    shell32.SHChangeNotify.argtypes = [
        ctypes.c_long,
        ctypes.c_uint,
        ctypes.c_wchar_p,
        ctypes.c_wchar_p,
    ]
    shell32.SHChangeNotify.restype = None
    shell32.SHChangeNotify(0x00001000, 0x0005, str(folder), None)


class FolderIconApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("تغییر آیکون پوشه")
        root.resizable(False, False)
        root.configure(background="#F3F6FB")
        root.option_add("*Font", (FONT_FAMILY, 10))

        self.folder_var = tk.StringVar()
        self.icon_var = tk.StringVar()
        self.status_var = tk.StringVar(value="برای شروع، پوشه و فایل آیکون را انتخاب کنید")

        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(
            "Path.TEntry",
            font=(FONT_FAMILY, 10),
            foreground="#23324A",
            fieldbackground="#FFFFFF",
            bordercolor="#DCE4EF",
            lightcolor="#DCE4EF",
            darkcolor="#DCE4EF",
            padding=(10, 9),
        )
        style.map(
            "Path.TEntry",
            bordercolor=[("focus", "#3978E5")],
            lightcolor=[("focus", "#3978E5")],
            darkcolor=[("focus", "#3978E5")],
        )
        style.configure(
            "Browse.TButton",
            font=(FONT_FAMILY, 9, "bold"),
            foreground="#315FAF",
            background="#EEF4FF",
            borderwidth=0,
            padding=(14, 10),
        )
        style.map(
            "Browse.TButton",
            background=[("active", "#E1EBFF"), ("pressed", "#D5E3FF")],
        )
        style.configure(
            "Primary.TButton",
            font=(FONT_FAMILY, 10, "bold"),
            foreground="#FFFFFF",
            background="#326FE0",
            borderwidth=0,
            padding=(24, 12),
        )
        style.map(
            "Primary.TButton",
            background=[("active", "#255FC9"), ("pressed", "#1D50AE")],
        )
        style.configure(
            "Dialog.TButton",
            font=(FONT_FAMILY, 9, "bold"),
            foreground="#FFFFFF",
            background="#326FE0",
            borderwidth=0,
            padding=(22, 9),
        )
        style.map(
            "Dialog.TButton",
            background=[("active", "#255FC9"), ("pressed", "#1D50AE")],
        )

        root.iconbitmap(str(_resource_path("assets/folder_icon.ico")))
        page = tk.Frame(root, background="#F3F6FB")
        page.pack(fill="both", expand=True)

        header = tk.Frame(page, background="#172B4D", height=150)
        header.pack(fill="x")
        header.pack_propagate(False)
        header_content = tk.Frame(header, background="#172B4D")
        header_content.pack(fill="both", padx=42, pady=(29, 22))
        tk.Label(
            header_content,
            text="شخصی‌سازی پوشه‌ها",
            font=(FONT_FAMILY, 19, "bold"),
            foreground="#FFFFFF",
            background="#172B4D",
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            header_content,
            text="آیکون دلخواهت را انتخاب کن و به پوشه‌ات جلوه‌ای تازه بده",
            font=(FONT_FAMILY, 10),
            foreground="#C2D0E6",
            background="#172B4D",
            anchor="e",
        ).pack(fill="x", pady=(5, 0))

        card = tk.Frame(
            page,
            background="#FFFFFF",
            highlightbackground="#E2E8F0",
            highlightthickness=1,
        )
        card.pack(fill="x", padx=34, pady=(22, 14))
        content = tk.Frame(card, background="#FFFFFF")
        content.pack(fill="x", padx=24, pady=22)
        content.columnconfigure(0, weight=1)

        self._add_path_field(
            content,
            row=0,
            title="پوشه‌ای که می‌خواهی تغییر کند",
            hint="یک پوشه را در رایانه‌ات انتخاب کن",
            variable=self.folder_var,
            button_text="انتخاب پوشه",
            command=self._browse_folder,
        )
        self._add_path_field(
            content,
            row=1,
            title="فایل آیکون",
            hint="فقط فایل‌های با پسوند .ico پشتیبانی می‌شوند",
            variable=self.icon_var,
            button_text="انتخاب فایل",
            command=self._browse_icon,
        )

        note = tk.Frame(content, background="#F0F6FF")
        note.grid(row=2, column=0, sticky="ew", pady=(4, 18))
        tk.Label(
            note,
            text="نکته",
            font=(FONT_FAMILY, 9, "bold"),
            foreground="#315FAF",
            background="#F0F6FF",
            anchor="e",
        ).pack(fill="x", padx=13, pady=(10, 2))
        tk.Label(
            note,
            text="فایل آیکون مخفی می‌شود. برای حفظ آیکون، همه فایل‌های پوشه را هنگام ارسال نگه دار",
            font=(FONT_FAMILY, 9),
            foreground="#52647D",
            background="#F0F6FF",
            anchor="e",
            justify="right",
            wraplength=620,
        ).pack(fill="x", padx=13, pady=(0, 10))

        actions = tk.Frame(content, background="#FFFFFF")
        actions.grid(row=3, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(
            actions,
            text="اعمال آیکون",
            style="Primary.TButton",
            command=self._apply,
        ).grid(row=0, column=0, sticky="e")
        tk.Label(
            actions,
            textvariable=self.status_var,
            font=(FONT_FAMILY, 9),
            foreground="#718096",
            background="#FFFFFF",
            anchor="e",
            justify="right",
            wraplength=360,
        ).grid(row=0, column=1, padx=(14, 0), sticky="e")

        tk.Label(
            page,
            text="Developer: Keyvan Adili",
            font=(FONT_FAMILY, 8),
            foreground="#8A97A9",
            background="#F3F6FB",
        ).pack(pady=(0, 12))

        self._center_window(720, 570)

    def _add_path_field(
        self,
        parent: tk.Frame,
        row: int,
        title: str,
        hint: str,
        variable: tk.StringVar,
        button_text: str,
        command: Callable[[], None],
    ) -> None:
        field = tk.Frame(parent, background="#FFFFFF")
        field.grid(row=row, column=0, sticky="ew", pady=(0, 18))
        field.columnconfigure(0, weight=1)
        tk.Label(
            field,
            text=title,
            font=(FONT_FAMILY, 10, "bold"),
            foreground="#26364D",
            background="#FFFFFF",
            anchor="e",
        ).grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Label(
            field,
            text=hint,
            font=(FONT_FAMILY, 8),
            foreground="#8390A3",
            background="#FFFFFF",
            anchor="e",
        ).grid(row=1, column=0, columnspan=2, sticky="ew", pady=(3, 8))
        ttk.Button(
            field,
            text=button_text,
            style="Browse.TButton",
            command=command,
        ).grid(row=2, column=1, padx=(12, 0), sticky="e")
        ttk.Entry(
            field,
            textvariable=variable,
            style="Path.TEntry",
            justify="left",
        ).grid(row=2, column=0, sticky="ew")

    def _center_window(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        actual_width = min(max(width, self.root.winfo_reqwidth()), screen_width - 40)
        actual_height = min(max(height, self.root.winfo_reqheight()), screen_height - 80)
        x = (screen_width - actual_width) // 2
        y = (screen_height - actual_height) // 2
        self.root.geometry(f"{actual_width}x{actual_height}+{x}+{y}")

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(title="پوشه را انتخاب کنید")
        if selected:
            self.folder_var.set(selected)
            self.status_var.set("پوشه انتخاب شد؛ حالا فایل آیکون را انتخاب کن")

    def _browse_icon(self) -> None:
        selected = filedialog.askopenfilename(
            title="فایل آیکون را انتخاب کنید",
            filetypes=[("فایل آیکون", "*.ico")],
        )
        if selected:
            self.icon_var.set(selected)
            self.status_var.set("آماده اعمال آیکون جدید")

    def _show_notice(self, title: str, message: str) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.configure(background="#FFFFFF")
        dialog.iconbitmap(str(_resource_path("assets/folder_icon.ico")))

        body = tk.Frame(dialog, background="#FFFFFF", padx=24, pady=20)
        body.pack(fill="both", expand=True)
        tk.Label(
            body,
            text=title,
            font=(FONT_FAMILY, 12, "bold"),
            foreground="#26364D",
            background="#FFFFFF",
            anchor="e",
        ).pack(fill="x")
        tk.Label(
            body,
            text=message,
            font=(FONT_FAMILY, 9),
            foreground="#52647D",
            background="#FFFFFF",
            justify="right",
            anchor="e",
            wraplength=390,
        ).pack(fill="x", pady=(10, 18))
        ttk.Button(
            body,
            text="باشه",
            style="Dialog.TButton",
            command=dialog.destroy,
        ).pack(anchor="e")

        dialog.bind("<Return>", lambda _event: dialog.destroy())
        dialog.bind("<Escape>", lambda _event: dialog.destroy())
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (
            self.root.winfo_width() - dialog.winfo_width()
        ) // 2
        y = self.root.winfo_rooty() + (
            self.root.winfo_height() - dialog.winfo_height()
        ) // 2
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        self.root.wait_window(dialog)

    def _apply(self) -> None:
        folder_text = self.folder_var.get().strip()
        icon_text = self.icon_var.get().strip()
        if not folder_text or not icon_text:
            self.status_var.set("برای ادامه، هر دو مسیر را انتخاب کن")
            self._show_notice(
                "اطلاعات ناقص", "لطفاً پوشه و فایل آیکون را انتخاب کنید"
            )
            return

        try:
            apply_folder_icon(Path(folder_text), Path(icon_text))
        except (OSError, ValueError) as error:
            self.status_var.set("اعمال آیکون انجام نشد")
            self._show_notice("خطا", str(error))
            return

        self.status_var.set("آیکون پوشه با موفقیت تغییر کرد")
        self._show_notice(
            "انجام شد",
            "آیکون پوشه تغییر کرد. برای حفظ آن هنگام ارسال، پوشه را همراه "
            "با فایل‌های desktop.ini و آیکون داخل آن ارسال کنید",
        )


def main() -> None:
    _register_bundled_fonts()
    root = tk.Tk()
    FolderIconApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
