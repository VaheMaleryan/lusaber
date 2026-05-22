/**
 * Lusaber · Լուսաբեր — friendly-error mapper.
 *
 * Single source of truth for "API response → message a human can read".
 * Never shows raw JSON, never echoes Pydantic field paths, never prints
 * an HTTP status code as the headline.
 *
 * The mapper is conservative: when an error doesn't match a known
 * shape it returns a generic, blame-neutral fallback rather than
 * leaking the response body.
 */

/**
 * Try to extract a useful body from a fetch Response. Returns either
 * the parsed JSON object or `null`. Never throws.
 */
export async function safeReadBody(resp) {
  try {
    const ct = resp.headers.get("content-type") || "";
    if (ct.includes("application/json")) return await resp.json();
    const text = await resp.text();
    try {
      return JSON.parse(text);
    } catch {
      return text ? { detail: text } : null;
    }
  } catch {
    return null;
  }
}

/**
 * Given an HTTP status and an optional parsed body, return one
 * human-friendly sentence telling the user what happened and (where
 * possible) what to do about it. No JSON, no field paths, no HTTP
 * numbers in the output.
 */
export function friendlyError(status, body) {
  // ----- 422 — Pydantic / FastAPI validation -----
  if (status === 422) {
    // Pydantic's `detail` is normally an array of error objects.
    const errors = Array.isArray(body?.detail) ? body.detail : [];
    if (errors.length > 0) {
      const first = errors[0] || {};
      const type = String(first.type || "");
      const msg = String(first.msg || "");
      const loc = Array.isArray(first.loc) ? first.loc : [];
      const field = loc[loc.length - 1] || "";

      if (
        type === "string_too_short" ||
        /at least \d+ character/i.test(msg)
      ) {
        return "Please paste a longer article — at least a few sentences.";
      }
      if (
        type === "string_too_long" ||
        /at most \d+ character/i.test(msg)
      ) {
        return "That article is too long. Please trim it down before summarizing.";
      }
      if (
        type === "url_parsing" ||
        type === "url_type" ||
        /valid url/i.test(msg)
      ) {
        return "Please enter a valid URL starting with https://";
      }
      if (type === "missing") {
        if (field === "text") {
          return "Please paste an article before summarizing.";
        }
        if (field === "url") {
          return "Please enter a URL to check.";
        }
        return "Something required is missing — please fill in the form.";
      }
      if (
        type === "extra_forbidden" ||
        /extra inputs/i.test(msg)
      ) {
        return "The form sent an unexpected field. Please refresh the page and try again.";
      }
      // Fallback for other validation cases — repeat the model's
      // sentence but lowercased / un-prefixed so it doesn't read like
      // a Python traceback.
      if (msg) return msg.charAt(0).toUpperCase() + msg.slice(1) + ".";
    }
    // Detail-as-string case (we sometimes return a single explanatory
    // sentence directly).
    if (typeof body?.detail === "string") return body.detail;
    return "The request was rejected — please check the form and try again.";
  }

  // ----- 429 — rate limit -----
  if (status === 429) {
    return "Too many requests in a row. Please wait a moment, then try again.";
  }

  // ----- 502 — upstream model returned unparseable output -----
  if (status === 502) {
    return "Lusaber couldn't read the AI's reply. We'll try again automatically.";
  }

  // ----- 503 — service unavailable (GROQ_API_KEY missing, etc.) -----
  if (status === 503) {
    return "The AI service is briefly unavailable. Retrying automatically.";
  }

  // ----- 5xx generic -----
  if (status >= 500) {
    return "The server is having trouble right now. We'll retry shortly.";
  }

  // ----- 4xx other -----
  if (status >= 400) {
    return "Something about the request didn't work. Please check the form and try again.";
  }

  // Catch-all — should never fire (callers gate on !resp.ok).
  return "Something didn't work. Please try again.";
}
