# Estimation: site visit filters from Azure warehouse

**2.5 weeks** · **160 h** Bootlabs ·  · 2 people  

160 h ÷ 2 people ÷ 40 h/week = **2 weeks**

| Area | Hours | Activities | Timeline |
|------|------:|------------|----------|
| **Backend** | 52 | • Save site visit on upload<br>• Batch start: look up Azure warehouse, attach Division / Zone / RFMM cluster / FME Code / User Type<br>• Retry if lookup fails; file still processes<br>• Daily copy of filter lists (changes only)<br>• Reports use those saved filters; unknown visit still visible | Week 1–2 |
| **Frontend / Power BI** | 52 | **Website (16 h)**<br>• Bind drop-downs to daily lists + saved filters<br>• Show unknown visit on the call<br>• Check: filter by Division, audio still plays<br><br>**Power BI (36 h, Bootlabs builds)**<br>• Connect to company database (private)<br>• Tag matrices, product drill, summary / excerpt<br>• Slicers for the same filters<br>• Refresh after batches<br>• No full conversation or audio in Power BI | Week 2–2.5 |
| **DevOps** | 28 | • Warehouse login (batch + daily list copy)<br>• Network: Google Cloud → Azure; Power BI → company database (private)<br>• Schedule daily list copy<br>• Alerts: unmatched visits, overdue copy, slow lookup<br>• Align Power BI refresh with batch | Week 1 (Power BI network into week 2) |
| **Testing** | 20 | • Upload with site visit; ignore dummy filters<br>• Batch lookup: match / not found / warehouse down<br>• Website filters and unknown visit<br>• Power BI slicers and refresh after a batch<br>• Daily list copy (new / changed only) | Week 2–2.5 |
| **Documentation** | 8 | • How filters work (site visit → warehouse → reports)<br>• Ops: logins, daily copy, alerts, unknown visit<br>• Power BI refresh and Pidilite sign-off | Week 2.5 |
| **Total** | **160** | | **2.5 weeks** |

| Week | What happens |
|------|----------------|
| **1** | DevOps (logins, network) + backend (upload, batch lookup, daily lists) |
| **2** | Backend reports + website filters + Power BI + lookup tests |
| **2.5** (3 days) | Finish Power BI, remaining tests, documentation, sign-off |
