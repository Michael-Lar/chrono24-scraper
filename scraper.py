#!/usr/bin/env python3
import json
import os
import time
import random
import sys
import logging
import re
import asyncio
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse, urljoin
from playwright.sync_api import sync_playwright, Page, TimeoutError
from functools import wraps
import argparse

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Constants
DATA_DIR = "./data"
BRANDS_JSON = f"{DATA_DIR}/brands.json"
WATCHES_JSON = f"{DATA_DIR}/rolex_watches.json"
BASE_URL = "https://www.chrono24.com"
ERRORS_DIR = f"{DATA_DIR}/errors"
PROGRESS_DIR = f"{DATA_DIR}/progress"

# Centralized CSS Selectors
SELECTORS = {
    "LISTING_CONTAINER": "#wt-watches",
    "LISTING_LINK": "#wt-watches > div:nth-child(n) > a",
    "LISTING_LINK_ALL": "#wt-watches a",
    "DETAIL_NAME": "#detail-page-dealer section.data h1 span",
    "DETAIL_PRICE": ".detail-page-price span",
    "DETAIL_DESC": [
        "#detail-page-dealer section.data .description-text",
        "#detail-page-dealer section.data .article-description",
        ".dealer-listing__description",
        ".detail-page__description"
    ],
    "SPEC_TABLES": [
        "#detail-page-dealer section.data table",
        "#detail-page-dealer section.data div table",
        "table.technical-details",
        "table"
    ]
}

def with_retry(max_retries=3, backoff_factor=2):
    """Decorator for retrying operations with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            last_exception = None
            
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    retries += 1
                    sleep_time = backoff_factor ** retries
                    logging.warning(f"Attempt {retries}/{max_retries} failed: {e}. Retrying in {sleep_time}s")
                    time.sleep(sleep_time)
            
            # If we get here, all retries failed
            raise last_exception
        return wrapper
    return decorator

def get_pagination_url(base_url: str, page_num: int) -> str:
    """Generate pagination URL using proper URL parsing."""
    parsed_url = urlparse(base_url)
    
    # Handle different pagination patterns
    if page_num == 1:
        return base_url
        
    # Try to identify the pagination pattern
    path = parsed_url.path
    if path.endswith('index.htm'):
        # Handle standard pattern
        base_path = path[:-9]  # Remove 'index.htm'
        new_path = f"{base_path}index-{page_num}.htm"
    elif path.endswith('/'):
        # Handle path ending with slash
        new_path = f"{path}index-{page_num}.htm"
    else:
        # Handle path without special ending
        new_path = f"{path}/index-{page_num}.htm"
    
    # Reconstruct the URL
    pagination_url = f"{parsed_url.scheme}://{parsed_url.netloc}{new_path}"
    if parsed_url.query:
        pagination_url += f"?{parsed_url.query}"
        
    return pagination_url

def adaptive_delay(response_time: float, status_code: int) -> float:
    """Adapt delay based on server response metrics."""
    # Base delay on response time (slower response = longer delay)
    base_delay = min(response_time * 1.5, 3.0)
    
    # Adjust for status codes
    if status_code >= 429:  # Too Many Requests
        return base_delay * 5 + random.uniform(10, 15)  # Much longer delay
    elif status_code >= 500:  # Server error
        return base_delay * 3 + random.uniform(5, 10)  # Longer delay
    
    # Add jitter to avoid detection patterns
    jitter = random.uniform(0, base_delay * 0.5)
    
    return base_delay + jitter

def load_progress(brand_name: str) -> Dict:
    """Load scraping progress for a brand."""
    progress_file = os.path.join(PROGRESS_DIR, f"{brand_name}_progress.json")
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Error reading progress file for {brand_name}")
    return {"current_page": 1, "processed_urls": []}

def save_progress(brand_name: str, progress: Dict):
    """Save scraping progress for a brand."""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    progress_file = os.path.join(PROGRESS_DIR, f"{brand_name}_progress.json")
    with open(progress_file, 'w') as f:
        json.dump(progress, f)

def polite_delay():
    """Add a random delay between requests (2-5 seconds)."""
    delay = random.uniform(2, 5)
    time.sleep(delay)

def load_brands(filename=BRANDS_JSON):
    """Load brand data from JSON file."""
    if not os.path.exists(filename):
        logging.error(f"Brands file {filename} not found.")
        return []
    
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_watches_to_json(watches, filename=WATCHES_JSON):
    """Save watch data to a JSON file."""
    os.makedirs(os.path.dirname(filename), exist_ok=True)
    
    # Load existing watches if file exists
    existing_watches = []
    if os.path.exists(filename):
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                existing_watches = json.load(f)
        except json.JSONDecodeError:
            logging.error(f"Error reading existing watches file. Starting fresh.")
    
    # Combine existing and new watches, avoiding duplicates
    all_watches = existing_watches.copy()
    existing_urls = {w.get('url') for w in existing_watches}
    
    # Filter out watches that already exist
    new_watches = [w for w in watches if w.get("url") not in existing_urls]
    
    if not new_watches:
        logging.info("No new watches to save, skipping file write")
        return
    
    # Add only new watches
    all_watches.extend(new_watches)
    
    # Save all watches
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_watches, f, indent=2, ensure_ascii=False)
    
    logging.info(f"Watch data ({len(all_watches)} total watches) saved to {filename}")

def make_absolute_url(url: str) -> str:
    """Convert a relative URL to an absolute URL."""
    if not url.startswith(('http://', 'https://')):
        return urljoin(BASE_URL, url.lstrip('/'))
    return url

def extract_specs(page: Page) -> Dict[str, str]:
    """Extract specifications from watch detail page."""
    specs = {}
    
    # Try all spec table selectors in order
    for selector in SELECTORS["SPEC_TABLES"]:
        try:
            tables = page.query_selector_all(selector)
            if tables:
                for table in tables:
                    rows = table.query_selector_all("tbody > tr")
                    for row in rows:
                        key_element = row.query_selector("th") or row.query_selector("td:first-child")
                        value_element = row.query_selector("td:last-child") or row.query_selector("td:nth-child(2)")
                        
                        if key_element and value_element:
                            key = key_element.text_content().strip()
                            value = value_element.text_content().strip()
                            
                            # Remove embedded JS loader code
                            value = re.sub(r'.*function docReady[\s\S]*', '', value).strip()
                            
                            # Skip the generic header row
                            key_lower = key.lower()
                            if key_lower == "basic info":
                                continue

                            # Skip only the header-like "Description" row,
                            # not the real description content
                            if key_lower == "description" and value.strip().lower() == "description":
                                continue
                                
                            if key:
                                specs[key] = value
                if specs:  # If we found specs, no need to try other selectors
                    break
        except Exception as e:
            logging.warning(f"Error extracting specs with selector {selector}: {e}")
    
    return specs

def extract_description(page: Page) -> str:
    """Extract watch description from detail page."""
    for selector in SELECTORS["DETAIL_DESC"]:
        try:
            desc_element = page.query_selector(selector)
            if desc_element:
                description = desc_element.text_content().strip()
                if description:
                    return description
        except Exception as e:
            logging.warning(f"Error extracting description with selector {selector}: {e}")
    
    return ""

def process_watch_detail(page: Page, watch_url: str, brand_name: str) -> Optional[Dict]:
    """Process a watch detail page and extract all required information."""
    try:
        # Ensure URL is absolute
        watch_url = make_absolute_url(watch_url)
        
        # Navigate to the watch detail page
        page.goto(watch_url)
        page.wait_for_load_state("domcontentloaded")
        
        # Extract watch name with fallback
        name_element = page.query_selector(SELECTORS["DETAIL_NAME"]) or page.query_selector("h1")
        watch_name = name_element.text_content().strip() if name_element else ""
        
        # Log and skip empty names
        if not watch_name:
            # Save HTML snapshot for debugging
            os.makedirs(ERRORS_DIR, exist_ok=True)
            path = f"{ERRORS_DIR}/empty_name_{brand_name}_{int(time.time())}.html"
            with open(path, "w", encoding="utf-8") as f:
                f.write(page.content())
            logging.warning(f"Empty watch name at {watch_url}, HTML saved to {path}")
            return None
        
        # Extract price
        price_element = page.query_selector(SELECTORS["DETAIL_PRICE"])
        price = price_element.text_content().strip() if price_element else ""
        
        # Extract description
        description = extract_description(page)
        
        # Extract specifications
        specs = extract_specs(page)
        
        # If no top-level description, pull it from specs
        if not description and "Description" in specs:
            description = specs.pop("Description")
        
        # Create watch data object
        watch_data = {
            "url": watch_url,
            "name": watch_name,
            "price": price,
            "description": description,
            "specifications": specs
        }
        
        logging.info(f"Extracted: {watch_name} ({price})")
        return watch_data
    
    except Exception as e:
        logging.error(f"Error processing watch detail page {watch_url}: {e}")
        return None

def process_listing_page(page: Page) -> List[str]:
    """Process a listing page and extract watch URLs."""
    watch_urls = []
    
    logging.info("Starting to collect watch URLs from listing page...")
    
    # First try to get all links at once
    try:
        logging.info("Trying to find all watch links at once...")
        all_links = page.query_selector_all(SELECTORS["LISTING_LINK_ALL"])
        if all_links:
            logging.info(f"Found {len(all_links)} links using query_selector_all")
            for link in all_links:
                href = link.get_attribute("href")
                if href:
                    absolute_url = make_absolute_url(href)
                    watch_urls.append(absolute_url)
                    logging.info(f"Found link: {absolute_url}")
            return watch_urls
    except Exception as e:
        logging.warning(f"Error finding all links at once: {e}")
    
    # If that fails, try the incremental approach
    logging.info("Falling back to incremental link collection...")
    n = 1
    while True:
        selector = f"#wt-watches > div:nth-child({n}) > a"
        try:
            link = page.query_selector(selector)
            if not link:
                logging.info(f"No more watch links found after {n-1} links")
                break
                
            href = link.get_attribute("href")
            if href:
                absolute_url = make_absolute_url(href)
                watch_urls.append(absolute_url)
                logging.info(f"Found watch URL {n}: {absolute_url}")
            n += 1
        except Exception as e:
            logging.error(f"Error extracting watch URL {n}: {e}")
            break
    
    if not watch_urls:
        logging.error("No links found. Page content:")
        logging.error(page.content())
    
    logging.info(f"Total watch URLs collected from page: {len(watch_urls)}")
    return watch_urls

def smoke_test_selectors(page: Page, brand: Dict) -> bool:
    """Test if all required selectors are working on a sample page."""
    try:
        # Load first page
        page.goto(brand["url"])
        page.wait_for_load_state("domcontentloaded")
        
        # Wait for watch container
        try:
            page.wait_for_selector(SELECTORS["LISTING_CONTAINER"], timeout=30000)
        except TimeoutError:
            logging.error("Selector LISTING_CONTAINER failed on sample page")
            return False
        
        # Test listing link selector
        if not page.query_selector(SELECTORS["LISTING_LINK"]):
            logging.error("Selector LISTING_LINK failed on sample page")
            return False
        
        # Get first watch URL
        first_link = page.query_selector(SELECTORS["LISTING_LINK"])
        if not first_link:
            logging.error("Could not find first watch link")
            return False
        
        watch_url = make_absolute_url(first_link.get_attribute("href"))
        
        # Test detail page selectors
        page.goto(watch_url)
        page.wait_for_load_state("domcontentloaded")
        
        if not page.query_selector(SELECTORS["DETAIL_NAME"]):
            logging.error("Selector DETAIL_NAME failed on sample page")
            return False
            
        if not page.query_selector(SELECTORS["DETAIL_PRICE"]):
            logging.error("Selector DETAIL_PRICE failed on sample page")
            return False
            
        if not any(page.query_selector(selector) for selector in SELECTORS["SPEC_TABLES"]):
            logging.error("All SPEC_TABLES selectors failed on sample page")
            return False
        
        return True
        
    except Exception as e:
        logging.error(f"Error during smoke test: {e}")
        return False

@with_retry(max_retries=3)
def process_brand_page(page: Page, brand: Dict, page_num: int) -> bool:
    """Process a single page of brand listings with retry logic."""
    current_url = get_pagination_url(brand["url"], page_num)
    
    logging.info(f"\nProcessing page {page_num}: {current_url}")
    
    # Navigate to the page
    start_time = time.time()
    response = page.goto(current_url, wait_until="networkidle")
    response_time = time.time() - start_time
    
    if not response or response.status != 200:
        logging.error(f"Failed to load page {page_num}")
        logging.error(f"Response status: {response.status if response else 'No response'}")
        return False
    
    # Wait for the page to be fully loaded
    try:
        page.wait_for_selector(SELECTORS["LISTING_CONTAINER"], timeout=30000)
    except TimeoutError:
        logging.error(f"Watch container not found on page {page_num}")
        # Take screenshot of error
        os.makedirs(ERRORS_DIR, exist_ok=True)
        screenshot_path = f"{ERRORS_DIR}/screenshot_{brand['name']}_{page_num}.png"
        page.screenshot(path=screenshot_path)
        logging.error(f"Screenshot saved to {screenshot_path}")
        return False
    
    # Apply adaptive delay based on response time and status
    delay = adaptive_delay(response_time, response.status)
    time.sleep(delay)
    
    return True

def process_brand(page: Page, brand: Dict) -> List[Dict]:
    """Process a single brand's watches with progress tracking and recovery."""
    brand_watches = []
    
    # Load progress
    progress = load_progress(brand["name"])
    start_page = progress.get("current_page", 1)
    processed_urls = set(progress.get("processed_urls", []))
    
    try:
        logging.info(f"\nProcessing brand: {brand['name']}")
        
        for page_num in range(start_page, 100):  # Limit to 100 pages max
            # Process the page
            if not process_brand_page(page, brand, page_num):
                logging.warning(f"Failed to process page {page_num}, stopping pagination")
                break
            
            # Get watch URLs
            watch_urls = process_listing_page(page)
            if not watch_urls:
                logging.info(f"No watches found on page {page_num}")
                break
            
            # Filter out already processed URLs
            new_urls = [url for url in watch_urls if url not in processed_urls]
            if not new_urls:
                logging.info(f"No new watches found on page {page_num}, stopping pagination")
                break
            
            logging.info(f"Found {len(new_urls)} new watches on page {page_num}")
            
            # Process each new watch
            for i, url in enumerate(new_urls, 1):
                try:
                    logging.info(f"\nProcessing watch {i}/{len(new_urls)} on page {page_num}")
                    watch_data = process_watch_detail(page, url, brand["name"])
                    if watch_data:
                        brand_watches.append(watch_data)
                        # Save incrementally after each successful watch
                        save_watches_to_json([watch_data])
                        # Update processed URLs
                        processed_urls.add(url)
                        # Save progress
                        save_progress(brand["name"], {
                            "current_page": page_num,
                            "processed_urls": list(processed_urls)
                        })
                    polite_delay()  # Add delay between watch detail requests
                except Exception as e:
                    logging.error(f"Error processing watch {url}: {e}")
                    continue
            
            # Save progress after each page
            save_progress(brand["name"], {
                "current_page": page_num + 1,  # Next page
                "processed_urls": list(processed_urls)
            })
        
        logging.info(f"\nFinished processing {brand['name']}. Total watches: {len(brand_watches)}")
        return brand_watches
        
    except Exception as e:
        logging.error(f"Error processing brand {brand['name']}: {e}")
        # Save progress for later resumption
        save_progress(brand["name"], {
            "current_page": page_num,
            "processed_urls": list(processed_urls)
        })
        return brand_watches

def main():
    """Main function to orchestrate the watch extraction process."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Scrape Rolex watches from Chrono24')
    parser.add_argument('--headless', action='store_true', default=True, 
                        help='Run browser in headless mode')
    parser.add_argument('--slow-mo', type=int, default=0, 
                        help='Slow down browser actions by specified milliseconds')
    parser.add_argument('--max-concurrent', type=int, default=3,
                        help='Maximum number of concurrent watch detail page processing')
    args = parser.parse_args()
    
    # Create necessary directories
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(ERRORS_DIR, exist_ok=True)
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    
    # Load brands
    brands = load_brands()
    if not brands:
        logging.error("No brands found. Please run extract_brands.py first.")
        return
    
    logging.info(f"Loaded {len(brands)} brands")
    
    # Initialize watches list
    all_watches = []
    
    # Launch Playwright browser
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            slow_mo=args.slow_mo
        )
        
        # Create a new browser context with a realistic viewport
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        )
        
        # Create a new page
        page = context.new_page()
        
        try:
            # Find the main Rolex brand page
            rolex_brand = next((brand for brand in brands if brand["name"] == "Rolex"), None)
            if not rolex_brand:
                logging.error("Rolex brand not found in brands list")
                return
                
            logging.info(f"\nProcessing Rolex watches...")
            
            # Run smoke test before processing
            if not smoke_test_selectors(page, rolex_brand):
                logging.error("Smoke test failed. Aborting.")
                sys.exit(1)
            
            brand_watches = process_brand(page, rolex_brand)
            all_watches.extend(brand_watches)
            
            # Save after processing
            if brand_watches:
                save_watches_to_json(all_watches)
                logging.info(f"Extracted {len(all_watches)} Rolex watches")
            else:
                logging.warning("No Rolex watches were extracted")
        
        except Exception as e:
            logging.error(f"Error in main process: {e}")
            # Save whatever watches we've collected so far
            if all_watches:
                save_watches_to_json(all_watches)
        
        finally:
            # Clean up
            context.close()
            browser.close()

if __name__ == "__main__":
    main() 