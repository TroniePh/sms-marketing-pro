import os
import sys
import streamlit.web.cli as stcli

if __name__ == "__main__":
    if getattr(sys, "frozen", False):
        application_path = sys._MEIPASS
    else:
        application_path = os.path.dirname(os.path.abspath(__file__))

    app_path = os.path.join(application_path, "app.py")

    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
        "--server.headless=false",
        "--server.port=8501",
    ]

    sys.exit(stcli.main())
