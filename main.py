from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
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
    """Setup Chrome driver untuk Render.com"""
    chrome_options = Options()
    
    # Options untuk production environment
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-images")  # Optional: disable images untuk speed
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Untuk Render.com, kita perlu set binary location
    chrome_options.binary_location = "/usr/bin/google-chrome"
    
    # Setup service dengan ChromeDriver
    service = Service(executable_path="/usr/local/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Hide automation
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
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
        driver.get(url)
        
        # Tunggu sampai page fully loaded
        wait = WebDriverWait(driver, timeout)
        time.sleep(3)  # Tunggu initial load
        
        result = {
            'price': None,
            'product_name': None,
            'original_price': None,
            'discount': None
        }
        
        # 1. Cari harga sale - priority selectors
        price_selectors = [
            "span.pdp-price",
            ".pdp-product-price",
            "span.pdp-v2-price",
            ".final-price",
            "[data-spm*='price']",
            # Fallback selectors
            "span[class*='price']",
            "div[class*='price']"
        ]
        
        for selector in price_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    price_text = element.text.strip()
                    if price_text and any(char.isdigit() for char in price_text):
                        # Filter hanya yang seperti format harga
                        if any(x in price_text for x in ['.', 'Rp', 'rp']):
                            result['price'] = f"Rp {price_text}" if 'Rp' not in price_text else price_text
                            logger.info(f"Harga ditemukan: {result['price']}")
                            break
                if result['price']:
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} gagal: {e}")
                continue
        
        # 2. Cari nama produk
        name_selectors = [
            "h1.pdp-mod-product-badge-title",
            ".pdp-product-title",
            "h1.pdp-title",
            "title",
            "h1[class*='title']",
            "h1[class*='product']"
        ]
        
        for selector in name_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                name_text = element.text.strip()
                if name_text and len(name_text) > 5:  # Minimal 5 karakter
                    result['product_name'] = name_text
                    logger.info(f"Nama produk: {result['product_name']}")
                    break
            except:
                continue
        
        # 3. Cari harga original dan discount
        try:
            original_elements = driver.find_elements(By.CSS_SELECTOR, "[class*='original']")
            for element in original_elements:
                text = element.text.strip()
                if text and any(char.isdigit() for char in text):
                    result['original_price'] = text
                    break
        except:
            pass
        
        # 4. Fallback: cari dengan text pattern
        if not result['price']:
            page_text = driver.page_source
            import re
            # Cari pattern harga Indonesia
            price_patterns = [
                r'Rp\s*[\d.,]+',
                r'[\d.,]+\s*Rp',
                r'\b\d{1,3}(?:\.\d{3})*(?:,\d{2})?\b'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, page_text)
                for match in matches:
                    if any(char.isdigit() for char in match) and len(match) > 4:
                        result['price'] = match
                        logger.info(f"Harga ditemukan via regex: {result['price']}")
                        break
                if result['price']:
                    break
        
        execution_time = round(time.time() - start_time, 2)
        
        if not result['price']:
            logger.warning("Tidak ada harga yang ditemukan")
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
            "health": "GET /health"
        }
    }

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_price(request: ScrapeRequest):
    """Endpoint utama untuk scraping harga"""
    logger.info(f"Received request for URL: {request.url}")
    
    # Validasi URL
    if not request.url.startswith('https://www.lazada.co.id/products/'):
        raise HTTPException(
            status_code=400, 
            detail="URL harus dari Lazada Indonesia (https://www.lazada.co.id/products/...)"
        )
    
    result = scrape_lazada_price(request.url, request.timeout)
    
    if not result['success']:
        raise HTTPException(status_code=404, detail=result['error'])
    
    return result

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Test Chrome setup
        driver = setup_driver()
        driver.quit()
        return {"status": "healthy", "service": "Lazada Scraper API", "chrome": "working"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500

@app.get("/scrape-simple")
async def scrape_simple(url: str):
    """Simple GET endpoint untuk scraping"""
    if not url:
        raise HTTPException(status_code=400, detail="URL parameter required")
    
    result = scrape_lazada_price(url)
    return result

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)