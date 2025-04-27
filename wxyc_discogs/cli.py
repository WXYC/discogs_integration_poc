import requests
import json
import os
import sys
import time
import threading
import math
import concurrent.futures
from typing import Dict, List, Optional
import curses
from dotenv import load_dotenv
import re
from wxyc_discogs.login import authenticate


# Global variable to store the wxyc jwt
token = None

class LoadingScreen:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.is_loading = False
        self.loading_thread = None

    def start(self):
        self.is_loading = True
        self.loading_thread = threading.Thread(target=self._animate)
        self.loading_thread.start()

    def stop(self):
        self.is_loading = False
        if self.loading_thread:
            self.loading_thread.join()
        self.stdscr.clear()
        self.stdscr.refresh()

    def _animate(self):
        i = 0
        max_y, max_x = self.stdscr.getmaxyx()
        while self.is_loading:
            self.stdscr.clear()
            self.stdscr.addstr(max_y//2, math.floor(max_x/2.25), "Loading" + "." * (i % 4))
            self.stdscr.refresh()
            time.sleep(0.4)
            i += 1

class DiscogsSearch:
    def __init__(self, key: str, secret: str):
        self.key = key
        self.secret = secret
        self.base_url = "https://api.discogs.com/database/search"
        self.headers = {
            "Authorization": f"Discogs key={key}, secret={secret}",
            "User-Agent": "WXYC-Discogs-Search/1.0"
        }
        self.current_page = 1
        self.total_pages = 1
        self.cached_results: Dict[int, List[Dict]] = {}
        self.current_search_params = {}
        self.wxyc_releases = []
        self.wxyc_current_page = 1
        self.wxyc_total_pages = 1
        self.wxyc_releases_per_page = 10

    def search(self, artist: str, track: str, page: int = 1) -> Dict:
        if artist.casefold() == "Various Artists".casefold():
            artist = "Various"

        params = {
            "artist": artist,
            "track": track,
            "type": "master",
            "per_page": 10,
            "page": page
        }
        
        self.current_search_params = params
        response = requests.get(self.base_url, headers=self.headers, params=params)
        response.raise_for_status()

        self.total_pages = response.json().get("pagination", {}).get("pages", 1)

        albums = self.process_albums(response.json().get("results", []))

        self.cached_results[page] = albums

        return albums

    def process_albums(self, albums: List[Dict]) -> List[Dict]:
        for album in albums:
            # Parse out the title and artist from the compound title that discogs provides
            compound_title = album.get("title", "N/A")

            album["artist"] = compound_title.split(" - ")[0]
            album["artist"] = re.sub(r"\(\d+\)", "", album["artist"])
            album["title"] = compound_title.split(" - ")[1]

        # Process WXYC status checks in parallel
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            future_to_album = {
                executor.submit(getWxycStatusForRelease, album["artist"], album["title"]): album 
                for album in albums
            }
            
            for future in concurrent.futures.as_completed(future_to_album):
                album = future_to_album[future]
                try:
                    album["wxyc_status"] = future.result()
                except Exception as e:
                    album["wxyc_status"] = False
                    print(f"Error checking WXYC status for {album['artist']} - {album['title']}: {e}")

        return albums

    def get_page(self, page: int, loading_screen: LoadingScreen) -> List[Dict]:
        if page not in self.cached_results:
            loading_screen.start()
            results = self.search(
                self.current_search_params["artist"],
                self.current_search_params["track"],
                page
            )
            loading_screen.stop()
        return self.cached_results[page]

    def next_page(self, loading_screen: LoadingScreen) -> List[Dict]:
        if self.current_page < self.total_pages:
            self.current_page += 1

        return self.get_page(self.current_page, loading_screen)

    def previous_page(self, loading_screen: LoadingScreen) -> List[Dict]:
        if self.current_page > 1:
            self.current_page -= 1

        return self.get_page(self.current_page, loading_screen)

    def clear_cache(self):
        self.cached_results = {}
        self.current_page = 1
        self.total_pages = 1
        self.current_search_params = {}

    def fetch_wxyc_releases(self, artist: str):
        self.wxyc_releases = getWxycReleasesForArtist(artist)
        self.wxyc_total_pages = (len(self.wxyc_releases) + self.wxyc_releases_per_page - 1) // self.wxyc_releases_per_page
        self.wxyc_current_page = 1

    def get_wxyc_page(self, page: int) -> List[Dict]:
        start_idx = (page - 1) * self.wxyc_releases_per_page
        end_idx = start_idx + self.wxyc_releases_per_page
        return self.wxyc_releases[start_idx:end_idx]

    def next_wxyc_page(self) -> List[Dict]:
        if self.wxyc_current_page < self.wxyc_total_pages:
            self.wxyc_current_page += 1
        return self.get_wxyc_page(self.wxyc_current_page)

    def previous_wxyc_page(self) -> List[Dict]:
        if self.wxyc_current_page > 1:
            self.wxyc_current_page -= 1
        return self.get_wxyc_page(self.wxyc_current_page)

def getWxycStatusForRelease(artist: str, title: str) -> bool:
    headers = {}
    if token:
        headers["Authorization"] = f"{token}"
        
    artist_param = f"&artist_name={artist}" if artist != "Various" else ""
    response = requests.get(
        f"http://api.wxyc.org/library?album_title={title}{artist_param}&n=10",
        headers=headers
    )
    response_json = response.json()

    for release in response_json:
        if (artist == "Various" or (release.get("artist_dist", 1) <= 0.7)) and release.get("album_dist", 1) < 0.2 :
            return True

    return False

def getWxycReleasesForArtist(artist: str) -> List[Dict]:
    headers = {}
    if token:
        headers["Authorization"] = f"{token}"
        
    response = requests.get(
        f"http://api.wxyc.org/library?artist_name={artist}&n=100",
        headers=headers
    )
    response_json = response.json()

    return list(map(lambda x: {
        "title": x.get("album_title", "N/A"),
        "artist": x.get("artist_name", "N/A"),
        "year": x.get("year", "N/A"),
        "label": x.get("label", "N/A"),
        "format": [x.get("format_name", "N/A")],
        "wxyc_status": True
    }, response_json))

def display_results(stdscr, results: List[Dict], current_page: int, total_pages: int, show_wxyc: bool = False):
    # Clear the screen
    stdscr.clear()
    
    # Get screen dimensions
    max_y, max_x = stdscr.getmaxyx()
    
    # Define column widths
    col_widths = {
        "title": int(max_x * 0.25),
        "artist": int(max_x * 0.25),
        "year": int(max_x * 0.1),
        "label": int(max_x * 0.15),
        "format": int(max_x * 0.15),
        "wxyc_status": int(max_x * 0.1)
    }
    
    # Print headers
    headers = ["Title", "Artist", "Year", "Label", "Format", "WXYC"]
    x_pos = 0
    for i, header in enumerate(headers):
        width = col_widths[list(col_widths.keys())[i]]
        stdscr.addstr(0, x_pos, header[:width-1].ljust(width), curses.A_BOLD)
        x_pos += width
    
    # Print separator line
    stdscr.addstr(1, 0, "-" * max_x)

    if not results:
        stdscr.addstr(max_y//2, max_x//2, "No results found", curses.A_BOLD)
    
    # Print results
    for i, result in enumerate(results):
        if i + 4 >= max_y:  # Leave room for controls and headers
            break
        
        title = result.get("title", "N/A")[:col_widths["title"]-1]
        artist = result.get("artist", "N/A")[:col_widths["artist"]-1]
        wxyc_status = "✓" if result.get("wxyc_status", False) else "X"

        year = str(result.get("year", "N/A"))[:col_widths["year"]-1]
        label = (result.get("label", ["N/A"])[0] if result.get("label") else "N/A")[:col_widths["label"]-1]
        format_ = (result.get("format", ["N/A"])[0] if result.get("format") else "N/A")[:col_widths["format"]-1]
        
        x_pos = 0
        for value, width in zip([title, artist, year, label, format_, wxyc_status], col_widths.values()):
            stdscr.addstr(i + 2, x_pos, value.ljust(width))
            x_pos += width
        
        stdscr.refresh()
    
    # Print page info and controls
    controls_line = max_y - 2
    stdscr.addstr(controls_line, 0, f"Page {current_page} of {total_pages}")
    stdscr.addstr(controls_line + 1, 0, "Controls: [n]ext, [b]ack, [s]earch, [w]xyc, [q]uit")
    
    # Add WXYC library status if showing WXYC releases
    if show_wxyc:
        stdscr.addstr(controls_line, 12, "| [WXYC Library]")
    
    # Refresh the screen
    stdscr.refresh()

def get_input(stdscr, prompt: str, secret: bool = False) -> str:
    stdscr.clear()
    stdscr.addstr(0, 0, prompt)
    stdscr.refresh()
    
    if secret:
        curses.curs_set(1)
        curses.noecho() 
        input_str = stdscr.getstr(1, 0).decode('utf-8')
    else:
        curses.curs_set(1)
        curses.echo()
        input_str = stdscr.getstr(1, 0).decode('utf-8')
        curses.noecho()
    
    return input_str

def main(stdscr):
    # Initialize curses
    curses.curs_set(1)  # Show cursor
    stdscr.keypad(True)  # Enable keypad mode
    curses.start_color()
    curses.init_pair(1, curses.COLOR_WHITE, curses.COLOR_BLACK)
    
    # Load environment variables from .env file
    load_dotenv()

    # Get WXYC authentication token
    username = get_input(stdscr, "Enter your username: ")
    password = get_input(stdscr, "Enter your password: ", secret=True)
    global token 
    token = authenticate(username, password)
    if token is None:
        stdscr.clear()
        stdscr.addstr(0, 0, "Error: Incorrect username or password")
        stdscr.refresh()
        stdscr.getch()
        sys.exit(1)
    
    # Get API credentials from environment variables
    key = os.getenv("DISCOGS_KEY")
    secret = os.getenv("DISCOGS_SECRET")

    if not key or not secret:
        stdscr.addstr(0, 0, "Error: DISCOGS_KEY and DISCOGS_SECRET must be set in .env file")
        stdscr.addstr(1, 0, "Please create a .env file with your Discogs API credentials")
        stdscr.refresh()
        stdscr.getch()
        sys.exit(1)

    discogs = DiscogsSearch(key, secret)
    loading_screen = LoadingScreen(stdscr)
    show_wxyc = False

    def handle_search():
        artist = get_input(stdscr, "Enter artist name: ")
        track = get_input(stdscr, "Enter track title: ")
        discogs.clear_cache()
        curses.curs_set(0)

        loading_screen.start()
        results = discogs.search(artist, track)
        loading_screen.stop()

        # Start fetching WXYC releases in background
        wxyc_thread = threading.Thread(target=discogs.fetch_wxyc_releases, args=(artist,))
        wxyc_thread.daemon = True
        wxyc_thread.start()

        display_results(stdscr, results, discogs.current_page, discogs.total_pages, show_wxyc)

    # Initial search
    handle_search()

    while True:
        try:
            # Get a single character
            key = stdscr.getch()
            
            if key == ord('n'):
                if show_wxyc:
                    results = discogs.next_wxyc_page()
                    display_results(stdscr, results, discogs.wxyc_current_page, discogs.wxyc_total_pages, show_wxyc)
                else:
                    results = discogs.next_page(loading_screen)
                    display_results(stdscr, results, discogs.current_page, discogs.total_pages, show_wxyc)
            elif key == ord('b'):
                if show_wxyc:
                    results = discogs.previous_wxyc_page()
                    display_results(stdscr, results, discogs.wxyc_current_page, discogs.wxyc_total_pages, show_wxyc)
                else:
                    results = discogs.previous_page(loading_screen)
                    display_results(stdscr, results, discogs.current_page, discogs.total_pages, show_wxyc)
            elif key == ord('s'):
                handle_search()
                show_wxyc = False
            elif key == ord('w'):
                if show_wxyc:
                    show_wxyc = False
                    results = discogs.get_page(discogs.current_page, loading_screen)
                    display_results(stdscr, results, discogs.current_page, discogs.total_pages, show_wxyc)
                else:
                    show_wxyc = True
                    results = discogs.get_wxyc_page(discogs.wxyc_current_page)
                    display_results(stdscr, results, discogs.wxyc_current_page, discogs.wxyc_total_pages, show_wxyc)
                
            elif key == ord('q') or key == 27:  # 27 is ESC key
                break
        except KeyboardInterrupt:
            break

def run():
    curses.wrapper(main)

if __name__ == "__main__":
    run()
