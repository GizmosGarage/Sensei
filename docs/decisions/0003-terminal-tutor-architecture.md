# ADR 0003: Terminal tutor architecture

- **Status:** Amended
- **Date:** 2026-08-21
- **Amended:** 2026-08-29

## Decision

Separate terminal tutoring into three roles:

- `TutorSession` owns pedagogical modes and bounded problem context.
- `ChatProvider` defines the model-independent inference boundary.
- `ResponsesAPIProvider` owns authentication, request/response validation,
  streaming, retries, and hosted endpoint configuration.

Every request contains one consolidated system message, the active problem, and at
most 12,000 characters of recent exchanges. The active problem is stored separately
so trimming cannot remove it. Starting a new problem resets transient history.

Long-term learning memory is not chat history. SQLite owns structured attempts,
misconceptions, mastery, review dates, and XP. A small relevant memory summary can be
added to the system context.

## Consequences

- Tutor policy is testable without network requests.
- Provider changes do not affect storage or progression code.
- Hosted API credentials are required before startup.
- A character budget approximates rather than exactly measures provider tokens.
