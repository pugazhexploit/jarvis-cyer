"""
JARVIS Personality Message Formatter.
Transforms raw tool outputs, system alerts, and information into JARVIS's distinct,
intelligent, calm, concise, and professional voice optimized for WhatsApp.

Ensures strict factual accuracy: NEVER modifies numbers, dates, times, names, or URLs.
Author: pugazhenthi
"""

from __future__ import annotations

import re
from typing import Optional, Union

AUTHOR_NAME = "pugazhenthi"
DEFAULT_USER_NAME = "Pugazh"

# Generic chatbot phrases to eliminate
ROBOTIC_PHRASES = [
    r"(?i)^here\s+is\s+the\s+(information|result|data)\s+(you\s+requested|for\s+you)[:\.\s]*",
    r"(?i)^sure[,!\s]+i\s+can\s+help\s+(you\s+)?with\s+that[:\.\s]*",
    r"(?i)^according\s+to\s+my\s+(analysis|system|records)[:\.\s]*",
    r"(?i)^as\s+an\s+ai\s+language\s+model[,:\.\s]*",
    r"(?i)^i\s+would\s+be\s+happy\s+to\s+help[:\.\s]*",
    r"(?i)^please\s+find\s+below\s+(the\s+information|the\s+details)[:\.\s]*",
    r"(?i)^as\s+requested[,:\.\s]*",
]


def _clean_robotic_intros(text: str) -> str:
    """Strip robotic chatbot openers."""
    cleaned = text.strip()
    for pattern in ROBOTIC_PHRASES:
        cleaned = re.sub(pattern, "", cleaned).strip()
    return cleaned


def _detect_context(content: str, explicit_context: Optional[str] = None) -> str:
    """Infer the message category if not explicitly passed."""
    if explicit_context:
        return explicit_context.lower().strip()

    low = content.lower()
    if any(k in low for k in ["⚠️", "alert", "critical", "warning", "exceeded", "cpu usage", "memory usage", "disk usage"]):
        return "system_alert"
    if any(k in low for k in ["done", "completed successfully", "task completed", "saved", "finished"]):
        return "task_completion"
    if any(k in low for k in ["host:", "port:", "ip:", "service:", "192.168.", "10.0.", "172.", "exit code", "ping", "nmap"]):
        return "technical_result"
    if any(k in low for k in ["reminder:", "remind", "at 0", "at 1", "at 2", "scheduled for"]):
        return "reminder"
    if any(k in low for k in ["weather", "temperature", "°c", "forecast", "chance of rain"]):
        return "status_update"
    if any(k in low for k in ["search", "results for", "found:"]):
        return "search_result"
    return "general"


def format_as_jarvis_message(
    content: str,
    context: Optional[Union[str, dict]] = None,
    user_name: Optional[str] = None,
) -> str:
    """
    Format any content, alert, or tool result into JARVIS's personality specifically for WhatsApp.

    Pipeline:
    User Request -> Tool/Reasoning -> Accurate Result -> JARVIS Formatter -> WhatsApp Message

    Guarantees:
    - Never modifies numbers, dates, times, URLs, or technical output.
    - Eliminates generic AI cliches.
    - Applies clean WhatsApp markdown (*bold*, ```code```, bullet points •).
    - Uses respectful, calm, and intelligent British-style butler / cyber AI tone.
    """
    if not content or not content.strip():
        return "Sir, there is no content to report."

    # Unpack context dict if provided
    context_str = ""
    recipient = ""
    if isinstance(context, dict):
        context_str = str(context.get("category") or context.get("context") or "")
        recipient = str(context.get("sender") or context.get("recipient") or "")
    elif isinstance(context, str):
        context_str = context

    category = _detect_context(content, context_str)
    cleaned = _clean_robotic_intros(content)
    honorific = "Sir"

    # 1. Category: System Alert
    if category in ("system_alert", "alert", "warning"):
        # Format as calm, high-priority notification with ⚠️
        msg = cleaned
        if not msg.startswith("⚠️"):
            # Ensure "Sir," prefix
            if not re.search(r"(?i)\b(sir|warning|alert)\b", msg[:15]):
                msg = f"⚠️ Sir, I've detected an issue.\n\n{msg}"
            else:
                msg = f"⚠️ {msg}"
        # Bold percentages or threshold numbers for WhatsApp
        msg = re.sub(r"(\b\d+%\b)", r"*\1*", msg)
        return msg.strip()

    # 2. Category: Task Completion
    if category in ("task_completion", "task_completed", "done"):
        # Format as crisp, confident confirmation
        body = cleaned
        # Strip redundant "Done" if already at start
        body = re.sub(r"(?i)^(done[,:\.\s]*|task\s+completed[,:\.\s]*)", "", body).strip()
        if body:
            return f"Done, sir. ✅\n\n{body}"
        return "Done, sir. ✅ The requested task has been completed successfully."

    # 3. Category: Weather / Environmental Status Update
    if category in ("status_update", "weather"):
        body = cleaned
        # Transform flat weather into natural JARVIS advisory
        temp_match = re.search(r"(\d+°C|\d+\s*degrees)", body, re.IGNORECASE)
        rain_match = re.search(r"(\d+%\s*chance\s*of\s*rain)", body, re.IGNORECASE)
        if temp_match and rain_match:
            temp = temp_match.group(1)
            rain = rain_match.group(1)
            advisory = " You may want to carry an umbrella." if ("60%" in rain or "70%" in rain or "80%" in rain or "90%" in rain or "100%" in rain) else ""
            return f"Sir, it's *{temp}* today with a *{rain}*.{advisory}"
        
        # Memory or hardware usage status
        mem_match = re.search(r"(memory|cpu|disk)\s*(?:usage\s*)?(?:is\s*currently\s*using|has\s*reached|is\s*at)\s*(\d+%)", body, re.IGNORECASE)
        if mem_match:
            res_type = mem_match.group(1).title()
            pct = mem_match.group(2)
            pct_val = int(re.sub(r"\D", "", pct))
            comment = "That's slightly elevated, but operations are stable." if pct_val < 85 else "That's high; monitoring resource pressure."
            return f"Sir, *{res_type}* usage has reached *{pct}*.\n{comment}"

        if not body.lower().startswith("sir"):
            return f"Sir, {body}"
        return body

    # 4. Category: Technical Result / Kali Terminal / Security
    if category in ("technical_result", "terminal", "security"):
        lines = [l.strip() for l in cleaned.splitlines() if l.strip()]
        # If output contains structured key-value lines
        kv_pairs = []
        is_kv = True
        for line in lines:
            if ":" in line and not line.startswith("http"):
                parts = line.split(":", 1)
                kv_pairs.append((parts[0].strip().title(), parts[1].strip()))
            else:
                is_kv = False
                break

        if is_kv and len(kv_pairs) >= 2:
            formatted_lines = [f"• *{k}*: {v}" for k, v in kv_pairs]
            return "Sir, here's the technical result:\n\n" + "\n".join(formatted_lines)

        # Raw code or terminal output
        if "\n" in cleaned or len(cleaned) > 80:
            return f"Sir, the execution result is as follows:\n\n```{cleaned}```"
        return f"Sir, the result is: *{cleaned}*"

    # 5. Category: Reminder
    if category in ("reminder", "scheduled"):
        body = cleaned
        body = re.sub(r"(?i)^(reminder[:\s]*|scheduled\s*reminder[:\s]*)", "", body).strip()
        return f"⏰ Sir, reminder for you:\n\n*{body}*"

    # 6. Category: Personal Response / Auto-reply to contacts
    if category in ("personal_response", "whatsapp_auto_reply"):
        body = cleaned
        # If replying on user's behalf to someone else (e.g. Pugazh is busy)
        active_user = user_name or DEFAULT_USER_NAME
        if recipient and not any(k in body.lower() for k in ["jarvis", "assistant"]):
            return (
                f"Hello, I am JARVIS, personal assistant to *{active_user}*.\n\n"
                f"{active_user} is currently engaged at his desk. {body}\n\n"
                f"I will ensure he receives your message."
            )
        return body

    # 7. General Fallback with JARVIS Persona & WhatsApp Polish
    # Ensure natural honorific without double "Sir"
    if not re.match(r"(?i)^(sir|done|yes|⚠️|⏰)", cleaned):
        cleaned = f"Sir, {cleaned}"

    # Polish bullet points
    cleaned = re.sub(r"^[-*]\s+", "• ", cleaned, flags=re.MULTILINE)
    return cleaned.strip()
