"""Test LLM slide matcher inside Docker container."""
import asyncio, sys
sys.path.insert(0, "/app")

from config import settings
from services.llm import llm_service

segments = [
    type("Seg", (), {"segment_index": 0, "start_time": 2.1, "end_time": 72.0, "topic_label": "Lab Introduction", "text": "Okay, Assalamualaikum and good morning. So I hope that everyone is here already for today class. So I will start the sessions for today where we are going to start the lab sessions."}),
    type("Seg", (), {"segment_index": 1, "start_time": 72.0, "end_time": 142.0, "topic_label": "Lab Topics", "text": "Synopsys VCS and number two is more on the design compiler, how we can synthesize your design very low cost to the netlist."}),
    type("Seg", (), {"segment_index": 2, "start_time": 142.0, "end_time": 209.6, "topic_label": "Server Access", "text": "please arrange among your group members only one person access at one time to using your group account."}),
    type("Seg", (), {"segment_index": 3, "start_time": 209.6, "end_time": 277.8, "topic_label": "Simulation", "text": "the half header codes that we used before in our model. Or I think I already uploaded the half header codes so that you can use it to test this Synopsys VCS."}),
    type("Seg", (), {"segment_index": 4, "start_time": 277.8, "end_time": 342.4, "topic_label": "VCS Flow", "text": "So this is the flow when we are running the simulations using Synopsys VCS tools where you need to have the codes."}),
]

slides = [
    {"page_index": 0, "text": "Lab module 1 : Simulation using Synopsys VCS. Associate Prof. Dr. Bakhtiar Affendi Bin Rosdi"},
    {"page_index": 1, "text": "Learning outcomes: simulate Verilog codes using VCS, visualize waveform using Verdi."},
    {"page_index": 2, "text": "Setting the environment. After login to server using Kerio and VNC, open terminal, check current directory."},
    {"page_index": 3, "text": "VCS compilation and simulation flow. Verilog Code -> Compilation -> VCS -> simv -> Simulation -> VPD -> Debug."},
    {"page_index": 4, "text": "Compile using VCS: cd lab1, vcs -R -gui -debug_access+all -kdb half_adder.v. Make sure which vcs was successful."},
    {"page_index": 5, "text": "Simulate using VCS: ./simv. After simulation, check waveform using Verdi."},
    {"page_index": 6, "text": "Use header codes provided to test your design. Uploaded to e-learning for students."},
    {"page_index": 7, "text": "VCS Simulation Flow Diagram showing compilation steps and simulation outputs."},
    {"page_index": 8, "text": "Verification and Waveforms. Visualize waveform to verify if design meets specifications."},
    {"page_index": 9, "text": "Login and Account info: group leader jot down login and password. Server account for each group."},
]

SYSTEM = """You are matching lecture transcript segments to slides. For each segment, pick ONE slide that best matches what the lecturer is discussing.

Rules: multiple segments can map to same slide. Can go back to earlier slides. Can jump forward. Use slide TEXT content, not just titles. All slide indices must exist (0-N). Return valid JSON only.

Output: {"mappings": [{"segment_index": 0, "slide_index": 0, "reason": "brief"}, ...]}"""

async def test():
    se = [f"[{s.segment_index}] {s.start_time:.0f}-{s.end_time:.0f}s {s.topic_label}: {(s.text or '')[:200]}" for s in segments]
    sl = [f"Slide [{i}]: {s['text'][:200]}" for i, s in enumerate(slides)]

    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"SEGMENTS:\n" + "\n".join(se) + f"\n\nSLIDES:\n" + "\n".join(sl)},
    ]

    print("Calling LLM (V4 Pro)...")
    try:
        r = await llm_service.chat_json(msgs, model=settings.AGENT5_MODEL, temperature=0.1, max_tokens=4096)
        mp = r.get("mappings", [])
        print(f"\n✅ {len(mp)} mappings:")
        for m in mp:
            print(f"  Seg{m.get('segment_index')}→Slide{m.get('slide_index')}: {m.get('reason','')[:60]}")
    except Exception as e:
        print(f"\n❌ FAILED: {e}")

asyncio.run(test())
