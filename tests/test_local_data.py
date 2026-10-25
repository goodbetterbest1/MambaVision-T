"""Synthetic-only tests for source-image preparation and automatic local annotation files."""
from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo

from app.db import AnnotationDB
from tests_fixture import image_bytes
from tools.prepare_images import prepare_archive


class ImagePreparationTests(unittest.TestCase):
    def test_extract_strip_wrapper_preserve_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'Images.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('Images/batch_A/case01.png', image_bytes())
                package.writestr('Images/batch_B/case02.png', image_bytes())
                package.writestr('Images/metadata.json', '{}')
                package.writestr('__MACOSX/._case01.png', b'not an image')
            result = prepare_archive(archive, root / 'images')
            self.assertEqual(len(result), 2)
            self.assertEqual((root / 'images/batch_A/case01.png').read_bytes(), image_bytes())
            self.assertEqual((root / 'images/batch_B/case02.png').read_bytes(), image_bytes())
            self.assertFalse((root / 'images/metadata.json').exists())

    def test_archive_without_common_wrapper_is_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'flat.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('one.png', image_bytes())
                package.writestr('two.jpg', image_bytes())
            result = prepare_archive(archive, root / 'images')
            self.assertEqual({path.name for path in result}, {'one.png', 'two.jpg'})

    def test_repeated_extraction_never_overwrites(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'Images.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('Images/case.png', image_bytes())
            prepare_archive(archive, root / 'images')
            (root / 'images/case.png').write_bytes(b'existing original')
            with self.assertRaises(FileExistsError):
                prepare_archive(archive, root / 'images')
            self.assertEqual((root / 'images/case.png').read_bytes(), b'existing original')

    def test_traversal_symlink_and_duplicate_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for index, name in enumerate(('../escape.png', '/absolute.png', 'C:/outside.png', '..\\escape.png')):
                archive = root / f'unsafe{index}.zip'
                with ZipFile(archive, 'w') as package:
                    package.writestr(name, image_bytes())
                with self.assertRaises(ValueError):
                    prepare_archive(archive, root / f'out{index}')
            archive = root / 'symlink.zip'
            info = ZipInfo('Images/link.png')
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            with ZipFile(archive, 'w') as package:
                package.writestr(info, '../outside')
            with self.assertRaises(ValueError):
                prepare_archive(archive, root / 'outlink')
            archive = root / 'duplicate.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('Images/case.png', image_bytes())
                package.writestr('Images/CASE.png', image_bytes())
            with self.assertRaises(ValueError):
                prepare_archive(archive, root / 'outdup')

    def test_non_images_or_conflicts_fail_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive = root / 'only_json.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('annotation.json', '{}')
            with self.assertRaises(ValueError):
                prepare_archive(archive, root / 'empty')
            archive = root / 'Images.zip'
            with ZipFile(archive, 'w') as package:
                package.writestr('Images/new.png', image_bytes())
                package.writestr('Images/existing.png', image_bytes())
            output = root / 'images'
            output.mkdir()
            (output / 'existing.png').write_bytes(b'old')
            with self.assertRaises(FileExistsError):
                prepare_archive(archive, output)
            self.assertFalse((output / 'new.png').exists())


class LocalAnnotationFilesTests(unittest.TestCase):
    def test_save_writes_complete_json_and_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            database = Path(folder) / 'annotator_A.sqlite3'
            db = AnnotationDB(database)
            payload = {
                'image_id': 'sample01', 'filename': 'case01.png', 'width': 2, 'height': 1,
                'annotator_id': 'A', 'upper_crest_segments': [[[.1, .2], [.3, .4]]],
                'severity_points': [{'x': .3, 'y': .4, 'jaw': 'upper', 'severity': 'moderate'}],
            }
            first = db.save(payload)
            target = Path(folder) / 'annotator_A_json/sample01.json'
            self.assertEqual(json.loads(target.read_text()), first)
            second = db.save({**first, 'case_grade': 'moderate'})
            self.assertEqual(json.loads(target.read_text())['annotation_version'], 2)
            self.assertEqual(json.loads(target.read_text())['upper_crest_segments'], payload['upper_crest_segments'])
            self.assertEqual(len(list(target.parent.glob('*.json'))), 1)
            self.assertEqual(list(target.parent.glob('.save-*')), [])
            self.assertEqual(db.storage_info()['snapshot_warning'], None)
            db.close()
            db = AnnotationDB(database)
            self.assertEqual(db.get('sample01'), second)
            db.close()

    def test_snapshot_failure_does_not_lose_sqlite_record(self):
        with tempfile.TemporaryDirectory() as folder:
            db = AnnotationDB(Path(folder) / 'test.sqlite3')
            with patch.object(db, '_write_snapshot', side_effect=PermissionError('synthetic failure')):
                saved = db.save({'image_id': 'case', 'filename': 'case.png'})
            self.assertEqual(db.get('case'), saved)
            self.assertIsNotNone(db.storage_info()['snapshot_warning'])
            saved = db.save(saved)
            self.assertIsNone(db.storage_info()['snapshot_warning'])
            self.assertTrue((db.json_dir / 'case.json').exists())
            db.close()

    def test_unsafe_id_cannot_escape_json_directory_and_import_writes_mirror(self):
        with tempfile.TemporaryDirectory() as folder:
            db = AnnotationDB(Path(folder) / 'test.sqlite3')
            db.import_cases([{'image_id': '../escape', 'filename': 'case.png'}])
            files = list(db.json_dir.glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text())['image_id'], '../escape')
            self.assertFalse((Path(folder) / 'escape.json').exists())
            db.close()
