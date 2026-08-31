# Infra questionnaire — User Feedback (**Production only**)

**Current environment is UAT** (project `pidilite-user-feedback-ai`, `asia-south1`). This request is **only for a new Production environment**. Do not provision another UAT.

This application is **not** Windows/Linux VMs. It runs as **GCP Cloud Run (containers) + Cloud SQL (managed PostgreSQL) + Cloud Storage**. Sections 3 and 5 map those services to the form’s “server” fields. Section 4 (UAT) is **not applicable**.

IAM: [prod-gcp-access.md](prod-gcp-access.md).

**Production volume (sizing basis):** **5,000 calls per day.**

| Assumption | Value | Result |
|------------|-------|--------|
| Calls | 5,000 / day | ~210 / hour if even; **~600–800 / hour** in an 8-hour field window |
| Audio (webm/mp3, ~5–8 min) | **~8 MB** average | **~40 GB / day** · **~1.2 TB / month** · **~3.6 TB** for 90 days hot |
| Audio if WAV | ~25–40 MB | Do **not** use WAV in production; 3–5× storage |
| Transcripts / STT JSON | **~150 KB** | **~0.75 GB / day** · **~23 GB / month** |
| DB rows | ~1 job + ~5 feedbacks / call | ~30,000 rows / day; text is small vs audio |

GCS is object storage (no pre-buy cap). Disk numbers below are **initial provision + lifecycle**, not a hard stop.

| Field | Value |
|-------|--------|
| **Application Name** | Pidilite User Feedback (Voice Conversations / Field Call Feedback) |
| **Application Owners Name** | Pidilite business owner — *to be named by Pidilite.* Implementation / support: Bootlabs |
| **Service Criticality** | **Medium** — internal reporting (listen to field calls, tagged feedback). Not order booking, manufacturing, or payments. |
| **DR Criticality** | **Medium** — RPO 24 hours (daily backup). RTO same region, next business day. No second-region DR in this rollout. |

---

## 1) Hosting

**a. GCP**

Region: **`asia-south1`**. Azure and AWS are not used. Microsoft Entra ID is used only for website login.

---

## 2) How many environments are required?

**a. Production**

UAT already exists and stays as-is. This ticket asks for **Production only**.

**c. HA (High Availability) — Production**

| Component | Production |
|-----------|------------|
| Cloud Run (web, API, pipeline) | Regional `asia-south1`. Min instances: frontend **1**, dashboard **2**, pipeline **2**. Pipeline max instances **30** (5,000 calls/day, field-hour burst). |
| Cloud SQL | **Regional HA** (automatic failover in `asia-south1`) |
| Cloud Storage | Regional `asia-south1` + object versioning |
| Multi-region / DR site | Not required |

---

## 3) How many servers are required?

**Production only. Zero IaaS VMs.**

| Unit (treat as “server” for this form) | Count | GCP resource |
|----------------------------------------|-------|--------------|
| Website | 1 | Cloud Run `pidilite-frontend` (container port 3000) |
| Reports / dashboard API | 1 | Cloud Run `pidilite-dashboard` (container port 8000) |
| Pipeline (ingest, STT, translate, insights) | 1 | Cloud Run `pidilite-pipeline-svc` (container port 8001) |
| Schema / load job | 1 (on demand) | Cloud Run Job `pidilite-pipeline-migrate` |
| Database | 1 | Cloud SQL PostgreSQL 15, **private IP**, **regional HA**, **4 vCPU / 16 GB / 250 GB SSD** |
| VPC connector | 1 | Serverless VPC Access, min **4** / max **10** instances (Cloud SQL traffic at 5,000 calls/day) |

Also required (not servers): Artifact Registry, Secret Manager `PROD_*`, Cloud Tasks queues, Cloud Scheduler, Eventarc on GCS, two **prod** GCS buckets (raw audio + transcripts). **Do not reuse UAT buckets, SQL, or secrets.**

---

## 4) Configuration of servers (UAT)

**Not requested.** UAT is already running. Skip 4.1–4.4. Do not size or build UAT on this ticket.

---

## 5) Configuration of servers (Production)

Cloud Run has no guest OS disk. Sizing is **container CPU/memory** and **Cloud SQL** disks. **Every Cloud Run service is at least 2 GB RAM.**

### 5 — Website — Cloud Run `pidilite-frontend`

| # | Item | Answer |
|---|------|--------|
| 5.1 | Operating System | **b. Linux** — container (`node`, Debian slim). **Not** Windows 2022, **not** RHEL/SUSE to patch. |
| 5.2 | # of CPU Cores | **1** vCPU |
| 5.3 | Size of Memory | **2 GB** (minimum for all Cloud Run services) |
| 5.4.1 | OS disk size | **N/A** (ephemeral container) |
| 5.4.2 | OS disk type | **a. SSD** |
| 5.4.3 | Application disk | **N/A** on the service. Audio is in GCS (see 8.2). |
| 5.4.4 | Application disk type | **a. SSD** |
| Min instances | | **1** |

### 5 — Dashboard API — Cloud Run `pidilite-dashboard`

| # | Item | Answer |
|---|------|--------|
| 5.1 | OS | **b. Linux** — `python:3.11-slim` |
| 5.2 | CPU | **2** vCPU |
| 5.3 | Memory | **2 GB** |
| 5.4.1 | OS disk size | **N/A** |
| 5.4.2 | OS disk type | **a. SSD** |
| 5.4.3 | Application disk | **N/A** |
| 5.4.4 | Application disk type | **a. SSD** |
| Min / max instances | | **2** / **10** (reports over ~5,000 new rows/day) |

### 5 — Pipeline — Cloud Run `pidilite-pipeline-svc`

| # | Item | Answer |
|---|------|--------|
| 5.1 | OS | **b. Linux** — `python:3.11-slim` |
| 5.2 | CPU | **2** vCPU |
| 5.3 | Memory | **4 GB** |
| 5.4.1 | OS disk size | **N/A** |
| 5.4.2 | OS disk type | **a. SSD** |
| 5.4.3 | Application disk | **N/A** (audio/transcripts on GCS) |
| 5.4.4 | Application disk type | **a. SSD** |
| Timeout | | **900** seconds |
| Min / max instances | | **2** / **30** (burst ~600–800 calls/hour) |
| Concurrency per instance | | **4** (STT / Gemini workers) |

### 5 — Database — Cloud SQL (Production)

| # | Item | Answer |
|---|------|--------|
| 5.1 | OS | Managed Linux (no OS login). Engine **PostgreSQL 15** |
| 5.2 | CPU | **4** vCPU (`db-custom-4-16384` or equivalent) |
| 5.3 | Memory | **16 GB** |
| 5.4.1 | OS / data disk | **250 GB** (enable storage auto-increase) |
| 5.4.2 | Disk type | **a. SSD** (Cloud SQL pd-ssd) |
| 5.4.3 | Application disk | Same **250 GB** (no second volume) |
| 5.4.4 | Application disk type | **a. SSD** |
| HA | | **Regional HA** (`asia-south1`) |
| Network | | **Private IP only.** No public IP. Automated backups + PITR (7 days). |

---

## 6) Additional software packages (Production)

Nothing is installed on a guest VM. Images are built in CI and deployed to Cloud Run.

### 6.1) Web server

**d. Other** — **Cloud Run.**

- Website: **Next.js** (Node) on port **3000**
- Dashboard API: **Uvicorn / FastAPI** on port **8000**
- Pipeline: **Uvicorn / FastAPI** on port **8001**

Not IIS, Apache, or Tomcat.

### 6.2) Middleware

**d. Other**

- **Python 3.11** (Poetry) — dashboard API + pipeline
- **Node.js 20+** — website
- **Microsoft Entra ID (Azure AD)** — website login only

Not .NET, not Java, not Visual Studio Code on the server.

### 6.3) Database

**b. Postgres** — **Cloud SQL PostgreSQL 15** (new **Production** instance)

Not SQL Server, not Cosmos.

Other GCP: Secret Manager, Cloud Tasks, Cloud Scheduler, Eventarc, Speech-to-Text, Vertex AI (Gemini), Artifact Registry.

---

## 7) Access details (Production)

### 7.1) Application developers / support (Bootlabs + Pidilite IT)

No SSH/RDP host. **GCP IAM is sufficient for Production access** — no PAM. Support uses GCP Console / `gcloud` with the roles in [prod-gcp-access.md](prod-gcp-access.md). Business users use the HTTPS website (Entra ID).

| # | Item | Answer |
|---|------|--------|
| 7.1.1 | Access methodology | **b. Direct Access** via **GCP IAM** (least privilege). **PAM is not required.** No SSH/RDP to compute. |
| 7.1.2 | Login IDs | GCP identities for Bootlabs DevOps + named Pidilite GCP admins — *Pidilite IAM to attach the list.* Runtime: `cloud-run-api@PROJECT_ID`. CI: `github-actions-sa@PROJECT_ID`. |
| 7.1.3 | OS-specific access | **Neither.** No RDP, no SSH to Cloud Run. Cloud SQL: Studio / IAM DB auth / private path only. |
| 7.1.4 | Source public IPs | Pidilite corporate / VPN egress — *network team to list.* Bootlabs office / VPN egress — *Bootlabs to list.* Production Cloud SQL has **no public IP**. |
| 7.1.5 | FQDN / URL | **Prod website:** `https://<prod-frontend-fqdn>` **Prod API:** `https://<prod-dashboard-fqdn>` **Prod pipeline (internal only):** `https://<prod-pipeline-fqdn>` FQDNs to be assigned by Pidilite. Until then: Cloud Run `*.asia-south1.run.app`. |
| 7.1.6 | Ports | **Inbound 443/TCP** to Cloud Run (frontend + dashboard). Pipeline: **443** only from Eventarc, Cloud Tasks, Cloud Scheduler (OIDC). **5432/TCP** Cloud SQL: source = **prod** VPC connector CIDR only. Container ports 3000 / 8000 / 8001 are not on the VPC. |

### 7.2) Application business users (Production)

Business users **do not get server or OS access.** Browser + Entra ID only.

| # | Item | Answer |
|---|------|--------|
| 7.2.1 | Access methodology | **b. Direct Access** to the **Production HTTPS website** (Entra ID). Not PAM. Not GCP IAM (no server login). |
| 7.2.2 | Login IDs | Pidilite Entra ID users granted the Production app. No server login IDs. |
| 7.2.3 | OS-specific access | **Not applicable** |
| 7.2.4 | Source public IPs | India field / office internet and Pidilite WAN. Optional IAP/allow-list is Pidilite’s choice. |
| 7.2.5 | FQDN / URL | `https://<prod-frontend-fqdn>` |
| 7.2.6 | Ports | **443/TCP** to frontend (and frontend → dashboard 443). **No 5432, no SSH, no RDP.** |

---

## 8) Integration of new Production infra with existing (UAT) infra

### 8.1) Connectivity — existing (UAT / M-Power) → new Production

| # | Item | Answer |
|---|------|--------|
| 8.1.1 | Existing server source IP | **UAT** Cloud Run / VPC (`pidilite-user-feedback-ai`) — *GCP admin to confirm connector CIDR.* **M-Power:** Pidilite-owned GCS writer. **Entra ID:** Microsoft login (public HTTPS). |
| 8.1.2 | Existing server source hostname | Current UAT Cloud Run `*.asia-south1.run.app`; M-Power upload; `login.microsoftonline.com`; `storage.googleapis.com` |
| 8.1.3 | Existing server source port | **443** (HTTPS / GCS). M-Power does **not** call Cloud Run; it writes a GCS object. UAT must **not** write to prod SQL. |
| 8.1.4 | New server destination IP | Cloud Run: Google anycast. Cloud SQL: **new Production private IP** (assigned at create). |
| 8.1.5 | New server destination hostname | `https://<prod-frontend-fqdn>` `https://<prod-dashboard-fqdn>` `gs://<prod-raw-audio>` `gs://<prod-processed-text>` Production Cloud SQL private hostname |
| 8.1.6 | New server destination port | **443** (web/API). **5432** (prod Cloud SQL, private only). GCS **443**. |
| 8.1.7 | Login ID | M-Power: GCS `objectCreator` on **prod input bucket only**. App: `cloud-run-api@` (prod). Users: Entra ID. |
| 8.1.8 | Level of access | M-Power: **write objects** to prod input bucket. `cloud-run-api@`: prod app + prod DB read/write. Business users: **HTTPS prod app only**. Reporting DB user (if used): **SELECT** on views only. UAT identities must **not** have write on prod SQL or prod buckets. |

Eventarc on the **prod** input bucket starts the pipeline (`POST /api/v1/file`). No VPN from M-Power into Cloud SQL. UAT and Production stay isolated.

### 8.2) Connectivity — storage (Production)

| # | Item | Answer |
|---|------|--------|
| 8.2.1 | Existing storage | UAT already has GCS (`pidilite-raw-audio`, `pidilite-processed-text`) and Cloud SQL `user-feedback-db`. **New prod buckets and a new prod SQL instance** — do not share UAT storage. No SAN/NAS. |
| 8.2.2 | Storage size (Production) | **Audio:** provision **4 TB** (covers ~90 days at 8 MB × 5,000/day). **Transcripts:** **200 GB**. **Cloud SQL:** **250 GB SSD** (auto-increase). GCS has no fixed cap — these are the Day-1 quotas / alerts. |
| 8.2.3 | Anticipated growth | **5,000 calls/day × ~8 MB = ~40 GB audio/day (~1.2 TB/month).** After **90 days** move audio to Nearline (or Coldline after 365 days) so hot storage stays ~3.6 TB. Transcripts **~23 GB/month**. DB **~5–15 GB/month** (text + JSON); 250 GB covers **12+ months** before a disk bump. Alert at 70% on buckets and SQL. |

### 8.3) Backup and restoration (Production)

| # | Item | Answer |
|---|------|--------|
| 8.3.1 | Backup | **a. Default policy on Cloud: Daily with retention for 7 days** on Production Cloud SQL. **Also:** PITR **7 days**. GCS: **object versioning** on both prod buckets. Cloud Run: rollback = previous Artifact Registry image tag. |
| 8.3.2 | Restoration | **a. Ad-hoc as per request from stakeholders.** App rollback: previous image. DB rollback: Cloud SQL backup / PITR. |
