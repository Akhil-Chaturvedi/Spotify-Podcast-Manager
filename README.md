# Spotify Podcast Manager
[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://www.gnu.org/licenses/gpl-3.0)

A web application designed to intelligently manage your Spotify podcast queue. It automatically curates a playlist with new episodes and batches from your backlog, sorted by duration, to create a seamless listening experience.

This tool solves the "podcast overload" problem by creating a smart, rotating playlist that prioritizes new content while helping you systematically work through your backlog of unplayed episodes.

**Live at** **[https://ebutuoy.pythonanywhere.com/](https://ebutuoy.pythonanywhere.com/)**

---

## Key Features
-   **Priority Inbox:** Automatically places episodes released since your last update at the top of your playlist.
-   **Batch by Duration:** Groups your entire backlog of unplayed episodes by their length and adds them one batch at a time, starting with the shortest.
-   **Smart Queue:** Combines new episodes and the next backlog batch into one playlist with a single click.
-   **Web Interface:** A simple web app that works on desktop and mobile. No command-line needed.
-   **Quick Setup:** The app can create a new private playlist for you, or you can use an existing one.
-   **Skip Short Episodes:** Configure a minimum duration to ignore short clips or trailers in your backlog.
-   **Real-Time Progress:** A live progress bar shows you exactly what the app is doing during a scan.

---

## How to Use the Live App
For users who just want to use the tool without setting anything up.

1.  **Visit the Website:** Go to **[https://ebutuoy.pythonanywhere.com/](https://ebutuoy.pythonanywhere.com/)**.
2.  **Log In:** Click "Login with Spotify" and authorize the app to view your library and manage your playlists.
3.  **First-Time Setup:**
    -   **Easiest Way:** Click **"Create a New Playlist & Run First Scan"**. The app will create a new private playlist in your Spotify account called "My Podcast Queue" and start the initial scan.
    -   **Advanced:** If you prefer to use an existing playlist, paste its Spotify link or ID and click "Save & Use Existing Playlist".
4.  **Update Your Queue:** Once set up, click **"Update My Podcast Queue"** whenever you want to refresh your playlist.
5.  **Listen on Spotify:** Open the "My Smart Podcast Queue" playlist in your Spotify app and enjoy!

---

## Flawless Self-Hosting Guide (PythonAnywhere)
For developers who want to run their own instance. These instructions are designed to work perfectly the first time on a free PythonAnywhere account.

### Step 1: Get Spotify API Credentials
1.  Go to the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard/) and log in.
2.  Click **"Create App"**. Give it a name and description.
3.  You will see your **Client ID** and **Client Secret**. Keep these safe for Step 4.
4.  Click **"Edit Settings"**. In the **Redirect URIs** box, you *must* add the callback URL for your app. It will be: `https://your-username.pythonanywhere.com/callback` (replace `your-username`).
5.  Click **"Save"**.

### Step 2: Get the Code
1.  Log in to [PythonAnywhere](https://www.pythonanywhere.com/) and open a new **Bash Console**.
2.  Clone this repository:
    ```bash
    git clone https://github.com/Akhil-Chaturvedi/Spotify-Podcast-Manager.git
    ```

### Step 3: Configure the PythonAnywhere Web App
1.  Go to the **"Web"** tab on the PythonAnywhere dashboard.
2.  Click **"Add a new web app"**.
3.  Choose the **Flask** framework and a Python version (e.g., **Python 3.10**).
4.  Accept the default file path it suggests.
5.  On the main "Web" tab for your new app, configure the following:
    -   **Source code:** `/home/your-username/Spotify-Podcast-Manager`
    -   **Virtualenv:** `/home/your-username/Spotify-Podcast-Manager/venv`
    -   **Static files:** Add one mapping:
        -   **URL:** `/static`
        -   **Directory:** `/home/your-username/Spotify-Podcast-Manager/static`

### Step 4: The WSGI Configuration File (The Most Important Step)
This is where you will securely store your API keys and settings.

1.  On the **Web** tab, click the link to your **WSGI configuration file**. It will be something like `/var/www/your-username_pythonanywhere_com_wsgi.py`.
2.  **Delete everything** inside that file.
3.  **Copy and paste the template below** into the empty file.

    ```python
    import sys
    import os

    os.environ['SPOTIPY_CLIENT_ID'] = '<YOUR_SPOTIFY_CLIENT_ID>'
    os.environ['SPOTIPY_CLIENT_SECRET'] = '<YOUR_SPOTIFY_CLIENT_SECRET>'
    os.environ['SECRET_KEY'] = '<A_LONG_RANDOM_STRING_FOR_SESSIONS>'
    os.environ['REDIRECT_URI'] = 'https://<YOUR-USERNAME>.pythonanywhere.com/callback'

    path = '/home/<YOUR-USERNAME>/Spotify-Podcast-Manager'
    if path not in sys.path:
        sys.path.insert(0, path)

    from app import app as application
    ```

4.  **IMPORTANT: Replace all the placeholder values** (`<...>`):
    -   `<YOUR_SPOTIFY_CLIENT_ID>`: Your Client ID from the Spotify Dashboard.
    -   `<YOUR_SPOTIFY_CLIENT_SECRET>`: Your Client Secret.
    -   `<A_LONG_RANDOM_STRING_FOR_SESSIONS>`: You can generate one by running `python -c 'import uuid; print(uuid.uuid4().hex)'` in a console.
    -   `<YOUR-USERNAME>`: Your PythonAnywhere username (in both places).

5.  **Save the file.**

> **Why do we do it this way?** The WSGI file is specific to your deployment and is never (and should never be) pushed to GitHub. This keeps your secret keys safe and your repository clean.

### Step 5: Install Packages
1.  Go back to your **Bash Console**.
2.  Set up and activate the virtual environment you pointed to in Step 3:
    ```bash
    # Navigate into the project folder
    cd ~/Spotify-Podcast-Manager

    # Create the virtual environment
    python3.10 -m venv venv

    # Activate it
    source ven.v/bin/activate

    # Install the required packages
    pip install -r requirements.txt
    ```

### Step 6: Reload and Launch!
1.  Go back to the **"Web"** tab.
2.  Click the big green **"Reload your-username.pythonanywhere.com"** button.
3.  Visit your site. It will now be live and fully configured.

---

## Technology Stack
-   **Backend:** Python, Flask
-   **Spotify API Wrapper:** Spotipy
-   **Frontend:** HTML, CSS, Vanilla JavaScript
-   **Hosting:** PythonAnywhere

## License
This project is licensed under the **GNU General Public License v3.0**. See the [LICENSE](LICENSE) file for details.
