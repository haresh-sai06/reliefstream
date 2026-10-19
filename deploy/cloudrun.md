# Deploying to Google Cloud Run

Not deployed yet (no cloud credentials were available when this was written). These are the exact steps.

```bash
PROJECT=your-gcp-project
REGION=asia-south1
gcloud config set project $PROJECT
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com secretmanager.googleapis.com

# store the LLM key as a secret (Groq / OpenRouter / Gemini OpenAI-compatible key)
printf '%s' "$LLM_API_KEY" | gcloud secrets create reliefstream-llm-key --data-file=-

# build from source with the repo Dockerfile and deploy
gcloud run deploy reliefstream \
  --source . --region $REGION --allow-unauthenticated \
  --set-env-vars LLM_BASE_URL=https://api.groq.com/openai/v1,LLM_MODEL=llama-3.3-70b-versatile,DATABASE_PATH=/tmp/reliefstream.db \
  --set-secrets LLM_API_KEY=reliefstream-llm-key:latest \
  --min-instances 0 --max-instances 1
```

Dashboard: `https://<service-url>/ui` · API docs: `https://<service-url>/docs`.

Notes
- `--max-instances 1` because the SSE event bus and SQLite DB are in-process. For more than one instance, move storage to Postgres (Cloud SQL) and the event bus to Redis/PubSub.
- `/tmp` on Cloud Run is in-memory and wiped on restart; mount a Cloud Storage FUSE volume or use Cloud SQL for durability.
