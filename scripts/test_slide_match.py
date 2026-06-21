"""Test Agent 4 slide matching to diagnose desynchronization."""
import asyncio, sys
sys.path.insert(0, "/app")
from rag.vector_store import rag_service

segments = [
    (0, "Okay, Assalamualaikum and good morning. So I hope that everyone is here already for today class. So far we have about 52 students maybe later we join the sessions. So I will start the sessions for today where as mentioned earlier today we are going to start the lab sessions", "Greeting + Lab intro"),
    (1, "Synopsys VCS and number two is more on the design compiler, how we can synthesize your design very low cost to the netlist which later we are going to do the physical design which is not covered in this course. And then finally you are going to do the FPGA board", "VCS + Design Compiler overview"),
    (2, "please arrange among your group members only one person access at one time to using your group account. And then for that server you can use to run this Synopsys VCS software for simulations", "Server access instructions"),
    (3, "the half header codes that we used before in our model in our first few classes. Or I think I already uploaded the half header codes so that you can use it to test this Synopsys VCS", "Using header codes to test VCS"),
    (4, "So this is the flow when we are running the simulations using Synopsys VCS tools where, as usual, you need to have the codes. You need to have the codes. You can see here the Verilog codes are for example any v codes", "VCS simulation flow explanation"),
    (5, "simulations. So later I am going to explain to you the codes, the command line, the syntax for you to run the simulations using VCS. So this is the flow when you are running the simulations", "More VCS flow details"),
    (6, "your group leader, jot down the login and the password information. And I think for those who have gone through EEE301, the other courses digital IC design", "Login info for students"),
]

async def test():
    print("=== PURE QDRANT MATCHES (top 2 per segment, no order constraint) ===")
    for seg_idx, text, desc in segments:
        results = await rag_service.search(
            query=text[:200],
            top_k=2,
            source_type="slide_page",
            score_threshold=0.1,
        )
        if results:
            parts = []
            for r in results:
                meta = r.get("metadata", {})
                parts.append(f"page={meta.get('page_index', '?')} (score={r.get('score', 0):.3f})")
            match_str = " | ".join(parts)
        else:
            match_str = "NO MATCH"
        print(f"  Seg {seg_idx} ({desc[:35]}): {match_str}")

asyncio.run(test())
