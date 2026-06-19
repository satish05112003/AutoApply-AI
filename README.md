# AutoApply AI

AutoApply AI is an enterprise-grade autonomous job discovery, matching, and application platform. The system operates continuously to harvest job postings from multiple sources, analyze position requirements using a multi-agent AI architecture, match candidate profiles and resumes against target roles, construct customized application packages, and submit applications autonomously via headless browser automation. Designed for high reliability, scalability, and observability, the platform integrates live WebSocket notifications, real-time analytics, and automated tracking synchronizations.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Features](#features)
3. [System Architecture](#system-architecture)
4. [End-to-End Flow](#end-to-end-flow)
5. [Project Structure](#project-structure)
6. [Database Design](#database-design)
7. [Background Services](#background-services)
8. [AI Pipeline](#ai-pipeline)
9. [Job Discovery Pipeline](#job-discovery-pipeline)
10. [Application Pipeline](#application-pipeline)
11. [API Documentation](#api-documentation)
12. [Frontend Dashboard](#frontend-dashboard)
13. [Local Development Setup](#local-development-setup)
14. [Backend Setup](#backend-setup)
15. [Frontend Setup](#frontend-setup)
16. [Running the Complete System](#running-the-complete-system)
17. [Environment Variables](#environment-variables)
18. [Troubleshooting](#troubleshooting)
19. [Performance Optimizations](#performance-optimizations)
20. [Security Considerations](#security-considerations)
21. [Deployment](#deployment)
22. [Future Improvements](#future-improvements)
23. [License](#license)

---

## System Overview

### Why the Project Exists
Modern job search pipelines are highly fragmented, requiring manual monitoring of dozens of Applicant Tracking Systems (ATS) and career portals. Candidates waste substantial time filtering irrelevant listings, tailoring resumes, and filling repetitive forms, leading to search fatigue and missed opportunities.

### Problems Solved
- **Manual Scraping Overhead**: Automatically aggregates openings across direct job boards (Greenhouse, Lever, Ashby) and listings platforms.
- **Form-Filling Redundancy**: Programmatically interacts with web elements to enter candidate information, answer screening questions, and upload documents.
- **Tailoring Inefficiencies**: Performs vector-based matching and heuristic optimizations to select appropriate resume variants and compose contextually relevant application documents.

### High-Level Workflow
1. The platform executes scheduled crawls across direct integration APIs and public career portals.
2. New jobs are parsed, deduplicated, and ingested into a centralized PostgreSQL repository.
3. The AI engine scores the candidate's active profile and specialized resumes against the job description.
4. If the job matches preference thresholds, custom screening answers and cover letters are created.
5. In Full-Auto mode, browser automation scripts submit the application; in Semi-Auto mode, human review is requested via the UI.
6. Execution outcomes, metrics, and evidence screenshots are synced to Google Sheets and rendered on the live dashboard.

---

## Features

| Feature | Description |
| :--- | :--- |
| **Job Discovery** | Multi-board ingestion engine that crawls direct links and processes structured feeds. |
| **ATS Crawlers** | Scraping micro-agents designed for parsing public-facing API endpoints and career listing tables. |
| **Greenhouse Integration** | API crawler for Greenhouse board feeds to extract structured title, department, and description data. |
| **Lever Integration** | Native integration with Lever API boards supporting batched extraction of post listings. |
| **Ashby Integration** | Structured job board API integration utilizing Ashby's raw JSON endpoints. |
| **LinkedIn Integration** | Guest-session scraper that fetches recent postings using paginated API queries. |
| **Resume Matching** | Algorithmic alignment scoring candidate capabilities against extraction profiles. |
| **Job Analysis** | AI processing of unstructured descriptions into required skills, experience levels, and categories. |
| **AI Scoring** | Heuristic and vector-similarity comparison between specialized resumes and parsed job requirements. |
| **Cover Letter Generation** | Context-driven creation of custom application narratives matching role descriptions. |
| **Browser Automation** | Playwright pool manager that handles headless browser profiles and interactions. |
| **Auto Apply** | Multi-step form submission agent capable of identifying inputs, radio groups, and uploads. |
| **Google Sheets Sync** | Asynchronous service that publishes application tracking lines to a connected spreadsheet. |
| **Email Monitoring** | IMAP service that polls recruiter inboxes to flag status modifications and interview requests. |
| **Celery Task Queue** | Asynchronous job runner enforcing rate-limits, retries, and database transaction boundaries. |
| **Redis Queue** | Fast broker and transient memory store for task orchestration. |
| **PostgreSQL Storage** | Core relational database storing application states, user parameters, and job logs. |
| **Vector Search** | Optional Qdrant integration to run fast embeddings comparisons and deduplications. |
| **WebSocket Live Updates** | Real-time push channel transmitting execution status and logs to the client UI. |

---

## System Architecture

The interaction layout of the system components is modeled below:

```mermaid
graph TD
    UI[Next.js Client Dashboard] <-->|WebSockets / HTTP| API[FastAPI Backend REST API]
    API <-->|SQLAlchemy Engine Pool| DB[(PostgreSQL Database)]
    API <-->|Cache / PubSub| Redis[(Redis Broker)]
    Worker[Celery Worker - Solo Pool] <-->|Pulls Tasks| Redis
    Beat[Celery Beat Scheduler] -->|Schedules Discoveries / Retries| Redis
    Worker <-->|Reads/Writes| DB
    Worker -->|Browser Automation| Playwright[Playwright Browser Instances]
    Worker -->|Embeddings Search| Qdrant[(Qdrant Vector DB)]
    Worker -->|Crawl Requests| BoardAPIs[Greenhouse, Lever, Ashby, LinkedIn]
    Playwright -->|Submits Forms| CompanyPortals[Company Application Pages]
```

---

## End-to-End Flow

1. **User Registration**: The user registers on the platform, establishing their base credentials and generating a default profile record in the database.
2. **Resume Upload**: The user uploads their primary resume in PDF format. The system parses the document, extracts raw text, and generates specialized resume variants for different technical roles.
3. **Preference Configuration**: The user configures preferred job categories, locations, target salary bands, and minimum matching scores on the profile page.
4. **Job Discovery**: The Celery Beat scheduler triggers the `scheduled_discover_jobs` task, enqueuing crawl processes for each target source and role query.
5. **Job Ingestion**: The crawlers fetch listings, parse structure, filters non-technical entries, and checks duplication against existing database records before batch inserting.
6. **AI Analysis**: For every new job, the job analysis agent classifies the required experience, base skills, and role category.
7. **Matching**: The matching agent compares the job analysis requirements against candidate preferences and resume variants, generating a matching score.
8. **Application Generation**: If the match score meets thresholds, the system selects the best resume and generates responses to job-specific screening questions.
9. **Browser Automation**: In Full-Auto mode, a Playwright browser instance is spun up to navigate the application form, insert fields, upload the resume, and submit.
10. **Application Tracking**: The result of the submission (success, verification required, or failure) is stored in the database, alongside evidence screenshots.
11. **Google Sheets Synchronization**: Staged events are parsed and pushed to a connected Google Sheet spreadsheet via the Sheets integration service.
12. **Email Monitoring**: The IMAP tracker periodically monitors the candidate's email for replies, parsing headers to detect interviewer updates.

---

## Project Structure

The project structure is organized as follows:

```
AutoApply-AI/
├── .agents/                      # Agent instruction sets and skills definitions
├── backend/                      # Backend application folder
│   ├── alembic/                  # Alembic migration scripts and environment config
│   ├── app/                      # Main API application code
│   │   ├── agents/               # Multi-agent AI logic and orchestration pipelines
│   │   ├── api/                  # REST routers and request dependencies
│   │   ├── browser/              # Playwright browser form handler and session pool
│   │   ├── crawlers/             # Structured career board scraping scripts
│   │   ├── integrations/         # External integrations (Google Sheets, Vector DB)
│   │   ├── llm/                  # LLM routing, endpoints, and fallback handlers
│   │   ├── models/               # SQLAlchemy core model definitions
│   │   ├── services/             # Core business logics (auth, email, storage, profiles)
│   │   ├── tasks/                # Celery asynchronous tasks definitions
│   │   └── utils/                # General utilities (security, parsers, embedding tools)
│   ├── tests/                    # Backend testing suite
│   ├── alembic.ini               # Alembic configuration
│   ├── Dockerfile                # Backend containerization file
│   └── requirements.txt          # Python packages specification
├── frontend/                     # Next.js frontend application
│   ├── public/                   # Static UI assets
│   ├── src/                      # Source code
│   │   ├── app/                  # Next.js routing pages and dashboard layouts
│   │   ├── config.ts             # Environment environment config
│   │   └── store/                # Zustand global state management
│   ├── Dockerfile                # Frontend containerization file
│   └── package.json              # NPM dependencies and scripts
├── docker-compose.yml            # Core multi-service docker orchestrator
└── README.md                     # General setup and deployment reference
```

### responsibilities of major folders:
- **backend/app/agents/**: Contains the reasoning agents (Matching, Resume selection, Form Filling, and Screening) and the orchestrator that manages them.
- **backend/app/crawlers/**: Houses scraper logic customized per board (Greenhouse, Lever, Ashby, LinkedIn) inheriting from a common base scraper.
- **backend/app/services/**: Provides transactional database mutations and filesystem actions.
- **backend/app/tasks/**: Defines celery task entry points and isolation wrappers utilizing isolated async loops.
- **backend/app/models/**: Relational mapping tables mapping database schemas to Python objects.
- **backend/app/api/routers/**: HTTP routes defining access logic.

---

## Database Design

### Users
Stores account settings, authentication hashes, and execution status parameters.
- `id` (UUID, Primary Key)
- `email` (String, Unique)
- `hashed_password` (String)
- `is_active` (Boolean)
- `agent_enabled` (Boolean)
- `agent_mode` (String, defaults to "SEMI_AUTO")

### Preferences
Contains candidate matching rules and filters.
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key -> Users)
- `preferred_roles` (JSON Array of Strings)
- `preferred_locations` (JSON Array of Strings)
- `min_match_score` (Integer, defaults to 60)
- `auto_apply_threshold` (Integer, defaults to 75)

### JobPostings
Houses the raw listings data discovered by the crawls.
- `id` (UUID, Primary Key)
- `title` (String)
- `company` (String)
- `description` (Text)
- `location` (String)
- `url` (String, Unique)
- `source` (String)
- `external_id` (String)
- `created_at` (DateTime)

### Applications
Tracks matching decisions, custom answers, and execution outcomes.
- `id` (UUID, Primary Key)
- `user_id` (UUID, Foreign Key -> Users)
- `job_id` (UUID, Foreign Key -> JobPostings)
- `match_score` (Float)
- `status` (String, e.g. "PENDING_APPROVAL", "SUBMITTED", "FAILED")
- `resume_used` (String)
- `generated_answers` (JSON Object)
- `evidence_screenshot` (String)

### DiscoveryLogs
Stores metadata results for every execution of a crawl.
- `id` (UUID, Primary Key)
- `source` (String)
- `status` (String)
- `jobs_found` (Integer)
- `jobs_new` (Integer)
- `crawl_completed_at` (DateTime)

### ApplicationLogs
Execution steps logged during a Playwright auto-submission task.
- `id` (UUID, Primary Key)
- `application_id` (UUID, Foreign Key -> Applications)
- `step_name` (String)
- `status` (String)
- `message` (Text)
- `timestamp` (DateTime)

---

## Background Services

| Service | Purpose |
| :--- | :--- |
| **FastAPI** | REST API serving frontend requests and handling WebSocket connections. |
| **Celery Worker** | Asynchronous worker process that runs crawlers and browser automations. |
| **Celery Beat** | Periodic scheduler that enqueues discovery passes and application retries. |
| **Redis** | Message broker for Celery tasks and cache store. |
| **PostgreSQL** | Primary relational transactional database. |
| **Qdrant** | Semantic database storing document embeddings for matching (optional). |
| **Playwright** | Browser automation library utilized by Celery workers to submit applications. |

---

## AI Pipeline

The matching, tailoring, and form-submission decisions are handled by isolated agents coordinated by a centralized orchestrator:

```
[New Job Posting] 
       │
       ▼
┌──────────────────────────┐
│   Job Analysis Agent     │ ──► Extracts category, skills, and experience level
└──────────────────────────┘
       │
       ▼
┌──────────────────────────┐
│      Matching Agent      │ ──► Scores job details against profile & resume variants
└──────────────────────────┘
       │
       ▼
┌──────────────────────────┐
│ Screening Question Engine│ ──► Composes contextually accurate answers to forms
└──────────────────────────┘
       │
       ▼
┌──────────────────────────┐
│    Application Agent     │ ──► Selects best resume & initiates Playwright script
└──────────────────────────┘
```

- **Job Analysis Agent**: Reads unstructured text, identifies technical requirements, experience limits, and flags entries that do not qualify as technical positions.
- **Matching Agent**: Uses lexical comparison, experience calculations, and vector comparisons to generate an aggregate match score between candidate profile and job requirements.
- **Screening Question Engine**: Iterates over form inputs, utilizing LLM context blocks to write answers to customized fields (e.g. salary expectation, visa needs).
- **Application Agent**: Coordinates the Playwright task loop, matching DOM inputs against text values and executing form validation checks.
- **Orchestrator**: Acts as the transactional controller, managing DB session states and committing logs.

---

## Job Discovery Pipeline

### Data Extraction
Crawlers pull data via distinct pathways:
- **Greenhouse / Lever / Ashby**: Structured API endpoints are queried for specific company board handles.
- **LinkedIn**: Programmatic HTTP requests simulate guest searches for targeted role keywords.

### Deduplication
Each crawled job is validated before insertion:
- A database-level unique constraint on `url` prevents exact-duplicate ingestion.
- (Optional) Document text is passed to Qdrant to calculate cosine similarity; descriptions matching existing jobs above 98% are discarded.

### Freshness Filtering
To optimize resources, crawlers default to parsing listings created or updated within the last 24 hours.

### Ingestion Flow
Discovered jobs are parsed, bulk-inserted, and matching tasks are triggered instantly for any candidates whose discovery daemon is active.

---

## Application Pipeline

- **Resume Matching**: Compares candidate's specialized resume formats (e.g., Frontend, Python, Machine Learning) to the target job profile.
- **Scoring**: Calculates matching values based on requirements alignment.
- **Shortlisting**: Statically routes jobs scoring above the candidate's minimum setting (`min_match_score`) into `PENDING_APPROVAL` (Semi-Auto) or `SHORTLISTED` (Full-Auto).
- **Auto-Apply**: Playwright loads browser profiles, enters data fields, attaches resumes, handles checkbox approvals, and submits the form.
- **Status Tracking**: Updates database records upon completion, saving confirmation details and screenshots.

---

## API Documentation

| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/auth/login` | `POST` | Authenticates candidate and issues JWT access tokens. |
| `/api/v1/profile` | `GET`/`PUT` | Fetches and updates candidate information and credentials. |
| `/api/v1/resumes` | `POST`/`GET` | Uploads raw PDFs and registers specialized resume profiles. |
| `/api/v1/jobs` | `GET` | Paginated search of crawled job listings. |
| `/api/v1/applications` | `GET` | Lists all matched, pending, and submitted applications. |
| `/api/v1/agents/status` | `GET` | Fetches state maps of running daemons and Redis connectivity. |
| `/api/v1/agents/refresh-jobs` | `POST` | Forces an immediate manual crawl of all job boards. |
| `/api/v1/analytics/overview`| `GET` | Compiles dashboard statistics (success rates, score averages). |
| `/ws/{user_id}` | `WS` | WebSocket stream providing real-time log prints. |

---

## Frontend Dashboard

- **Control Center**: Displays daemon controllers, live status badges, and sheet synchronizations.
- **Agent Orchestrator**: Shows buttons to toggle job discovery, IMAP trackers, and system modes.
- **Statistics**: Renders critical KPIs including shortlisted files, submitted values, and average match scores.
- **Live Logs**: Dedicated console panel streaming backend task outputs via WebSockets.
- **Google Sheets**: Status board showing Google Sheets linkage data.
- **System Status**: Displays WebSocket connectivity and backend system connection health.

---

## Local Development Setup

### Prerequisites
Ensure the following are installed:
- **Python**: `3.10` or higher (virtual environment recommended).
- **Node.js**: `18` or higher (with npm package manager).
- **PostgreSQL**: Local database instance running on port `5432`.
- **Redis**: Running instance on port `6379`.
- **Playwright**: Installed browser binaries.

---

## Backend Setup

1. Navigate to the backend folder:
   ```bash
   cd backend
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   # On Windows:
   .\venv\Scripts\activate
   # On Unix/macOS:
   source venv/bin/activate
   ```
3. Install required packages:
   ```bash
   pip install -r requirements.txt
   ```
4. Install Playwright browser binaries:
   ```bash
   playwright install chromium
   ```
5. Copy the environment template and customize values:
   ```bash
   cp ../.env.example .env
   ```
6. Run database migrations:
   ```bash
   alembic upgrade head
   ```
7. Start the API server:
   ```bash
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```

---

## Frontend Setup

1. Navigate to the frontend folder:
   ```bash
   cd frontend
   ```
2. Install npm packages:
   ```bash
   npm install
   ```
3. Start the Next.js development server:
   ```bash
   npm run dev
   ```
   The client will run at `http://localhost:3000`.

---

## Running the Complete System

To run the complete system, launch the services in this exact order:

1. **Start PostgreSQL**: Make sure the local database service is active and the `autoapply_ai` database is reachable.
2. **Start Redis**:
   ```bash
   redis-server
   ```
3. **Start Backend API**: Activate virtual environment and run:
   ```bash
   cd backend
   uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
4. **Start Celery Worker**: Activate virtual environment and run:
   ```bash
   cd backend
   celery -A app.celery_app worker --loglevel=info --pool=solo
   ```
5. **Start Celery Beat**: Activate virtual environment and run:
   ```bash
   cd backend
   celery -A app.celery_app beat --loglevel=info
   ```
6. **Start Frontend Client**:
   ```bash
   cd frontend
   npm run dev
   ```

---

## Environment Variables

| Variable | Description |
| :--- | :--- |
| `DATABASE_URL` | PostgreSQL async connection URI (`postgresql+asyncpg://user:pass@host:port/db`). |
| `REDIS_URL` | Redis server URL used by Celery and cache handlers. |
| `JWT_SECRET_KEY` | Symmetric encryption key used to sign session tokens. |
| `STORAGE_TYPE` | Storage target mode (set to `local` or `minio`). |
| `OLLAMA_BASE_URL` | Endpoint host URL for local Ollama instances. |
| `GROQ_API_KEY` | Authorization key for Groq API services. |
| `OPENROUTER_API_KEY` | Authorization key for OpenRouter API services. |
| `QDRANT_URL` | Endpoint host URL for Qdrant database services. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Credentials string used to write tracking rows to Google Sheets. |
| `SMTP_HOST` | Host address of target outgoing mail servers. |
| `SMTP_USER` | Email user login credentials. |
| `SMTP_PASSWORD` | App password used to send notification emails. |

---

## Troubleshooting

### Redis Offline
- **Symptom**: Dashboard shows critical warning or celery task registration fails.
- **Fix**: Verify local Redis service status:
  ```bash
  redis-cli ping
  ```
  Ensure Redis is listening on port `6379`.

### Celery Worker Not Processing Jobs
- **Symptom**: Refresh requests remain stuck or task details do not appear in console.
- **Fix**: Restart the worker process. Ensure the worker is started with the correct configuration (`--pool=solo` is mandatory on Windows environments). Check if worker outputs task registration lists on startup.

### WebSocket Reconnect Loop
- **Symptom**: Console outputs constant closed events, and UI badges toggle rapidly.
- **Fix**: Confirm that the backend FastAPI app is running on port `8000`. If utilizing proxies, verify WebSocket headers (`Upgrade`, `Connection`) are correctly forwarded.

### Qdrant Unavailable
- **Symptom**: Matching functions output timeout errors or slow search responses.
- **Fix**: Confirm that the Qdrant database container is listening on port `6333`. If Qdrant is offline, the backend client will fallback to local heuristic matching automatically.

### No Jobs Discovered
- **Symptom**: Discovery runs complete with zero results returned.
- **Fix**: Verify database preference fields for the logged-in candidate. If the active candidate has no preferred roles or locations configured, the scheduler ignores the account.

### Frontend Unable to Reach Backend
- **Symptom**: API endpoints return network connection failures.
- **Fix**: Verify that `NEXT_PUBLIC_API_URL` inside `frontend/.env.local` accurately targets the running FastAPI port.

### Playwright Failures
- **Symptom**: Form submissions crash with selector missing exceptions.
- **Fix**: Run Playwright script in non-headless mode to visually trace selectors:
  ```env
  PLAYWRIGHT_HEADLESS=false
  ```
  Update targeted CSS element strings in `backend/app/browser/form_handler.py`.

---

## Performance Optimizations

- **Batch Ingestion**: Job Service parses list records and executes database bulk inserts, reducing connection overhead.
- **Database Indexes**: Performance indexes are applied to search query constraints (`job_postings.created_at`, `applications.status`) to optimize query speeds.
- **Celery Background Processing**: Heavy operations (crawls, submissions) are dispatched to the message queue, preserving main thread response times.
- **Vector Search Optimization**: Uses Qdrant collections with small dimensional limits to run quick cosine comparisons.

---

## Security Considerations

- **Secret Management**: API keys and tokens are loaded strictly from system configurations and environment files.
- **Environment Variables**: Template files (`.env.example`) are checked into git; specific `.env` files containing credentials are excluded.
- **Git Ignore Rules**: Strict exclusions are configured globally to prevent tracking local state caches, binary uploads, PDF documents, or Playwright browser profiles.
- **Resume Privacy**: Uploaded documents are saved under hashed candidate directories within local storage to prevent public file exposures.
- **Database Access**: Relational models utilize parameterized queries to prevent SQL injection risks.
- **Browser Automation Safety**: staging environments default to `DRY_RUN=True` to run simulations without executing final submit buttons.

---

## Deployment

- **Backend**: FastAPI runs inside a Docker container, scaled behind Nginx reverse proxies, with SSL termination at the gateway level.
- **Frontend**: Next.js client is compiled and deployed to cloud nodes or container instances, pointing base variables to the backend service.
- **Redis**: Deployed as an isolated caching instance with authentication enabled.
- **PostgreSQL**: Set up as a managed instance with automatic backups enabled.
- **Qdrant**: Runs as a separate vector storage node with API authorization.

---

## Future Improvements

- Add support for multi-step CAPTCHA solving integrations.
- Support auto-apply submissions for direct company portals (Workday, SuccessFactors).
- Introduce multi-account tracking and agent analytics.

---

## License

This project is licensed under the terms of the MIT License.
