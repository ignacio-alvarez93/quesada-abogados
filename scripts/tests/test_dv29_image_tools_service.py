"""WO-DV29-01: JPG/JPEG/PNG engines and the viewer image-tools contract, from
Bandeja and Expedientes.

Synthetic images in a TemporaryDirectory only. The Bandeja registry is an
in-memory fake behind the real document-tools services; no database, no
network, no Box, no expediente folders other than the temporary one.
"""
import hashlib
import random
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import fitz
from PIL import Image

from backend.services import document_viewer_service as viewer_service
from backend.services.document_tools import document_inbox_tools_service as inbox_tools
from backend.services.document_tools import document_viewer_image_tools_service as tools
from backend.services.document_tools import image_tools_service as image_tools
from backend.services.document_tools import safe_file_service


RED, BLUE, CLEAR, OPAQUE = (255, 0, 0), (0, 0, 255), (0, 0, 0, 0), (0, 128, 255, 255)
ORIENTATION = 0x0112

PARAMS = {
    "crop": {"left": "0", "top": "0", "right": "10", "bottom": "10"},
    "rotate": {"degrees": "90"},
    "resize": {"width": "32"},
    "optimize": {"quality": "40"},
    "convert": {"target_format": "png"},
    "to_pdf": {},
}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def noise(size, seed=1):
    w, h = size
    return Image.frombytes("RGB", size, random.Random(seed).randbytes(w * h * 3))


def halves(size, left, right, mode="RGB"):
    w, h = size
    img = Image.new(mode, size, left)
    img.paste(right, (w // 2, 0, w, h))
    return img


def save_jpeg(img, path, orientation=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"quality": 95}
    if orientation:
        exif = Image.Exif()
        exif[ORIENTATION] = orientation
        kwargs["exif"] = exif.tobytes()
    img.save(path, "JPEG", **kwargs)
    return path


def save_png(img, path, **kwargs):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", **(kwargs or {"compress_level": 0}))
    return path


def close_to(pixel, color, tolerance=40):
    return all(abs(a - b) <= tolerance for a, b in zip(pixel, color))


class FakeInbox:
    """In-memory Bandeja registry behind the real document-tools services."""

    def __init__(self):
        self.items = {}
        self.registered = []
        self.next_id = 100

    def get(self, item_id):
        item = self.items.get(int(item_id))
        if not item:
            raise ValueError("No existe el documento de bandeja indicado.")
        return dict(item)

    def register(self, file_path, source_type, source_label, notes, client_id, expedient_id, metadata_json):
        item = {"id": self.next_id, "stored_path": str(file_path), "original_filename": Path(file_path).name,
                "source_type": source_type, "source_label": source_label, "notes": notes,
                "client_id": client_id, "expedient_id": expedient_id, "metadata_json": metadata_json}
        self.next_id += 1
        self.registered.append(item)
        return dict(item)


class Dv29ImageToolsBase(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.tools_root = self.tmp / "tools"

        # Expediente folder (temporary), with valid and invalid images.
        self.exp_root = self.tmp / "expediente_42"
        self.exp_jpg = save_jpeg(noise((64, 48)), self.exp_root / "fotos" / "foto.jpg")
        self.exp_jpeg = save_jpeg(noise((64, 48), 2), self.exp_root / "scan.jpeg")
        self.exp_png = save_png(halves((40, 20), CLEAR, OPAQUE, "RGBA"), self.exp_root / "plano.png")
        self.exp_rotated = save_jpeg(halves((40, 20), RED, BLUE), self.exp_root / "girada.jpg", orientation=6)
        bad = self.exp_root / "malos"
        bad.mkdir()
        Image.new("RGB", (8, 8), RED).save(bad / "nota.gif", "GIF")
        Image.new("RGB", (8, 8), RED).save(bad / "imagen.bmp", "BMP")
        save_png(Image.new("RGB", (8, 8), RED), bad / "falso.jpg")
        (bad / "roto.png").write_bytes(b"esto no es una imagen")
        (bad / "truncado.jpg").write_bytes(self.exp_jpg.read_bytes()[: self.exp_jpg.stat().st_size // 2])
        (bad / "vacio.png").write_bytes(b"")
        frames = [Image.new("RGB", (8, 8), color) for color in (RED, BLUE)]
        frames[0].save(bad / "animada.png", "PNG", save_all=True, append_images=frames[1:])
        self.bad = bad
        self.foreign = save_jpeg(noise((16, 16)), self.tmp / "ajeno" / "ajeno.jpg")

        # Bandeja originals.
        self.inbox = FakeInbox()
        self.inbox_jpg = save_jpeg(noise((64, 48), 3), self.tmp / "inbox" / "a.jpg")
        self.inbox_jpeg = save_jpeg(noise((64, 48), 4), self.tmp / "inbox" / "b.jpeg")
        self.inbox_png = save_png(halves((40, 20), CLEAR, OPAQUE, "RGBA"), self.tmp / "inbox" / "c.png")
        self.inbox_rotated = save_jpeg(halves((40, 20), RED, BLUE), self.tmp / "inbox" / "girada.jpg",
                                       orientation=6)
        link = {"client_id": 7, "expedient_id": 42, "status": "pending"}
        self.inbox.items = {
            1: {"id": 1, "stored_path": str(self.inbox_jpg), "original_filename": "a.jpg", **link},
            2: {"id": 2, "stored_path": str(self.inbox_jpeg), "original_filename": "b.jpeg", **link},
            3: {"id": 3, "stored_path": str(self.inbox_png), "original_filename": "c.png", **link},
            5: {"id": 5, "stored_path": str(self.inbox_rotated), "original_filename": "girada.jpg", **link},
        }

        self.protected = [p for p in self.tmp.rglob("*") if p.is_file()]
        self.hashes = {path: sha256(path) for path in self.protected}
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))

        for target, attribute, value in (
            (safe_file_service, "DOCUMENT_TOOLS_ROOT", self.tools_root),
            (viewer_service, "get_expediente_document_root", Mock(side_effect=self.expediente_root)),
            (inbox_tools, "get_inbox_item", self.inbox.get),
            (inbox_tools, "import_file_to_inbox", self.inbox.register),
        ):
            patcher = patch.object(target, attribute, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def expediente_root(self, expediente_id):
        if int(expediente_id) != 42:
            return {"exists": False, "root_path": "", "message": "El expediente no tiene carpeta vinculada."}
        return {"exists": True, "root_path": str(self.exp_root), "expediente_id": 42}

    def tearDown(self):
        # Originals are byte-identical and nothing was written into the expediente folder.
        for path, digest in self.hashes.items():
            self.assertEqual(sha256(path), digest, path)
        self.assertEqual(sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*")),
                         self.exp_listing)
        # Working copies never outlive the operation.
        self.assertEqual(list((self.tools_root / "temp").glob("*")), [])

    # ------------------------------------------------------------------ helpers

    def scope(self, context, kind="jpg"):
        if context == "inbox":
            item_id = {"jpg": 1, "jpeg": 2, "png": 3, "rotated": 5}[kind]
            return tools.inbox_image_scope(item_id, self.inbox.items[item_id]["stored_path"])
        path = {"jpg": self.exp_jpg, "jpeg": self.exp_jpeg, "png": self.exp_png, "rotated": self.exp_rotated}[kind]
        return tools.expedient_image_scope(42, path)

    def output(self, outcome):
        self.assertEqual(len(outcome["outputs"]), 1)
        output = Path(outcome["outputs"][0])
        self.assertTrue(output.is_file())
        self.assertNotEqual(output.resolve(), Path(outcome["source_path"]).resolve())
        self.assertTrue(output.resolve().is_relative_to(self.tools_root.resolve()), output)
        return output

    def check_registration(self, outcome, context, operation):
        (item,) = outcome["generated_items"]
        metadata = item["metadata_json"]
        self.assertEqual(item["source_type"], "generated")
        self.assertEqual(item["expedient_id"], 42)
        self.assertEqual(metadata["operation"], tools.REGISTRY_OPERATIONS[operation])
        self.assertEqual([str(Path(p).resolve()) for p in metadata["source_paths"]],
                         [str(Path(outcome["source_path"]).resolve())])
        if context == "inbox":
            self.assertEqual(item["client_id"], 7)
            self.assertEqual(len(metadata["source_item_ids"]), 1)
        else:
            self.assertEqual(metadata["source_item_ids"], [])
            provenance = metadata["provenance"]
            self.assertEqual(provenance["source_context"], "expedient")
            self.assertEqual(provenance["expediente_id"], 42)
            self.assertEqual(provenance["source_sha256"], outcome["source_sha256"])
            self.assertEqual(provenance["source_relative_path"],
                             str(Path(outcome["source_path"]).resolve().relative_to(self.exp_root.resolve())))

    def images_written(self):
        return [p for p in self.tools_root.rglob("*") if p.is_file()] if self.tools_root.exists() else []


class SixToolsTests(Dv29ImageToolsBase):
    def test_six_tools_in_both_contexts_create_registered_copies(self):
        for context in ("inbox", "expedient"):
            for operation in tools.OPERATIONS:
                with self.subTest(context=context, operation=operation):
                    scope = self.scope(context)
                    outcome = tools.run_image_tool(scope, operation, PARAMS[operation])
                    self.assertTrue(outcome["ok"])
                    self.assertEqual(outcome["scope"], context)
                    self.assertEqual(outcome["source_sha256"], scope.sha256)
                    output = self.output(outcome)
                    self.check_registration(outcome, context, operation)
                    if operation == "to_pdf":
                        self.assertTrue(output.read_bytes().startswith(b"%PDF"))
                        self.assertEqual(output.suffix, ".pdf")
                        continue
                    with Image.open(output) as img:
                        expected = {
                            "crop": ((10, 10), "JPEG"),
                            "rotate": ((48, 64), "JPEG"),
                            "resize": ((32, 24), "JPEG"),
                            "optimize": ((64, 48), "JPEG"),
                            "convert": ((64, 48), "PNG"),
                        }[operation]
                        self.assertEqual((img.size, img.format), expected)
                    if operation == "optimize":
                        self.assertLess(output.stat().st_size, Path(scope.source_path).stat().st_size)
        self.assertEqual(len(self.inbox.registered), 2 * len(tools.OPERATIONS))

    def test_jpeg_extension_is_kept_and_png_keeps_alpha(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context, kind="jpeg"):
                outcome = tools.run_image_tool(self.scope(context, "jpeg"), "rotate", {"degrees": "180"})
                self.assertEqual(self.output(outcome).suffix, ".jpeg")
            with self.subTest(context=context, kind="png"):
                scope = self.scope(context, "png")
                self.assertTrue(scope.has_alpha)
                self.assertEqual((scope.format, scope.width, scope.height), ("PNG", 40, 20))
                output = self.output(tools.run_image_tool(scope, "rotate", {"degrees": "90"}))
                with Image.open(output) as img:
                    self.assertEqual((img.format, img.mode, img.size), ("PNG", "RGBA", (20, 40)))
                    self.assertEqual(img.getpixel((10, 5)), CLEAR)  # left (clear) half is now on top
                    self.assertEqual(img.getpixel((10, 35)), OPAQUE)
                output = self.output(tools.run_image_tool(scope, "resize", {"height": "10"}))
                with Image.open(output) as img:
                    self.assertEqual((img.mode, img.size), ("RGBA", (20, 10)))
                    self.assertEqual(img.getpixel((1, 5))[3], 0)

    def test_png_optimization_is_lossless(self):
        scope = self.scope("expedient", "png")
        outcome = tools.run_image_tool(scope, "optimize", {})
        output = self.output(outcome)
        self.assertLess(output.stat().st_size, self.exp_png.stat().st_size)
        with Image.open(output) as out, Image.open(self.exp_png) as src:
            self.assertEqual(out.mode, src.mode)
            self.assertEqual(list(out.getdata()), list(src.getdata()))
        metadata = outcome["generated_items"][0]["metadata_json"]["tool_result"]["metadata"]
        self.assertTrue(metadata["lossless"])

    def test_png_to_jpg_flattens_alpha_on_white_and_jpg_to_png_is_lossless(self):
        outcome = tools.run_image_tool(self.scope("inbox", "png"), "convert", {"target_format": "jpg"})
        output = self.output(outcome)
        self.assertEqual(output.suffix, ".jpg")
        with Image.open(output) as img:
            self.assertEqual((img.format, img.mode), ("JPEG", "RGB"))
            self.assertTrue(close_to(img.getpixel((3, 10)), (255, 255, 255), 10), img.getpixel((3, 10)))
            self.assertTrue(close_to(img.getpixel((35, 10)), OPAQUE[:3]), img.getpixel((35, 10)))
        metadata = outcome["generated_items"][0]["metadata_json"]["tool_result"]["metadata"]
        self.assertTrue(metadata["alpha_flattened"])
        self.assertEqual(metadata["background"], "#FFFFFF")

        output = self.output(tools.run_image_tool(self.scope("expedient"), "convert", {"target_format": "PNG"}))
        with Image.open(output) as out, Image.open(self.exp_jpg) as src:
            self.assertEqual(out.format, "PNG")
            self.assertEqual(list(out.convert("RGB").getdata()), list(src.convert("RGB").getdata()))

    def test_png_to_pdf_flattens_alpha_on_white(self):
        outcome = tools.run_image_tool(self.scope("expedient", "png"), "to_pdf", {})
        with fitz.open(self.output(outcome)) as doc:
            self.assertEqual(doc.page_count, 1)
            pix = doc[0].get_pixmap(matrix=fitz.Matrix(2, 2))
            self.assertTrue(close_to(pix.pixel(4, pix.height // 2), (255, 255, 255), 10))
            self.assertTrue(close_to(pix.pixel(pix.width - 4, pix.height // 2), OPAQUE[:3]))
        metadata = outcome["generated_items"][0]["metadata_json"]["tool_result"]["metadata"]
        self.assertTrue(metadata["alpha_flattened"])

    def test_exif_orientation_is_applied_coherently(self):
        # Stored 40x20 (left red, right blue) with orientation 6: shown 20x40, red on top.
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                scope = self.scope(context, "rotated")
                self.assertEqual((scope.width, scope.height, scope.exif_orientation), (20, 40, 6))

                output = self.output(tools.run_image_tool(scope, "convert", {"target_format": "png"}))
                with Image.open(output) as img:
                    self.assertEqual(img.size, (20, 40))
                    self.assertTrue(close_to(img.getpixel((10, 5)), RED))
                    self.assertTrue(close_to(img.getpixel((10, 35)), BLUE))

                outcome = tools.run_image_tool(scope, "crop", {"left": 0, "top": 0, "right": 20, "bottom": 20})
                with Image.open(self.output(outcome)) as img:
                    self.assertEqual(img.size, (20, 20))
                    self.assertTrue(close_to(img.getpixel((10, 10)), RED))
                    self.assertIn(img.getexif().get(ORIENTATION), (None, 1))
                self.check_registration(outcome, context, "crop")
                tool_metadata = outcome["generated_items"][0]["metadata_json"]["tool_result"]["metadata"]
                self.assertTrue(tool_metadata["exif_orientation_applied"])

                with Image.open(self.output(tools.run_image_tool(scope, "rotate", {"degrees": 90}))) as img:
                    self.assertEqual(img.size, (40, 20))
                    self.assertTrue(close_to(img.getpixel((5, 10)), BLUE))
                    self.assertTrue(close_to(img.getpixel((35, 10)), RED))
                    self.assertIn(img.getexif().get(ORIENTATION), (None, 1))

                with Image.open(self.output(tools.run_image_tool(scope, "resize", {"height": 20}))) as img:
                    self.assertEqual(img.size, (10, 20))

                with fitz.open(self.output(tools.run_image_tool(scope, "to_pdf", {}))) as doc:
                    self.assertLess(doc[0].rect.width, doc[0].rect.height)

    def test_repeated_runs_never_collide(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                scope = self.scope(context)
                first = tools.run_image_tool(scope, "rotate", {"degrees": "90"})
                second = tools.run_image_tool(scope, "rotate", {"degrees": "90"})
                self.assertNotEqual(first["outputs"], second["outputs"])
                self.assertTrue(all(Path(p).is_file() for p in first["outputs"] + second["outputs"]))
                self.assertNotEqual(first["generated_items"][0]["id"], second["generated_items"][0]["id"])
                rotated = self.scope(context, "rotated")
                crops = [tools.run_image_tool(rotated, "crop", PARAMS["crop"])["outputs"][0] for _ in range(2)]
                self.assertNotEqual(crops[0], crops[1])
        self.assertEqual(len(self.inbox.registered), 8)


class ValidationTests(Dv29ImageToolsBase):
    def test_invalid_parameters_are_reported_without_outputs(self):
        cases = [
            ("jpg", "rotate", {"degrees": "45"}, "90, 180 o 270"),
            ("jpg", "rotate", {"degrees": "x"}, "número entero"),
            ("jpg", "rotate", {}, "número entero"),
            ("jpg", "resize", {}, "ancho, el alto"),
            ("jpg", "resize", {"width": "0"}, "fuera de límites"),
            ("jpg", "resize", {"width": "-5"}, "fuera de límites"),
            ("jpg", "resize", {"width": "99999"}, "fuera de límites"),
            ("jpg", "resize", {"width": "12000"}, "demasiado grande"),
            ("jpg", "resize", {"width": "1.5"}, "número entero"),
            ("jpg", "resize", {"width": "64"}, "ya tiene ese tamaño"),
            ("jpg", "optimize", {"quality": "5"}, "Calidad fuera"),
            ("jpg", "optimize", {"quality": "99"}, "Calidad fuera"),
            ("png", "optimize", {"quality": "80"}, "sin pérdida"),
            ("jpg", "convert", {"target_format": "gif"}, "destino no válido"),
            ("jpg", "convert", {}, "destino no válido"),
            ("jpg", "convert", {"target_format": "jpeg"}, "ya está"),
            ("png", "convert", {"target_format": "png"}, "ya está"),
            ("jpg", "crop", {"left": 0, "top": 0, "right": 999, "bottom": 10}, "fuera de límites"),
            ("jpg", "crop", {"left": 10, "top": 0, "right": 5, "bottom": 10}, "inválidas"),
            ("jpg", "crop", {"left": "a", "top": 0, "right": 5, "bottom": 10}, "número entero"),
            ("rotated", "crop", {"left": 0, "top": 0, "right": 40, "bottom": 20}, "fuera de límites"),
        ]
        for context in ("inbox", "expedient"):
            for kind, operation, params, message in cases:
                with self.subTest(context=context, operation=operation, params=params):
                    with self.assertRaisesRegex(ValueError, message):
                        tools.run_image_tool(self.scope(context, kind), operation, params)
        with self.assertRaisesRegex(ValueError, "no soportada"):
            tools.run_image_tool(self.scope("expedient"), "delete", {})
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(self.images_written(), [])

    def test_optimization_without_reduction_is_a_visible_error(self):
        tight = save_png(Image.new("RGB", (8, 8), RED), self.exp_root / "compacta.png", optimize=True)
        self.hashes[tight] = sha256(tight)
        self.exp_listing = sorted(p.relative_to(self.exp_root) for p in self.exp_root.rglob("*"))
        with self.assertRaisesRegex(ValueError, "no reduce"):
            tools.run_image_tool(tools.expedient_image_scope(42, tight), "optimize", {})
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(self.images_written(), [])

    def test_unsupported_corrupt_or_oversized_files_are_refused(self):
        cases = [
            ("nota.gif", "solo están disponibles"),
            ("imagen.bmp", "solo están disponibles"),
            ("falso.jpg", "no coincide con la extensión"),
            ("roto.png", "dañada"),
            ("truncado.jpg", "dañada"),
            ("vacio.png", "vacío"),
            ("animada.png", "animada"),
            ("falta.png", "no existe"),
        ]
        for name, message in cases:
            with self.subTest(name=name):
                with self.assertRaisesRegex(tools.ToolScopeError, message):
                    tools.expedient_image_scope(42, self.bad / name)
        with patch.object(image_tools, "MAX_EDITABLE_IMAGE_BYTES", 100):
            with self.assertRaisesRegex(tools.ToolScopeError, "demasiado pesada"):
                tools.expedient_image_scope(42, self.exp_jpg)
        with patch.object(image_tools, "MAX_EDITABLE_IMAGE_PIXELS", 100):
            with self.assertRaisesRegex(tools.ToolScopeError, "demasiado grande"):
                tools.expedient_image_scope(42, self.exp_jpg)
        # The engines refuse the same files on their own.
        for name in ("nota.gif", "falso.jpg", "roto.png"):
            with self.subTest(engine=name):
                result = image_tools.rotate_image(self.bad / name, degrees=90)
                self.assertFalse(result.ok)
                self.assertIsNone(result.output_path)
        self.assertEqual(self.images_written(), [])

    def test_expedient_scope_rejects_paths_outside_the_folder(self):
        for path in (self.foreign, self.exp_root / ".." / "ajeno" / "ajeno.jpg"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(tools.ToolScopeError, "no pertenece"):
                    tools.expedient_image_scope(42, path)
        with self.assertRaisesRegex(tools.ToolScopeError, "carpeta vinculada"):
            tools.expedient_image_scope(7, self.exp_jpg)
        with self.assertRaisesRegex(tools.ToolScopeError, "expediente guardado"):
            tools.expedient_image_scope(None, self.exp_jpg)

    def test_inbox_scope_requires_registered_matching_processable_item(self):
        with self.assertRaisesRegex(tools.ToolScopeError, "no está registrado"):
            tools.inbox_image_scope(55)
        with self.assertRaisesRegex(tools.ToolScopeError, "ya no coincide"):
            tools.inbox_image_scope(1, self.inbox_jpeg)
        for status in ("discarded", "duplicate", "error"):
            with self.subTest(status=status):
                self.inbox.items[1]["status"] = status
                with self.assertRaisesRegex(tools.ToolScopeError, f"estado '{status}'"):
                    tools.inbox_image_scope(1)
        self.inbox.items[1]["status"] = "linked"
        self.inbox.items[1]["sha256"] = "0" * 64
        with self.assertRaisesRegex(tools.ToolScopeError, "SHA-256"):
            tools.inbox_image_scope(1)
        self.inbox.items[1]["sha256"] = self.hashes[self.inbox_jpg].upper()
        self.assertEqual(tools.inbox_image_scope(1).sha256, self.hashes[self.inbox_jpg])

    def test_changed_or_reassigned_source_is_refused(self):
        scope = self.scope("inbox")
        save_jpeg(noise((64, 48), 9), self.inbox_jpg)
        self.hashes[self.inbox_jpg] = sha256(self.inbox_jpg)
        with self.assertRaisesRegex(ValueError, "ha cambiado"):
            tools.run_image_tool(scope, "rotate", {"degrees": "90"})
        scope = self.scope("inbox")
        self.inbox.items[1]["stored_path"] = str(self.inbox_jpeg)
        with self.assertRaisesRegex(ValueError, "ya no coincide"):
            tools.run_image_tool(scope, "rotate", {"degrees": "90"})
        scope = self.scope("expedient")
        save_jpeg(noise((64, 48), 9), self.exp_jpg)
        self.hashes[self.exp_jpg] = sha256(self.exp_jpg)
        with self.assertRaisesRegex(ValueError, "ha cambiado"):
            tools.run_image_tool(scope, "convert", {"target_format": "png"})
        self.assertEqual(self.inbox.registered, [])
        self.assertEqual(self.images_written(), [])


class SafetyTests(Dv29ImageToolsBase):
    def test_existing_files_are_never_overwritten(self):
        scope = self.scope("expedient")
        for target in (self.exp_jpg, self.exp_jpeg):
            for operation, params in (("rotate", {"degrees": 90}), ("resize", {"width": 10}),
                                      ("optimize", {}), ("convert", {"target_format": "png"})):
                with self.subTest(target=target.name, operation=operation):
                    with patch.object(image_tools, "build_output_path", return_value=target):
                        with self.assertRaisesRegex(ValueError, "no se sobrescribe"):
                            tools.run_image_tool(scope, operation, params)
        self.assertEqual(self.inbox.registered, [])

    def test_exclusive_write_refuses_an_existing_path(self):
        with Image.open(self.exp_png) as img:
            with self.assertRaises(FileExistsError):
                image_tools._write_exclusive(img, self.exp_jpeg, "PNG")

    def test_registration_failure_is_visible_and_keeps_the_derivative(self):
        for context in ("inbox", "expedient"):
            with self.subTest(context=context):
                scope = self.scope(context)
                with patch.object(inbox_tools, "import_file_to_inbox", side_effect=OSError("disco lleno")):
                    with self.assertRaises(tools.ImageToolRegistrationError) as caught:
                        tools.run_image_tool(scope, "rotate", {"degrees": "270"})
                message = str(caught.exception)
                self.assertIn("disco lleno", message)
                self.assertIn("pendiente de revisión", message)
                (pending,) = caught.exception.output_paths
                self.assertIn(pending, message)
                self.assertTrue(Path(pending).is_file())
                self.assertTrue(Path(pending).resolve().is_relative_to(self.tools_root.resolve()))
        self.assertEqual(self.inbox.registered, [])

    def test_engine_failure_surfaces_and_removes_the_working_copy(self):
        scope = self.scope("expedient", "rotated")
        with patch.object(image_tools, "crop_image", side_effect=RuntimeError("motor caído")):
            with self.assertRaisesRegex(RuntimeError, "motor caído"):
                tools.run_image_tool(scope, "crop", PARAMS["crop"])
        with patch.object(image_tools, "image_to_pdf", return_value=image_tools.DocumentToolResult.failure(
                operation="image_to_pdf", errors=["sin PDF"])):
            with self.assertRaisesRegex(ValueError, "sin PDF"):
                tools.run_image_tool(scope, "to_pdf", {})
        self.assertEqual(self.inbox.registered, [])

    def test_partial_crop_or_pdf_write_leaves_no_derivative(self):
        # WO-04: crop and image->PDF reuse the older engines; a failed write must
        # not leave a half-written file in storage/document_tools.
        def broken_save(img, fp, *args, **kwargs):
            Path(fp).write_bytes(b"parcial")
            raise OSError("disco lleno")

        for context in ("inbox", "expedient"):
            for operation in ("crop", "to_pdf"):
                with self.subTest(context=context, operation=operation):
                    scope = self.scope(context)
                    with patch.object(Image.Image, "save", broken_save):
                        with self.assertRaisesRegex(ValueError, "disco lleno"):
                            tools.run_image_tool(scope, operation, PARAMS[operation])
                    self.assertEqual(self.images_written(), [])
        self.assertEqual(self.inbox.registered, [])

    def test_availability_enables_the_six_tools(self):
        self.assertEqual(tools.availability(self.scope("expedient", "png")),
                         {operation: None for operation in tools.OPERATIONS})


if __name__ == "__main__":
    unittest.main()
