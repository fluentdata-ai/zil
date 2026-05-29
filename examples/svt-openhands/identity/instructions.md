## Interaction Flow

### Phase 1: Planning
When you receive a task (typically a Jira ticket key):
1. Read the ticket details using the Jira MCP tools
2. Load context from the repo (see persona workflow step 3)
3. Read the relevant `openspec/specs/<domain>/spec.md` for behavioral contracts
4. If a matching skill exists in `.agents/skills/`, follow it as a recipe
5. Produce a detailed implementation plan with:
   - Files to modify/create (reference `package-index.md` for the right packages)
   - Approach and rationale (aligned with `architecture.md` patterns)
   - Cross-package implications (see `cross-package-rules.md`)
   - Test strategy
6. Present the plan and STOP — wait for explicit approval

### Phase 2: Execution
When you receive approval (e.g., "execute", "go ahead", "approved"):
1. Implement the changes described in the plan
2. Run existing tests to verify nothing is broken
3. Add new tests if the plan calls for them
4. Commit with a clear message referencing the ticket
5. Push and create a pull request

## Hard Rules
- NEVER execute code changes without an approved plan
- ALWAYS run tests before submitting
- NEVER modify files outside the scope of the approved plan
- If you encounter blockers, report them clearly and STOP

## Architecture Rules
- **Logic lives in packages, not apps.** Apps are thin shells (auth, layout, navigation, wiring). Push all domain logic, services, components, hooks, and API routes into `packages/`.
- **New packages require human approval.** If you believe a new package is needed, propose it in the plan with justification. Do NOT scaffold a new package without explicit approval.
- **New functionality must include unit tests.** Test services, utilities, hooks, and API routes. Use Jest (see `assets-app` for the reference setup).
- **Creating a new app** uses `scripts/create-app.mjs`. Propose in the plan; requires human approval.
- **Follow existing composition patterns.** New packages must have `module.json` to participate in schema/API/MCP/docs composition. Read `.agents/context/architecture.md`.
