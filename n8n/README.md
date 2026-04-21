# n8n Workflow Setup — Outer Automation Layer

## Overview

n8n handles the **outer automation** layer of the AI Video Editing pipeline:
- Webhook trigger when desktop app uploads a video
- Status polling every 15 seconds during processing
- Notifications when processing completes or fails
- (Optional) Email/Slack notifications to the teacher
- (Optional) Batch scheduling for processing multiple videos

LangGraph handles the **inner agent coordination** (the actual AI pipeline).

## Quick Setup

### 1. Access n8n

After `docker-compose up -d`, open:
```
http://localhost:5678
Username: admin
Password: admin
```

### 2. Import the Workflow

1. In n8n, click **Add workflow** → **Import from file**
2. Select `n8n/workflows/pipeline_monitor.json`
3. The workflow will appear with all nodes pre-configured

### 3. Activate the Workflow

1. Click the **Active** toggle in the top-right corner
2. The webhook is now listening at:
   ```
   http://localhost:5678/webhook/video-uploaded
   ```

### 4. Test the Webhook

```bash
curl -X POST http://localhost:5678/webhook/video-uploaded \
  -H "Content-Type: application/json" \
  -d '{"video_id": "YOUR_VIDEO_UUID"}'
```

The workflow will:
1. Start polling the FastAPI backend for processing status
2. Wait 15 seconds between polls
3. When status = `awaiting_review`: fetch the quality report and format a success message
4. When status = `failed`: format an error message

## Workflow Nodes

```
[Webhook Trigger] → [Check Status] → [Is Ready?] → YES → [Get Report] → [Success]
                          ↑                        → NO  → [Wait 15s] → [loop back]
                          |              [Is Failed?] → YES → [Format Error] → [Failure]
                          |                           → NO  → [Wait 15s] → [loop back]
                          └────────────────────────────────────────────┘
```

## Adding Email Notifications

To get email when processing completes:

1. Add an **Email (SMTP)** node after "Format Success Message"
2. Configure your SMTP settings (Gmail, Outlook, etc.)
3. Set the subject: `Video Processing Complete`
4. Set the body: `{{ $json.message }}`

## Adding Slack Notifications

1. Add a **Slack** node after "Format Success Message"
2. Connect your Slack workspace
3. Select the channel to post to
4. Set the message: `{{ $json.message }}`

## Connecting to the Desktop App

The desktop app (Tauri) can trigger n8n in two ways:

**Option A: Direct n8n webhook** (simpler)
- After uploading to FastAPI, the desktop app also POSTs to n8n's webhook
- n8n handles the monitoring and notification

**Option B: FastAPI triggers n8n** (decoupled)
- The FastAPI background task handler calls the n8n webhook
- Add this to `_process_video_bg()`:
  ```python
  import httpx
  async with httpx.AsyncClient() as client:
      await client.post("http://n8n:5678/webhook/video-uploaded",
                        json={"video_id": video_id})
  ```

## Batch Processing Workflow

For processing multiple videos (e.g., all recordings from a week):

1. Create a new n8n workflow with a **Schedule Trigger** (e.g., every night at 2 AM)
2. Add an **HTTP Request** node to call `GET /api/v1/videos?status=uploaded`
3. Add a **Split In Batches** node to process one video at a time
4. Call `POST /api/v1/videos/{id}/process` for each video
5. Add a final **Email** node summarizing the batch results
