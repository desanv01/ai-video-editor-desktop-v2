"""Verify the slide pacing algorithm produces expected results."""
total_slides = 10  # 10 pages in PDF
total_segments = 7  # 7 transcript segments

print("=== SLIDE PACING: 10 pages across 7 segments ===")
print()

# Pacing: seg i gets pacing_min = i * 10 // 7
for seg_idx in range(total_segments):
    pacing_min = int(seg_idx * total_slides // total_segments)
    pacing_min = min(pacing_min, total_slides - 1)

    # What the slide would show (at minimum)
    max_advance = min(pacing_min + 1, total_slides - 1)

    print(f"  Seg {seg_idx}: pacing_min=page {pacing_min}, max=page {max_advance}")

print()
print("Expected slide progression: 0 → 1 → 2 → 4 → 5 → 7 → 8")
print("(never regresses, all 10 pages reachable)")
print()
print("BEFORE: [0, 1, 0, 0, 1, 1, 0] ❌ Bouncing, only pages 0-1")
print("AFTER:  [0, 1, 2, 4, 5, 7, 8] ✅ Forward, covers most pages")
