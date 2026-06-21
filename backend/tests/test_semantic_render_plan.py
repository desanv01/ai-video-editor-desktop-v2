import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from db.models import SegmentAction  # noqa: E402
from services.native_semantic_compositor import _build_bounded_scene_command  # noqa: E402
from services.edit_plan_payload import update_slide_cues  # noqa: E402
from services.semantic_render_plan import build_semantic_render_plan, with_semantic_render_plan  # noqa: E402


def segment(index, start, end, text, *, topic="Lab Session", action=SegmentAction.KEEP, importance=0.6, layout_mode=None):
    return SimpleNamespace(
        id=f"segment-{index}",
        segment_index=index,
        start_time=start,
        end_time=end,
        duration=end - start,
        text=text,
        summary=text,
        topic_label=topic,
        importance_score=importance,
        segment_type="core_content",
        action=action,
        teacher_action=None,
        is_teacher_modified=False,
        layout_mode=layout_mode,
    )


def asset(asset_id, *, filename, text):
    return SimpleNamespace(
        id=asset_id,
        role="notes",
        kind="pdf_notes",
        source_type="pdf_notes",
        sync_role="structure_reference",
        status="ready",
        original_filename=filename,
        filename=filename,
        duration_seconds=0.0,
        metadata_json={
            "structure_reference": {
                "title": filename,
                "reference_role": "notes",
                "document_format": "pdf",
                "items": [
                    {
                        "index": 1,
                        "title": "Lab logistics and resources",
                        "text": text,
                    }
                ],
            }
        },
    )


class SemanticRenderPlanTests(unittest.TestCase):
    def test_matches_transcript_to_uploaded_structure_slide(self):
        video = SimpleNamespace(
            id="video-1",
            project_id="project-1",
            original_filename="lecturer.mov",
            duration_seconds=60.0,
        )
        plan = SimpleNamespace(
            plan_json={"layout_cues": []},
            original_duration=60.0,
            estimated_duration=60.0,
        )
        segments = [
            segment(
                1,
                0,
                30,
                "Today we discuss lab logistics, FPGA board borrowing, and CDAT resources.",
                topic="Lab logistics",
                importance=0.8,
            )
        ]
        assets = [
            asset(
                "notes-1",
                filename="tutorial_lab_1.pdf",
                text="Lab logistics and resources. Instructor details FPGA board borrowing, CDAT access, and lab requirements.",
            )
        ]

        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=segments,
            transcript=None,
            assets=assets,
        )

        self.assertEqual(render_plan["schema_version"], "aive.render-plan.v2")
        self.assertEqual(render_plan["renderer"]["preferred"], "ffmpeg_native_semantic")
        self.assertEqual(render_plan["renderer"]["experimental"], "revideo")
        self.assertEqual(render_plan["timeline"]["scene_count"], 2)
        self.assertEqual(
            [(scene["start_time"], scene["end_time"]) for scene in render_plan["scenes"]],
            [(0.0, 15.0), (15.0, 30.0)],
        )
        self.assertTrue(all(scene["slide_id"] == "slide-01-001" for scene in render_plan["scenes"]))
        self.assertTrue(all(scene["semantic_match"]["score"] > 0.1 for scene in render_plan["scenes"]))
        self.assertEqual(render_plan["slides"][0]["source_filename"], "tutorial_lab_1.pdf")
        self.assertTrue(render_plan["plan_hash"])

    def test_teacher_full_screen_layout_has_no_picture_in_picture(self):
        video = SimpleNamespace(id="video-layout", project_id="project-1", original_filename="lecture.mov", duration_seconds=40.0)
        plan = SimpleNamespace(
            plan_json={"layout_cues": [{
                "id": "teacher-full-slide",
                "layout": "full_screen_source",
                "start_time": 0.0,
                "end_time": 40.0,
                "source": "teacher_layout_override",
            }]},
            original_duration=40.0,
            estimated_duration=40.0,
        )
        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=[segment(0, 0, 40, "VCS compilation and simulation flow", layout_mode="pip_slide")],
            assets=[asset("notes", filename="lab.pdf", text="VCS compilation and simulation flow")],
        )

        self.assertTrue(render_plan["scenes"])
        self.assertTrue(all(scene["layout"] == "full_screen_source" for scene in render_plan["scenes"]))
        self.assertTrue(all(not scene["camera"]["enabled"] for scene in render_plan["scenes"]))
        self.assertTrue(all(scene["layout_source"] == "teacher_layout_override" for scene in render_plan["scenes"]))

    def test_unrelated_automatic_slide_cue_uses_lecturer_only(self):
        video = SimpleNamespace(id="video-low-confidence", project_id="project-1", original_filename="lecture.mov", duration_seconds=20.0)
        plan = SimpleNamespace(
            plan_json={
                "slide_cues": [{
                    "id": "weak-match",
                    "start_time": 0.0,
                    "end_time": 20.0,
                    "slide_id": "slide-01-001",
                    "slide_index": 0,
                    "confidence": 0.05,
                    "slide_relation": "unrelated",
                    "strategy": "semantic_chunk_token_match",
                }],
                "layout_cues": [],
            },
            original_duration=20.0,
            estimated_duration=20.0,
        )
        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=[segment(0, 0, 20, "unrelated welcome and housekeeping")],
            assets=[asset("notes", filename="lab.pdf", text="VCS compiler waveform and Verdi")],
        )

        self.assertIsNone(render_plan["slide_cues"][0]["slide_id"])
        self.assertTrue(all(scene["layout"] == "full_camera_source" for scene in render_plan["scenes"]))
        self.assertTrue(all(scene["camera"]["enabled"] for scene in render_plan["scenes"]))

    def test_low_confidence_related_slide_cue_is_preserved(self):
        video = SimpleNamespace(id="video-related-low-score", project_id="project-1", original_filename="lecture.mov", duration_seconds=20.0)
        plan = SimpleNamespace(
            plan_json={
                "slide_cues": [{
                    "id": "related-match",
                    "start_time": 0.0,
                    "end_time": 20.0,
                    "slide_id": "slide-01-001",
                    "slide_index": 0,
                    "confidence": 0.05,
                    "slide_relation": "related",
                    "strategy": "deepseek_semantic_rerank",
                }],
                "layout_cues": [],
            },
            original_duration=20.0,
            estimated_duration=20.0,
        )
        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=[segment(0, 0, 20, "VCS compiler waveform and Verdi")],
            assets=[asset("notes", filename="lab.pdf", text="VCS compiler waveform and Verdi")],
        )

        self.assertIsNotNone(render_plan["slide_cues"][0]["slide_id"])

    def test_uncovered_timeline_range_is_explicit_lecturer_only_and_beats_ai_pip(self):
        video = SimpleNamespace(id="video-gap", project_id="project-1", original_filename="lecture.mov", duration_seconds=20.0)
        plan = SimpleNamespace(
            plan_json={
                "slide_cues": [{
                    "id": "relevant-slide",
                    "start_time": 10.0,
                    "end_time": 20.0,
                    "slide_index": 0,
                    "confidence": 0.9,
                    "source": "agent4_anchor_planner",
                }],
                "layout_cues": [{
                    "id": "ai-pip",
                    "layout": "picture_in_picture",
                    "start_time": 0.0,
                    "end_time": 20.0,
                    "source": "agent5_auto_layout",
                }],
            },
            original_duration=20.0,
            estimated_duration=20.0,
        )

        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=[segment(0, 0, 20, "welcome first, then VCS simulation flow")],
            assets=[asset("notes", filename="lab.pdf", text="VCS simulation flow")],
        )

        self.assertIsNone(render_plan["slide_cues"][0]["slide_id"])
        self.assertEqual(render_plan["slide_cues"][0]["cue_type"], "lecturer_only")
        self.assertEqual(render_plan["scenes"][0]["layout"], "full_camera_source")
        self.assertEqual(render_plan["scenes"][0]["layout_source"], "semantic_lecturer_only")
        self.assertEqual(render_plan["scenes"][-1]["layout"], "picture_in_picture")

    def test_slide_cue_update_preserves_ai_sources_for_untouched_cues(self):
        payload = {
            "original_duration": 20.0,
            "slide_cues": [],
        }
        updated = update_slide_cues(payload, [
            {"id": "manual", "start_time": 0, "end_time": 10, "slide_index": None, "source": "teacher_slide_override"},
            {"id": "ai", "start_time": 10, "end_time": 20, "slide_index": 1, "source": "agent4_anchor_planner"},
        ])

        self.assertEqual(updated["slide_cues"][0]["source"], "teacher_slide_override")
        self.assertEqual(updated["slide_cues"][1]["source"], "agent4_anchor_planner")

    def test_semantic_chunks_match_vcs_waveform_and_login_pages(self):
        video = SimpleNamespace(id="video-test14", project_id="project-1", original_filename="lecture.mov", duration_seconds=60.0)
        plan = SimpleNamespace(plan_json={"layout_cues": []}, original_duration=60.0, estimated_duration=60.0)
        notes = asset("notes", filename="tutorial.pdf", text="placeholder")
        notes.metadata_json["structure_reference"]["items"] = [
            {"index": 1, "title": "VCS Simulation Flow", "text": "compile design using VCS then run simv simulation executable"},
            {"index": 2, "title": "Waveform and Verdi", "text": "open VPD waveform results in Verdi and analyze signals"},
            {"index": 3, "title": "Environment Login", "text": "login account setup environment access and CDAT credentials"},
        ]
        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=[
                segment(0, 0, 20, "compile the design using VCS and run the simv executable", topic="VCS flow"),
                segment(1, 20, 40, "open the VPD waveform in Verdi and inspect the signals", topic="Waveform"),
                segment(2, 40, 60, "login with your account and configure the environment credentials", topic="Login"),
            ],
            assets=[notes],
        )
        titles = [scene["slide_title"] for scene in render_plan["scenes"]]
        self.assertEqual(titles, ["VCS Simulation Flow", "Waveform and Verdi", "Environment Login"])

    def test_plan_hash_is_stable_and_changes_with_teacher_layout(self):
        video = SimpleNamespace(id="video-hash", project_id="project-1", original_filename="lecture.mov", duration_seconds=20.0)
        segment_list = [segment(0, 0, 20, "VCS simulation flow")]
        assets = [asset("notes", filename="lab.pdf", text="VCS simulation flow")]
        plan = SimpleNamespace(plan_json={"layout_cues": []}, original_duration=20.0, estimated_duration=20.0)
        first = build_semantic_render_plan(video=video, plan=plan, segments=segment_list, assets=assets)
        second = build_semantic_render_plan(video=video, plan=plan, segments=segment_list, assets=assets)
        changed_plan = SimpleNamespace(
            plan_json={"layout_cues": [{"id": "manual", "layout": "full_camera_source", "start_time": 0, "end_time": 20, "source": "teacher_layout_override"}]},
            original_duration=20.0,
            estimated_duration=20.0,
        )
        changed = build_semantic_render_plan(video=video, plan=changed_plan, segments=segment_list, assets=assets)
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        self.assertNotEqual(first["plan_hash"], changed["plan_hash"])

    def test_native_scene_command_has_no_unbounded_split_graph(self):
        command = _build_bounded_scene_command(
            source_video_path="source.mov",
            slide_path="slide.png",
            output_path="output.mp4",
            scene={"duration_seconds": 10.0, "source_start_time": 20.0, "source_end_time": 30.0, "layout": "picture_in_picture"},
            output_width=1920,
            output_height=1080,
            fps=30,
            video_bitrate="10M",
            audio_bitrate="256k",
        )
        self.assertEqual(command.count("source.mov"), 1)
        graph = command[command.index("-filter_complex") + 1]
        self.assertNotIn("split=", graph)
        self.assertNotIn("asplit=", graph)
        self.assertIn("20.000", command)

    def test_native_scene_command_applies_circle_camera_mask(self):
        command = _build_bounded_scene_command(
            source_video_path="source.mov",
            slide_path="slide.png",
            output_path="output.mp4",
            scene={
                "duration_seconds": 10.0,
                "source_start_time": 0.0,
                "layout": "picture_in_picture",
                "camera": {"shape": "circle", "size": "small", "corner": "top_left"},
            },
            output_width=1920,
            output_height=1080,
            fps=30,
            video_bitrate="10M",
            audio_bitrate="256k",
        )

        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("format=rgba", graph)
        self.assertIn("geq=", graph)
        self.assertIn("overlay=", graph)

    def test_native_scene_command_applies_transition_from_previous_scene(self):
        with tempfile.TemporaryDirectory(prefix="aive-transition-command-") as temp_dir:
            previous = Path(temp_dir) / "previous.mp4"
            previous.touch()
            command = _build_bounded_scene_command(
                source_video_path="source.mov",
                slide_path="slide.png",
                output_path="output.mp4",
                scene={
                    "duration_seconds": 10.0,
                    "source_start_time": 10.0,
                    "layout": "picture_in_picture",
                    "transition": {"type": "crossfade", "duration_seconds": 0.35},
                },
                output_width=1920,
                output_height=1080,
                fps=30,
                video_bitrate="10M",
                audio_bitrate="256k",
                previous_scene_path=str(previous),
                previous_scene_duration=10.0,
            )

            graph = command[command.index("-filter_complex") + 1]
            self.assertIn("xfade=transition=fade", graph)
            self.assertIn("duration=0.350", graph)

    def test_persists_render_plan_inside_edit_payload(self):
        payload = with_semantic_render_plan({"schema_version": "phase6.edit-plan.v2"}, {"schema_version": "aive.render-plan.v2", "plan_hash": "abc", "timeline": {"scene_count": 3}})

        self.assertEqual(payload["render_plan"]["schema_version"], "aive.render-plan.v2")
        self.assertEqual(payload["metadata"]["render_plan_scene_count"], 3)
        self.assertEqual(payload["metadata"]["render_plan_hash"], "abc")


if __name__ == "__main__":
    unittest.main()
