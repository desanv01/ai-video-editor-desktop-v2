import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if "config" not in sys.modules:
    config_stub = types.ModuleType("config")
    config_stub.settings = SimpleNamespace(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost/test",
        APP_DEBUG=False,
        ASR_PROVIDER="voxtral",
        VOXTRAL_MODEL="voxtral-mini-latest",
        WHISPER_MODEL="whisper-1",
        MISTRAL_API_KEY="",
        MISTRAL_BASE_URL="https://api.mistral.ai/v1",
        OPENAI_API_KEY="",
        DEEPSEEK_API_KEY="",
        DEEPSEEK_BASE_URL="https://api.deepseek.com",
        AGENT2_MODEL="deepseek-chat",
        EMBEDDING_MODEL="text-embedding-3-small",
        EMBEDDING_DIMENSIONS=1536,
        TEMP_PATH="/tmp",
        LOCAL_MODEL_STORAGE_PATH="/tmp/models",
        LOCAL_TRANSCRIPTION_MODEL_PATH="",
        LOCAL_TRANSCRIPTION_MODEL_ID="small",
        LOCAL_TRANSCRIPTION_MODELS_DIR="",
        WHISPER_CPP_BINARY_PATH="whisper-cli",
        WHISPER_CPP_MODEL_PATH="",
        WHISPER_CPP_MODEL_ID="small",
        WHISPER_CPP_MODELS_DIR="",
        WHISPER_CPP_THREADS=0,
        domain_terms_list=[],
    )
    sys.modules["config"] = config_stub

from db.models import (
    Project,
    ProjectAsset,
    ProjectAssetKind,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectSourceMode,
    ProjectStatus,
    Video,
)
from models.schemas import ProjectAssetResponse, ProjectDetailResponse, VideoUploadResponse


class ProjectModelTests(unittest.TestCase):
    def test_project_and_asset_tables_are_project_first(self):
        project_columns = Project.__table__.c
        asset_columns = ProjectAsset.__table__.c
        video_columns = Video.__table__.c

        self.assertIn("title", project_columns)
        self.assertIn("source_mode", project_columns)
        self.assertIn("metadata_json", project_columns)

        self.assertIn("project_id", asset_columns)
        self.assertIn("kind", asset_columns)
        self.assertIn("role", asset_columns)
        self.assertIn("sync_offset_seconds", asset_columns)
        self.assertEqual(
            {fk.column.table.name for fk in asset_columns.project_id.foreign_keys},
            {"projects"},
        )

        self.assertIn("project_id", video_columns)
        self.assertIn("project_asset_id", video_columns)
        self.assertEqual(
            {fk.column.table.name for fk in video_columns.project_id.foreign_keys},
            {"projects"},
        )
        self.assertEqual(
            {fk.column.table.name for fk in video_columns.project_asset_id.foreign_keys},
            {"project_assets"},
        )

    def test_project_enums_persist_wire_values(self):
        self.assertEqual(ProjectStatus.READY.value, "ready")
        self.assertEqual(ProjectSourceMode.SINGLE_VIDEO.value, "single_video")
        self.assertEqual(ProjectAssetKind.MIXED_VIDEO.value, "mixed_video")
        self.assertEqual(ProjectAssetRole.PRIMARY.value, "primary")
        self.assertEqual(ProjectAssetStatus.READY.value, "ready")

        status_type = Project.__table__.c.status.type
        kind_type = ProjectAsset.__table__.c.kind.type

        self.assertIn("ready", status_type.enums)
        self.assertIn("mixed_video", kind_type.enums)

    def test_project_schemas_expose_asset_and_legacy_video_links(self):
        project_id = uuid4()
        asset_id = uuid4()

        asset = ProjectAssetResponse(
            id=asset_id,
            project_id=project_id,
            kind=ProjectAssetKind.MIXED_VIDEO,
            role=ProjectAssetRole.PRIMARY,
            status=ProjectAssetStatus.READY,
            is_primary=True,
            filename="stored.mp4",
            original_filename="lecture.mp4",
            file_path="uploads/stored.mp4",
            created_at="2026-05-15T00:00:00",
            updated_at="2026-05-15T00:00:00",
        )
        project = ProjectDetailResponse(
            id=project_id,
            title="lecture",
            status=ProjectStatus.READY,
            source_mode=ProjectSourceMode.SINGLE_VIDEO,
            created_at="2026-05-15T00:00:00",
            updated_at="2026-05-15T00:00:00",
            assets=[asset],
        )
        upload = VideoUploadResponse(
            id=uuid4(),
            project_id=project_id,
            project_asset_id=asset_id,
            filename="lecture.mp4",
            status="uploaded",
        )

        self.assertEqual(project.assets[0].kind, ProjectAssetKind.MIXED_VIDEO)
        self.assertEqual(upload.project_id, project_id)
        self.assertEqual(upload.project_asset_id, asset_id)


if __name__ == "__main__":
    unittest.main()
