#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parsing helpers extracted from legacy_helpers."""
# flake8: noqa

import os
from urllib.parse import urlparse
from app_pkg.constants import TECHNICIAN_PM_SECTIONS


def _is_valid_image_file_path(file_path):
    # Lightweight check: accept common image file extensions and existing files.
    if not file_path or not os.path.isfile(file_path):
        return False
    ext = os.path.splitext(file_path)[1].lower()
    return ext in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".svg"}

def parse_activity_kv(details_text):
    values = {}
    for raw_line in (details_text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            line = line[2:].strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        values[key.strip().lower()] = value.strip()
    return values

def parse_activity_details_structured(details_text, expected_photo_labels=None):
    _title_upper_set = {s["title"].upper() for s in TECHNICIAN_PM_SECTIONS}
    _title_canonical = {s["title"].upper(): s["title"] for s in TECHNICIAN_PM_SECTIONS}
    header_rows = []
    sections = []
    insights = {}
    photos = []
    signature_url = ""
    mode = "start"
    current_section = None
    current_insight_key = None
    current_photo = None
    for raw_line in (details_text or "").splitlines():
        clean = raw_line.strip()
        if clean == "PM FORM HEADER":
            mode = "header"
            continue
        if clean == "SMART INSIGHTS":
            mode = "insights"
            current_insight_key = None
            continue
        if clean == "PHOTO SPECIFICATIONS":
            mode = "photos"
            current_photo = None
            continue
        if not clean:
            continue
        if clean.upper() in _title_upper_set:
            mode = "section"
            current_section = {"title": _title_canonical[clean.upper()], "rows": []}
            sections.append(current_section)
            continue
        if mode == "header":
            if ":" in clean and not clean.startswith("- "):
                label, _, value = clean.partition(":")
                header_rows.append((label.strip(), value.strip()))
            continue
        if mode == "section" and current_section is not None:
            if clean.startswith("- ") and ":" in clean:
                field_part = clean[2:]
                label, _, value = field_part.partition(":")
                current_section["rows"].append((label.strip(), value.strip()))
            continue
        if mode == "insights":
            if clean.startswith("- ") and current_insight_key is not None:
                insights.setdefault(current_insight_key, [])
                insights[current_insight_key].append(clean[2:].strip())
            elif ":" in clean and not clean.startswith("- "):
                label, _, value = clean.partition(":")
                label_clean = label.strip()
                label_lower = label_clean.lower()
                if label_lower in {
                    "risk score",
                    "risk level",
                    "critical",
                    "sla deadline (utc)",
                    "outage detected",
                    "operational category",
                    "incident categories",
                    "issue summary",
                    "sla breach category",
                }:
                    insights[label_clean] = value.strip()
                    current_insight_key = None
                elif label_lower in {"critical flags", "anomalies", "recommendations"}:
                    insights.setdefault(label_clean, [])
                    current_insight_key = label_clean
                elif label_lower in {"detected snags"}:
                    insights.setdefault(label_clean, [])
                    current_insight_key = label_clean
            continue
        if mode == "photos":
            if clean.startswith("- ") and ":" in clean:
                field_part = clean[2:]
                label, _, url_val = field_part.partition(":")
                current_photo = {"label": label.strip(), "url": url_val.strip(), "description": ""}
                photos.append(current_photo)
            elif raw_line.startswith("  ") and current_photo is not None:
                if clean.lower().startswith("system description:"):
                    current_photo["description"] = clean[len("System description:"):].strip()
            elif ":" in clean and not clean.startswith("- "):
                label, _, value = clean.partition(":")
                if "technician signature" in label.lower():
                    signature_url = value.strip()
            continue
    if expected_photo_labels:
        photo_by_label = {item["label"]: item for item in photos}
        photos = [
            photo_by_label.get(label, {"label": label, "url": "", "description": ""})
            for label in expected_photo_labels
        ]
    return {
        "header_rows": header_rows,
        "sections": sections,
        "insights": insights,
        "photos": photos,
        "signature_url": signature_url,
    }

def _resolve_uploaded_image_path(image_url, upload_folder):
    raw_url = (image_url or "").strip()
    if not raw_url:
        return None
    parsed = urlparse(raw_url)
    candidate_name = os.path.basename(parsed.path or raw_url)
    if not candidate_name:
        return None
    upload_root = os.path.abspath(upload_folder)
    candidate_path = os.path.abspath(os.path.join(upload_root, candidate_name))
    if os.path.commonpath([upload_root, candidate_path]) == upload_root and os.path.isfile(candidate_path):
        if _is_valid_image_file_path(candidate_path):
            return candidate_path

    # Fallback support: images may be stored in a shared sibling uploads folder.
    alternate_upload_root = os.path.abspath(os.path.join(upload_root, os.pardir, "uploads"))
    fallback_path = os.path.abspath(os.path.join(alternate_upload_root, candidate_name))
    if os.path.commonpath([alternate_upload_root, fallback_path]) == alternate_upload_root and os.path.isfile(fallback_path):
        if _is_valid_image_file_path(fallback_path):
            return fallback_path

    return None

