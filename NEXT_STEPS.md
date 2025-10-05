Next session reminder

- Continue testing the search and add-to-cart flow on coop.se (semantic tools first).
- Add agent capabilities to observe and learn new surfaces:
  - Detect and summarize new modals/prompts; resolve via semantic actions.
  - Persist robust hints when semantics are insufficient (optional).
  - Prefer role/label/text discovery before selectors.

## Temporal v2 rollout
- Start Temporal server/UI: `make temporal-up`
- Start worker: `make worker`
- Use new endpoints:
  - POST `/v2/run/authentication` with `{ "store": "coop_se", "headless": true, "debug": true }`
  - POST `/v2/run/shopping` with `{ "store": "coop_se", "headless": true, "debug": true }`
- Monitor runs in Temporal UI at `http://localhost:8080`
