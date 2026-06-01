#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Analysis helpers extracted from legacy_helpers."""
# flake8: noqa

import re
from datetime import datetime

from flask import request
from sqlalchemy import func, or_

from app_pkg.utils import slugify_label
from model import db, User

from pm_app.legacy_parsing import parse_activity_kv
from pm_app.legacy_helpers import HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD, Image
from pm_app.services.llm_summarizer import activity_suggestions_enabled, generate_activity_suggestion
from pm_app.services.time_utils import utcnow_naive

def extract_risk_score_from_details(details_text):
    match = re.search(r"Risk Score:\s*(\d{1,3})", details_text or "", flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return max(0, min(100, int(match.group(1))))
    except ValueError:
        return None

def extract_sla_deadline_from_details(details_text):
    match = re.search(r"SLA Deadline \(UTC\):\s*([0-9\-: TZ]+)", details_text or "", flags=re.IGNORECASE)
    if not match:
        return None
    raw_value = match.group(1).strip().replace("Z", "")
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None

def extract_site_number_from_details(details_text):
    values = parse_activity_kv(details_text)
    return values.get("site number") or values.get("site id")

def extract_recommendations_from_details(details_text):
    recommendations = []
    in_section = False
    for raw_line in (details_text or "").splitlines():
        line = raw_line.strip()
        if line.lower() in {"recommendations:", "recommendation:"}:
            in_section = True
            continue
        if in_section:
            if not line:
                break
            if line.endswith(":") and not line.startswith("- "):
                break
            if line.startswith("- "):
                item = line[2:].strip()
            else:
                item = line
            if item and item.lower() not in {"none", "n/a", "no recommendation", "no recommendations"}:
                recommendations.append(item)
    return recommendations

def extract_detected_snags_from_details(details_text):
    snags = []
    in_section = False
    for raw_line in (details_text or "").splitlines():
        line = raw_line.strip()
        if line.lower() == "detected snags:":
            in_section = True
            continue
        if in_section:
            if not line:
                break
            if line.endswith(":") and not line.startswith("- "):
                break
            if line.startswith("- "):
                item = line[2:].strip()
                if item and item.lower() != "none":
                    snags.append(item)
    return snags

_OUTAGE_SIGNAL_RULES = [
    {
        "name": "site_down",
        "terms": ("site down", "network down", "outage", "off air", "no service", "link down", "total blackout"),
        "score": 26,
        "critical": True,
        "category": "OUTAGE_RESPONSE",
        "flag": "Network/site outage reported",
        "recommendation": "Escalate immediate outage response with NOC and field teams.",
    },
    {
        "name": "power_loss",
        "terms": ("no power", "power failure", "blackout", "mains down", "grid down", "genset failed", "generator failed", "rectifier fault"),
        "score": 18,
        "critical": True,
        "category": "POWER_CHAIN",
        "flag": "Power outage indicators detected",
        "recommendation": "Prioritize power restoration checks and generator failover validation.",
    },
    {
        "name": "transmission_fault",
        "terms": ("fiber cut", "transmission down", "backhaul down", "microwave down", "los", "transmission alarm"),
        "score": 20,
        "critical": True,
        "category": "TRANSMISSION",
        "flag": "Transmission outage indicators detected",
        "recommendation": "Raise transmission incident handling and confirm backhaul restoration path.",
    },
    {
        "name": "service_degradation",
        "terms": ("degraded", "intermittent", "flapping", "unstable", "packet loss", "high latency", "poor service", "slow service"),
        "score": 10,
        "critical": False,
        "category": "SERVICE_DEGRADATION",
        "flag": "Service degradation indicators detected",
        "recommendation": "Capture service quality evidence and investigate recurring degradation trends.",
    },
    {
        "name": "alarm_pressure",
        "terms": ("critical alarm", "major alarm", "multiple alarms", "alarm flood"),
        "score": 12,
        "critical": False,
        "category": "ALARM_PRESSURE",
        "flag": "High alarm pressure reported",
        "recommendation": "Correlate alarms with root cause and clear non-actionable noise.",
    },
    {
        "name": "access_security",
        "terms": ("forced access", "security issue", "site inaccessible", "access denied", "break in", "vandal", "theft"),
        "score": 16,
        "critical": True,
        "category": "ACCESS_SECURITY",
        "flag": "Access/security incident indicators detected",
        "recommendation": "Coordinate access, safety, and security teams before restoration work proceeds.",
    },
]

def analyze_outage_signals(free_text: str | None):
    text = (free_text or "").lower().strip()
    if not text:
        return {
            "matched_signals": [],
            "risk_boost": 0,
            "critical_flags": [],
            "recommendations": [],
            "categories": [],
        }
    matched_signals = []
    critical_flags = []
    recommendations = []
    categories = []
    risk_boost = 0
    def _matches_term(term: str) -> bool:
        escaped = re.escape((term or "").strip().lower())
        if not escaped:
            return False
        pattern = escaped.replace(r"\ ", r"\s+")
        return re.search(rf"(?<!\w){pattern}(?!\w)", text) is not None
    for rule in _OUTAGE_SIGNAL_RULES:
        if any(_matches_term(term) for term in rule["terms"]):
            matched_signals.append(rule["name"])
            risk_boost += int(rule["score"])
            categories.append(rule["category"])
            if rule["critical"]:
                critical_flags.append(rule["flag"])
            recommendations.append(rule["recommendation"])
    risk_boost = min(40, risk_boost)
    return {
        "matched_signals": matched_signals,
        "risk_boost": risk_boost,
        "critical_flags": critical_flags,
        "recommendations": recommendations,
        "categories": sorted(set(categories)),
    }

def classify_risk_level(score):
    if score >= HIGH_RISK_THRESHOLD:
        return "High"
    if score >= MEDIUM_RISK_THRESHOLD:
        return "Medium"
    return "Low"

def derive_sla_suggestion(sla_state: str, risk_level: str) -> str:
    state = (sla_state or "").strip().lower()
    risk = (risk_level or "").strip().lower()
    if state == "overdue":
        if risk == "high":
            return "SLA breached: escalate immediately with NOC and dispatch field remediation."
        return "SLA breached: prioritize this item for same-day review and corrective action."
    if state == "due soon":
        if risk == "high":
            return "SLA due soon on high risk: fast-track approvals and mitigation before deadline."
        return "SLA due soon: complete pending checks and close action items ahead of deadline."
    if state == "on track":
        return "SLA is on track: continue monitoring and keep evidence complete for closure."
    if state == "resolved":
        return "SLA resolved: document closure notes and preventive follow-up actions."
    return "SLA not set: assign a deadline based on risk and operational impact."


def extract_ai_suggestion_from_details(details_text):
    if not details_text:
        return None

    suggestions = []
    capture = False
    for raw_line in (details_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            if capture:
                break
            continue
        lower = line.lower()
        if lower.startswith("ai suggestion") or lower.startswith("ai recommendation") or lower.startswith("suggested action"):
            capture = True
            if ":" in line:
                suggestions.append(line.split(":", 1)[1].strip())
            continue
        if capture:
            if line.startswith("- "):
                suggestions.append(line[2:].strip())
            elif ":" in line and not line.startswith("- "):
                break
            else:
                suggestions.append(line)
    if suggestions:
        return " ".join(suggestions)[:400].strip()
    return None


def build_activity_suggestion(activity, recommendations, sla_state, risk_level):
    if recommendations:
        return recommendations[0]
    ai_suggestion = extract_ai_suggestion_from_details(activity.details)
    if ai_suggestion:
        return ai_suggestion
    if activity_suggestions_enabled():
        try:
            return generate_activity_suggestion(
                activity.details or "",
                sla_state=sla_state,
                risk_level=risk_level,
                activity_type=activity.activity_type,
            )
        except Exception:
            pass
    return derive_sla_suggestion(sla_state, risk_level)


def build_activity_suggestion_with_source(activity, recommendations, sla_state, risk_level):
    """Return (suggestion_text, source) where source is one of:
    - 'manual' (explicit recommendations in details)
    - 'ai_embedded' (AI suggestion embedded in details)
    - 'ai_llm' (generated via LLM)
    - 'heuristic' (derived SLA suggestion / fallback)
    """
    if recommendations:
        return (recommendations[0], "manual")
    ai_suggestion = extract_ai_suggestion_from_details(activity.details)
    if ai_suggestion:
        return (ai_suggestion, "ai_embedded")
    if activity_suggestions_enabled():
        try:
            txt = generate_activity_suggestion(
                activity.details or "",
                sla_state=sla_state,
                risk_level=risk_level,
                activity_type=activity.activity_type,
            )
            return (txt, "ai_llm")
        except Exception:
            pass
    return (derive_sla_suggestion(sla_state, risk_level), "heuristic")


def analyze_uploaded_photo_quality(file_path):
    result = {
        "width": None,
        "height": None,
        "megapixels": None,
        "warnings": [],
    }
    if Image is None:
        result["warnings"].append("Image quality could not be inspected because Pillow is unavailable.")
        return result
    try:
        with Image.open(file_path) as img:
            width, height = img.size
            result["width"] = width
            result["height"] = height
            result["megapixels"] = round((width * height) / 1_000_000, 2)
            if width < 640 or height < 480:
                result["warnings"].append("Low resolution photo; staff may need a clearer retake.")
            if result["megapixels"] is not None and result["megapixels"] < 0.3:
                result["warnings"].append("Photo detail is below recommended evidence quality.")
            if img.mode not in {"RGB", "RGBA", "L"}:
                result["warnings"].append("Unusual image color mode detected; verify photo opens correctly.")
    except Exception:
        result["warnings"].append("Image opened during validation but quality metadata could not be inspected.")
    return result

def build_review_priority(activity, *, risk_score, sla_state, recommendations=None):
    """Build intelligent review priority with multiple factors.
    
    Args:
        activity: Activity model instance
        risk_score: Numeric risk score (0-100)
        sla_state: 'overdue', 'due soon', 'on track', 'resolved', or None
        recommendations: List of extracted recommendations from analysis
    
    Returns:
        Dict with score, label, badge, reasons, and urgency metadata
    """
    score = int(risk_score or 0)
    reasons = []
    state = (sla_state or "").strip().lower()
    
    # SLA impact (highest priority)
    if state == "overdue":
        score += 40
        reasons.append("🚨 SLA OVERDUE - Escalate immediately")
    elif state == "due soon":
        score += 25
        reasons.append("⏰ SLA due within 6 hours")
    elif state == "on track":
        score += 5
        reasons.append("✓ SLA tracking normally")
    
    # Form type complexity
    if activity.activity_type == "rca":
        score += 15
        reasons.append("RCA (complex analysis required)")
    elif activity.activity_type == "consumable":
        score += 8
        reasons.append("Consumable request")
    
    # Risk level impact
    if risk_score >= HIGH_RISK_THRESHOLD:
        score += 20
        reasons.append("HIGH operational risk")
    elif risk_score >= MEDIUM_RISK_THRESHOLD:
        score += 10
        reasons.append("MEDIUM operational risk")
    
    # Historical context (days waiting)
    if activity.created_at:
        age_hours = max(0, int((utcnow_naive() - activity.created_at).total_seconds() // 3600))
        age_days = age_hours / 24
        if age_hours >= 24 and not activity.approved_at:
            # Escalating penalty for waiting time
            if age_days > 7:
                score += 25
                reasons.append(f"⚠️ Pending {age_days:.1f} days (critical wait)")
            elif age_days > 3:
                score += 15
                reasons.append(f"⚠️ Pending {age_days:.1f} days")
            else:
                score += 8
                reasons.append(f"Pending {age_hours}h")
    
    # Rejection history
    rejection_count = getattr(activity, 'rejection_count', 0)
    if rejection_count >= 2:
        score += 15
        reasons.append(f"⚠️ Multiple rejections ({rejection_count}x)")
    elif rejection_count == 1:
        score += 8
        reasons.append("Previously rejected - resubmitted")
    
    # Recommendations impact (more recommendations = more complex)
    rec_count = len(recommendations or [])
    if rec_count >= 3:
        score += 12
        reasons.append(f"Multiple actions required ({rec_count})")
    elif rec_count > 0:
        score += 5
        reasons.append("Has recommended actions")
    
    # Data completeness (estimated from details)
    details = activity.details or ""
    field_count = len([line for line in details.split('\n') if ':' in line])
    if field_count < 3 and len(details) < 200:
        score += 5
        reasons.append("May need clarification")
    
    # Normalize score and determine label
    score = max(0, min(120, score))
    
    if score >= 95:
        label = "CRITICAL"
        badge = "danger"
        urgency = "immediate"
    elif score >= 70:
        label = "HIGH"
        badge = "warning"
        urgency = "high"
    elif score >= 45:
        label = "STANDARD"
        badge = "info"
        urgency = "normal"
    else:
        label = "ROUTINE"
        badge = "secondary"
        urgency = "low"
    
    return {
        "score": score,
        "label": label,
        "badge": badge,
        "urgency": urgency,
        "reasons": reasons[:5] or ["Routine review"],
        "escalation_recommended": score >= 70,
        "requires_senior_review": risk_score >= HIGH_RISK_THRESHOLD or state == "overdue",
    }

def suggest_reviewer_for_activity(activity, reviewer_pool, *, activity_analysis_cache=None):
    """Suggest best reviewer for an activity based on expertise, load, and past performance.
    
    Args:
        activity: Activity model instance
        reviewer_pool: Dict of {reviewer_id: {stats_dict}} with expertise/performance data
        activity_analysis_cache: Optional cache of pre-computed analysis
    
    Returns:
        Dict with suggested_reviewer_id, confidence, and recommendation_reason
    """
    if not reviewer_pool:
        return {
            'suggested_reviewer_id': None,
            'confidence': 0,
            'reason': 'No reviewers available'
        }
    
    activity_type = activity.activity_type or 'pm'
    risk_score = getattr(activity, 'risk_score', 0)
    
    scored_reviewers = []
    for reviewer_id, stats in reviewer_pool.items():
        score = 0
        factors = []
        
        # Expertise match (40% weight)
        type_approval_rate = stats.get(f'{activity_type}_approval_rate', 50)
        score += (type_approval_rate / 100) * 40
        if type_approval_rate > 80:
            factors.append("Expert in this form type")
        
        # Current workload (30% weight - less work is better)
        queue_size = stats.get('current_queue_size', 0)
        load_penalty = min(queue_size * 3, 30)
        score += max(0, 30 - load_penalty)
        if queue_size < 3:
            factors.append("Low current queue")
        
        # Average review speed (20% weight)
        avg_time = stats.get('avg_review_hours', 24)
        if avg_time < 4:
            score += 15
            factors.append("Fast reviewer")
        elif avg_time < 12:
            score += 10
        else:
            score += 2
        
        # First-time pass rate (10% weight)
        ftpr = stats.get('first_time_pass_rate', 50)
        score += (ftpr / 100) * 10
        
        # Risk-specific bonus for high-risk items
        if risk_score >= HIGH_RISK_THRESHOLD:
            senior_flag = stats.get('senior_reviewer', False)
            if senior_flag:
                score += 15
                factors.append("Senior reviewer available")
        
        scored_reviewers.append((reviewer_id, score, factors, stats))
    
    if not scored_reviewers:
        return {
            'suggested_reviewer_id': None,
            'confidence': 0,
            'reason': 'Unable to score reviewers'
        }
    
    # Sort by score descending
    scored_reviewers.sort(key=lambda x: x[1], reverse=True)
    
    best_id, best_score, best_factors, best_stats = scored_reviewers[0]
    confidence = min(100, int(best_score))
    
    reason = f"Recommended based on: {', '.join(best_factors[:3])}"
    
    return {
        'suggested_reviewer_id': best_id,
        'confidence': confidence,
        'reason': reason,
        'reviewer_name': best_stats.get('name', f'Reviewer {best_id}'),
        'estimated_review_hours': best_stats.get('avg_review_hours', 24)
    }


SNAG_KEYWORDS = {
    "GATE_NOT_CLOSED": ["gate not closed", "gate open", "gate unlocked"],
    "POWER_FAILURE": ["no power", "power failure", "blackout", "mains down", "grid down"],
    "BATTERY_ISSUE": ["battery low", "battery dead", "battery fault", "battery weak"],
    "ACCESS_ISSUE": ["no access", "locked site", "access denied", "site inaccessible"],
    "FIBER_ISSUE": ["fiber cut", "link down", "transmission down", "no link"],
    "SECURITY_BREACH": ["theft", "vandal", "break in", "security issue", "intrusion"],
    "RECTIFIER_ISSUE": ["rectifier fault", "rectifier failed", "rectifier alarm"],
    "GENERATOR_ISSUE": ["generator failed", "genset failed", "dg failed", "dg fault"],
    "FUEL_RISK": ["low fuel", "fuel theft", "fuel leak", "no fuel"],
    "COOLING_ISSUE": ["high temperature", "cooling fault", "fan failed", "overheat"],
    "MISSING_SOLAR_PANEL": ["missing solar panel", "solar panel theft", "solar panel damage", "solar panel issue"],
}

OUTAGE_SNAGS = {"POWER_FAILURE", "BATTERY_ISSUE", "FIBER_ISSUE", "RECTIFIER_ISSUE", "GENERATOR_ISSUE", "COOLING_ISSUE"}
CRITICAL_SNAGS = {"GATE_NOT_CLOSED", "POWER_FAILURE", "BATTERY_ISSUE", "FIBER_ISSUE", "SECURITY_BREACH", "RECTIFIER_ISSUE", "GENERATOR_ISSUE", "FUEL_RISK", "COOLING_ISSUE", "MISSING_SOLAR_PANEL"}

SNAG_CLASSIFICATIONS = {
    "GATE_NOT_CLOSED": {"category": "ACCESS_SECURITY", "label": "Gate security issue", "score": 12},
    "POWER_FAILURE": {"category": "POWER_CHAIN", "label": "Power failure", "score": 24},
    "BATTERY_ISSUE": {"category": "POWER_CHAIN", "label": "Battery issue", "score": 18},
    "ACCESS_ISSUE": {"category": "ACCESS_SECURITY", "label": "Access issue", "score": 12},
    "FIBER_ISSUE": {"category": "TRANSMISSION", "label": "Transmission issue", "score": 22},
    "SECURITY_BREACH": {"category": "ACCESS_SECURITY", "label": "Security breach", "score": 20},
    "RECTIFIER_ISSUE": {"category": "POWER_CHAIN", "label": "Rectifier issue", "score": 18},
    "GENERATOR_ISSUE": {"category": "POWER_CHAIN", "label": "Generator issue", "score": 18},
    "FUEL_RISK": {"category": "POWER_CHAIN", "label": "Fuel risk", "score": 16},
    "COOLING_ISSUE": {"category": "POWER_CHAIN", "label": "Cooling issue", "score": 14},
    "MISSING_SOLAR_PANEL": {"category": "POWER_CHAIN", "label": "Missing solar panel", "score": 16},
}

BREACH_REASON_CATEGORIES = {
    "RESOURCE_DELAY",
    "MISSING_DATA",
    "APPROVAL_BOTTLENECK",
    "SYSTEM_ISSUE",
    "EXTERNAL_DEPENDENCY",
}

WORKFLOW_TRACE_LABELS = {
    "created": "Stage Created At (UTC)",
    "assigned": "Stage Assigned At (UTC)",
    "started": "Stage Started At (UTC)",
    "resolved": "Stage Resolved At (UTC)",
    "closed": "Stage Closed At (UTC)",
}

def _detail_label_prefix(label: str) -> str:
    return f"{label.strip()}:"

def upsert_detail_line(details_text: str, label: str, value: str) -> str:
    lines = (details_text or "").splitlines()
    prefix = _detail_label_prefix(label).lower()
    replaced = False
    for idx, raw_line in enumerate(lines):
        if raw_line.strip().lower().startswith(prefix):
            lines[idx] = f"{label}: {value}"
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        if not any(line.strip() == "WORKFLOW TRACE" for line in lines):
            lines.append("WORKFLOW TRACE")
        lines.append(f"{label}: {value}")
    return "\n".join(lines)

def parse_workflow_stage_times(details_text: str):
    values = parse_activity_kv(details_text)
    parsed = {}
    for stage, label in WORKFLOW_TRACE_LABELS.items():
        raw_value = (values.get(label.lower()) or "").strip().replace("Z", "")
        if not raw_value:
            parsed[stage] = None
            continue
        try:
            parsed[stage] = datetime.fromisoformat(raw_value)
        except ValueError:
            parsed[stage] = None
    return parsed

def append_workflow_stage(details_text: str, stage: str, when: datetime | None = None):
    when_value = when or utcnow_naive()
    label = WORKFLOW_TRACE_LABELS.get(stage)
    if not label:
        return details_text
    return upsert_detail_line(details_text, label, when_value.isoformat(timespec="seconds"))

def compute_activity_stage_durations(details_text: str):
    stages = parse_workflow_stage_times(details_text)
    def _duration_seconds(start, end):
        if not start or not end:
            return None
        return max(0, int((end - start).total_seconds()))
    return {
        "response_seconds": _duration_seconds(stages.get("assigned") or stages.get("created"), stages.get("started")),
        "resolution_seconds": _duration_seconds(stages.get("started"), stages.get("resolved")),
        "total_seconds": _duration_seconds(stages.get("created"), stages.get("closed") or stages.get("resolved")),
    }

def format_duration_seconds(value):
    if value is None:
        return "-"
    total = max(0, int(value))
    hours = total // 3600
    minutes = (total % 3600) // 60
    return f"{hours}h {minutes}m"

def detect_snags_from_form(form_data):
    def _get(label):
        return (form_data.get(f"field_{slugify_label(label)}") or "").strip().lower()
    findings = set()
    if _get("Is Gate Closed on Exit") == "no":
        findings.add("GATE_NOT_CLOSED")
    if _get("Is ATS Working?") == "no":
        findings.add("POWER_FAILURE")
    if _get("Is Battery on DG Working?") == "no":
        findings.add("BATTERY_ISSUE")
    if _get("Was grid available during site visit?") == "no":
        findings.add("POWER_FAILURE")
    free_text = " | ".join(
        [
            (form_data.get("validation_comments") or ""),
            _get("Comment"),
            _get("Any grid faults identified? Share."),
            _get("Purpose of Visit"),
        ]
    ).lower()
    for snag, keywords in SNAG_KEYWORDS.items():
        if any(keyword in free_text for keyword in keywords):
            findings.add(snag)
    findings_list = sorted(findings)
    outage_detected = any(item in OUTAGE_SNAGS for item in findings_list)
    return {
        "snags": findings_list,
        "outage_detected": outage_detected,
        "critical_snags": [item for item in findings_list if item in CRITICAL_SNAGS],
    }

def summarize_snag_profile(detected_snags):
    categories = []
    labels = []
    risk_boost = 0
    for snag in detected_snags or []:
        config = SNAG_CLASSIFICATIONS.get(snag)
        if not config:
            continue
        categories.append(config["category"])
        labels.append(config["label"])
        risk_boost += int(config["score"])
    primary_category = categories[0] if categories else "ROUTINE_PM"
    if "OUTAGE_RESPONSE" in categories:
        primary_category = "OUTAGE_RESPONSE"
    elif "TRANSMISSION" in categories:
        primary_category = "TRANSMISSION"
    elif "POWER_CHAIN" in categories:
        primary_category = "POWER_CHAIN"
    elif "ACCESS_SECURITY" in categories:
        primary_category = "ACCESS_SECURITY"
    return {
        "categories": sorted(set(categories)),
        "labels": labels,
        "risk_boost": min(36, risk_boost),
        "primary_category": primary_category,
    }

_ROLE_UID_PREFIX = {
    "developer": "DEV",
    "technician": "TEC",
    "staff": "STF",
    "manager": "MGR",
    "general_manager": "GMR",
}

def generate_uid(role: str) -> str:
    """Generate a unique UID for a user role using a database-backed counter."""
    from model import UIDCounter
    prefix = _ROLE_UID_PREFIX.get(role, "USR")

    counter = UIDCounter.query.filter_by(role=role).with_for_update().first()
    if counter:
        counter.last_value += 1
        num = counter.last_value
        db.session.commit()
    else:
        max_existing = User.query.with_entities(func.max(User.uid)).filter(
            User.role == role, User.uid.like(f"{prefix}-%")
        ).scalar()
        start = 0
        if max_existing:
            try:
                start = int(max_existing.split("-")[1])
            except (IndexError, ValueError):
                pass
        counter = UIDCounter(role=role, last_value=start + 1)
        db.session.add(counter)
        db.session.commit()
        num = start + 1

    return f"{prefix}-{num:03d}"

# REMOVED: generate_temporary_password - no longer needed
# All account credential setup now uses one-time activation tokens

def apply_user_search(query):
    search_query = (query or "").strip()[:100]
    users_query = User.query
    if search_query:
        like = f"%{search_query}%"
        users_query = users_query.filter(
            or_(
                User.uid.ilike(like),
                User.email.ilike(like),
                User.full_name.ilike(like),
                User.first_name.ilike(like),
                User.last_name.ilike(like),
                User.region.ilike(like),
                User.role.ilike(like),
            )
        )
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(max(10, request.args.get("per_page", 24, type=int)), 100)
    pagination = users_query.order_by(User.created_at.desc(), User.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    users = pagination.items
    grouped = {}
    for user in users:
        grouped.setdefault(user.role, []).append(user)
    return search_query, users, grouped, pagination

# ============================================================================
# Flask App Factory
# ============================================================================

