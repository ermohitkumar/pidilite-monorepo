"""
Script to update the Test Cases Excel sheet with all backend API test cases
from tests/test_api_v1.py.

Appends rows after existing frontend test cases, preserving the sheet structure:
  Sl No | Module | Task | Description | Expected Result | Actual Result | Status | Comments
"""
import openpyxl
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from copy import copy

EXCEL_PATH = "/Users/akshaymanjunath/Downloads/Test_Cases_User_Feedback_App(FE_User_Feedback_Test_Cases).xlsx"

# ── All backend test cases extracted from test_api_v1.py ──────────────────────
# Each tuple: (Module, Task, Description, Expected Result, Status)
BACKEND_TEST_CASES = [
    # ── Health Check ──────────────────────────────────────────────────────────
    (
        "Health Check (API)",
        "GET /health endpoint",
        "Send a GET request to the /health endpoint.",
        "Response status code is 200 and JSON body contains {\"status\": \"ok\"}.",
        "Completed",
    ),

    # ── Endpoint 1: POST /api/v1/file (Ingest) ───────────────────────────────
    (
        "File Ingestion (API)",
        "Ingest new file",
        "POST /api/v1/file with a valid GCS file notification payload (name, contentType, size, crc32c, etag, md5Hash, etc.).",
        "Response 200 with success=true. Data contains correct file_name (basename stripped), gcs_input_uri (reconstructed gs:// URI), status='PENDING', and a non-empty job_id.",
        "Completed",
    ),
    (
        "File Ingestion (API)",
        "Ingest duplicate file",
        "POST /api/v1/file twice with the identical GCS file notification payload.",
        "Both responses return 200. Second response returns the same job_id as the first and the message contains 'already ingested'.",
        "Completed",
    ),

    # ── Endpoint 2: POST /api/v1/batch ────────────────────────────────────────
    (
        "Batch Processing (API)",
        "Start batch — no pending jobs",
        "POST /api/v1/batch when no jobs have PENDING status in the database.",
        "Response 200 with success=true and data.jobs_enqueued == 0.",
        "Completed",
    ),
    (
        "Batch Processing (API)",
        "Start batch — with pending jobs",
        "Create 3 PENDING jobs in the DB, then POST /api/v1/batch.",
        "Response 200 with success=true, data.jobs_enqueued == 3, and a non-empty batch_id is returned.",
        "Completed",
    ),

    # ── Endpoint 3: POST /api/v1/files/transcription (STT Submit) ────────────
    (
        "STT Transcription (API)",
        "Submit STT — success",
        "POST /api/v1/files/transcription with a valid job_id (status BATCHED), gcs_input_uri, gcs_output_uri_prefix, batch_id, language_code, and model.",
        "Response 200 with success=true, data.status='STT_SUBMITTED', and data.stt_operation_name matches the expected GCP operation URI.",
        "Completed",
    ),
    (
        "STT Transcription (API)",
        "Submit STT — job not found",
        "POST /api/v1/files/transcription with a nonexistent job_id.",
        "Response 200 with success=true, message contains 'not found', and data.status='NOT_FOUND'.",
        "Completed",
    ),
    (
        "STT Transcription (API)",
        "Submit STT — wrong job status",
        "POST /api/v1/files/transcription with a job whose status is COMPLETED (not BATCHED).",
        "Response 200 with success=true and message contains 'skipping' (job is not eligible for STT).",
        "Completed",
    ),

    # ── Endpoint 4a: POST /api/v1/files/stt-complete ─────────────────────────
    (
        "STT Complete (API)",
        "STT complete — enqueues translate",
        "POST /api/v1/files/stt-complete with a GCS notification for a job that has status STT_COMPLETED and a valid gcs_stt_output_uri.",
        "Response 200 with success=true, data.status='TRANSLATING', data.action='enqueued_translate'. Cloud Tasks enqueue is called once.",
        "Completed",
    ),
    (
        "STT Complete (API)",
        "STT complete — race condition (STT_SUBMITTED)",
        "POST /api/v1/files/stt-complete for a job still in STT_SUBMITTED status (Eventarc fires before checker marks STT_COMPLETED).",
        "Response 200 with success=true, data.action='enqueued_translate', data.previous_status='STT_SUBMITTED'. Cloud Tasks enqueue is called once.",
        "Completed",
    ),
    (
        "STT Complete (API)",
        "STT complete — skips ineligible status",
        "POST /api/v1/files/stt-complete for a job in PENDING status (not eligible).",
        "Response 200, data.action='skipped', and skip_reason is present in the response. Cloud Tasks enqueue is NOT called.",
        "Completed",
    ),
    (
        "STT Complete (API)",
        "STT complete — no extractable job_id",
        "POST /api/v1/files/stt-complete with a GCS notification payload whose 'name' field doesn't match the expected path pattern (e.g., 'random/file.json').",
        "Response 200 and message contains 'could not extract' (job_id could not be parsed from the object name).",
        "Completed",
    ),

    # ── Endpoint 4b: POST /api/v1/files/translate ─────────────────────────────
    (
        "Translation (API)",
        "Translate — success",
        "POST /api/v1/files/translate with a valid job_id (status TRANSLATING) and gcs_transcript_uri. GCS and Vertex AI translate are mocked.",
        "Response 200 with success=true, data.status='TRANSLATED'. Cloud Tasks enqueue is called once. ProcessedFile record in DB has translated_text populated.",
        "Completed",
    ),
    (
        "Translation (API)",
        "Translate — idempotent (already translated)",
        "POST /api/v1/files/translate for a job that already has a ProcessedFile with translated_text.",
        "Response 200, data.status='TRANSLATED'. Cloud Tasks enqueue is called once (proceeds to next stage even if already translated).",
        "Completed",
    ),

    # ── Endpoint 4c: POST /api/v1/files/post-processing ──────────────────────
    (
        "Post-Processing (API)",
        "Normalize + Insights — success",
        "POST /api/v1/files/post-processing with a valid job_id (status TRANSLATED) that has a ProcessedFile with translated_text. Vertex AI normalize and insights are mocked.",
        "Response 200 with success=true, data.status='COMPLETED', data.insights_generated=true. A JobSummary record is created in the DB. Job status is updated to COMPLETED.",
        "Completed",
    ),
    (
        "Post-Processing (API)",
        "Post-processing — resumes from NORMALIZED",
        "POST /api/v1/files/post-processing for a job already in NORMALIZED status that has a ProcessedFile with normalized_text. Only Vertex insights is mocked.",
        "Response 200, data.status='COMPLETED'. Vertex insights is called exactly once (normalize step is skipped).",
        "Completed",
    ),
    (
        "Post-Processing (API)",
        "Post-processing — no translated text",
        "POST /api/v1/files/post-processing for a TRANSLATED job that has no ProcessedFile record (translated_text missing).",
        "Response 200 with success=false. Error message contains 'translated_text' indicating missing prerequisite data.",
        "Completed",
    ),

    # ── Endpoint 5: POST /api/v1/checker/run ──────────────────────────────────
    (
        "Checker (API)",
        "Checker run — empty (no actionable jobs)",
        "POST /api/v1/checker/run with an empty JSON body when no jobs are in ERROR or stuck states.",
        "Response 200 with success=true. Data shows jobs_checked=0, jobs_recovered=0, jobs_marked_failed=0, jobs_still_pending=0.",
        "Completed",
    ),
    (
        "Checker (API)",
        "Checker recovers ERROR jobs to PENDING",
        "Create two ERROR jobs: one with retry_count=0 (recoverable) and one with retry_count=3 (exhausted retries). POST /api/v1/checker/run.",
        "Response 200 with success=true. Data shows jobs_recovered=1 (the recoverable job) and jobs_marked_failed=1 (the exhausted job).",
        "Completed",
    ),
    (
        "Checker (API)",
        "Checker retries post-STT translation",
        "Create an ERROR job (retry_count=0) that already has a gcs_stt_output_uri set (STT output exists). POST /api/v1/checker/run.",
        "Response 200, data.jobs_recovered >= 1. Cloud Tasks enqueue is called (job is re-enqueued for translation).",
        "Completed",
    ),
    (
        "Checker (API)",
        "Checker reconciles batch status",
        "Create a PROCESSING batch with 2 COMPLETED jobs assigned to it. POST /api/v1/checker/run.",
        "Response 200. The batch status is updated to COMPLETED after reconciliation.",
        "Completed",
    ),

    # ── STT Error Handling ────────────────────────────────────────────────────
    (
        "STT Error Handling (API)",
        "STT credentials error — marks FAILED",
        "POST /api/v1/files/transcription for a BATCHED job when the STT service raises STTCredentialsError.",
        "Response with success=false, data.status='FAILED'. Job status in DB is updated to FAILED (non-retryable error).",
        "Completed",
    ),
    (
        "STT Error Handling (API)",
        "STT quota exhausted — marks ERROR with retry",
        "POST /api/v1/files/transcription for a BATCHED job when the STT service raises STTQuotaExhaustedError.",
        "Response with success=false, data.status='ERROR'. Job status in DB is ERROR and retry_count is incremented to 1 (retryable error).",
        "Completed",
    ),
]


def main():
    wb = openpyxl.load_workbook(EXCEL_PATH)
    ws = wb.active

    # Find the last row that has data
    last_data_row = ws.max_row
    # The last serial number from existing data
    last_sl_no = 0
    for row_idx in range(2, last_data_row + 1):
        val = ws.cell(row=row_idx, column=1).value
        if val is not None and isinstance(val, (int, float)):
            last_sl_no = int(val)

    # Copy formatting from the last populated data row (row 16 = last fully filled row)
    reference_row = 2  # Use row 2 as formatting reference (fully populated)

    # Clear rows 17-21 that have partial/empty placeholder data
    for row_idx in range(17, 22):
        for col in range(1, 9):
            ws.cell(row=row_idx, column=col).value = None

    # Start appending at row 17 (after the 16 existing complete test cases)
    # But first keep the incomplete rows 17-21 as-is if they have valid data
    # Actually, rows 17-21 have partial/empty Batches data — we'll replace from row 17
    start_row = last_data_row + 1  # Append after all existing rows

    # Actually, let's check: rows 17-21 have partial data. Let's overwrite from row 17.
    # Row 16 is the last fully populated row (Sl No 15).
    # Rows 17-21 have Sl Nos 16-20 but are mostly empty. Let's keep them and append after.
    # Better: overwrite from row 17 since those are incomplete placeholders.
    start_row = 17
    current_sl = 16  # Continue from Sl No 16

    # Define styling
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin'),
    )
    default_font = Font(name='Calibri', size=11)
    wrap_alignment = Alignment(wrap_text=True, vertical='top')

    for i, (module, task, description, expected, status) in enumerate(BACKEND_TEST_CASES):
        row_idx = start_row + i
        sl_no = current_sl + i

        ws.cell(row=row_idx, column=1, value=sl_no)
        ws.cell(row=row_idx, column=2, value=module)
        ws.cell(row=row_idx, column=3, value=task)
        ws.cell(row=row_idx, column=4, value=description)
        ws.cell(row=row_idx, column=5, value=expected)
        ws.cell(row=row_idx, column=6, value=None)  # Actual Result (to be filled during execution)
        ws.cell(row=row_idx, column=7, value=status)
        ws.cell(row=row_idx, column=8, value="Automated test (pytest)")  # Comments

        # Apply formatting to all cells in the row
        for col in range(1, 9):
            cell = ws.cell(row=row_idx, column=col)
            cell.font = default_font
            cell.alignment = wrap_alignment
            cell.border = thin_border

    # Adjust column widths for readability
    col_widths = {
        1: 8,    # Sl No
        2: 25,   # Module
        3: 40,   # Task
        4: 60,   # Description
        5: 60,   # Expected Result
        6: 40,   # Actual Result
        7: 12,   # Status
        8: 25,   # Comments
    }
    for col_num, width in col_widths.items():
        col_letter = openpyxl.utils.get_column_letter(col_num)
        ws.column_dimensions[col_letter].width = width

    wb.save(EXCEL_PATH)
    total_added = len(BACKEND_TEST_CASES)
    print(f"✅ Successfully added {total_added} backend API test cases to the Excel sheet.")
    print(f"   Rows {start_row} to {start_row + total_added - 1} (Sl No {current_sl} to {current_sl + total_added - 1})")
    print(f"   File saved: {EXCEL_PATH}")


if __name__ == "__main__":
    main()
