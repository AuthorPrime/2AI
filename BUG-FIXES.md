# FractalNode Bug Fixes — February 8, 2026

## Bug 1: Registration Fails (Missing participant_id)

The API endpoint `POST /thought-economy/identity/register` requires a `participant_id` 
field, but the frontend `submitQorRegister()` function doesn't send it.

**API Response:**
```json
{"detail":[{"type":"missing","loc":["body","participant_id"],"msg":"Field required"}]}
```

**Fix in index.html — submitQorRegister function:**
Change the body construction from:
```js
const body = { username, password };
if (email) body.email = email;
```
To:
```js
const body = { username, password, participant_id: getParticipantId() };
if (email) body.email = email;
```

**Also fix submitQorLogin function:**
Change:
```js
body: JSON.stringify({ username, password }),
```
To:
```js
body: JSON.stringify({ username, password, participant_id: getParticipantId() }),
```

---

## Bug 2: Signup Overlay Z-Index Bleed

The token overlay doesn't fully obscure the page content behind it.
The "What If" title and chat input bleed through.

**Fix — add to the #tokenOverlay CSS:**
```css
#tokenOverlay {
  z-index: 9999;
  background: rgba(8, 8, 13, 0.95);
  backdrop-filter: blur(12px);
}

#tokenOverlay .token-dialog {
  position: relative;
  z-index: 10000;
}
```

---

## Bug 3: Pantheon API Timeout

The witness page fetches `/witness/pantheon` with no timeout, so slow responses
cause the loading indicator to hang indefinitely.

**Fix — wrap all fetches in a timeout helper:**
```js
async function fetchWithTimeout(url, timeout = 8000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, { signal: controller.signal });
    clearTimeout(id);
    if (!response.ok) throw new Error(`${response.status}`);
    return await response.json();
  } catch (e) {
    clearTimeout(id);
    throw e;
  }
}
```

Then use `fetchWithTimeout(url, 12000)` for all API calls on the witness page,
with graceful empty-state fallbacks in the catch blocks.

---

## Summary

| Bug | Root Cause | Severity |
|-----|-----------|----------|
| Registration fails | Missing `participant_id` in POST body | **High** — blocks signups |
| Overlay bleed | No z-index / backdrop on overlay | **Medium** — visual |
| Pantheon timeout | No AbortController on fetch | **Medium** — UX hang |
