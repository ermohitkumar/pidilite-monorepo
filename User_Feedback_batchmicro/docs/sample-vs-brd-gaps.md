# Gaps: Sample Data vs DW BRD structure

**Sample:** [`Sample Data.xlsx`](../Sample%20Data.xlsx) (10 site rows, 10 members, 10 hierarchy rows, 19 materials)  
**BRD:** [`DW_BRD_Feedback_voicebot.xlsx`](../DW_BRD_Feedback_voicebot.xlsx) → landing SQL [`scripts/sql/dw_brd_landing_tables.sql`](../scripts/sql/dw_brd_landing_tables.sql)  
**Report filters needed:** Division, Zone, User Type, RFMM Cluster, FME Code, Product

This is a **data / contract** gap list, not an infra list.

---

## Filter coverage (what the website needs)

| Report filter | BRD column | In BRD? | In sample values? | Gap |
|---------------|------------|---------|-------------------|-----|
| **Division** | `FactSitedetails.SiteDivision`, `DimHierarchy.divisioncode`, `vw_DimMaterial.DivisionCode` / `DivisionDescription`, `Dimmember.DivisionName` | Yes (code). **Name only on material.** | Site/member: code **`10` only**, no name. Material: `10` / **`FV`**. Hierarchy: codes `10,20,30,40,70` | Drop-down would show **`10`**, not “FV / Fevicol”. `Dimmember.DivisionName` is **100% empty**. No division master list in BRD. |
| **Zone** | — | **No** | Sample fact `Zone`: **7/10 NULL** (`ZN00102`, `ZW00101`). Sample member `ZoneCode`: **100% empty**. BRD dropped `Zone` from FactSitedetails | **Cannot populate Zone filter from BRD tables.** Sample Zone is too sparse to be the source of truth. |
| **User Type** | `FactSitedetails.CMDITSITag`; `Dimmember.EndUserType` | Partial | `CMDITSITag` = **IMR / BDE** (all 10). `EndUserType` on fact and member: **100% empty**. BRD dropped fact `EndUserType` | If User Type means **contractor vs dealer**, BRD/sample **do not have it**. If it means **IMR vs BDE**, use `CMDITSITag` — confirm with Pidilite. |
| **RFMM Cluster** | `FactSitedetails.Cluster`; `DimHierarchy.ClusterCode` + `ClusterDescription` | Two different “clusters” | Fact: `CA00500`, `DELHI-C`, `CY00500`… Hierarchy: `AASM028` / `ARAL_ASM_SB_Bangalore`. **Zero overlap** | Fact `Cluster` looks like **BDE/town cluster**. Hierarchy `ClusterCode` looks like **RFMM/ASM**. BRD has both names and **no mapping table**. UI cannot treat them as one RFMM filter. |
| **FME Code** | `DimHierarchy.SH2Code` (+ `SH2Name`) | Yes on hierarchy only | Sample SH2 is mixed: FME, **SFME**, BDE, ASE, KAE — not FME-only. Fact has **no FME column**. `SH2EmpPosition` (needed to know “this is an FME”) is **not in BRD** | Site visit **cannot get FME** from FactSitedetails. Must join hierarchy. Sample cannot tell FME vs SFME without position, which BRD dropped. |
| **Product** | `vw_DimMaterial.ProductGroup3Description` | Yes | 11 brand names (FEVICOL SH, SPEEDX, …). **18/19 FSN = Discontinued**. Hierarchy products are **Feviseal / Roff**, not Fevicol SH | Catalog for voice reports is Fevicol-style; hierarchy sample is a **different product tree**. `PrdGroup4` / `PrdGroup5` **code columns missing** in sample (description-only for group 5). |

---

## Site visit → filter mapping (broken in the sample)

Intended path: **M-Power site visit id → FactSitedetails → Division / Zone / User Type / RFMM / FME**.

| Join | Expected | Sample result |
|------|----------|----------------|
| Upload key → site fact | `UniqueReferenceNumber` (`SD-00546800` …) is the natural visit id | Column **exists in sample**, **not in BRD**. BRD PK is Salesforce `ID` (`a0G5i…`). Pipeline cannot look up `SD-…` unless BRD adds `UniqueReferenceNumber` (and/or `SiteId` / `siteNumber`). |
| Site → member | `FactSitedetails.MemberId` = `Dimmember.MembershipNo` | **0 / 10 match.** Fact ids are `16071409`, `12092181`… Member PKs are `105241213757258`… Different ID spaces. Member side is unused for these visits. |
| Site → hierarchy (FME / RFMM) | `WSSTerritoryCode` + `divisioncode` + `SalesGroup` | Fact **`WSSTerritoryCode` is 100% NULL** (and **not in BRD**). Cannot join `DimHierarchy`. |
| Site cluster → hierarchy cluster | `Fact.Cluster` = `DimHierarchy.ClusterCode` | **No shared values.** `CA00500` ≠ `AASM028`. |
| Site division + sales group → hierarchy | `SiteDivision=10` + `salesgroupcode=105` | Only **one** hierarchy row is `10` + `105` (`TC10501` / `BDESWB3` / Feviseal). That FME is **not** the FME for the 10 WWA Fevicol sites. |

**Bottom line:** with this sample, a site visit can yield **Division code `10`**, **User Type = IMR/BDE** (`CMDITSITag`), and **Fact.Cluster** (not RFMM). It **cannot** yield Zone, FME, or a hierarchy RFMM name.

---

## BRD structure vs sample (columns)

### FactSitedetails — dropped from BRD but present in sample (needed for filters / join)

| Sample column | Why it matters |
|---------------|----------------|
| `UniqueReferenceNumber` | Likely M-Power visit key (`SD-…`) |
| `Zone` | Report Zone filter (sparse even in sample) |
| `EndUserType` | Alternate User Type (empty here) |
| `BDEClusterCode` | Same values as `Cluster` in sample |
| `WSSTerritoryCode` / `WSSTerriName` | Join to `DimHierarchy` (empty here) |
| `IsDeleted` | BRD load filter (“IsDeleted not equal to 1”) but **not a BRD column** — assumed applied in DW before land |

BRD **Sitedetails** sheet is mis-labelled “Source - Dimmember”.

### DimHierarchy

- BRD **PK = `WSSTerritoryCode` only**. Sample comments say the real key is **WSS TTy + Division + Sales Group + Product + L2 (SH2)**. Same territory with two products would **collide** on the BRD PK.
- **2 / 10** hierarchy rows have **NULL ClusterCode** → RFMM list incomplete.
- `ProductName` **empty/NULL on 6 / 10** rows.
- `SH2EmpPosition` not in BRD (sample values look like **cost-center codes**, not “FME”).

### Dimmember

- Prerequisites say PK **MembershipID**; structure/SQL use **MembershipNo**.
- Load filter `Recordtype-WWA`; sample `RecordtypeName` is **`FFF`**, not WWA.
- `DivisionName`, `EndUserType`, `ClusterCode`, `ZoneCode`: **all empty** in sample.
- No join to the 10 site rows (see mapping above).

### vw_DimMaterial

- Sample missing **`PrdGroup4`**, **`ProductGroup4Description`**, **`PrdGroup5`** (only SKU description exists).
- `BaseUOMDescription` and `ProductGroup6Description`: **100% empty**.
- Sample is **Division 10 / FV / SalesGroup 105 only** — not a full product master.
- Almost all SKUs **Discontinued** — poor seed for an active Product drop-down.

---

## Other contract gaps

| Topic | Gap |
|-------|-----|
| Destination | BRD destination is **Azure MySQL Jharokha** (`pidilite_pimcore_*`). Our app is **Postgres Cloud SQL**. Landing SQL is a copy of BRD names, not the DW pipeline. |
| Refresh | Material + Fact **daily**; Hierarchy **twice a week**. Site processed between hierarchy loads can have stale FME/RFMM. |
| Volume of sample | 10 sites / 10 members / 10 hierarchy / 19 materials — not enough to prove joins or filter lists. |
| Hierarchy vs voice products | Sites are WWA Fevicol (`producthierarchycode=11`). Hierarchy sample is mixed divisions (10/20/30/40/70) and **sealants/Roff**. |

---

## What Pidilite must add or confirm

1. **Add to FactSitedetails (BRD):** `UniqueReferenceNumber` (or the exact M-Power visit id), **`Zone`** (or the official zone column), **`WSSTerritoryCode`** (to join FME/RFMM).
2. **Say which cluster is RFMM:** Fact `Cluster` vs Hierarchy `ClusterCode` — they are not the same in the sample.
3. **Say what User Type is:** `CMDITSITag` (IMR/BDE) vs contractor `EndUserType` (empty).
4. **Division label:** ship `DivisionDescription` on the site or a small division master (`10` → `FV`).
5. **How to attach FME to a visit:** join path that works when `WSSTerritoryCode` is blank on the site (today it is).
6. **Member join:** `MemberId` vs `MembershipNo` — which key does M-Power send?
7. **Hierarchy PK:** confirm composite key; BRD single-column PK is unsafe.
8. **Product grain:** `ProductGroup3Description`, active only (`FSN` / `ActiveFlag`), Fevicol set vs full ZFGD.

Until 1–5 are in the **daily Fact + Hierarchy extract**, report filters cannot be filled “from DB itself” for a real site visit.
