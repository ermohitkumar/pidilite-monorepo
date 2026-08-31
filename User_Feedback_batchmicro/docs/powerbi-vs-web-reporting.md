# Power BI vs Web Reporting

This note compares two ways people can look at feedback from field call recordings:

- **Web reporting** — the Pidilite User Feedback website (Reports, Monitor, Files).
- **Power BI** — Microsoft’s dashboard tool, used widely in the company for charts and Excel-style reports.

Both can show the same numbers (tag counts, products, summaries). They are not equal for listening to calls, checking failed files, or keeping data private.


---

## How the system works

1. A field person records a conversation and uploads it.
2. The system turns speech into English text and tags it (product, user, dealer).
3. Results are stored in a company database that is **not on the public internet**.
4. People then read those results — either on the website or, if we connect it, in Power BI.

---

## Side by side

| | Website | Power BI |
|--|---------|----------|
| What it is | Our own screens, already live | A separate Microsoft report |
| Tag counts and filters | Yes | Yes |
| Read the AI summary and full talk | Easy (chat-style, one call at a time) | Possible, but long text is hard to read |
| **Play the original recording** | Yes — play, pause, skip | No practical way without weakening security |
| See if files failed / retry work | Yes (Monitor and Files) | Not  right tool |
| Data as soon as a file finishes | Immediate | Usually delayed until a refresh |
| Managing masters | Easy | Not right tool|
| Extra setup cost | Already running | New licences + a secure link to our database |


## Audio

A count of tags is not enough. People need to **hear the call** to check that the AI got it right.

**Website today:** Play from the report. Seek, skip 10 seconds, keyboard shortcuts. Login required. Recordings stay in private storage.

**Power BI:** Can show a file name. It cannot play a private recording the way a website can. To play from Power BI we have to:

- put recordings on a public (or easy-to-share) link — **not acceptable**, or
- download files to laptops — **bad for privacy**, or
- build a complicated extra player — still a poor experience inside a chart.

**Later audio ideas** (speed up playback, click a line of text to jump in the audio, mute private parts) only work on a website we control. They will not work well in Power BI.



---

## Monitoring

Monitoring means: *did today’s uploads finish? which files failed? can I open that file and listen?*

The website already has this. Power BI can show a percentage after the fact. It cannot open a failed file, show the error, and play the audio. **Keep operations on the website.** Cloud alerts (service down, queue stuck) belong in Google Cloud monitoring, not in either report.

---

## Infrastructure and challenges

This is the main reason Power BI is not a drop-in replacement.

**The database is private on purpose.** The website already talks to it through our secure cloud setup. Power BI (Microsoft’s cloud) **does not** have a path to that database today.

To use Power BI in production we would need extra machinery, for example a always-on machine that sits in our private network and forwards data. That means:

- more servers to run and patch
- extra Microsoft licences
- a copy of conversations may sit in Microsoft’s cloud (if the report “imports” the data)
- India field talks may leave India, depending on where Power BI stores the file
- passwords must not be saved inside the report file

Opening the database to the internet so Power BI can connect is **not** an option.





