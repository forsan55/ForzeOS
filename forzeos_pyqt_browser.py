"""
Helper process to run a Chromium-based browser using PyQt5 + QtWebEngine.
Usage: python forzeos_pyqt_browser.py "<title>" "<url-or-path>"
This runs a standalone Qt application with a QWebEngineView so it executes
on its own main thread and supports modern sites (YouTube, JS-heavy pages),
file inputs, and uploads.
"""
import sys
import os


def main():
    try:
        from PyQt5.QtWidgets import QApplication, QMainWindow
        from PyQt5.QtCore import QUrl
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except Exception as e:
        print('PyQt5 import failed:', e)
        sys.exit(2)

    title = sys.argv[1] if len(sys.argv) > 1 else 'ForzeOS Browser'
    url = sys.argv[2] if len(sys.argv) > 2 else 'https://www.google.com'

    app = QApplication(sys.argv)
    app.setApplicationName(title)

    window = QMainWindow()
    window.setWindowTitle(title)
    web = QWebEngineView(window)

    # Load local file if given file path
    if os.path.exists(url) and not url.startswith(('http://', 'https://', 'file://')):
        local_url = QUrl.fromLocalFile(os.path.abspath(url))
        web.load(local_url)
    else:
        # Ensure scheme for plain hostnames
        if not url.startswith(('http://', 'https://', 'file://')):
            url = 'https://' + url
        web.load(QUrl(url))

    window.setCentralWidget(web)
    window.resize(1100, 720)
    window.show()

    try:
        rc = app.exec_()
    except Exception as e:
        print('Qt runtime error:', e)
        rc = 3
    sys.exit(rc)

if __name__ == '__main__':
    main()
