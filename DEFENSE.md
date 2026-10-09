Good start. Two answers are right, two are half right, and two need fixing. Here's each one:

---

**1. `time.monotonic()`: mostly right ✅, one wrong bit**

> "It remembers it start time to avoid using cpu time"

That part is wrong. `monotonic()` doesn't remember anything, and it has nothing to do with CPU time (that's a different function, `time.process_time()`). The **code** does the remembering, in `self.last_request_at`. `monotonic()` only gives a number that never goes backwards, and you subtract two readings to get "how long since".

Suggested: *"A stopwatch that only goes forward. We read it before and after and subtract, to know how long since the last request. We don't use the wall clock because it can be changed and jump."*

---

**2. `__call__`: mixed up ❌**

The memory doesn't come from `__call__`. It comes from **the object itself**: `self.last_request_at` lives on the object for as long as the object exists. Running a method doesn't "clean out" the object.

What `__call__` actually does is let you **use the object like a function**: `fetch(url)` instead of something like `fetch.get(url)`. That matters because `run.py` can then be handed either the real `Fetcher` or the test's `FakeFetch`, and it uses both the same way.

Suggested: *"`__call__` lets an object be used like a function: `fetch(url)`. We use an object because it keeps memory (last request time, the connection). `__call__` makes the real fetcher and the fake one interchangeable."*

---

**3. `parser.feed()`: right ✅**

One small addition: the parser collects **every** link. Picking out only the PDF/Excel/CSV links happens afterwards, in `find_file_links`.

---

**4. `file_name_for`: half right ⚠️**

"Clean up" is right, but you're missing the **two reasons** behind it:
- **Safety:** a sneaky name like `../../x` could save a file outside its folder. Cleaning stops that.
- **No overwriting:** if two links give the same name, the second becomes `report_2.pdf`, so the first isn't replaced.

---

**5. Homework: not quite ❌**

Here's the catch: `report.pdf` and `report_2.pdf` are in the **same folder**, with the same source and the same date. That's exactly *why* the `_2` was needed. So the folder can't tell you which web address each came from.

The answer is **`manifest.json`** in `data/raw/<source>/`. It's the notebook that says:
```json
"https://.../2025/06/report.pdf": {"file": "2026-10-09T.../report.pdf", ...}
"https://.../2026/06/report.pdf": {"file": "2026-10-09T.../report_2.pdf", ...}
```
Each web address points to its file.

Open a real one in `data/raw/knbs_cpi/manifest.json` and find one of the `_1.pdf` files, so you can see it for yourself.