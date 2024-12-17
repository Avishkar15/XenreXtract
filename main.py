from flask import Flask, render_template, request, redirect, session, flash
import spotipy
from spotipy import oauth2
from spotipy.oauth2 import SpotifyOAuth
from spotipy.cache_handler import CacheFileHandler
from collections import Counter
import os
import binascii
from datetime import datetime
import redis
import shutil

app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_COOKIE_SECURE'] = True  # Set to False if not using HTTPS
app.config['SESSION_REDIS'] = redis.from_url(os.environ['REDIS_URL'])
redis_connection = app.config['SESSION_REDIS']

SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')
SPOTIPY_SCOPE = 'user-library-read playlist-modify-public user-top-read'
cache_dir = os.path.join(app.instance_path, 'spotify_cache.cache')



@app.before_request
def before_request():
    delete_cache_if_not_logged_out()

def delete_cache_if_not_logged_out():
    # Check if the user is logged in and if the session has expired
    if 'token_info' in session and 'token_expiry' in session:
        token_expiry = session['token_expiry']
        if token_expiry and token_expiry < datetime.utcnow():
            # Clean up the cache if the session has expired
            if os.path.exists(cache_dir):
                os.remove(cache_dir)

@app.route('/')
def home():
    session.pop("token_info", None)
    return render_template('app/home.html', page='home')


@app.route('/login')
def login():
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=SPOTIPY_SCOPE,
    cache_handler=cache_handler,
    show_dialog=True
    )
    auth_url = auth_manager.get_authorize_url()
    return redirect(auth_url)

@app.route('/logout')
def logout():
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_dir)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    return render_template('app/home.html')

    

@app.route('/callback')
def callback():
    try:
        cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
        auth_manager = spotipy.oauth2.SpotifyOAuth(
        client_id=SPOTIPY_CLIENT_ID,
        client_secret=SPOTIPY_CLIENT_SECRET,
        redirect_uri=SPOTIPY_REDIRECT_URI,
        scope=SPOTIPY_SCOPE,
        cache_handler=cache_handler,
        show_dialog=True
        )

        code = request.args.get('code')
        token_info = auth_manager.get_access_token(code)
        session['token_info'] = token_info
        access_token = token_info['access_token']
        sp = spotipy.Spotify(auth_manager=auth_manager)

        top_genres = topgenres()
        top_songs = get_top_songs()
        user_info = sp.current_user()
        user_name = user_info['display_name']
        return render_template('app/genre.html', context=top_genres, user_name=user_name, songs=top_songs)
    except Exception as e:
        flash("You need to logged in!","danger")
        return render_template('app/home.html', page='home')

def create_or_get_playlist(user_id, playlist_name, playlist_description):
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)

    sp = spotipy.Spotify(auth_manager=auth_manager)

    playlists = sp.current_user_playlists(limit=20, offset=0)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            return playlist
    return sp.user_playlist_create(user_id, playlist_name, public=True, description=playlist_description)

def fetch_liked_tracks(sp, max_tracks=200):
    limit = 50
    track_ids = []
    for offset in range(0, max_tracks, limit):
        liked_songs = sp.current_user_saved_tracks(limit=limit, offset=offset)
        track_ids.extend([track["track"]["id"] for track in liked_songs["items"]])
        if not liked_songs["items"]:
            break
    return track_ids


def fetch_artists_genres(sp, track_ids, genre):
    batch_size = 50
    genre_tracks = []
    for i in range(0, len(track_ids), batch_size):
        batch = track_ids[i:i + batch_size]
        tracks_info = sp.tracks(batch)
        for track in tracks_info['tracks']:
            for artist in track['artists']:
                artist_info = sp.artist(artist['id'])
                if genre.lower() in [g.lower() for g in artist_info["genres"]]:
                    genre_tracks.append(track['id'])
    return genre_tracks


@app.route('/generate_playlist/', methods=['POST'])
def generate_playlist():
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    user_id = sp.current_user()['id']
    genre = request.form['button_text']

    # Fetch liked songs efficiently
    track_ids = fetch_liked_tracks(sp, max_tracks=200)

    # Retrieve genre-specific tracks in fewer API calls
    genre_tracks = fetch_artists_genres(sp, track_ids, genre)

    # Create or fetch playlist
    playlist_name = f"Liked Songs - {genre}"
    playlist_description = f"Playlist of liked songs in the {genre} genre"
    playlist = create_or_get_playlist(user_id, playlist_name, playlist_description)

    # Add tracks to playlist
    existing_tracks = {item['track']['id'] for item in sp.playlist_items(playlist['id'], fields="items(track.id)")['items']}
    tracks_to_add = [track for track in genre_tracks if track not in existing_tracks]

    if tracks_to_add:
        for i in range(0, len(tracks_to_add), 100):
            sp.playlist_add_items(playlist['id'], tracks_to_add[i:i + 100])

    return render_template('app/playlist.html', playlist_name=playlist_name)

@app.route('/similar_songs/', methods=['POST'])
def similar_songs():
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)
    
    
    sp = spotipy.Spotify(auth_manager=auth_manager)

    current_user = sp.current_user()
    user_id = current_user['id']
    seed_track_id =request.form['button_text']

    track = sp.track(seed_track_id)
    track_name = track['name']
    artist_name = track['artists'][0]['name']
    
    recommendations = sp.recommendations(seed_tracks=[seed_track_id], seed_genres=None, seed_artists=None,
                                         limit=20, country='US')
    
    track_uris = [track['uri'] for track in recommendations['tracks']]
    
    playlist_name = "Songs like [{} - {}]".format(track_name,artist_name)
    playlist_description = "Playlist of songs similar to {} by {}".format(track_name,artist_name)
    playlist = create_or_get_playlist(user_id, playlist_name, playlist_description)
    
    existing_tracks = set()
    playlist_items = sp.playlist_items(playlist["id"], fields="items(track.id)", limit=100)
    for item in playlist_items["items"]:
        existing_tracks.add(item["track"]["id"])

    tracks_to_add = [track_id for track_id in track_uris if track_id not in existing_tracks]
    sp.playlist_add_items(playlist["id"], tracks_to_add)

    return render_template('app/playlist.html',playlist_name=playlist_name)

def topgenres():
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)

    
    sp = spotipy.Spotify(auth_manager=auth_manager)

    current_user = sp.current_user()
    user_id = current_user['id']

    top_artists = sp.current_user_top_artists(limit=10, time_range="medium_term")

    # Extract the genres from the top artists
    genres = []
    for artist in top_artists['items']:
        genres.extend(artist['genres'])

    # Get the top 6 genres
    top_genres = [genre for genre, _ in Counter(genres).most_common(8)]
    
    #for genre, count in top_genres:
        #print(f"- {genre} ({count} occurrences)")

    return top_genres

def get_top_songs(limit=12):
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)

    
    sp = spotipy.Spotify(auth_manager=auth_manager)

    # Get the user's top tracks
    top_tracks = sp.current_user_top_tracks(limit=limit, time_range='short_term')  # 'short_term', 'medium_term', 'long_term'

    # Extract the track names and IDs
    track_names = [track['name'] for track in top_tracks['items']]
    artist_names = [track['artists'][0]['name'] for track in top_tracks['items']]
    track_ids = [track['id'] for track in top_tracks['items']]

    tracks= zip(track_names, artist_names, track_ids)

    return tracks

@app.route('/top_artist', methods=['POST'])
def top_artist():
    cache_handler = spotipy.cache_handler.FlaskSessionCacheHandler(session)
    auth_manager = spotipy.oauth2.SpotifyOAuth(cache_handler=cache_handler)
    sp = spotipy.Spotify(auth_manager=auth_manager)

    user_info = sp.current_user()
    user_name = user_info['display_name']
    try:
        
        artist_name = request.form['search']
        results = sp.search(q='artist:' + artist_name, type='artist')

        artist_id = results['artists']['items'][0]['id']
        artist = results['artists']['items'][0]
        image_url = artist['images'][0]['url']

        # Get the current user's top tracks
        top_tracks = sp.current_user_top_tracks(limit=1000, time_range='medium_term')

        # Filter the tracks for the specified artist
        artist_top_tracks = [track for track in top_tracks['items'] if artist_id in [artist['id'] for artist in track['artists']]]

        # Sort the tracks by popularity
        sorted_tracks = sorted(artist_top_tracks, key=lambda track: track['popularity'], reverse=True)

        # Extract track names
        track_names = [track['name'] for track in sorted_tracks[:10]]

        if not track_names:
            flash("You have no tracks by this artist in your top songs!","danger")
            return render_template('app/topartist.html', artist=artist_name, tracks=track_names, image_url=image_url)
        else:
            return render_template('app/topartist.html', artist=artist_name, tracks=track_names, image_url=image_url)
    
    except IndexError:
        flash("No such artist found!","danger")
        top_genres = topgenres()
        top_songs = get_top_songs()
        user_info = sp.current_user()
        user_name = user_info['display_name']
        return render_template('app/genre.html', context=top_genres, user_name=user_name, songs=top_songs)

    
    


if __name__ == '__main__':
    app.run(debug=True)

