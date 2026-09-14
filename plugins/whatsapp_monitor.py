"""
plugins/whatsapp_monitor.py — Automatic WhatsApp AI Auto-Responder

Monitors Windows Toast notifications for incoming WhatsApp messages in the background.
When a message arrives while you are coding or away:
  1. Detects the sender and message content (filtering out system banners).
  2. Generates a smart, contextual AI reply via OpenRouter / Groq / Gemini.
  3. Sends the reply in the background and IMMEDIATELY restores focus to your editor.
  4. Displays the incoming message and your automated reply on your monitor
     (Console banner + JARVIS HUD log + Windows Toast notification).
"""

import asyncio
import json
import os
import re
import sys
import threading
import time
import urllib.parse
from pathlib import Path

# Try importing winrt (Windows 10/11) or winsdk for notification monitoring
try:
    try:
        from winrt.windows.ui.notifications.management import UserNotificationListener
        from winrt.windows.ui.notifications import (
            NotificationKinds,
            ToastNotificationManager,
            ToastNotification,
        )
        from winrt.windows.data.xml.dom import XmlDocument
        _WINRT_AVAILABLE = True
    except ImportError:
        from winsdk.windows.ui.notifications.management import UserNotificationListener
        from winsdk.windows.ui.notifications import NotificationKinds
        _WINRT_AVAILABLE = True
except ImportError:
    _WINRT_AVAILABLE = False

try:
    import win32gui
    import win32con
    import win32process
    _WIN32_AVAILABLE = True
except ImportError:
    _WIN32_AVAILABLE = False

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _PYAUTOGUI = True
except ImportError:
    _PYAUTOGUI = False

try:
    import pyperclip
    _PYPERCLIP = True
except ImportError:
    _PYPERCLIP = False

try:
    from google import genai
    _GENAI_AVAILABLE = True
except ImportError:
    _GENAI_AVAILABLE = False


PLUGIN = {
    "name": "whatsapp_monitor",
    "description": (
        "Turn on or off the WhatsApp background auto-responder. "
        "When active, JARVIS reads Windows notifications for WhatsApp messages, "
        "generates a smart contextual AI reply, sends it in the background without "
        "interrupting your coding, and displays the conversation on your monitor."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "status": {
                "type": "STRING",
                "description": "'on' to start monitoring, 'off' to stop monitoring."
            }
        },
        "required": ["status"],
    },
}

_monitor_thread = None
_monitoring_active = False
_replied_notification_ids = set()

# System notifications and banners to ignore (not real user messages)
_IGNORED_SENDER_PATTERNS = [
    "you may have new messages",
    "checking for new messages",
    "whatsapp",
    "whatsapp web",
    "new messages",
    "incoming voice call",
    "incoming video call",
    "missed voice call",
    "missed video call",
    "ongoing voice call",
    "ongoing video call",
    "calling...",
    "backup in progress",
]


def _get_user_name() -> str:
    """Retrieve user name from config or default to Sir."""
    try:
        cfg_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            return cfg.get("user_name", "Sir")
    except Exception:
        pass
    return "Sir"


def _show_desktop_toast(title: str, text: str) -> None:
    """Display a non-intrusive toast on the monitor so the user sees the message while coding."""
    try:
        clean_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        clean_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        xml = XmlDocument()
        xml.load_xml(
            f"<toast><visual><binding template='ToastGeneric'>"
            f"<text>{clean_title}</text>"
            f"<text>{clean_text}</text>"
            f"</binding></visual></toast>"
        )
        notif = ToastNotification(xml)
        notifier = ToastNotificationManager.get_default().create_toast_notifier()
        notifier.show(notif)
    except Exception:
        pass


def _generate_dynamic_reply(sender: str, message: str) -> str:
    """Generate a contextual AI reply on the user's behalf."""
    user_name = _get_user_name()
    prompt = (
        f"You are JARVIS, {user_name}'s personal AI assistant. {user_name} is currently busy coding at their desk. "
        f"You received a WhatsApp message from '{sender}' which says: '{message}'. "
        f"Write a short, polite, and natural reply on {user_name}'s behalf. "
        f"Acknowledge what they said. If it is urgent or an update, tell them you will notify {user_name} immediately. "
        f"Keep the reply concise (1 to 2 short sentences). Reply directly as JARVIS."
    )

    raw_reply = None
    # 1. Try the core LLM router (OpenRouter, Groq, Ollama)
    try:
        from core.llm_client import call_llm_text
        reply = call_llm_text(prompt)
        if reply and len(reply.strip()) > 0:
            raw_reply = reply.strip()
    except Exception as e:
        print(f"[WhatsApp Monitor] LLM router reply error: {e}")

    # 2. Try Gemini API fallback
    if not raw_reply and _GENAI_AVAILABLE:
        try:
            cfg_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                api_key = cfg.get("gemini_api_key")
                if api_key:
                    client = genai.Client(api_key=api_key)
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                    )
                    if resp and resp.text:
                        raw_reply = resp.text.strip()
        except Exception as e:
            print(f"[WhatsApp Monitor] Gemini reply fallback error: {e}")

    if not raw_reply:
        raw_reply = f"{user_name} is currently busy coding right now, but I have noted your message."

    try:
        from core.message_formatter import format_as_jarvis_message
        return format_as_jarvis_message(raw_reply, context={"category": "personal_response", "sender": sender}, user_name=user_name)
    except Exception:
        return raw_reply



def _paste_text_fast(text: str) -> None:
    """Paste text cleanly via clipboard."""
    if _PYPERCLIP:
        pyperclip.copy(text)
        time.sleep(0.08)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.08)
    elif _PYAUTOGUI:
        pyautogui.write(text, interval=0.01)


def _find_whatsapp_window():
    """Find any visible or background WhatsApp window handle."""
    if not _WIN32_AVAILABLE:
        return None

    wa_hwnd = None

    def _enum_cb(hwnd, _):
        nonlocal wa_hwnd
        try:
            title = win32gui.GetWindowText(hwnd)
            cls = win32gui.GetClassName(hwnd)
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            # Check for WhatsApp Desktop window
            if "WhatsApp" in title or cls in ("ApplicationFrameWindow", "Windows.UI.Core.CoreWindow"):
                if "WhatsApp" in title:
                    wa_hwnd = hwnd
                    return False
        except Exception:
            pass
        return True

    try:
        win32gui.EnumWindows(_enum_cb, None)
    except Exception:
        pass
    return wa_hwnd


def _send_whatsapp_seamless(receiver: str, message: str) -> bool:
    """
    Sends WhatsApp message in the background and immediately restores
    focus to whatever window the user was coding in.
    """
    if not _PYAUTOGUI:
        print("[WhatsApp Monitor] PyAutoGUI not installed, cannot send.")
        return False

    try:
        from core.message_formatter import format_as_jarvis_message
        message = format_as_jarvis_message(message, context={"category": "personal_response", "sender": receiver})
    except Exception as e:
        print(f"[WhatsApp Monitor] Formatter fallback: {e}")

    prev_hwnd = None
    if _WIN32_AVAILABLE:
        try:
            prev_hwnd = win32gui.GetForegroundWindow()
        except Exception:
            pass

    success = False
    try:
        # Check if receiver is a phone number
        digits_only = re.sub(r"[^0-9]", "", receiver)
        if len(digits_only) >= 10:
            # Direct deep-link URL protocol (fastest & most reliable)
            encoded_msg = urllib.parse.quote(message)
            url = f"whatsapp://send?phone={digits_only}&text={encoded_msg}"
            os.system(f'start "" "{url}"')
            time.sleep(1.2)
            # WhatsApp opens with message prefilled in the chat box
            pyautogui.press("enter")
            time.sleep(0.2)
            success = True
        else:
            # Search contact by name
            # Launch WhatsApp via protocol if not open
            os.system('start "" "whatsapp:"')
            time.sleep(0.9)

            wa_hwnd = _find_whatsapp_window()
            if wa_hwnd and _WIN32_AVAILABLE:
                try:
                    win32gui.ShowWindow(wa_hwnd, win32con.SW_RESTORE)
                    win32gui.SetForegroundWindow(wa_hwnd)
                    time.sleep(0.3)
                except Exception:
                    pass

            # Focus search bar in WhatsApp
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "a")
            time.sleep(0.1)
            pyautogui.press("delete")
            time.sleep(0.1)
            _paste_text_fast(receiver)
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(0.5)

            # Paste and send message
            _paste_text_fast(message)
            time.sleep(0.2)
            pyautogui.press("enter")
            time.sleep(0.3)
            success = True

        # Deselect chat so subsequent notifications still trigger
        pyautogui.press("esc")
        time.sleep(0.1)

    except Exception as e:
        print(f"[WhatsApp Monitor] Send error: {e}")
        success = False

    finally:
        # IMMEDIATELY RESTORE USER'S ACTIVE WINDOW
        if _WIN32_AVAILABLE and prev_hwnd and prev_hwnd != 0:
            try:
                time.sleep(0.1)
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass

    return success


async def _get_whatsapp_notifications():
    """Query Windows Action Center for real WhatsApp messages."""
    if not _WINRT_AVAILABLE:
        return []

    try:
        listener = UserNotificationListener.current
        access = await listener.request_access_async()
        if int(access) != 1:  # 1 == ALLOWED
            return []

        notifs = await listener.get_notifications_async(NotificationKinds.TOAST)
    except Exception as e:
        print(f"[WhatsApp Monitor] Notification query error: {e}")
        return []

    results = []
    for n in notifs:
        try:
            app_name = n.app_info.display_info.display_name
            app_id = getattr(n.app_info, "id", "")

            # Match WhatsApp Desktop (AppX or Win32)
            if "whatsapp" in app_name.lower() or "whatsapp" in app_id.lower():
                bindings = n.notification.visual.bindings
                texts = []
                for b in bindings:
                    for t in b.get_text_elements():
                        if t.text and t.text.strip():
                            texts.append(t.text.strip())

                if not texts:
                    continue

                raw_sender = texts[0].strip()
                raw_msg = texts[1].strip() if len(texts) > 1 else ""

                # Ignore system banners
                if raw_sender.lower() in _IGNORED_SENDER_PATTERNS:
                    continue
                if not raw_msg and raw_sender.lower() in ("you may have new messages", "whatsapp"):
                    continue

                # Clean sender name (remove (X messages) suffix if present)
                clean_sender = re.sub(r"\s*\(\d+\s*messages?\)", "", raw_sender, flags=re.IGNORECASE).strip()

                results.append({
                    "id": n.id,
                    "sender": clean_sender or raw_sender,
                    "message": raw_msg,
                })
        except Exception:
            pass

    return results


def _whatsapp_monitor_loop(player):
    """Background monitoring thread."""
    global _monitoring_active, _replied_notification_ids

    print("\n" + "=" * 62)
    print("  [WhatsApp Monitor] BACKGROUND AUTO-RESPONDER ACTIVE")
    print("  Incoming WhatsApp messages will be answered automatically.")
    print("  Your active coding windows will not be interrupted.")
    print("=" * 62 + "\n")

    if player and hasattr(player, "write_log"):
        player.write_log("JARVIS: WhatsApp background auto-reply is now ACTIVE.")

    _show_desktop_toast(
        "JARVIS WhatsApp Monitor",
        "Background monitoring active. Messages will auto-reply while you code."
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Seed existing notifications so we NEVER reply to old historical messages
    try:
        initial = loop.run_until_complete(_get_whatsapp_notifications())
        for n in initial:
            _replied_notification_ids.add(n["id"])
        if initial:
            print(f"[WhatsApp Monitor] Seeded {len(initial)} existing notification(s) to avoid replying to old history.")
    except Exception as e:
        print(f"[WhatsApp Monitor] Notification seeding error: {e}")

    listener = None
    if _WINRT_AVAILABLE:
        try:
            listener = UserNotificationListener.current
        except Exception:
            pass

    while _monitoring_active:
        try:
            notifications = loop.run_until_complete(_get_whatsapp_notifications())

            for notif in notifications:
                notif_id = notif["id"]
                sender = notif["sender"]
                message = notif["message"]

                if notif_id not in _replied_notification_ids:
                    _replied_notification_ids.add(notif_id)

                    # If message body is empty (e.g. status mention or photo), use polite fallback
                    display_msg = message if message else "(Attachment or media message)"

                    # 1. Print visual banner to console
                    print("\n" + "┌" + "─" * 58 + "┐")
                    print(f"│ 💬 WHATSAPP INCOMING: {sender}")
                    print(f"│    Message: {display_msg}")

                    # 2. Generate smart AI response
                    reply_text = _generate_dynamic_reply(sender, display_msg)
                    print(f"│ 🤖 AUTO-REPLYING: {reply_text}")
                    print("└" + "─" * 58 + "┘\n")

                    # 3. Display on the monitor (JARVIS HUD + Native Windows Toast)
                    if player and hasattr(player, "write_log"):
                        player.write_log(f"📱 WhatsApp [{sender}]: {display_msg}")
                        player.write_log(f"🤖 Auto-Replied: {reply_text}")

                    _show_desktop_toast(
                        f"WhatsApp: {sender}",
                        f"{display_msg}\n↪ Replied: {reply_text}"
                    )

                    # 4. Dispatch the reply in the background & restore coding window
                    sent = _send_whatsapp_seamless(sender, reply_text)
                    if sent:
                        print(f"[WhatsApp Monitor] ✅ Successfully replied to {sender}.")
                    else:
                        print(f"[WhatsApp Monitor] ⚠️ Could not dispatch reply to {sender}.")

                    # 5. Dismiss notification from Action Center
                    if listener:
                        try:
                            listener.remove_notification(notif_id)
                        except Exception:
                            pass

                    # 6. Inject into JARVIS's context memory
                    if player and hasattr(player, "on_text_command") and callable(player.on_text_command):
                        internal_memory = (
                            f"[SYSTEM_ALERT] You just automatically replied to a WhatsApp message in the background.\n"
                            f"Sender: {sender}\n"
                            f"Their message: {display_msg}\n"
                            f"Your reply: {reply_text}\n\n"
                            f"Keep this in your memory so you know what happened."
                        )
                        try:
                            player.on_text_command(internal_memory)
                        except Exception:
                            pass

        except Exception as e:
            print(f"[WhatsApp Monitor] Loop error: {e}")

        time.sleep(2)

    loop.close()
    print("[WhatsApp Monitor] Background thread stopped.")


def run(parameters: dict, player=None, session_memory=None) -> str:
    global _monitor_thread, _monitoring_active

    status = parameters.get("status", "off").lower()

    if status == "on":
        if _monitoring_active:
            return "WhatsApp background monitoring is already active."

        _monitoring_active = True
        _monitor_thread = threading.Thread(
            target=_whatsapp_monitor_loop,
            args=(player,),
            daemon=True
        )
        _monitor_thread.start()

        return (
            "WhatsApp background auto-reply enabled. I am monitoring for incoming messages, "
            "will reply automatically in the background while you code, and display updates on your monitor."
        )

    elif status == "off":
        if not _monitoring_active:
            return "WhatsApp background monitoring is already off."

        _monitoring_active = False
        return "I have stopped WhatsApp background monitoring."

    return "Invalid status. Use 'on' or 'off'."
