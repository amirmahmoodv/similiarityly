# Contributing

Thanks for helping improve Similarityly!

1. Open an issue first for anything larger than a small fix, so the approach can be agreed.
2. Fork, create a branch, and keep the change focused.
3. Make sure the checks pass:

   ```bash
   cd backend && uv run pytest && uv run ruff check .
   cd frontend && npm run lint && npm run typecheck && npm test && npm run build
   ```

4. Open a pull request describing what changed and why.

## Conventions

- **Backend:** FastAPI + Pydantic; errors are returned as stable string codes
  (`HTTPException(400, "some_code")`) that the UI translates.
- **Frontend:** every user-visible string lives in `src/i18n/fa.ts` (the source
  of truth) and `src/i18n/en.ts`; key parity is enforced by the type checker.
  Numbers always go through the shared formatters in `src/lib/format.ts`.
- See `frontend/CLAUDE.md` and `frontend/VISUAL-QA.md` for UI and motion standards.

Security issues: please follow [SECURITY.md](SECURITY.md) instead of opening an issue.
