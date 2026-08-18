# Security

Do not report a security issue in a public issue.

No private security contact has been configured for this repository. Until one
is configured, send the report to the PrismML repository owner through an
existing private channel.

## Sensitive files

Never commit:

- Customer deal room files
- API keys or signing keys
- Private model weights
- Raw prompts, answers, or reviewer notes from private work
- Trace exports that contain confidential content

Local secrets belong in `.env` or `.runtime/`, which Git ignores. Synthetic and
public fixtures must state their data classification in their manifest.

## Prototype boundary

The current local sandbox, routing controls, and loopback checks are engineering
controls. They are not a certified isolation boundary or a proof of an air gap.
