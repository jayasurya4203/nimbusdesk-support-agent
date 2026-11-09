# Incident Management and Status Communication Policy

Last updated: 2026-09-19
Owner: Reliability Engineering
Applies to: All customers

## Status page

The authoritative source for platform health is `https://status.nimbusdesk.io`. It is hosted independently of the application so it remains available during an outage. Customers can subscribe to email, SMS, and webhook notifications. Support agents should link the status page rather than describe unverified symptoms.

## Severity levels

| Severity | Definition | Example | First update target |
| --- | --- | --- | --- |
| P1 | Complete outage or data loss risk for many workspaces | API unavailable in all regions; auth failures platform-wide | 15 minutes |
| P2 | Major degradation for many workspaces | Webhooks delayed over 30 minutes; one region slow | 30 minutes |
| P3 | Limited impact or workaround available | Single connector failing; export jobs slow | 2 business hours |
| P4 | Cosmetic or single-customer issue | Incorrect label on a report | Next business day |

Severity is set by the incident commander, not by the number of tickets received. A single customer's issue is usually P4 even if it feels urgent to that customer.

## Communication cadence

- P1: updates every 30 minutes until resolved, then an incident review within 5 business days.
- P2: updates every 60 minutes.
- P3: updates at meaningful milestones.
- Updates are posted to the status page, and support agents share the status page link in tickets. Do not invent ETAs that are not on the status page.

## During an incident: what support may say

Support may:

- Confirm that the incident is tracked and link the status page.
- Summarize the latest published update verbatim.
- Explain the customer's workaround if one is published.
- Set expectations that the next update will follow the cadence above.

Support may not:

- Estimate a resolution time beyond what is published.
- Assign blame to a vendor, cloud provider, or individual.
- Promise SLA credits. Credits are handled through the SLA process after the incident review.
- Share internal incident channel details, root-cause hypotheses, or customer names.

## Incident review and customer follow-up

Every P1 and P2 receives a written incident review containing the timeline in UTC, customer impact, contributing factors, and preventive actions. Enterprise customers receive the review within 5 business days on request. The review is approved by Reliability Engineering before distribution.

## SLA credits

SLA credits are governed by `service_level_agreement.md`. Credits are not automatic; the customer must submit a claim within 30 days of the incident. Support opens a claim ticket and routes it to Finance Operations. Support does not calculate or approve credits during an incident.

## Escalation criteria during incidents

Escalate to the on-call incident commander when:

- A customer reports a symptom not listed on the status page that suggests a new, wider failure.
- The customer has evidence of data loss or data corruption.
- A customer's security team reports suspected unauthorized access.

Escalate with: workspace ID, symptom, first observed time in UTC, affected endpoints, request IDs, and a sample failure response. Do not forward raw customer payloads containing personal data.

## Post-incident customer messaging

After resolution, the support agent replies in the original ticket with:

1. Confirmation that the incident is resolved.
2. The published resolution summary.
3. A link to the status page history entry.
4. An offer to open a follow-up ticket if the customer still sees impact.

For customers who remain dissatisfied, the ticket is escalated with a full handoff so a human can review compensation eligibility with Finance Operations.
