import csv
import json
import shutil
import time
from datetime import UTC
from html import escape
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import gradio as gr

import config
from src.database.models import (
    CALL_STATUS_BLOCKED,
    CALL_STATUS_COMPLETED,
    CALL_STATUS_FAILED,
    CALL_STATUS_FLAGGED,
)
from src.database.repository import (
    get_all_calls,
    get_call_by_id,
    get_call_status_counts,
    get_recent_audit_logs,
    get_report_by_call_id,
    get_table_counts,
)
from src.graph.pipeline import pipeline
from src.services.audio.transcriber import preload_whisper_model
from src.services.audio.validator import validate_audio

AUDIT_LOG_HEADERS = ["Time", "Severity", "Event", "Call ID", "Message"]
EMPTY_AUDIT_LOG_ROWS = [["", "", "", "", ""]]
DISPLAY_TIMEZONE = ZoneInfo("America/Los_Angeles")
DISPLAY_TIMEZONE_LABEL = "Pacific Time"
AUDIT_EVENT_LABELS = {
    "intake": "Intake",
    "transcription": "Transcription",
    "injection_scan": "Injection Scan",
    "pii_scan": "PII Scan",
    "summary": "Summary",
    "qa_scoring": "QA Scoring",
    "supervisor_review": "Supervisor Review",
    "report_generation": "Report Generation",
    "pipeline": "Pipeline",
    # Labels for rows written by older app versions.
    "intake_validated": "Intake Validated",
    "transcription_completed": "Transcription Completed",
    "transcription_cache_hit": "Transcript Cache Hit",
    "injection_scan_clean": "Injection Scan Clean",
    "injection_detected": "Injection Detected",
    "pii_scan_clean": "PII Scan Clean",
    "pii_redacted": "PII Redacted",
    "summary_generated": "Summary Generated",
    "qa_scoring_completed": "QA Scoring Completed",
    "supervisor_review_flagged": "Supervisor Review Flagged",
    "report_generated": "Report Generated",
    "pipeline_failed": "Pipeline Failed",
    # Labels for rows written by older app versions.
    "pipeline_started": "Intake Validated",
    "transcription_complete": "Transcription Completed",
    "analysis_complete": "Analysis Step Completed",
    "pii_detected": "PII Redacted",
}
PIPELINE_PROGRESS = {
    "intake": (12, "Validating intake"),
    "transcription": (35, "Transcribing audio"),
    "injection_check": (48, "Scanning for injection"),
    "pii_redaction": (58, "Checking PII"),
    "summarize_qa": (82, "Generating summary and QA"),
    "supervisor": (88, "Checking supervisor review"),
    "report": (100, "Reports generated"),
    "error": (100, "Pipeline stopped"),
}
PIPELINE_NEXT_STEP = {
    "intake": "transcription",
    "transcription": "injection_check",
    "injection_check": "pii_redaction",
    "pii_redaction": "summarize_qa",
    "summarize_qa": "report",
    "supervisor": "report",
}

APP_CSS = """
:root {
    --brand: #2f6f63;
    --brand-dark: #1f4f47;
    --accent: #586174;
    --conversation-agent: #345f92;
    --conversation-agent-label: #2f527b;
    --ink: #1f2937;
    --muted: #667085;
    --line: #d7dde6;
    --surface: #f4f6f8;
    --panel: #ffffff;
    --success: #17845b;
    --warning: #a15c07;
    --danger: #b42318;
}

.gradio-container {
    max-width: none !important;
    width: 100vw !important;
    min-height: 100vh !important;
    margin: 0 !important;
    background: #f4f6f8 !important;
    color: var(--ink) !important;
}

.app-shell {
    width: 100% !important;
    padding: 12px 18px 18px;
}

.app-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 24px;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: #ffffff;
    padding: 10px 12px;
    margin-bottom: 10px;
    box-shadow: 0 1px 3px rgba(31, 41, 55, 0.04);
}

.gradio-container .block-info {
    background: #eef2f5 !important;
    color: #344054 !important;
    border-radius: 6px !important;
}

.gradio-container label,
.gradio-container label span,
.gradio-container .block label,
.gradio-container .block label span,
.gradio-container .block-info {
    color: #344054 !important;
}

.gradio-container label > span,
.gradio-container .block-info {
    background: #eef2f5 !important;
    border-color: #d7dde6 !important;
}

.app-brand {
    display: flex;
    align-items: center;
    gap: 10px;
}

.app-logo {
    display: grid;
    width: 34px;
    height: 34px;
    place-items: center;
    border-radius: 8px;
    color: white;
    background: var(--brand);
    font-weight: 900;
}

.app-kicker {
    margin: 0;
    color: var(--muted);
    font-size: 11px;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

.app-header h1 {
    margin: 0;
    font-size: 20px;
    line-height: 1.1;
    letter-spacing: 0;
}

.app-header p {
    margin: 0;
    max-width: 520px;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.35;
}

.section-title h2 {
    margin: 0 0 4px;
    font-size: 19px;
}

.section-title p {
    margin: 0 0 14px;
    color: var(--muted);
    font-size: 13px;
}

.input-panel,
.output-panel,
.observability-panel {
    background: var(--panel);
    border: 1px solid #e5e9f0;
    border-radius: 8px;
    padding: 12px;
    box-shadow: 0 1px 3px rgba(23, 33, 43, 0.04);
}

#analysis-layout,
.analysis-layout {
    display: grid !important;
    grid-template-columns: minmax(300px, 360px) minmax(0, 1fr) !important;
    gap: 12px !important;
    align-items: start !important;
    width: 100% !important;
}

#analysis-layout > *,
.analysis-layout > * {
    min-width: 0 !important;
    width: 100% !important;
}

.output-panel {
    min-height: calc(100vh - 210px);
}

.workspace-grid {
    display: grid;
    grid-template-columns: minmax(0, 1.35fr) minmax(300px, 0.65fr);
    gap: 12px;
    align-items: start;
}

.workspace-main,
.workspace-side {
    display: grid;
    gap: 12px;
}

.workspace-main {
    min-height: 0;
}

.workspace-side {
    max-height: calc(100vh - 320px);
    min-height: 0;
    overflow-y: auto;
    padding-right: 4px;
    scrollbar-gutter: stable;
}

.workspace-side::after {
    position: sticky;
    bottom: 0;
    display: block;
    height: 22px;
    margin-top: -22px;
    pointer-events: none;
    background: linear-gradient(180deg, rgba(255,255,255,0), #ffffff 82%);
    content: "";
}

.analyze-button,
.refresh-button,
.export-button,
.report-download,
.csv-download {
    border-radius: 7px !important;
    font-weight: 700 !important;
}

.analyze-button,
.report-download,
.export-button,
.csv-download,
.analyze-button button,
.report-download button,
.export-button button,
.csv-download button {
    background: var(--brand) !important;
    border-color: var(--brand) !important;
    color: white !important;
}

.analyze-button:hover,
.report-download:hover,
.export-button:hover,
.csv-download:hover,
.analyze-button button:hover,
.report-download button:hover,
.export-button button:hover,
.csv-download button:hover {
    background: var(--brand-dark) !important;
}

.refresh-button,
.refresh-button button {
    background: #eef2f1 !important;
    border-color: #c9d6d3 !important;
    color: var(--brand-dark) !important;
}

.history-action,
.history-action button {
    background: var(--brand) !important;
    border-color: var(--brand) !important;
    color: white !important;
}

.history-action:hover,
.history-action button:hover {
    background: var(--brand-dark) !important;
}

.history-summary-panel {
    display: grid;
    gap: 8px;
    border: 1px solid #dfe7ef;
    border-radius: 8px;
    padding: 12px;
    background: #ffffff;
}

.history-stat,
.history-latest {
    display: grid;
    gap: 2px;
}

.history-stat span,
.history-latest span {
    color: var(--muted);
    font-size: 12px;
    font-weight: 800;
    text-transform: uppercase;
}

.history-stat strong,
.history-latest strong {
    color: var(--ink);
    font-size: 16px;
}

.history-latest small {
    color: var(--muted);
}

.history-radio label {
    border-radius: 7px !important;
}

.history-radio .wrap {
    gap: 6px !important;
}

.status-box {
    border-left: 0;
}

.status-card {
    border: 1px solid #cbded9;
    border-left: 5px solid var(--brand);
    border-radius: 8px;
    padding: 12px;
    background: #f1f6f4;
}

.status-title {
    margin: 0 0 5px;
    color: var(--ink);
    font-size: 15px;
    font-weight: 850;
}

.status-detail {
    margin: 0;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.45;
}

.progress-row {
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 10px;
    align-items: center;
    margin: 10px 0 8px;
    color: var(--brand-dark);
    font-size: 12px;
    font-weight: 850;
}

.progress-track {
    height: 7px;
    overflow: hidden;
    border-radius: 999px;
    background: #d8e5e1;
}

.progress-bar {
    height: 100%;
    border-radius: inherit;
    background: var(--brand);
    transition: width 240ms ease;
    position: relative;
}

.progress-bar::after {
    content: none;
}

@keyframes progress-shine {
    from {
        transform: translateX(-100%);
    }
    to {
        transform: translateX(100%);
    }
}

.report-panel {
    border-top: 1px solid #e5e9f0;
    margin-top: 12px;
    padding-top: 12px;
}

.report-panel-title {
    margin: 0 0 4px;
    color: var(--muted);
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}

.report-panel-status {
    margin: 0 0 10px;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.4;
}

.report-panel-ready .report-panel-status {
    color: var(--brand-dark);
    font-weight: 700;
}

.download-row {
    gap: 8px !important;
}

.audio-upload-preview {
    min-height: 260px;
}

.audio-upload-preview audio,
.audio-upload-preview canvas {
    width: 100% !important;
}

.report-download {
    min-height: 40px !important;
}

.report-download[disabled],
.csv-download[disabled],
.report-download button:disabled,
.csv-download button:disabled,
.report-download button[aria-disabled="true"],
.csv-download button[aria-disabled="true"] {
    background: #f3f6f8 !important;
    border-color: #e1e7ef !important;
    color: #8a94a3 !important;
    box-shadow: none !important;
}

.conversation-panel {
    border: 1px solid #e4e9f1;
    border-radius: 8px;
    background: #ffffff;
    overflow: hidden;
}

.conversation-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    background: #f1f4f5;
    border-bottom: 1px solid #e4e9f1;
}

.conversation-title {
    margin: 0;
    font-size: 18px;
    font-weight: 800;
}

.conversation-pills {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
}

.conversation-pill {
    border-radius: 999px;
    padding: 5px 11px;
    font-size: 12px;
    font-weight: 800;
    white-space: nowrap;
}

.conversation-pill-live {
    color: white;
    background: var(--brand);
}

.conversation-pill-confidence {
    color: #3d4a5c;
    background: #e8ebf2;
}

.conversation-pill-warning {
    color: #92400e;
    background: #fff3d6;
}

.conversation-body {
    padding: 14px 14px 16px;
    max-height: clamp(320px, calc(100vh - 360px), 560px);
    overflow-y: auto;
    scrollbar-gutter: stable;
}

.conversation-row {
    display: flex;
    flex-direction: column;
    margin-bottom: 14px;
}

.conversation-row-customer {
    align-items: flex-end;
}

.speaker-meta {
    display: flex;
    gap: 8px;
    align-items: baseline;
    margin-bottom: 7px;
    color: #667085;
    font-size: 12px;
    font-weight: 800;
    text-transform: uppercase;
}

.conversation-row-customer .speaker-meta {
    justify-content: flex-end;
}

.speaker-name-agent {
    color: var(--conversation-agent-label);
}

.speaker-name-customer {
    color: #475467;
}

.conversation-bubble {
    width: min(86%, 820px);
    border-radius: 8px;
    padding: 11px 13px;
    font-size: 14px;
    line-height: 1.5;
    overflow-wrap: anywhere;
}

.conversation-bubble-agent {
    color: white;
    background: var(--conversation-agent);
}

.conversation-bubble-customer {
    color: #1d2939;
    background: #f4f5f9;
    border: 1px solid #dfe3ec;
}

.conversation-summary {
    display: flex;
    gap: 12px;
    margin: 4px 0 16px;
    padding: 11px 12px;
    border-left: 5px solid var(--success);
    border-radius: 7px;
    color: #14532d;
    background: #edf6f1;
}

.conversation-audio-warning {
    margin: 0 0 14px;
    padding: 10px 12px;
    border-left: 5px solid var(--warning);
    border-radius: 7px;
    color: #7c2d12;
    background: #fff7ed;
    font-size: 13px;
    font-weight: 700;
}

.transcript-box textarea {
    min-height: 160px !important;
    max-height: 34vh !important;
    overflow-y: auto !important;
}

.raw-transcript-panel {
    border: 1px solid #e4e9f1;
    border-radius: 8px;
    background: #ffffff;
    padding: 12px;
}

.raw-transcript-title {
    margin: 0 0 8px;
    color: #344054;
    font-size: 14px;
    font-weight: 850;
}

.content-panel {
    border: 1px solid #e4e9f1;
    border-radius: 8px;
    background: var(--panel);
    overflow: hidden;
}

.content-panel-header {
    padding: 12px 14px;
    background: #f3f4f8;
    border-bottom: 1px solid #e4e9f1;
}

.content-panel-title {
    margin: 0;
    font-size: 16px;
    font-weight: 850;
}

.content-panel-body {
    padding: 14px;
}

.summary-accordion {
    display: grid;
    gap: 9px;
}

.summary-section {
    border: 1px solid #e1e7ef;
    border-radius: 7px;
    background: #ffffff;
}

.summary-section summary {
    cursor: pointer;
    padding: 11px 12px;
    color: #1f2937;
    font-size: 13px;
    font-weight: 850;
    list-style: none;
}

.summary-section summary::-webkit-details-marker {
    display: none;
}

.summary-section summary::after {
    float: right;
    color: #667085;
    content: "+";
    font-weight: 900;
}

.summary-section[open] summary {
    border-bottom: 1px solid #edf1f5;
    background: #f7f9fb;
}

.summary-section[open] summary::after {
    content: "-";
}

.summary-section-body {
    padding: 11px 12px 12px;
}

.summary-section-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 9px;
}

.summary-section-list {
    margin: 0;
    padding-left: 18px;
}

.summary-section-list li {
    margin-bottom: 6px;
    color: #111827;
    font-size: 14px;
    line-height: 1.45;
    font-weight: 600;
}

.summary-grid,
.qa-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
}

.compliance-evidence-grid {
    margin-top: 10px;
}

.summary-card,
.qa-card {
    border: 1px solid #edf1f5;
    border-radius: 7px;
    padding: 10px 11px;
    background: #ffffff;
}

.summary-card-wide {
    grid-column: 1 / -1;
}

.summary-label,
.qa-label {
    margin: 0 0 5px;
    color: #2f6f63;
    font-size: 11px;
    font-weight: 800;
    text-transform: uppercase;
}

.summary-value,
.qa-value {
    margin: 0;
    color: #111827;
    font-size: 14px;
    line-height: 1.45;
    font-weight: 600;
}

.usage-inline {
    margin-top: 10px;
    border-top: 1px solid #e5e9f0;
    padding-top: 9px;
    color: #334155;
    font-size: 12px;
    line-height: 1.4;
}

.qa-value {
    font-size: 20px;
    font-weight: 850;
}

.conversation-summary-icon {
    width: 24px;
    flex: 0 0 24px;
    font-weight: 900;
}

.conversation-summary-title {
    margin: 0 0 3px;
    font-size: 12px;
    font-weight: 900;
    letter-spacing: 0.02em;
    text-transform: uppercase;
}

.conversation-summary-text {
    margin: 0;
    font-size: 13px;
    line-height: 1.45;
}

.conversation-empty {
    padding: 44px 18px;
    color: var(--muted);
    text-align: center;
}

.placeholder-panel {
    padding: 18px 14px;
    color: var(--muted);
    font-size: 13px;
    line-height: 1.45;
}

textarea {
    font-size: 13px !important;
    line-height: 1.45 !important;
}

.metrics-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(130px, 1fr));
    gap: 10px;
    margin-bottom: 12px;
}

.metric-card {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: 8px;
    padding: 11px 12px;
    min-height: 76px;
}

.metric-label {
    color: var(--muted);
    font-size: 12px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.02em;
}

.metric-value {
    color: var(--ink);
    font-size: 28px;
    line-height: 1.2;
    font-weight: 800;
    margin-top: 7px;
}

.langsmith-status {
    margin: 2px 0 18px;
    color: var(--muted);
    font-size: 13px;
}

.storage-status {
    margin: 4px 0 16px;
    border-radius: 8px;
    padding: 10px 12px;
    background: #f8fafc;
    color: #334155;
    font-size: 13px;
    line-height: 1.45;
}

.storage-status strong {
    color: var(--ink);
}

.storage-warning {
    margin-top: 6px;
    color: #9a3412;
    font-weight: 750;
}

.audit-note {
    margin: 0 0 8px;
    color: var(--muted);
    font-size: 13px;
}

.audit-table-wrap {
    max-height: 440px;
    overflow-y: auto;
    border: 1px solid var(--line);
    border-radius: 8px;
    background: white;
}

.audit-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
    table-layout: fixed;
}

.audit-table th {
    position: sticky;
    top: 0;
    z-index: 1;
    background: #eef4f5;
    color: var(--ink);
    text-align: left;
    padding: 12px 14px;
    border-bottom: 1px solid var(--line);
}

.audit-table td {
    padding: 13px 14px;
    border-bottom: 1px solid #edf1f3;
    vertical-align: middle;
    overflow-wrap: anywhere;
}

.audit-table tr:hover td {
    background: #f8fbfc;
}

.audit-time {
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
}

.severity-pill {
    display: inline-block;
    min-width: 64px;
    border-radius: 999px;
    padding: 4px 8px;
    text-align: center;
    font-weight: 700;
    font-size: 12px;
}

.severity-error {
    color: var(--danger);
    background: #fff1ef;
}

.severity-warning {
    color: var(--warning);
    background: #fff7e8;
}

.severity-info {
    color: var(--success);
    background: #eef8f3;
}

@media (max-width: 860px) {
    .app-header {
        display: block;
    }

    .workspace-grid {
        grid-template-columns: 1fr;
    }

    .analysis-layout {
        grid-template-columns: 1fr !important;
    }

    .metrics-grid {
        grid-template-columns: repeat(2, minmax(130px, 1fr));
    }

    .summary-grid,
    .qa-grid,
    .summary-section-grid {
        grid-template-columns: 1fr;
    }

    .workspace-side {
        max-height: none;
        overflow-y: visible;
        padding-right: 0;
    }

    .workspace-side::after {
        content: none;
    }
}

@media (max-width: 620px) {
    .app-shell {
        padding: 14px;
    }

    .metrics-grid {
        grid-template-columns: 1fr;
    }

    .conversation-header {
        align-items: flex-start;
        flex-direction: column;
    }

    .conversation-bubble {
        width: 100%;
    }
}
"""


def format_status_html(
    title: str,
    detail: str = "",
    *,
    in_progress: bool = False,
    percent: int | None = None,
) -> str:
    """Format pipeline status with optional animated progress."""
    progress_label = f"<span>{escape(title)} · {percent}%</span>" if percent is not None else ""
    progress_html = (
        "<div class='progress-row'>"
        "<div class='progress-track'>"
        f"<div class='progress-bar' style='width: {percent or 35}%'></div>"
        "</div>"
        f"{progress_label}"
        "</div>"
        if in_progress
        else ""
    )
    return (
        "<div class='status-card'>"
        f"<p class='status-title'>{escape(title)}</p>"
        f"{progress_html}"
        f"<p class='status-detail'>{escape(detail)}</p>"
        "</div>"
    )


def approximate_processing_seconds(audio_duration: float | None, cached: bool) -> int:
    """Estimate runtime from audio duration and whether transcription is cached."""
    duration = audio_duration or 60
    if cached:
        return max(12, min(75, round(10 + duration * 0.08)))
    return max(25, min(180, round(20 + duration * 0.35)))


def format_duration_range(seconds: int) -> str:
    """Format an approximate runtime as a compact range."""
    low = max(5, round(seconds * 0.75))
    high = max(low + 5, round(seconds * 1.25))

    if high < 60:
        return f"about {low}-{high} seconds"

    low_minutes = max(1, round(low / 60))
    high_minutes = max(low_minutes, round(high / 60))
    if low_minutes == high_minutes:
        return f"about {high_minutes} minute"
    return f"about {low_minutes}-{high_minutes} minutes"


def format_elapsed_time(seconds: float) -> str:
    """Format elapsed processing time for final status messages."""
    if seconds < 60:
        return f"{seconds:.1f} seconds"

    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{int(minutes)} min {remaining_seconds:.1f} sec"


def get_processing_message(audio_path: str) -> str:
    from src.services.audio.cache import compute_hash, get_cached_transcript

    file_hash = compute_hash(audio_path)
    cached = bool(get_cached_transcript(file_hash))
    validation = validate_audio(audio_path)
    time_estimate = format_duration_range(
        approximate_processing_seconds(validation.duration, cached)
    )

    if cached:
        detail = (
            "Cached transcript found. Running fresh summary, QA scoring, "
            f"and report generation; expected {time_estimate}."
        )
    else:
        detail = (
            "Transcribing audio, then running security checks, summary, QA scoring, "
            f"and reports; expected {time_estimate}."
        )

    return format_status_html(
        "Analysis in progress",
        detail,
        in_progress=True,
        percent=5,
    )


def build_progress_status(node_name: str) -> str:
    """Return status HTML for a completed pipeline node."""
    percent, label = PIPELINE_PROGRESS.get(node_name, (5, "Analysis running"))
    return format_status_html(
        label,
        "Pipeline is moving through the analysis graph.",
        in_progress=percent < 100,
        percent=percent,
    )


def build_next_step_status(node_name: str) -> str | None:
    """Return status HTML for the next long-running pipeline step."""
    next_node = PIPELINE_NEXT_STEP.get(node_name)
    if not next_node:
        return None

    percent, label = PIPELINE_PROGRESS[next_node]
    return format_status_html(
        label,
        "Working on this step now.",
        in_progress=percent < 100,
        percent=percent,
    )


def empty_report_downloads() -> tuple:
    """Return disabled report download controls while reports are not ready."""
    return (
        gr.update(value=None, label="PDF report pending", interactive=False),
        gr.update(value=None, label="JSON report pending", interactive=False),
    )


def ready_report_downloads(
    report_path: str | None,
    json_report_path: str | None,
) -> tuple:
    """Return report download controls with generated files when available."""
    report_path = resolve_download_path(report_path)
    json_report_path = resolve_download_path(json_report_path)
    return (
        gr.update(
            value=report_path,
            label="Download PDF report" if report_path else "PDF report unavailable",
            interactive=bool(report_path),
        ),
        gr.update(
            value=json_report_path,
            label="Download JSON report" if json_report_path else "JSON report unavailable",
            interactive=bool(json_report_path),
        ),
    )


def resolve_download_path(path: str | None) -> str | None:
    """Return an existing report path, allowing for host/container path changes."""
    if not path:
        return None

    candidate = Path(path)
    if candidate.exists():
        return str(candidate)

    mounted_candidate = config.REPORTS_DIR / candidate.name
    if mounted_candidate.exists():
        return str(mounted_candidate)

    return None


def format_report_panel_html(ready: bool = False) -> str:
    """Return the report panel header and empty/ready state copy."""
    panel_class = "report-panel report-panel-ready" if ready else "report-panel"
    status = (
        "Reports are ready to download."
        if ready
        else "PDF and JSON reports will be available after analysis."
    )
    return (
        f"<div class='{panel_class}'>"
        "<p class='report-panel-title'>Generated Reports</p>"
        f"<p class='report-panel-status'>{escape(status)}</p>"
        "</div>"
    )


def format_injection_block_detail(result: dict) -> str:
    """Return a user-facing reason for prompt-injection blocking."""
    patterns = result.get("injection_patterns") or []
    if not patterns:
        return "Pipeline stopped before summary and QA scoring."

    pattern_text = ", ".join(str(pattern) for pattern in patterns)
    return (
        "Pipeline stopped before summary and QA scoring. "
        f"Matched injection patterns: {pattern_text}."
    )


def empty_analysis_outputs() -> tuple:
    """Return unchanged/empty outputs while progress advances."""
    return (
        format_conversation_html({}),
        "",
        format_summary_html({}),
        format_qa_scorecard_html({}),
        format_report_panel_html(False),
        *empty_report_downloads(),
    )


def copy_audio_to_data_dir(audio_path: str) -> str:
    """Copy a Gradio temp upload into the project audio directory."""
    source_path = Path(audio_path)
    config.AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    if source_path.resolve().parent == config.AUDIO_DIR.resolve():
        return str(source_path)

    destination_path = (
        config.AUDIO_DIR / f"{source_path.stem}_{uuid4().hex[:8]}{source_path.suffix}"
    )
    shutil.copy2(source_path, destination_path)
    return str(destination_path)


def format_summary_html(result: dict) -> str:
    """Format summary details as expandable sections."""
    result = hydrate_summary_result(result)
    if not result.get("summary"):
        return (
            "<div class='content-panel'>"
            "<div class='content-panel-header'>"
            "<h3 class='content-panel-title'>Summary</h3>"
            "</div>"
            "<div class='placeholder-panel'>Summary details will appear after analysis.</div>"
            "</div>"
        )

    usage = get_token_usage(result)
    context_cards = format_summary_cards(
        [
            ("Sentiment", result.get("sentiment") or "N/A"),
            ("Call Purpose", result.get("call_purpose") or "N/A"),
            ("Resolution Status", result.get("resolution_status") or "N/A"),
            ("Sentiment Trajectory", result.get("sentiment_trajectory") or "N/A"),
            ("Key Entities", format_summary_list(result.get("key_entities")), True),
        ],
    )
    follow_up_html = (
        "<div class='summary-section-grid'>"
        f"{format_summary_list_card('Key Discussion Points', result.get('key_discussion_points'))}"
        f"{format_summary_list_card('Action Items', result.get('action_items'))}"
        "</div>"
    )
    review_cards = format_summary_cards(
        [
            ("Agent Behavior", result.get("agent_behavior") or "N/A", True),
            ("Compliance Flag", str(result.get("compliance_flag", "N/A"))),
            ("Overall QA", str(result.get("overall_score", "N/A"))),
        ],
    )
    sections = "".join(
        [
            format_summary_section_html(
                "Executive Summary",
                (
                    "<p class='summary-value'>"
                    f"{escape(str(result.get('summary') or 'No summary was generated.'))}"
                    "</p>"
                ),
                open_by_default=True,
            ),
            format_summary_section_html(
                "Call Context",
                f"<div class='summary-section-grid'>{context_cards}</div>",
                open_by_default=True,
            ),
            format_summary_section_html(
                "Discussion Points and Action Items",
                follow_up_html,
            ),
            format_summary_section_html(
                "Agent and Compliance Review",
                f"<div class='summary-section-grid'>{review_cards}</div>",
            ),
        ],
    )

    return (
        "<div class='content-panel'>"
        "<div class='content-panel-header'>"
        "<h3 class='content-panel-title'>Summary</h3>"
        "</div>"
        "<div class='content-panel-body'>"
        f"<div class='summary-accordion'>{sections}</div>"
        "<div class='usage-inline'>"
        f"{format_usage_label(usage)} summary tokens: "
        f"input {usage['summary_input']:,}, "
        f"output {usage['summary_output']:,}, "
        f"total {usage['summary_total']:,}"
        "</div>"
        "</div>"
        "</div>"
    )


def format_summary_section_html(
    title: str,
    body_html: str,
    *,
    open_by_default: bool = False,
) -> str:
    """Format an expandable summary section."""
    open_attr = " open" if open_by_default else ""
    return (
        f"<details class='summary-section'{open_attr}>"
        f"<summary>{escape(title)}</summary>"
        f"<div class='summary-section-body'>{body_html}</div>"
        "</details>"
    )


def format_summary_cards(fields: list[tuple]) -> str:
    """Format summary fields as cards inside an accordion."""
    cards = ""
    for field in fields:
        label = field[0]
        value = field[1]
        wide = bool(field[2]) if len(field) > 2 else False
        cards += (
            f"<div class='summary-card {'summary-card-wide' if wide else ''}'>"
            f"<p class='summary-label'>{escape(label)}</p>"
            f"<p class='summary-value'>{escape(str(value))}</p>"
            "</div>"
        )
    return cards


def format_summary_list_card(label: str, value) -> str:
    """Format a list-valued summary field as a readable card."""
    return (
        "<div class='summary-card summary-card-wide'>"
        f"<p class='summary-label'>{escape(label)}</p>"
        f"{format_summary_list_html(value)}"
        "</div>"
    )


def format_summary_list_html(value) -> str:
    """Format SummaryResult list fields as HTML list content."""
    if not value:
        return "<p class='summary-value'>N/A</p>"

    if isinstance(value, str):
        return f"<p class='summary-value'>{escape(value)}</p>"

    items = "".join(f"<li>{escape(str(item))}</li>" for item in value)
    return f"<ul class='summary-section-list'>{items}</ul>"


def format_summary_list(value) -> str:
    """Format SummaryResult list fields for compact display."""
    if not value:
        return "N/A"

    if isinstance(value, str):
        return value

    return "\n".join(f"- {item}" for item in value)


def hydrate_summary_result(result: dict) -> dict:
    """Fill missing summary UI fields from structured summary/report JSON."""
    hydrated = dict(result)
    summary_data = parse_summary_payload(hydrated.get("summary_json"))
    report_summary_data = parse_report_summary_payload(hydrated.get("report_json"))

    for source in (summary_data, report_summary_data):
        for key in (
            "summary",
            "sentiment",
            "agent_behavior",
            "call_purpose",
            "key_entities",
            "key_discussion_points",
            "action_items",
            "resolution_status",
            "sentiment_trajectory",
        ):
            if not hydrated.get(key) and source.get(key):
                hydrated[key] = source[key]

    return hydrated


def parse_summary_payload(summary_json: str | None) -> dict:
    """Parse SummaryResult JSON from the pipeline state."""
    if not summary_json:
        return {}

    try:
        payload = json.loads(summary_json)
    except (TypeError, json.JSONDecodeError):
        return {}

    return payload if isinstance(payload, dict) else {}


def parse_report_summary_payload(report_json: str | None) -> dict:
    """Parse nested summary details from generated report JSON."""
    payload = parse_report_json(report_json)
    summary_data = payload.get("summary", {})
    return summary_data if isinstance(summary_data, dict) else {}


def format_qa_scorecard_html(result: dict) -> str:
    """Format QA scores as a stable HTML scorecard."""
    qa_scores = result.get("qa_scores") or {}
    if not qa_scores and result.get("overall_score") is None:
        return (
            "<div class='content-panel'>"
            "<div class='content-panel-header'>"
            "<h3 class='content-panel-title'>QA Scorecard</h3>"
            "</div>"
            "<div class='placeholder-panel'>QA scores will appear after analysis.</div>"
            "</div>"
        )

    usage = get_token_usage(result)
    fields = [
        ("Overall", result.get("overall_score", "N/A")),
        ("Empathy", qa_scores.get("empathy_score", "N/A")),
        ("Resolution", qa_scores.get("resolution_score", "N/A")),
        ("Compliance", qa_scores.get("compliance_score", "N/A")),
        ("Communication", qa_scores.get("communication_score", "N/A")),
        ("Professionalism", qa_scores.get("professionalism_score", "N/A")),
    ]
    cards = "".join(
        (
            "<div class='qa-card'>"
            f"<p class='qa-label'>{escape(label)}</p>"
            f"<p class='qa-value'>{escape(str(value))}</p>"
            "</div>"
        )
        for label, value in fields
    )
    evidence = result.get("timestamp_evidence") or []
    evidence_text = (
        ", ".join(str(item) for item in evidence) if evidence else "No timestamp evidence"
    )
    compliance_details = [
        ("Severity", result.get("compliance_severity") or "none"),
        (
            "Violation",
            result.get("violation_description") or "No violation detected",
        ),
        ("Evidence", evidence_text),
    ]
    compliance_cards = "".join(
        (
            "<div class='summary-card summary-card-wide'>"
            f"<p class='summary-label'>{escape(label)}</p>"
            f"<p class='summary-value'>{escape(str(value))}</p>"
            "</div>"
        )
        for label, value in compliance_details
    )

    return (
        "<div class='content-panel'>"
        "<div class='content-panel-header'>"
        "<h3 class='content-panel-title'>QA Scorecard</h3>"
        "</div>"
        "<div class='content-panel-body'>"
        f"<div class='qa-grid'>{cards}</div>"
        f"<div class='summary-grid compliance-evidence-grid'>{compliance_cards}</div>"
        "<div class='usage-inline'>"
        f"{format_usage_label(usage)} QA tokens: input {usage['qa_input']:,}, "
        f"output {usage['qa_output']:,}, "
        f"total {usage['qa_total']:,}. "
        f"Combined summary + QA total: {usage['total']:,}"
        "</div>"
        "</div>"
        "</div>"
    )


def format_usage_label(usage: dict) -> str:
    """Return token usage label based on metadata source."""
    return "Actual" if usage.get("source") == "actual" else "Estimated"


def format_seconds(seconds: float | int | None) -> str:
    """Format a segment offset as MM:SS or HH:MM:SS."""
    if seconds is None:
        return "--:--"

    total_seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)

    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_confidence(confidence: float | int | None) -> str:
    """Format normalized confidence as a percentage."""
    if confidence is None:
        return "N/A"

    confidence_value = float(confidence)
    if confidence_value <= 1:
        confidence_value *= 100

    return f"{confidence_value:.1f}%"


def estimate_token_count(text: str | None) -> int:
    """Estimate token count for UI usage display."""
    if not text:
        return 0

    return max(1, round(len(text) / 4))


def get_token_usage(result: dict) -> dict[str, int]:
    """Return actual token usage when available, otherwise estimate it."""
    actual_usage = result.get("token_usage") or {}
    summary_actual = actual_usage.get("summary") or {}
    qa_actual = actual_usage.get("qa") or {}

    if summary_actual or qa_actual:
        summary_input = int(summary_actual.get("input_tokens", 0) or 0)
        summary_output = int(summary_actual.get("output_tokens", 0) or 0)
        qa_input = int(qa_actual.get("input_tokens", 0) or 0)
        qa_output = int(qa_actual.get("output_tokens", 0) or 0)
        summary_total = int(summary_actual.get("total_tokens", 0) or 0)
        qa_total = int(qa_actual.get("total_tokens", 0) or 0)
        if summary_total == 0:
            summary_total = summary_input + summary_output
        if qa_total == 0:
            qa_total = qa_input + qa_output

        actual = {
            "summary_input": summary_input,
            "summary_output": summary_output,
            "summary_total": summary_total,
            "qa_input": qa_input,
            "qa_output": qa_output,
            "qa_total": qa_total,
            "total": summary_total + qa_total,
            "source": "actual",
        }
        if actual["total"] > 0:
            return actual

    transcript = result.get("transcript") or ""
    summary = result.get("summary") or ""
    qa_scores = result.get("qa_scores") or {}

    if not transcript and not summary and not qa_scores:
        return {
            "summary_input": 0,
            "summary_output": 0,
            "summary_total": 0,
            "qa_input": 0,
            "qa_output": 0,
            "qa_total": 0,
            "total": 0,
            "source": "empty",
        }

    summary_input = estimate_token_count(transcript)
    summary_output = estimate_token_count(summary)
    qa_input = summary_input + summary_output
    qa_output = estimate_token_count(str(qa_scores)) + estimate_token_count(
        str(result.get("overall_score", ""))
    )
    summary_total = summary_input + summary_output
    qa_total = qa_input + qa_output

    return {
        "summary_input": summary_input,
        "summary_output": summary_output,
        "summary_total": summary_total,
        "qa_input": qa_input,
        "qa_output": qa_output,
        "qa_total": qa_total,
        "total": summary_total + qa_total,
        "source": "estimated",
    }


def get_display_segments(result: dict) -> list[dict]:
    """Return segments for the conversation UI, falling back to one transcript block."""
    segments = result.get("segments") or []
    if segments:
        return segments

    transcript = result.get("transcript") or ""
    if not transcript.strip():
        return []

    return [{"speaker": "Transcript", "start": None, "text": transcript}]


def normalize_speaker(speaker: str | None, index: int) -> tuple[str, str]:
    """Return speaker display text and CSS role."""
    if not speaker:
        speaker = "Agent" if index % 2 == 0 else "Customer"

    role = "agent" if speaker.lower().startswith("agent") else "customer"
    return speaker, role


def format_conversation_html(result: dict) -> str:
    """Format transcript segments as a speaker-bubble conversation."""
    segments = get_display_segments(result)
    if not segments:
        return (
            "<div class='conversation-panel'>"
            "<div class='conversation-empty'>Conversation will appear after analysis.</div>"
            "</div>"
        )

    summary = result.get("summary") or "Summary will appear after analysis."
    confidence = format_confidence(result.get("confidence"))
    low_quality_audio = bool(result.get("low_quality_audio"))
    quality_pill = (
        "<span class='conversation-pill conversation-pill-warning'>Low quality audio</span>"
        if low_quality_audio
        else ""
    )
    rows_html = []

    if low_quality_audio:
        rows_html.append(
            "<div class='conversation-audio-warning'>"
            "Transcript confidence is below the configured quality threshold. "
            "Review the transcript before relying on summary or QA scores."
            "</div>"
        )

    if summary:
        rows_html.append(
            "<div class='conversation-summary'>"
            "<div class='conversation-summary-icon'>AI</div>"
            "<div>"
            "<p class='conversation-summary-title'>AI Insight</p>"
            f"<p class='conversation-summary-text'>{escape(str(summary))}</p>"
            "</div>"
            "</div>"
        )

    for index, segment in enumerate(segments):
        speaker, role = normalize_speaker(segment.get("speaker"), index)
        timestamp = format_seconds(segment.get("start"))
        text = str(segment.get("text") or "").strip()
        if not text:
            continue

        rows_html.append(
            f"<div class='conversation-row conversation-row-{role}'>"
            "<div class='speaker-meta'>"
            f"<span class='speaker-name-{role}'>{escape(speaker)}</span>"
            f"<span>{escape(timestamp)}</span>"
            "</div>"
            f"<div class='conversation-bubble conversation-bubble-{role}'>"
            f"{escape(text)}"
            "</div>"
            "</div>"
        )

    body_html = "".join(rows_html)
    return f"""
<div class="conversation-panel">
    <div class="conversation-header">
        <h3 class="conversation-title">Speaker Transcript</h3>
        <div class="conversation-pills">
            <span class="conversation-pill conversation-pill-live">Analysis</span>
            <span class="conversation-pill conversation-pill-confidence">
                Confidence: {escape(confidence)}
            </span>
            {quality_pill}
        </div>
    </div>
    <div class="conversation-body">{body_html}</div>
</div>
"""


def get_json_report_path(report_path: str | None):
    """Return the generated JSON report path that matches the PDF report."""
    report_path = resolve_download_path(report_path)
    if not report_path:
        return None

    json_path = Path(report_path).with_suffix(".json")
    return resolve_download_path(str(json_path))


def add_report_json_to_result(result: dict, json_report_path: str | None) -> dict:
    """Attach generated report JSON to the final Analyze result when available."""
    if not json_report_path:
        return result

    try:
        report_json = Path(json_report_path).read_text()
    except OSError:
        return result

    return {**result, "report_json": report_json}


def get_mp3_history_records() -> list[tuple]:
    """Return MP3 call history records from the database."""
    try:
        calls = get_all_calls(limit=100)
    except Exception:
        return []

    records = []
    for call in calls:
        if Path(call.filename).suffix.lower() != ".mp3":
            continue

        try:
            report = get_report_by_call_id(call.id)
        except Exception:
            report = None

        records.append((call, report))

    return records


def load_call_history_summary():
    """Return a compact status summary for MP3 history."""
    records = get_mp3_history_records()
    if not records:
        return "<div class='placeholder-panel'>No analyzed MP3 calls yet.</div>"

    completed_count = sum(1 for call, _report in records if call.status == "completed")
    latest_call, latest_report = records[0]
    latest_score = f"{latest_report.overall_score:.1f}" if latest_report else "N/A"

    return (
        "<div class='history-summary-panel'>"
        "<div class='history-stat'>"
        "<span>Total MP3 calls</span>"
        f"<strong>{len(records)}</strong>"
        "</div>"
        "<div class='history-stat'>"
        "<span>Completed</span>"
        f"<strong>{completed_count}</strong>"
        "</div>"
        "<div class='history-latest'>"
        "<span>Latest</span>"
        f"<strong>{escape(latest_call.filename)}</strong>"
        f"<small>{escape(format_audit_timestamp(latest_call.created_at))} | "
        f"QA {escape(latest_score)}</small>"
        "</div>"
        "</div>"
    )


def load_history_choices():
    """Return dropdown choices for MP3 history detail loading."""
    choices = [format_history_choice(call, report) for call, report in get_mp3_history_records()]
    return gr.update(choices=choices, value=choices[0] if choices else None)


def refresh_history():
    """Refresh the history summary and selected-call choices together."""
    return load_call_history_summary(), load_history_choices()


def load_call_detail(selected_call: str | int | None):
    """Load one history call from DB and return Analyze-style detail outputs."""
    try:
        call_id = parse_history_choice_id(selected_call)
        if call_id is None:
            return empty_history_detail_outputs()

        call = get_call_by_id(call_id)
        if call is None:
            return empty_history_detail_outputs()

        report = get_report_by_call_id(call.id)
        result = build_history_result(call, report)
        report_path = resolve_download_path(report.pdf_path if report else None)
        json_report_path = get_history_json_report_path(call.id, report)
    except Exception:
        return empty_history_detail_outputs()

    return (
        format_conversation_html(result),
        call.transcription or "",
        format_summary_html(result),
        format_qa_scorecard_html(result),
        format_report_panel_html(bool(report_path or json_report_path)),
        *ready_report_downloads(report_path, json_report_path),
    )


def empty_history_detail_outputs() -> tuple:
    """Return empty Analyze-style outputs for history detail panels."""
    return (
        format_conversation_html({}),
        "",
        format_summary_html({}),
        format_qa_scorecard_html({}),
        format_report_panel_html(False),
        *empty_report_downloads(),
    )


def format_history_choice(call, report) -> str:
    """Return a readable radio choice with the DB id embedded up front."""
    score = f"{report.overall_score:.1f}" if report else "N/A"
    return (
        f"{call.id} - {call.filename} | "
        f"{call.created_at.strftime('%Y-%m-%d %H:%M')} | "
        f"{call.status} | QA {score}"
    )


def parse_history_choice_id(selected_call: str | int | None) -> int | None:
    """Extract a call id from the selected history radio value."""
    if selected_call is None:
        return None

    if isinstance(selected_call, int):
        return selected_call

    raw_value = str(selected_call).strip().split(" ", 1)[0]
    return int(raw_value) if raw_value.isdigit() else None


def build_history_result(call, report) -> dict:
    """Reconstruct the result dict used by Analyze Call display helpers."""
    report_data = parse_report_json(report.report_json if report else None)
    summary_data = report_data.get("summary", {})

    return {
        "transcript": call.transcription,
        "segments": call.segments,
        "confidence": call.confidence,
        "low_quality_audio": (
            call.confidence is not None and call.confidence < config.MIN_CONFIDENCE_THRESHOLD
        ),
        "summary": report.summary if report else None,
        "sentiment": call.sentiment,
        "call_purpose": call.call_purpose,
        "agent_behavior": summary_data.get("agent_behavior") or call.agent_behavior,
        "key_entities": summary_data.get("key_entities") or [],
        "key_discussion_points": summary_data.get("key_discussion_points") or [],
        "action_items": summary_data.get("action_items") or [],
        "resolution_status": summary_data.get("resolution_status"),
        "sentiment_trajectory": summary_data.get("sentiment_trajectory"),
        "compliance_flag": report.compliance_flag if report else None,
        "compliance_severity": report.compliance_severity if report else None,
        "violation_description": report.violation_description if report else None,
        "timestamp_evidence": report.timestamp_evidence if report else [],
        "overall_score": report.overall_score if report else None,
        "qa_scores": build_history_qa_scores(report),
    }


def build_history_qa_scores(report) -> dict:
    """Return QA scores in the same shape produced by the pipeline."""
    if report is None:
        return {}

    return {
        "empathy_score": report.empathy_score,
        "resolution_score": report.resolution_score,
        "compliance_score": report.compliance_score,
        "communication_score": report.communication_score,
        "professionalism_score": report.professionalism_score,
    }


def parse_report_json(report_json: str | None) -> dict:
    """Parse persisted report JSON, tolerating older rows with no JSON."""
    if not report_json:
        return {}

    try:
        return json.loads(report_json)
    except json.JSONDecodeError:
        return {}


def get_history_json_report_path(call_id: int, report) -> str | None:
    """Return a downloadable JSON report path for a persisted report."""
    if report is None:
        return None

    existing_path = get_json_report_path(report.pdf_path)
    if existing_path:
        return existing_path

    if not report.report_json:
        return None

    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = config.REPORTS_DIR / f"call_{call_id}_history_report.json"
    json_path.write_text(report.report_json)
    return str(json_path)


def get_observability_data():
    """Read pipeline metrics and audit log from DB."""
    try:
        audit_logs = get_recent_audit_logs(limit=200)
    except Exception as exc:
        audit_rows = [
            [
                "",
                "error",
                "audit_log_load_failed",
                "",
                f"Unable to load audit log: {exc}",
            ]
        ]
    else:
        audit_rows = [
            [
                format_audit_timestamp(audit_log.created_at),
                str(audit_log.severity),
                str(audit_log.event_type),
                str(audit_log.call_id or ""),
                str(audit_log.message),
            ]
            for audit_log in audit_logs
        ] or EMPTY_AUDIT_LOG_ROWS

    try:
        calls = get_all_calls(limit=500)
        status_counts = get_call_status_counts()
        reports = [get_report_by_call_id(call.id) for call in calls]
        completed_reports = [report for report in reports if report is not None]
    except Exception as exc:
        return (
            (
                "<div class='metric-card'>"
                "<div class='metric-label'>Pipeline Metrics</div>"
                f"<div class='metric-value'>Unable to load</div><p>{escape(str(exc))}</p>"
                "</div>"
            ),
            audit_rows,
        )

    total_calls = sum(status_counts.values())
    successful_calls = status_counts.get(CALL_STATUS_COMPLETED, 0) + status_counts.get(
        CALL_STATUS_FLAGGED,
        0,
    )
    success_rate = (successful_calls / total_calls * 100) if total_calls else 0
    average_qa_score = (
        sum(report.overall_score for report in completed_reports) / len(completed_reports)
        if completed_reports
        else 0
    )
    compliance_flags = sum(1 for report in completed_reports if report.compliance_flag)

    metrics_html = format_metrics_html(
        total_calls=total_calls,
        completed_calls=status_counts.get(CALL_STATUS_COMPLETED, 0),
        failed_calls=status_counts.get(CALL_STATUS_FAILED, 0),
        blocked_calls=status_counts.get(CALL_STATUS_BLOCKED, 0),
        flagged_calls=status_counts.get(CALL_STATUS_FLAGGED, 0),
        success_rate=success_rate,
        average_qa_score=average_qa_score,
        compliance_flags=compliance_flags,
    )

    return metrics_html, audit_rows


def format_metrics_html(
    total_calls: int,
    completed_calls: int,
    failed_calls: int,
    blocked_calls: int,
    flagged_calls: int,
    success_rate: float,
    average_qa_score: float,
    compliance_flags: int,
) -> str:
    """Format high-level observability metrics as dashboard cards."""
    metrics = [
        ("Total Calls", str(total_calls)),
        ("Completed", str(completed_calls)),
        ("Failed", str(failed_calls)),
        ("Blocked", str(blocked_calls)),
        ("Flagged", str(flagged_calls)),
        ("Success Rate", f"{success_rate:.1f}%"),
        ("Average QA Score", f"{average_qa_score:.1f}"),
        ("Compliance Flags", str(compliance_flags)),
    ]
    cards = "".join(
        (
            "<div class='metric-card'>"
            f"<div class='metric-label'>{escape(label)}</div>"
            f"<div class='metric-value'>{escape(value)}</div>"
            "</div>"
        )
        for label, value in metrics
    )
    return f"<div class='metrics-grid'>{cards}</div>"


def format_bytes(size_bytes: int) -> str:
    """Format a file size for storage diagnostics."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def get_storage_status_html() -> str:
    """Return SQLite storage diagnostics for the observability page."""
    db_path = config.DATABASE_PATH
    exists = db_path.exists()
    size = db_path.stat().st_size if exists else 0

    try:
        counts = get_table_counts()
    except Exception as exc:
        return (
            "<div class='storage-status'>"
            "<strong>Storage:</strong> unable to inspect SQLite database at "
            f"{escape(str(db_path))}. {escape(str(exc))}"
            "</div>"
        )

    warning = ""
    if counts["calls"] == 0 and counts["audit_logs"] == 0:
        warning = (
            "<div class='storage-warning'>"
            "This database has no call or audit rows. In Docker, previous stats only "
            "survive container recreation when /app/data is mounted as a volume."
            "</div>"
        )

    return (
        "<div class='storage-status'>"
        f"<strong>Storage:</strong> {escape(str(db_path))} "
        f"({format_bytes(size)}, {'exists' if exists else 'missing'})"
        "<br>"
        f"<strong>Rows:</strong> calls {counts['calls']}, reports {counts['reports']}, "
        f"audit events {counts['audit_logs']}"
        f"{warning}"
        "</div>"
    )


def format_audit_timestamp(timestamp) -> str:
    """Format audit timestamps in Pacific time with an explicit timezone."""
    if timestamp is None:
        return ""

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)

    local_timestamp = timestamp.astimezone(DISPLAY_TIMEZONE)
    return local_timestamp.strftime("%Y-%m-%d %H:%M:%S %Z")


def format_audit_event_label(event_type: str) -> str:
    """Return a readable event label for the audit table."""
    return AUDIT_EVENT_LABELS.get(
        event_type,
        event_type.replace("_", " ").title(),
    )


def format_audit_log_html(audit_rows: list[list[str]]) -> str:
    """Format audit log as a scrollable HTML table."""
    if audit_rows == EMPTY_AUDIT_LOG_ROWS:
        return "<p>No audit events yet.</p>"

    rows_html = ""
    for event_time, severity, event, call_id, message in audit_rows:
        severity_class = (
            "severity-error"
            if severity == "error"
            else "severity-warning"
            if severity == "warning"
            else "severity-info"
        )
        rows_html += (
            "<tr>"
            f"<td class='audit-time'>{escape(event_time)}</td>"
            f"<td><span class='severity-pill {severity_class}'>{escape(severity)}</span></td>"
            f"<td>{escape(format_audit_event_label(event))}</td>"
            f"<td>{escape(call_id)}</td>"
            f"<td>{escape(message)}</td>"
            "</tr>"
        )

    return f"""
<p class="audit-note">Times shown in {DISPLAY_TIMEZONE_LABEL}.</p>
<div class="audit-table-wrap">
<table class="audit-table">
<colgroup>
<col style="width:210px">
<col style="width:120px">
<col style="width:180px">
<col style="width:80px">
<col>
</colgroup>
<thead>
<tr><th>Time</th><th>Severity</th><th>Event</th><th>Call ID</th><th>Message</th></tr>
</thead>
<tbody>{rows_html}</tbody>
</table>
</div>
"""


def export_audit_log_csv() -> str:
    """Export all audit logs to a CSV file."""
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    audit_logs = get_recent_audit_logs(limit=1000)
    csv_path = config.REPORTS_DIR / "audit_log_export.csv"

    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(AUDIT_LOG_HEADERS)
        for log in audit_logs:
            writer.writerow(
                [
                    format_audit_timestamp(log.created_at),
                    log.severity,
                    log.event_type,
                    log.call_id or "",
                    log.message,
                ]
            )

    return gr.update(value=str(csv_path), visible=True)


def get_observability_display():
    """Return observability metrics and audit log for Gradio display."""
    metrics_html, audit_rows = get_observability_data()
    storage_html = get_storage_status_html()
    langsmith_enabled = bool(config.LANGSMITH_API_KEY)
    langsmith_status = "Enabled" if langsmith_enabled else "Disabled"
    langsmith_html = f"<div class='langsmith-status'><strong>LangSmith:</strong> {langsmith_status}"

    if langsmith_enabled:
        langsmith_html += (
            f" - <a href='{escape(config.LANGSMITH_PROJECT_URL)}' target='_blank'>View traces</a>"
        )

    langsmith_html += "</div>"

    return f"{metrics_html}{storage_html}{langsmith_html}", format_audit_log_html(audit_rows)


def normalize_optional_text(value: str | None) -> str | None:
    """Return stripped optional form text, or None when blank."""
    if value is None:
        return None

    value = value.strip()
    return value or None


def run_pipeline(
    audio_path: str,
    caller_id: str | None = None,
    department: str | None = None,
):
    """Run the call analysis pipeline for a Gradio-uploaded audio file."""
    started_at = time.perf_counter()
    caller_id = normalize_optional_text(caller_id)
    department = normalize_optional_text(department)

    if not audio_path:
        yield (
            gr.update(
                value=format_status_html(
                    "Upload needed",
                    "Please upload an audio file before analyzing.",
                ),
                visible=True,
            ),
            format_conversation_html({}),
            "",
            format_summary_html({}),
            format_qa_scorecard_html({}),
            format_report_panel_html(False),
            *empty_report_downloads(),
        )
        return

    try:
        copied_audio_path = copy_audio_to_data_dir(audio_path)
        processing_message = get_processing_message(copied_audio_path)
    except Exception as exc:
        yield (
            gr.update(
                value=format_status_html("Audio upload failed", str(exc)),
                visible=True,
            ),
            format_conversation_html({}),
            "",
            format_summary_html({}),
            format_qa_scorecard_html({}),
            format_report_panel_html(False),
            *empty_report_downloads(),
        )
        return

    yield (
        gr.update(value=processing_message, visible=True),
        *empty_analysis_outputs(),
    )

    pipeline_input = {
        "audio_path": copied_audio_path,
        "caller_id": caller_id,
        "department": department,
    }
    result = dict(pipeline_input)
    try:
        for chunk in pipeline.stream(pipeline_input):
            for node_name, update in chunk.items():
                if isinstance(update, dict):
                    result.update(update)
                yield (
                    gr.update(value=build_progress_status(node_name), visible=True),
                    *empty_analysis_outputs(),
                )
                next_step_status = build_next_step_status(node_name)
                can_continue = not update.get("error") and not update.get("injection_detected")
                if next_step_status and can_continue:
                    yield (
                        gr.update(value=next_step_status, visible=True),
                        *empty_analysis_outputs(),
                    )
    except Exception as exc:
        yield (
            gr.update(
                value=format_status_html("Pipeline failed", str(exc)),
                visible=True,
            ),
            format_conversation_html({}),
            "",
            format_summary_html({}),
            format_qa_scorecard_html({}),
            format_report_panel_html(False),
            *empty_report_downloads(),
        )
        return

    if result.get("error"):
        yield (
            gr.update(
                value=format_status_html("Pipeline failed", str(result["error"])),
                visible=True,
            ),
            format_conversation_html({}),
            "",
            format_summary_html({}),
            format_qa_scorecard_html({}),
            format_report_panel_html(False),
            *empty_report_downloads(),
        )
        return
    if result.get("injection_detected"):
        yield (
            gr.update(
                value=format_status_html(
                    "Injection attempt detected",
                    format_injection_block_detail(result),
                    percent=100,
                ),
                visible=True,
            ),
            format_conversation_html(result),
            "",
            format_summary_html(result),
            format_qa_scorecard_html(result),
            format_report_panel_html(False),
            *empty_report_downloads(),
        )
        return

    transcript = result.get("transcript") or ""
    summary = result.get("summary") or "No summary was generated."
    report_path = result.get("report_path")
    json_report_path = get_json_report_path(report_path)
    result = add_report_json_to_result(result, json_report_path)

    if result.get("supervisor_review_needed"):
        summary = f"{summary}\n\n**Supervisor review needed.**"
        result = {**result, "summary": summary}

    yield (
        gr.update(
            value=format_status_html(
                "Processing complete",
                (
                    "Transcript, summary, QA scorecard, and reports are ready. "
                    f"Total time: {format_elapsed_time(time.perf_counter() - started_at)}."
                ),
                percent=100,
            ),
            visible=True,
        ),
        format_conversation_html(result),
        transcript,
        format_summary_html(result),
        format_qa_scorecard_html(result),
        format_report_panel_html(bool(report_path or json_report_path)),
        *ready_report_downloads(report_path, json_report_path),
    )


theme = gr.themes.Soft(
    primary_hue="slate",
    neutral_hue="slate",
    radius_size="sm",
    font=[gr.themes.GoogleFont("Inter"), "Arial", "sans-serif"],
)


with gr.Blocks() as app:
    with gr.Column(elem_classes=["app-shell"]):
        gr.HTML(
            """
            <header class="app-header">
                <div class="app-brand">
                    <div class="app-logo">CI</div>
                    <div>
                        <p class="app-kicker">Operations Console</p>
                        <h1>Call Center Intelligence</h1>
                    </div>
                </div>
                <p>
                    Analyze calls, score quality, generate reports, and monitor
                    pipeline activity.
                </p>
            </header>
            """
        )

        with gr.Tab("Analyze Call"):
            with gr.Row(
                equal_height=False,
                elem_id="analysis-layout",
                elem_classes=["analysis-layout"],
            ):
                with gr.Column(scale=4, min_width=300, elem_classes=["input-panel"]):
                    gr.HTML(
                        """
                        <div class="section-title">
                            <h2>Call Intake</h2>
                            <p>Upload an audio file, then run the analysis pipeline.</p>
                        </div>
                        """
                    )
                    audio_input = gr.Audio(
                        type="filepath",
                        label="Audio file",
                        sources=["upload"],
                        interactive=True,
                        editable=True,
                        waveform_options=gr.WaveformOptions(
                            waveform_color="#d8dee8",
                            waveform_progress_color="#256f63",
                            trim_region_color="#5b5bd6",
                        ),
                        elem_classes=["audio-upload-preview"],
                    )
                    caller_id_input = gr.Textbox(
                        label="Caller ID (optional)",
                        placeholder="Caller reference, phone, or email",
                        lines=1,
                    )
                    department_input = gr.Textbox(
                        label="Department (optional)",
                        placeholder="Support, emergency dispatch, billing...",
                        lines=1,
                    )
                    analyze_btn = gr.Button(
                        "Analyze Call",
                        variant="primary",
                        elem_classes=["analyze-button"],
                    )
                    status_output = gr.HTML(visible=False, elem_classes=["status-box"])
                    with gr.Column():
                        report_panel_output = gr.HTML(
                            value=format_report_panel_html(False),
                        )
                        with gr.Row(elem_classes=["download-row"]):
                            pdf_download = gr.DownloadButton(
                                label="PDF pending",
                                value=None,
                                interactive=False,
                                elem_classes=["report-download"],
                            )
                            json_download = gr.DownloadButton(
                                label="JSON pending",
                                value=None,
                                interactive=False,
                                elem_classes=["report-download"],
                            )

                with gr.Column(scale=7, min_width=600, elem_classes=["output-panel"]):
                    gr.HTML(
                        """
                        <div class="section-title">
                            <h2>Analysis Workspace</h2>
                            <p>
                                Review transcript, summary, QA scorecard, and generated artifacts.
                            </p>
                        </div>
                        """
                    )
                    with gr.Row(elem_classes=["workspace-grid"]):
                        with gr.Column(elem_classes=["workspace-main"]):
                            conversation_output = gr.HTML(
                                value=format_conversation_html({}),
                                label="Speaker Transcript",
                            )
                            with gr.Column(elem_classes=["raw-transcript-panel"]):
                                gr.HTML("<p class='raw-transcript-title'>Raw Transcript</p>")
                                transcript_output = gr.Textbox(
                                    label="Raw transcript text",
                                    show_label=False,
                                    placeholder="Raw transcript appears after analysis.",
                                    lines=8,
                                    elem_classes=["transcript-box"],
                                )
                        with gr.Column(elem_classes=["workspace-side"]):
                            summary_output = gr.HTML(
                                value=format_summary_html({}),
                                label="Summary",
                            )
                            qa_output = gr.HTML(
                                value=format_qa_scorecard_html({}),
                                label="QA Scorecard",
                            )

            analyze_btn.click(
                fn=run_pipeline,
                inputs=[audio_input, caller_id_input, department_input],
                outputs=[
                    status_output,
                    conversation_output,
                    transcript_output,
                    summary_output,
                    qa_output,
                    report_panel_output,
                    pdf_download,
                    json_download,
                ],
            )

        with gr.Tab("MP3 History") as history_tab:
            with gr.Row(equal_height=False, elem_classes=["analysis-layout"]):
                with gr.Column(scale=4, min_width=360, elem_classes=["input-panel"]):
                    gr.HTML(
                        """
                        <div class="section-title">
                            <h2>Call History</h2>
                            <p>Select an analyzed MP3 call to review stored results.</p>
                        </div>
                        """
                    )
                    refresh_history_btn = gr.Button(
                        "Refresh History",
                        elem_classes=["refresh-button"],
                    )
                    history_call_selector = gr.Radio(
                        label="Analyzed MP3 calls",
                        choices=[],
                        value=None,
                        interactive=True,
                        elem_classes=["history-radio"],
                    )
                    load_history_detail_btn = gr.Button(
                        "View Analysis",
                        elem_classes=["history-action"],
                    )
                    history_overview_output = gr.HTML(
                        value=load_call_history_summary(),
                    )

                with gr.Column(scale=8, min_width=700, elem_classes=["output-panel"]):
                    gr.HTML(
                        """
                        <div class="section-title">
                            <h2>Stored Analysis</h2>
                            <p>Review transcript, summary, QA scorecard, and reports from DB.</p>
                        </div>
                        """
                    )
                    with gr.Row(elem_classes=["workspace-grid"]):
                        with gr.Column(elem_classes=["workspace-main"]):
                            history_conversation_output = gr.HTML(
                                value=format_conversation_html({}),
                                label="Speaker Transcript",
                            )
                            with gr.Column(elem_classes=["raw-transcript-panel"]):
                                gr.HTML("<p class='raw-transcript-title'>Raw Transcript</p>")
                                history_transcript_output = gr.Textbox(
                                    label="Raw transcript text",
                                    show_label=False,
                                    placeholder="Raw transcript appears after loading analysis.",
                                    lines=8,
                                    elem_classes=["transcript-box"],
                                )
                        with gr.Column(elem_classes=["workspace-side"]):
                            history_summary_output = gr.HTML(
                                value=format_summary_html({}),
                                label="Summary",
                            )
                            history_qa_output = gr.HTML(
                                value=format_qa_scorecard_html({}),
                                label="QA Scorecard",
                            )
                            history_report_panel_output = gr.HTML(
                                value=format_report_panel_html(False),
                            )
                            with gr.Row(elem_classes=["download-row"]):
                                history_pdf_download = gr.DownloadButton(
                                    label="PDF pending",
                                    value=None,
                                    interactive=False,
                                    elem_classes=["report-download"],
                                )
                                history_json_download = gr.DownloadButton(
                                    label="JSON pending",
                                    value=None,
                                    interactive=False,
                                    elem_classes=["report-download"],
                                )

            refresh_history_btn.click(
                fn=refresh_history,
                inputs=None,
                outputs=[history_overview_output, history_call_selector],
                queue=False,
            )
            history_call_selector.change(
                fn=load_call_detail,
                inputs=[history_call_selector],
                outputs=[
                    history_conversation_output,
                    history_transcript_output,
                    history_summary_output,
                    history_qa_output,
                    history_report_panel_output,
                    history_pdf_download,
                    history_json_download,
                ],
                queue=False,
            )
            load_history_detail_btn.click(
                fn=load_call_detail,
                inputs=[history_call_selector],
                outputs=[
                    history_conversation_output,
                    history_transcript_output,
                    history_summary_output,
                    history_qa_output,
                    history_report_panel_output,
                    history_pdf_download,
                    history_json_download,
                ],
                queue=False,
            )
            history_tab.select(
                fn=refresh_history,
                inputs=None,
                outputs=[history_overview_output, history_call_selector],
                queue=False,
            )

        with gr.Tab("Observability") as observability_tab:
            with gr.Column(elem_classes=["observability-panel"]):
                gr.HTML(
                    """
                    <div class="section-title">
                        <h2>Pipeline Observability</h2>
                        <p>
                            Track call volume, quality score trends, compliance flags,
                            and audit events.
                        </p>
                    </div>
                    """
                )
                metrics_output = gr.HTML()
                audit_log_output = gr.HTML()
                with gr.Row():
                    refresh_observability_btn = gr.Button(
                        "Refresh",
                        elem_classes=["refresh-button"],
                    )
                    export_btn = gr.Button(
                        "Export Audit Log",
                        elem_classes=["export-button"],
                    )
                csv_download = gr.DownloadButton(
                    label="Download CSV",
                    visible=False,
                    elem_classes=["csv-download"],
                )

            refresh_observability_btn.click(
                fn=get_observability_display,
                inputs=None,
                outputs=[metrics_output, audit_log_output],
                queue=False,
            )
            export_btn.click(
                fn=export_audit_log_csv,
                inputs=None,
                outputs=[csv_download],
                queue=False,
            )
            observability_tab.select(
                fn=get_observability_display,
                inputs=None,
                outputs=[metrics_output, audit_log_output],
                queue=False,
            )


app.queue()


if __name__ == "__main__":
    preload_whisper_model()
    app.launch(theme=theme, css=APP_CSS)
