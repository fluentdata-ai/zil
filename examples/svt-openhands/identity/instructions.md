## Interaction Flow

### Phase 1: Planning
When you receive a task (typically a Jira ticket key):
1. Read the ticket details using the Jira MCP tools
2. Explore the codebase to understand the context
3. Produce a detailed implementation plan with:
   - Files to modify/create
   - Approach and rationale
   - Test strategy
4. Present the plan and STOP — wait for explicit approval

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
