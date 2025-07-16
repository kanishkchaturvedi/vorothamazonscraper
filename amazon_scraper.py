from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig, ProxyConfig
import json
import asyncio
import os
from dotenv import load_dotenv
import google.generativeai as genai
import random
import string
import requests
import uuid
import re
from bs4 import BeautifulSoup

def generate_session_id():
    return f"SESSION_{uuid.uuid4().hex[:8].upper()}"

def extract_price_from_snippet(snippet):
    """
    Extract price information from Google search result snippet text.
    Handles various price formats like ₹23,490.00, ₹23490, etc.
    """
    if not snippet:
        return ""
    
    # Pattern to match Indian Rupee prices
    # Matches: ₹23,490.00, ₹23490, ₹23,490, etc.
    price_patterns = [
        r'₹\s*[\d,]+\.?\d*',  # ₹23,490.00 or ₹23490
        r'Rs\.?\s+[\d,]+\.?\d*',  # Rs. 23,490.00 or Rs 23490 (requires space after Rs)
        r'INR\s+[\d,]+\.?\d*',  # INR 23,490.00 (requires space)
        r'\b[\d,]+\.?\d*\s*(?:rupees?|INR)\b',  # 23,490 rupees or 23490 INR
        r'\b[\d]{3,}(?:,\d{3})*(?:\.\d{2})?\b',  # Plain numbers like 7,399 or 11,088 (3+ digits)
    ]
    
    for pattern in price_patterns:
        matches = re.findall(pattern, snippet, re.IGNORECASE)
        if matches:
            for match in matches:
                price = match.strip()
                
                # Skip if it's part of resolution (like 1366x768) or technical specs
                if 'x' in price or 'hz' in price.lower() or 'degree' in price.lower():
                    continue
                
                # Check context around the number for resolution or technical specs
                # Find the position of this price in the original snippet
                price_index = snippet.lower().find(price.lower())
                if price_index != -1:
                    # Check surrounding context (10 characters before and after)
                    context_start = max(0, price_index - 10)
                    context_end = min(len(snippet), price_index + len(price) + 10)
                    context = snippet[context_start:context_end].lower()
                    
                    # Skip if it's part of resolution, technical specs, or model numbers
                    if any(keyword in context for keyword in ['x', 'hz', 'degree', 'pixel', 'resolution', 'refresh', 'display', 'model']):
                        continue
                
                # For plain numbers, ensure they're likely prices (reasonable price range)
                if price.replace(',', '').replace('.', '').isdigit():
                    price_value = float(price.replace(',', ''))
                    # Skip if too small (like 60 hertz) or too large (like 1366 resolution)
                    # Indian TV prices typically range from 5000 to 200000
                    if price_value < 1000 or price_value > 200000:
                        continue
                
                # Clean up the price (remove extra spaces, etc.)
                price = re.sub(r'\s+', ' ', price)
                return price
    
    return ""

def extract_price_from_html(html_content):
    """
    Extract price information from raw HTML content by finding spans with rupee symbols.
    This navigates through the div structure to find price spans.
    """
    if not html_content:
        return ""
    
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for spans containing rupee symbols
        price_patterns = [r'₹[\d,]+\.?\d*', r'Rs\.?\s*[\d,]+\.?\d*', r'INR\s*[\d,]+\.?\d*']
        
        # Find all spans
        spans = soup.find_all('span')
        
        for span in spans:
            text = span.get_text(strip=True)
            for pattern in price_patterns:
                matches = re.findall(pattern, text, re.IGNORECASE)
                if matches:
                    price = matches[0].strip()
                    # Verify this looks like a valid price (not just a random rupee symbol)
                    if len(price) > 2 and any(c.isdigit() for c in price):
                        return price
        
        return ""
    except Exception as e:
        return ""

def rotate_session(api_key, session_id, product_type):
    url = "https://api.evomi.com/public/rotate_session"
    headers = {"x-apikey": api_key}
    params = {
        "sessionid": session_id,
        "product": product_type
    }
    
    response = requests.get(url, headers=headers, params=params)

# Load environment variables
load_dotenv()

Evomi_api_key = os.getenv('EVOMI_API_KEY')
if not Evomi_api_key:
    raise ValueError("EVOMI_API_KEY environment variable is not set")

# Set API Key from environment variable
api_key = os.getenv('GEMINI_API_KEY')
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set")

genai.configure(api_key=api_key)

# Create a model instance
gemini_model = genai.GenerativeModel("gemini-1.5-pro")

def check_title_category_match(title: str, expected_category: str) -> bool:
    prompt = (
        f"Given the product title:\n\"{title}\"\n"
        f"Does this product title refer to a product in the category '{expected_category}'?\n"
        f"Important rules:\n"
        f"1. Exclude accessories, parts, covers, or any add-on items\n"
        f"2. Only include actual products in the category\n"
        f"3. For example:\n"
        f"   - For 'Washing Machine': exclude covers, lids, parts, or accessories\n"
        f"   - For 'Air Conditioner': exclude covers, stands, or installation parts\n"
        f"   - For 'Refrigerator': exclude covers, shelves, or replacement parts\n"
        f"   - For 'Television': exclude stands, mounts, or remote covers\n"
        f"4. If the product is an accessory or part, answer 'no'\n"
        f"5. If unsure, answer 'no'\n"
        f"\n"
        f"Answer only 'yes' or 'no' without any explanation."
    )

    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip().lower()
        print(f"Gemini category match response: {result}")
        return "yes" in result
    except Exception as e:
        print(f"Error during Gemini classification: {e}")
        return False

def format_factor(product_category, factor, FACTOR_LABELS):
    if product_category == "Mobiles & Tablets":
        try:
            ram, storage = factor.split(',')
            return f"{ram}GB RAM {storage}GB Storage"
        except ValueError:
            return factor  # fallback if unexpected format
    else:
        unit = FACTOR_LABELS.get(product_category, "")
        return f"{factor} {unit}".strip()


async def extract_amazon_products(product_category, model_number, brand, factor):
    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",  # Still used for reference
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    proxy_config_evomi = ProxyConfig(
        server="http://core-residential.evomi.com:1000",
        username="kanishkcha5",
        password="vdYFqTHTs8nCeYHqLEKY",
    )

    session_id = generate_session_id()
    rotate_session(Evomi_api_key, session_id, "rpc")

    browswer_config = BrowserConfig(proxy_config=proxy_config_evomi)

    # Build query for main product
    factor_with_unit = format_factor(product_category, factor, FACTOR_LABELS)
    main_query = f"{brand} {factor_with_unit} {product_category} {model_number}".replace(' ', '+')
    main_url = f"https://www.amazon.in/s?k={main_query}"

    # Build query for competitors
    competitor_query = f"{factor_with_unit} {product_category}".replace(' ', '+')
    competitor_url = f"https://www.amazon.in/s?k={competitor_query}"

    crawler_config = CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(
            schema={
                "name": "Amazon product search result",
                "baseSelector": "[data-component-type='s-search-result']",
                "fields": [
                    {"name": "title", "selector": "h2 span", "type": "text"},
                    {"name": "reviews_count", "selector": ".a-size-base", "type": "text"},
                    {"name": "rating", "selector": ".a-icon-star-small .a-icon-alt", "type": "text"},
                    {"name": "price", "selector": ".a-price .a-offscreen", "type": "text"},
                    {"name": "url", "selector": ".a-link-normal", "type": "attribute", "attribute": "href"}
                ]
            }
        )
    )

    try:
        print(f"Starting extraction for: {brand} {factor} {product_category} {model_number}")
        async with AsyncWebCrawler(config=browswer_config) as crawler:
            # Get main product results
            main_result = await crawler.arun(url=main_url, config=crawler_config, cache_mode=CacheMode.BYPASS)
            main_products = json.loads(main_result.extracted_content) if main_result and main_result.extracted_content else []

            # Get competitor results
            competitor_result = await crawler.arun(url=competitor_url, config=crawler_config, cache_mode=CacheMode.BYPASS)
            competitor_products = json.loads(competitor_result.extracted_content) if competitor_result and competitor_result.extracted_content else []

            return main_products, competitor_products
    except Exception as e:
        print(f"Error during extraction: {e}")
        return [], []



async def classify_products(main_products, competitor_products, model_number, brand_name, product_category=None, factor=None):
    main_product = None
    competitors = []

    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    def title_has_factor(title: str, factor: str, unit: str) -> bool:
        title = title.lower()
        factor = str(factor).lower()
        return factor in title or (f"{factor} {unit}".lower() in title)

    unit = FACTOR_LABELS.get(product_category, "")
    factor_clean = factor.lower() if factor else ""

    # Priority 1: Try Google search first for main product
    print(f"Searching with Google for main product: {brand_name} {model_number}")
    main_product = await search_google_for_amazon_product(brand_name, model_number, product_category, factor)
    
    # Priority 2: If Google fails, try Amazon search results
    if main_product is None:
        print(f"Google search failed. Searching Amazon results for: {brand_name} {model_number}")
        for product in main_products:
            title = product.get('title', '').lower()
            if model_number.lower() in title:
                if product_category and not check_title_category_match(title, product_category):
                    continue
                main_product = product
                main_product['url'] = f"https://www.amazon.in{product.get('url')}"
                # Normalize price format for consistency
                if main_product.get('price'):
                    main_product['price'] = normalize_price_format(main_product['price'])
                break
    
    # Priority 3: If both Google and Amazon fail, use Perplexity as final fallback
    if main_product is None:
        print(f"Amazon search also failed. Searching with Perplexity for: {brand_name} {model_number}")
        main_product = search_product_with_perplexity(brand_name, model_number, product_category, factor)

    # If we found a main product, use its title for type matching
    main_product_title = main_product.get('title', '') if main_product else None

    # Find competitors from competitor_products
    for product in competitor_products:
        title = product.get('title', '').lower()

        if brand_name.lower() in title:
            continue
        if product_category and not check_title_category_match(title, product_category):
            continue
        if factor and not title_has_factor(title, factor_clean, unit):
            continue
        # Add new check for product type matching
        if main_product_title and not check_product_type_match(title, main_product_title):
            continue

        important_fields = ['title', 'price', 'rating', 'reviews_count', 'url']
        if any(product.get(field) is None for field in important_fields):
            continue

        product['url'] = f"https://www.amazon.in{product.get('url')}"
        # Normalize price format for consistency
        if product.get('price'):
            product['price'] = normalize_price_format(product['price'])
        competitors.append(product)

        if len(competitors) == 5:
            break

    return main_product, competitors

def check_product_type_match(title: str, main_product_title: str) -> bool:
    prompt = (
        f"Given two product titles:\n"
        f"1. Main product: \"{main_product_title}\"\n"
        f"2. Potential competitor: \"{title}\"\n"
        f"Are these products of the same type/subtype? Consider these rules:\n"
        f"- For washing machines:\n"
        f"  * Semi-automatic should ONLY match with semi-automatic\n"
        f"  * Fully automatic should ONLY match with fully automatic\n"
        f"  * Front load should ONLY match with front load\n"
        f"  * Top load should ONLY match with top load\n"
        f"- For ACs:\n"
        f"  * Window AC should ONLY match with window AC\n"
        f"  * Split AC should ONLY match with split AC\n"
        f"- For vacuum cleaners:\n"
        f"  * Cordless should ONLY match with cordless\n"
        f"  * Robotic should ONLY match with robotic\n"
        f"  * Bagged should ONLY match with bagged\n"
        f"  * Bagless should ONLY match with bagless\n"
        f"- For refrigerators:\n"
        f"  * Single door should ONLY match with single door\n"
        f"  * Double door should ONLY match with double door\n"
        f"  * Side by side should ONLY match with side by side\n"
        f"\n"
        f"Important rules:\n"
        f"1. Different types should not match (e.g., semi-automatic should not match with fully automatic)\n"
        f"2. If the main product has multiple type indicators (e.g., 'semi-automatic top load'), both must match\n"
        f"3. If unsure, answer 'no'\n"
        f"\n"
        f"Answer only 'yes' or 'no' without any explanation."
    )

    try:
        response = gemini_model.generate_content(prompt)
        result = response.text.strip().lower()
        print(f"Gemini type match response: {result}")
        return "yes" in result
    except Exception as e:
        print(f"Error during Gemini type matching: {e}")
        return False

async def search_google_for_amazon_product(brand_name, model_number, product_category, factor):
    """
    Search Google for Amazon results and extract product information from search snippets.
    Returns product information in the same format as the scraper.
    """
    import re
    
    try:
        # Construct Google search URL with better query
        search_query = f"{model_number}"
        google_search_url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
        
        # Use the same proxy configuration as Amazon scraping
        proxy_config_evomi = ProxyConfig(
            server="http://core-residential.evomi.com:1000",
            username="kanishkcha5",
            password="vdYFqTHTs8nCeYHqLEKY",
        )
        
        session_id = generate_session_id()
        rotate_session(Evomi_api_key, session_id, "rpc")
        
        browser_config = BrowserConfig(
            proxy_config=proxy_config_evomi,
        )
        
        # Create extraction strategy for Google search results
        google_extraction_config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(
                schema={
                    "name": "Google search results",
                    "baseSelector": "div.srKDX",
                    "fields": [
                        {"name": "title", "selector": "h3", "type": "text"},
                        {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
                        {"name": "snippet", "selector": "div.VwiC3b", "type": "text"},
                        {"name": "price", "selector": "span.LI0TWe, span.wHYlTd", "type": "text"},
                        {"name": "rating", "selector": "span.yi40Hd.YrbPuc, span.yi40Hd, span.YrbPuc", "type": "text"},
                        {"name": "review_count", "selector": "span.RDApEe.YrbPuc, span.RDApEe", "type": "text"}
                    ]
                }
            )
        )
        
        print(f"Searching Google for: {google_search_url}")
        
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun(url=google_search_url, config=google_extraction_config, cache_mode=CacheMode.BYPASS)
            
            if not result:
                print("No result object from Google search")
                return None
            
            # Check if Google is blocking requests
            if hasattr(result, 'html') and result.html:
                if "unusual traffic" in result.html.lower() or "captcha" in result.html.lower():
                    print("WARNING: Google may be blocking requests due to unusual traffic")
            
            if not result.extracted_content:
                print("No extracted content from Google search")
                print(f"Result status: {getattr(result, 'status', 'Unknown')}")
                return None
                
            try:
                search_results = json.loads(result.extracted_content)
                print(f"Found {len(search_results)} Google search results")
                
                # Debug: Print first few results to see structure
                for i, result_item in enumerate(search_results[:3]):
                    print(f"Result {i+1}: {result_item}")
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON: {e}")
                print(f"Raw content: {result.extracted_content[:500]}...")  # Show first 500 chars
                return None
            
            # If no results with current selector, try alternative approach
            if len(search_results) == 0:
                print("Trying alternative selectors...")
                alternative_config = CrawlerRunConfig(
                    extraction_strategy=JsonCssExtractionStrategy(
                        schema={
                            "name": "Google search results alternative",
                            "baseSelector": "div.g, div.tF2Cxc, div.srKDX, div.MjjYud, div.jC6vSe",
                            "fields": [
                                {"name": "title", "selector": "h3", "type": "text"},
                                {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
                                {"name": "snippet", "selector": "div.VwiC3b, .IsZvec, span", "type": "text"},
                                {"name": "price", "selector": "span.LI0TWe, span.wHYlTd", "type": "text"},
                                {"name": "rating", "selector": "span.yi40Hd.YrbPuc, span.yi40Hd, span.YrbPuc, span[class*='rating']", "type": "text"},
                                {"name": "review_count", "selector": "span.RDApEe.YrbPuc, span.RDApEe, span[class*='review']", "type": "text"}
                            ]
                        }
                    )
                )
                result = await crawler.arun(url=google_search_url, config=alternative_config, cache_mode=CacheMode.BYPASS)
                if result and result.extracted_content:
                    search_results = json.loads(result.extracted_content)
                    print(f"Alternative extraction found {len(search_results)} results")
            
            # First, collect all results and look for price information
            amazon_result = None
            best_price = ""
            
            for result in search_results:
                url = result.get('url', '')
                title = result.get('title', '')
                
                # Check if this is an Amazon result
                if ('amazon.in' in url or 'amazon.com' in url) and (model_number.upper() in title.upper() or model_number.upper() in url.upper()):
                    print(f"Found Amazon result: {title}")
                    amazon_result = result
                    
                    # Extract price, rating, and reviews from the result
                    price = result.get('price', '').strip()
                    rating = result.get('rating', '').strip()
                    review_count = result.get('review_count', '').strip()
                    
                    # If price not found in dedicated field, try multiple fallback methods
                    if not price:
                        # First try extracting from snippet
                        snippet = result.get('snippet', '')
                        price = extract_price_from_snippet(snippet)
                        
                        # If still no price, try extracting from raw HTML (if available)
                        if not price and hasattr(result, 'raw_html') and result.raw_html:
                            price = extract_price_from_html(result.raw_html)
                    
                    best_price = price
                    break
            
            # If we found an Amazon result but no price, look for price in other results for the same model
            if amazon_result and not best_price:
                print("Looking for price in other results for the same model...")
                for i, result in enumerate(search_results):
                    title = result.get('title', '')
                    price = result.get('price', '').strip()
                    snippet = result.get('snippet', '')
                    
                    if model_number.upper() in title.upper() and price:
                        best_price = price
                        break
                    elif model_number.upper() in title.upper() and not price:
                        # Try extracting from snippet for this result too
                        snippet_price = extract_price_from_snippet(snippet)
                        if snippet_price:
                            best_price = snippet_price
                            break
                    
                    # Also check if snippet contains model number and has price info
                    elif model_number.upper() in snippet.upper():
                        snippet_price = extract_price_from_snippet(snippet)
                        if snippet_price:
                            best_price = snippet_price
                            break
            
            if amazon_result:
                # Use the Amazon result but with the best price found
                price = best_price
                rating = amazon_result.get('rating', '').strip()
                review_count = amazon_result.get('review_count', '').strip()
                
                print(f"Raw extracted data: Price='{price}', Rating='{rating}', Reviews='{review_count}'")
                

                
                # Clean up review count (remove parentheses)
                if review_count:
                    review_count = review_count.replace('(', '').replace(')', '')
                
                # Format rating properly
                if rating:
                    try:
                        # Handle comma decimal separator (European format)
                        rating_clean = rating.replace(',', '.')
                        rating_value = float(rating_clean)
                        rating = f"{rating_value} out of 5 stars"
                    except ValueError:
                        rating = ""
                
                # Create product data
                product_data = {
                    "title": amazon_result.get('title', ''),
                    "price": normalize_price_format(price),
                    "rating": rating,
                    "reviews_count": review_count,
                    "url": amazon_result.get('url', '')
                }
                
                print(f"Extracted from Google: Price={price}, Rating={rating}, Reviews={review_count}")
                return product_data
            
            print("No Amazon results found in Google search")
            return None
            
    except Exception as e:
        print(f"Error during Google search: {e}")
        return None

def search_product_with_perplexity(brand_name, model_number, product_category, factor):
    """
    Search for product information using Perplexity when the product is not found in Amazon search results.
    Returns product information in the same format as the scraper.
    """
    FACTOR_LABELS = {
        "Home Audio": "",
        "Television": "inch",
        "Mobiles & Tablets": "RAM and Storage",
        "Fans": "MM",
        "Coolers": "L",
        "Mixer Grinders": "Watt",
        "Water Purifiers": "L",
        "Vacuum Cleaners": "Watts",
        "Air Fryers": "Watts",
        "Geysers": "L",
        "Irons": "Watt",
        "Kettles": "L",
        "Sandwich Makers": "Watt",
        "Dishwashers": "L",
        "Air Conditioners": "Tonnage",
        "Microwave Ovens": "L",
        "Refrigerators": "L",
        "Washing Machine": "Kg",
        "Chimneys": "m3/hr",
    }

    factor_with_unit = format_factor(product_category, factor, FACTOR_LABELS)

    print(f"{brand_name} {model_number} {factor_with_unit} {product_category}")
    
    prompt = (
        f"Search the web for the current price, ratings and reviews for {brand_name} {model_number} {factor_with_unit} {product_category}. "
        f"Find the actual current information and return it in this exact JSON format:\n"
        f"{{\n"
        f"  \"reviews_count\": \"[actual number of reviews]\",\n"
        f"  \"rating\": \"[actual rating out of 5 stars]\",\n"
        f"  \"price\": \"[actual current price in INR]\"\n"
        f"}}\n\n"
        f"Important: Search for the real current data, not example data. If not found, return null for all fields."
    )

    try:
        # Check if API key is set
        perplexity_api_key = os.getenv('PERPLEXITY_API_KEY')
        if not perplexity_api_key:
            print("Error: PERPLEXITY_API_KEY environment variable is not set")
            return None
        
        # Perplexity API endpoint
        url = "https://api.perplexity.ai/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {perplexity_api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "sonar",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": 150
        }
        
        print(f"Making Perplexity API request with model: {data['model']}")
        response = requests.post(url, headers=headers, json=data)
        
        # Better error handling for API responses
        if response.status_code == 400:
            print(f"Perplexity API 400 Error: {response.text}")
            return None
        elif response.status_code == 401:
            print("Perplexity API 401 Error: Invalid API key")
            return None
        elif response.status_code == 429:
            print("Perplexity API 429 Error: Rate limit exceeded")
            return None
        
        response.raise_for_status()  # Raise an exception for other bad status codes
        
        result_text = response.json()["choices"][0]["message"]["content"].strip()
        
        print(f"Perplexity raw response: {result_text}")
        
        # Handle responses wrapped in markdown code blocks
        if result_text.startswith('```json'):
            # Remove the markdown code block wrapper
            result_text = result_text.replace('```json', '').replace('```', '').strip()
        elif result_text.startswith('```'):
            # Remove generic markdown code block wrapper
            result_text = result_text.replace('```', '').strip()
        
        # Try to extract JSON from the response - look for the first complete JSON object
        json_start = result_text.find('{')
        json_end = result_text.rfind('}')
        
        if json_start != -1 and json_end != -1 and json_end > json_start:
            # Extract just the JSON part
            json_text = result_text[json_start:json_end + 1]
            try:
                product_data = json.loads(json_text)
                
                # Construct the complete product data with title and URL
                complete_product_data = {
                    "title": f"{brand_name} {model_number}",
                    "price": normalize_price_format(product_data.get('price') or ""),
                    "rating": normalize_rating_format(product_data.get('rating') or ""),
                    "reviews_count": product_data.get('reviews_count') or "",
                    "url": ""  # Keep URL blank as requested
                }
                
                # Convert "null" strings to blank strings
                for key in ['price', 'rating', 'reviews_count']:
                    if complete_product_data[key] == "null":
                        complete_product_data[key] = ""
                
                # Check if we got any meaningful data (not all null/empty)
                has_data = any(product_data.get(field) and product_data.get(field) != "null" for field in ['price', 'rating', 'reviews_count'])
                
                if has_data:
                    print(f"Found product via Perplexity: {complete_product_data.get('title', 'Unknown')}")
                    return complete_product_data
                else:
                    print("No product data found via Perplexity")
                    return None
            except json.JSONDecodeError as e:
                print(f"Error parsing extracted JSON: {e}")
                return None
        else:
            print("No valid JSON object found in Perplexity response")
            return None
            
    except json.JSONDecodeError as e:
        print(f"Error parsing Perplexity JSON response: {e}")
        return None
    except Exception as e:
        print(f"Error during Perplexity product search: {e}")
        return None

def normalize_rating_format(rating):
    """
    Normalize rating format to 'xx out of 5 stars' format.
    Handles various input formats like '4.5/5', '4.5/5 stars', '4.5 out of 5', etc.
    Returns blank if the rating is descriptive text instead of a number.
    """
    if not rating:
        return ""
    
    rating = str(rating).strip()
    
    # If rating contains descriptive text instead of numbers, return blank
    descriptive_phrases = [
        "not explicitly provided",
        "not available",
        "not found",
        "generally rated well",
        "based on the context",
        "no rating",
        "unavailable"
    ]
    
    rating_lower = rating.lower()
    for phrase in descriptive_phrases:
        if phrase in rating_lower:
            return ""
    
    # Handle "xx/5 stars" format
    if "/5" in rating:
        # Extract the number before "/5"
        parts = rating.split("/5")
        if parts and parts[0]:
            try:
                rating_value = parts[0].strip()
                return f"{rating_value} out of 5 stars"
            except:
                pass
    
    # Handle "xx out of 5" format (already correct)
    if "out of 5" in rating:
        if "stars" not in rating:
            return f"{rating} stars"
        return rating
    
    # Handle just numbers (assume out of 5)
    try:
        rating_value = float(rating)
        if 0 <= rating_value <= 5:
            return f"{rating_value} out of 5 stars"
    except:
        pass
    
    # If no pattern matches and it's not a number, return blank
    return ""

def normalize_price_format(price):
    """
    Normalize price format to ₹xx,xxx format for consistency.
    Handles various input formats like '6499,00 INR', '₹11,990', 'Rs. 23,490', etc.
    """
    if not price:
        return ""
    
    price = str(price).strip()
    
    # Remove common currency indicators and clean up
    price = price.replace('INR', '').replace('Rs.', '').replace('Rs', '').strip()
    
    # Extract numbers and decimal/comma separators
    # Handle European format (6499,00) and Indian format (6,499.00)
    import re
    
    # Find all numbers, commas, and dots
    numbers = re.findall(r'[\d,\.]+', price)
    
    if not numbers:
        return price  # Return as-is if no numbers found
    
    number_part = numbers[0]
    
    # Handle European decimal format (6499,00 -> 6499.00)
    if ',' in number_part and '.' not in number_part:
        # Check if comma is likely a decimal separator (2 digits after comma)
        parts = number_part.split(',')
        if len(parts) == 2 and len(parts[1]) == 2:
            # This is likely a decimal separator
            number_part = parts[0] + '.' + parts[1]
    
    # Convert to float and back to remove unnecessary decimals
    try:
        price_value = float(number_part.replace(',', ''))
        
        # Format with Indian number system (lakhs, crores)
        if price_value >= 10000000:  # 1 crore
            formatted = f"₹{price_value:,.0f}"
        elif price_value >= 100000:  # 1 lakh
            formatted = f"₹{price_value:,.0f}"
        else:
            formatted = f"₹{price_value:,.0f}"
        
        return formatted
    except ValueError:
        # If conversion fails, try to add ₹ symbol if not present
        if not price.startswith('₹'):
            return f"₹{price}"
        return price
