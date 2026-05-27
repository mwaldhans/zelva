from .app import app

# WSGI entrypoint for Linux servers (gunicorn/uwsgi).
application = app
