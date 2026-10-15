# WeChat QQ AI Panel

- Windows tray panel using Python, pywebview and pystray. Static HTML has no local HTTP listener.
- Read messages only through the sibling access repository JSON interface; never load original databases, credentials or QCE tokens here.
- All model inputs must be authorized immediately before sending. Permission changes invalidate results and cancel active tasks.
- DSH runs with a fail-closed no-tools guard and private session storage. Never fall back to an unrestricted profile or another provider.
- No sending, automatic replies, background collection, CU or GUI automation. Real DSH model tests are performed by the operator.
- Keep runtime, secrets, logs, results, account identifiers and messages outside public source. Diagnostics contain counts/times/error codes only.
- Cleanup defaults to preview then the Windows Recycle Bin. Never empty the bin or fall back to permanent deletion.
- Use synthetic fixtures for tests. Do not commit or publish without checking repository boundaries and the user's provenance classification.
