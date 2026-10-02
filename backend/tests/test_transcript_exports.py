import csv
import io
import json
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.export_artifacts import artifact_records, create_artifact_bundle, build_generated_evidence_index
from services.transcript_exports import (
    TRANSCRIPT_EXPORT_FORMATS,
    TranscriptExportUnavailable,
    format_transcript_export,
    transcript_download_filename,
    transcript_export_availability,
    transcript_export_catalog,
    write_transcript_artifacts,
)


class TranscriptExportTests(unittest.TestCase):
    def setUp(self):
        self.video = SimpleNamespace(id="video-1", original_filename="Kuliah.Minggu.1.mp4", duration_seconds=100.0)
        self.transcript = SimpleNamespace(
            id="transcript-1", full_text='Um, selamat pagi.\n\n“Reuse”, bukan ulang! 中文',
            language="ms", asr_provider="whisper", word_count=9, created_at=datetime(2026, 10, 1),
            words_json=[{"word": "Um,", "start": 12.4, "end": 12.9}],
            segments_json=[
                {"text": "Um, selamat pagi.", "start": 12.4, "end": 18.9, "speaker": "Speaker 1"},
                {"text": '“Reuse”, bukan ulang!\n中文', "start": 75.0, "end": 82.1},
            ], speakers_json=[{"label": "Speaker 1", "segments_count": 1}],
        )

    def test_plain_text_preserves_all_stored_wording_and_whitespace(self):
        content = format_transcript_export(self.video, self.transcript, "txt")
        self.assertEqual(content, self.transcript.full_text)
        self.assertEqual(content.encode("utf-8").decode("utf-8"), self.transcript.full_text)

    def test_timestamped_text_uses_source_time_and_only_existing_speakers(self):
        content = format_transcript_export(self.video, self.transcript, "timestamped_txt")
        self.assertIn("[00:00:12.400 → 00:00:18.900] Speaker 1\nUm, selamat pagi.", content)
        self.assertIn("[00:01:15.000 → 00:01:22.100]\n“Reuse”, bukan ulang!", content)
        self.assertEqual(content.count("Speaker 1"), 1)

    def test_json_preserves_raw_provider_data_and_identifies_original_timeline(self):
        data = json.loads(format_transcript_export(self.video, self.transcript, "json"))
        self.assertEqual(data["timeline"], "original_recording")
        self.assertEqual(data["full_text"], self.transcript.full_text)
        self.assertEqual(data["words"], self.transcript.words_json)
        self.assertEqual(data["segments"], self.transcript.segments_json)
        self.assertEqual(data["speakers"], self.transcript.speakers_json)
        self.assertEqual(data["asr_provider"], "whisper")
        self.assertEqual(data["text_source"], "stored_full_text")
        self.assertNotIn("file_path", data["video"])

    def test_csv_round_trips_punctuation_newlines_and_source_times(self):
        content = format_transcript_export(self.video, self.transcript, "csv")
        rows = list(csv.DictReader(io.StringIO(content)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["text"], self.transcript.segments_json[1]["text"])
        self.assertEqual(rows[1]["start_seconds"], "75.0")
        self.assertEqual(rows[1]["speaker"], "")

    def test_text_only_transcript_keeps_text_and_json_available(self):
        self.transcript.segments_json = []
        self.transcript.words_json = []
        availability = transcript_export_availability(self.transcript)
        self.assertTrue(availability["txt"]["available"])
        self.assertTrue(availability["json"]["available"])
        self.assertFalse(availability["csv"]["available"])
        self.assertFalse(availability["timestamped_txt"]["available"])
        with self.assertRaisesRegex(TranscriptExportUnavailable, "timestamps"):
            format_transcript_export(self.video, self.transcript, "timestamped_txt")

    def test_invalid_or_missing_timing_is_never_invented(self):
        self.transcript.segments_json.extend([
            {"text": "Unknown timing", "start": None, "end": 5},
            {"text": "Backwards", "start": 10, "end": 9},
            {"text": "Nonfinite", "start": "NaN", "end": "Infinity"},
            {"text": "Negative", "start": -2, "end": 0},
        ])
        content = format_transcript_export(self.video, self.transcript, "timestamped_txt")
        self.assertEqual(content.count("[Timing unavailable]"), 4)
        rows = list(csv.DictReader(io.StringIO(format_transcript_export(self.video, self.transcript, "csv"))))
        self.assertTrue(all(row["start_seconds"] == row["end_seconds"] == "" for row in rows[2:]))
        self.assertTrue(all(row["timing_source"] == "unavailable" for row in rows[2:]))

    def test_provider_alias_times_are_supported_without_estimates(self):
        self.transcript.segments_json = [{"text": "Hello", "start_time": 3600.9996, "end_time": 3602}]
        content = format_transcript_export(self.video, self.transcript, "timestamped_txt")
        self.assertIn("[01:00:01.000 → 01:00:02.000]", content)

    def test_legacy_records_can_export_stored_segments_or_words(self):
        self.transcript.full_text = None
        data = json.loads(format_transcript_export(self.video, self.transcript, "json"))
        self.assertEqual(data["text_source"], "stored_segments")
        self.assertIn("Um, selamat pagi.", data["text"])
        self.transcript.segments_json = []
        self.assertEqual(format_transcript_export(self.video, self.transcript, "txt"), "Um,")
        data = json.loads(format_transcript_export(self.video, self.transcript, "json"))
        self.assertEqual(data["text_source"], "stored_words")

    def test_missing_and_empty_transcripts_are_unavailable(self):
        for transcript in [None, SimpleNamespace(full_text=" ", words_json=[], segments_json=[])]:
            self.assertTrue(all(not item["available"] for item in transcript_export_availability(transcript).values()))
            with self.assertRaises(TranscriptExportUnavailable):
                format_transcript_export(self.video, transcript, "txt")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            format_transcript_export(self.video, self.transcript, "pdf")

    def test_catalog_is_available_without_rendered_files(self):
        catalog = transcript_export_catalog(self.video.id, self.transcript)
        self.assertEqual(len(catalog), 4)
        self.assertTrue(all(item["available"] for item in catalog.values()))
        self.assertIn("format=txt", catalog["original_transcript_txt"]["path"])
        self.assertFalse(catalog["original_transcript_txt"].get("reason"))

    def test_bundle_and_evidence_index_include_exact_download_contents(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_transcript_artifacts(self.video, self.transcript, folder)
            records = artifact_records(paths)
            self.assertTrue(all(record["available"] for record in records))
            self.assertTrue(all(record["label"].startswith("Original transcript") for record in records))
            index = build_generated_evidence_index(records)
            self.assertIn("original_transcript_txt", json.dumps(index))
            bundle_path = str(Path(folder) / "bundle.zip")
            create_artifact_bundle(bundle_path, records)
            with zipfile.ZipFile(bundle_path) as bundle:
                self.assertEqual(len(bundle.namelist()), 4)
                for format_name, (kind, _suffix, _media_type, _label) in TRANSCRIPT_EXPORT_FORMATS.items():
                    bundled = bundle.read(Path(paths[kind]).name).decode("utf-8")
                    self.assertEqual(bundled, format_transcript_export(self.video, self.transcript, format_name))

    def test_materializing_refreshes_changed_text_and_removes_unavailable_stale_files(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = write_transcript_artifacts(self.video, self.transcript, folder)
            self.transcript.full_text = "Updated transcript"
            write_transcript_artifacts(self.video, self.transcript, folder)
            self.assertEqual(Path(paths["original_transcript_txt"]).read_text(encoding="utf-8"), "Updated transcript")
            self.transcript.segments_json = []
            refreshed = write_transcript_artifacts(self.video, self.transcript, folder)
            self.assertIsNone(refreshed["original_transcript_timestamped_txt"])
            self.assertFalse(Path(paths["original_transcript_timestamped_txt"]).exists())
            self.assertFalse(Path(paths["original_transcript_segments_csv"]).exists())

    def test_download_names_handle_source_paths_and_unicode(self):
        self.assertEqual(transcript_download_filename(self.video, "txt"), "Kuliah.Minggu.1_original_transcript.txt")
        self.video.original_filename = 'C:\\uploads\\Kuliah 中文\r\n.mp4'
        filename = transcript_download_filename(self.video, "json")
        self.assertEqual(filename, "Kuliah 中文___original_transcript.json")
        self.assertNotIn("\\", filename)
        self.assertNotIn("\n", filename)


if __name__ == "__main__":
    unittest.main()
