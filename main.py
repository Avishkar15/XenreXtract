from fastapi import FastAPI, Request, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from spotipy import Spotify
from spotipy.oauth2 import SpotifyOAuth
import asyncio
import aiohttp

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# Spotify OAuth Setup
SPOTIPY_CLIENT_ID = "your_client_id"
SPOTIPY_CLIENT_SECRET = "your_client_secret"
SPOTIPY_REDIRECT_URI = "your_redirect_uri"
SPOTIPY_SCOPE = "user-library-read playlist-modify-public"

# Create Spotify Auth Manager
def get_spotify():
    auth_manager = SpotifyOAuth(client_id=SPOTIPY_CLIENT_ID,
                                client_secret=SPOTIPY_CLIENT_SECRET,
                                redirect_uri=SPOTIPY_REDIRECT_URI,
                                scope=SPOTIPY_SCOPE)
    return Spotify(auth_manager=auth_manager)

# Fetch liked songs asynchronously
async def fetch_liked_tracks(sp, max_tracks=200):
    track_ids = set()
    limit = 50
    offsets = [offset for offset in range(0, max_tracks, limit)]
    async with aiohttp.ClientSession() as session:
        tasks = [get_liked_batch(sp, offset, limit) for offset in offsets]
        results = await asyncio.gather(*tasks)
    for result in results:
        track_ids.update(result)
    return list(track_ids)

async def get_liked_batch(sp, offset, limit):
    liked_songs = sp.current_user_saved_tracks(limit=limit, offset=offset)
    return [track["track"]["id"] for track in liked_songs["items"]]

# Fetch genre-specific tracks asynchronously
async def fetch_genre_tracks(sp, track_ids, target_genre):
    genre_tracks = set()
    batch_size = 50
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i + batch_size]
        tracks_info = sp.tracks(batch)
        artist_ids = {artist['id'] for track in tracks_info['tracks'] for artist in track['artists']}
        artists_info = sp.artists(list(artist_ids))
        artist_genres = {artist['id']: artist['genres'] for artist in artists_info['artists']}

        for track in tracks_info['tracks']:
            for artist in track['artists']:
                if target_genre.lower() in [g.lower() for g in artist_genres.get(artist['id'], [])]:
                    genre_tracks.add(track['id'])
    return list(genre_tracks)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("home.html", {"request": request})

@app.post("/generate_playlist/")
async def generate_playlist(request: Request, button_text: str = Form(...)):
    sp = get_spotify()
    user_id = sp.current_user()["id"]

    # Fetch liked songs
    track_ids = await fetch_liked_tracks(sp, max_tracks=200)

    # Fetch genre-specific tracks
    genre_tracks = await fetch_genre_tracks(sp, track_ids, button_text)

    # Create or fetch playlist
    playlist_name = f"Liked Songs - {button_text}"
    playlist_description = f"Playlist of liked songs in the {button_text} genre"
    playlist = create_or_get_playlist(sp, user_id, playlist_name, playlist_description)

    # Avoid duplicates
    existing_tracks = {item["track"]["id"] for item in sp.playlist_items(playlist["id"], fields="items(track.id)")["items"]}
    tracks_to_add = [track for track in genre_tracks if track not in existing_tracks]

    # Add tracks in batches
    for i in range(0, len(tracks_to_add), 100):
        sp.playlist_add_items(playlist["id"], tracks_to_add[i:i + 100])

    return templates.TemplateResponse("playlist.html", {"request": request, "playlist_name": playlist_name})

def create_or_get_playlist(sp, user_id, playlist_name, playlist_description):
    playlists = sp.current_user_playlists(limit=20, offset=0)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            return playlist
    return sp.user_playlist_create(user_id, playlist_name, public=True, description=playlist_description)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
