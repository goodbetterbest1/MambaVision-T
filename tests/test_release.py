"""Regression tests for release safety and multi-annotator data preservation."""
import concurrent.futures
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from app.db import AnnotationDB
from app.import_export import parse_import
from app.schema import validate_case_payload
from app.server import AppState, make_server
from tests_fixture import image_bytes
from tools.merge_annotations import make_consensus, majority


class ReleaseTests(unittest.TestCase):
    def test_concurrent_versions_are_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            db = AnnotationDB(Path(directory) / 'test.sqlite3')
            case = {'image_id':'same','filename':'same.png','width':2,'height':1}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                versions = list(pool.map(lambda _: db.save(case)['annotation_version'], range(20)))
            self.assertEqual(sorted(versions), list(range(1,21)))
            db.close()

    def test_keep_local_and_prevalidate_import(self):
        with tempfile.TemporaryDirectory() as directory:
            db=AnnotationDB(Path(directory)/'test.sqlite3')
            case={'image_id':'same','filename':'same.png','severity_points':[{'x':.2,'y':.3,'jaw':'upper','severity':'mild'}]}
            db.save(case)
            self.assertEqual(db.import_cases([{**case,'case_grade':'severe'}],'keep_local')['skipped'],1)
            self.assertEqual(db.get('same')['case_grade'],'mild')
            with self.assertRaises(ValueError):
                db.import_cases([{'image_id':'new','filename':'new.png'},{'image_id':'bad','filename':'bad.png','case_grade':'typo'}])
            self.assertIsNone(db.get('new'))
            db.close()

    def test_legacy_geometry_read_without_erasure(self):
        with tempfile.TemporaryDirectory() as directory:
            db=AnnotationDB(Path(directory)/'test.sqlite3')
            case=db.save({'image_id':'legacy','filename':'legacy.png'})
            case['upper_crest']=[[.1,.2],[.7,.3]]
            case.pop('upper_crest_segments')
            with db.conn:
                db.conn.execute('UPDATE annotations SET payload_json=? WHERE image_id=?',(json.dumps(case),'legacy'))
            self.assertEqual(db.get('legacy')['upper_crest_segments'],[[[.1,.2],[.7,.3]]])
            db.close()

    def test_merge_ties_and_duplicate_votes_require_review(self):
        self.assertEqual(majority(["mild", "severe"]), "requires_review")
        result = make_consensus("one", [
            {"filename":"one.png", "_annotator":"A", "case_grade":"mild"},
            {"filename":"one.png", "_annotator":"A", "case_grade":"severe"},
        ])
        self.assertEqual(result["annotator_count"], 1)
        self.assertTrue(result["duplicate_annotator_exports"])
        self.assertEqual(result["agreement_template"]["case_grade_majority"], "requires_review")

    def test_invalid_dimensions_or_negative_version_rejected(self):
        for updates in ({"width":0}, {"height":-1}, {"annotation_version":-1}):
            with self.assertRaises(ValueError):
                validate_case_payload({"image_id":"x", "filename":"x.png", **updates})

    def test_unknown_export_version_rejected(self):
        with self.assertRaises(ValueError):
            parse_import('{"schema_version":"future-format","cases":[]}')

    def test_localhost_security_and_private_file_protection(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); images=root/'images'; images.mkdir()
            (images/'practice.png').write_bytes(image_bytes())
            (images/'private.json').write_text('{"private":true}')
            state=AppState(images,root/'annotations.sqlite3')
            server=make_server('127.0.0.1',0,state)
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                for path,headers,expected in [
                    ('/api/images',{'Host':'untrusted.example'},403),
                    ('/api/images',{'Origin':'https://untrusted.example'},403),
                    ('/images/private.json',{},404),
                ]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base+path,headers=headers))
                    self.assertEqual(error.exception.code,expected)
                request=urllib.request.Request(base+'/api/import',data=b'[]',method='POST',headers={'Content-Type':'text/plain'})
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(request)
                self.assertEqual(error.exception.code,400)
            finally:
                server.shutdown();server.server_close();worker.join();state.close()
