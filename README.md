

[![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20%7C%20macOS-lightgrey.svg)]()

**JARVIS-CYER** is an advanced, multimodal AI desktop assistant equipped with real-time voice interaction, dynamic UI HUD, autonomous system & browser control, WhatsApp voice bridging, hardware drone interfacing, and integrated Kali Linux security tool automation via WSL2.

---

## 🌟 Key Features

- 🎙️ **Real-Time Voice & Multimodal Interaction**
  - Ultra-low latency voice streaming powered by Google Gemini Live API.
  - Multi-engine Speech-To-Text (Whisper STT) and Text-To-Speech (Edge-TTS, ElevenLabs, PyTorch-based neural TTS).
  - Screen comprehension and real-time visual assistance.

- 🧠 **Multi-Provider LLM Intelligence**
  - **Google Gemini Live API** for real-time bidirectional audio streaming.
  - **OpenRouter & Groq** routing with automatic fallback and budget thresholds.
  - **Local Offline LLMs** supported via Ollama (`http://localhost:11434`) and LM Studio (`http://localhost:1234`).

- 🛡️ **Cybersecurity & Terminal Automation (Kali Linux on WSL2)**
  - Seamless integration with Kali Linux running in WSL2.
  - Interactive terminal plugin with safety gates for pentesting/security tools (`nmap`, `gobuster`, `sqlmap`, `nikto`).
  - Strict confirmation gates for elevated (`sudo`) or destructive commands.

- 📞 **WhatsApp Voice & Message Automation**
  - Automated WhatsApp desktop voice calls with real-time two-way voice bridging.
  - Automated direct messaging via WhatsApp, Telegram, Discord, and Instagram.

- 🛸 **Hardware & Drone Control**
  - Wi-Fi controller interface for KY UFO drones (offline simulation mode and real UDP hardware protocol over `192.168.1.1:7099`).

- 🖥️ **Futuristic Desktop HUD & Web Dashboard**
  - High-performance PyQt holographic user interface.
  - Web-based companion dashboard (FastAPI / WebSockets) accessible on local network via encrypted TLS/HTTP.

- ⚡ **Desktop & Web Automation**
  - Hands-free browser control, web searches, news scraping, YouTube video playback, weather reports, and flight finding.
  - Automated Windows task scheduling and reminders.

---

## 📂 Project Structure

```text
jarvies/
├── actions/                 # Core automation actions (browser, weather, youtube, etc.)
│   ├── browser_control.py   # Web browser navigation and searches
│   ├── code_helper.py       # Code assistance & screenshot analysis
│   ├── desktop.py           # Sandboxed desktop automation execution
│   ├── flight_finder.py     # Flight searches via Google Flights
│   ├── send_message.py      # Messaging automation (WhatsApp, Discord, Telegram, etc.)
│   └── web_search.py        # Web search & news intelligence
├── config/                  # Configuration & API definitions
│   ├── api_keys.json.example# Template for API keys and UI preferences
│   └── certs/               # TLS certificates for local dashboard
├── core/                    # Core engines (LLM router, STT, TTS, memory)
│   ├── llm_client.py        # Ollama / LM Studio client
│   ├── provider_router.py   # OpenRouter & Groq fallback router
│   ├── stt.py               # Speech-to-Text (Whisper)
│   └── tts.py               # Text-to-Speech (Edge-TTS / ElevenLabs)
├── dashboard/               # Local Web & Mobile companion dashboard
│   ├── server.py            # FastAPI / WebSocket server
│   └── static/app.html      # Responsive dashboard web app
├── plugins/                 # Extensible plugin system
│   ├── jarvis_terminal.py   # Kali Linux WSL2 terminal interface
│   ├── ky_ufo_drone.py      # KY UFO drone UDP flight controller
│   ├── whatsapp_desktop_call.py # WhatsApp desktop call automation
│   └── whatsapp_voice_bridge.py # Two-way voice call bridge
├── tests/                   # Automated unit & integration tests
├── main.py                  # Main voice assistant entrypoint (Gemini Live + HUD)
├── ui.py                    # Futuristic PyQt HUD interface
├── requirements.txt         # Project dependencies
└── README.md                # Project documentation
```

---

## 🚀 Quick Start & How to Use

### 1. Clone the Repository
```bash
git clone https://github.com/pugazhexploit/jarvis-cyer.git
cd jarvis-cyer
```

### 2. Create and Activate Virtual Environment
```bash
# Windows (PowerShell)
python -m venv venv
.\venv\Scripts\Activate.ps1

# Linux / macOS
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

### 4. Configuration Setup
1. **Copy the example configuration files**:
   ```bash
   cp .env.example .env
   cp config/api_keys.json.example config/api_keys.json
   ```

2. **Configure your API keys**:
   - In `.env`:
     ```env
     OPENROUTER_API_KEY=your_openrouter_api_key_here
     GROQ_API_KEY=your_groq_api_key_here
     OPENROUTER_BUDGET=1.00
     ```
   - In `config/api_keys.json`:
     ```json
     {
         "gemini_api_key": "YOUR_GEMINI_API_KEY_HERE",
         "os_system": "windows",
         "assistant_name": "JARVIS",
         "user_name": "YourName",
         "llm_provider": "openrouter"
     }
     ```

> ⚠️ **IMPORTANT**: Never commit your `.env` or `config/api_keys.json` containing live API keys to a public repository. They are already listed in `.gitignore`.

---

## 🎯 Running JARVIS

### Run the Main Voice Assistant & Holographic HUD
```bash
python main.py
```

### Run the Companion Web Dashboard
```bash
python -m dashboard.server
```
Visit `http://localhost:8000` or scan the QR code displayed in the console from your mobile device.

### Running Automated Tests
```bash
pytest tests/
```

---

## 🔒 Security & Safe Usage

- **Local Execution Sandboxing**: Dynamic desktop actions use strict isolation layers.
- **Terminal Confirmation Gates**: Destructive actions (`rm -rf`, `dd`, etc.) and sensitive security scanning tools require explicit confirmation before execution.
- **Secret Isolation**: Configuration files containing sensitive tokens and TLS private keys are excluded from git tracking.

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
