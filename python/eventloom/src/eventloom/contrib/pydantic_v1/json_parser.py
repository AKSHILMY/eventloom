"""
Partial JSON parser — repairs incomplete JSON strings produced by token streaming.

Algorithm:
1. Walk the string char-by-char tracking open string/object/array state.
2. If a string is still open at end, close it with a quote.
3. Iteratively strip trailing invalid tokens:
   - trailing commas
   - trailing colons (and their preceding key)
   - partial boolean/null literals (tru, fals, nul, tr, fa, nu, t, f, n)
   - bare quoted keys without a colon/value
4. Recompute open bracket/brace stack and append closing characters.

Known limitations (inherent to parsing a truncated stream, not bugs):
- A number cut off mid-digit (e.g. "count": 4 with more digits still coming)
  can't be distinguished from a complete one — numeric fields may lag behind
  string fields during streaming.
- A trailing bare `-` or partial exponent (e.g. `1e`) isn't stripped by any
  phase-2 rule, so that token's parse attempt is skipped (safe: the caller
  just doesn't get a yield for it) until more digits arrive.
"""

import json
import re
from typing import Optional


def _compute_stack_and_string_state(s: str):
    """
    Walk s and return (stack_of_opens, in_string).
    stack_of_opens contains '{' and '[' in order of opening (plus '"' for strings).
    """
    stack = []
    in_string = False
    escape_next = False
    for ch in s:
        if escape_next:
            escape_next = False
            continue
        if in_string:
            if ch == "\\":
                escape_next = True
            elif ch == '"':
                in_string = False
                if stack and stack[-1] == '"':
                    stack.pop()
        else:
            if ch == '"':
                in_string = True
                stack.append('"')
            elif ch in ('{', '['):
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()
    return stack, in_string


def repair_partial_json(s: str) -> str:
    """
    Repair a partial (streaming) JSON string into valid JSON.
    Returns a best-effort valid JSON string, defaulting to '{}' on empty input.
    """
    s = s.strip()
    if not s:
        return "{}"

    # Phase 1: close an open string
    stack, in_string = _compute_stack_and_string_state(s)
    if in_string:
        s += '"'
        stack, _ = _compute_stack_and_string_state(s)

    # Phase 2: iteratively strip trailing invalid tokens
    changed = True
    while changed:
        changed = False
        s = s.rstrip()

        if s.endswith(','):
            s = s[:-1].rstrip()
            changed = True
            continue

        if s.endswith(':'):
            s = s[:-1].rstrip()
            m = re.search(r'"[^"]*"\s*$', s)
            if m:
                s = s[:m.start()].rstrip()
            changed = True
            continue

        # Partial boolean/null after a colon: strip key + colon + partial literal
        m = re.search(r':\s*(?:tru|fals|nul|tr|fa|nu|t|f|n)\s*$', s)
        if m:
            prefix = s[:m.start()].rstrip()
            key_m = re.search(r'"[^"]*"\s*$', prefix)
            if key_m:
                prefix = prefix[:key_m.start()].rstrip()
            s = prefix
            changed = True
            continue

        # Bare quoted key at end (no colon follows it)
        m = re.search(r'[,{]\s*"[^"]*"\s*$', s)
        if m:
            boundary_char = s[m.start()]
            s = s[:m.start()].rstrip()
            if boundary_char == '{':
                s += '{'
            changed = True
            continue

    # Phase 3: recompute stack and close open brackets/braces
    stack, _ = _compute_stack_and_string_state(s)
    close_map = {'{': '}', '[': ']'}
    for ch in reversed(stack):
        if ch in close_map:
            s += close_map[ch]

    return s


def parse_partial_json(s: str) -> Optional[dict]:
    """
    Parse a partial JSON string, returning a dict or None on failure.
    None means the accumulated string isn't parseable yet — callers skip the yield.
    """
    if not s or not s.strip():
        return None
    try:
        repaired = repair_partial_json(s)
        result = json.loads(repaired)
        return result if isinstance(result, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None
