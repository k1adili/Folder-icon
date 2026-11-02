import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from app import _icon_filename, _resource_path, _updated_desktop_ini


class FolderIconHelpersTests(unittest.TestCase):
    def test_bundled_assets_are_available(self) -> None:
        self.assertTrue(_resource_path("assets/fonts/Vazirmatn-Regular.ttf").is_file())
        self.assertTrue(_resource_path("assets/fonts/Vazirmatn-Bold.ttf").is_file())
        self.assertTrue(_resource_path("assets/folder_icon.ico").is_file())

    def test_desktop_ini_adds_relative_icon_resource(self) -> None:
        updated = _updated_desktop_ini("", "folder_icon_123456789abc.ico")

        self.assertIn("[.ShellClassInfo]", updated)
        self.assertIn("IconResource=folder_icon_123456789abc.ico,0", updated)
        self.assertNotIn(":", updated)

    def test_desktop_ini_updates_existing_icon_and_preserves_other_settings(self) -> None:
        existing = (
            "[.ShellClassInfo]\r\n"
            "LocalizedResourceName=@shell32.dll,-21813\r\n"
            "IconFile=old.ico\r\n"
            "IconIndex=0\r\n"
            "IconResource=old.ico,0\r\n"
        )

        updated = _updated_desktop_ini(existing, "folder_icon_new.ico")

        self.assertIn("LocalizedResourceName=@shell32.dll,-21813", updated)
        self.assertIn("IconResource=folder_icon_new.ico,0", updated)
        self.assertNotIn("IconFile=", updated)
        self.assertNotIn("IconIndex=", updated)

    def test_desktop_ini_adds_section_without_replacing_existing_sections(self) -> None:
        existing = "[ViewState]\r\nMode=1\r\n"

        updated = _updated_desktop_ini(existing, "folder_icon.ico")

        self.assertTrue(updated.startswith("[ViewState]\r\nMode=1\r\n"))
        self.assertIn("[.ShellClassInfo]\r\n", updated)
        self.assertIn("IconResource=folder_icon.ico,0", updated)

    def test_icon_filename_is_stable_and_avoids_existing_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            folder = Path(temporary_directory)
            icon = folder / "source.ico"
            icon.write_bytes(b"\x00\x00\x01\x00test")

            name = _icon_filename(icon, folder)
            self.assertTrue(name.startswith("folder_icon_"))
            self.assertEqual(name, _icon_filename(icon, folder))

            collision = folder / name
            collision.write_bytes(b"different content")
            self.assertNotEqual(name, _icon_filename(icon, folder))


if __name__ == "__main__":
    unittest.main()
