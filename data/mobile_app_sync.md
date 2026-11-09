# NimbusDesk Mobile App Sync and Troubleshooting

Last updated: 2026-08-08
Owner: Mobile Team
Applies to: NimbusDesk iOS 5.2+ and Android 5.2+

## How sync works

The mobile app caches tickets, contacts, and comments locally. When the device is online, changes sync every 30 seconds in the foreground and every 5 minutes in the background (subject to OS background limits). Actions taken offline are queued and replayed when connectivity returns.

Conflict handling: the last write wins per field, based on the server's `updated_at`. Comments are append-only and never conflict. A comment created offline is flagged **Pending sync** until the server acknowledges it.

## Common issues

### Changes on desktop do not appear on mobile
1. Pull to refresh on the relevant list.
2. Force-quit and reopen the app; this triggers a full sync on launch.
3. Confirm the mobile user is signed into the same workspace. The workspace name is shown under Settings → Workspace.
4. Confirm the ticket is not filtered out by the mobile default filter (for example "Assigned to me").

### Comments stuck in "Pending sync"
- Check connectivity and confirm the app is allowed to use background data.
- Keep the app open for 60 seconds; the queue drains fastest in the foreground.
- Do not sign out with pending items; signing out discards the local queue and those comments are lost.
- If a comment remains pending for more than 24 hours while online, clear the app cache (Android) or reinstall (iOS) after confirming there are no other pending items, then escalate with the comment IDs.

### Stale data after a role change
Mobile caches permissions for up to 15 minutes. Sign out and back in to force a fresh token and permission set. Revoked users are signed out at the next token refresh, which can take up to 15 minutes.

### Push notifications not arriving
1. Confirm notifications are allowed in the OS settings for NimbusDesk.
2. Confirm notification preferences in the app: Settings → Notifications, and in the web app under Profile → Notifications.
3. Check Focus / Do Not Disturb and battery optimization settings. On Android, exclude NimbusDesk from battery optimization for reliable push.
4. Toggle the notification permission off and on to re-register the device token.
5. If the user recently restored a phone backup, the device token may be stale; sign out and back in.

### App crashes on opening a ticket with many attachments
Known issue in 5.1, fixed in 5.2. Ask the user to update. If updating is not possible, open the ticket in a mobile browser.

### Login loop after SSO sign-in
The app uses the system browser for SSO. If the browser has stale cookies from a different tenant, use a private browsing session or clear browser cookies, then retry. Confirm the IdP is configured to allow the NimbusDesk mobile callback.

## Supported versions

| Platform | Supported | End of support |
| --- | --- | --- |
| iOS | 5.2 and later; iOS 16+ | 5.0 ended 2026-06-30 |
| Android | 5.2 and later; Android 10+ | 5.0 ended 2026-06-30 |

Unsupported versions continue to work for 90 days after end of support, then receive a mandatory upgrade prompt.

## Clearing cache

- Android: Settings → Apps → NimbusDesk → Storage → Clear cache. This does not delete the signed-in session.
- iOS: there is no cache control; delete and reinstall the app. Confirm that no actions are pending sync first.

## Offline limits

- Up to 500 queued actions per device.
- Attachments over 25 MB cannot be uploaded from mobile.
- Offline mode is not available for SSO-enforced workspaces without a successful online sign-in in the last 30 days.

## Escalation guidance

Escalate to the Mobile Team when:

- Crashes reproduce on the latest version with steps to reproduce
- Sync is stuck for more than 24 hours while online and pending items are not visible on the web app
- Push notifications fail for all users in a workspace

Collect: platform and OS version, app version, device model, workspace ID, approximate timestamps in UTC, whether the user is on cellular or Wi-Fi, and a screen recording if possible. Do not request the user's password or MFA code.
