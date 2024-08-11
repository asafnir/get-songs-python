from flask import Flask, send_from_directory, request, jsonify, send_file
from flask_cors import CORS
import yt_dlp
import os
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from dotenv import load_dotenv
from werkzeug.utils import safe_join

# Load environment variables from .env file
load_dotenv()

# Initialize Flask app
app = Flask(__name__, static_folder='build')
CORS(app)
DOWNLOAD_FOLDER = "downloads"

# Get Spotify API credentials from environment variables
SPOTIPY_CLIENT_ID = os.getenv('SPOTIPY_CLIENT_ID')
SPOTIPY_CLIENT_SECRET = os.getenv('SPOTIPY_CLIENT_SECRET')

# Initialize Spotify client with credentials
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=SPOTIPY_CLIENT_ID, client_secret=SPOTIPY_CLIENT_SECRET))

# Ensure the download folder exists
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

# Function to search YouTube songs with pagination support
def search_youtube_songs(song_name, page=1, limit=5):
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'noplaylist': True,
        'extract_flat': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        search_result = ydl.extract_info(f"ytsearch{limit * page}:{song_name}", download=False)
        if 'entries' in search_result:
            start = (page - 1) * limit
            end = start + limit
            entries = search_result['entries'][start:end]
            return entries, len(search_result['entries']) > end
    return [], False

# Function to get track information from a Spotify link
def get_spotify_track_info(spotify_link):
    track_info = sp.track(spotify_link)
    return {
        'full_name': track_info['name'],
        'preview_image': track_info['album']['images'][0]['url'],
        'duration': track_info['duration_ms'] // 1000,
        'preview_url': track_info['preview_url'] if 'preview_url' in track_info else None
    }

# Route to validate and fetch song details based on user input
@app.route('/validate_song', methods=['POST'])
def validate_song():
    data = request.json
    song_name = data.get('song_name')
    youtube_link = data.get('youtube_link')
    spotify_link = data.get('spotify_link')
    page = data.get('page', 1)

    if spotify_link:
        try:
            track_info = get_spotify_track_info(spotify_link)
        except Exception as e:
            return jsonify({"error": "Invalid Spotify link"}), 400

        return jsonify({
            "full_name": track_info['name'],
            "preview_image": track_info['album']['images'][0]['url'],
            "duration": track_info['duration_ms'] // 1000,
            "preview_url": track_info['preview_url'],
            "source": "spotify"
        })

    if youtube_link:
        ydl_opts = {'quiet': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            try:
                info = ydl.extract_info(youtube_link, download=False)
                return jsonify({
                    "full_name": info.get('title'),
                    "preview_image": info.get('thumbnail'),
                    "duration": info.get('duration'),
                    "preview_url": info.get('url'),
                    "source": "youtube"
                })
            except Exception as e:
                return jsonify({"error": "Invalid YouTube link"}), 400

    if song_name:
        youtube_results, has_more = search_youtube_songs(song_name, page)
        if youtube_results:
            song_options = [
                {
                    "full_name": entry.get('title'),
                    "preview_image": entry.get('thumbnails')[0]['url'],
                    "youtube_link": entry.get('url'),
                    "duration": entry.get('duration'),
                    "preview_url": entry.get('url')
                } for entry in youtube_results
            ]
            return jsonify({"song_options": song_options, "has_more": has_more})

    return jsonify({"error": "No valid song link or name provided"}), 400

# Route to fetch all songs from a Spotify playlist
@app.route('/get_playlist_songs', methods=['POST'])
def get_playlist_songs():
    data = request.json
    playlist_link = data.get('playlist_link')

    try:
        playlist_id = playlist_link.split('/')[-1].split('?')[0]
        playlist = sp.playlist_tracks(playlist_id)

        songs = []
        for item in playlist['items']:
            track = item['track']
            songs.append({
                "full_name": track['name'],
                "artist": track['artists'][0]['name'],
                "preview_image": track['album']['images'][0]['url'],
                "duration": track['duration_ms'] // 1000,
                "preview_url": track.get('preview_url', None)
            })

        return jsonify({"songs": songs})
    except Exception as e:
        return jsonify({"error": "Invalid Spotify playlist link"}), 400

# Function to search and download a song using yt-dlp
def search_and_download_song(song_name, output_folder=DOWNLOAD_FOLDER):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': f'{output_folder}/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'nocheckcertificate': True,
        'quiet': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch:{song_name}", download=True)
        if 'entries' in info:
            video_info = info['entries'][0]
            file_path = f"{output_folder}/{video_info['title']}.mp3"
            return file_path
    return None

# Route to handle downloading multiple songs
@app.route('/download_songs', methods=['POST'])
def download_songs():
    song_names = request.json.get('songs')
    downloaded_songs = []

    for song in song_names:
        file_path = search_and_download_song(song)
        if file_path:
            downloaded_songs.append(os.path.basename(file_path))

    return jsonify({"downloaded_songs": downloaded_songs}), 200

# Route to handle downloading a specific file and deleting it after download
@app.route('/download_file/<filename>', methods=['GET'])
def download_file(filename):
    try:
        file_path = safe_join(DOWNLOAD_FOLDER, filename)
        response = send_file(file_path, as_attachment=True)
        response.call_on_close(lambda: os.remove(file_path))  # Remove file after download
        return response
    except Exception as e:
        return jsonify({"error": "File not found"}), 404

# Route to serve the frontend React app
@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    if path != "" and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    else:
        return send_from_directory(app.static_folder, 'index.html')

if __name__ == "__main__":
    app.run(debug=True)
