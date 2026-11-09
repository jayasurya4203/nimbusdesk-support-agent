# New Workspace Onboarding Checklist

Last updated: 2026-07-03
Owner: Customer Success
Applies to: New Growth, Scale, and Enterprise workspaces

## Purpose

This checklist is used by the onboarding specialist and the customer's project lead during the first 14 days. It is also the reference for "where do I start?" questions. Support can answer questions about any step using this document.

## Phase 1 — Workspace setup (Day 1–2)

- [ ] Owner signs in and completes MFA
- [ ] Workspace name, region, and timezone confirmed. Region cannot be changed later.
- [ ] Branding applied: logo, sender name, support email
- [ ] Team invites sent; roles assigned (Owner, Admin, Agent, Viewer)
- [ ] Billing Admin designated if different from the Owner
- [ ] SSO configured and tested if the plan includes it; keep a break-glass Owner

## Phase 2 — Data and channels (Day 3–5)

- [ ] Import contacts and open tickets using the CSV importer (template in Settings → Import)
- [ ] Verify import mapping; required columns are `email`, `subject`, and `created_at`
- [ ] Connect at least one channel: email forwarding, web form, chat widget, or API
- [ ] Configure email forwarding and confirm the verification message
- [ ] Set up webhooks or Zapier only after the first channel works

## Phase 3 — Workflows (Day 5–8)

- [ ] Create teams and queues
- [ ] Configure assignment rules (round robin or load balanced)
- [ ] Define SLA policies: first response and resolution targets per priority
- [ ] Create saved views for each team
- [ ] Add tags and custom fields needed for reporting
- [ ] Configure notification preferences for Agents and Admins

## Phase 4 — Integrations and automation (Day 8–12)

- [ ] Connect Slack or Microsoft Teams and test a ticket notification
- [ ] Connect Jira or Salesforce if required; map required fields
- [ ] Create one automation rule (for example auto-assign by keyword) and test it on a sample ticket
- [ ] Connect a database connector only after the core workflow is stable

## Phase 5 — Go-live readiness (Day 12–14)

- [ ] Run a pilot with 2–3 agents for one business day
- [ ] Verify SLA timers start and stop correctly
- [ ] Confirm reporting dashboards show the pilot data
- [ ] Train agents: ticket lifecycle, macros, mentions, internal notes
- [ ] Review the escalation path and who to contact for P1 incidents
- [ ] Agree on a review date at 30 days

## Common onboarding blockers

| Blocker | Cause | Resolution |
| --- | --- | --- |
| Import fails with `invalid_email` | Rows with empty or malformed email | Download the error CSV, fix rows, re-upload |
| Forwarding verification never arrives | DNS records missing or email deliverability issues | Verify MX records; see `email_deliverability.md` |
| Agents cannot see imported tickets | Membership not added before the import, or restricted access model | Add members, then re-run the import or bulk reassign |
| SSO users cannot sign in | Assertion email mismatch | See `sso_saml_setup.md` |
| Sender name reverts to "NimbusDesk" | Branding not saved due to missing verification | Verify the support email domain, then save branding again |

## Success criteria for the first 30 days

- 100% of inbound channels routing into NimbusDesk
- Median first response within the plan's target
- At least 80% of agents active weekly
- At least three automations or macros in use
- No unresolved P1 tickets older than 7 days

## When to involve Customer Success

- The customer is behind by more than 7 days on the checklist
- The customer asks about changing their plan, adding seats, or a custom contract
- The customer requests a training session or a business review
- The customer is evaluating competitors or mentions cancellation

Support can help with product configuration questions at any phase. Commercial topics belong to Customer Success, and billing/refund topics follow `refund_and_dispute_policy.md`.
