# Security Policy

## Reporting a vulnerability

Please **do not open a public issue** for security problems. Use GitHub's
private vulnerability reporting instead:
<https://github.com/amirmahmoodv/similiarityly/security/advisories/new>

Include what you found, how to reproduce it, and the impact you expect. You
should get an acknowledgement within a few days; fixes are released as soon as
practical and credited to the reporter unless you prefer otherwise.

## Supported versions

Only the latest commit on the default branch receives security fixes.

## Deployment model

Similarityly has no user accounts. Its threat model assumes that either
`SIM_API_TOKEN` is set, or the service is reachable only by trusted users
(local-only binding, VPN, or an authenticating reverse proxy). Running it on an
untrusted network without a token is unsupported. See the
[Security section of the README](README.md#security).
