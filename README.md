
# 🚀 ForzeOS
**A high-performance Linux-like desktop simulation environment built with Python 3.11 for Windows.**

LOGIN - admin
PASSWORD - Forze esp32

> [!WARNING]
> **ForzeOS is NOT for Linux.** It is specifically designed to create and simulate a Linux-style desktop workspace, terminal, and AI integration within a Windows environment.

---

## 🛠️ Installation & Setup
Follow these steps to get ForzeOS running on your system:

1. **Install Dependencies:**
   ```powershell
   pip install -r requirements.txt
   ```
2. **Note for Linux Users:** If you are testing specific modules on a Linux kernel, ensure you have Python 3 installed:
   ```bash
   sudo apt install python3
   ```
3. **External Requirements:** To use video and editor features, you must install **VLC Media Player** and **FFmpeg**.
   * **VLC Path Configuration:** Ensure your `VLC_PLUGIN_PATH` is correctly mapped in your config:
     `r"C:\Program Files\VideoLAN\VLC\plugins"`

4. **Launch the System:** Run the launcher to start the desktop space:
   ```powershell
   python forze_launcher.py
   ```

---

## 📂 Project Architecture
**Note:** All `.py` files must remain in the same root directory for the system to link correctly.

### 🧠 Core & System Modules
* **Kernel Simulation:** `ForzeOS System.py`, `forzeos_core.py`
* **AI & Hybrid Assistants:** `assistant_ai.py`, `assistant_ai_offline.py`, `hybrid_assistant.py` (Manages memory via `assistant_memory_large.json`)
* **Utilities:** `forze_audio_settings.py`, `forze_wikipedia.py`, `math_engine.py`, `forzeos_focus.py`
* **Web Integration:** `forzeos_pyqt_browser.py`, `forzeos_pywebview_process.py`

### ⚡ C++ Hybrid Integration
ForzeOS utilizes compiled C++ for high-performance window management:
* `forze_agressive_focus.cpp`: Handles window priority and "aggressive" focus management for a seamless experience.

### ⚙️ Configuration & Assets
* `forzeos_config.json`: Central configuration file for paths, AI settings, and UI tweaks.
* `forze_assets/`: Directory containing system icons and AI stabilization assets.

---

## ⌨️ Controls & Navigation
* **Toggle Focus:** `Control + Shift + M`
* **Navigation:** Use `Tab` to cycle through elements and `Esc` to exit or go back.

---

## 🤝 Contributing
ForzeOS is an evolving project. Feel free to fork, report issues, or submit pull requests!
```

---

### Why this is better:
* **Visual Hierarchy:** Uses headers and bullet points so people can scan it in 5 seconds.
* **Code Blocks:** Makes it easy to copy-paste the installation commands.
* **Clarity:** Specifically mentions the **C++ integration** which makes your project look much more advanced to other developers.



**One last tip:** Since you have that **C++** file (`forze_agressive_focus.cpp`), you might want to tell people if they need a specific compiler (like MinGW or MSVC) to run it, or if you've already included a compiled `.dll`. 

Would you like me to help you write a `requirements.txt` file based on the libraries you're using?
