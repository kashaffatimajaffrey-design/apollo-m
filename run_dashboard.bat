@echo off
REM Run the Streamlit dashboard FROM apollo-m so Streamlit finds .streamlit/secrets.toml
cd /d "%~dp0"
python -m streamlit run dashboard/app.py --server.headless true --server.port 8501 --browser.gatherUsageStats false
