#!/usr/bin/env python3
"""One-off script to generate AI suggestions for recent activities.

Usage: set environment variables for Flask app as usual, then run:

    python scripts/generate_ai_suggestions.py --limit 50

This will call the Celery task logic synchronously via the app context.
"""
import argparse
from app_main import create_app
from model import db
from pm_app.services.llm_summarizer import is_llm_enabled, generate_activity_suggestion
from model import Activity, AiSuggestion

parser = argparse.ArgumentParser()
parser.add_argument("--limit", type=int, default=50)
parser.add_argument("--activity", type=int, default=None)
args = parser.parse_args()

app = create_app()
with app.app_context():
    if not is_llm_enabled():
        print("LLM not enabled; set OPENAI_API_KEY and OPENAI_ACTIVITY_SUGGESTIONS to enable.")
        raise SystemExit(0)
    query = Activity.query
    if args.activity:
        query = query.filter_by(id=args.activity)
    else:
        query = query.order_by(Activity.created_at.desc()).limit(args.limit)
    generated = 0
    for activity in query:
        existing = AiSuggestion.query.filter_by(activity_id=activity.id).first()
        if existing:
            continue
        try:
            suggestion = generate_activity_suggestion(activity.details or "", sla_state=None, risk_level=None, activity_type=activity.activity_type)
            if suggestion and suggestion.strip():
                rec = AiSuggestion(activity_id=activity.id, suggestion_text=suggestion.strip(), source="ai_llm", provider="openai")
                db.session.add(rec)
                db.session.commit()
                generated += 1
                print(f"Generated suggestion for activity {activity.id}")
        except Exception as e:
            db.session.rollback()
            print(f"Failed for {activity.id}: {e}")
    print(f"Done — generated {generated} suggestions")
