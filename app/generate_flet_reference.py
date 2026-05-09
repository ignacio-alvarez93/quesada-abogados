import flet as ft
import pydoc
from pathlib import Path


def write_help(file, title, obj):
    file.write(f"\n\n# {title}\n")
    file.write("=" * 80 + "\n")
    file.write(pydoc.render_doc(obj, renderer=pydoc.plaintext))


def main():
    output_path = Path("docs/technical/flet_084_raw.txt")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as f:
        f.write("FLET VERSION\n")
        f.write("=" * 80 + "\n")
        f.write(getattr(ft, "__version__", "unknown"))

        write_help(f, "FilePicker", ft.FilePicker)
        write_help(f, "Image", ft.Image)
        write_help(f, "Dropdown", ft.Dropdown)
        write_help(f, "TextField", ft.TextField)
        write_help(f, "Button", ft.Button)
        write_help(f, "AlertDialog", ft.AlertDialog)
        write_help(f, "Container", ft.Container)

    print(f"Referencia generada en: {output_path}")


if __name__ == "__main__":
    main()