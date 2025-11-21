from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium_stealth import stealth
import time
import os
from typing import Optional
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lazada Price Scraper API",
    description="API untuk scraping harga produk dari Lazada",
    version="1.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str
    timeout: Optional[int] = 30

class ScrapeResponse(BaseModel):
    success: bool
    price: Optional[str] = None
    product_name: Optional[str] = None
    original_price: Optional[str] = None
    discount: Optional[str] = None
    error: Optional[str] = None
    execution_time: float

def setup_driver():
    """Setup Chrome driver untuk Render.com tanpa install system packages"""
    chrome_options = Options()
    
    # Options untuk Render.com
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-images")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Gunakan webdriver-manager untuk auto-download ChromeDriver
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Apply stealth settings
    stealth(driver,
        languages=["en-US", "en"],
        vendor="Google Inc.",
        platform="Win32",
        webgl_vendor="Intel Inc.",
        renderer="Intel Iris OpenGL Engine",
        fix_hairline=True,
    )
    
    return driver

def scrape_lazada_price(url: str, timeout: int = 30):
    """Function utama untuk scraping harga Lazada"""
    start_time = time.time()
    driver = None
    
    try:
        logger.info(f"Memulai scraping untuk URL: {url}")
        driver = setup_driver()
        
        # Set timeouts
        driver.set_page_load_timeout(timeout)
        driver.implicitly_wait(10)
        
        # Buka URL
        logger.info("Membuka URL...")
        driver.get(url)
        
        # Tunggu sampai page fully loaded
        time.sleep(5)
        
        result = {
            'price': None,
            'product_name': None,
            'original_price': None,
            'discount': None
        }
        
        # 1. Cari harga dengan multiple strategies
        logger.info("Mencari harga...")
        
        # Strategy 1: CSS Selectors
        price_selectors = [
            "span.pdp-price",
            ".pdp-product-price",
            "span.pdp-v2-price",
            ".final-price",
            "[data-spm*='price']",
            "span[class*='price']",
            "div[class*='price']"
        ]
        
        for selector in price_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    price_text = element.text.strip()
                    if price_text and any(char.isdigit() for char in price_text):
                        # Clean price text
                        cleaned_price = price_text.replace('Rp', '').replace(' ', '').strip()
                        if '.' in cleaned_price or ',' in cleaned_price:
                            result['price'] = f"Rp {cleaned_price}"
                            logger.info(f"Harga ditemukan via CSS: {result['price']}")
                            break
                if result['price']:
                    break
            except Exception as e:
                continue
        
        # Strategy 2: XPath
        if not result['price']:
            xpath_selectors = [
                "//span[contains(text(), 'Rp')]",
                "//*[contains(text(), 'Rp')]",
                "//span[contains(@class, 'price')]",
                "//div[contains(@class, 'price')]"
            ]
            
            for xpath in xpath_selectors:
                try:
                    elements = driver.find_elements(By.XPATH, xpath)
                    for element in elements:
                        price_text = element.text.strip()
                        if price_text and any(char.isdigit() for char in price_text):
                            result['price'] = price_text
                            logger.info(f"Harga ditemukan via XPath: {result['price']}")
                            break
                    if result['price']:
                        break
                except:
                    continue
        
        # 2. Cari nama produk
        logger.info("Mencari nama produk...")
        name_selectors = [
            "h1.pdp-mod-product-badge-title",
            ".pdp-product-title",
            "h1.pdp-title",
            "title",
            "h1"
        ]
        
        for selector in name_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                name_text = element.text.strip()
                if name_text and len(name_text) > 5:
                    result['product_name'] = name_text
                    logger.info(f"Nama produk ditemukan: {result['product_name']}")
                    break
            except:
                continue
        
        # 3. Cari harga original
        try:
            original_selectors = [
                "span.pdp-v2-product-price-content-originalPrice-amount",
                ".original-price",
                "[class*='originalPrice']"
            ]
            for selector in original_selectors:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                    result['original_price'] = element.text.strip()
                    break
                except:
                    continue
        except:
            pass
        
        # 4. Cari discount
        try:
            discount_selectors = [
                "span.pdp-v2-product-price-content-originalPrice-discount",
                ".discount",
                "[class*='discount']"
            ]
            for selector in discount_selectors:
                try:
                    element = driver.find_element(By.CSS_SELECTOR, selector)
                    result['discount'] = element.text.strip()
                    break
                except:
                    continue
        except:
            pass
        
        execution_time = round(time.time() - start_time, 2)
        
        if not result['price']:
            logger.warning("Tidak ada harga yang ditemukan")
            # Fallback: cari angka yang mirip harga di seluruh page
            page_text = driver.page_source
            import re
            price_matches = re.findall(r'\b\d{1,3}(?:\.\d{3})+\b', page_text)
            if price_matches:
                result['price'] = f"Rp {price_matches[0]}"
                logger.info(f"Harga ditemukan via regex fallback: {result['price']}")
            else:
                return {
                    'success': False,
                    'error': 'Price not found on the page',
                    'execution_time': execution_time
                }
        
        return {
            'success': True,
            **result,
            'execution_time': execution_time
        }
        
    except Exception as e:
        logger.error(f"Error selama scraping: {str(e)}")
        execution_time = round(time.time() - start_time, 2)
        return {
            'success': False,
            'error': str(e),
            'execution_time': execution_time
        }
    finally:
        if driver:
            driver.quit()

@app.get("/")
async def root():
    return {
        "message": "Lazada Price Scraper API", 
        "status": "running",
        "version": "1.0.0",
        "endpoints": {
            "scrape": "POST /scrape",
            "scrape_simple": "GET /scrape-simple?url=URL",
            "health": "GET /health"
        }
    }

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_price(request: ScrapeRequest):
    """Endpoint utama untuk scraping harga"""
    logger.info(f"Received request for URL: {request.url}")
    
    # Validasi URL
    if not request.url.startswith(('https://www.lazada.co.id/products/', 'http://www.lazada.co.id/products/')):
        raise HTTPException(
            status_code=400, 
            detail="URL harus dari Lazada Indonesia (https://www.lazada.co.id/products/...)"
        )
    
    result = scrape_lazada_price(request.url, request.timeout)
    
    if not result['success']:
        raise HTTPException(status_code=404, detail=result['error'])
    
    return result

@app.get("/scrape-simple")
async def scrape_simple(url: str):
    """Simple GET endpoint untuk scraping"""
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter required")
    
    if not url.startswith(('https://www.lazada.co.id/products/', 'http://www.lazada.co.id/products/')):
        raise HTTPException(status_code=400, detail="URL harus dari Lazada Indonesia")
    
    result = scrape_lazada_price(url)
    return result

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "Lazada Scraper API",
        "timestamp": time.time()
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)