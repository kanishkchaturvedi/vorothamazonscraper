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

    # Initialize main product data structure
    main_product_data = {
        "title": "",
        "price": "",
        "rating": "",
        "reviews_count": "",
        "url": ""
    }

    # Step 1: Try Google search (SERP API) first
    print(f"Step 1: Searching with Google for main product: {brand_name} {model_number}")
    google_result = await search_google_for_amazon_product(brand_name, model_number, product_category, factor)
    
    if google_result:
        # Update main_product_data with any data found from Google
        if google_result.get('title'):
            main_product_data['title'] = google_result['title']
        if google_result.get('price'):
            main_product_data['price'] = google_result['price']
        if google_result.get('rating'):
            main_product_data['rating'] = google_result['rating']
        if google_result.get('reviews_count'):
            main_product_data['reviews_count'] = google_result['reviews_count']
        if google_result.get('url'):
            main_product_data['url'] = google_result['url']
        
        print(f"Google results - Price: {main_product_data['price']}, Rating: {main_product_data['rating']}, Reviews: {main_product_data['reviews_count']}")
    
    # Check if we have all three fields
    has_all_data = all([main_product_data['price'], main_product_data['rating'], main_product_data['reviews_count']])
    if has_all_data:
        print("All data found from Google search. Skipping further steps.")
        main_product = main_product_data
    else:
        # Step 2: Try Amazon search results for missing fields
        print(f"Step 2: Searching Amazon results for missing fields: {brand_name} {model_number}")
        for product in main_products:
            title = product.get('title', '').lower()
            if model_number.lower() in title:
                if product_category and not check_title_category_match(title, product_category):
                    continue
                
                # Update missing fields from Amazon results
                if not main_product_data['title'] and product.get('title'):
                    main_product_data['title'] = product.get('title')
                if not main_product_data['price'] and product.get('price'):
                    main_product_data['price'] = normalize_price_format(product.get('price'))
                if not main_product_data['rating'] and product.get('rating'):
                    main_product_data['rating'] = product.get('rating')
                if not main_product_data['reviews_count'] and product.get('reviews_count'):
                    main_product_data['reviews_count'] = product.get('reviews_count')
                if not main_product_data['url'] and product.get('url'):
                    main_product_data['url'] = f"https://www.amazon.in{product.get('url')}"
                
                print(f"Amazon results - Price: {main_product_data['price']}, Rating: {main_product_data['rating']}, Reviews: {main_product_data['reviews_count']}")
                break
        
        # Check if we have all three fields now
        has_all_data = all([main_product_data['price'], main_product_data['rating'], main_product_data['reviews_count']])
        if has_all_data:
            print("All data found from Amazon search. Skipping Perplexity.")
            main_product = main_product_data
        else:
            # Step 3: Try Perplexity for any remaining missing fields
            print(f"Step 3: Searching with Perplexity for remaining missing fields: {brand_name} {model_number}")
            perplexity_result = search_product_with_perplexity(brand_name, model_number, product_category, factor)
            
            if perplexity_result:
                # Update only missing fields from Perplexity
                if not main_product_data['title'] and perplexity_result.get('title'):
                    main_product_data['title'] = perplexity_result['title']
                if not main_product_data['price'] and perplexity_result.get('price'):
                    main_product_data['price'] = perplexity_result['price']
                if not main_product_data['rating'] and perplexity_result.get('rating'):
                    main_product_data['rating'] = perplexity_result['rating']
                if not main_product_data['reviews_count'] and perplexity_result.get('reviews_count'):
                    main_product_data['reviews_count'] = perplexity_result['reviews_count']
                if not main_product_data['url'] and perplexity_result.get('url'):
                    main_product_data['url'] = perplexity_result['url']
                
                print(f"Perplexity results - Price: {main_product_data['price']}, Rating: {main_product_data['rating']}, Reviews: {main_product_data['reviews_count']}")
            
            # Final check - if we have at least title and URL, use the data
            if main_product_data['title'] or main_product_data['url']:
                main_product = main_product_data
            else:
                print("No product data found from any source")
                main_product = None

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
    Search Google using Serp API for Amazon results and extract product information.
    Returns product information in the same format as the scraper.
    """
    from serpapi import GoogleSearch
    import re
    
    try:
        # Check if Serp API key is set
        serp_api_key = os.getenv('SERP_API_KEY')
        if not serp_api_key:
            print("Warning: SERP_API_KEY environment variable not set, cannot perform Google search.")
            return None
        
        # Construct search query
        search_query = f"{brand_name} {model_number}"
        
        # Setup Serp API parameters
        params = {
            "q": search_query,
            "engine": "google",
            "api_key": serp_api_key,
            "location": "India",
            "hl": "en",
            "gl": "in",
            "num": 10
        }
        
        print(f"Searching Google via Serp API for: {search_query}")
        
        # Make the search request
        search = GoogleSearch(params)
        results = search.get_dict()
        
        if "error" in results:
            print(f"Serp API error: {results['error']}")
            return None
        
        organic_results = results.get("organic_results", [])
        shopping_results = results.get("shopping_results", [])
        
        print(f"Found {len(organic_results)} organic results and {len(shopping_results)} shopping results")
        
        # Debug: Print detailed results
        print("\n=== DEBUG: SERP API Response ===")
        for i, result in enumerate(organic_results[:5]):  # Show first 5 results
            title = result.get('title', 'N/A')
            link = result.get('link', 'N/A')
            source = result.get('source', 'N/A')
            
            print(f"\nResult {i+1}:")
            print(f"  Title: {title}")
            print(f"  Link: {link}")
            print(f"  Source: {source}")
            
            # Check for rich snippet data
            if 'rich_snippet' in result:
                rich_snippet = result['rich_snippet']
                if 'bottom' in rich_snippet and 'detected_extensions' in rich_snippet['bottom']:
                    detected_extensions = rich_snippet['bottom']['detected_extensions']
                    print(f"  Rich Snippet Extensions: {detected_extensions}")
            
            # Check if model number is in title/link
            model_in_title = model_number.upper() in title.upper()
            model_in_link = model_number.upper() in link.upper()
            is_amazon = (source == "Amazon.in" or 'amazon.in' in link or 'amazon.com' in link)
            
            print(f"  Model in title: {model_in_title}")
            print(f"  Model in link: {model_in_link}")
            print(f"  Is Amazon: {is_amazon}")
        
        if shopping_results:
            print(f"\n=== Shopping Results ===")
            for i, result in enumerate(shopping_results[:3]):  # Show first 3 shopping results
                title = result.get('title', 'N/A')
                source = result.get('source', 'N/A')
                price = result.get('price', 'N/A')
                print(f"Shopping {i+1}: {title} | {source} | {price}")
        
        print("=== END DEBUG ===\n")
        
        # First, look for Amazon results in organic results
        amazon_result = None
        best_price = ""
        best_rating = ""
        best_reviews = ""
        
        for result in organic_results:
            link = result.get('link', '')
            title = result.get('title', '')
            snippet = result.get('snippet', '')
            source = result.get('source', '')
            
            # Check if this is an Amazon result (prioritize source field)
            is_amazon_result = (source == "Amazon.in" or 
                              'amazon.in' in link or 
                              'amazon.com' in link)
            
            
            if is_amazon_result:
                print(f"Found Amazon result: {title}")
                amazon_result = result
                
                # Extract data from rich snippet's detected_extensions
                price = ""
                rating = ""
                reviews = ""
                
                if 'rich_snippet' in result:
                    rich_snippet = result['rich_snippet']
                    if 'bottom' in rich_snippet and 'detected_extensions' in rich_snippet['bottom']:
                        detected_extensions = rich_snippet['bottom']['detected_extensions']
                        
                        # Extract price
                        if 'price' in detected_extensions and 'currency' in detected_extensions:
                            price_value = detected_extensions['price']
                            currency = detected_extensions['currency']
                            # Format as integer if it's a whole number
                            if isinstance(price_value, float) and price_value.is_integer():
                                price = f"{currency}{int(price_value):,}"
                            else:
                                price = f"{currency}{price_value:,}"
                        
                        # Extract rating
                        if 'rating' in detected_extensions:
                            rating_value = detected_extensions['rating']
                            rating = f"{rating_value} out of 5 stars"
                        
                        # Extract reviews
                        if 'reviews' in detected_extensions:
                            reviews = str(detected_extensions['reviews'])
                    
                    # Also check extensions array for fallback
                    if 'bottom' in rich_snippet and 'extensions' in rich_snippet['bottom']:
                        extensions = rich_snippet['bottom']['extensions']
                        for extension in extensions:
                            # Look for price pattern
                            if not price and ('₹' in extension or 'INR' in extension or 'Rs' in extension):
                                if not any(word in extension.lower() for word in ['stock', 'स्टॉक', 'out of stock']):
                                    price = extension
                            
                            # Look for rating/review pattern like "4.6(342)"
                            if not rating and not reviews:
                                rating_review_match = re.search(r'(\d+\.?\d*)\((\d+(?:,\d+)*)\)', extension)
                                if rating_review_match:
                                    rating_value = float(rating_review_match.group(1))
                                    rating = f"{rating_value} out of 5 stars"
                                    reviews = rating_review_match.group(2)
                
                # If no price in rich snippet, try extracting from snippet text
                if not price and snippet:
                    price = extract_price_from_snippet(snippet)
                
                best_price = price
                best_rating = rating
                best_reviews = reviews
                break
        
        # If no Amazon result or price found in organic results, check shopping results
        if not amazon_result or not best_price:
            for result in shopping_results:
                title = result.get('title', '')
                source = result.get('source', '')
                price = result.get('price', '')
                
                has_model_shopping = (model_number.upper() in title.upper() or 
                                     model_number.upper() in result.get('link', '').upper())
                is_amazon_shopping = ('amazon' in source.lower() or 'amazon' in result.get('link', '').lower())
                
                if has_model_shopping and is_amazon_shopping:
                    
                    if not amazon_result:
                        amazon_result = result
                        
                        # Extract rating and reviews from shopping result if available
                        if 'rich_snippet' in result:
                            rich_snippet = result['rich_snippet']
                            if 'bottom' in rich_snippet and 'detected_extensions' in rich_snippet['bottom']:
                                detected_extensions = rich_snippet['bottom']['detected_extensions']
                                
                                # Extract rating
                                if 'rating' in detected_extensions and not best_rating:
                                    rating_value = detected_extensions['rating']
                                    best_rating = f"{rating_value} out of 5 stars"
                                
                                # Extract reviews
                                if 'reviews' in detected_extensions and not best_reviews:
                                    best_reviews = str(detected_extensions['reviews'])
                    
                    if price and not best_price:
                        best_price = price
                        print(f"Found price in shopping results: {price}")
                    
                    break
        
        # If still no price, look for price in other results for the same model
        if amazon_result and not best_price:
            print("Looking for price in other results for the same model...")
            
            # First priority: Look for Amazon results with the model number
            for result in organic_results:
                title = result.get('title', '')
                snippet = result.get('snippet', '')
                link = result.get('link', '')
                source = result.get('source', '')
                
                # Check if this is an Amazon result with the model number
                is_amazon = (source == "Amazon.in" or 'amazon.in' in link or 'amazon.com' in link)
                
                if is_amazon:
                    # First check rich snippet for price
                    price = ""
                    if 'rich_snippet' in result:
                        rich_snippet = result['rich_snippet']
                        if 'bottom' in rich_snippet and 'detected_extensions' in rich_snippet['bottom']:
                            detected_extensions = rich_snippet['bottom']['detected_extensions']
                            if 'price' in detected_extensions and 'currency' in detected_extensions:
                                price_value = detected_extensions['price']
                                currency = detected_extensions['currency']
                                price = f"{currency}{price_value:,}"
                    
                    # If no price in rich snippet, try snippet text
                    if not price:
                        price = extract_price_from_snippet(snippet)
                    
                    if price:
                        best_price = price
                        print(f"Found price in Amazon result with model number: {price}")
                        break
            
            # Second priority: If no Amazon result found, collect all prices and find the lowest
            if not best_price:
                all_prices = []
                
                for result in organic_results:
                    title = result.get('title', '')
                    snippet = result.get('snippet', '')
                    link = result.get('link', '')
                    source = result.get('source', '')
                    
                    # Consider results that have the model number in title, link, or snippet
                    has_model_in_result = (model_number.upper() in title.upper() or 
                                         model_number.upper() in link.upper() or 
                                         model_number.upper() in snippet.upper())
                    
                    if has_model_in_result:
                        # Skip if it's already the Amazon result we found (avoid duplicates)
                        if result == amazon_result:
                            continue
                        
                        # Prefer shopping/e-commerce sites for pricing
                        is_shopping_site = any(domain in link.lower() for domain in [
                            'amazon', 'flipkart', 'jiomart', 'snapdeal', 'myntra', 'ajio', 
                            'tatacliq', 'reliancedigital', 'croma', 'vijaysales'
                        ])
                        
                        if is_shopping_site:
                            # First check rich snippet for price
                            price = ""
                            price_value = 0
                            
                            if 'rich_snippet' in result:
                                rich_snippet = result['rich_snippet']
                                if 'bottom' in rich_snippet and 'detected_extensions' in rich_snippet['bottom']:
                                    detected_extensions = rich_snippet['bottom']['detected_extensions']
                                    if 'price' in detected_extensions and 'currency' in detected_extensions:
                                        price_value = detected_extensions['price']
                                        currency = detected_extensions['currency']
                                        # Format as integer if it's a whole number
                                        if isinstance(price_value, float) and price_value.is_integer():
                                            price = f"{currency}{int(price_value):,}"
                                        else:
                                            price = f"{currency}{price_value:,}"
                            
                            # If no price in rich snippet, try snippet text
                            if not price:
                                price = extract_price_from_snippet(snippet)
                                if price:
                                    # Extract numerical value for comparison
                                    price_match = re.search(r'[\d,]+', price.replace('₹', '').replace(',', ''))
                                    if price_match:
                                        try:
                                            price_value = float(price_match.group().replace(',', ''))
                                        except ValueError:
                                            continue
                            
                            if price and price_value > 0:
                                all_prices.append({
                                    'price': price,
                                    'price_value': price_value,
                                    'source': source or link,
                                    'title': title
                                })
                                print(f"Found price: {price} from {source or link}")
                
                # Select the lowest price
                if all_prices:
                    lowest_price_info = min(all_prices, key=lambda x: x['price_value'])
                    best_price = lowest_price_info['price']
                    print(f"Selected lowest price: {best_price} from {lowest_price_info['source']}")
                    print(f"All prices found: {[p['price'] for p in all_prices]}")
        
        # Final fallback: If still no price found, try Perplexity
        if amazon_result and not best_price:
            print("No price found in SERP API results. Falling back to Perplexity...")
            try:
                perplexity_result = search_product_with_perplexity(brand_name, model_number, product_category, factor)
                if perplexity_result and perplexity_result.get('price'):
                    best_price = perplexity_result['price']
                    print(f"Found price via Perplexity: {best_price}")
                else:
                    print("Perplexity also failed to find price")
            except Exception as e:
                print(f"Error getting price from Perplexity: {e}")
        
        # Create product data even if we don't have all fields
        product_data = {
            "title": amazon_result.get('title', '') if amazon_result else '',
            "price": normalize_price_format(best_price),
            "rating": best_rating,
            "reviews_count": best_reviews,
            "url": amazon_result.get('link', '') if amazon_result else ''
        }
        
        # If we have an Amazon result but missing rating/reviews, try extracting from snippet
        if amazon_result and (not best_rating or not best_reviews):
            snippet = amazon_result.get('snippet', '')
            if snippet:
                # Look for rating patterns like "4.4 out of 5 stars" or "4.4/5"
                if not best_rating:
                    rating_patterns = [
                        r'(\d+\.?\d*)\s*out of\s*5\s*stars',
                        r'(\d+\.?\d*)/5',
                        r'(\d+\.?\d*)\s*stars',
                        r'Rating:\s*(\d+\.?\d*)',
                        r'(\d+\.?\d*)\s*★'
                    ]
                    
                    for pattern in rating_patterns:
                        match = re.search(pattern, snippet, re.IGNORECASE)
                        if match:
                            rating_value = float(match.group(1))
                            product_data['rating'] = f"{rating_value} out of 5 stars"
                            break
                
                # Look for review count patterns
                if not best_reviews:
                    review_patterns = [
                        r'\((\d+(?:,\d+)*)\)\s*reviews?',
                        r'(\d+(?:,\d+)*)\s*reviews?',
                        r'(\d+(?:,\d+)*)\s*customer reviews?'
                    ]
                    
                    for pattern in review_patterns:
                        match = re.search(pattern, snippet, re.IGNORECASE)
                        if match:
                            product_data['reviews_count'] = match.group(1)
                            break
        
        print(f"Extracted from Serp API: Price={product_data['price']}, Rating={product_data['rating']}, Reviews={product_data['reviews_count']}")
        
        # Return the product data if we have at least a title or URL (indicating we found the product)
        if product_data['title'] or product_data['url']:
            return product_data
        
        print("No Amazon results found in Serp API search")
        return None
        
    except Exception as e:
        print(f"Error during Serp API search: {e}")
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
                
                # Return the product data if we have any meaningful data (not all null/empty)
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
