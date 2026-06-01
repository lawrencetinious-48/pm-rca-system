#!/usr/bin/env python3
"""
Backfill script to populate `risk_score` and `sla_deadline` for existing activities.
Run once after adding the columns to the database.
"""

import sys
import logging
from datetime import timedelta

from app import (
    SLA_HOURS_CRITICAL,
    SLA_HOURS_STANDARD,
    create_app,
    extract_risk_score_from_details,
    extract_sla_deadline_from_details,
)
from model import Activity, db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

BATCH_SIZE = 1000  # commit after this many updates


def main():
    app = create_app({"SEED_SAMPLE_DATA": False})

    with app.app_context():
        query = Activity.query.filter(
            (Activity.risk_score.is_(None)) | (Activity.sla_deadline.is_(None))
        ).enable_eagerloads(False)  # reduce memory footprint

        total_scanned = 0
        total_updated = 0
        batch_updates = 0

        try:
            for activity in query.yield_per(500):
                total_scanned += 1
                changed = False

                # Risk score
                if activity.risk_score is None:
                    risk_score = extract_risk_score_from_details(activity.details)
                    if risk_score is not None:
                        activity.risk_score = risk_score
                        changed = True

                # SLA deadline
                if activity.sla_deadline is None and activity.activity_type in {"pm", "rca"}:
                    sla_deadline = extract_sla_deadline_from_details(activity.details)
                    if sla_deadline is None:
                        # Use default based on activity type
                        default_hours = SLA_HOURS_CRITICAL if activity.activity_type == "rca" else SLA_HOURS_STANDARD
                        sla_deadline = activity.created_at + timedelta(hours=default_hours)
                    activity.sla_deadline = sla_deadline
                    changed = True

                if changed:
                    total_updated += 1
                    batch_updates += 1

                # Commit in batches
                if batch_updates >= BATCH_SIZE:
                    db.session.commit()
                    logger.info(f"Committed batch: {total_updated} updates, {total_scanned} scanned")
                    batch_updates = 0

                # Progress report every 1000 scanned (even if no updates)
                if total_scanned % 1000 == 0:
                    logger.info(f"Progress: scanned {total_scanned} rows, updated {total_updated}")

            # Final commit for remaining updates
            if batch_updates > 0:
                db.session.commit()
                logger.info(f"Final commit: {total_updated} updates, {total_scanned} scanned")

            logger.info(f"Backfill completed successfully: scanned {total_scanned} activities, updated {total_updated} rows.")

        except Exception:
            logger.exception("Backfill failed, rolling back transaction.")
            db.session.rollback()
            sys.exit(1)


if __name__ == "__main__":
    main()
