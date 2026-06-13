"""Messaging bots — the chat-side mirror of the web app.

Each adapter (Telegram, Matrix) lets the family search and download from a chat client. A bot is
enabled when its credentials are present (via ``.env`` or the Settings page). Jobs it queues carry
``origin`` set to the bot name, so the web UI badges them with a phone icon.
"""
