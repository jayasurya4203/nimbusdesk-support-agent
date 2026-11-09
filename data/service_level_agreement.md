# Service Level Agreement (SLA) Summary

Last updated: 2026-09-30
Owner: Customer Success
Applies to: Growth, Scale, Enterprise
Full legal terms: available from the Customer Success Manager on request

## Uptime commitment

| Plan | Monthly uptime commitment | Measurement |
| --- | --- | --- |
| Growth | 99.9% | Core API and web application, per calendar month |
| Scale | 99.95% | Core API and web application, per calendar month |
| Enterprise | 99.99% | Core API and web application, per calendar month, contractual |

Uptime is calculated as:

```
uptime % = ((total minutes - unavailable minutes) / total minutes) * 100
```

Unavailability means that more than 5% of requests to the core API in a rolling 5-minute window return HTTP 5xx or fail to connect, as measured from three independent regions. Scheduled maintenance, customer-side network failures, and force majeure are excluded. Scheduled maintenance is announced at least 72 hours in advance, occurs on Sundays between 02:00 and 05:00 UTC, and is capped at 4 hours per month.

## Support response targets

| Priority | Starter | Growth | Scale | Enterprise |
| --- | --- | --- | --- | --- |
| P1 (outage / data loss) | Next business day | 4 hours | 2 hours | 1 hour, 24/7 |
| P2 (major degradation) | Next business day | 8 hours | 4 hours | 2 hours, 24/7 |
| P3 (workaround available) | 2 business days | 24 hours | 12 hours | 4 business hours |
| P4 (question / cosmetic) | 3 business days | 48 hours | 24 hours | 8 business hours |

Response targets are measured from ticket creation to the first substantive human or automated response. Auto-acknowledgements do not count.

## SLA credits

If monthly uptime falls below the commitment, the customer may request a credit:

| Achieved uptime | Credit (% of monthly fee) |
| --- | --- |
| 99.0% – below commitment | 10% |
| 98.0% – 98.99% | 15% |
| 95.0% – 97.99% | 25% |
| Below 95.0% | 50% |

Rules:

1. The customer must submit a claim within 30 days of the end of the affected month.
2. The claim must reference the incident(s) on the status page.
3. Finance Operations validates the claim against monitoring data.
4. Credits are applied to a future invoice; they are not paid in cash.
5. The maximum total credit in a month is 50% of the monthly fee.
6. SLA credits are the sole remedy for missed uptime commitments.

Support agents do not calculate or approve credits. A credit request is an account-sensitive, finance-owned process and must be escalated with the incident IDs and the customer's achieved-uptime evidence.

## Exclusions

- Beta features and preview APIs are excluded from the SLA.
- Sandbox environments are excluded.
- Issues caused by customer misconfiguration, unsupported integrations, or third-party services are excluded.
- API rate limiting responses (HTTP 429) are not counted as unavailability.

## Planned maintenance

Maintenance windows are posted on the status page at least 72 hours ahead. Emergency maintenance may occur with 2 hours' notice for critical security patches; emergency maintenance counts toward uptime only if it exceeds 30 minutes.

## Reporting

Monthly uptime reports are published on the status page by the 5th business day of the following month. Enterprise customers can request a signed report from their Customer Success Manager.

## Escalation contacts

- Support response SLA breaches: escalate to Customer Success Operations.
- Uptime SLA credit claims: escalate to Finance Operations.
- Active incident impact: follow the status page and the incident communication policy.
