# SSO and SAML Setup Guide

Last updated: 2026-08-27
Owner: Identity & Access
Applies to: Growth, Scale, Enterprise plans
Supported identity providers: Okta, Microsoft Entra ID, Google Workspace, OneLogin, JumpCloud, Ping Identity, and any SAML 2.0 compliant IdP

## Overview

NimbusDesk supports SAML 2.0 single sign-on and SCIM 2.0 provisioning. Once SSO is enforced, members must authenticate through your identity provider; password sign-in is disabled for all users except the one break-glass workspace Owner who retains a password for emergency access.

## Service provider configuration

| Setting | Value |
| --- | --- |
| ACS URL | `https://app.nimbusdesk.io/sso/saml/acs` |
| Entity ID / Audience | `urn:nimbusdesk:sp` |
| Start URL | `https://app.nimbusdesk.io/sso/login` |
| NameID format | `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress` |
| Signing | IdP signs the response; assertion must be signed |
| Encryption | Optional; if enabled, upload the NimbusDesk public certificate from Settings → Security → SSO |

## Required attributes

| SAML attribute | Required | Example |
| --- | --- | --- |
| `email` | Yes | `a.chen@example.com` |
| `firstName` | Yes | `Alex` |
| `lastName` | Yes | `Chen` |
| `groups` | Recommended | `nimbus-admins`, `nimbus-agents` |

The `email` value must match the user's existing NimbusDesk account email. If it does not, NimbusDesk creates a new member and does not link the old account. Email changes must be made in NimbusDesk before the IdP change.

## Setup steps

1. In NimbusDesk, open Settings → Security → SSO and choose **Configure SAML**.
2. Download the NimbusDesk metadata XML.
3. In your IdP, create a SAML application, upload the metadata, and map the attributes listed above.
4. Copy the IdP metadata URL and IdP signing certificate back into NimbusDesk.
5. Run **Test SSO** using a service account or a test user. The test must succeed before enforcement can be enabled.
6. Assign the NimbusDesk app to the groups that should have access.
7. Enable **Enforce SSO** and keep the break-glass Owner documented.

## SCIM provisioning

- SCIM base URL: `https://api.nimbusdesk.io/v2/scim/v2`
- Authentication: bearer token generated once in Settings → Security → SSO → SCIM. Store it in your IdP's secret store.
- Supported resources: `Users`, `Groups`.
- Default behavior: deactivating a user in the IdP deactivates the NimbusDesk member, which frees the seat. Deleting a user is not supported; deactivation is used instead.
- Group mapping: groups can be mapped to NimbusDesk roles. A group mapped to `Admin` grants admin rights to all members of that group. Only one role per user is applied; the highest-privilege mapped group wins.

## Common SSO errors

### `saml_signature_invalid`
The assertion is signed with a certificate that does not match the one configured in NimbusDesk, or the IdP rotated its certificate.
**Resolution:** upload the current IdP certificate, complete one test sign-in, then remove the old certificate. Do not disable assertion signing.

### `saml_audience_mismatch`
The Entity ID in the IdP does not equal `urn:nimbusdesk:sp`, or the IdP sends a different audience.
**Resolution:** correct the audience/entity ID in the IdP application settings and re-run Test SSO.

### `saml_clock_skew`
The assertion `NotBefore` or `NotOnOrAfter` is outside the accepted window (300 seconds).
**Resolution:** confirm the IdP's NTP synchronization. NimbusDesk does not accept assertions with a validity window longer than 10 minutes.

### `saml_attribute_missing`
The assertion does not include `email`, `firstName`, or `lastName`.
**Resolution:** add the attribute statements in the IdP. NameID alone is not sufficient.

### `saml_user_not_found` or `saml_email_mismatch`
The asserted email does not belong to a NimbusDesk member, or the member's email differs.
**Resolution:** invite the user with the exact email or update the member email first. Just-in-time provisioning must be enabled for automatic member creation.

### `saml_replay_detected`
The same assertion ID was submitted twice, usually because the browser was refreshed on the ACS URL.
**Resolution:** navigate to `https://app.nimbusdesk.io/sso/login` again instead of refreshing the ACS page.

## Enforcing SSO safely

Before enforcement, verify that:

- At least two Owners can sign in through SSO.
- The break-glass Owner password is stored in the company password manager.
- SCIM deprovisioning is working in staging.
- Support contact details are current.

If the IdP misconfigures or goes down after enforcement, users cannot sign in with passwords. In that case, the break-glass Owner signs in with email and password and can temporarily disable enforcement. If the break-glass Owner is unavailable, recovery requires identity verification by Identity & Access, which is an account-sensitive escalation.

## Troubleshooting checklist

1. Does Test SSO pass from Settings → Security → SSO?
2. Is the IdP signing certificate current and complete (single PEM block)?
3. Does the NameID equal the user's NimbusDesk email?
4. Is the user assigned to the application in the IdP?
5. Are groups mapped to roles, and is the user in the right group?
6. Does the IdP have a SAML trace export? Ask for the trace with sensitive fields redacted.

Never ask a customer to send a SAML assertion without redaction; assertions can contain signed session data.
