import requests
import json
import os
import sys
import time
import threading
from typing import Dict, List, Optional
import curses
from dotenv import load_dotenv
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
        while self.is_loading:
            self.stdscr.clear()
            self.stdscr.addstr(0, 0, "Loading" + "." * (i % 4))
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

    def search(self, artist: str, track: str, page: int = 1) -> Dict:
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
            album["title"] = compound_title.split(" - ")[1]

            album["wxyc_status"] = getWxycStatusForRelease(album["artist"], album["title"])
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



def getWxycStatusForRelease(artist: str, title: str) -> bool:
    headers = {}
    if token:
        headers["Authorization"] = f"{token}"
        
    response = requests.get(
        f"http://api.wxyc.org/library?artist_name={artist}&album_title={title}&n=1",
        headers=headers
    )
    response_json = response.json()

    for release in response_json:
        if release.get("artist_dist", 1) < 0.1 and release.get("album_dist", 1) < 0.1:
            return True

    return False

def display_loading(stdscr):
    stdscr.clear()
    for i in range(4):
        stdscr.addstr(0, 0, "Loading" + "." * i)
        stdscr.refresh()
        time.sleep(0.6)
    stdscr.refresh()
    
def display_results(stdscr, results: List[Dict], current_page: int, total_pages: int):
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
    stdscr.addstr(controls_line + 1, 0, "Controls: [n]ext, [b]ack, [s]earch, [q]uit")
    
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

    def handle_search():
        artist = get_input(stdscr, "Enter artist name: ")
        track = get_input(stdscr, "Enter track title: ")
        discogs.clear_cache()

        loading_screen.start()
        results = discogs.search(artist, track)
        loading_screen.stop()

        display_results(stdscr, results, discogs.current_page, discogs.total_pages)

    # Initial search
    handle_search()

    while True:
        try:
            # Get a single character
            key = stdscr.getch()
            
            if key == ord('n'):
                results = discogs.next_page(loading_screen)
                display_results(stdscr, results, discogs.current_page, discogs.total_pages)
            elif key == ord('b'):
                results = discogs.previous_page(loading_screen)
                display_results(stdscr, results, discogs.current_page, discogs.total_pages)
            elif key == ord('s'):
                handle_search()
            elif key == ord('q') or key == 27:  # 27 is ESC key
                break
        except KeyboardInterrupt:
            break

def run():
    curses.wrapper(main)

if __name__ == "__main__":
    run()
