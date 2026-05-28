import sys
import shutil
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class AsyncOpenAI:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    openai_stub.AsyncOpenAI = AsyncOpenAI
    sys.modules["openai"] = openai_stub

if "config" not in sys.modules:
    config_stub = types.ModuleType("config")
    config_stub.settings = SimpleNamespace(
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

from providers.defaults import build_provider_registry
from providers.interfaces import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    ProviderKind,
    ProviderMetadata,
    TranscriptionProvider,
    TranscriptionRequest,
    TranscriptionResponse,
)
from providers.processing_modes import (
    CapabilityModeConfig,
    ProcessingMode,
    ProcessingModeConfig,
    build_processing_mode_config,
    parse_processing_mode,
)
from providers.registry import ProviderRegistry
from providers.whisper_cpp import (
    WHISPER_CPP_PROVIDER_ID,
    WhisperCppRunResult,
    WhisperCppTranscriptionProvider,
    build_whisper_cpp_model_catalog,
    resolve_whisper_cpp_model_selection,
)
from services.local_transcription_models import LocalTranscriptionModelService
from services.llm import LLMService
from services.transcription import TranscriptionService


def settings_stub(**overrides):
    defaults = {
        "ASR_PROVIDER": "voxtral",
        "VOXTRAL_MODEL": "voxtral-mini-latest",
        "WHISPER_MODEL": "whisper-1",
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "AGENT2_MODEL": "deepseek-chat",
        "OPENAI_API_KEY": "",
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
        "AI_PROCESSING_MODE": "hybrid",
        "AI_PROVIDER_FALLBACK_ENABLED": True,
        "AI_TRANSCRIPTION_MODE": "api",
        "AI_CHAT_MODE": "api",
        "AI_EMBEDDING_MODE": "api",
        "AI_VISION_MODE": "api",
        "AI_LOCAL_RUNTIME_MODE": "local",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeChatProvider(ChatProvider):
    def __init__(self, provider_id="fake-chat", text="ok"):
        self.requests = []
        self._text = text
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.CHAT,
            label="Fake Chat",
            provider_name="fake",
            default_model="fake-chat-model",
        )

    @property
    def metadata(self):
        return self._metadata

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        return ChatResponse(
            text=self._text,
            provider_id=self.metadata.provider_id,
            model=request.model or self.metadata.default_model,
        )


class FakeEmbeddingProvider(EmbeddingProvider):
    def __init__(self, provider_id="fake-embedding"):
        self.requests = []
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.EMBEDDING,
            label="Fake Embeddings",
            provider_name="fake",
            default_model="fake-embedding-model",
        )

    @property
    def metadata(self):
        return self._metadata

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        return EmbeddingResponse(
            embeddings=[[float(i), float(len(text))] for i, text in enumerate(request.texts)],
            provider_id=self.metadata.provider_id,
            model=request.model or self.metadata.default_model,
            dimensions=2,
        )


class FakeTranscriptionProvider(TranscriptionProvider):
    def __init__(self, provider_id, transcript=None, error=None, is_local=False):
        self.calls = []
        self.error = error
        self.transcript = transcript or {
            "text": f"{provider_id} transcript",
            "duration": 4.0,
            "segments": [],
            "words": [],
            "speakers": [],
            "provider": provider_id,
        }
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.TRANSCRIPTION,
            label=provider_id.title(),
            provider_name="fake",
            default_model=f"{provider_id}-model",
            is_local=is_local,
        )

    @property
    def metadata(self):
        return self._metadata

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        self.calls.append(request)
        if self.error:
            raise self.error
        return TranscriptionResponse(
            transcript=dict(self.transcript),
            provider_id=self.metadata.provider_id,
            model=self.metadata.default_model,
        )


class ProviderRegistryTests(unittest.TestCase):
    def test_register_get_default_replace_and_describe(self):
        registry = ProviderRegistry()
        first = FakeChatProvider("first-chat")
        second = FakeChatProvider("second-chat")

        registry.register(first)
        registry.register(second, set_default=True)

        self.assertIs(registry.get(ProviderKind.CHAT, "first-chat"), first)
        self.assertIs(registry.get(ProviderKind.CHAT), second)
        self.assertEqual(registry.default_provider_id(ProviderKind.CHAT), "second-chat")

        with self.assertRaisesRegex(ValueError, "already registered"):
            registry.register(FakeChatProvider("first-chat"))

        replacement = FakeChatProvider("first-chat", text="replacement")
        registry.register(replacement, replace=True, set_default=True)

        self.assertIs(registry.get(ProviderKind.CHAT, "first-chat"), replacement)
        self.assertIs(registry.get(ProviderKind.CHAT), replacement)

        description = registry.describe()
        chat_entries = {
            entry["provider_id"]: entry for entry in description[ProviderKind.CHAT.value]
        }
        self.assertTrue(chat_entries["first-chat"]["is_default"])
        self.assertEqual(chat_entries["second-chat"]["configured_processing_mode"], "api")

    def test_missing_provider_errors_are_actionable(self):
        registry = ProviderRegistry()

        with self.assertRaisesRegex(KeyError, "No default provider registered"):
            registry.get(ProviderKind.CHAT)

        with self.assertRaisesRegex(KeyError, "Provider not registered"):
            registry.set_default(ProviderKind.CHAT, "missing")


class ProcessingModeTests(unittest.TestCase):
    def test_build_processing_mode_config_selects_defaults_by_capability(self):
        registry = ProviderRegistry()
        registry.register(FakeTranscriptionProvider("voxtral"), set_default=True)
        registry.register(FakeChatProvider("deepseek-chat"), set_default=True)
        registry.register(FakeEmbeddingProvider("openai-embeddings"), set_default=True)

        config = build_processing_mode_config(settings_stub(), registry)

        transcription = config.for_kind(ProviderKind.TRANSCRIPTION)
        chat = config.for_kind(ProviderKind.CHAT)
        local_runtime = config.for_kind(ProviderKind.LOCAL_RUNTIME)

        self.assertEqual(config.default_mode, ProcessingMode.HYBRID)
        self.assertEqual(transcription.mode, ProcessingMode.API)
        self.assertEqual(transcription.api_provider_id, "voxtral")
        self.assertEqual(transcription.mode_order(), (ProcessingMode.API,))
        self.assertEqual(chat.api_provider_id, "deepseek-chat")
        self.assertEqual(local_runtime.mode, ProcessingMode.LOCAL)
        self.assertIsNone(local_runtime.api_provider_id)

    def test_hybrid_mode_uses_capability_specific_fallback_order(self):
        config = ProcessingModeConfig(
            fallback_enabled=False,
            capabilities={
                ProviderKind.TRANSCRIPTION: CapabilityModeConfig(
                    kind=ProviderKind.TRANSCRIPTION,
                    mode=ProcessingMode.HYBRID,
                    api_provider_id="voxtral",
                    local_provider_id="whisper-cpp",
                    fallback_enabled=False,
                )
            },
        )

        transcription = config.for_kind(ProviderKind.TRANSCRIPTION)

        self.assertFalse(transcription.fallback_enabled)
        self.assertEqual(
            transcription.mode_order(),
            (ProcessingMode.LOCAL, ProcessingMode.API),
        )
        self.assertEqual(
            config.describe()["capabilities"]["transcription"]["mode_order"],
            ["local", "api"],
        )

    def test_parse_processing_mode_normalizes_and_rejects_unknown_values(self):
        self.assertEqual(parse_processing_mode(" HYBRID ", field_name="mode"), ProcessingMode.HYBRID)

        with self.assertRaisesRegex(ValueError, "mode must be one of"):
            parse_processing_mode("remote", field_name="mode")


class DefaultRegistryTests(unittest.TestCase):
    def test_default_registry_preserves_existing_pipeline_provider_ids(self):
        registry = build_provider_registry(settings_stub(ASR_PROVIDER="whisper"))

        self.assertEqual(
            registry.default_provider_id(ProviderKind.TRANSCRIPTION),
            "whisper",
        )
        self.assertEqual(registry.default_provider_id(ProviderKind.CHAT), "deepseek-chat")
        self.assertEqual(
            registry.default_provider_id(ProviderKind.EMBEDDING),
            "openai-embeddings",
        )
        self.assertEqual(
            registry.default_provider_id(ProviderKind.VISION),
            "vision-unconfigured",
        )
        self.assertEqual(
            registry.default_provider_id(ProviderKind.LOCAL_RUNTIME),
            "local-runtime-unconfigured",
        )

        transcription_ids = {
            provider.metadata.provider_id
            for provider in registry.list(ProviderKind.TRANSCRIPTION)
        }
        self.assertEqual(transcription_ids, {"voxtral", "whisper", "whisper-cpp"})

    def test_default_registry_exposes_local_transcription_provider_for_hybrid_mode(self):
        registry = build_provider_registry(settings_stub(AI_TRANSCRIPTION_MODE="hybrid"))

        transcription_mode = registry.processing_mode_for(ProviderKind.TRANSCRIPTION)

        self.assertEqual(transcription_mode.api_provider_id, "voxtral")
        self.assertEqual(transcription_mode.local_provider_id, "whisper-cpp")
        self.assertEqual(
            registry.get(ProviderKind.TRANSCRIPTION, "whisper-cpp").metadata.is_local,
            True,
        )


class WhisperCppProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_reports_not_configured_without_binary_or_model(self):
        provider = WhisperCppTranscriptionProvider(
            binary_path="missing-whisper-cli",
            model_path="C:/missing/ggml-small.en.bin",
            model_id="small.en",
        )

        health = await provider.health()

        self.assertEqual(health.status.value, "not_configured")
        self.assertIn("issues", health.details)

    async def test_transcribe_parses_whisper_cpp_json_without_real_model_download(self):
        async def fake_runner(command, output_json_path):
            return WhisperCppRunResult(stdout=json_payload, stderr="")

        json_payload = """
        {
          "result": {"language": "en"},
          "transcription": [
            {
              "text": " Hello class",
              "offsets": {"from": 0, "to": 1200}
            },
            {
              "text": " today we study bridges",
              "timestamps": {"from": "00:00:01.200", "to": "00:00:03.000"}
            }
          ]
        }
        """

        provider = WhisperCppTranscriptionProvider(
            binary_path="whisper-cli",
            model_path="ggml-small.en.bin",
            model_id="small.en",
            work_dir=str(Path.cwd()),
            runner=fake_runner,
            validate_runtime=False,
        )

        response = await provider.transcribe(
            TranscriptionRequest(audio_path="lecture.wav", language="en")
        )

        transcript = response.transcript
        self.assertEqual(response.provider_id, WHISPER_CPP_PROVIDER_ID)
        self.assertEqual(transcript["provider"], WHISPER_CPP_PROVIDER_ID)
        self.assertEqual(transcript["text"], "Hello class today we study bridges")
        self.assertEqual(transcript["language"], "en")
        self.assertEqual(transcript["duration"], 3.0)
        self.assertEqual(len(transcript["segments"]), 2)
        self.assertEqual(transcript["segments"][1]["start"], 1.2)
        self.assertGreater(len(transcript["words"]), 0)

    def test_model_selection_prefers_whisper_cpp_specific_model_path(self):
        selection = resolve_whisper_cpp_model_selection(
            settings_stub(
                LOCAL_TRANSCRIPTION_MODEL_PATH="C:/models/local.bin",
                WHISPER_CPP_MODEL_PATH="C:/models/whisper-cpp.bin",
                WHISPER_CPP_MODEL_ID="large-v3",
                WHISPER_CPP_BINARY_PATH="C:/tools/whisper-cli.exe",
            )
        )

        self.assertEqual(selection.model_id, "large-v3")
        self.assertEqual(selection.tier, "accurate")
        self.assertEqual(selection.model_path, "C:/models/whisper-cpp.bin")
        self.assertEqual(selection.binary_path, "C:/tools/whisper-cli.exe")

    def test_model_catalog_reports_size_quality_and_local_status(self):
        with patch(
            "providers.whisper_cpp.os.path.isfile",
            side_effect=lambda path: str(path).endswith("ggml-medium.bin"),
        ):
            catalog = build_whisper_cpp_model_catalog(
                settings_stub(
                    WHISPER_CPP_MODEL_ID="medium",
                    WHISPER_CPP_MODELS_DIR="C:/models",
                )
            )

        entries = {entry.model_id: entry for entry in catalog}

        self.assertEqual(list(entries), ["small", "medium", "large-v3"])
        self.assertEqual(entries["small"].size_label, "466 MB")
        self.assertTrue(entries["small"].download_url.endswith("/ggml-small.bin"))
        self.assertEqual(entries["small"].speed, "fast")
        self.assertEqual(entries["small"].quality, "good")
        self.assertTrue(entries["medium"].active)
        self.assertTrue(entries["medium"].downloaded)
        self.assertFalse(entries["large-v3"].downloaded)

    def test_legacy_small_en_model_id_maps_to_catalog_small(self):
        selection = resolve_whisper_cpp_model_selection(
            settings_stub(WHISPER_CPP_MODEL_ID="small.en")
        )

        self.assertEqual(selection.model_id, "small")
        self.assertEqual(selection.tier, "fast")


class LocalTranscriptionModelServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp_root = Path(__file__).resolve().parent / ".tmp_local_models"
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)
        self.tmp_root.mkdir(parents=True)

    def tearDown(self):
        if self.tmp_root.exists():
            shutil.rmtree(self.tmp_root)

    def test_existing_model_download_request_returns_completed_job_and_activates(self):
        local_settings = settings_stub(LOCAL_MODEL_STORAGE_PATH=str(self.tmp_root))
        model_dir = self.tmp_root / "whisper-cpp"
        model_dir.mkdir()
        model_path = model_dir / "ggml-small.bin"
        model_path.write_bytes(b"model")

        service = LocalTranscriptionModelService()
        with patch("services.local_transcription_models.settings", local_settings):
            job = service.start_download("small", activate_on_complete=True)

        self.assertEqual(job.status, "completed")
        self.assertEqual(job.progress_percent, 100.0)
        self.assertEqual(local_settings.WHISPER_CPP_MODEL_ID, "small")
        self.assertEqual(local_settings.WHISPER_CPP_MODEL_PATH, str(model_path))

    def test_remove_model_deletes_managed_file(self):
        local_settings = settings_stub(LOCAL_MODEL_STORAGE_PATH=str(self.tmp_root))
        model_dir = self.tmp_root / "whisper-cpp"
        model_dir.mkdir()
        model_path = model_dir / "ggml-medium.bin"
        model_path.write_bytes(b"model")

        service = LocalTranscriptionModelService()
        with patch("services.local_transcription_models.settings", local_settings):
            result = service.remove_model("medium")

        self.assertTrue(result.removed)
        self.assertFalse(model_path.exists())

    def test_remove_model_refuses_arbitrary_configured_file_path(self):
        outside_dir = self.tmp_root / "outside"
        outside_dir.mkdir()
        outside_path = outside_dir / "ggml-small.bin"
        outside_path.write_bytes(b"model")
        local_settings = settings_stub(
            LOCAL_MODEL_STORAGE_PATH=str(self.tmp_root / "managed"),
            WHISPER_CPP_MODEL_ID="small",
            WHISPER_CPP_MODEL_PATH=str(outside_path),
        )

        service = LocalTranscriptionModelService()
        with patch("services.local_transcription_models.settings", local_settings):
            with self.assertRaisesRegex(RuntimeError, "Refusing to remove"):
                service.remove_model("small")

        self.assertTrue(outside_path.exists())


class TranscriptionFallbackTests(unittest.IsolatedAsyncioTestCase):
    def _service_with_route(self, mode_config, providers):
        service = object.__new__(TranscriptionService)
        registry = Mock()
        registry.processing_mode_for.return_value = mode_config
        registry.default_provider_id.return_value = mode_config.api_provider_id

        service._get_audio_duration = AsyncMock(return_value=2.0)
        service._get_transcription_provider = Mock(
            side_effect=lambda provider_id: providers[provider_id]
        )
        service._registry = Mock(return_value=registry)
        return service

    async def test_voxtral_failure_falls_back_to_whisper_when_enabled(self):
        voxtral = FakeTranscriptionProvider("voxtral", error=RuntimeError("api down"))
        whisper = FakeTranscriptionProvider(
            "whisper",
            transcript={
                "text": "fallback transcript",
                "duration": 2.0,
                "segments": [{"text": "fallback transcript", "start": 0, "end": 2}],
                "words": [],
                "speakers": [],
                "provider": "whisper",
            },
        )
        mode_config = CapabilityModeConfig(
            kind=ProviderKind.TRANSCRIPTION,
            mode=ProcessingMode.API,
            api_provider_id="voxtral",
            fallback_enabled=True,
        )
        service = self._service_with_route(
            mode_config,
            {"voxtral": voxtral, "whisper": whisper},
        )

        result = await service.transcribe("lecture.wav", language="en", domain_terms=["bridge"])

        self.assertEqual(result["text"], "fallback transcript")
        self.assertEqual(result["provider"], "whisper_fallback")
        self.assertEqual(result["transcription_mode"], "api")
        self.assertEqual(result["transcription_route"]["attempted_providers"], ["voxtral", "whisper"])
        self.assertEqual(result["transcription_route"]["fallback_from"], "voxtral")
        self.assertEqual(len(voxtral.calls), 1)
        self.assertEqual(len(whisper.calls), 1)
        self.assertEqual(whisper.calls[0].metadata["duration"], 2.0)
        self.assertEqual(whisper.calls[0].domain_terms, ["bridge"])

    async def test_voxtral_failure_raises_when_fallback_disabled(self):
        voxtral = FakeTranscriptionProvider("voxtral", error=RuntimeError("api down"))
        mode_config = CapabilityModeConfig(
            kind=ProviderKind.TRANSCRIPTION,
            mode=ProcessingMode.API,
            api_provider_id="voxtral",
            fallback_enabled=False,
        )
        service = self._service_with_route(
            mode_config,
            {"voxtral": voxtral, "whisper": FakeTranscriptionProvider("whisper")},
        )

        with self.assertRaisesRegex(RuntimeError, "api down"):
            await service.transcribe("lecture.wav")

        requested_providers = [
            call.args[0] for call in service._get_transcription_provider.call_args_list
        ]
        self.assertEqual(requested_providers, ["voxtral"])

    async def test_hybrid_mode_tries_local_before_api(self):
        local = FakeTranscriptionProvider(
            "whisper-cpp",
            transcript={
                "text": "local transcript",
                "duration": 2.0,
                "segments": [{"text": "local transcript", "start": 0, "end": 2}],
                "words": [],
                "speakers": [],
                "provider": "whisper-cpp",
            },
            is_local=True,
        )
        voxtral = FakeTranscriptionProvider("voxtral")
        mode_config = CapabilityModeConfig(
            kind=ProviderKind.TRANSCRIPTION,
            mode=ProcessingMode.HYBRID,
            api_provider_id="voxtral",
            local_provider_id="whisper-cpp",
            fallback_enabled=True,
        )
        service = self._service_with_route(
            mode_config,
            {"whisper-cpp": local, "voxtral": voxtral},
        )

        result = await service.transcribe("lecture.wav")

        self.assertEqual(result["text"], "local transcript")
        self.assertEqual(result["provider"], "whisper-cpp")
        self.assertEqual(result["transcription_route"]["attempted_providers"], ["whisper-cpp"])
        self.assertEqual(len(local.calls), 1)
        self.assertEqual(len(voxtral.calls), 0)

    async def test_hybrid_mode_falls_back_to_api_when_local_fails(self):
        local = FakeTranscriptionProvider(
            "whisper-cpp",
            error=RuntimeError("local model missing"),
            is_local=True,
        )
        voxtral = FakeTranscriptionProvider(
            "voxtral",
            transcript={
                "text": "api transcript",
                "duration": 2.0,
                "segments": [{"text": "api transcript", "start": 0, "end": 2}],
                "words": [],
                "speakers": [],
                "provider": "voxtral",
            },
        )
        mode_config = CapabilityModeConfig(
            kind=ProviderKind.TRANSCRIPTION,
            mode=ProcessingMode.HYBRID,
            api_provider_id="voxtral",
            local_provider_id="whisper-cpp",
            fallback_enabled=True,
        )
        service = self._service_with_route(
            mode_config,
            {"whisper-cpp": local, "voxtral": voxtral},
        )

        result = await service.transcribe("lecture.wav")

        self.assertEqual(result["text"], "api transcript")
        self.assertEqual(result["provider"], "voxtral")
        self.assertEqual(
            result["transcription_route"]["attempted_providers"],
            ["whisper-cpp", "voxtral"],
        )
        self.assertEqual(result["transcription_route"]["fallback_from"], "whisper-cpp")


class PipelineCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_llm_chat_and_embedding_service_use_provider_registry(self):
        registry = ProviderRegistry()
        chat_provider = FakeChatProvider("deepseek-chat", text='{"ok": true}')
        embedding_provider = FakeEmbeddingProvider("openai-embeddings")
        registry.register(chat_provider, set_default=True)
        registry.register(embedding_provider, set_default=True)

        with patch("services.llm.get_provider_registry", return_value=registry):
            service = LLMService()
            chat_text = await service.chat(
                [{"role": "user", "content": "Plan edits"}],
                model="deepseek-chat",
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            embeddings = await service.embed(["lecture section", "summary"])

        self.assertEqual(chat_text, '{"ok": true}')
        self.assertEqual(chat_provider.requests[0].response_format, {"type": "json_object"})
        self.assertEqual(chat_provider.requests[0].messages[0]["content"], "Plan edits")
        self.assertEqual(embeddings, [[0.0, 15.0], [1.0, 7.0]])
        self.assertEqual(embedding_provider.requests[0].texts, ["lecture section", "summary"])

    async def test_llm_chat_json_keeps_existing_markdown_json_parsing(self):
        registry = ProviderRegistry()
        registry.register(
            FakeChatProvider("deepseek-chat", text='```json\n{"decision": "keep"}\n```'),
            set_default=True,
        )

        with patch("services.llm.get_provider_registry", return_value=registry):
            result = await LLMService().chat_json(
                [{"role": "user", "content": "Return JSON"}]
            )

        self.assertEqual(result, {"decision": "keep"})


if __name__ == "__main__":
    unittest.main()
