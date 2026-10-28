"""
Album Art Manager & Online Fetcher Module
=========================================
Locates local album art from audio directories, extracts from VLC cache,
fetches high-resolution cover artwork from free online public APIs
(iTunes Search, Deezer), and caches images locally for embedding into tags.
"""

from __future__ import annotations

import os
import re
import json
import urllib.request
import urllib.parse
from typing import Optional, List, Dict, Any, Tuple

from .metadata import AudioMetadata, COVER_FILENAMES

ARTWORK_CACHE_DIR = "album_art_cache"


def sanitize_filename(name: str) -> str:
    """Sanitize string for safe filenames on Windows."""
    clean = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    return clean[:60] if clean else "unknown"


class AlbumArtManager:
    """Discovers, fetches, and caches album artwork."""

    _cache_dir: str = ARTWORK_CACHE_DIR

    @classmethod
    def set_cache_directory(cls, dir_path: str):
        cls._cache_dir = os.path.abspath(dir_path)
        os.makedirs(cls._cache_dir, exist_ok=True)

    @classmethod
    def get_cache_directory(cls) -> str:
        os.makedirs(cls._cache_dir, exist_ok=True)
        return cls._cache_dir

    @classmethod
    def find_local_artwork(cls, file_path: str) -> Optional[str]:
        """
        Searches the file's parent directory and VLC art cache for cover art.
        """
        try:
            folder = os.path.dirname(os.path.abspath(file_path))
            if os.path.isdir(folder):
                # 1. Direct standard names
                for entry in os.listdir(folder):
                    entry_lower = entry.lower()
                    if entry_lower in COVER_FILENAMES:
                        full_p = os.path.join(folder, entry)
                        if os.path.isfile(full_p):
                            return full_p

                # 2. Any image file in the directory
                for entry in os.listdir(folder):
                    _, ext = os.path.splitext(entry)
                    if ext.lower() in (".jpg", ".jpeg", ".png"):
                        full_p = os.path.join(folder, entry)
                        if os.path.isfile(full_p):
                            return full_p
        except Exception:
            pass

        return None

    @classmethod
    def find_vlc_cached_art(cls, artist: str, album: str) -> Optional[str]:
        """Checks if VLC has previously cached artwork for this artist & album."""
        appdata = os.environ.get("APPDATA")
        if not appdata or not artist or not album:
            return None

        vlc_art_dir = os.path.join(appdata, "vlc", "art", "artistalbum", sanitize_filename(artist), sanitize_filename(album))
        if os.path.isdir(vlc_art_dir):
            for f in ("art.jpg", "art.png", "art.jpeg"):
                cand = os.path.join(vlc_art_dir, f)
                if os.path.isfile(cand):
                    return cand
        return None

    _url_cache_file: str = "album_art_urls.json"
    _url_cache: Dict[str, str] = {}
    _cache_loaded: bool = False

    @classmethod
    def _load_url_cache(cls):
        if cls._cache_loaded:
            return
        cls._cache_loaded = True
        cache_path = os.path.join(cls.get_cache_directory(), cls._url_cache_file)
        if os.path.isfile(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cls._url_cache = json.load(f)
            except Exception:
                cls._url_cache = {}

    @classmethod
    def _save_url_cache(cls):
        cache_path = os.path.join(cls.get_cache_directory(), cls._url_cache_file)
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cls._url_cache, f, indent=2)
        except Exception:
            pass

    @classmethod
    def get_cached_image_url(cls, artist: str, album: str) -> Optional[str]:
        """Check if a direct image link has been previously discovered and cached."""
        cls._load_url_cache()
        key = f"{artist.lower().strip()}__{album.lower().strip()}"
        return cls._url_cache.get(key)

    @classmethod
    def get_online_image_url(cls, artist: str, album: str, title: Optional[str] = None) -> Optional[str]:
        """
        Queries Apple iTunes CDN, Deezer CDN, and MusicBrainz Cover Art Archive
        for direct high-resolution cover image file links (.jpg / .png).
        Never returns search pages or HTML listings.
        """
        if not artist and not album:
            return None

        # Check memory/file cache first
        cached = cls.get_cached_image_url(artist, album)
        if cached:
            return cached

        search_query = f"{artist} {album}".strip()
        if not album or album.lower().startswith("unknown"):
            search_query = f"{artist} {title or ''}".strip()

        img_url = None

        # 1. Try iTunes Search API - album entity (returns direct Apple CDN .jpg link)
        try:
            encoded_query = urllib.parse.quote(search_query)
            itunes_url = f"https://itunes.apple.com/search?term={encoded_query}&entity=album&limit=1"
            req = urllib.request.Request(itunes_url, headers={"User-Agent": "AntigravityMusicPlayer/1.2"})
            with urllib.request.urlopen(req, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                results = payload.get("results", [])
                if results and "artworkUrl100" in results[0]:
                    raw_art = results[0]["artworkUrl100"]
                    # Upgrade to 600x600 direct JPEG file URL on Apple CDN
                    img_url = raw_art.replace("100x100bb", "600x600bb")
        except Exception:
            pass

        # 2. Try iTunes Search API - song entity fallback (for singles or unlisted albums)
        if not img_url and title:
            try:
                song_query = urllib.parse.quote(f"{artist} {title}".strip())
                itunes_url = f"https://itunes.apple.com/search?term={song_query}&entity=song&limit=1"
                req = urllib.request.Request(itunes_url, headers={"User-Agent": "AntigravityMusicPlayer/1.2"})
                with urllib.request.urlopen(req, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    results = payload.get("results", [])
                    if results and "artworkUrl100" in results[0]:
                        raw_art = results[0]["artworkUrl100"]
                        img_url = raw_art.replace("100x100bb", "600x600bb")
            except Exception:
                pass

        # 3. Try Deezer API (returns direct Deezer CDN image URL)
        if not img_url:
            try:
                deezer_url = f"https://api.deezer.com/search/album?q={urllib.parse.quote(search_query)}&limit=1"
                req = urllib.request.Request(deezer_url, headers={"User-Agent": "AntigravityMusicPlayer/1.2"})
                with urllib.request.urlopen(req, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    data = payload.get("data", [])
                    if data:
                        img_url = data[0].get("cover_xl") or data[0].get("cover_big") or data[0].get("cover_medium")
            except Exception:
                pass

        # 4. Try MusicBrainz Cover Art Archive
        if not img_url and album and not album.lower().startswith("unknown"):
            try:
                mb_q = urllib.parse.quote(f'artist:"{artist}" AND release:"{album}"')
                mb_url = f"https://musicbrainz.org/ws/2/release/?query={mb_q}&fmt=json&limit=1"
                req = urllib.request.Request(mb_url, headers={"User-Agent": "AntigravityMusicPlayer/1.2 (contact@example.com)"})
                with urllib.request.urlopen(req, timeout=4) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                    releases = payload.get("releases", [])
                    if releases and "id" in releases[0]:
                        mbid = releases[0]["id"]
                        img_url = f"https://coverartarchive.org/release/{mbid}/front-500.jpg"
            except Exception:
                pass

        if img_url:
            cls._load_url_cache()
            key = f"{artist.lower().strip()}__{album.lower().strip()}"
            cls._url_cache[key] = img_url
            cls._save_url_cache()

        return img_url

    @classmethod
    def fetch_online_artwork(cls, artist: str, album: str, title: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Searches music databases for direct high-resolution cover image URL and downloads the file.
        Returns (local_cached_file_path, direct_web_image_url).
        """
        if not artist and not album:
            return None, None

        cache_folder = cls.get_cache_directory()
        safe_name = f"{sanitize_filename(artist)}_{sanitize_filename(album)}.jpg"
        cached_target = os.path.join(cache_folder, safe_name)

        # Get direct image URL
        image_url = cls.get_online_image_url(artist, album, title)

        # If already cached on disk, return it immediately with direct image URL
        if os.path.isfile(cached_target) and os.path.getsize(cached_target) > 500:
            return cached_target, image_url

        # Download direct image bytes
        if image_url:
            try:
                dl_req = urllib.request.Request(
                    image_url,
                    headers={"User-Agent": "AntigravityMusicPlayer/1.2"}
                )
                with urllib.request.urlopen(dl_req, timeout=6) as dl_resp:
                    img_data = dl_resp.read()
                    if len(img_data) > 1000:
                        with open(cached_target, "wb") as f:
                            f.write(img_data)
                        return cached_target, image_url
            except Exception:
                pass

        return None, image_url

    @classmethod
    def resolve_artwork(cls, meta: AudioMetadata, enable_online_download: bool = True) -> bool:
        """
        Attempts to resolve album artwork for a song:
        1. Verifies existing art path
        2. Searches local folder
        3. Searches VLC art cache
        4. Queries online music CDNs for direct image URLs and downloads if permitted
        Updates meta.album_art_web_url and meta.album_art_html_link with direct image links.
        Returns True if artwork was found or fetched.
        """
        # If valid artwork already exists on disk
        if meta.has_album_art and meta.album_art_path and os.path.isfile(meta.album_art_path):
            if not meta.album_art_web_url:
                web_url = cls.get_cached_image_url(meta.artist, meta.album)
                if web_url:
                    meta.album_art_web_url = web_url
                    meta.album_art_html_link = f'<a href="{web_url}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
                else:
                    file_uri = f"file:///{os.path.abspath(meta.album_art_path).replace(os.sep, '/')}"
                    meta.album_art_html_link = f'<a href="{file_uri}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            return True

        # Check local folder
        local_art = cls.find_local_artwork(meta.file_path)
        if local_art:
            meta.has_album_art = True
            meta.album_art_path = local_art
            if "album_art" in meta.missing_fields:
                meta.missing_fields.remove("album_art")
            meta.has_incomplete_metadata = len(meta.missing_fields) > 0
            web_url = cls.get_cached_image_url(meta.artist, meta.album)
            if web_url:
                meta.album_art_web_url = web_url
                meta.album_art_html_link = f'<a href="{web_url}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            else:
                file_uri = f"file:///{os.path.abspath(local_art).replace(os.sep, '/')}"
                meta.album_art_html_link = f'<a href="{file_uri}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            return True

        # Check VLC cache
        vlc_art = cls.find_vlc_cached_art(meta.artist, meta.album)
        if vlc_art:
            meta.has_album_art = True
            meta.album_art_path = vlc_art
            if "album_art" in meta.missing_fields:
                meta.missing_fields.remove("album_art")
            meta.has_incomplete_metadata = len(meta.missing_fields) > 0
            web_url = cls.get_cached_image_url(meta.artist, meta.album)
            if web_url:
                meta.album_art_web_url = web_url
                meta.album_art_html_link = f'<a href="{web_url}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            else:
                file_uri = f"file:///{os.path.abspath(vlc_art).replace(os.sep, '/')}"
                meta.album_art_html_link = f'<a href="{file_uri}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            return True

        # Check URL cache even if download is disabled
        if not meta.album_art_web_url and meta.artist and meta.artist.lower() != "unknown artist":
            cached_url = cls.get_cached_image_url(meta.artist, meta.album)
            if cached_url:
                meta.album_art_web_url = cached_url
                meta.album_art_html_link = f'<a href="{cached_url}" target="_blank" download="cover.jpg">Download Album Art Image</a>'

        # Online search & direct image download
        if enable_online_download and meta.artist and meta.artist.lower() != "unknown artist":
            cached_art, web_url = cls.fetch_online_artwork(meta.artist, meta.album, meta.title)
            if web_url:
                meta.album_art_web_url = web_url
                meta.album_art_html_link = f'<a href="{web_url}" target="_blank" download="cover.jpg">Download Album Art Image</a>'
            if cached_art:
                meta.has_album_art = True
                meta.album_art_path = cached_art
                if "album_art" in meta.missing_fields:
                    meta.missing_fields.remove("album_art")
                meta.has_incomplete_metadata = len(meta.missing_fields) > 0
                return True

        return False
