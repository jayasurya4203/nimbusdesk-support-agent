# Security and Compliance FAQ

Last updated: 2026-09-22
Owner: Security & Compliance
Applies to: All plans
Trust center: `https://trust.nimbusdesk.io`

## Certifications and reports

**Is NimbusDesk SOC 2 certified?**
NimbusDesk maintains a SOC 2 Type II report covering Security and Availability. The report is refreshed annually and is available under NDA from the trust center. A SOC 2 bridge letter is available for the gap period between reports.

**Is NimbusDesk ISO 27001 certified?**
Yes. The ISO/IEC 27001:2022 certificate and statement of applicability are available from the trust center or from your Customer Success Manager.

**Do you support HIPAA?**
HIPAA workloads require a Business Associate Agreement (BAA) and an Enterprise plan. A BAA cannot be signed in chat; route requests to Privacy & Compliance.

**Can I get a penetration test report?**
Enterprise customers can request the latest third-party penetration test summary under NDA. Full reports are not shared. Requests are reviewed by Security & Compliance.

**Where is the subprocessor list?**
`https://trust.nimbusdesk.io/subprocessors`. Customers are notified 30 days before a new subprocessor that handles personal data is engaged.

## Encryption and keys

- Data in transit: TLS 1.2 or higher, with TLS 1.3 preferred. HSTS is enabled with a one-year max-age.
- Data at rest: AES-256-GCM, with keys managed in a cloud KMS and rotated every 90 days.
- Backups: encrypted with a separate key from primary storage.
- Customer-managed encryption keys (CMEK): available on Enterprise, requiring a dedicated key project and a 2-week onboarding project.
- Secrets: API keys and webhook signing secrets are stored hashed where possible; signing secrets are shown once at creation.

## Authentication and access

**Do you support MFA?**
Yes: TOTP authenticator apps, WebAuthn security keys, and SMS fallback (not recommended). Workspace Owners and Admins can enforce MFA for all members. SSO enforcement counts as MFA if the identity provider enforces it.

**What are NimbusDesk's internal access controls?**
Production access requires SSO, hardware keys, least-privilege roles, just-in-time approval, and full session recording. Employee access is reviewed quarterly. NimbusDesk personnel do not access customer data unless the customer grants time-bound support access, which is logged in the workspace audit log.

**Does the support agent need my password to investigate?**
No. NimbusDesk support never asks for passwords, API secrets, full card numbers, or MFA codes. If someone claiming to be support asks for these, report it to `security@nimbusdesk.io`.

## Workspace security features

- SAML 2.0 SSO and SCIM provisioning
- Enforced MFA and session timeouts (configurable from 1 hour to 30 days)
- IP allowlists for the web app and API
- Audit log export (CSV/JSON) with 12-month retention on Scale, 24 months on Enterprise
- Role-based access control with four default roles
- Data residency in US, EU, and APAC
- Optional customer-managed keys (Enterprise)

## Vulnerability management

- Third-party penetration test annually, plus continuous automated scanning.
- Critical vulnerabilities are patched within 7 days, high within 30 days.
- A public vulnerability disclosure program is available at `https://trust.nimbusdesk.io/vdp`.

## Responsible disclosure and abuse

Report suspected vulnerabilities to `security@nimbusdesk.io` with reproduction steps. Do not test against workspaces you do not own. Abuse reports (spam, phishing, malware hosted in NimbusDesk) go to `abuse@nimbusdesk.io`.

## Security questionnaires

Standard security questionnaires (CAIQ, SIG) are available from the trust center. Custom questionnaires require a Customer Success Manager and are typically returned within 10 business days. Support should not answer security questionnaire questions ad hoc.

## Suspected compromise

If a customer reports a compromised account, leaked API key, or suspicious login:

1. Treat the ticket as account-sensitive and escalate to Security Operations immediately.
2. Advise the customer to revoke exposed API keys in Settings → Developer → API Keys and to sign out all sessions in Settings → Security → Sessions.
3. Advise changing the password if the account is not SSO-enforced, and never ask for the current password.
4. Do not investigate login logs or confirm whether a breach occurred; Security Operations handles verification.
5. Preserve the customer's description of the incident in the handoff summary.

## Policy questions support can answer directly

- Which certifications exist and where to download them
- How to enable MFA or enforce SSO from the settings pages
- Encryption in transit and at rest, key rotation cadence
- Audit log retention windows
- How to report a vulnerability

Anything involving a signed agreement, BAA, DPA, custom security review, incident confirmation, or suspected data breach must be escalated.
