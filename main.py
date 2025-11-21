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
import time
import os
from typing import Optional
import logging
import re

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Lazada Price Scraper API",
    description="API untuk scraping harga produk dari Lazada",
    version="2.0.0"
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
    
    # Options untuk production
    chrome_options.add_argument("--headless=new")  # New headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    # User agent realistic
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Gunakan webdriver-manager
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Execute script to hide automation
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

def extract_price_from_text(text):
    """Extract price from text using regex"""
    # Pattern untuk harga Indonesia: Rp 240.000 atau 240.000
    patterns = [
        r'Rp\s*(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)',
        r'(\d{1,3}(?:\.\d{3})*(?:,\d{2})?)\s*Rp',
        r'\b(\d{1,3}(?:\.\d{3})+)\b'
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if match and '.' in match:  # Pastikan format ada titik (240.000)
                return f"Rp {match}"
    return None

def scrape_lazada_price(url: str, timeout: int = 30):
    """Function utama untuk scraping harga Lazada"""
    start_time = time.time()
    driver = None
    
    try:
        logger.info(f"Memulai scraping untuk URL: {url}")
        driver = setup_driver()
        
        # Set timeouts
        driver.set_page_load_timeout(timeout)
        
        # Buka URL
        logger.info("Membuka URL...")
        driver.get(url)
        
        # Tunggu page load
        time.sleep(5)
        
        result = {
            'price': None,
            'product_name': None,
            'original_price': None,
            'discount': None
        }
        
        # Strategy 1: Cari dengan CSS Selectors
        logger.info("Strategy 1: Mencari dengan CSS Selectors...")
        
        price_selectors = [
            "span.pdp-price",
            ".pdp-product-price", 
            "span.pdp-v2-price",
            ".final-price",
            "[data-spm*='price']",
            "span[class*='price']",
            "div[class*='price']",
            # Lazada specific selectors
            ".pdp-mod-product-price",
            ".pdp-product-price span",
            ".pdp-v2-product-price-content-salePrice-amount"
        ]
        
        for selector in price_selectors:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                for element in elements:
                    text = element.text.strip()
                    if text and any(char.isdigit() for char in text):
                        price = extract_price_from_text(text)
                        if price:
                            result['price'] = price
                            logger.info(f"Harga ditemukan via CSS: {result['price']}")
                            break
                if result['price']:
                    break
            except Exception as e:
                continue
        
        # Strategy 2: Cari dengan XPath
        if not result['price']:
            logger.info("Strategy 2: Mencari dengan XPath...")
            xpath_selectors = [
                "//span[contains(text(), 'Rp')]",
                "//div[contains(text(), 'Rp')]",
                "//*[contains(text(), 'Rp')]",
                "//span[contains(@class, 'price')]",
                "//div[contains(@class, 'price')]"
            ]
            
            for xpath in xpath_selectors:
                try:
                    elements = driver.find_elements(By.XPATH, xpath)
                    for element in elements:
                        text = element.text.strip()
                        if text and any(char.isdigit() for char in text):
                            price = extract_price_from_text(text)
                            if price:
                                result['price'] = price
                                logger.info(f"Harga ditemukan via XPath: {result['price']}")
                                break
                    if result['price']:
                        break
                except:
                    continue
        
        # Strategy 3: Regex search di page source
        if not result['price']:
            logger.info("Strategy 3: Regex search di page source...")
            page_source = driver.page_source
            price_patterns = [
                r'Rp\s*(\d{1,3}(?:\.\d{3})+)',
                r'(\d{1,3}(?:\.\d{3})+)\s*Rp',
                r'["\']price["\']\s*:\s*["\']([^"\']+)["\']',
                r'["\']salePrice["\']\s*:\s*["\']([^"\']+)["\']'
            ]
            
            for pattern in price_patterns:
                matches = re.findall(pattern, page_source)
                for match in matches:
                    if match and '.' in match:
                        result['price'] = f"Rp {match}"
                        logger.info(f"Harga ditemukan via regex: {result['price']}")
                        break
                if result['price']:
                    break
        
        # Cari nama produk
        name_selectors = [
            "h1.pdp-mod-product-badge-title",
            ".pdp-product-title",
            "h1.pdp-title",
            "title",
            "h1",
            ".pdp-mod-product-name"
        ]
        
        for selector in name_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                name = element.text.strip()
                if name and len(name) > 5:
                    result['product_name'] = name
                    break
            except:
                continue
        
        # Cari harga original dan discount
        try:
            # Cari elemen yang mengandung "original"
            original_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'original') or contains(text(), 'Original')]")
            for elem in original_elements:
                text = elem.text.strip()
                price = extract_price_from_text(text)
                if price:
                    result['original_price'] = price
                    break
        except:
            pass
        
        try:
            # Cari discount
            discount_elements = driver.find_elements(By.XPATH, "//*[contains(@class, 'discount') or contains(text(), '%')]")
            for elem in discount_elements:
                text = elem.text.strip()
                if '%' in text:
                    result['discount'] = text
                    break
        except:
            pass
        
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
        "version": "2.0.0",
        "endpoints": {
            "scrape_post": "POST /scrape",
            "scrape_get": "GET /scrape?url=URL",
            "health": "GET /health"
        },
        "example": "GET /scrape?url=https://www.lazada.co.id/products/your-product-url"
    }

@app.post("/scrape", response_model=ScrapeResponse)
async def scrape_price_post(request: ScrapeRequest):
    """POST endpoint untuk scraping harga"""
    logger.info(f"POST request untuk URL: {request.url}")
    
    if not request.url.startswith(('https://www.lazada.co.id/products/', 'http://www.lazada.co.id/products/')):
        raise HTTPException(
            status_code=400, 
            detail="URL harus dari Lazada Indonesia (https://www.lazada.co.id/products/...)"
        )
    
    result = scrape_lazada_price(request.url, request.timeout)
    
    if not result['success']:
        raise HTTPException(status_code=404, detail=result['error'])
    
    return result

@app.get("/scrape")
async def scrape_price_get(url: str, timeout: int = 30):
    """GET endpoint untuk scraping harga"""
    if not url:
        raise HTTPException(status_code=400, detail="Parameter 'url' diperlukan")
    
    if not url.startswith(('https://www.lazada.co.id/products/', 'http://www.lazada.co.id/products/')):
        raise HTTPException(status_code=400, detail="URL harus dari Lazada Indonesia")
    
    result = scrape_lazada_price(url, timeout)
    return result

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy", 
        "service": "Lazada Scraper API",
        "timestamp": time.time(),
        "version": "2.0.0"
    }

# New simple test endpoint
@app.get("/test")
async def test_endpoint():
    """Test endpoint dengan URL contoh"""
    test_url = "https://www.lazada.co.id/products/prikol-british-klasik-gaya-sepatu-pria-casual-santai-kerja-sepatu-keren-pantofel-loafer-kulit-cowok-sepatu-formal-slip-on-kuliah-160-i6593890539-s12535812627.html"
    
    try:
        result = scrape_lazada_price(test_url, timeout=20)
        return {
            "test_result": "success" if result['success'] else "failed",
            "data": result
        }
    except Exception as e:
        return {
            "test_result": "error",
            "error": str(e)
        }

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)