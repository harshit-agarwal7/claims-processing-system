## Project

A **Claims Processing System** for an insurance company.

Members submit claims for reimbursement. The system must determine what's covered, how much to pay, and track the claim through its lifecycle.

---

See [docs/domain-concepts.md](docs/domain-concepts.md) for the full domain model and vocabulary.

See [docs/acceptance-criteria.md](docs/acceptance-criteria.md) for acceptance criteria and scope boundaries.

---

## Directory Structure

- application code in `app/`, tests in `tests/`, config in `config/`

---

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.13 |
| Backend API | Flask |
| Database | SQLite |
| ORM | Flask-SQLAlchemy |
| Frontend | Vanilla JavaScript |
| LLM | OpenRouter |
| Tooling | Astral ecosystem (uv, ruff) |

---

## Code Standards

- Type hints on all function signatures
- One module = one responsibility
- No premature abstractions: don't create templates or helpers that are only used once. Inline values unless they're shared across 2+ call sites.
- No hardcoded secrets or magic numbers
- Google-style docstrings on all public functions
- Use `logging`, never `print()` for diagnostics
- No bare `except:` — always catch specific exceptions, log meaningful error messages.

---

## Dependencies

- Justify any new dependency before adding it
- Pin versions in pyproject.toml
- Use virtual environments. Never install globally

---

## Testing

- Think about how you would verify the working of any code you add - first write the tests and then go about writing the code.
- Run tests before presenting work as done
- Ensure that whenever you make a change, you check if any existing tests need to be updated.
- Run `ruff format`, `ruff check`, and `mypy` before finishing

---

## Git

- Commits: conventional commits format (feat:, fix:, chore:)
- Suggest a commit message when you are done with a set of changes. Always run `git diff HEAD` and `git status` to see the full picture of all uncommitted changes across the entire repo to suggest a commit message.

## Documentation
 
- Document what is included in the scope and left out of the scope along with any assumptions made in `docs/decisions.md`. Ensure that there is no duplication in the content of the file with time.

