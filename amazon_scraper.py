from crawl4ai import AsyncWebCrawler, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
import json
import asyncio


async def extract_amazon_products(product_name):
    browswer_config = BrowserConfig(
        browser_type="chromium",
        headless=True
    )
    url = f"https://www.amazon.in/s?k={product_name.replace(' ', '+')}"


    crawler_config = CrawlerRunConfig(
        extraction_strategy= JsonCssExtractionStrategy(
            schema={
                "name": "Amazon product search result",
                "baseSelector": "[data-component-type='s-search-result']",
                "fields": [

                    {
                        "name": "title",
                        "selector":"h2 span",
                        "type": "text"

                    },
                    {
                        "name": "reviews_count",
                        "selector": ".a-size-base",
                        "type": "text"
                    },
                    {
                        "name": "rating",
                        "selector": ".a-icon-star-small .a-icon-alt",
                        "type": "text"
                    },
                    
                    {
                        "name": "price",
                        "selector": ".a-price .a-offscreen",
                        "type": "text"
                    },
                    {
                        "name": "url",
                        "selector": ".a-link-normal",
                        "type": "attribute",
                        "attribute":"href"
                    }
                ]
            }
        )
    )

    try:
        print(f"Starting extraction for: {product_name}")
        async with AsyncWebCrawler(config=browswer_config) as crawler:
            print("Crawler initialized.")
            result = await crawler.arun(url=url, config=crawler_config, cache_mode=CacheMode.BYPASS)
            print("Extraction completed.")
            if result and result.extracted_content:
                products = json.loads(result.extracted_content)
                print(f"Extracted {len(products)} products.")
                return products
            else:
                print("No products found or extraction failed.")
                return []
    except Exception as e:
        print(f"Error during extraction: {e}")
        return []

def classify_products(products, model_number, brand_name):
    main_product = None
    competitors = []

    # Step 1: Find the main product
    for product in products:
        title = product.get('title').lower()
        if model_number.lower() in title:
            main_product = product
            main_product['url'] = f"https://www.amazon.in{product.get('url')}"            
            break

    # Step 2: Get top 5 competitors
    for product in products:
        # Skip if same brand
        if brand_name.lower() in product.get('title').lower():
            continue
        
        # Ensure important fields are not None (you can adjust this list as needed)
        important_fields = ['title', 'price', 'rating', 'reviews_count', 'url']
        if any(product.get(field) is None for field in important_fields):
            continue
        
        product['url'] = f"https://www.amazon.in{product.get('url')}"
        competitors.append(product)

        if len(competitors) == 5:
            break

    return main_product, competitors


# def search_product_on_amazon(product_name, model_number, brand):
#     products = extract_amazon_products(product_name)
#     return classify_products(products, model_number, brand)

