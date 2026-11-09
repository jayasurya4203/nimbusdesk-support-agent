# Database Connector Troubleshooting

Last updated: 2026-09-08
Owner: Data Platform
Applies to: Snowflake, PostgreSQL, MySQL, BigQuery, Redshift, and SQL Server connectors (Scale and Enterprise)

## Overview

Database connectors let NimbusDesk sync ticket and contact data to your warehouse, or enrich tickets with lookup tables. Connectors run in the workspace's region and use read-only credentials for lookups. Writes are only performed to tables that the connector created with the `nimbus_` prefix.

## Required configuration

- Host and port (or account identifier for Snowflake/BigQuery)
- Database and schema
- Username and password or key-pair authentication
- TLS mode: `require` or `verify-full`. `disable` is rejected in production.
- Egress CIDR allowlist on the database side: see `https://trust.nimbusdesk.io/sending-ips` for the NimbusDesk egress ranges. Note that connector egress ranges are listed separately from email sending IPs.

## Common errors

### `db_connection_refused`
The database rejected the TCP connection. Causes: firewall or security group not allowing the NimbusDesk egress range, the database paused (Snowflake auto-suspend or an idle warehouse), or the host/port incorrect.
**Resolution:** allow the egress ranges, resume the warehouse, and verify the host and port. Use **Test connection** after each change.

### `db_tls_required`
The server requires TLS but the connector is configured without it, or the server certificate is not trusted.
**Resolution:** set the TLS mode to `verify-full` and upload the CA certificate if it is not publicly trusted. Self-signed certificates are supported only with an uploaded CA, not with `verify-full` alone.

### `db_auth_failed`
Invalid username or password, an expired key pair, or the user lacks `USAGE` on the schema.
**Resolution:** rotate the credential in your database, update it in the connector, and grant `USAGE` on the schema plus `SELECT` on the referenced tables. NimbusDesk never displays the stored password; it must be re-entered.

### `db_query_timeout` / `internal_error`
A query exceeded the 30-second statement timeout. This surfaces to end users as a generic `internal_error` on ticket pages that use a lookup column.
**Resolution:**

1. Confirm the lookup query is indexed on the join column.
2. Add a filter to reduce the scan (for example restrict by `created_at` in the last 90 days).
3. Increase the warehouse size for Snowflake or add read replicas for PostgreSQL.
4. Reduce lookup frequency: cache lookups for up to 15 minutes in the connector settings.

### `db_schema_drift`
A referenced column was renamed, dropped, or changed type.
**Resolution:** open the connector's field mapping, remap the missing column, and run **Validate schema**. Schema changes are detected within 10 minutes; the connector pauses sync until mappings are valid.

### `db_row_limit_exceeded`
Lookup results exceeded the 10,000-row safety limit. Add a more selective query; NimbusDesk will not load unbounded result sets into a workspace.

### `db_ssl_certificate_expired`
The database server certificate expired.
**Resolution:** renew the certificate on the database server, then re-run **Test connection**. NimbusDesk does not offer an option to ignore certificate expiry.

## Sync behavior

- Full sync runs nightly; incremental sync runs every 15 minutes for Scale and Enterprise.
- A failed incremental sync retries three times with backoff, then pauses the connector and notifies workspace Admins.
- Deleting rows in the source does not delete tickets; lookups return "Not found" for missing rows.
- Connector logs retain 14 days of query metadata. Result rows are not logged.

## Security requirements

- Use a dedicated read-only database user for lookups. Do not use an admin account.
- Rotate credentials every 90 days. The connector warns 14 days before a configured rotation deadline.
- Do not enable write access unless the `nimbus_` tables are dedicated to NimbusDesk.
- Database credentials are encrypted at rest with AES-256-GCM and are never returned by the API.

## Escalation guidance

Escalate to the Data Platform team when:

- `Test connection` succeeds but the first sync fails with a 5xx from NimbusDesk
- Multiple connectors fail simultaneously in different regions
- `internal_error` pages persist after the query is optimized and indexed
- A credential rotation cannot be saved while the database is reachable

Collect: connector ID, database engine and version, error code, timestamp in UTC, whether Test connection succeeded, the exact query name (not customer data), and the workspace region. Never request database credentials in the ticket.
