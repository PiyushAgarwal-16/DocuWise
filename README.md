# DocuWise

DocuWise is a high-performance, modern, locally-run desktop document manager. It leverages cutting-edge AI (NVIDIA NIM and Google Gemini) to extract, analyze, and automatically organize your documents, finding duplicates and highlighting key files so you can save time and storage space.

Recently rebuilt with a blazing-fast **React + Tauri** architecture, DocuWise offers a sleek, responsive native desktop experience backed by a robust Python FastAPI engine and local SQLite database.

## ✨ Features
- **AI-Powered Analysis**: Automatically categorizes files, generates subjects, summaries, and determines importance.
- **Advanced Duplicate Detection**: Uses local ML models (`SentenceTransformers`) to compute content embeddings, finding identical and semantically similar documents to help you save space.
- **Local-First Privacy**: Your SQLite database and file embeddings are stored entirely locally on your machine.
- **Modern Desktop UI**: A beautiful, fluid interface built with React, TailwindCSS, and Shadcn UI, deployed natively via Tauri.
- **Resilient Pipeline**: Gracefully handles massive datasets, missing files, errors, and API rate limits.

---

## 🛠️ Prerequisites

Before you begin, ensure you have the following installed on your system:
- **Python 3.10+** (Required for the backend API and document processing pipeline)
- **Node.js 18+** (Required for the frontend React application)
- **Rust & Cargo** (Required to compile the Tauri native desktop application)
- **Git**

You will also need API keys for the AI providers:
- **NVIDIA NIM API Key** (Primary): Obtain from [build.nvidia.com](https://build.nvidia.com/)
- **Google Gemini API Key** (Secondary fallback): Obtain from [aistudio.google.com](https://aistudio.google.com/)

---

## 🚀 Setup Instructions

### 1. Clone the Repository
Open your terminal or command prompt and run:
```bash
git clone https://github.com/yourusername/DocuWise.git
cd DocuWise
```

### 2. Set Up the Python Backend
The Python backend handles the database, AI extraction, and machine learning models.

**Windows:**
```cmd
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

**macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure API Keys
Your API keys must **NOT** be placed directly inside the code to prevent them from being leaked.

1. In the root directory, locate the `.env.example` file.
2. **Create a new file** named `.env`.
3. Add your actual API keys to the `.env` file like this:
```ini
NVIDIA_API_KEY=your_actual_nvidia_key_here
GEMINI_API_KEY=your_actual_gemini_key_here
```

### 4. Set Up the React/Tauri Frontend
Navigate to the `frontend` directory and install the Node dependencies:
```bash
cd frontend
npm install
cd ..
```

---

## 🖥️ Running the Application

### On Windows
We have provided a convenient batch script that automatically manages the backend and frontend processes for you.

Simply run:
```powershell
.\dev.bat
```
*(This script will launch the FastAPI server in the background, start the Tauri desktop app, and automatically clean up the server when you close the app.)*

### On macOS / Linux
You will need to run the backend and the frontend simultaneously in two separate terminal windows.

**Terminal 1 (Backend):**
```bash
source venv/bin/activate
python api_server.py
```

**Terminal 2 (Frontend):**
```bash
cd frontend
npm run tauri dev
```

---

## 🧹 Utilities

### Resetting the Database
If you are testing the application and want to wipe your `docuwise.db` clean to rescan the exact same documents, we've provided a safe reset script.

**On Windows:**
Press `Ctrl+C` in your terminal to stop any running processes, then run:
```powershell
.\reset_db.bat
```
This will automatically wipe the database so the system can generate a fresh one on your next boot.

---

## 📁 Project Structure

- `api_server.py` - The FastAPI bridge that connects the UI to the Python engine.
- `dev.bat` / `reset_db.bat` - Process management utilities for Windows.
- `core/` - The Python backend engine.
  - `pipeline.py` - Orchestrates the scan, extract, analyze, and embed stages.
  - `analyzer.py` - Calls NVIDIA NIM / Gemini to classify text.
  - `embedder.py` - Generates vector embeddings using local HuggingFace ML models.
  - `database.py` - Local SQLite database operations.
- `frontend/` - The React + Tauri user interface.
  - `src-tauri/` - Rust configuration for the native desktop window.
  - `src/pages/` - Core UI views (Dashboard, Documents, Duplicates, etc).
  - `src/services/api.ts` - TypeScript HTTP client to communicate with FastAPI.
- `storage/` - Automatically created directory storing your local `docuwise.db`.
