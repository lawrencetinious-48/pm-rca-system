#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PDF helpers extracted from legacy_helpers."""
# flake8: noqa

import io
import os
from html import escape
import requests

from app_pkg.constants import TECHNICIAN_PHOTO_FIELDS
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from pm_app.legacy_parsing import (
    _resolve_uploaded_image_path,
    parse_activity_details_structured,
    parse_activity_kv,
)


def build_activity_pdf_buffer(activity, upload_folder):
    structured = parse_activity_details_structured(
        activity.details,
        expected_photo_labels=[item["label"] for item in TECHNICIAN_PHOTO_FIELDS],
    )
    if not any(structured.get(key) for key in ("header_rows", "sections", "insights", "photos", "signature_url")):
        values = parse_activity_kv(activity.details)
        if values:
            structured = {
                "header_rows": list(values.items()),
                "sections": [],
                "insights": {},
                "photos": [],
                "signature_url": "",
            }
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=24,
        rightMargin=24,
        topMargin=24,
        bottomMargin=24,
        title=f"{(activity.activity_type or '').upper()} Form #{activity.formatted_id}",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PdfTitle",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=15,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=2,
    )
    section_style = ParagraphStyle(
        "PdfSectionTitle",
        parent=styles["Heading4"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=colors.HexColor("#1E3A8A"),
        spaceAfter=0,
    )
    body_style = ParagraphStyle(
        "FormBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
        spaceAfter=2,
    )
    def _p(value):
        safe = escape((value or "").strip())
        return Paragraph(safe if safe else "-", body_style)
    def _kv_table(rows, header_left=None, header_right=None):
        data = []
        if header_left is not None and header_right is not None:
            data.append([_p(header_left), _p(header_right)])
        data.extend([_p(label), _p(value)] for label, value in rows)
        table = Table(data, colWidths=[210, 325], repeatRows=1 if data else 0)
        style = [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DADCE0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#F8FAFC")),
            ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 1), (0, -1), colors.HexColor("#334155")),
        ]
        if header_left is not None and header_right is not None:
            style.extend(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F0FE")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ]
            )
        table.setStyle(TableStyle(style))
        return table
    def _boxed(flowable):
        box = Table([[flowable]], colWidths=[535])
        box.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C7D2E4")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 5),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                    ("TOPPADDING", (0, 0), (-1, -1), 5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ]
            )
        )
        return box
    def _url_link(url, label_text="Open image"):
        raw = (url or "").strip()
        if not raw:
            return None
        safe_url = escape(raw)
        safe_label = escape(label_text)
        return Paragraph(f'<link href="{safe_url}">{safe_label}</link>', body_style)
    story = [
        Paragraph(f"{(activity.activity_type or '').upper()} Form #{activity.formatted_id}", title_style),
        Paragraph("AIRTEL UG Planned Preventive Maintenance Form", ParagraphStyle(
            "PdfSubTitle",
            parent=body_style,
            fontName="Helvetica-Bold",
            fontSize=9,
            textColor=colors.HexColor("#64748B"),
            spaceAfter=2,
        )),
        Spacer(1, 8),
    ]
    # Attempt to include branded logos (Airtel left, Soliton right) at top of PDF
    try:
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        images_dir = os.path.join(project_root, '..', 'static', 'images')
        # fallback: project_root/static/images
        if not os.path.isdir(images_dir):
            images_dir = os.path.join(project_root, 'static', 'images')

        left_logo = os.path.join(images_dir, 'airtel-logo.webp')
        right_logo = os.path.join(images_dir, 'soliton-telmec.jpeg')
        if not os.path.isfile(right_logo):
            right_logo = os.path.join(images_dir, 'soliton-telmec.png')
        logo_cells = []
        # Load images and scale; ensure Airtel (left) matches Soliton (right) height
        imgs = []
        for path in (left_logo, right_logo):
            if os.path.isfile(path):
                try:
                    img = RLImage(path)
                    imgs.append(img)
                except Exception:
                    imgs.append(None)
            else:
                imgs.append(None)
        # Apply initial width-based scaling
        max_w = 130
        for i, img in enumerate(imgs):
            if img is None:
                logo_cells.append(Paragraph('', body_style))
                continue
            try:
                scale = min(max_w / float(img.imageWidth), 1.0)
                img.drawWidth = float(img.imageWidth) * scale
                img.drawHeight = float(img.imageHeight) * scale
                img.hAlign = 'LEFT'
                logo_cells.append(img)
            except Exception:
                logo_cells.append(Paragraph('', body_style))
        # If both logos present, enforce same display height (use right logo as reference)
        try:
            if isinstance(logo_cells[1], RLImage) and isinstance(logo_cells[0], RLImage):
                ref_height = float(logo_cells[1].drawHeight)
                # adjust left logo to match reference height while preserving aspect ratio
                left_img = logo_cells[0]
                aspect = float(left_img.imageWidth) / float(left_img.imageHeight)
                new_w = ref_height * aspect
                # cap width to original max column width
                max_col_w = 140
                if new_w > max_col_w:
                    new_w = max_col_w
                    ref_height = new_w / aspect
                left_img.drawWidth = new_w
                left_img.drawHeight = ref_height
        except Exception:
            pass

        logos_row = Table([[logo_cells[0], Paragraph('', body_style), logo_cells[1]]], colWidths=[140, 255, 140])
        logos_row.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (-1, 0), (-1, 0), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ])
        )
        story.insert(0, logos_row)
        story.insert(1, Spacer(1, 6))
    except Exception:
        pass
    if structured["header_rows"]:
        story.append(_boxed(_kv_table(structured["header_rows"])))
        story.append(Spacer(1, 10))
    for section in structured["sections"]:
        story.append(_boxed(_kv_table(section["rows"], section["title"], "CURRENT VALUE")))
        story.append(Spacer(1, 10))
    if structured["insights"]:
        insight_rows = []
        for key in ["Risk Score", "Risk Level", "Critical", "SLA Deadline (UTC)"]:
            if key in structured["insights"]:
                insight_rows.append((key, str(structured["insights"][key])))
        for key in ["Critical Flags", "Anomalies", "Recommendations"]:
            if key in structured["insights"]:
                value = structured["insights"][key]
                if isinstance(value, list):
                    joined = "\n".join(item for item in value if item)
                    insight_rows.append((key, joined))
                else:
                    insight_rows.append((key, str(value)))
        story.append(_boxed(_kv_table(insight_rows, "SMART INSIGHTS", "DETAILS")))
        story.append(Spacer(1, 10))
    story.append(_boxed(Paragraph("PHOTO SPECIFICATIONS", section_style)))
    story.append(Spacer(1, 8))
    def _photo_cell(photo):
        photo_card = [Paragraph(escape(photo["label"]), styles["Heading5"]), Spacer(1, 4)]
        img_path = _resolve_uploaded_image_path(photo.get("url"), upload_folder)
        image = None
        if img_path:
            try:
                image = RLImage(img_path)
            except Exception:
                image = None
                # Try re-encoding with Pillow to a PNG in-memory and retry
                try:
                    from PIL import Image as _PILImage
                    with _PILImage.open(img_path) as pil_img:
                        bio_conv = io.BytesIO()
                        pil_img.convert("RGB").save(bio_conv, format="PNG")
                        bio_conv.seek(0)
                        image = RLImage(bio_conv)
                except Exception:
                    image = None
        # Fallback: if no local image path, attempt to download remote image URL
        if image is None and photo.get("url"):
            url = photo.get("url")
            try:
                resp = requests.get(url, timeout=6)
                if resp.status_code == 200 and resp.content:
                    bio = io.BytesIO(resp.content)
                    try:
                        image = RLImage(bio)
                    except Exception:
                        image = None
                        # Try to re-encode downloaded bytes with Pillow then retry
                        try:
                            from PIL import Image as _PILImage
                            bio.seek(0)
                            with _PILImage.open(bio) as pil_img:
                                bio_conv = io.BytesIO()
                                pil_img.convert("RGB").save(bio_conv, format="PNG")
                                bio_conv.seek(0)
                                image = RLImage(bio_conv)
                        except Exception:
                            image = None
            except Exception:
                image = None
        if image is not None:
            try:
                max_w = 235
                max_h = 150
                scale = min(max_w / float(image.imageWidth), max_h / float(image.imageHeight), 1.0)
                image.drawWidth = float(image.imageWidth) * scale
                image.drawHeight = float(image.imageHeight) * scale
                image.hAlign = "LEFT"
                photo_card.append(image)
            except Exception:
                image = None
        if image is None:
            if photo.get("url"):
                photo_card.append(_p("Photo preview unavailable in this PDF."))
            else:
                photo_card.append(_p("No photo uploaded"))
        if photo.get("url"):
            link_para = _url_link(photo.get("url"), "Tap to open full image")
            if link_para is not None:
                photo_card.append(Spacer(1, 2))
                photo_card.append(link_para)
        if photo.get("description"):
            photo_card.append(_p(photo["description"]))
        card_table = Table([[photo_card]], colWidths=[258])
        card_table.setStyle(
            TableStyle(
                [
                    ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#C7D2E4")),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ]
            )
        )
        return card_table
    photos = structured["photos"]
    for idx in range(0, len(photos), 2):
        left_cell = _photo_cell(photos[idx])
        right_cell = _photo_cell(photos[idx + 1]) if idx + 1 < len(photos) else Paragraph("", body_style)
        row_table = Table([[left_cell, right_cell]], colWidths=[266, 266])
        row_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        story.append(row_table)
        story.append(Spacer(1, 8))
    story.append(_boxed(Paragraph("TECHNICIAN SIGNATURE", section_style)))
    story.append(Spacer(1, 6))
    signature_card = []
    signature_path = _resolve_uploaded_image_path(structured.get("signature_url"), upload_folder)
    signature = None
    if signature_path:
        try:
            signature = RLImage(signature_path)
            max_w = 260
            max_h = 95
            scale = min(max_w / float(signature.imageWidth), max_h / float(signature.imageHeight), 1.0)
            signature.drawWidth = float(signature.imageWidth) * scale
            signature.drawHeight = float(signature.imageHeight) * scale
            signature.hAlign = "LEFT"
            signature_card.append(signature)
        except Exception:
            signature = None
    # Fallback: try to download signature URL if local path resolution failed
    if signature is None and structured.get("signature_url"):
        try:
            resp = requests.get(structured.get("signature_url"), timeout=6)
            if resp.status_code == 200 and resp.content:
                bio = io.BytesIO(resp.content)
                try:
                    signature = RLImage(bio)
                    max_w = 260
                    max_h = 95
                    scale = min(max_w / float(signature.imageWidth), max_h / float(signature.imageHeight), 1.0)
                    signature.drawWidth = float(signature.imageWidth) * scale
                    signature.drawHeight = float(signature.imageHeight) * scale
                    signature.hAlign = "LEFT"
                    signature_card.append(signature)
                except Exception:
                    signature = None
                    # Try re-encoding with Pillow and retry
                    try:
                        from PIL import Image as _PILImage
                        bio.seek(0)
                        with _PILImage.open(bio) as pil_img:
                            bio_conv = io.BytesIO()
                            pil_img.convert("RGB").save(bio_conv, format="PNG")
                            bio_conv.seek(0)
                            signature = RLImage(bio_conv)
                            max_w = 260
                            max_h = 95
                            scale = min(max_w / float(signature.imageWidth), max_h / float(signature.imageHeight), 1.0)
                            signature.drawWidth = float(signature.imageWidth) * scale
                            signature.drawHeight = float(signature.imageHeight) * scale
                            signature.hAlign = "LEFT"
                            signature_card.append(signature)
                    except Exception:
                        signature = None
        except Exception:
            signature = None
    if signature is None:
        if structured.get("signature_url"):
            signature_card.append(_p("Signature preview unavailable in this PDF."))
        else:
            signature_card.append(_p("Signature not available"))
    if structured.get("signature_url"):
        signature_link = _url_link(structured.get("signature_url"), "Tap to open signature")
        if signature_link is not None:
            signature_card.append(Spacer(1, 2))
            signature_card.append(signature_link)
    story.append(_boxed(signature_card))
    doc.build(story)
    buffer.seek(0)
    return buffer

def parse_float_value(value):
    if value is None:
        return None
    cleaned = str(value).strip().replace(",", "")
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None

def extract_metric_from_details(details_text, metric_label):
    values = parse_activity_kv(details_text)
    return parse_float_value(values.get(metric_label.lower()))

