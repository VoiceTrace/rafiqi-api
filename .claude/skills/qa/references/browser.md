# Driving this app in a browser

Read before Phase 4. Playwright is a devDependency of `rafiki-frontend`; no separate
install is needed.

## Find the route before you navigate

Routes do not always map to the URL you would guess, and a wrong guess looks like a
broken feature. `/student/homework/{id}` is **not** the student homework page — it is
a `redirect()` into `/student/study-cave?phase=homework&homeworkId=...`. Navigating to
the first URL and finding nothing means the route moved, not that the feature broke.

Confirm the real path before writing selectors:

```bash
# App Router pages live at page.tsx; this lists the real routes.
find rafiki-frontend/src/app -name "page.tsx" | sed 's|.*/app/||; s|/page.tsx||'
# Then check whether it actually renders or just redirects:
grep -n "redirect(" rafiki-frontend/src/app/<path>/page.tsx
```

Following the redirect once in the browser and printing `page.url()` is the fastest
way to learn the destination, including its query string.

## Never hardcode a user-visible string

All UI text comes from `messages/en.json` and `messages/ar.json`, so any label you
write into a selector is a copy that can drift — and if it drifts, your check silently
stops matching and reports a false PASS.

Look the label up instead of guessing it:

```bash
grep -n "revealHint\|submit\|hints" rafiki-frontend/messages/en.json
```

Prefer structural selectors (roles, `name` attributes, `data-slot`) and use text only
when you have just read the current string. When text is unavoidable, assert the
element count changes rather than trusting a regex to match forever.

## Running a script

Put the script in your scratchpad, not in the repo — it is QA scaffolding, not
product code. Node then cannot resolve `playwright` from there, so point it at the
frontend's modules:

```bash
cd D:/work/ENTRAI/Rafiqi/rafiki-frontend
NODE_PATH="D:/work/ENTRAI/Rafiqi/rafiki-frontend/node_modules" \
  node "<scratchpad>/qa-<ticket>.js"
```

Structure the script so every check prints `PASS`/`FAIL` with a short reason, and exit
non-zero if anything failed. You will run it many times while diagnosing; readable
output is worth the few extra lines.

```js
const fail = [];
function check(name, ok, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
  if (!ok) fail.push(name);
}
```

## Set up state through the API, assert through the UI

Use the API for everything that is not the thing under test — creating an assignment,
distributing it, making a user. Use the browser for the behaviour you are actually
verifying. This keeps scripts fast and stops a setup-step selector change from
breaking a test about something else.

The exception: if the ticket changed a **form**, drive that form in the browser. That
is precisely where API-level testing misses defects (see "required fields" below).

## Logging in

Take the base URL from the port you actually chose — do not hardcode 3000, which this
document already warns is usually taken:

```js
const BASE = `http://localhost:${process.env.FE_PORT ?? 3000}`;

async function login(page, { email, password }) {
  await page.goto(`${BASE}/en/login`);
  await page.waitForLoadState('networkidle');
  await page.fill('input[name="email"]', email);
  await page.fill('input[name="password"]', password);
  await page.click('button[type="submit"]');
  await page.waitForFunction(() => !location.pathname.includes('/login'), { timeout: 15000 })
    .catch(() => {});
  await page.waitForLoadState('networkidle');
}
```

Notes:

- The login form has a Student/Teacher toggle, but the backend does not check it —
  the JWT role decides where you land. Do not waste time clicking it.
- Give each role its own `browser.newContext()`. Sharing a context leaks the session
  and you end up testing the wrong user.
- After login, wait for real content (`nav`, `aside`) before screenshotting.
  `networkidle` alone fires too early and you get a blank page — a whole set of
  screenshots was once captured as empty white frames this way.

## Traps that produce false failures

### Required fields you did not fill

The teacher question form renders **four** option rows by default and every one is
`required`. A script that fills two and submits gets a native "Please fill out this
field" tooltip, nothing is sent, and it looks like the save is broken.

Enumerate and fill what is actually on screen rather than assuming a count:

```js
const inputs = page.locator('input[name^="option_text_"]');
const n = await inputs.count();
for (let i = 0; i < n; i++) await inputs.nth(i).fill(labels[i] ?? `Option ${i}`);
```

When a submit does nothing, screenshot **before** debugging the backend. The browser's
own validation tooltip is usually visible in the image and explains it instantly.

### Collapsed content

Hints live inside `<details>`. Content inside a closed `<details>` is in the DOM but
not visible. Open it before asserting, and re-open it after a reload — it collapses
again.

### Disabled buttons and React state

Buttons gated on state (`disabled={!allAnswered}`) are not immediately enabled after
programmatic clicks. Prefer waiting for the real condition:

```js
await submit.waitFor({ state: 'enabled', timeout: 5000 });
```

Avoid `click({ force: true })` on a disabled button. It does not fire React's handler,
so the click silently does nothing and you conclude the feature is broken.

### MCQ options are buttons, not radios

In the student view, options render as `button[type="button"]`. Looking for
`input[type="radio"]` finds nothing and reports zero questions.

## Always check after a reload

Anything the user spent an action on, or that must survive a revisit, gets asserted
twice: once after the action, once after `page.reload()`.

This is a real defect class here. Revealed hints were held only in React state, so a
refresh silently discarded hints the student had already spent a reveal on — and the
reveal counter reset far enough that the UI offered a reveal the API answers with 409.
The API was correct; the persistence was not.

```js
check('hint visible after reveal', (await page.getByText(hint).count()) > 0);
await page.reload();
await page.waitForLoadState('networkidle');
await page.locator('details').first().click().catch(() => {});
check('hint STILL visible after reload', (await page.getByText(hint).count()) > 0);
```

## Scope every assertion to the right card

A page-wide locator silently answers about the wrong element. With several question
cards on screen, `page.locator('button')` finds buttons belonging to a different
question, producing confident PASS and FAIL results that mean nothing.

Anchor to the card first, then query inside it. Question cards render as `<details>`
blocks in document order, which makes them stable to index:

```js
const card = page.locator('details').nth(i);     // the i-th question
const revealBtn = card.locator('button');        // scoped — cannot match a neighbour
```

When a locator gives a surprising result, print what it actually matched before
believing it:

```js
console.log(await page.locator('button').allInnerTexts());
```

That one line resolves most false results immediately, and it tells you the current
label without grepping.

## The UI must not offer what the API rejects

When a limit exists, verify both halves. A question authored with one hint must show
no reveal button once that hint is used — even though the API would correctly return
409 if pressed. Offering an action that always errors is a defect on its own.

Read the current label from `messages/en.json` first (at the time of writing the
reveal button renders `mcq.revealHint` → "Show hint {number}"), then scope to the card:

```js
const card = page.locator('details').nth(i);
check('no further reveal offered', (await card.locator('button').count()) === 0);
```

## Arabic and RTL

Any layout change needs a pass at `/ar/...`. The app mirrors for RTL, and icons that
need flipping use `rtl:-scale-x-100`. Screenshot both locales when the ticket touched
layout.

Authored content follows the requested locale, but historical messages keep the
language they were written in — do not report that as a bug.

## Screenshots

Capture every checkpoint, and always on failure.

```js
await page.screenshot({ path: `${OUT}/QA-<id>-<what>.png`, fullPage: true });
```

Write them to your scratchpad and keep them — they are the evidence your Phase 7
report cites by path. **Never** write them to `rafiki-frontend/design/boards/`; that
directory is approved design reference and QA output does not belong there. Phase 6's
cleanup rule is about anything that landed in a repo, not your scratchpad.
