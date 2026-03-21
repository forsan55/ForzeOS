"""
Helper process to run pywebview on its own main thread.
Usage: python forzeos_pywebview_process.py "<title>" "<url>"
This script is intentionally minimal and runs pywebview.start() on the process main thread.
"""
import sys
import argparse

def main():
    parser = argparse.ArgumentParser(description='ForzeOS pywebview helper')
    parser.add_argument('title', nargs='?', default='ForzeOS Browser')
    parser.add_argument('url', nargs='?', default='https://www.google.com')
    args = parser.parse_args()

    try:
        import webview
    except Exception as e:
        print("pywebview import failed:", e)
        sys.exit(2)

    title = args.title
    url = args.url

    try:
        webview.create_window(title, url)
        webview.start()
    except Exception as e:
        # Ensure any exception is visible to the parent process
        print('pywebview runtime error:', e)
        sys.exit(3)

if __name__ == '__main__':
    main()
