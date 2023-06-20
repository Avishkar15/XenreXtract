from flask import Flask, render_template, request, redirect,session, flash
import spotipy
from spotipy import oauth2
from spotipy.oauth2 import SpotifyOAuth
from collections import Counter
import os
import binascii


app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(64)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['SESSION_COOKIE_SECURE'] = True  # Set to False if not using HTTPS


SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')
SPOTIPY_REDIRECT_URI = os.getenv('SPOTIPY_REDIRECT_URI')
SPOTIPY_SCOPE = 'user-library-read playlist-modify-public user-top-read'
cache_dir = os.path.join(app.instance_path, 'spotify_cache')
os.makedirs(cache_dir, exist_ok=True)
cache_path = os.path.join(cache_dir, binascii.hexlify(os.urandom(16)).decode() + '.cache')

oauth = SpotifyOAuth(
    client_id=SPOTIPY_CLIENT_ID,
    client_secret=SPOTIPY_CLIENT_SECRET,
    redirect_uri=SPOTIPY_REDIRECT_URI,
    scope=SPOTIPY_SCOPE,
    cache_path=cache_path
)

@app.route('/')
def home():
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_path)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    return render_template('app/home.html', page='home')

@app.route('/genre')
def genre():
    return render_template('app/genre.html', page='Your Top 8 Genres')

@app.route('/login')
def login():
    auth_url = oauth.get_authorize_url()
    return redirect(auth_url)

@app.route('/logout')
def logout():
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_path)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    return render_template('app/home.html')

    

@app.route('/callback')
def callback():
    code = request.args.get('code')
    token_info = oauth.get_access_token(code)
    session['token_info'] = token_info
    access_token = token_info['access_token']
    sp = spotipy.Spotify(auth=access_token)
    top_genres = topgenres()
    top_songs = get_top_songs()
    user_info = sp.current_user()
    user_name = user_info['display_name']
    return render_template('app/genre.html', context=top_genres, user_name=user_name, songs=top_songs)

def create_or_get_playlist(user_id, playlist_name, playlist_description):
    token_info = session['token_info']
    access_token = token_info['access_token']
    
    
    sp = spotipy.Spotify(auth=access_token)
    playlists = sp.current_user_playlists(limit=20, offset=0)
    for playlist in playlists['items']:
        if playlist['name'] == playlist_name:
            return playlist
    return sp.user_playlist_create(user_id, playlist_name, public=True, description=playlist_description)


@app.route('/generate_playlist/', methods=['POST'])
def generate_playlist():
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_path)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    if 'token_info' not in session:
        return redirect('/')

    token_info = session['token_info']
    access_token = token_info['access_token']
    
    
    sp = spotipy.Spotify(auth=access_token)
    current_user = sp.current_user()
    user_id = current_user['id']
    genre =request.form['button_text']
    # Get user's liked songs
    limit = 50  # Number of songs per request (maximum: 50)
    offset = 0
    track_ids = []

    while len(track_ids) < 200:
        liked_songs = sp.current_user_saved_tracks(limit=limit, offset=offset)
        if not liked_songs["items"]:
            break  # No more liked songs to retrieve
        track_ids.extend([track["track"]["id"] for track in liked_songs["items"]])
        offset += limit
    
    # Get genre-specific tracks
    #genre = "k-pop"
    genre_tracks = []
    for track_id in track_ids:
        track_info = sp.track(track_id)
        track_artists = track_info["artists"]
        for artist in track_artists:
            artist_id = artist["id"]
            artist_info = sp.artist(artist_id)
            if genre.lower() in [genre.lower() for genre in artist_info["genres"]]:
                genre_tracks.append(track_id)
    # Create a new playlist
    playlist_name = "Liked Songs - {}".format(genre)
    playlist_description = "Playlist of liked songs in the {} genre".format(genre)
    playlist = create_or_get_playlist(user_id, playlist_name, playlist_description)

    existing_tracks = set()
    playlist_items = sp.playlist_items(playlist["id"], fields="items(track.id)", limit=100)
    for item in playlist_items["items"]:
        existing_tracks.add(item["track"]["id"])

    # Add genre-specific tracks to the playlist if they are not already present
    tracks_to_add = [track_id for track_id in genre_tracks if track_id not in existing_tracks]

    batch_size = 100  # Number of tracks per batch request
    for i in range(0, len(tracks_to_add), batch_size):
        batch = tracks_to_add[i:i + batch_size]
        sp.playlist_add_items(playlist["id"], batch)

    return render_template('app/playlist.html',playlist_name=playlist_name)

@app.route('/similar_songs/', methods=['POST'])
def similar_songs():
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_path)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    if 'token_info' not in session:
        return redirect('/')

    token_info = session['token_info']
    access_token = token_info['access_token']
    
    
    sp = spotipy.Spotify(auth=access_token)
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
    if 'token_info' not in session:
        return redirect('/')

    token_info = session['token_info']
    access_token = token_info['access_token']

    
    sp = spotipy.Spotify(auth=access_token)
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
    if 'token_info' not in session:
        return redirect('/')

    token_info = session['token_info']
    access_token = token_info['access_token']

    
    sp = spotipy.Spotify(auth=access_token)
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
    session.pop("token_info", None)
    session.clear()  # Clear the entire session
    full_cache_path = os.path.join(app.root_path, cache_path)
    if os.path.exists(full_cache_path):
        os.remove(full_cache_path)
    if 'token_info' not in session:
        return redirect('/')

    token_info = session['token_info']
    access_token = token_info['access_token']
    sp = spotipy.Spotify(auth=access_token)
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

