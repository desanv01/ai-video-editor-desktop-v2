## AIVE Revideo Bridge

This directory contains the commercial-safe Revideo compositor path.

Inputs:
- `AIVE_RENDER_PLAN_PATH`: absolute path to `render_plan.json`
- `AIVE_SOURCE_VIDEO_URL` or `AIVE_SOURCE_VIDEO_PATH`: lecturer/source video
- `AIVE_RENDER_OUTPUT`: output MP4 path
- `AIVE_RENDER_WORKERS`: optional worker count

Run from `desktop`:

```powershell
$env:AIVE_RENDER_PLAN_PATH="C:\path\render_plan.json"
$env:AIVE_SOURCE_VIDEO_PATH="C:\path\lecturer.mp4"
$env:AIVE_RENDER_OUTPUT="C:\path\output.mp4"
npm run render:revideo
```

The app-owned `render_plan.json` remains the source of truth. Revideo only
renders the plan; it does not decide the teaching timeline.
