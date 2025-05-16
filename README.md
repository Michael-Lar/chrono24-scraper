# Chrono Cursor

A modular web scraper for extracting watch information from Chrono24.com using Playwright.

## Project Structure

```
chrono-cursor/
├── chrono/                     # Main package
│   ├── __init__.py            # Package initialization
│   ├── config.py              # Configuration constants
│   ├── models/                # Data models
│   │   ├── __init__.py
│   │   └── watch.py          # Watch data model
│   ├── scrapers/              # Scraper implementations
│   │   ├── __init__.py
│   │   ├── brand_processor.py # Brand-level processing
│   │   ├── extractors.py      # Content extraction functions
│   │   └── page_processor.py  # Page-level processing
│   └── utils/                 # Utility functions
│       ├── __init__.py
│       ├── delays.py          # Polite delays and backoff
│       └── file_operations.py # File handling utilities
├── data/                       # Data storage directory
│   ├── brands.json            # Extracted brand information
│   └── rolex_watches_complete.json # Extracted watch data
├── chrono_scraper.py           # Main entry point
├── extract_brands.py           # Tool to extract brands
├── extract_watches.py          # Original scraper (kept for reference)
├── extract_watches_improved.py # Improved scraper (kept for reference)
└── requirements.txt            # Dependencies
```

## Features

- Extracts detailed watch information from Chrono24
- Checkpoint system for resuming interrupted scraping runs
- Exponential backoff for reliable and polite scraping
- Modular code organization for maintainability

## Installation

1. Clone the repository:
   ```
   git clone https://github.com/yourusername/chrono-cursor.git
   cd chrono-cursor
   ```

2. Create a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Install Playwright browsers:
   ```
   playwright install
   ```

## Usage

### 1. Extract Brand Information

First, extract brand information from Chrono24:

```
python extract_brands.py
```

This will create a `brands.json` file in the `data` directory.

### 2. Run the Scraper

To start scraping watches (currently focused on Rolex):

```
python chrono_scraper.py
```

The script will:
1. Load brand information
2. Process Rolex brand pages
3. Extract watch URLs
4. Extract detailed information from each watch page
5. Save data to `data/rolex_watches_complete.json`

### 3. Resume Interrupted Scraping

If the scraping process is interrupted, you can resume from the last checkpoint:

```
python chrono_scraper.py --resume
```

## Customization

- To scrape different brands, modify the brand filter in `chrono_scraper.py`
- Adjust delays and timing in `chrono/config.py`
- Modify extraction selectors in `chrono/scrapers/extractors.py`

## Notes

This is a research tool that makes polite requests to Chrono24 with appropriate delays. Please be respectful of the website's terms of service and resources when using this tool.

## License

MIT 