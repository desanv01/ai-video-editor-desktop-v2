import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import BigInteger


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

config_defaults = {
    "DATABASE_URL": "postgresql+asyncpg://user:pass@localhost/test",
    "APP_DEBUG": False,
    "UPLOAD_PATH": "/tmp/uploads",
    "MAX_VIDEO_SIZE_MB": 10240,
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
    "VIDEO_STORAGE_PATH": "/tmp/videos",
    "SILENCE_THRESHOLD_DB": -35,
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
    _project_source_sync_plan,
    _source_type_for_upload,
    _structure_metadata_for_upload,
    _sync_role_for_upload,
    _validate_asset_upload,
)
from models.schemas import (
    NativeImportInitResponse,
    ProjectAssetResponse,
    ProjectAssetUploadResponse,
    ProjectSourceSyncPlanResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectUpdateRequest,
    VideoUploadResponse,
)
from services.source_sync import (
    SYNC_METADATA_KEY,
    choose_reference_asset,
    extract_user_sync_offset,
    recommend_sync_offsets,
)
from services.upload_limits import max_upload_size_bytes, upload_limit_label


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
        self.assertIsInstance(asset_columns.file_size_bytes.type, BigInteger)
        self.assertIsInstance(video_columns.file_size_bytes.type, BigInteger)

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

    def test_native_import_schema_reports_disk_and_staging_details(self):
        project_id = uuid4()
        response = NativeImportInitResponse(
            token="session-token",
            project_id=project_id,
            original_filename="lecture.mp4",
            mime_type="video/mp4",
            file_size_bytes=2_730_000_000,
            max_size_bytes=10 * 1024 * 1024 * 1024,
            available_disk_bytes=40 * 1024 * 1024 * 1024,
            required_free_bytes=30 * 1024 * 1024 * 1024,
            staging_relative_path="staging/native-imports/session-token-lecture.mp4",
            staging_part_relative_path="staging/native-imports/session-token-lecture.mp4.part",
            warnings=["1 orphaned or stale staged import file(s) already exist. Review diagnostics before cleanup."],
        )

        self.assertEqual(response.project_id, project_id)
        self.assertIn(".part", response.staging_part_relative_path)
        self.assertGreater(response.available_disk_bytes, response.file_size_bytes)

    def test_project_update_schema_supports_dashboard_rename_and_setup_changes(self):
        request = ProjectUpdateRequest(
            title="Renamed lecture",
            description=None,
            source_mode=ProjectSourceMode.MULTI_SOURCE,
            project_type="tutorial",
            metadata={"dashboard_updated": True},
        )

        self.assertEqual(request.title, "Renamed lecture")
        self.assertIsNone(request.description)
        self.assertEqual(request.source_mode, ProjectSourceMode.MULTI_SOURCE)
        self.assertEqual(request.project_type, "tutorial")
        self.assertTrue(request.metadata["dashboard_updated"])

    def test_upload_limit_defaults_to_ten_gigabytes(self):
        settings = SimpleNamespace(MAX_VIDEO_SIZE_MB=10240)

        self.assertEqual(max_upload_size_bytes(settings), 10 * 1024 * 1024 * 1024)
        self.assertEqual(upload_limit_label(settings), "10GB")

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
        self.assertEqual(_source_type_for_upload("notes", "outline.pdf"), ProjectMediaSourceType.PDF_NOTES)
        self.assertEqual(_source_type_for_upload("notes", "outline.md"), ProjectMediaSourceType.TEXT_NOTES)
        self.assertEqual(_sync_role_for_upload("slides"), ProjectAssetSyncRole.STRUCTURE_REFERENCE)
        self.assertEqual(_sync_role_for_upload("notes"), ProjectAssetSyncRole.STRUCTURE_REFERENCE)

    def test_teaching_material_metadata_marks_structure_references(self):
        slide_metadata = _structure_metadata_for_upload(
            "slides",
            ProjectMediaSourceType.SLIDE_DECK,
            ".pptx",
        )
        pdf_metadata = _structure_metadata_for_upload(
            "notes",
            ProjectMediaSourceType.PDF_NOTES,
            ".pdf",
        )
        text_metadata = _structure_metadata_for_upload(
            "notes",
            ProjectMediaSourceType.TEXT_NOTES,
            ".md",
        )

        self.assertEqual(slide_metadata["structure_reference_role"], "slide_sequence")
        self.assertEqual(slide_metadata["document_format"], "pptx")
        self.assertTrue(slide_metadata["structure_inference_ready"])
        self.assertEqual(pdf_metadata["structure_reference_role"], "pdf_notes")
        self.assertEqual(text_metadata["structure_reference_role"], "text_notes")

        asset = ProjectAssetResponse(
            id=uuid4(),
            project_id=uuid4(),
            kind=ProjectAssetKind.PDF_NOTES,
            role=ProjectAssetRole.NOTES,
            source_type=ProjectMediaSourceType.PDF_NOTES,
            sync_role=ProjectAssetSyncRole.STRUCTURE_REFERENCE,
            status=ProjectAssetStatus.READY,
            filename="stored.pdf",
            original_filename="outline.pdf",
            file_path="/tmp/uploads/stored.pdf",
            metadata_json=pdf_metadata,
            created_at="2026-05-20T00:00:00",
            updated_at="2026-05-20T00:00:00",
        )

        self.assertEqual(asset.structure_reference_role, "pdf_notes")
        self.assertEqual(asset.document_format, "pdf")
        self.assertTrue(asset.structure_inference_ready)

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
        self.assertEqual(_validate_asset_upload(Upload("mic.webm"), "audio"), ".webm")
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

    def test_metadata_based_source_sync_recommends_relative_offsets(self):
        project_id = uuid4()
        screen = ProjectAsset(
            id=uuid4(),
            project_id=project_id,
            kind=ProjectAssetKind.SCREEN_VIDEO,
            role=ProjectAssetRole.SCREEN,
            source_type=ProjectMediaSourceType.SCREEN_RECORDING,
            sync_role=ProjectAssetSyncRole.SCREEN_REFERENCE,
            status=ProjectAssetStatus.READY,
            is_primary=True,
            filename="screen.mp4",
            original_filename="screen.mp4",
            file_path="/tmp/screen.mp4",
            sync_offset_seconds=0,
            metadata_json={"user_metadata": {"recording_started_at": "2026-05-20T10:00:00Z"}},
        )
        camera = ProjectAsset(
            id=uuid4(),
            project_id=project_id,
            kind=ProjectAssetKind.CAMERA_VIDEO,
            role=ProjectAssetRole.CAMERA,
            source_type=ProjectMediaSourceType.CAMERA_RECORDING,
            sync_role=ProjectAssetSyncRole.CAMERA_OVERLAY,
            status=ProjectAssetStatus.READY,
            filename="camera.mp4",
            original_filename="camera.mp4",
            file_path="/tmp/camera.mp4",
            sync_offset_seconds=2.5,
            metadata_json={"user_metadata": {"recording_started_at": "2026-05-20T10:00:02.500Z"}},
        )

        reference, recommendations = recommend_sync_offsets([camera, screen])
        by_asset = {item.asset_id: item for item in recommendations}

        self.assertEqual(reference.id, screen.id)
        self.assertEqual(by_asset[str(screen.id)].recommended_offset_seconds, 0)
        self.assertEqual(by_asset[str(camera.id)].recommended_offset_seconds, 2.5)
        self.assertEqual(by_asset[str(camera.id)].method, "metadata_timestamp")

    def test_source_sync_plan_marks_manual_adjustment_and_waveform_readiness(self):
        project_id = uuid4()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        screen = ProjectAsset(
            id=uuid4(),
            project_id=project_id,
            kind=ProjectAssetKind.SCREEN_VIDEO,
            role=ProjectAssetRole.SCREEN,
            source_type=ProjectMediaSourceType.SCREEN_RECORDING,
            sync_role=ProjectAssetSyncRole.SCREEN_REFERENCE,
            status=ProjectAssetStatus.READY,
            is_primary=True,
            filename="screen.mp4",
            original_filename="screen.mp4",
            file_path="/tmp/screen.mp4",
            sync_offset_seconds=0,
            metadata_json={"user_metadata": {"start_timecode_seconds": 10}},
            created_at=now,
            updated_at=now,
        )
        audio = ProjectAsset(
            id=uuid4(),
            project_id=project_id,
            kind=ProjectAssetKind.AUDIO,
            role=ProjectAssetRole.AUDIO,
            source_type=ProjectMediaSourceType.SEPARATE_AUDIO,
            sync_role=ProjectAssetSyncRole.AUDIO_MASTER,
            status=ProjectAssetStatus.READY,
            is_primary=False,
            filename="audio.wav",
            original_filename="audio.wav",
            file_path="/tmp/audio.wav",
            sync_offset_seconds=1.75,
            metadata_json={"user_metadata": {"start_timecode_seconds": 11.5}},
            created_at=now,
            updated_at=now,
        )
        project = Project(
            id=project_id,
            title="Multi-source lecture",
            status=ProjectStatus.READY,
            source_mode=ProjectSourceMode.MULTI_SOURCE,
        )
        project.assets = [screen, audio]

        plan = _project_source_sync_plan(project)
        audio_item = next(item for item in plan.assets if item.asset.id == audio.id)

        self.assertIsInstance(plan, ProjectSourceSyncPlanResponse)
        self.assertEqual(plan.reference_asset_id, screen.id)
        self.assertEqual(audio_item.recommended_offset_seconds, 1.5)
        self.assertEqual(audio_item.current_offset_seconds, 1.75)
        self.assertEqual(audio_item.manual_adjustment_seconds, 0.25)
        self.assertTrue(audio_item.waveform_sync_ready)

    def test_user_supplied_sync_offset_can_seed_upload_metadata(self):
        metadata = {"sync_offset_seconds": "3.25", "device": "field_recorder"}

        self.assertEqual(extract_user_sync_offset(metadata), 3.25)

        asset = ProjectAsset(
            id=uuid4(),
            project_id=uuid4(),
            kind=ProjectAssetKind.AUDIO,
            role=ProjectAssetRole.AUDIO,
            source_type=ProjectMediaSourceType.SEPARATE_AUDIO,
            sync_role=ProjectAssetSyncRole.AUDIO_MASTER,
            status=ProjectAssetStatus.READY,
            filename="audio.wav",
            original_filename="audio.wav",
            file_path="/tmp/audio.wav",
            sync_offset_seconds=3.25,
            metadata_json={SYNC_METADATA_KEY: {"user_adjusted": True}},
        )

        self.assertEqual(choose_reference_asset([asset]).id, asset.id)
        self.assertTrue(asset.metadata_json[SYNC_METADATA_KEY]["user_adjusted"])


if __name__ == "__main__":
    unittest.main()
