# Workspace Roles and Permissions

Last updated: 2026-08-30
Owner: Product
Applies to: All plans

## Default roles

| Capability | Owner | Admin | Agent | Viewer |
| --- | --- | --- | --- | --- |
| View tickets | Yes | Yes | Yes | Yes |
| Reply to tickets | Yes | Yes | Yes | No |
| Assign tickets | Yes | Yes | Yes | No |
| Manage members | Yes | Yes | No | No |
| Manage billing | Yes (or Billing Admin) | No | No | No |
| Manage API keys | Yes | Yes | No | No |
| Manage integrations | Yes | Yes | No | No |
| Manage SSO / security | Yes | Yes | No | No |
| Delete workspace | Yes | No | No | No |
| Transfer ownership | Yes | No | No | No |

A workspace has exactly one Owner. Owners can assign the Billing Admin role to any member; Billing Admin is an add-on capability, not a separate role.

## Role changes

- An Owner or Admin can change a member's role in Settings → Members → Roles.
- An Admin cannot promote a member to Owner; only the current Owner can transfer ownership.
- An Admin cannot demote or remove another Admin. Only the Owner can remove an Admin.
- Removing an Admin requires the Owner to confirm the change by email.
- A member cannot change their own role.

## Transferring workspace ownership

1. The current Owner opens Settings → Members and selects the new Owner.
2. The current Owner confirms the transfer and completes MFA.
3. The new Owner accepts within 72 hours; otherwise the transfer expires.
4. The previous Owner becomes an Admin.

Ownership transfer is an account-sensitive action. Support cannot perform or approve a transfer, and cannot bypass the MFA requirement. If the Owner has left the company, escalate the request to Identity & Access with evidence of company authorization (for example an email from the current Owner's manager on the company domain). Never accept a personal email address as authorization.

## `permission_denied` errors

### Web application
A member sees "You don't have permission to perform this action" when their role lacks the capability or when object-level access restricts the ticket. Ticket visibility follows the workspace access model: **Open** (all members), **Restricted** (assigned team), or **Private** (creator and assignee).

### API
The API returns:

```json
{"error":{"code":"permission_denied","message":"Role 'agent' cannot manage integrations","required_scope":"admin:integrations"}}
```

Resolve by granting the role or issuing a token with the required scope. Scopes are not additive across roles; the effective permission is the intersection of role and token scope.

### SCIM-managed roles
If the workspace uses SCIM group mapping, roles set by SCIM override manual changes and are reapplied at the next SCIM sync (within 40 minutes). To change a role permanently, update the group membership in the identity provider.

## Guests and external collaborators

Guest seats can view and comment on explicitly shared tickets only. Guests cannot be assigned tickets, cannot access reports, and do not count toward the Agent seat count but do consume a guest seat allocation. Guest invitations require domain verification if the guest's domain is on the workspace deny list.

## Audit trail

Every role change, permission change, ownership transfer, API key creation, and SSO configuration change is written to the audit log with actor, timestamp in UTC, source IP, and previous and new values. Owners and Admins can export the audit log from Settings → Security → Audit Log.

## Member offboarding

When a member leaves:

1. Deactivate the member in the IdP if SCIM is enabled; otherwise deactivate them in Settings → Members.
2. Reassign their open tickets in bulk from the member's profile.
3. Rotate any API keys they created; key ownership does not transfer automatically.
4. Review integrations they authorized and reconnect them with a service account.

Deactivating a member frees their seat but keeps their historical comments attributed to their profile.

## Escalation guidance

Escalate to Identity & Access for:

- Ownership transfer when the current Owner is unreachable
- Suspected privilege escalation or unauthorized role changes
- Requests to bypass MFA or SSO enforcement
- Audit log questions involving another member's actions

Collect the workspace ID, member email (not the password), the attempted action, the exact error message, and the timestamp in UTC. Do not make role changes on the customer's behalf.
