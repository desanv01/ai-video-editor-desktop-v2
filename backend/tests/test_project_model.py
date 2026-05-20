import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

config_defaults = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/test",
    "APP_DEBUG": False,
    "UPLOAD_PATH": "/tmp/uploads",
    "MAX_VIDEO_SIZE_MB": 500,
    "ASR_PROVIDER": "voxtral",
    "VOXTRAL_MODEL": "voxtral-mini-latest",
    "WHISPER_MODEL": "whisper-1",
    "MISTRAL_API_KEY": "",
    "MISTRAL_BASE_URL": "https://api.mistral.ai/v1",
    "OPENAI_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
    "AGENT2_MODEL": "deepseek-chat",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "EMBEDDING_DIMENSIONS": 1536,
    "TEMP_PATH": "/tmp",
    "LOCAL_MODEL_STORAGE_PATH": "/tmp/models",
    "LOCAL_TRANSCRIPTION_MODEL_PATH": "",
    "LOCAL_TRANSCRIPTION_MODEL_ID": "small",
    "LOCAL_TRANSCRIPTION_MODELS_DIR": "",
    "WHISPER_CPP_BINARY_PATH": "whisper-cli",
    "WHISPER_CPP_MODEL_PATH": "",
    "WHISPER_CPP_MODEL_ID": "small",
    "WHISPER_CPP_MODELS_DIR": "",
    "WHISPER_CPP_THREADS": 0,
    "domain_terms_list": [],
}

if "config" not in sys.modules:
    config_stub = types.ModuleType("config")
    config_stub.settings = SimpleNamespace(**config_defaults)
    sys.modules["config"] = config_stub
else:
    settings_stub = sys.modules["config"].settings
    for key, value in config_defaults.items():
        if not hasattr(settings_stub, key):
            setattr(settings_stub, key, value)

from db.models import (
    Project,
    ProjectAsset,
    ProjectAssetKind,
    ProjectAssetRole,
    ProjectAssetSyncRole,
    ProjectAssetStatus,
    ProjectMediaSourceType,
    ProjectSourceMode,
    ProjectStatus,
    Video,
)
from api.routes.projects import (
    _asset_kind_for_upload,
    _asset_role_for_upload,
    _parse_metadata_form,
    _source_type_for_upload,
    _sync_role_for_upload,
    _validate_asset_upload,
)
from models.schemas import (
    ProjectAssetResponse,
    ProjectAssetUploadResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    VideoUploadResponse,
)


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
        self.assertIn("source_type", asset_columns)
        self.assertIn("sync_role", asset_columns)
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
        self.assertEqual(ProjectMediaSourceType.SCREEN_RECORDING.value, "screen_recording")
        self.assertEqual(ProjectMediaSourceType.WEBCAM_RECORDING.value, "webcam_recording")
        self.assertEqual(ProjectAssetSyncRole.AUDIO_MASTER.value, "audio_master")
        self.assertEqual(ProjectAssetStatus.READY.value, "ready")

        status_type = Project.__table__.c.status.type
        kind_type = ProjectAsset.__table__.c.kind.type
        source_type = ProjectAsset.__table__.c.source_type.type
        sync_role_type = ProjectAsset.__table__.c.sync_role.type

        self.assertIn("ready", status_type.enums)
        self.assertIn("mixed_video", kind_type.enums)
        self.assertIn("screen_recording", source_type.enums)
        self.assertIn("audio_master", sync_role_type.enums)

    def test_project_schemas_expose_asset_and_legacy_video_links(self):
        project_id = uuid4()
        asset_id = uuid4()

        asset = ProjectAssetResponse(
            id=asset_id,
            project_id=project_id,
            kind=ProjectAssetKind.MIXED_VIDEO,
            role=ProjectAssetRole.PRIMARY,
            source_type=ProjectMediaSourceType.MIXED_VIDEO,
            sync_role=ProjectAssetSyncRole.PRIMARY_TIMELINE,
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

    def test_project_create_and_asset_upload_schemas_cover_asset_api(self):
        project_id = uuid4()
        asset_id = uuid4()

        request = ProjectCreateRequest(title="Lecture 3", metadata={"course": "CS101"})
        response = ProjectAssetUploadResponse(
            id=asset_id,
            project_id=project_id,
            kind=ProjectAssetKind.AUDIO,
            role=ProjectAssetRole.AUDIO,
            source_type=ProjectMediaSourceType.SEPARATE_AUDIO,
            sync_role=ProjectAssetSyncRole.AUDIO_MASTER,
            status=ProjectAssetStatus.READY,
            filename="stored.wav",
            original_filename="lecture-audio.wav",
            file_path="/tmp/uploads/stored.wav",
            created_at="2026-05-15T00:00:00",
            updated_at="2026-05-15T00:00:00",
            file_size_mb=1.5,
        )

        self.assertEqual(request.title, "Lecture 3")
        self.assertEqual(request.metadata["course"], "CS101")
        self.assertEqual(response.kind, ProjectAssetKind.AUDIO)
        self.assertEqual(response.message, "Asset uploaded successfully.")

    def test_asset_upload_type_maps_to_project_asset_kind_and_role(self):
        self.assertEqual(_asset_kind_for_upload("video", "lecture.mp4"), ProjectAssetKind.MIXED_VIDEO)
        self.assertEqual(_asset_role_for_upload("video"), ProjectAssetRole.PRIMARY)
        self.assertEqual(_source_type_for_upload("video", "lecture.mp4"), ProjectMediaSourceType.MIXED_VIDEO)
        self.assertEqual(_sync_role_for_upload("video"), ProjectAssetSyncRole.PRIMARY_TIMELINE)
        self.assertEqual(_asset_kind_for_upload("screen", "screen.mp4"), ProjectAssetKind.SCREEN_VIDEO)
        self.assertEqual(_asset_role_for_upload("screen"), ProjectAssetRole.SCREEN)
        self.assertEqual(_source_type_for_upload("screen", "screen.mp4"), ProjectMediaSourceType.SCREEN_RECORDING)
        self.assertEqual(_sync_role_for_upload("screen"), ProjectAssetSyncRole.SCREEN_REFERENCE)
        self.assertEqual(_asset_kind_for_upload("camera", "webcam.mov"), ProjectAssetKind.CAMERA_VIDEO)
        self.assertEqual(_asset_role_for_upload("camera"), ProjectAssetRole.CAMERA)
        self.assertEqual(_source_type_for_upload("camera", "webcam.mov"), ProjectMediaSourceType.CAMERA_RECORDING)
        self.assertEqual(_asset_kind_for_upload("webcam", "webcam.mov"), ProjectAssetKind.CAMERA_VIDEO)
        self.assertEqual(_asset_role_for_upload("webcam"), ProjectAssetRole.CAMERA)
        self.assertEqual(_source_type_for_upload("webcam", "webcam.mov"), ProjectMediaSourceType.WEBCAM_RECORDING)
        self.assertEqual(_sync_role_for_upload("webcam"), ProjectAssetSyncRole.CAMERA_OVERLAY)
        self.assertEqual(_asset_kind_for_upload("phone_camera", "phone.mov"), ProjectAssetKind.CAMERA_VIDEO)
        self.assertEqual(_source_type_for_upload("phone_camera", "phone.mov"), ProjectMediaSourceType.PHONE_CAMERA_RECORDING)
        self.assertEqual(_sync_role_for_upload("phone_camera"), ProjectAssetSyncRole.CAMERA_OVERLAY)
        self.assertEqual(_asset_kind_for_upload("audio", "lecture.wav"), ProjectAssetKind.AUDIO)
        self.assertEqual(_asset_role_for_upload("audio"), ProjectAssetRole.AUDIO)
        self.assertEqual(_source_type_for_upload("audio", "lecture.wav"), ProjectMediaSourceType.SEPARATE_AUDIO)
        self.assertEqual(_sync_role_for_upload("audio"), ProjectAssetSyncRole.AUDIO_MASTER)
        self.assertEqual(_asset_kind_for_upload("slides", "week-1.pptx"), ProjectAssetKind.SLIDE_DECK)
        self.assertEqual(_asset_role_for_upload("slides"), ProjectAssetRole.SLIDES)
        self.assertEqual(_asset_kind_for_upload("notes", "outline.pdf"), ProjectAssetKind.PDF_NOTES)
        self.assertEqual(_asset_kind_for_upload("notes", "outline.md"), ProjectAssetKind.TEXT_NOTES)
        self.assertEqual(_asset_role_for_upload("materials"), ProjectAssetRole.SUPPORTING_MATERIAL)

    def test_asset_upload_validation_accepts_expected_groups(self):
        class Upload:
            def __init__(self, filename):
                self.filename = filename

        self.assertEqual(_validate_asset_upload(Upload("lecture.webm"), "video"), ".webm")
        self.assertEqual(_validate_asset_upload(Upload("screen.mkv"), "screen"), ".mkv")
        self.assertEqual(_validate_asset_upload(Upload("webcam.mov"), "camera"), ".mov")
        self.assertEqual(_validate_asset_upload(Upload("webcam.webm"), "webcam"), ".webm")
        self.assertEqual(_validate_asset_upload(Upload("phone.mp4"), "phone_camera"), ".mp4")
        self.assertEqual(_validate_asset_upload(Upload("voice.flac"), "audio"), ".flac")
        self.assertEqual(_validate_asset_upload(Upload("deck.pdf"), "slides"), ".pdf")
        self.assertEqual(_validate_asset_upload(Upload("notes.docx"), "notes"), ".docx")
        self.assertEqual(_validate_asset_upload(Upload("rubric.xlsx"), "materials"), ".xlsx")

        with self.assertRaisesRegex(Exception, "Unsupported audio file type"):
            _validate_asset_upload(Upload("voice.mp4"), "audio")

    def test_metadata_form_must_be_json_object(self):
        self.assertEqual(_parse_metadata_form(None), {})
        self.assertEqual(_parse_metadata_form('{"device": "webcam"}'), {"device": "webcam"})

        with self.assertRaisesRegex(Exception, "metadata must be a JSON object"):
            _parse_metadata_form('["not", "object"]')

        with self.assertRaisesRegex(Exception, "Invalid metadata JSON"):
            _parse_metadata_form("{bad")


if __name__ == "__main__":
    unittest.main()
