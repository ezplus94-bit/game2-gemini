# Deploying Modinion online (Render)

(Modinion is the new name of the game. The Python package and the start command still say `dominion`, so
nothing in the Render setup below changes.)

This is a **new, separate** Render service from your Number String demo. Your
existing service is not affected.

## 1. Put the code on GitHub
Upload the project to its own repository (drag and drop works: see the earlier
instructions). The repo root must contain `pyproject.toml`, `src/`, `tests/`,
`docs/` and `README.md`. Do **not** upload `node_modules` (only exists if you
ran the optional browser tests).

**Keep the folders.** The project has six different files called `__init__.py`
(`src/dominion/`, and one each in `cards/`, `engine/`, `ai/`, `ui/`, `web/`). If an upload
flattens the folders, or one copy overwrites another, the site fails to start with an
`ImportError` (for example `No module named 'dominion.base'`). Unzip the project and drag the
**folders themselves** (`src`, `tests`, `docs`, `tools`) into GitHub's upload page, not the files
inside them. To check a copy, open `src/dominion/__init__.py` on GitHub: the first import line must be
`from .cards.base import CardDef, ...` (the one in `src/dominion/cards/__init__.py` starts with
`from .base import ...`). A test in the suite (`test_top_level_package_exports_...`) checks all six.

## 2. Create the Render service
1. In Render: **New +** -> **Web Service** -> connect your GitHub account -> pick the `dominion` repo.
2. Fill in:

| Setting | Value |
|---|---|
| Name | `dominion` (any name; it becomes part of your URL) |
| Branch | `main` |
| Runtime / Language | **Python 3** |
| Build Command | `pip install ".[web]"` |
| Start Command | `uvicorn dominion.web.server:app --host 0.0.0.0 --port $PORT` |
| Instance Type | Free is fine to try |

3. Under **Advanced**, set **Health Check Path** to `/healthz` (optional but recommended).
4. Click **Create Web Service**. When the log says the service is live, open the
   URL Render shows (like `https://dominion-xxxx.onrender.com`).

**If the log says `uvicorn: command not found` (or `python: command not found`)**
even though the build succeeded, Render is not putting the installed Python
environment on the search path. This happened on our deployment and was fixed
by changing the Start Command to the full path:

```
/opt/render/project/src/.venv/bin/uvicorn dominion.web.server:app --host 0.0.0.0 --port $PORT
```

(This path comes from Render's own logs and could change if Render changes its
layout; if it ever stops working, look at the first lines of a failed log for the
`.venv` location.)

If the build complains about the Python version, add an environment variable
`PYTHON_VERSION` with a 3.10+ value your Render account supports (for example `3.12.3`).

## 3. Play
1. Open the URL, enter your name, click **Create room**.
2. Share the 4-letter code (or **Copy invite link**) with friends. They open the
   site and click **Join room**.
3. Optionally **Add bot** (Big Money bots) and tick the Kingdom cards you want.
4. Host clicks **Start game**.

Everyone's tab remembers its seat, so refreshing or a brief connection drop
rejoins automatically. Each browser *tab* is its own player (handy for testing
alone: open two tabs).

## 4. Updating
Change files on GitHub (or upload new ones) and commit. Render redeploys
automatically. A redeploy restarts the server, which **ends all games in
progress** (state is in memory).

## 5. Things to know
* **Run one instance.** Rooms live in the server's memory. Do not scale to
  multiple instances or add `--workers`.
* **Free tier sleeps** after a period without traffic; the first visit wakes it
  (can take a while). Open the site a minute before game night. Any sleep or
  restart clears rooms; a player whose room vanished lands back on the home screen.
* Limits: 4 players per room (bots count), 100 rooms at once, idle empty rooms
  are deleted after an hour. Render's free-tier terms change, so check their
  current pricing page.
* Anyone with the URL can create rooms. For wider public use, add rate limits
  and accounts later.

## 6. Run it on your own computer
```bash
pip install -e ".[dev]"
dominion-web                      # then open http://localhost:8000
# or: uvicorn dominion.web.server:app --reload
```
Other devices on your network can use `http://<your-computer-IP>:8000`.
Set `DOMINION_BOT_DELAY=0.1` for faster bots.
