"""
API routes for PM/RCA system.
Provides REST endpoints for consumables, activities, and dashboard counts.
"""

from flask import jsonify, request, current_app, abort
from flask_login import current_user, login_required

_MAX_SEARCH_LEN = 100
_VALID_ROLES = {"developer", "staff", "technician", "manager", "general_manager"}


def _err(code: str, message: str, status: int):
    """Return a consistent JSON error envelope."""
    return jsonify({"status": "error", "code": code, "message": message}), status


def _create_limiter(limiter):
    if limiter is not None:
        return limiter.limit
    return lambda spec: (lambda f: f)


def _serialize_consumable(c):
    return {
        'id': c.id,
        'site_id': c.site_id,
        'site_name': c.site_name,
        'description': c.description,
        'created_by': c.created_by,
        'location': c.location,
        'signage_image_url': c.signage_image_url,
        'screenshot_url': c.screenshot_url,
        'before_usage_image_url': c.before_usage_image_url,
        'is_approved': c.is_approved,
        'approved_by': c.approved_by,
        'approved_at': c.approved_at.isoformat() if c.approved_at else None,
        'treatment_given': c.treatment_given,
        'review_notes': c.review_notes,
        'created_at': c.created_at.isoformat(),
    }


def _register_consumable_routes(app, consumable_model, db, normalize_role, limit):
    @app.route('/api/consumables/', methods=['GET'])
    @login_required
    @limit('200 per hour')
    def api_get_consumables():
        site_id = (request.args.get('site_id') or '')[:_MAX_SEARCH_LEN]
        site_name = (request.args.get('site_name') or '')[:_MAX_SEARCH_LEN]
        search = (request.args.get('q') or '')[:_MAX_SEARCH_LEN]
        query = consumable_model.query
        if site_id:
            query = query.filter(consumable_model.site_id.ilike(f'%{site_id}%'))
        if site_name:
            query = query.filter(consumable_model.site_name.ilike(f'%{site_name}%'))
        if search:
            query = query.filter(consumable_model.description.ilike(f'%{search}%'))

        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(max(1, request.args.get('per_page', 10, type=int)), 100)
        results = query.order_by(consumable_model.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'status': 'ok',
            'total': results.total,
            'page': results.page,
            'per_page': results.per_page,
            'items': [_serialize_consumable(c) for c in results.items],
        })

    @app.route('/api/consumables/<int:item_id>/', methods=['GET'])
    @login_required
    @limit('300 per hour')
    def api_consumable_detail(item_id):
        c = db.session.get(consumable_model, item_id)
        if c is None:
            abort(404)
        return jsonify({'status': 'ok', **_serialize_consumable(c)})

    @app.route('/api/consumables/', methods=['POST'])
    @login_required
    @limit('60 per hour')
    def api_create_consumable():
        if normalize_role(current_user.role) != 'developer':
            return _err('FORBIDDEN', 'Your role cannot create consumables.', 403)

        payload = request.get_json(silent=True) or {}
        required = ['site_id', 'site_name', 'description']
        if not all((payload.get(key) or '').strip() for key in required):
            return _err('VALIDATION_ERROR', 'site_id, site_name and description are required.', 400)

        description = payload.get('description', '').strip()
        if len(description) > 2000:
            return _err('VALIDATION_ERROR', 'description must be 2000 characters or fewer.', 400)

        site_id = payload.get('site_id', '').strip()[:20]
        site_name = payload.get('site_name', '').strip()[:120]
        location = payload.get('location')
        if location is not None:
            location = location.strip()[:200]

        c = consumable_model(
            site_id=site_id,
            site_name=site_name,
            description=description,
            created_by=current_user.email,
            location=location,
            signage_image_url=payload.get('signage_image_url'),
            screenshot_url=payload.get('screenshot_url'),
            before_usage_image_url=payload.get('before_usage_image_url'),
        )
        db.session.add(c)
        db.session.commit()
        return jsonify({'status': 'ok', 'id': c.id}), 201

    @app.route('/api/consumables/<int:item_id>/approve', methods=['POST'])
    @login_required
    @limit('120 per hour')
    def api_consumable_approve(item_id):
        if normalize_role(current_user.role) not in ('staff', 'manager', 'general_manager'):
            current_app.logger.warning(
                'Forbidden approve attempt: user=%r role=%r normalized=%r item=%r',
                getattr(current_user, 'email', None),
                getattr(current_user, 'role', None),
                normalize_role(getattr(current_user, 'role', None)),
                item_id,
            )
            return _err('FORBIDDEN', 'Your role cannot approve consumables.', 403)

        c = db.session.get(consumable_model, item_id)
        if c is None:
            abort(404)
        payload = request.get_json(silent=True) or {}
        current_app.logger.info('Approve payload: user=%r item=%r payload_keys=%r', getattr(current_user, 'email', None), item_id, list(payload.keys()))

        treatment_given = (payload.get('treatment_given') or '').strip()
        review_notes = (payload.get('review_notes') or '').strip()

        c.is_approved = True
        c.approved_by = getattr(current_user, 'email', None) or c.approved_by or 'unknown'
        try:
            c.approved_at = db.func.now()
        except Exception:
            # Fall back to Python-side timestamp if DB function isn't available
            from datetime import datetime

            c.approved_at = datetime.utcnow()

        if treatment_given:
            c.treatment_given = treatment_given[:500]
        if review_notes:
            c.review_notes = review_notes[:1000]

        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.exception('Failed to commit consumable approval: user=%r item=%r error=%s', getattr(current_user, 'email', None), item_id, e)
            db.session.rollback()
            return _err('DB_ERROR', 'Failed to approve consumable.', 500)

        current_app.logger.info('Consumable approved: user=%r item=%r', getattr(current_user, 'email', None), item_id)
        return jsonify({'status': 'ok', 'message': 'Consumable approved'}), 200

    @app.route('/api/consumables/<int:item_id>/reject', methods=['POST'])
    @login_required
    @limit('120 per hour')
    def api_consumable_reject(item_id):
        if normalize_role(current_user.role) not in ('staff', 'manager', 'general_manager'):
            current_app.logger.warning(
                'Forbidden reject attempt: user=%r role=%r normalized=%r item=%r',
                getattr(current_user, 'email', None),
                getattr(current_user, 'role', None),
                normalize_role(getattr(current_user, 'role', None)),
                item_id,
            )
            return _err('FORBIDDEN', 'Your role cannot reject consumables.', 403)

        c = db.session.get(consumable_model, item_id)
        if c is None:
            abort(404)
        payload = request.get_json(silent=True) or {}
        current_app.logger.info('Reject payload: user=%r item=%r payload_keys=%r', getattr(current_user, 'email', None), item_id, list(payload.keys()))

        review_notes = (payload.get('review_notes') or '').strip()
        if not review_notes:
            current_app.logger.warning('Reject attempt missing review_notes: user=%r item=%r', getattr(current_user, 'email', None), item_id)
            return _err('VALIDATION_ERROR', 'rejection reason (review_notes) is required.', 400)

        c.is_approved = False
        c.approved_by = getattr(current_user, 'email', None) or c.approved_by or 'unknown'
        try:
            c.approved_at = db.func.now()
        except Exception:
            from datetime import datetime

            c.approved_at = datetime.utcnow()
        c.review_notes = review_notes[:1000]

        try:
            db.session.commit()
        except Exception as e:
            current_app.logger.exception('Failed to commit consumable rejection: user=%r item=%r error=%s', getattr(current_user, 'email', None), item_id, e)
            db.session.rollback()
            return _err('DB_ERROR', 'Failed to reject consumable.', 500)

        current_app.logger.info('Consumable rejected: user=%r item=%r', getattr(current_user, 'email', None), item_id)
        return jsonify({'status': 'ok', 'message': 'Consumable rejected'}), 200


def _register_dashboard_routes(app, consumable_model, activity_model, limit):
    @app.route('/api/dashboard/stats', methods=['GET'])
    @login_required
    @limit('60 per minute')
    def api_dashboard_stats():
        try:
            from pm_app.legacy_helpers import HIGH_RISK_THRESHOLD
            pm_total = activity_model.query.filter(activity_model.activity_type == 'pm').count()
            pm_approved = activity_model.query.filter(activity_model.activity_type == 'pm', activity_model.is_approved.is_(True)).count()
            pm_rejected = activity_model.query.filter(activity_model.activity_type == 'pm', activity_model.approved_at.isnot(None), activity_model.is_approved.is_(False)).count()

            rca_total = activity_model.query.filter(activity_model.activity_type == 'rca').count()
            rca_approved = activity_model.query.filter(activity_model.activity_type == 'rca', activity_model.is_approved.is_(True)).count()
            rca_rejected = activity_model.query.filter(activity_model.activity_type == 'rca', activity_model.approved_at.isnot(None), activity_model.is_approved.is_(False)).count()

            consumables_total = consumable_model.query.count()
            try:
                consumables_approved = consumable_model.query.filter(consumable_model.is_approved.is_(True)).count()
                consumables_rejected = consumable_model.query.filter(consumable_model.approved_at.isnot(None), consumable_model.is_approved.is_(False)).count()
            except Exception:
                consumables_approved = 0
                consumables_rejected = 0

            try:
                high_risk_pending = activity_model.query.filter(
                    activity_model.activity_type.in_(['pm', 'rca']),
                    activity_model.approved_at.is_(None),
                    activity_model.risk_score >= HIGH_RISK_THRESHOLD,
                ).count()
            except Exception:
                high_risk_pending = 0

            total_submitted = pm_total + rca_total + consumables_total
            total_approved = pm_approved + rca_approved + consumables_approved
            total_rejected = pm_rejected + rca_rejected + consumables_rejected
            approved_reviews = activity_model.query.filter(
                activity_model.activity_type.in_(['pm', 'rca']),
                activity_model.approved_at.isnot(None),
            ).all()
            total_review_hours = 0.0
            on_time_reviews = 0
            for activity in approved_reviews:
                if activity.created_at and activity.approved_at:
                    total_review_hours += max(0.0, (activity.approved_at - activity.created_at).total_seconds() / 3600.0)
                if activity.sla_deadline and activity.approved_at and activity.approved_at <= activity.sla_deadline:
                    on_time_reviews += 1

            avg_review_hours = round(total_review_hours / len(approved_reviews), 1) if approved_reviews else 0.0
            on_time_rate = round((on_time_reviews / len(approved_reviews)) * 100, 1) if approved_reviews else 0.0
            first_time_pass_rate = round((total_approved / total_submitted) * 100, 1) if total_submitted else 0.0

            return jsonify({
                'status': 'ok',
                'pm': {'total': pm_total, 'approved': pm_approved, 'rejected': pm_rejected},
                'rca': {'total': rca_total, 'approved': rca_approved, 'rejected': rca_rejected},
                'consumables': {'total': consumables_total, 'approved': consumables_approved, 'rejected': consumables_rejected},
                'total_submitted': total_submitted,
                'total_approved': total_approved,
                'total_rejected': total_rejected,
                'on_time_rate': on_time_rate,
                'first_time_pass_rate': first_time_pass_rate,
                'avg_review_hours': avg_review_hours,
                'prioritization': {'high_risk_pending': high_risk_pending},
            })
        except Exception as e:
            return _err('dashboard_stats_error', str(e), 500)

    @app.route('/api/dashboard/sla-trends', methods=['GET'])
    @login_required
    @limit('60 per minute')
    def api_dashboard_sla_trends():
        try:
            from datetime import datetime, timedelta
            days_count = request.args.get('days', 30, type=int)
            days_count = max(7, min(days_count, 365))
            today = datetime.utcnow().date()
            days = []
            submissions = []
            pendings = []
            for i in range(days_count - 1, -1, -1):
                day = today - timedelta(days=i)
                start = datetime.combine(day, datetime.min.time())
                end = datetime.combine(day, datetime.max.time())
                total = activity_model.query.filter(
                    activity_model.created_at >= start,
                    activity_model.created_at <= end,
                    activity_model.activity_type.in_(['pm', 'rca'])
                ).count()
                pending = activity_model.query.filter(
                    activity_model.created_at >= start,
                    activity_model.created_at <= end,
                    activity_model.activity_type.in_(['pm', 'rca']),
                    activity_model.approved_at.is_(None),
                ).count()
                days.append(day.isoformat())
                submissions.append(total)
                pendings.append(pending)

            return jsonify({'status': 'ok', 'days': days, 'submissions': submissions, 'pendings': pendings})
        except Exception as e:
            return _err('sla_trends_error', str(e), 500)

    @app.route('/api/dashboard/summary', methods=['GET'])
    @login_required
    @limit('30 per minute')
    def api_dashboard_summary():
        try:
            from datetime import datetime, timedelta
            today = datetime.utcnow().date()

            def _range_counts(days_back_start, days_back_end):
                start = datetime.combine(today - timedelta(days=days_back_start), datetime.min.time())
                end = datetime.combine(today - timedelta(days=days_back_end), datetime.max.time())
                total = activity_model.query.filter(
                    activity_model.created_at >= start,
                    activity_model.created_at <= end,
                    activity_model.activity_type.in_(['pm', 'rca'])
                ).count()
                pending = activity_model.query.filter(
                    activity_model.created_at >= start,
                    activity_model.created_at <= end,
                    activity_model.activity_type.in_(['pm', 'rca']),
                    activity_model.approved_at.is_(None),
                ).count()
                return total, pending

            last_total, last_pending = _range_counts(0, 6)
            prev_total, prev_pending = _range_counts(7, 13)
            insights = []
            if prev_total > 0:
                pct = (last_total - prev_total) / prev_total * 100
                if pct >= 30:
                    insights.append('Submission volume up sharply (>30%) over previous week — review backlog and staffing.')
                elif pct <= -30:
                    insights.append('Submission volume down significantly (>30%) compared to previous week — verify field activity.')
            if last_total > 0:
                pending_ratio = (last_pending / last_total) * 100 if last_total else 0
                if pending_ratio >= 50:
                    insights.append('High pending rate: over 50% of recent submissions remain unreviewed — consider triage.')

            try:
                from pm_app.legacy_helpers import HIGH_RISK_THRESHOLD
                high_risk_pending = activity_model.query.filter(
                    activity_model.activity_type.in_(['pm', 'rca']),
                    activity_model.approved_at.is_(None),
                    activity_model.risk_score >= HIGH_RISK_THRESHOLD,
                ).count()
            except Exception:
                high_risk_pending = 0
            if high_risk_pending > 0:
                insights.insert(0, f'{high_risk_pending} high‑risk unreviewed items — prioritize triage and escalation.')

            if not insights:
                insights = ['Trends stable: submission and pending rates are within expected ranges.']

            return jsonify({'status': 'ok', 'insights': insights[:3]})
        except Exception as e:
            return _err('dashboard_summary_error', str(e), 500)


def _register_activity_routes(app, activity_model, limit):
    @app.route('/api/activities/', methods=['GET'])
    @login_required
    @limit('200 per hour')
    def api_activities():
        q = activity_model.query
        activity_type = (request.args.get('activity_type') or '')[:20]
        if activity_type:
            q = q.filter_by(activity_type=activity_type)

        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(max(1, request.args.get('per_page', 10, type=int)), 100)
        results = q.order_by(activity_model.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)

        return jsonify({
            'status': 'ok',
            'total': results.total,
            'page': results.page,
            'per_page': results.per_page,
            'items': [
                {
                    'id': a.id,
                    'activity_type': a.activity_type,
                    'details': a.details,
                    'created_at': a.created_at.isoformat(),
                }
                for a in results.items
            ],
        })

    @app.route('/api/dashboard-counts', methods=['GET'])
    @login_required
    @limit('120 per minute')
    def api_dashboard_counts():
        get_counts = current_app.config.get('_get_live_dashboard_counts')
        if not get_counts:
            return _err('NOT_AVAILABLE', 'Dashboard counts not configured.', 503)
        try:
            counts = get_counts()
        except Exception as e:
            current_app.logger.exception('Error computing live dashboard counts: %s', e)
            return _err('dashboard_counts_error', 'Failed to compute dashboard counts.', 500)

        if not isinstance(counts, dict):
            current_app.logger.warning('_get_live_dashboard_counts returned non-dict: %r', type(counts))
            return _err('dashboard_counts_error', 'Invalid counts payload.', 500)

        counts['status'] = 'ok'
        return jsonify(counts)


def register_api_routes(app, *, consumable_model, activity_model, db, normalize_role, limiter=None):
    limit = _create_limiter(limiter)
    _register_consumable_routes(app, consumable_model, db, normalize_role, limit)
    _register_dashboard_routes(app, consumable_model, activity_model, limit)
    _register_activity_routes(app, activity_model, limit)
