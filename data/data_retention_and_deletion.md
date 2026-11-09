# Data Retention and Deletion Policy

Last updated: 2026-08-14
Owner: Privacy & Compliance
Applies to: All plans
Related: Data Processing Addendum (DPA), available from the Customer Success Manager

## Retention schedule

| Data type | Standard retention | Enterprise option |
| --- | --- | --- |
| Active workspace data | Until deletion | Until deletion |
| Soft-deleted workspaces | 30 days (recoverable) | 30 days (recoverable) |
| Soft-deleted tickets and comments | 30 days | 30 days |
| Automated backups | 35 days, rolling | 35 days, rolling |
| Audit logs | 12 months | 24 months |
| Export files | 7 days after generation | 7 days after generation |
| Support conversation transcripts | 24 months | 24 months |
| Handoff and escalation records | 24 months | 24 months |
| Billing records | 7 years (legal requirement) | 7 years (legal requirement) |

Retention is enforced by scheduled jobs. Deleting a record in the application removes it from the user interface immediately and from backups within 35 days.

## Account and workspace deletion

A workspace Owner can request deletion from Settings → Workspace → Danger Zone. The workspace enters a 30-day recovery period during which any Owner can restore it. After 30 days, deletion begins and completes within 14 days, after which the data is removed from backups within the 35-day backup window.

Deletion requests are account-sensitive. Support cannot initiate, cancel, or accelerate workspace deletion. If a customer requests deletion in chat, verify their identity, explain the self-serve path and 30-day recovery window, and escalate to Privacy & Compliance if they cannot access the Danger Zone.

## Individual data subject requests

Customers can export or delete an individual's data using:

- **Export:** Settings → Privacy → Data Subject Export, or the API `POST /v2/privacy/exports`.
- **Deletion:** Settings → Privacy → Data Subject Deletion, or `POST /v2/privacy/deletions`.

Requests are queued and processed within 30 days as required by applicable law. A deletion request for a member removes their profile, comments, and attachments unless a legal hold applies. Tickets they created remain but are attributed to "Former member" to preserve audit integrity.

## Legal hold

If a workspace is under legal hold, deletion requests are suspended and the customer's legal contact is notified. Support cannot see whether a legal hold exists; Privacy & Compliance handles all legal hold questions. Suspected litigation or regulatory requests must be escalated immediately (see `refund_and_dispute_policy.md`, "Legal and regulatory complaints").

## Exports

Export links expire after 7 days. To change who can download an export, generate a new export with the desired scope. Support cannot recover expired export links; the customer must regenerate the export.

## Data residency

Workspaces can be provisioned in `us-east-1`, `eu-central-1`, or `ap-southeast-1`. Data residency is chosen at workspace creation and cannot be changed after provisioning. Backups remain in the same region. Requests to change data residency require a migration project led by Customer Success and are not handled by support.

## Subprocessors

The current subprocessor list is published at `https://trust.nimbusdesk.io/subprocessors`. Customers are notified at least 30 days before a new subprocessor that processes personal data is added. Support can share the trust center link but cannot negotiate the DPA.

## Compliance requests

- SOC 2 Type II report: available under NDA from the trust center.
- Penetration test summary: available to Enterprise customers under NDA.
- DPA signing: routed to Privacy & Compliance; do not sign or agree to terms in chat.
- GDPR/CCPA deletion or access requests: never handle manually; direct to the Privacy settings or escalate to Privacy & Compliance with the workspace ID and request type.

## Security incidents

If a customer reports suspected unauthorized access to their workspace or a potential personal data breach, treat it as an account-security incident: escalate immediately to Security Operations per `security_compliance_faq.md`. Do not ask for passwords or full card numbers.
