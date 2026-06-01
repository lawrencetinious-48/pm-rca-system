LLM-backed summarizer and activity suggestions

Overview

This project includes an opt-in LLM-backed summarizer and per-activity AI suggestion pipeline. The integration is designed to be safe and additive: nothing changes unless you enable the LLM via environment variables.

Environment variables

- `OPENAI_API_KEY`: (required to enable LLM) Bearer API key for OpenAI-compatible providers.
- `OPENAI_API_BASE`: Optional. Defaults to `https://api.openai.com/v1`. Use to point to Azure OpenAI or a proxy.
- `OPENAI_API_MODEL`: Optional. Default `gpt-3.5-turbo`.
- `OPENAI_API_TIMEOUT`: Optional request timeout seconds. Default `15`.
- `OPENAI_ACTIVITY_SUGGESTIONS`: Set to `1`, `true`, or `yes` to allow activity suggestions from the LLM.

What was added

- `model.AiSuggestion` table: stores persisted AI suggestions (no schema change to existing `Activity` table required).
- `pm_app/tasks.py::generate_activity_suggestions` Celery task: generates and saves suggestions for recent activities (no-op if LLM disabled).
- `scripts/generate_ai_suggestions.py`: one-shot script to generate suggestions without running Celery.
- `/api/activity/<id>/suggestion`: now returns persisted suggestion (if present) with `source` field; falls back to manual/heuristic suggestion.
- `templates/desk_activities.html`: UI updated to show suggestion source and client fetch will display API-provided suggestion if server-side row lacks one.

Usage

1. Enable LLM by setting `OPENAI_API_KEY` and `OPENAI_ACTIVITY_SUGGESTIONS=1` in your environment.
2. Option A (Celery): Start Celery worker and call `generate_activity_suggestions.delay()` or schedule periodically.
3. Option B (one-shot): Run the script:

```bash
python scripts/generate_ai_suggestions.py --limit 50
```

Notes and safety

- The LLM is opt-in; when disabled the system falls back to existing heuristic and embedded recommendations.
- Suggestions are stored separately in `ai_suggestions` so existing Activity schema is unchanged.
- UI shows a `source` label so reviewers can see whether a suggestion was human-provided or AI-generated.

If you'd like, I can:
- Add an admin UI to review and bulk-generate suggestions.
- Add a migration (Alembic) to register the `ai_suggestions` table in your database migration history.
- Wire suggestion generation into an approval workflow (e.g., generate when a new Activity is created).

Tell me which next step you prefer.
