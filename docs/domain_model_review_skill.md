Review the markdown file at docs/data_model.md which defines the domain model for a claims processing system.
This model will be directly implemented as database tables (SQLite + SQLAlchemy ORM),
API endpoints (Flask), and frontend state. Your job is to find every issue that would
cause problems during implementation or at runtime — before a single line of code is written.

Work through each section below systematically. For each finding, state:
- SEVERITY: BLOCKER | MAJOR | MINOR
- LOCATION: which entity/relationship/state machine
- PROBLEM: what is wrong or ambiguous
- RECOMMENDATION: the specific fix

---

## 1. Entity Completeness
- Is every real-world object that the system must track represented?
- Are there entities implied by relationships that are not explicitly defined (e.g., a many-to-many requires a join entity)?
- Are all attributes present for each entity to satisfy the acceptance criteria?
- Are attribute types, nullability, and default values specified where they matter?
- Are there computed/derived attributes that should be stored vs. calculated?

## 2. Relationship Correctness
- Verify cardinality (1:1, 1:N, M:N) for every relationship. Check each direction independently.
- Are all foreign keys explicitly named? Which side owns the FK?
- For every M:N relationship: is there a join/association entity? Does it need its own attributes?
- Are cascade rules defined (what happens to children when a parent is deleted/updated)?
- Are there circular dependencies that would cause issues in ORM or migration order?
- Are there relationships that are optional vs. required — and is that clearly stated?

## 3. State Machine Correctness
- For each state machine, list all states and verify:
  - Is there exactly one initial state?
  - Are all terminal (absorbing) states correct and complete?
  - Is every state reachable from the initial state?
  - Are there dead states (states with no outgoing transitions that are not intended terminals)?
- For each transition, verify:
  - Is the trigger/event defined?
  - Are guard conditions specified where a transition only applies in certain cases?
  - Are side effects (actions on entry/exit) documented?
  - Can two transitions fire simultaneously from the same state — and if so, is the conflict resolved?
- Cross-entity state dependencies: if entity A's state constrains entity B's allowed transitions, is that captured?
- Are there implicit state transitions buried in business rules that should be made explicit?

## 4. Internal Consistency
- Every entity referenced in a relationship must be defined — flag any dangling references.
- Every state referenced in a transition must be in the state list for that machine.
- Attribute names used in guard conditions must exist on the relevant entity.
- Naming: are the same concepts referred to by different names in different sections?

## 5. Business Rule Coverage
- Cross-reference every rule in the acceptance criteria against the model. Flag any rule that has no corresponding entity attribute, relationship, or state transition to enforce it.
- Are all validation rules (e.g., claim amount <= coverage limit) expressible with the current model, or would they require attributes that don't exist?
- Are audit/history requirements (who changed what, when) addressed by the model?

## 6. Implementability
- Would a developer need to make any non-trivial assumptions to map this model to ORM classes? List each ambiguity.
- Are there attributes that need indexing for expected query patterns (e.g., status lookups, date range queries)?
- Are soft deletes vs. hard deletes addressed for any entity?
- For state machines: is the current state stored as an attribute on the entity? Is its type (enum, string) specified?
- Is there anything in the model that would require a migration to fix after initial implementation?

## 7. Summary
End with:
1. A prioritized list of all BLOCKERs that must be resolved before implementation begins.
2. A list of open questions where the model is ambiguous and a decision is needed.
3. An overall assessment: is this model ready to implement, or does it need another revision?

---

## 8. Query Efficiency Analysis

1. **Infer common read paths** — what queries will the application need to run given the domain (e.g. "load a claim with all its line items and current adjudication results"). For each, write out the approximate SQL (tables joined, WHERE clauses, ORDER BY).

2. **Infer common write paths** — what INSERTs/UPDATEs/DELETEs will the application need, and in what transactional groupings. Note any ordering constraints (e.g. parent must exist before child).

3. **Recommend indexes** — for each read path, identify which columns need indexes (foreign keys, filter columns, sort columns). Flag any unique constraints mentioned in the model that should be enforced at the DB level.

4. **Flag efficiency risks** — N+1 patterns that are likely given the relationships, queries that will require full scans without indexes, any "get the latest revision" or "get current result" patterns that need special handling.

5. **Summarize** as a prioritized list of index recommendations and query design decisions to make before implementation, so they can be built in from the start rather than retrofitted.

Feel free to recommend a design change if required instead of just focus on index recommendations and query design decisions.