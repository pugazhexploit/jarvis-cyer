import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'plugins'))
import whatsapp_desktop_call

print("Starting live test...")
result = whatsapp_desktop_call.run({
    "intent": "voice_call",
    "contact_name": "My World"
})

print("\n--- LIVE TEST RESULT ---")
print(result)
