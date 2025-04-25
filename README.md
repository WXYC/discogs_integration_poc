# WXYC Discogs Integration

A command-line tool for searching Discogs and checking WXYC library status.

## Installation

1. Create a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install the package:

```bash
pip install -e .
```

3. Create a `.env` file in the project root with your Discogs API credentials:

```
DISCOGS_KEY=your_key_here
DISCOGS_SECRET=your_secret_here

AWS_REGION=us-east-1
AWS_CLIENT_ID=cognito_client_id_here
```

## Usage

Run the tool:

```bash
wxyc-discogs
```

Controls:

- `n`: Next page
- `b`: Previous page
- `s`: New search
- `q` or `ESC`: Quit
