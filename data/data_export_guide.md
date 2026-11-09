# Data Export Guide

Last updated: 2026-07-29
Owner: Product
Applies to: All plans

## Export options

| Option | Best for | Limits |
| --- | --- | --- |
| CSV export from a filtered list | Up to 50,000 rows | 50,000 rows per file; 10 exports/hour |
| Bulk export job (`POST /v2/exports`) | Large datasets | 500,000 rows per job; 10 jobs/hour |
| Workspace backup (Enterprise) | Full workspace archive | Weekly schedule; delivered to customer storage |
| API pagination | Real-time sync | 100 records/page; standard rate limits |

## CSV export steps

1. Apply the filters you want on the list view (status, assignee, date range, tags).
2. Select **Export → CSV**. Filters are honored; hidden columns are not included.
3. The file downloads when ready. Files larger than 25 MB are delivered as an email link valid for 7 days.

CSV exports include only the fields visible to your role. Personal data fields such as requester email are included for Agents and above.

## Bulk export jobs

```bash
curl -X POST https://api.nimbusdesk.io/v2/exports \
  -H "Authorization: Bearer $NIMBUSDESK_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "object": "tickets",
    "format": "csv",
    "filters": {"created_after": "2025-01-01T00:00:00Z"},
    "include": ["comments", "tags"]
  }'
```

The response returns an export ID. Poll `GET /v2/exports/{id}` for status: `queued`, `running`, `completed`, `failed`, or `expired`. When completed, the response includes a signed download URL valid for 7 days. Export jobs are processed in the workspace's region.

## Common export failures

### `export_too_large`
The requested rows exceed the per-job limit. Narrow the date range or split by team/queue. The error message includes the estimated row count.

### `export_timed_out`
The job exceeded the 60-minute execution limit, usually because comments and attachments were included for a very large date range. Split by month and exclude attachments.

### `export_quota_exceeded`
More than 10 export jobs were requested in an hour. Wait until the hourly window resets; the reset time is shown in the error response.

### Empty or truncated CSV
- Filters are evaluated at job creation time, not at download time.
- Rows deleted after the job completed are still present in the file.
- Excel may truncate display at 1,048,576 rows; the file itself is complete. Use a streaming tool for large files.

### Download link expired
Links are valid for 7 days. Export files are deleted after 7 days and cannot be recovered. Regenerate the export.

## Attachments

Attachments are not included in CSV exports. Use `GET /v2/tickets/{id}/attachments` to list attachment metadata and download each file with its signed URL. Attachment URLs expire after 15 minutes.

Bulk attachment export is available as a ZIP for Enterprise workspaces. ZIP exports can take up to 4 hours and are limited to 50 GB.

## Data privacy considerations

- An export may contain personal data. Handle it according to your own retention policy.
- A workspace-wide export requested for a data subject access request should be made through Settings → Privacy → Data Subject Export so that it is logged and scoped to that person.
- Export records are written to the audit log with the requesting member, timestamp, filters, and row count.
- Support cannot email export files and cannot download customer data on the customer's behalf.

## Escalation

Escalate to the Data Platform team when:

- A completed export consistently downloads a corrupt file
- A completed export is missing rows that are visible in the UI for the same filters
- Repeated `export_timed_out` errors occur for a dataset under 100,000 rows
- A privacy export is blocked by a legal hold

Include workspace ID, export ID, filters used, row count, timestamps in UTC, and the file size of the downloaded artifact. Never attach exported customer data to the ticket; include only aggregate counts.
