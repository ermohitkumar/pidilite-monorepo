# Plan: Site visit → report filters from Azure warehouse

## Current project scope

The agreed product turns **field call recordings** into **tagged feedback** and lets people **read it**.

| In scope today | What it does |
|----------------|--------------|
| Upload | M-Power (or a test upload) puts the audio in the cloud. Dummy Division / Zone / RFMM cluster / FME Code / User Type may travel with the file. |
| Pipeline | Batch the files, speech-to-text, English translation, AI tags (product / user / dealer), short summary. |
| Website | Reports, listen to the call, monitor failed files, users and access. |
| Power BI (this CR also covers Bootlabs building the report) | Same feedback numbers, once a private path to the company database exists. |
| Master lists we already own | Tags, tag descriptions, products — not territory / FME master from Azure. |

**Not in the original scope:** connecting to Pidilite’s **Azure warehouse**, using a **site visit** as the key, or treating warehouse Division / Zone / RFMM / FME / User Type as the real filters.

Work in this document starts only after the **Prerequisites** below. Hours: [estimation](site-visit-dw-estimation.md) (2.5 weeks).

---

## Why this is a change request

Pidilite now wants report filters to come from the **company warehouse**, keyed by **site visit**, not from dummy values on the audio file.

That is new work, not a small tweak:

| Original build | This change |
|----------------|-------------|
| Filters are placeholders sent with the file | Filters are looked up in **Azure** when a **batch starts** |
| No warehouse connection | Secure login and network from Google Cloud to Azure |
| Drop-downs from whatever was on the file | Official filter lists copied **daily** (changes only) |
| No site visit on the recording | M-Power must send a **site visit**; pipeline must store it and look it up |

Speech-to-text and AI tagging stay as they are. The change is **how geography and FME filters are sourced and kept in sync** for reporting.

If this were in the original scope, the upload would already send a site visit, the batch would already call Azure, and reports would not be built on dummy filters.

---

**Target after this CR:** M-Power sends a **site visit** only. The warehouse already knows that visit’s Division, Zone, RFMM cluster, FME Code, and User Type. The pipeline looks that up when processing starts. Website and Power BI use that **same answer**.

---

## Two approaches (same mapping, two screens)

| | Approach 1 — Website | Approach 2 — Power BI |
|--|----------------------|------------------------|
| When the visit is matched to filters | When a **batch of files starts processing** | Same stored match — no second lookup |
| Lists in the dropdowns / slicers | Copied from the warehouse **once a day** (only changes) | Same daily lists, in the same company database |
| What the user filters on | The website | Power BI |

---

## How it will work

1. A field user records a call in **M-Power**. The file is uploaded with a **site visit** only (not dummy Division / Zone / etc.).
2. Files wait until the usual **batch** run (a scheduled group of recordings).
3. When that batch starts, the system **opens a connection to the Azure warehouse** and, for each site visit in the group, fetches Division, Zone, RFMM cluster, FME Code, and User Type.
4. Those values are **saved next to that recording**. Speech-to-text and AI tagging continue as today, even if the warehouse is slow or misses a visit.
5. **Allowed lists** (all Divisions, all Zones, …) are not fetched per file. They are loaded **daily**, and only **what changed**, because they barely move.
6. The **website** and **Power BI** both read those saved values and those daily lists. They do **not** call Azure when someone opens a report.

```
M-Power sends: audio + site visit
                    │
                    ▼
         File waits for the next batch
                    │
                    ▼
    Batch starts → connect to Azure warehouse
                 → attach filters to each recording
                    │
         ┌──────────┴──────────┐
         ▼                     ▼
   Website reports        Power BI
   (same saved filters)
```

If a visit is not in the warehouse yet, the recording still processes. Reports show it as **unknown visit** until a later retry.

---

## Two kinds of warehouse data

**Visit lookup** — one site visit → that visit’s Division, Zone, RFMM cluster, FME Code, User Type.  
Used **when a batch starts**.

**Filter lists** — the official drop-down values (every Division, every Zone, …).  
Used **daily**. Lets empty options still appear in reports even if no call used them yet.

Pidilite owns both in Azure. Bootlabs only **reads** them.

---

## Approach 1 — Website

The product website stays the place to filter, drill, and listen to audio.

- **Drop-downs** come from the **daily** filter lists.
- **Which calls appear** after you pick a Division (etc.) uses the filters **saved when that file’s batch ran**.
- Opening a report does **not** talk to Azure.

**Bootlabs:** save the site visit on upload; look up Azure when the batch starts; retry if the warehouse failed; website drop-downs and filters use the saved data and daily lists.  
**Pidilite:** M-Power sends the site visit; warehouse visit lookup and filter lists are correct and available; agree labels (what “User Type” means).  
**DevOps:** secure warehouse login used only at batch time and for the daily list copy; alert if many visits do not match; keep the company database off the public internet.

---

## Approach 2 — Power BI

Power BI does **not** look up visits in Azure by itself. It uses the **same saved mapping** the batch already wrote. Website and Power BI then show the same Division for the same call.

- Slicers use those saved filters, and the **same daily lists** so unused values can still show.
- Refresh the Power BI report **after batches have run** (or when a batch finishes), so new calls appear only after their visit has been matched.
- Do not load full conversations or audio into Power BI.

**Bootlabs:** same batch mapping as the website; **build the Power BI report** (slicers, pages, publish); prepare data Power BI can read (no extra Azure join); set refresh to follow batch timing.  
**Pidilite:** Power BI workspace / licences; private path from Power BI to the company database; review and sign-off.  
**DevOps:** secure Power BI connection to the company database (not a second live Azure visit lookup). Optional: open a call in the website from a Power BI row to hear the audio.

---

## Why the match happens at batch time (not when you open a report)

| If we did this | Problem |
|----------------|---------|
| Website uses an old copy, Power BI asks Azure live | Same call could show two Divisions |
| Ask Azure on every report click | Slow; report breaks if Azure is down |
| Copy dummy values at upload | Not the real company master |

Batch-time match = **one snapshot** for both screens: “filters as of when this file started processing.”

Daily lists = drop-downs stay complete without hitting Azure all day.

---

## Who does what

| Work | Pidilite | Bootlabs |
|------|----------|----------|
| Meaning of site visit; warehouse data | Owns | Advises |
| M-Power sends site visit with the audio | Owns | Advises |
| Look up the warehouse when a batch starts and save filters | Advises | Owns |
| Daily copy of filter lists (changes only) | Gives access | Owns |
| Website filters and screens | Advises | Owns |
| Power BI report development and refresh vs batch | Advises (workspace, licences, sign-off) | Owns |
| Warehouse access and network rules | Owns | Connects from Google Cloud |
| Company database not on the public internet | Advises | Owns |

---

## Prerequisites (Pidilite, before build)

Build does not start until these are in place.

| # | Prerequisite | Needed so that |
|---|--------------|----------------|
| 1 | Visit lookup and filter lists are published in Azure, with access for Bootlabs (where they live, how to connect). | Batch can look up a site visit; daily list copy can run. |
| 2 | A real M-Power **site visit** example (what the ID looks like, one production sample). | Upload and lookup use the same ID. |
| 3 | Rule if the warehouse later changes a visit’s Zone (or similar): **keep the value from batch time** (default), or update old recordings. | Website and Power BI stay consistent. |
| 4 | M-Power sends the **site visit** with every production upload (no dummy Division / Zone as the source of truth). | There is something to look up. |
| 5 | Network and login: Bootlabs may read the warehouse from Google Cloud; Power BI may read the company database privately. | Connections are allowed and secure. |
| 6 | Power BI workspace and licences so Bootlabs can build and publish the report. | Report development can start. |

---

