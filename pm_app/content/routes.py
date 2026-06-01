# flake8: noqa
from flask import render_template, request, flash, redirect, url_for, send_from_directory, send_file, jsonify, current_app, abort
from flask_login import login_required, current_user
from urllib.parse import urlparse
from werkzeug.utils import secure_filename
from PIL import Image
import os
import io
import shutil
import uuid
import json
from xml.sax.saxutils import escape
from pm_app.legacy_helpers import resolve_share_context
from pm_app.legacy_parsing import parse_activity_kv, parse_activity_details_structured
from pm_app.legacy_analysis import classify_risk_level
from openpyxl import Workbook
from reportlab.graphics import renderPM
from reportlab.graphics import renderSVG
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.barcode import qr as reportlab_qr
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage


def register_content_routes(
    app,
    *,
    Consumable,
    Activity,
    db,
    normalize_photo_library_controls,
    PHOTO_LIBRARY_IMAGE_EXTENSIONS,
    AVATAR_KEYS,
    TECHNICIAN_PHOTO_FIELDS,
    describe_monitored_image,
    get_record_or_404,
    analyze_uploaded_photo_quality,
    describe_uploaded_photo,
):
    def _is_consumables_user():
        # Allow configuration via app config `CONSUMABLES_VIEW_ROLES` which
        # accepts a comma-separated list of roles (e.g. "staff,technician").
        # If not configured, the consumables workflow is available to staff and technicians only.
        role = (getattr(current_user, "role", "") or "").strip().lower()
        if role == "desk_staff":
            role = "staff"
        cfg = app.config.get("CONSUMABLES_VIEW_ROLES")
        if cfg:
            # parse comma-separated roles from config
            allowed = {r.strip().lower() for r in str(cfg).split(",") if r.strip()}
            return role in allowed
        # Allow staff, technicians and managers by default to review consumables.
        return role in {"staff", "technician", "manager", "general_manager"}

    def _normalize_consumable_image_bytes(file_storage, label, ext):
        try:
            raw_bytes = file_storage.stream.read()
        except Exception as exc:
            raise ValueError(f"Image '{label}' could not be read. Please upload a different file.") from exc
        if not raw_bytes:
            raise ValueError(f"Image '{label}' is empty. Please upload a different file.")

        try:
            with Image.open(io.BytesIO(raw_bytes)) as image:
                image.verify()
        except Exception as exc:
            raise ValueError(f"Image '{label}' could not be verified as a valid image. Please upload a different file.") from exc

        try:
            with Image.open(io.BytesIO(raw_bytes)) as image:
                image.load()
                if getattr(image, "n_frames", 1) > 1 and ext == "gif":
                    return raw_bytes
                image.thumbnail((1600, 1600), Image.LANCZOS)
                if ext in {"jpg", "jpeg"}:
                    image = image.convert("RGB")
                    output = io.BytesIO()
                    image.save(
                        output,
                        format="JPEG",
                        quality=85,
                        optimize=True,
                        progressive=True,
                    )
                    return output.getvalue()
                if ext == "png":
                    if image.mode != "RGBA":
                        image = image.convert("RGBA")
                    output = io.BytesIO()
                    image.save(output, format="PNG", optimize=True)
                    return output.getvalue()
                if ext == "webp":
                    image = image.convert("RGB")
                    output = io.BytesIO()
                    image.save(output, format="WEBP", quality=85, method=6)
                    return output.getvalue()
                output = io.BytesIO()
                image.save(output, format=ext.upper(), optimize=True)
                return output.getvalue()
        except Exception as exc:
            raise ValueError(f"Image '{label}' could not be processed. Please upload a different file.") from exc

    def _parse_consumable_image_payload(raw_value):
        if not raw_value:
            return {}
        if isinstance(raw_value, dict):
            return raw_value
        if isinstance(raw_value, (list, tuple)):
            parsed = {}
            for index, value in enumerate(raw_value):
                if isinstance(value, str) and value.strip():
                    parsed[f"Image {index + 1}"] = value.strip()
            return parsed
        if isinstance(raw_value, str):
            raw_value = raw_value.strip()
            if not raw_value:
                return {}
            try:
                parsed = json.loads(raw_value)
            except Exception:
                return {"after": raw_value}
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, (list, tuple)):
                return {f"Image {index + 1}": value for index, value in enumerate(parsed) if isinstance(value, str) and value.strip()}
            return {"after": str(parsed)}
        return {}

    def _resolve_consumable_images(item):
        before_url = (item.before_usage_image_url or "").strip()
        after_payload = _parse_consumable_image_payload(getattr(item, "screenshot_url", None))
        after_url = ""
        for key in ("after", "After", "after_usage", "After Usage"):
            value = after_payload.get(key)
            if isinstance(value, str) and value.strip():
                after_url = value.strip()
                break
        if not after_url:
            for value in after_payload.values():
                if isinstance(value, str) and value.strip():
                    after_url = value.strip()
                    break
        if not after_url and getattr(item, "signage_image_url", None):
            after_url = (item.signage_image_url or "").strip()
        return before_url, after_url

    def _local_upload_path_from_url(url):
        if not url:
            return None
        filename = urlparse(url).path.rsplit("/", 1)[-1]
        if not filename:
            return None
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        if os.path.isfile(path):
            return path
        return None

    def _build_consumable_pdf_buffer(item):
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=24,
            leftMargin=24,
            topMargin=24,
            bottomMargin=24,
            compression=0,
            title="Consumable Review Report",
            author="Preventive Maintenance System",
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "Title",
            parent=styles["Heading1"],
            fontSize=18,
            leading=22,
            spaceAfter=12,
        )
        section_style = ParagraphStyle(
            "Section",
            parent=styles["Heading2"],
            fontSize=12,
            leading=14,
            spaceAfter=8,
        )
        body_style = ParagraphStyle(
            "Body",
            parent=styles["BodyText"],
            fontSize=10,
            leading=13,
            spaceAfter=6,
        )

        status_text = "Approved" if item.is_approved else ("Rejected" if item.approved_at else "Pending")
        table_data = [
            [Paragraph("<b>Field</b>", body_style), Paragraph("<b>Value</b>", body_style)],
            [Paragraph("Site ID", body_style), Paragraph(item.site_id or "-", body_style)],
            [Paragraph("Site Name", body_style), Paragraph(item.site_name or "-", body_style)],
            [Paragraph("Created By", body_style), Paragraph(item.created_by or "-", body_style)],
            [Paragraph("Created At", body_style), Paragraph(item.created_at.strftime("%Y-%m-%d %H:%M:%S") if item.created_at else "-", body_style)],
            [Paragraph("Location", body_style), Paragraph(item.location or "-", body_style)],
            [Paragraph("Status", body_style), Paragraph(status_text, body_style)],
            [Paragraph("Approved By", body_style), Paragraph(item.approved_by or "-", body_style)],
            [Paragraph("Approved At", body_style), Paragraph(item.approved_at.strftime("%Y-%m-%d %H:%M:%S") if item.approved_at else "-", body_style)],
        ]

        story = []
        story.append(Paragraph("Consumable Review Report", title_style))
        story.append(Paragraph(f"Generated for site <b>{item.site_name}</b> ({item.site_id})", body_style))
        story.append(Spacer(1, 12))
        story.append(Table(table_data, colWidths=[120, 380], style=TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f0f0f0")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d9d9d9")),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#d9d9d9")),
        ])))
        story.append(Spacer(1, 14))

        story.append(Paragraph("Description", section_style))
        story.append(Paragraph(escape(item.description or "-"), body_style))
        story.append(Spacer(1, 14))

        before_url, after_url = _resolve_consumable_images(item)
        if before_url or after_url:
            story.append(Paragraph("Images", section_style))
            if before_url:
                story.append(Paragraph("Before Usage", body_style))
                before_path = _local_upload_path_from_url(before_url)
                if before_path:
                    story.append(RLImage(before_path, width=260, height=180))
                    story.append(Spacer(1, 6))
                else:
                    story.append(Paragraph("Before image could not be loaded from local storage.", body_style))
                    story.append(Spacer(1, 6))
            if after_url:
                story.append(Paragraph("After Usage", body_style))
                after_path = _local_upload_path_from_url(after_url)
                if after_path:
                    story.append(RLImage(after_path, width=260, height=180))
                    story.append(Spacer(1, 6))
                else:
                    story.append(Paragraph("After image could not be loaded from local storage.", body_style))
                    story.append(Spacer(1, 6))

        doc.build(story)
        buffer.seek(0)
        return buffer

    @app.route("/consumables/<int:item_id>/pdf")
    @login_required
    def consumable_pdf(item_id):
        if not _is_consumables_user():
            abort(403)
        item = get_record_or_404(Consumable, item_id)
        buffer = _build_consumable_pdf_buffer(item)
        return send_file(
            buffer,
            mimetype="application/pdf",
            download_name=f"consumable_{item.id}.pdf",
            as_attachment=False,
        )

    @app.route("/consumables/", methods=["GET", "POST"])
    @login_required
    def consumables():
        if not _is_consumables_user():
            abort(403)
        if request.method == "POST":
            # Only technicians and staff may submit consumables via the form.
            submit_role = (getattr(current_user, "role", "") or "").strip().lower()
            if submit_role == "desk_staff":
                submit_role = "staff"
            if submit_role not in {"staff", "technician"}:
                flash("Only technicians and staff may submit consumables.", "warning")
                return redirect(url_for("consumables"))
            site_id = (request.form.get("site_id") or "").strip()[:20]
            site_name = (request.form.get("site_name") or "").strip()[:120]
            description = (request.form.get("description") or "").strip()
            location = (request.form.get("location") or "").strip() or None

            if not site_id or not site_name or not description:
                flash("Site ID, site name, and description are required.", "warning")
                return redirect(url_for("consumables"))

            upload_folder = app.config["UPLOAD_FOLDER"]
            os.makedirs(upload_folder, exist_ok=True)

            def _save_uploaded_image(file_storage, label):
                if not file_storage or not file_storage.filename:
                    return None
                original_name = secure_filename(file_storage.filename)
                if not original_name or "." not in original_name:
                    raise ValueError(f"Image '{label}' has an invalid filename.")
                ext = original_name.rsplit(".", 1)[1].lower()
                if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
                    raise ValueError(f"Image '{label}' must be a valid PNG, JPG, JPEG, GIF, or WebP image.")
                normalized_bytes = _normalize_consumable_image_bytes(file_storage, label, ext)
                stored_name = f"consumable_{uuid.uuid4().hex}.{ext}"
                stored_path = os.path.join(upload_folder, stored_name)
                with open(stored_path, "wb") as out_file:
                    out_file.write(normalized_bytes)
                return url_for("uploaded_file", filename=stored_name)

            before_file = request.files.get("before_usage_image")
            after_file = request.files.get("after_usage_image")
            before_label = (request.form.get("before_usage_label") or "Before usage").strip() or "Before usage"
            after_label = (request.form.get("after_usage_label") or "After usage").strip() or "After usage"
            before_url = None
            after_url = None

            if before_file and before_file.filename and after_file and after_file.filename:
                before_url = _save_uploaded_image(before_file, before_label)
                after_url = _save_uploaded_image(after_file, after_label)
            else:
                image_labels = request.form.getlist("image_labels[]") or []
                image_files = request.files.getlist("image_files[]") or []
                if not image_labels or not image_files or len(image_labels) != len(image_files):
                    flash("Please upload both before and after photos.", "warning")
                    return redirect(url_for("consumables"))
                valid_images = [(label, file) for label, file in zip(image_labels, image_files) if label.strip() and file and file.filename]
                if not valid_images:
                    flash("Please upload both before and after photos.", "warning")
                    return redirect(url_for("consumables"))
                try:
                    first_url = _save_uploaded_image(valid_images[0][1], valid_images[0][0].strip())
                    after_url = first_url
                except ValueError as exc:
                    flash(str(exc), "warning")
                    return redirect(url_for("consumables"))

            if not after_url:
                flash("Please upload both before and after photos.", "warning")
                return redirect(url_for("consumables"))

            item = Consumable(
                site_id=site_id,
                site_name=site_name,
                description=description,
                created_by=current_user.email,
                location=location,
                signage_image_url=None,
                screenshot_url=json.dumps({"after": after_url}),
                before_usage_image_url=before_url,
            )
            db.session.add(item)
            db.session.commit()
            flash("Consumable submitted to staff for review.", "success")
            return redirect(url_for("consumables", submitted=1))

        search_query = (request.args.get("q") or "").strip()[:100]
        query = Consumable.query
        if search_query:
            like = f"%{search_query}%"
            query = query.filter(
                (Consumable.site_id.ilike(like)) | (Consumable.site_name.ilike(like)) | (Consumable.description.ilike(like)) | (Consumable.created_by.ilike(like))
            )
        page = max(1, request.args.get("page", 1, type=int))
        per_page = 5  # Default: 5 items per page for recent review and better page navigation
        pagination = query.order_by(Consumable.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
        return render_template("consumables.html", consumables=pagination.items, pagination=pagination, search_query=search_query)

    @app.route("/consumables/<int:item_id>/")
    @login_required
    def consumable_detail(item_id):
        if not _is_consumables_user():
            abort(403)
        item = get_record_or_404(Consumable, item_id)
        before_usage_image_url, after_usage_image_url = _resolve_consumable_images(item)
        return render_template(
            "consumable_detail.html",
            item=item,
            before_usage_image_url=before_usage_image_url,
            after_usage_image_url=after_usage_image_url,
        )

    @app.route("/developer/photo-library")
    @login_required
    def developer_photo_library():
        controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
        photo_query = (request.args.get("q") or "").strip().lower()
        requested_limit = request.args.get("limit", controls["max_scan_limit"], type=int)
        photo_limit = min(max(requested_limit or 12, 12), controls["max_scan_limit"])
        photo_dir = os.path.join(app.root_path, "photo")
        candidates = []
        if os.path.isdir(photo_dir):
            for name in os.listdir(photo_dir):
                ext = os.path.splitext(name)[1].lower()
                if ext not in PHOTO_LIBRARY_IMAGE_EXTENSIONS:
                    continue
                lowered = name.lower()
                kind = "screenshot" if "screenshot" in lowered or "whatsapp" in lowered else "image"
                if kind == "screenshot" and not controls["include_screenshots"]:
                    continue
                path = os.path.join(photo_dir, name)
                if photo_query and photo_query not in lowered:
                    continue
                stat = os.stat(path)
                candidates.append({
                    "name": name,
                    "path": path,
                    "extension": ext.lstrip("."),
                    "kind": kind,
                    "size_kb": max(1, round(stat.st_size / 1024)),
                    "modified_at": datetime.fromtimestamp(stat.st_mtime),
                    "preview_url": url_for("photo_library_file", filename=name),
                })
        candidates.sort(key=lambda item: item["modified_at"], reverse=True)
        entries = candidates[:photo_limit]
        for entry in entries:
            entry["description"] = describe_monitored_image(entry["path"], entry["name"])
            entry.pop("path", None)
        return render_template(
            "developer_photo_library.html",
            photo_entries=entries,
            photo_library_total=len(entries),
            screenshot_count=sum(1 for item in entries if item["kind"] == "screenshot"),
            photo_library_path=photo_dir,
            monitored_sources=[photo_dir],
            photo_query=request.args.get("q", ""),
            photo_limit=photo_limit,
            photo_library_controls=controls,
        )

    @app.route("/photo/<path:filename>")
    @login_required
    def photo_library_file(filename):
        return send_from_directory(os.path.join(app.root_path, "photo"), filename)

    # -----------------------------------------------------------------
    # Admin: AI suggestions review
    # -----------------------------------------------------------------
    @app.route('/admin/ai-suggestions/')
    @login_required
    def admin_ai_suggestions():
        # Restrict to developer/admin roles
        role = (getattr(current_user, 'role', '') or '').strip().lower()
        if role not in {'developer', 'admin'}:
            abort(403)
        try:
            from model import AiSuggestion
            suggestions = AiSuggestion.query.order_by(AiSuggestion.created_at.desc()).limit(200).all()
        except Exception:
            suggestions = []
        return render_template('admin_ai_suggestions.html', suggestions=suggestions)

    @app.route('/admin/ai-suggestions/<int:sid>/apply', methods=['POST'])
    @login_required
    def admin_ai_suggestion_apply(sid):
        role = (getattr(current_user, 'role', '') or '').strip().lower()
        if role not in {'developer', 'admin'}:
            abort(403)
        try:
            from model import AiSuggestion
            from pm_app.legacy_analysis import upsert_detail_line
            s = AiSuggestion.query.get(sid)
            if not s:
                flash('Suggestion not found', 'warning')
                return redirect(url_for('admin_ai_suggestions'))
            activity = Activity.query.get(s.activity_id)
            if not activity:
                flash('Related activity not found', 'warning')
                return redirect(url_for('admin_ai_suggestions'))
            # Upsert AI Suggestion into activity.details
            activity.details = upsert_detail_line(activity.details or '', 'AI Suggestion', s.suggestion_text)
            db.session.commit()
            flash('Suggestion applied to activity details', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to apply suggestion: {e}', 'danger')
        return redirect(url_for('admin_ai_suggestions'))

    @app.route('/admin/ai-suggestions/<int:sid>/delete', methods=['POST'])
    @login_required
    def admin_ai_suggestion_delete(sid):
        role = (getattr(current_user, 'role', '') or '').strip().lower()
        if role not in {'developer', 'admin'}:
            abort(403)
        try:
            from model import AiSuggestion
            s = AiSuggestion.query.get(sid)
            if not s:
                flash('Suggestion not found', 'warning')
                return redirect(url_for('admin_ai_suggestions'))
            db.session.delete(s)
            db.session.commit()
            flash('Suggestion deleted', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Failed to delete suggestion: {e}', 'danger')
        return redirect(url_for('admin_ai_suggestions'))

    @app.route("/developer/photo-library/import", methods=["POST"])
    @login_required
    def import_photo_library_file():
        controls = app.config.get("PHOTO_LIBRARY_CONTROLS", normalize_photo_library_controls(None))
        if not controls.get("allow_import"):
            flash("Photo import is disabled by developer policy.", "warning")
            return redirect(url_for("developer_photo_library"))
        filename = secure_filename(request.form.get("filename") or "")
        source = os.path.join(app.root_path, "photo", filename)
        if not filename or not os.path.isfile(source) or not _is_valid_image_file_path(source):
            flash("Selected photo could not be imported.", "danger")
            return redirect(url_for("developer_photo_library"))
        dest_name = f"photo_library_{uuid.uuid4().hex}_{filename}"
        shutil.copy2(source, os.path.join(app.config["UPLOAD_FOLDER"], dest_name))
        flash("Photo imported into uploads.", "success")
        return redirect(url_for("developer_photo_library"))

    @app.route("/developer/share-qr.png")
    @login_required
    def developer_share_qr():
        requested_url = request.args.get("url") or resolve_share_context().get("login_url")
        if not requested_url:
            requested_url = url_for("technician_login", _external=True)
            current_app.logger.warning(
                "Developer share QR requested without explicit URL and no resolved login URL; falling back to current host technician login URL=%s",
                requested_url,
            )
        image_format = (request.args.get("format") or "png").lower()
        drawing = Drawing(220, 220)
        qr_code = reportlab_qr.QrCodeWidget(requested_url)
        bounds = qr_code.getBounds()
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        qr_code.barWidth = 190 / width
        qr_code.barHeight = 190 / height
        qr_code.x = 15
        qr_code.y = 15
        drawing.add(qr_code)
        if image_format == "svg":
            data = renderSVG.drawToString(drawing)
            return app.response_class(data, mimetype="image/svg+xml")
        buffer = io.BytesIO()
        renderPM.drawToFile(drawing, buffer, fmt="PNG")
        buffer.seek(0)
        return send_file(buffer, mimetype="image/png")

    @app.route("/system/share-url")
    @login_required
    def system_share_url():
        share_context = resolve_share_context()
        public_login_url = share_context.get("login_url") or url_for("technician_login", _external=True)
        if not share_context.get("login_url"):
            current_app.logger.warning(
                "System share URL resolved without a login_url; falling back to current host technician login URL=%s",
                public_login_url,
            )
        lan_ip = "127.0.0.1"
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                lan_ip = probe.getsockname()[0]
        except Exception:
            lan_ip = request.host.split(":")[0] if request.host else lan_ip
        request_base = urlparse(request.host_url.rstrip("/"))
        request_scheme = request_base.scheme or "http"
        request_port = request_base.port
        port_suffix = f":{request_port}" if request_port and request_port not in {80, 443} else ""
        login_path = url_for("technician_login") or "/technician/login"
        lan_url = f"{request_scheme}://{lan_ip}{port_suffix}{login_path}"
        return render_template("system_share_url.html", public_login_url=public_login_url, public_url_source=share_context["source"], lan_url=lan_url)

    @app.route("/api/live-share-url")
    @login_required
    def api_live_share_url():
        share_context = resolve_share_context()
        return jsonify(share_context)

    def _tracker_rows(Activity, parse_activity_kv):
        # Combine PM/RCA activities with consumables so the tracker/export shows everything
        activity_items = Activity.query.filter(Activity.activity_type.in_(["pm", "rca"]))
        consumable_items = Consumable.query

        base_labels = ["Site Number", "Site Name", "Issue Summary", "Risk Score", "Risk Level", "Description"]
        labels = list(base_labels)
        seen_labels = set(base_labels)
        rows = []

        def _normalize_tracker_label(label):
            if not label:
                return ""
            normalized = label.strip()
            mapping = {
                "site id": "Site Number",
                "site number": "Site Number",
                "site name": "Site Name",
                "issue summary": "Issue Summary",
                "issue": "Issue Summary",
                "risk score": "Risk Score",
                "risk level": "Risk Level",
                "description": "Description",
            }
            return mapping.get(normalized.lower(), normalized)

        def _coerce_tracker_value(value):
            if value is None:
                return ""
            if isinstance(value, (list, tuple)):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                return "\n".join(cleaned)
            return str(value).strip()

        def _collect_field_values(summary_values, structured):
            field_values = {}
            photo_labels = {item["label"].strip().lower() for item in TECHNICIAN_PHOTO_FIELDS}

            def _is_tracker_input_label(label):
                lowered = (label or "").strip().lower()
                if lowered in photo_labels:
                    return True
                return any(token in lowered for token in ("photo", "image", "signature", "attachment", "screenshot", "before usage", "before_usage", "upload", "url"))

            def _add_field(label, value):
                display_label = _normalize_tracker_label(label)
                if not display_label or _is_tracker_input_label(display_label):
                    return
                text = _coerce_tracker_value(value)
                if display_label not in field_values or not field_values[display_label]:
                    field_values[display_label] = text

            for header_label, header_value in (structured.get("header_rows", []) or []):
                _add_field(header_label, header_value)
            for section in (structured.get("sections", []) or []):
                for row_label, row_value in section.get("rows", []) or []:
                    _add_field(row_label, row_value)
            for insight_label, insight_value in (structured.get("insights", {}) or {}).items():
                _add_field(insight_label, insight_value)
            for fallback_label, fallback_value in (summary_values or {}).items():
                _add_field(fallback_label, fallback_value)

            return field_values

        # Activities
        for activity in activity_items.order_by(Activity.created_at.desc()).all():
            # Base kv parsing (backwards compatible)
            values = parse_activity_kv(activity.details)

            # Prefer structured parser when available to surface named fields
            try:
                structured = parse_activity_details_structured(activity.details)
            except Exception:
                structured = {}

            field_values = _collect_field_values(values, structured)
            site_number = field_values.get("Site Number") or field_values.get("site number") or values.get("site number") or values.get("site id") or "-"
            site_name = field_values.get("Site Name") or field_values.get("site name") or values.get("site name") or "-"
            issue_summary = field_values.get("Issue Summary") or values.get("issue summary") or values.get("issue") or "-"
            risk_score = field_values.get("Risk Score") or values.get("risk score") or str(activity.risk_score or 0)
            risk_level = field_values.get("Risk Level") or values.get("risk level") or classify_risk_level(activity.risk_score or 0)
            description = field_values.get("Description") or values.get("description") or values.get("issue") or "-"

            field_values["Site Number"] = site_number
            field_values["Site Name"] = site_name
            field_values["Issue Summary"] = issue_summary
            field_values["Risk Score"] = risk_score
            field_values["Risk Level"] = risk_level
            field_values["Description"] = description

            for label in field_values:
                if label not in seen_labels:
                    seen_labels.add(label)
                    labels.append(label)

            rows.append({
                "form_id": activity.id,
                "activity_type": activity.activity_type.upper(),
                "site_number": site_number,
                "site_name": site_name,
                "technician": activity.created_by or "-",
                "created_at": activity.created_at.strftime("%Y-%m-%d %H:%M") if activity.created_at else "-",
                "status": "Approved" if activity.is_approved else ("Rejected" if activity.approved_at else "Pending"),
                "approved_by": activity.approved_by,
                "approved_at": activity.approved_at.strftime("%Y-%m-%d %H:%M") if activity.approved_at else "",
                "field_values": field_values,
            })

        # Consumables - treat like form submissions for tracking
        for c in consumable_items.order_by(Consumable.created_at.desc()).all():
            field_values = {
                "Site Number": c.site_id or "-",
                "Site Name": c.site_name or "-",
                "Issue Summary": c.description or "-",
                "Risk Score": "-",
                "Risk Level": "-",
                "Description": c.description or "-",
            }
            rows.append({
                "form_id": f"C-{c.id}",
                "activity_type": "CONSUMABLE",
                "site_number": c.site_id or "-",
                "site_name": c.site_name or "-",
                "technician": c.created_by or "-",
                "created_at": c.created_at.strftime("%Y-%m-%d %H:%M") if c.created_at else "-",
                "status": "Approved" if c.is_approved else ("Rejected" if c.approved_at else "Pending"),
                "approved_by": c.approved_by,
                "approved_at": c.approved_at.strftime("%Y-%m-%d %H:%M") if c.approved_at else "",
                "field_values": field_values,
            })

        return labels, rows

    @app.route("/desk/rca-tracker/")
    @login_required
    def desk_rca_tracker():
        labels, rows = _tracker_rows(Activity, parse_activity_kv)
        # Server-side pagination for tracker rows (combined Activities + Consumables)
        page = max(1, request.args.get("page", 1, type=int))
        per_page = min(max(10, request.args.get("per_page", 25, type=int)), 200)
        total = len(rows)
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page > total_pages:
            page = total_pages
        start = (page - 1) * per_page
        end = start + per_page
        page_rows = rows[start:end]
        pagination = {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "prev_page": page - 1 if page > 1 else None,
            "next_page": page + 1 if page < total_pages else None,
        }
        return render_template("desk_rca_tracker.html", labels=labels, rows=page_rows, pagination=pagination)

    @app.route("/staff/rca-tracker/")
    @login_required
    def staff_rca_tracker():
        return redirect(url_for("desk_rca_tracker"))

    @app.route("/desk/rca-tracker/export")
    @login_required
    def export_rca_tracker_excel():
        labels, rows = _tracker_rows(Activity, parse_activity_kv)
        wb = Workbook()
        ws = wb.active
        assert ws is not None
        ws.title = "PM RCA Tracker"
        header = ["Form ID", "Type", "Site Number", "Site Name", "Technician", "Created At", "Status", "Approved By", "Approved At"] + labels
        ws.append(header)
        try:
            for row in rows:
                base = [
                    row.get("form_id"), row.get("activity_type"), row.get("site_number"), row.get("site_name"), row.get("technician"),
                    row.get("created_at"), row.get("status"), row.get("approved_by") or "", row.get("approved_at") or "",
                ]
                extras = []
                for label in labels:
                    val = row.get("field_values", {}).get(label, "")
                    # Coerce to safe types for Excel
                    if val is None:
                        extras.append("")
                    elif isinstance(val, (int, float, bool)):
                        extras.append(val)
                    else:
                        extras.append(str(val))
                ws.append(base + extras)

            buffer = io.BytesIO()
            wb.save(buffer)
            buffer.seek(0)
        except Exception as exc:
            # Return a helpful error message for debugging client-side failures
            current_app.logger.exception("Failed to generate PM/RCA tracker Excel: %s", exc)
            return ("Failed to generate Excel export: %s" % str(exc), 500)

        as_attachment = request.args.get("mode") != "open"
        response = send_file(
            buffer,
            as_attachment=as_attachment,
            download_name="pm_rca_tracker.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        # Prevent caching issues in some browsers
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/staff/rca-tracker/export")
    @login_required
    def export_staff_rca_tracker_excel():
        return export_rca_tracker_excel()

    @app.route("/approved-forms/export")
    @login_required
    def export_approved_forms_excel():
        return export_rca_tracker_excel()
