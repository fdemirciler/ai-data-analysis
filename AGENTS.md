# AGENTS.md - AI Data Analyst Project

## Commands

**Frontend (React/Vite/TypeScript)**
- Build: `npm run build` (in frontend/)
- Dev server: `npm run dev` (in frontend/)
- No test framework configured yet

**Backend (Python/Google Cloud)**
- Run tests: `pytest` (in backend/run-preprocess/, backend/functions/sign_upload_url/, backend/functions/orchestrator/)
- Run single test: `pytest path/to/test_file.py::test_function_name`
- Deploy: PowerShell scripts `deploy-preprocess.ps1`, `deploy-analysis.ps1` (in backend/)

## Architecture

**Monorepo**: Frontend (React/Vite) + Backend (Google Cloud Functions & Cloud Run)
- `frontend/`: React app with Radix UI, Tailwind, Firebase Auth, SSE chat interface
- `backend/functions/sign_upload_url/`: Cloud Function for secure GCS upload URLs
- `backend/functions/orchestrator/`: Main Cloud Function handling chat/analysis with Gemini AI
- `backend/run-preprocess/`: Cloud Run service for data preprocessing (Pandas/Polars/Parquet)
- `backend/shared/`: Shared utilities (AST validation, etc.)
- **Database**: Firestore (sessions, datasets, messages, user profiles)
- **Storage**: Google Cloud Storage (files bucket)
- **AI**: Gemini 2.5 Flash for code generation; sandboxed Python execution

## Code Style

**Python**: Standard library imports first, then third-party, then local. Use type hints. Follow existing patterns for error handling (logging module). Imports organized by relative imports with fallbacks for tests.

**TypeScript/React**: Functional components with hooks. Use existing Radix UI components. Imports: React/external libs, then internal services/components/types. Use `type` keyword for type-only imports. Follow existing naming: PascalCase for components, camelCase for functions/variables.

**General**: Mimic existing code style. Check neighboring files for conventions. No unnecessary comments unless complex logic requires explanation.
