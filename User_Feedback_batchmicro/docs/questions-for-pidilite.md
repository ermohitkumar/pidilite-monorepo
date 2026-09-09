# Questions for Pidilite

Items Bootlabs cannot close. Answers needed to finish Production infra and the filter-master work.

---

## A. Ownership and sign-off (infra form header)

1. Who is the **Application Owner** (name, email, department)?
2. Confirm **Service Criticality = Medium** and **DR Criticality = Medium** (RPO 24h, same-region RTO). If different, state the official ratings.
3. Who **approves Production go-live** (name)? Who **approves the first Production master-data load** (name)?

---

## B. Production GCP project and network

4. Is Production a **new GCP project** or the same project as UAT (`pidilite-user-feedback-ai`) with separate SQL/buckets?
5. Confirm region **`asia-south1`** for Production.
6. What are the **Production FQDNs** (or confirm Cloud Run `*.run.app` until DNS exists)?
   - Website  
   - Dashboard API  
   - Pipeline (internal only)
7. What is the **UAT VPC connector CIDR** (for the integration form)?
8. Should Production sit on a **new VPC** or the existing UAT VPC (isolated SQL/buckets either way)?
9. Is **IAP / IP allow-list** required on the Production website, or is **Entra ID only** enough?

---

## C. People, IAM, Entra ID

10. List **Pidilite GCP admin** Google identities (or group) who will grant Production IAM.
11. List **Pidilite ops** identities who need **read-only** Production (`roles/run.viewer`, `roles/cloudsql.viewer`).
12. Confirm **GCP IAM is sufficient** (no PAM) — already proposed; need written OK.
13. Which **Entra ID tenant / app registration** is Production (same as UAT or new)? Who supplies `AZURE_AD_CLIENT_ID`, secret, tenant ID?
14. Which **Entra ID users/groups** get Production website access (and which app roles: admin vs viewer)?

---

## D. M-Power / upload path

15. Which **service account** (or identity) will **write audio to the Production input bucket**? (Needs `roles/storage.objectCreator` only.)
16. Will Production uploads send a **site visit id** (and/or FME + territory) on the GCS object, or only dummy Division/Zone?
17. Confirm Production audio format is **webm/mp3/ogg** (not WAV). WAV at 5,000 calls/day is 3–5× storage.

---

## E. Filter and product master (data)

18. Sign the **filter mapping** (or correct it):
    - Division ← hierarchy / `SiteDivision`
    - Zone ← site / member
    - User Type ← `CMDITSITag` (IMR/BDE) or `EndUserType`?
    - RFMM Cluster ← `Clustercode` / `ClusterDescription`
    - FME ← `SH2Code`
    - Product ← `ProductGroup3Description` (brand) vs SKU pack?
19. Confirm **join keys**: site (`UniqueReferenceNumber` / `SiteId` / `siteNumber`), member (`MemberId`), hierarchy (`WSSTerritoryCode` + `DivisionCode` + `SH2Code`).
20. Who owns the **warehouse extract**, and **when** is the full file available (not only `Sample Data.xlsx`)?
21. If a visit’s Zone later changes in the warehouse: **keep the value stored at processing time** (default) or update old calls?

---

## F. Volume, storage, backup

22. Confirm **5,000 calls/day** is the Production peak we should size for (every day vs peak days only).
23. Confirm **Nearline after 90 days** (and optional Coldline after 365 days) for Production audio. If audio must stay hot longer, say how many days.
24. Confirm Cloud SQL backup: **daily, 7-day retention + 7-day PITR**, restore **ad-hoc on request**.

---

## G. Reporting (optional this sprint)

25. Is **Power BI on Production** in scope now, or website only? If now: workspace, licences, and who owns the private path to Cloud SQL.
26. Is a **read-only Postgres reporting login** required (SELECT on views only), separate from the app user?

---

## H. UAT testers (filter work, Week 2)

27. Who will execute UAT on filters (names) and from **when** (from 8 Sep 2026)?
28. Who attends the **UAT sign-off** meeting (11 Sep 2026)?
