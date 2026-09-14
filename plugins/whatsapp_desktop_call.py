import uiautomation as auto
import time
import re
import psutil

# --- CONFIGURABLE OFFSETS FOR CALL BUTTONS ---
# Based on WhatsApp Desktop window geometry:
VOICE_CALL_X_OFFSET = 148
VIDEO_CALL_X_OFFSET = 205
CALL_BUTTON_Y_OFFSET = 70
# ---------------------------------------------

class WhatsAppDesktopController:
    def __init__(self):
        self.window = None
        self.diagnostic_log = []
        self.active_contact = None

    def log(self, msg):
        self.diagnostic_log.append(msg)

    def find_or_focus_whatsapp(self):
        self.window = None
        root = auto.GetRootControl()
        for win in root.GetChildren():
            try:
                name = win.Name
                pid = win.ProcessId
                proc_name = psutil.Process(pid).name()
                if "WhatsApp" in proc_name or "WhatsApp" in name:
                    self.window = win
                    break
            except:
                continue

        if self.window and self.window.Exists(0, 0):
            try:
                self.window.SetActive()
                time.sleep(0.3)
            except Exception:
                pass
            self.log("WhatsApp detected and focused.")
            return True
        self.log("WhatsApp NOT detected.")
        return False

    def is_whatsapp_running(self):
        if self.find_or_focus_whatsapp():
            return True
        # Try auto-launching WhatsApp Desktop
        try:
            import os
            os.system('start "" "whatsapp:"')
            time.sleep(2.5)
            return self.find_or_focus_whatsapp()
        except Exception:
            return False

    def search_contact(self, name):
        if not self.window:
            if not self.is_whatsapp_running():
                self.log("Search failed: WhatsApp window is not open or cannot be found.")
                return []
                
        normalized = name.lower().replace(" ", "")
        if getattr(self, 'active_contact', None) == normalized:
            self.log(f"No contact search required; target chat already open: {name}")
            return ["ALREADY_ACTIVE"]
                
        self.log(f"Initiating search for: '{name}'")
        
        layer1_success = False
        # Layer 1: Try finding EditControl inside the WebView2 (UIA)
        try:
            search_box = self.window.EditControl(searchDepth=12)
            if search_box.Exists(0.5, 1):
                search_box.Click(waitTime=0.1)
                search_box.SendKeys('{Ctrl}a{Delete}', waitTime=0.1)
                search_box.SendKeys(name, waitTime=1.5)
                self.log("Layer 1 (UIA): Search text entered via EditControl.")
                layer1_success = True
        except Exception as e:
            pass

        # Layer 2: Keyboard shortcuts (Highly reliable for Electron/WebView2 apps)
        if not layer1_success:
            try:
                self.window.SetActive()
                time.sleep(0.2)
                # Ctrl+F focuses the search in WhatsApp Desktop natively
                self.window.SendKeys('{Ctrl}f', waitTime=0.5)
                self.window.SendKeys('{Ctrl}a{Delete}', waitTime=0.1)
                self.window.SendKeys(name, waitTime=1.5)
                self.log("Layer 2 (Keyboard): Search text entered via Ctrl+F shortcut.")
                layer1_success = True
            except Exception as e:
                self.log(f"Layer 2 failed: {e}")
                
        # Layer 3: PyAutoGUI spatial fallback (last resort)
        if not layer1_success:
            try:
                import pyautogui
                rect = self.window.BoundingRectangle
                # Relative click at approx x=150, y=80 from top-left (typical search bar location)
                pyautogui.click(rect.left + 150, rect.top + 80)
                time.sleep(0.2)
                pyautogui.hotkey('ctrl', 'a')
                pyautogui.press('delete')
                pyautogui.write(name, interval=0.05)
                self.log("Layer 3 (PyAutoGUI): Clicked relative coordinates for search box.")
            except Exception as e:
                self.log(f"Layer 3 failed: {e}")

        # Wait for rendering
        time.sleep(1.0)
            
        # Try to read the actual result controls inside WebView2 -> DocumentControl
        matches = []
        try:
            # We look for the main WebView area
            doc = self.window.DocumentControl(searchDepth=8)
            if doc.Exists(0.1, 1):
                # Search for texts that match the name
                normalized_target = name.lower().replace(" ", "")
                for c, d in auto.WalkControl(doc, maxDepth=10):
                    try:
                        if c.Name:
                            normalized_cname = c.Name.lower().replace(" ", "")
                            if normalized_target in normalized_cname:
                                matches.append(c.Name)
                    except:
                        pass
        except Exception:
            pass
            
        matches = list(set(matches))
        if matches:
            self.log(f"Contact search successful: {name}. Results detected via UIA inside WebView2: {matches}")
        else:
            self.log(f"Contact search successful: {name}. UIA blind to result list inside WebView2. Will rely on default top-result behavior.")
            
        return matches

    def _open_contact_keyboard_fallback(self, contact_name, is_uia_blind=False):
        if is_uia_blind:
            self.log("UIA blind search path detected.")
        try:
            self.window.SetActive()
            self.log("Keyboard fallback: selecting top search result.")
            self.window.SendKeys('{Enter}', waitTime=0.5)
            self.log("Keyboard fallback: waiting for chat transition.")
            time.sleep(1.0)
            return True
        except Exception as e:
            self.log(f"Keyboard fallback failed: {e}")
            return False

    def open_contact(self, name, uia_matches):
        if not self.window: return False
        
        normalized_name = name.lower().replace(" ", "")
        if uia_matches == ["ALREADY_ACTIVE"]:
            self.active_contact = normalized_name
            self.log(f"Active chat established: {name}")
            return True
        
        self.active_contact = None
        opened = False
        # Layer 1: Click the exact UIA match if it was detected
        if uia_matches:
            try:
                doc = self.window.DocumentControl(searchDepth=8)
                if doc.Exists(0.1, 1):
                    normalized_target = name.lower().replace(" ", "")
                    for c, d in auto.WalkControl(doc, maxDepth=10):
                        try:
                            if c.Name:
                                normalized_cname = c.Name.lower().replace(" ", "")
                                if normalized_target in normalized_cname:
                                    c.Click()
                                    time.sleep(0.5)
                                    self.log(f"Layer 1 (UIA): Clicked contact item '{c.Name}'.")
                                    opened = True
                                    break
                        except:
                            continue
            except Exception:
                pass

        # Determine if UIA was blind during search
        is_uia_blind = any("UIA blind" in msg for msg in self.diagnostic_log[-10:])
        
        # Layer 2: Keyboard 'Enter' to open top search result
        if not opened:
            opened = self._open_contact_keyboard_fallback(name, is_uia_blind)
                
        if opened:
            # Verification: Check if the contact name appears in the Window title or if call buttons exist
            verified = False
            
            # Check 1: Window Title
            try:
                if name.lower().replace(" ", "") in self.window.Name.lower().replace(" ", ""):
                    verified = True
                    self.log(f"Post-click verification: Window Title confirmed chat '{self.window.Name}'")
            except Exception:
                pass
                
            # Check 2: Call Buttons (if UIA works)
            if not verified:
                try:
                    v_btn = self.window.ButtonControl(searchDepth=12, Name="Voice call")
                    if v_btn.Exists(0.1, 1):
                        verified = True
                        self.log("Post-click verification: Call buttons detected via UIA.")
                except Exception:
                    pass
                    
            if not verified:
                if is_uia_blind:
                    self.log("Chat open assumed after successful blind WebView2 navigation.")
                elif uia_matches:
                    self.log("Post-click verification failed: UIA matches found but UI state didn't update.")
                    opened = False
                else:
                    self.log("Post-click verification failed: Chat did not open.")
                    opened = False
            else:
                self.log("Chat opened successfully.")
            
        if opened:
            self.active_contact = normalized_name
            self.log(f"Active chat established: {name}")
            
        return opened

    def check_call_buttons(self):
        try:
            voice_btn = self.window.ButtonControl(searchDepth=12, Name="Voice call")
            if not voice_btn.Exists(0.1, 1):
                voice_btn = self.window.ButtonControl(searchDepth=12, Name="Call")
                
            video_btn = self.window.ButtonControl(searchDepth=12, Name="Video call")
            
            v_exists = voice_btn.Exists(0.1, 1)
            vid_exists = video_btn.Exists(0.1, 1)
            
            if v_exists or vid_exists:
                self.log("Call buttons DETECTED via UIA in chat header.")
            else:
                self.log("Call buttons NOT DETECTED (UIA is blind or not in chat).")
        except:
            self.log("Call buttons NOT DETECTED (Exception during UIA check).")

    def _verify_call_state(self):
        self.log("Waiting 1.5s for call state UI change...")
        time.sleep(1.5)
        state = self.get_call_state()
        if state == "CONNECTED":
            self.log("Post-click verification: Call state verified as CONNECTED/OUTGOING.")
            return "SUCCESS_VERIFIED"
        else:
            self.log(f"Post-click verification: Call state could not be independently verified (State: {state}).")
            return "SUCCESS_UNVERIFIED"

    def _ensure_active_chat(self, name):
        normalized = name.lower().replace(" ", "")
        if getattr(self, 'active_contact', None) != normalized:
            self.log(f"Fail safe: Target chat '{name}' is not currently established as active.")
            return False
        return True

    def start_voice_call(self, name):
        if not self.window: return False
        
        if not self._ensure_active_chat(name):
            return False
            
        self.log(f"Starting voice call from active chat: {name}")
        
        # Delay to allow chat header to render fully
        time.sleep(1.0)

        # Layer 1: UIA Click
        try:
            voice_btn = self.window.ButtonControl(searchDepth=12, Name="Voice call")
            if not voice_btn.Exists(0.1, 1):
                voice_btn = self.window.ButtonControl(searchDepth=12, Name="Call")
            
            if voice_btn.Exists(0.1, 1):
                voice_btn.Click()
                self.log("Voice call button located in active chat via UIA.")
                self.log(f"Initiating WhatsApp voice call to {name}.")
                return self._verify_call_state()
        except Exception as e:
            self.log(f"Layer 1 UIA voice call click failed: {e}")

        # Layer 2: Spatial Fallback
        self.log("UIA blind; using spatial fallback on active chat header.")
        try:
            import pyautogui
            rect = self.window.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            self.log(f"WhatsApp window rectangle: x={rect.left}, y={rect.top}, width={width}, height={height}")
            
            # Prevent blind clicks if window geometry is nonsensical
            if width < 500 or height < 400:
                self.log("Window too small to safely calculate spatial call buttons.")
                return False
                
            click_x = rect.left + width - VOICE_CALL_X_OFFSET
            click_y = rect.top + CALL_BUTTON_Y_OFFSET
            
            self.log(f"Targeting voice call button at Spatial geometry (x={click_x}, y={click_y}).")
            
            self.window.SetActive()
            time.sleep(0.2)
            pyautogui.click(click_x, click_y)
            self.log("Voice call button click executed from active chat.")
            self.log(f"Initiating WhatsApp voice call to {name}.")
            return self._verify_call_state()
        except Exception as e:
            self.log(f"Layer 2 Spatial voice call click failed: {e}")
            
        return False

    def start_video_call(self, name):
        if not self.window: return False
        self.log(f"Attempting to start video call for {name}...")
        
        # Delay to allow chat header to render fully
        time.sleep(0.5)

        # Layer 1: UIA Click
        try:
            video_btn = self.window.ButtonControl(searchDepth=12, Name="Video call")
            if video_btn.Exists(0.1, 1):
                video_btn.Click()
                self.log("Video call button located via UIA. Click executed.")
                self.log(f"Initiating WhatsApp video call to {name}.")
                return self._verify_call_state()
        except Exception as e:
            self.log(f"Layer 1 UIA video call click failed: {e}")

        # Layer 2: Spatial Fallback
        try:
            import pyautogui
            rect = self.window.BoundingRectangle
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            
            self.log(f"WhatsApp window rectangle: x={rect.left}, y={rect.top}, width={width}, height={height}")
            
            if width < 500 or height < 400:
                self.log("Window too small to safely calculate spatial call buttons.")
                return False
                
            click_x = rect.left + width - VIDEO_CALL_X_OFFSET
            click_y = rect.top + CALL_BUTTON_Y_OFFSET
            
            self.log(f"Targeting video call button at Spatial geometry (x={click_x}, y={click_y}).")
            
            self.window.SetActive()
            time.sleep(0.2)
            pyautogui.click(click_x, click_y)
            self.log(f"Video call button click executed.")
            self.log(f"Initiating WhatsApp video call to {name}.")
            return self._verify_call_state()
        except Exception as e:
            self.log(f"Layer 2 Spatial video call click failed: {e}")
            
        return False

    def end_call(self):
        if not self.window: return False
        btn = self.window.ButtonControl(searchDepth=12, Name="End call")
        if btn.Exists(1, 1):
            btn.Click()
            return True
        return False

    def answer_call(self):
        if not self.window: return False
        btn = self.window.ButtonControl(searchDepth=12, Name="Accept")
        if btn.Exists(1, 1):
            btn.Click()
            return True
        return False

    def reject_call(self):
        if not self.window: return False
        btn = self.window.ButtonControl(searchDepth=12, Name="Decline")
        if btn.Exists(1, 1):
            btn.Click()
            return True
        return False

    def get_call_state(self):
        if not self.window: return "UNKNOWN"
        if self.window.ButtonControl(searchDepth=12, Name="End call").Exists(0.5, 1):
            return "CONNECTED"
        if self.window.ButtonControl(searchDepth=12, Name="Accept").Exists(0.5, 1):
            return "INCOMING_CALL"
        return "UNKNOWN"


PLUGIN = {
    "name": "whatsapp_desktop_call",
    "description": (
        "Controls WhatsApp Desktop calling features. "
        "Use this tool when the user asks to call someone on WhatsApp, answer a call, or end a call."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "intent": {
                "type": "STRING", 
                "description": "The specific intent (e.g., 'voice_call', 'video_call', 'end_call', 'answer_call', 'reject_call', 'status', 'whatsapp_search_test')."
            },
            "contact_name": {
                "type": "STRING",
                "description": "The name of the contact to call, if applicable."
            }
        },
        "required": ["intent"],
    },
}

def extract_contact_name(text):
    patterns = [
        r"call\s+(.+?)\s+on\s+whatsapp",
        r"whatsapp\s+video\s+call\s+to\s+(.+)",
        r"whatsapp\s+video\s+call\s+(.+)",
        r"whatsapp\s+voice\s+call\s+to\s+(.+)",
        r"whatsapp\s+voice\s+call\s+(.+)",
        r"voice\s+call\s+to\s+(.+)",
        r"voice\s+call\s+(.+)",
        r"video\s+call\s+to\s+(.+)",
        r"whatsapp\s+call\s+(.+)",
        r"whatsapp\s+la\s+(.+?)\s*ku\s+call",
        r"(.+?)\s*ku\s+voice\s+call\s*pannu",
        r"(.+?)\s*ku\s+video\s+call\s*pannu",
        r"(.+?)\s*ku\s+call\s*pannu",
        r"(.+?)\s*ku\s+call",
        r"whatsapp\s+search\s+(.+)",
        r"search\s+(.+?)\s+on\s+whatsapp",
        r"call\s+(.+)"
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            name = m.group(1).strip()
            name = re.sub(r'(?i)\b(pannu|please|to|on\s+whatsapp)\b', '', name).strip()
            if name:
                return name
    return None


def run(parameters: dict, player=None, session_memory=None) -> str:
    raw_intent = parameters.get("intent", "").lower().strip()
    contact_name = parameters.get("contact_name", "").strip()

    controller = WhatsAppDesktopController()
    
    if not contact_name and ("call" in raw_intent or "search" in raw_intent):
        contact_name = extract_contact_name(raw_intent) or ""
        
    if "whatsapp_search_test" in raw_intent or "search" in raw_intent:
        logical_intent = "whatsapp_search_test"
    elif "end" in raw_intent or "cut" in raw_intent or "hang" in raw_intent:
        logical_intent = "end_call"
    elif "answer" in raw_intent or "attend" in raw_intent or "accept" in raw_intent:
        logical_intent = "answer_call"
    elif "reject" in raw_intent or "decline" in raw_intent:
        logical_intent = "reject_call"
    elif "video" in raw_intent:
        logical_intent = "video_call"
    elif "voice" in raw_intent or "call" in raw_intent:
        logical_intent = "voice_call"
    elif "status" in raw_intent:
        logical_intent = "status"
    else:
        return "Error: Ambiguous WhatsApp command."

    if not controller.is_whatsapp_running():
        return "Error: WhatsApp Desktop is not running."

    if logical_intent == "status":
        state = controller.get_call_state()
        return f"WhatsApp Call State: {state}"

    if logical_intent in ["end_call", "answer_call", "reject_call"]:
        if logical_intent == "end_call":
            success = controller.end_call()
        elif logical_intent == "answer_call":
            success = controller.answer_call()
        elif logical_intent == "reject_call":
            success = controller.reject_call()
            
        if success:
            return f"Successfully executed {logical_intent}."
        else:
            return f"Failed to {logical_intent}. UI elements not found."

    if not contact_name:
        return "Error: Contact name not specified."

    if player and logical_intent != "whatsapp_search_test":
        try:
            player.write_log(f"JARVIS: Searching WhatsApp for '{contact_name}'...")
        except:
            pass

    matches = controller.search_contact(contact_name)
    
    if logical_intent == "whatsapp_search_test":
        controller.open_contact(contact_name, matches)
        controller.check_call_buttons()
        log_output = "\n".join(controller.diagnostic_log)
        return f"--- WhatsApp Diagnostic Search Test Completed ---\nLog Trace:\n{log_output}\n\nSearch complete, no call initiated."
            
    # For actual calls, we handle multiple matches if UIA is NOT blind
    if len(matches) > 1:
        return f"Multiple contacts found for '{contact_name}'. Matches: {matches}. Please be more specific."
    elif len(matches) == 0 and len(controller.diagnostic_log) > 0 and "UIA blind" not in controller.diagnostic_log[-1]:
        # If UIA works and found nothing
        return f"Contact '{contact_name}' not found on WhatsApp Desktop."

    if player:
        try:
            player.write_log(f"JARVIS: Calling {contact_name} on WhatsApp.")
        except:
            pass
            
    success_open = controller.open_contact(contact_name, matches)
    if not success_open:
        log_output = "\n".join(controller.diagnostic_log)
        return f"Failed to open chat for {contact_name}.\nLogs:\n{log_output}"

    if logical_intent == "video_call":
        success_call = controller.start_video_call(contact_name)
    else:
        success_call = controller.start_voice_call(contact_name)
        
    log_output = "\n".join(controller.diagnostic_log)
    
    if success_call == "SUCCESS_VERIFIED":
        return f"Successfully initiated {logical_intent} to {contact_name}.\nLogs:\n{log_output}"
    elif success_call == "SUCCESS_UNVERIFIED":
        return f"{logical_intent.replace('_', ' ').capitalize()} button click executed; call state could not be independently verified.\nLogs:\n{log_output}"
    else:
        return f"Failed to click the call button for {contact_name}. UI elements not found.\nLogs:\n{log_output}"

