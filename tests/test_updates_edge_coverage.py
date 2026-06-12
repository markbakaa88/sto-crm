import unittest
from pathlib import Path


class TestUpdatesCoverageEdge(unittest.TestCase):
    def test_latest_backup_info_os_error(self):
        # Переопределим глобальный RUNTIME в updates._runtime, заменив его на объект с другим db_path
        # Но так как RUNTIME - dataclass, мы можем создать новый instance Runtime
        from sto_crm import runtime
        from sto_crm.updates import latest_backup_info
        orig_runtime = runtime.RUNTIME
        try:
            runtime.RUNTIME = runtime.Runtime(
                db_path=Path("/nonexistent_dir_xyz_12345/database.sqlite3"),
                start_time=0.0,
                csrf_token="",
                access_token="",
                bootstrap_token=""
            )
            res = latest_backup_info()
            self.assertIsNone(res)
        finally:
            runtime.RUNTIME = orig_runtime

    def test_semantic_version_tuple_various(self):
        from sto_crm.updates import semantic_version_tuple
        self.assertEqual(semantic_version_tuple("v1.2.3.4"), (1, 2, 3, 4))
        self.assertEqual(semantic_version_tuple(""), (0,))

    def test_scorer_scores(self):
        from sto_crm.updates import manifest_asset_score, release_asset_score
        # MANIFEST_ASSET_RE matches: r"(?:^|[-_.])latest(?:[-_.]|$).*\.json$|^latest\.json$"
        # latest.json => should match
        self.assertEqual(manifest_asset_score({"name": "latest_release.json"}), 80)
        self.assertEqual(manifest_asset_score({"name": "latest.json"}), 100)
        self.assertEqual(manifest_asset_score({"name": "some_manifest.json"}), 10)
        self.assertEqual(manifest_asset_score({"name": "random.json"}), 0)
        self.assertEqual(manifest_asset_score({"name": "doc.pdf"}), 0)

        # STO_CRM_portable.exe -> EXE_ASSET_RE matches "(?:^|[-_.])STO[-_]?CRM(?:[-_.]|$).*\.exe$|^STO_CRM\.exe$" (score = 100)
        # and endswith(".exe") (score += 40)
        # and portable (score += 6)
        # = 146
        self.assertGreater(release_asset_score({"name": "STO_CRM_portable.exe"}), 100)
        
        # STO_CRM_checksum.exe -> EXE_ASSET_RE matches => 100
        # endswith .exe => +40
        # checksum => -80
        # = 60
        self.assertEqual(release_asset_score({"name": "STO_CRM_checksum.exe"}), 60)
