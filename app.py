# ==============================================================================
#      Smart Batch Playlist Manager for Spotify
## ==============================================================================

import os
import re
import json
import uuid
import threading
from collections import defaultdict
from datetime import datetime, timezone

import spotipy
from flask import Flask, Response, redirect, render_template, request, session, url_for, jsonify
from spotipy.oauth2 import SpotifyOAuth

# --- CONFIGURATION ---
# Best practice to load these from environment variables in a real deployment
SPOTIPY_CLIENT_ID = os.environ.get('SPOTIPY_CLIENT_ID', 'YOUR_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.environ.get('SPOTIPY_CLIENT_SECRET', 'YOUR_CLIENT_SECRET')
# This must match the Redirect URI in your Spotify Developer Dashboard
REDIRECT_URI = "http://127.0.0.1:5000/callback" 
SECRET_KEY = os.environ.get('SECRET_KEY', 'a_strong_random_secret_key')
SCOPE = "user-library-read playlist-modify-public playlist-modify-private"
BLOCKLIST_KEYWORDS = ['trailer', 'bonus:', 'replay:', 'announcement', 'preview']

# --- APP SETUP ---
STATE_FOLDER = 'user_states'
if not os.path.exists(STATE_FOLDER):
    os.makedirs(STATE_FOLDER)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
TOKEN_INFO_KEY = 'spotify_token_info'

# In-memory storage for background job status.
# In a multi-worker setup, this would need to be moved to a shared store like Redis.
background_jobs = {}

# ==============================================================================
# --- SPOTIFY & STATE HELPERS ---
# ==============================================================================

def get_spotify_client():
    """Creates a Spotipy client from the user's session token."""
    token_info = session.get(TOKEN_INFO_KEY)
    if not token_info:
        return None
        
    # Auto-refresh token if expired
    if SpotifyOAuth.is_token_expired(token_info):
        # The cache_path here is a temporary location for the oauth object
        # The actual token is stored and re-saved in the user's JSON file
        user_id = session.get('user_id')
        cache_path = os.path.join(STATE_FOLDER, f"{user_id}_token.json")
        auth_manager = SpotifyOAuth(
            client_id=SPOTIPY_CLIENT_ID,
            client_secret=SPOTIPY_CLIENT_SECRET,
            redirect_uri=REDIRECT_URI,
            scope=SCOPE,
            cache_path=cache_path
        )
        token_info = auth_manager.refresh_access_token(token_info['refresh_token'])
        # Re-save the refreshed token
        _save_token(user_id, token_info)
        session[TOKEN_INFO_KEY] = token_info

    return spotipy.Spotify(auth=token_info['access_token'])

def _get_user_state_path(user_id):
    """Returns the standardized path for a user's state file."""
    return os.path.join(STATE_FOLDER, f"{user_id}.json")

def _load_state(user_id):
    """Loads a user's state from their JSON file."""
    state_file = _get_user_state_path(user_id)
    if not os.path.exists(state_file):
        return {}
    try:
        with open(state_file, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {} # Return empty state on file corruption

def _save_state(user_id, state):
    """Saves a user's state to their JSON file."""
    state_file = _get_user_state_path(user_id)
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=4)
        
def _get_token_path(user_id):
    return os.path.join(STATE_FOLDER, f"{user_id}_token.json")

def _load_token(user_id):
    try:
        with open(_get_token_path(user_id), 'r') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError):
        return None
        
def _save_token(user_id, token_info):
    with open(_get_token_path(user_id), 'w') as f:
        json.dump(token_info, f)

def extract_item_id(text):
    """Extracts a Spotify ID from a URL or URI."""
    match = re.search(r'(playlist|show|episode)/([a-zA-Z0-9]+)', text)
    if match:
        return match.group(2)
    if re.match(r'^[a-zA-Z0-9]+$', text.strip()): # Handle raw ID
        return text.strip()
    return None

# ==============================================================================
# --- CORE BACKGROUND LOGIC ---
# ==============================================================================

def run_update_task(user_id, playlist_id):
    """The main background task orchestrator."""
    sp = get_spotify_client()
    state = _load_state(user_id)
    
    # Initialize state for new users
    if 'last_update_ts' not in state:
        state['last_update_ts'] = '1970-01-01T00:00:00Z'
    if 'completed_shows' not in state:
        state['completed_shows'] = {}
    if 'show_progress' not in state: # CRITICAL: For efficient scanning
        state['show_progress'] = {}

    last_update_dt = datetime.fromisoformat(state['last_update_ts'].replace('Z', '+00:00'))

    try:
        # 1. Fetch all saved shows
        saved_shows = _fetch_all_shows(sp, user_id)
        if not saved_shows:
            _update_job_status(user_id, "No saved shows found.", 1, 1)
            return

        # 2. Scan shows for new and backlog episodes
        priority_eps, backlog_eps, state = _scan_all_shows(sp, user_id, saved_shows, state, last_update_dt)

        # 3. Determine the next batch from the backlog
        last_minute = state.get('current_minute', -1)
        next_batch, next_minute = _determine_next_backlog_batch(backlog_eps, last_minute)

        # 4. Combine and update the playlist
        uris_to_add = [ep['uri'] for ep in sorted(priority_eps, key=lambda x: x['duration_ms'])]
        uris_to_add.extend([ep['uri'] for ep in next_batch])

        _update_job_status(user_id, f"Updating playlist with {len(uris_to_add)} episodes...", len(saved_shows), len(saved_shows))
        
        if uris_to_add:
            sp.playlist_replace_items(playlist_id, [])
            for i in range(0, len(uris_to_add), 100):
                sp.playlist_add_items(playlist_id, uris_to_add[i:i+100])
        
        # 5. Save final state
        state['current_minute'] = next_minute
        state['last_batch_info'] = {
            'priority_count': len(priority_eps),
            'backlog_minute': next_minute,
            'backlog_count': len(next_batch),
            'total_count': len(uris_to_add),
            'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        }
        state['last_update_ts'] = datetime.now(timezone.utc).isoformat()
        _save_state(user_id, state)
        _update_job_status(user_id, "Update complete!", 100, 100, is_done=True)

    except Exception as e:
        app.logger.error(f"Error in background task for {user_id}: {e}")
        _update_job_status(user_id, f"An error occurred: {e}", 1, 1, is_error=True)
    finally:
        # Job state is cleared by the front-end after completion/error
        pass

def _fetch_all_shows(sp, user_id):
    """Fetches all of a user's saved podcast shows from Spotify."""
    _update_job_status(user_id, "Fetching saved shows...", 0, 1)
    saved_shows = []
    results = sp.current_user_saved_shows(limit=50)
    while results:
        saved_shows.extend(item['show'] for item in results['items'])
        results = sp.next(results) if results['next'] else None
    return saved_shows

def _scan_all_shows(sp, user_id, shows, state, last_update_dt):
    """
    Scans all shows for episodes. Uses the 'show_progress' state to be efficient.
    """
    priority_episodes = []
    backlog_episodes = []
    
    total_shows = len(shows)
    for i, show in enumerate(shows):
        # Skip shows that are already marked as completed
        if show['id'] in state['completed_shows']:
            _update_job_status(user_id, f"({i+1}/{total_shows}) Skipping completed: {show['name']}", i, total_shows)
            continue

        _update_job_status(user_id, f"({i+1}/{total_shows}) Scanning: {show['name']}", i, total_shows)
        
        newly_found_eps, all_unplayed_found = _process_episodes_for_show(sp, show, state)

        if all_unplayed_found == 0 and show['total_episodes'] > 0:
            state['completed_shows'][show['id']] = show['name']
        
        for episode in newly_found_eps:
            release_dt = datetime.fromisoformat(episode['release_date'].replace('Z', '+00:00'))
            if release_dt > last_update_dt:
                priority_episodes.append(episode)
            else:
                backlog_episodes.append(episode)

        # Intermediary save in case of very large libraries on first scan
        if i % 10 == 0:
            _save_state(user_id, state)

    return priority_episodes, backlog_episodes, state


def _process_episodes_for_show(sp, show, state):
    """
    Gets all *new* unplayed episodes for a single show efficiently.
    Stops scanning when it finds an episode it has already processed.
    """
    last_seen_episode_id = state.get('show_progress', {}).get(show['id'])
    newly_found_episodes = []
    unplayed_count_in_show = 0
    
    ep_results = sp.show_episodes(show['id'], limit=50)
    
    while ep_results:
        should_break = False
        for episode in ep_results['items']:
            if episode['id'] == last_seen_episode_id:
                should_break = True
                break

            if episode.get('resume_point', {}).get('fully_played', False):
                continue
            
            if any(keyword in episode['name'].lower() for keyword in BLOCKLIST_KEYWORDS):
                continue
            
            unplayed_count_in_show += 1
            newly_found_episodes.append(episode)
            
        if should_break:
            break
            
        ep_results = sp.next(ep_results) if ep_results['next'] else None

    # After scanning, set the new "high water mark" to the latest episode
    if newly_found_episodes:
        state['show_progress'][show['id']] = newly_found_episodes[0]['id']

    return newly_found_episodes, unplayed_count_in_show


def _determine_next_backlog_batch(backlog_episodes, last_minute_processed):
    """
    Groups backlog episodes by duration and finds the next batch to add.
    """
    if not backlog_episodes:
        return [], -1

    backlog_by_minute = defaultdict(list)
    for ep in backlog_episodes:
        minute = ep['duration_ms'] // 60000
        backlog_by_minute[minute].append(ep)
    
    sorted_minutes = sorted(backlog_by_minute.keys())
    
    next_minute_to_add = -1
    for minute in sorted_minutes:
        if minute > last_minute_processed:
            next_minute_to_add = minute
            break
    
    # If we've processed all lengths, loop back to the beginning
    if next_minute_to_add == -1:
        next_minute_to_add = sorted_minutes[0]

    return backlog_by_minute.get(next_minute_to_add, []), next_minute_to_add

def _update_job_status(user_id, message, progress, total, is_done=False, is_error=False):
    """Updates the shared job status dictionary."""
    background_jobs[user_id] = {
        "message": message,
        "progress": progress,
        "total": total,
        "is_done": is_done,
        "is_error": is_error,
    }

# ==============================================================================
# --- WEB INTERFACE (FLASK ROUTES) ---
# ==============================================================================

@app.route('/')
def index():
    if not session.get(TOKEN_INFO_KEY):
        return render_template('index.html')

    sp = get_spotify_client()
    if not sp:
        return redirect('/logout') # Token invalid, force logout

    user_info = sp.current_user()
    session['user_id'] = user_info['id']
    user_id = user_info['id']

    state = _load_state(user_id)
    return render_template('index.html', user=user_info, state=state, is_running=(user_id in background_jobs))

@app.route('/login')
def login():
    # Use a file-based cache for the auth flow itself
    cache_path = os.path.join(STATE_FOLDER, f"cache-{uuid.uuid4()}")
    session['auth_cache_path'] = cache_path
    auth_manager = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        show_dialog=True,
        cache_path=cache_path
    )
    return redirect(auth_manager.get_authorize_url())

@app.route('/callback')
def callback():
    cache_path = session.get('auth_cache_path')
    auth_manager = SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE,
        cache_path=cache_path
    )
    token_info = auth_manager.get_access_token(request.args.get('code'), as_dict=True)
    
    # Get user ID to permanently save their token
    user_id = spotipy.Spotify(auth=token_info['access_token']).current_user()['id']
    session['user_id'] = user_id
    session[TOKEN_INFO_KEY] = token_info
    _save_token(user_id, token_info)

    if os.path.exists(cache_path): # Clean up temporary cache file
        os.remove(cache_path)

    return redirect('/')

@app.route('/logout')
def logout():
    user_id = session.get('user_id')
    if user_id:
        token_path = _get_token_path(user_id)
        if os.path.exists(token_path):
            os.remove(token_path)
        # We don't remove the state file, so users don't lose their progress
    session.clear()
    return redirect('/')

@app.route('/start-update', methods=['POST'])
def start_update():
    user_id = session.get('user_id')
    if not user_id or user_id in background_jobs:
        return redirect('/')
    
    state = _load_state(user_id)
    playlist_id = state.get('playlist_id')

    if not playlist_id:
        return "Error: Playlist ID not set.", 400

    _update_job_status(user_id, "Starting update...", 0, 0)
    
    thread = threading.Thread(target=run_update_task, args=(user_id, playlist_id))
    thread.daemon = True
    thread.start()
    
    return redirect('/')

@app.route('/create-playlist-and-scan', methods=['POST'])
def create_playlist_and_scan():
    user_id = session.get('user_id')
    if not user_id or user_id in background_jobs:
        return redirect('/')

    sp = get_spotify_client()
    user_info = sp.current_user()
    
    playlist_name = "My Smart Podcast Queue"
    playlist = sp.user_playlist_create(
        user=user_info['id'], 
        name=playlist_name, 
        public=False, 
        description="Auto-generated by the Smart Podcast Manager."
    )
    
    state = _load_state(user_id)
    state['playlist_id'] = playlist['id']
    _save_state(user_id, state)
    
    return start_update()

@app.route('/set-playlist', methods=['POST'])
def set_playlist():
    user_id = session.get('user_id')
    if not user_id:
        return redirect('/')
    
    playlist_input = request.form.get('playlist_input', '')
    playlist_id = extract_item_id(playlist_input)

    if not playlist_id:
        # Here you might want to add a flash message for the user
        return redirect('/')

    state = _load_state(user_id)
    state['playlist_id'] = playlist_id
    # Reset progress when changing playlist
    state['current_minute'] = -1
    _save_state(user_id, state)

    return redirect('/')
    
@app.route('/status')
def status():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"error": "Not logged in"}), 401
    
    job = background_jobs.get(user_id)
    if not job:
        return jsonify({"status": "idle"})
    
    if job.get('is_done') or job.get('is_error'):
        # Once the client has seen the final state, clear it.
        background_jobs.pop(user_id, None)

    return jsonify(job)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
