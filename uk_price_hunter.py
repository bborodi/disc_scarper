#!/usr/bin/env python3
"""
UK Price Error Hunter
=====================
Scans major UK retailers for pricing errors — items listed well under £1
that should normally cost significantly more.

Retailers covered:
  • HotUKDeals  (community deal aggregator — most reliable)
  • eBay UK     (marketplace — large, updated frequently)
  • Amazon UK   (best-effort; may hit CAPTCHA)
  • Currys PC World
  • Argos
  • Very.co.uk
  • AO.com
  • Tesco

Usage:
  python uk_price_hunter.py                    # one-shot, all retailers
  python uk_price_hunter.py --threshold 0.50   # flag only items under 50p
  python uk_price_hunter.py --retailers hotukdeals ebay currys
  python uk_price_hunter.py --watch 15         # re-scan every 15 minutes
  python uk_price_hunter.py --output my_finds  # saves my_finds.csv + my_finds.html
  python uk_price_hunter.py --notify           # macOS desktop notification on finds

Notes:
  • Respects sites with polite random delays between requests.
  • Amazon blocks bots heavily; use Amazon PA-API for reliable results.
  • HotUKDeals is the highest-signal source — community already vets errors.
  • This tool reads public price data only and does not log in to any service.
"""

import argparse
import csv
import json
import os
import random
import re
import smtplib
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from html import escape
from typing import Callable, List, Optional

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("[!] Missing dependencies. Run:  pip install requests beautifulsoup4 lxml")
    sys.exit(1)

DEFAULT_THRESHOLD = 1.00
MIN_WORTHWHILE    = 3.00
REQUEST_TIMEOUT   = 15

DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}

GENERAL_TERMS = [
    # Household / cleaning / essentials
    "water bottles 24 pack", "sparkling water pack", "mineral water",
    "kitchen roll", "toilet roll 9 pack", "toilet roll 24 pack",
    "laundry pods", "washing up liquid", "fabric softener",
    "coffee pods", "tea bags 80", "instant coffee",
    "shower gel", "shampoo", "conditioner", "hand cream", "face wash",
    "deodorant", "moisturiser", "body lotion", "hand soap", "hand sanitiser",
    "notebook A5", "ballpoint pens 10", "highlighters", "sticky notes",
    "microfibre cloth", "cleaning spray", "disinfectant spray", "bin bags",
    "air freshener", "kitchen sponges", "rubber gloves",

    # Kitchen
    "air fryer", "slow cooker", "pressure cooker", "rice cooker",
    "kettle", "toaster", "blender", "food processor", "stand mixer",
    "hand mixer", "coffee machine", "espresso machine", "milk frother",
    "microwave", "mini fridge", "wine cooler", "ice maker",
    "knife set", "chopping board", "kitchen scales", "measuring cups",
    "non stick pans", "saucepan set", "baking trays", "mixing bowls",
    "food storage containers", "vacuum sealer", "spice rack",
    "dish drying rack", "kitchen utensil set", "can opener",
    "water filter jug", "thermos flask", "lunch box",

    # Living room
    "throw blanket", "cushion covers", "floor lamp", "table lamp",
    "led strip lights", "fairy lights", "wall clock", "picture frames",
    "candle holders", "scented candles", "diffuser", "rug",
    "curtains blackout", "tv stand", "bookshelf", "storage ottoman",
    "coffee table", "side table", "shoe rack", "coat rack",
    "wall mirror", "soft furnishings", "draft excluder",

    # Garden
    "garden hose", "watering can", "plant pots", "raised garden bed",
    "garden gloves", "pruning shears", "secateurs", "garden trowel",
    "lawn mower", "strimmer", "leaf blower", "hedge trimmer",
    "outdoor solar lights", "string lights outdoor", "bird feeder",
    "garden furniture cover", "patio heater", "bbq grill", "bbq tools set",
    "outdoor cushions", "garden parasol", "compost bin", "plant fertiliser",
    "greenhouse", "garden tools set", "wheelbarrow",

    # Gym / fitness
    "resistance bands", "dumbbells set", "kettlebell", "yoga mat",
    "foam roller", "exercise bike", "treadmill", "skipping rope",
    "pull up bar", "ab roller", "weight bench", "gym gloves",
    "gym bag", "water bottle gym", "massage gun", "ankle weights",
    "exercise ball", "jump rope", "gym flooring mats",

    # Office / organisation
    "desk organiser", "monitor riser", "desk mat", "cable management box",
    "filing cabinet", "document folders", "whiteboard", "cork board",
    "desk lamp", "office chair", "standing desk converter", "footrest",
    "drawer organiser", "storage boxes", "stationery set", "label printer",
    "paper shredder", "laminator", "calendar planner", "desk pad",

    # Home improvement
    "tool set", "screwdriver set", "drill driver", "tape measure",
    "spirit level", "hammer", "pliers set", "socket set",
    "led bulbs", "extension cable reel", "door draft stopper",
    "smoke alarm", "carbon monoxide detector", "storage shelving unit",
    "wall shelves", "door hooks", "curtain rail", "blinds",
    "doormat", "step ladder", "tool box", "glue gun", "duct tape",
]

TECH_TERMS = [
    "USB cable", "USB-C cable", "lightning cable", "phone case",
    "screen protector", "tempered glass screen protector",
    "HDMI cable 2m", "ethernet cable", "memory card 32gb", "memory card 128gb",
    "SD card", "microSD card", "SSD external", "external hard drive",
    "USB flash drive", "USB hub", "docking station",
    "earphones", "wireless earbuds", "headphones", "noise cancelling headphones",
    "phone charger", "wireless charger", "fast charger plug", "multi port charger",
    "laptop bag", "laptop sleeve", "laptop stand",
    "keyboard", "wireless keyboard", "mechanical keyboard",
    "mouse", "wireless mouse", "mouse pad",
    "webcam 1080p", "webcam 4k", "ring light",
    "bluetooth speaker", "smart speaker", "power bank", "power bank 20000mah",
    "phone stand", "tablet stand", "cable organiser", "cable ties",
    "surge protector", "extension lead", "smart plug", "smart bulb",
    "graphics card", "GPU", "RAM memory kit", "motherboard",
    "CPU cooler", "PC case fan", "thermal paste",
    "monitor", "portable monitor", "monitor arm", "monitor stand",
    "router", "wifi extender", "mesh wifi system", "network switch",
    "smartwatch", "fitness tracker", "VR headset",
    "printer", "printer ink cartridges", "label maker",

    # Camera / recording / equipment
    "action camera", "GoPro accessories", "tripod", "phone tripod",
    "camera tripod", "gimbal stabiliser", "selfie stick",
    "lavalier microphone", "USB microphone", "podcast microphone",
    "camera lens", "camera lens filter", "camera bag", "camera strap",
    "memory card reader", "SD card case", "camera cleaning kit",
    "lighting kit photography", "softbox lighting", "green screen",
    "DSLR camera", "mirrorless camera", "instant camera", "camera flash",
    "security camera", "baby monitor camera", "trail camera",
    "voice recorder", "dictaphone",
]


@dataclass
class PricingError:
    retailer:     str
    product_name: str
    error_price:  float
    normal_price: Optional[float]
    url:          str
    category:     str = "General"
    confidence:   str = "Medium"
    found_at:     str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M"))

    def saving(self) -> Optional[float]:
        if self.normal_price and self.normal_price > self.error_price:
            return round(self.normal_price - self.error_price, 2)
        return None

    def discount_pct(self) -> Optional[float]:
        if self.normal_price and self.normal_price > 0:
            return round((1 - self.error_price / self.normal_price) * 100, 1)
        return None


def jitter(lo: float = 1.5, hi: float = 4.0):
    time.sleep(random.uniform(lo, hi))


def extract_gbp(text: str) -> Optional[float]:
    m = re.search(r"£\s*([\d,]+\.?\d*)", text)
    if m:
        return float(m.group(1).replace(",", ""))
    m = re.search(r"\b(\d+)p\b", text, re.IGNORECASE)
    if m:
        return float(m.group(1)) / 100
    return None


def safe_get(session, url, label="", **kwargs):
    try:
        r = session.get(url, headers=DESKTOP_HEADERS, timeout=REQUEST_TIMEOUT, **kwargs)
        r.raise_for_status()
        return r
    except requests.exceptions.HTTPError as e:
        print(f"    [!] HTTP {e.response.status_code} — {label or url[:60]}")
    except requests.exceptions.ConnectionError:
        print(f"    [!] Connection error — {label or url[:60]}")
    except requests.exceptions.Timeout:
        print(f"    [!] Timeout — {label or url[:60]}")
    except Exception as e:
        print(f"    [!] Error ({type(e).__name__}) — {label or url[:60]}")
    return None


def abs_url(href, base):
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    return base.rstrip("/") + "/" + href.lstrip("/")


def scan_hotukdeals(session, threshold):
    results = []
    search_urls = [
        "https://www.hotukdeals.com/tag/pricing-error",
        "https://www.hotukdeals.com/search?q=pricing+error&sortBy=new",
        "https://www.hotukdeals.com/search?q=1p+deal&sortBy=new",
        "https://www.hotukdeals.com/search?q=free+with+voucher&sortBy=new",
    ]
    for url in search_urls:
        print(f"    {url}")
        r = safe_get(session, url, "HotUKDeals")
        if not r:
            jitter()
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        articles = soup.select(
            "article.thread--deal, article[class*='thread'], "
            "li[class*='thread'], .thread-item"
        )
        for art in articles:
            try:
                title_el = art.select_one(
                    ".thread-title a, .thread-link, h2 a, h3 a, "
                    "[class*='title'] a, [class*='thread-link']"
                )
                price_el = art.select_one(
                    ".thread-price, .price, [class*='threadPrice'], "
                    "[class*='price--thread'], span[class*='price']"
                )
                link_el = art.select_one("a[href]")
                title = (title_el or art).get_text(strip=True)[:120]
                if not title or not price_el:
                    continue
                price = extract_gbp(price_el.get_text(strip=True))
                if price is None or price > threshold or price <= 0:
                    continue
                href = abs_url((link_el.get("href") or "") if link_el else "", "https://www.hotukdeals.com")
                results.append(PricingError(
                    retailer="HotUKDeals", product_name=title, error_price=price,
                    normal_price=None, url=href, category="Deal Aggregator", confidence="High",
                ))
            except Exception:
                pass
        jitter(1.5, 3.5)
    return results


def scan_ebay_uk(session, threshold):
    results = []
    terms = random.sample(GENERAL_TERMS, min(10, len(GENERAL_TERMS)))
    for term in terms:
        url = (
            "https://www.ebay.co.uk/sch/i.html"
            f"?_nkw={requests.utils.quote(term)}&LH_BIN=1&LH_ItemCondition=3&_sop=15"
        )
        print(f"    eBay UK — '{term}'")
        r = safe_get(session, url, f"eBay: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".s-item"):
            try:
                title_el = item.select_one(".s-item__title")
                price_el = item.select_one(".s-item__price")
                link_el  = item.select_one("a.s-item__link")
                if not title_el or not price_el:
                    continue
                title = title_el.get_text(strip=True)
                if "Shop on eBay" in title:
                    continue
                price_text = price_el.get_text(strip=True)
                if " to " in price_text.lower():
                    continue
                price = extract_gbp(price_text)
                if price is None or price <= 0 or price > threshold:
                    continue
                results.append(PricingError(
                    retailer="eBay UK", product_name=title[:120], error_price=price,
                    normal_price=None, url=(link_el.get("href") or "") if link_el else "",
                    category=term.title(), confidence="Medium",
                ))
            except Exception:
                pass
        jitter(2, 4)
    return results


def scan_amazon_uk(session, threshold):
    results = []
    terms = random.sample(GENERAL_TERMS, min(4, len(GENERAL_TERMS)))
    amz = requests.Session()
    amz.headers.update({**DESKTOP_HEADERS, "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    )})
    for term in terms:
        url = f"https://www.amazon.co.uk/s?k={requests.utils.quote(term)}&s=price-asc-rank&i=aps"
        print(f"    Amazon UK — '{term}' (best-effort)")
        r = safe_get(amz, url, f"Amazon: {term}")
        if not r:
            jitter(3, 7)
            continue
        if "captcha" in r.text.lower() or "robot" in r.text.lower():
            print("    [!] Amazon returned CAPTCHA — skipping.")
            break
        if "Sorry, we just need to make sure" in r.text:
            print("    [!] Amazon bot-check — skipping.")
            break
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select('[data-component-type="s-search-result"]'):
            try:
                title_el    = item.select_one("h2 .a-text-normal, h2 a span")
                price_whole = item.select_one(".a-price-whole")
                price_frac  = item.select_one(".a-price-fraction")
                link_el     = item.select_one("h2 a")
                if not title_el or not price_whole:
                    continue
                pw = price_whole.get_text(strip=True).replace(",", "").rstrip(".")
                pf = price_frac.get_text(strip=True) if price_frac else "00"
                try:
                    price = float(f"{pw}.{pf}")
                except ValueError:
                    continue
                if price <= 0 or price > threshold:
                    continue
                results.append(PricingError(
                    retailer="Amazon UK", product_name=title_el.get_text(strip=True)[:120],
                    error_price=price, normal_price=None,
                    url=abs_url((link_el.get("href") or "") if link_el else "", "https://www.amazon.co.uk"),
                    category=term.title(), confidence="High",
                ))
            except Exception:
                pass
        jitter(4, 8)
    return results


def scan_currys(session, threshold):
    results = []
    for term in random.sample(TECH_TERMS, min(6, len(TECH_TERMS))):
        url = f"https://www.currys.co.uk/search?q={requests.utils.quote(term)}&sortby=price-asc"
        print(f"    Currys — '{term}'")
        r = safe_get(session, url, f"Currys: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.string or "")
                for d in (data if isinstance(data, list) else [data]):
                    if d.get("@type") not in ("Product", "ItemList"):
                        continue
                    offers = d.get("offers", {})
                    if isinstance(offers, list):
                        offers = offers[0] if offers else {}
                    try:
                        price = float(str(offers.get("price", "")))
                    except (ValueError, TypeError):
                        continue
                    if price <= 0 or price > threshold:
                        continue
                    results.append(PricingError(
                        retailer="Currys PC World", product_name=d.get("name", "Unknown")[:120],
                        error_price=price, normal_price=None,
                        url=d.get("url", "https://www.currys.co.uk"),
                        category="Technology", confidence="High",
                    ))
            except Exception:
                pass
        for item in soup.select(".product-tile, [class*='product-item']"):
            try:
                title_el = item.select_one("h2, h3, [class*='title']")
                price_el = item.select_one("[class*='price'], [data-price]")
                link_el  = item.select_one("a[href]")
                if not title_el or not price_el:
                    continue
                price = extract_gbp(price_el.get_text(strip=True))
                if price is None or price <= 0 or price > threshold:
                    continue
                results.append(PricingError(
                    retailer="Currys PC World", product_name=title_el.get_text(strip=True)[:120],
                    error_price=price, normal_price=None,
                    url=abs_url((link_el.get("href") or "") if link_el else "", "https://www.currys.co.uk"),
                    category="Technology", confidence="High",
                ))
            except Exception:
                pass
        jitter(2, 4)
    return results


def _walk_for_products(data, found=None, depth=0):
    if found is None:
        found = []
    if depth > 12:
        return found
    if isinstance(data, dict):
        if ("price" in data or "unitPrice" in data) and ("name" in data or "title" in data):
            found.append(data)
        for v in data.values():
            _walk_for_products(v, found, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _walk_for_products(item, found, depth + 1)
    return found


def _walk_jsonld_products(data):
    products = []
    if isinstance(data, dict):
        if data.get("@type") == "Product":
            offers = data.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            try:
                price = float(str(offers.get("price", "99")).replace(",", ""))
            except Exception:
                price = 99
            products.append({"name": data.get("name", ""), "price": price,
                             "was_price": None, "url": data.get("url", "")})
        elif data.get("@type") == "ItemList":
            for el in data.get("itemListElement", []):
                products.extend(_walk_jsonld_products(el.get("item", {})))
    return products


def scan_argos(session, threshold):
    results = []
    categories = ["kitchen", "toys", "garden", "baby", "home",
                  "phone accessories", "gaming", "beauty", "sports"]
    for term in random.sample(categories, min(5, len(categories))):
        url = f"https://www.argos.co.uk/search/{requests.utils.quote(term)}/?sortBy=price_asc"
        print(f"    Argos — '{term}'")
        r = safe_get(session, url, f"Argos: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        if tag:
            try:
                for p in _walk_for_products(json.loads(tag.string or "")):
                    try:
                        price = float(str(p.get("price", "99")).replace("£", "").replace(",", ""))
                    except ValueError:
                        continue
                    if price <= 0 or price > threshold:
                        continue
                    pid = p.get("id", p.get("productId", ""))
                    results.append(PricingError(
                        retailer="Argos", product_name=str(p.get("name", p.get("title", "Unknown")))[:120],
                        error_price=price, normal_price=None,
                        url=f"https://www.argos.co.uk/product/{pid}" if pid else "https://www.argos.co.uk",
                        category=term.title(), confidence="High",
                    ))
            except Exception:
                pass
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                for p in _walk_jsonld_products(json.loads(script.string or "")):
                    if p.get("price", 99) <= threshold:
                        results.append(PricingError(
                            retailer="Argos", product_name=p.get("name", "Unknown")[:120],
                            error_price=p["price"], normal_price=p.get("was_price"),
                            url=p.get("url", "https://www.argos.co.uk"),
                            category=term.title(), confidence="High",
                        ))
            except Exception:
                pass
        jitter(2, 4)
    return results


def scan_very(session, threshold):
    results = []
    for term in random.sample(["phone accessories", "kitchen gadgets", "garden", "home decor", "toys"], 3):
        url = f"https://www.very.co.uk/e/q/{requests.utils.quote(term)}.end?sortby=3"
        print(f"    Very.co.uk — '{term}'")
        r = safe_get(session, url, f"Very: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for item in soup.select(".productBlock, [class*='product-item'], [class*='productItem']"):
            try:
                title_el = item.select_one("h2, h3, [class*='productTitle'], [class*='title']")
                price_el = item.select_one("[class*='productPrice'], [class*='price']")
                link_el  = item.select_one("a[href]")
                if not title_el or not price_el:
                    continue
                price = extract_gbp(price_el.get_text(strip=True))
                if price is None or price <= 0 or price > threshold:
                    continue
                results.append(PricingError(
                    retailer="Very.co.uk", product_name=title_el.get_text(strip=True)[:120],
                    error_price=price, normal_price=None,
                    url=abs_url((link_el.get("href") or "") if link_el else "", "https://www.very.co.uk"),
                    category=term.title(), confidence="Medium",
                ))
            except Exception:
                pass
        jitter(2, 4)
    return results


def scan_ao(session, threshold):
    results = []
    for term in random.sample(["kettle", "toaster", "phone accessories", "cables", "headphones", "speakers"], 4):
        url = f"https://ao.com/l/{requests.utils.quote(term.replace(' ', '-'))}/?sort=price_asc"
        print(f"    AO.com — '{term}'")
        r = safe_get(session, url, f"AO: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                for p in _walk_jsonld_products(json.loads(script.string or "")):
                    if p.get("price", 99) <= threshold:
                        results.append(PricingError(
                            retailer="AO.com", product_name=p.get("name", "Unknown")[:120],
                            error_price=p["price"], normal_price=p.get("was_price"),
                            url=p.get("url", "https://ao.com"),
                            category=term.title(), confidence="High",
                        ))
            except Exception:
                pass
        for item in soup.select("[class*='product'], [class*='Product']"):
            try:
                title_el = item.select_one("h2, h3, [class*='name'], [class*='title']")
                price_el = item.select_one("[class*='price'], [class*='Price']")
                link_el  = item.select_one("a[href]")
                if not title_el or not price_el:
                    continue
                price = extract_gbp(price_el.get_text(strip=True))
                if price is None or price <= 0 or price > threshold:
                    continue
                results.append(PricingError(
                    retailer="AO.com", product_name=title_el.get_text(strip=True)[:120],
                    error_price=price, normal_price=None,
                    url=abs_url((link_el.get("href") or "") if link_el else "", "https://ao.com"),
                    category=term.title(), confidence="Medium",
                ))
            except Exception:
                pass
        jitter(2, 4)
    return results


def scan_tesco(session, threshold):
    results = []
    grocery_terms = [
        "sparkling water 24 pack", "still water 24 pack", "soft drinks multipack",
        "energy drinks 24", "tea bags 80 pack", "coffee", "juice multipack",
        "washing powder", "dishwasher tablets",
    ]
    for term in random.sample(grocery_terms, min(5, len(grocery_terms))):
        url = f"https://www.tesco.com/groceries/en-GB/search?query={requests.utils.quote(term)}&sortBy=price-ascending"
        print(f"    Tesco — '{term}'")
        r = safe_get(session, url, f"Tesco: {term}")
        if not r:
            jitter(2, 5)
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for script in soup.find_all("script"):
            raw = script.string or ""
            if '"price"' not in raw and "'price'" not in raw:
                continue
            matches = re.findall(r'"price"\s*:\s*([\d.]+)', raw)
            names   = re.findall(r'"title"\s*:\s*"([^"]+)"', raw)
            urls_m  = re.findall(r'"url"\s*:\s*"(/[^"]+)"', raw)
            for i, price_str in enumerate(matches):
                try:
                    price = float(price_str)
                except ValueError:
                    continue
                if price <= 0 or price > threshold:
                    continue
                name = names[i] if i < len(names) else "Unknown product"
                href = ("https://www.tesco.com" + urls_m[i]) if i < len(urls_m) else "https://www.tesco.com"
                results.append(PricingError(
                    retailer="Tesco", product_name=name[:120], error_price=price,
                    normal_price=None, url=href, category=term.title(), confidence="Medium",
                ))
            break
        jitter(2, 4)
    return results


SCANNERS: dict[str, Callable] = {
    "hotukdeals": scan_hotukdeals,
    "ebay":       scan_ebay_uk,
    "amazon":     scan_amazon_uk,
    "currys":     scan_currys,
    "argos":      scan_argos,
    "very":       scan_very,
    "ao":         scan_ao,
    "tesco":      scan_tesco,
}

CONF_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def print_results(errors):
    if not errors:
        print("\n  No pricing errors found this scan — try again later.\n")
        return
    print(f"\n{'═'*68}")
    print(f"  PRICING ERRORS FOUND: {len(errors)}")
    print(f"{'═'*68}")
    for i, e in enumerate(errors, 1):
        saving_str = f"  (save £{e.saving():.2f} — {e.discount_pct()}% off)" if e.saving() else ""
        print(f"\n  [{i}] {e.retailer}  [{e.confidence} confidence]")
        print(f"  Product : {e.product_name}")
        print(f"  Price   : £{e.error_price:.2f}{saving_str}")
        if e.url:
            print(f"  URL     : {e.url}")
        print(f"  Found   : {e.found_at}")
    print(f"\n{'═'*68}\n")


def save_csv(errors, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "retailer", "product_name", "error_price", "normal_price",
            "saving", "discount_pct", "url", "category", "confidence", "found_at",
        ])
        writer.writeheader()
        for e in errors:
            writer.writerow({
                "retailer":     e.retailer,
                "product_name": e.product_name,
                "error_price":  f"£{e.error_price:.2f}",
                "normal_price": f"£{e.normal_price:.2f}" if e.normal_price else "",
                "saving":       f"£{e.saving():.2f}" if e.saving() else "",
                "discount_pct": f"{e.discount_pct()}%" if e.discount_pct() else "",
                "url":          e.url,
                "category":     e.category,
                "confidence":   e.confidence,
                "found_at":     e.found_at,
            })
    print(f"  CSV saved → {path}")


def save_html(errors, path):
    rows = ""
    for e in errors:
        badge_color = {"High": "#16a34a", "Medium": "#d97706", "Low": "#6b7280"}.get(e.confidence, "#6b7280")
        saving_str = f"£{e.saving():.2f} ({e.discount_pct()}% off)" if e.saving() else "—"
        link = f'<a href="{escape(e.url)}" target="_blank">View</a>' if e.url else "—"
        rows += f"""
        <tr>
          <td><span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{escape(e.confidence)}</span></td>
          <td>{escape(e.retailer)}</td>
          <td>{escape(e.product_name)}</td>
          <td style="color:#dc2626;font-weight:600">£{e.error_price:.2f}</td>
          <td>{escape(saving_str)}</td>
          <td>{link}</td>
          <td style="color:#6b7280;font-size:12px">{escape(e.found_at)}</td>
        </tr>"""
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>UK Price Error Hunter — Results</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background:#f8fafc; color:#1e293b; margin:0; padding:24px }}
  h1   {{ font-size:1.5rem; margin-bottom:4px }}
  p.sub {{ color:#64748b; margin-top:0; margin-bottom:20px }}
  table {{ width:100%; border-collapse:collapse; background:#fff;
           border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,.1) }}
  th   {{ background:#1e293b; color:#fff; text-align:left; padding:12px 16px; font-size:13px; font-weight:500 }}
  td   {{ padding:12px 16px; border-bottom:1px solid #e2e8f0; font-size:14px }}
  tr:last-child td {{ border-bottom:none }}
  tr:hover td {{ background:#f1f5f9 }}
  a    {{ color:#2563eb; text-decoration:none }}
  a:hover {{ text-decoration:underline }}
  .none {{ text-align:center; color:#94a3b8; padding:48px }}
</style>
</head>
<body>
<h1>UK Price Error Hunter</h1>
<p class="sub">Scan run: {datetime.now().strftime("%d %b %Y %H:%M")} &nbsp;|&nbsp; {len(errors)} error(s) found</p>
<table>
  <thead>
    <tr>
      <th>Confidence</th><th>Retailer</th><th>Product</th>
      <th>Error Price</th><th>Saving</th><th>Link</th><th>Found At</th>
    </tr>
  </thead>
  <tbody>
    {"<tr><td colspan='7' class='none'>No pricing errors found this scan.</td></tr>" if not errors else rows}
  </tbody>
</table>
</body>
</html>"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  HTML report → {path}")


def send_email_report(errors, to_addr, from_addr, password, html_mode=True):
    subject = f"Price Error Hunter — {len(errors)} error(s) found ({datetime.now().strftime('%d %b %Y %H:%M')})"
    lines = [f"Price Error Hunter found {len(errors)} potential error(s):\n"]
    for i, e in enumerate(errors, 1):
        saving_str = f" — save £{e.saving():.2f} ({e.discount_pct()}% off)" if e.saving() else ""
        lines += [f"[{i}] {e.retailer}  [{e.confidence}]", f"    {e.product_name}",
                  f"    £{e.error_price:.2f}{saving_str}", f"    {e.url}\n"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Price Hunter <{from_addr}>"
    msg["To"]      = to_addr
    msg.attach(MIMEText("\n".join(lines), "plain"))
    if html_mode:
        rows = ""
        for e in errors:
            badge_color = {"High": "#16a34a", "Medium": "#d97706", "Low": "#6b7280"}.get(e.confidence, "#6b7280")
            saving_str = f"£{e.saving():.2f} ({e.discount_pct()}% off)" if e.saving() else "—"
            link = f'<a href="{escape(e.url)}" style="color:#2563eb">View deal</a>' if e.url else "—"
            rows += f"""
            <tr>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0">
                <span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px">{escape(e.confidence)}</span>
              </td>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0">{escape(e.retailer)}</td>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0">{escape(e.product_name)}</td>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0;color:#dc2626;font-weight:600">£{e.error_price:.2f}</td>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0">{escape(saving_str)}</td>
              <td style="padding:12px 16px;border-bottom:1px solid #e2e8f0">{link}</td>
            </tr>"""
        html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f8fafc;color:#1e293b;margin:0;padding:24px">
  <h1 style="font-size:1.4rem;margin-bottom:4px">UK Price Error Hunter</h1>
  <p style="color:#64748b;margin-top:0;margin-bottom:20px">{len(errors)} error(s) found &nbsp;&middot;&nbsp; {datetime.now().strftime("%d %b %Y %H:%M")}</p>
  <table style="width:100%;border-collapse:collapse;background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.1)">
    <thead>
      <tr style="background:#1e293b;color:#fff">
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Confidence</th>
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Retailer</th>
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Product</th>
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Price</th>
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Saving</th>
        <th style="padding:12px 16px;text-align:left;font-size:13px;font-weight:500">Link</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
  <p style="color:#94a3b8;font-size:12px;margin-top:16px">Sent by UK Price Error Hunter on GitHub Actions</p>
</body>
</html>"""
        msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.ehlo()
            server.starttls()
            server.login(from_addr, password)
            server.sendmail(from_addr, to_addr, msg.as_string())
        print(f"  Email sent → {to_addr}")
    except smtplib.SMTPAuthenticationError:
        print("  [!] Email failed: check GMAIL_ADDRESS and GMAIL_APP_PASSWORD.")
    except Exception as exc:
        print(f"  [!] Email failed: {exc}")


def notify_macos(count, top):
    if sys.platform != "darwin":
        return
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "£{top.error_price:.2f} — {top.product_name[:60]}" '
            f'with title "Price Error Hunter" subtitle "{count} error(s) found"'], check=False)
    except Exception:
        pass


def run_scan(threshold, retailers):
    session = requests.Session()
    session.headers.update(DESKTOP_HEADERS)
    all_errors = []
    for name, scanner in SCANNERS.items():
        if retailers and name not in retailers:
            continue
        print(f"\n[{name.upper()}]")
        try:
            found = scanner(session, threshold)
            print(f"  → {len(found)} potential error(s) from {name}")
            all_errors.extend(found)
        except Exception as exc:
            print(f"  [!] Scanner '{name}' crashed: {exc}")
    seen = set()
    unique = []
    for e in all_errors:
        key = e.url or f"{e.retailer}:{e.product_name}"
        if key not in seen:
            seen.add(key)
            unique.append(e)
    unique.sort(key=lambda x: (CONF_ORDER.get(x.confidence, 2), x.error_price))
    return unique


def main():
    parser = argparse.ArgumentParser(
        description="UK Price Error Hunter — finds items under £1 on major UK retailers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--threshold", "-t", type=float, default=DEFAULT_THRESHOLD)
    parser.add_argument("--retailers", "-r", nargs="+", choices=list(SCANNERS.keys()),
                        default=list(SCANNERS.keys()), metavar="RETAILER")
    parser.add_argument("--output", "-o", type=str, default="price_errors")
    parser.add_argument("--watch", "-w", type=int, default=0, metavar="MINUTES")
    parser.add_argument("--notify", "-n", action="store_true")
    parser.add_argument("--no-html", action="store_true")
    parser.add_argument("--email", action="store_true")
    args = parser.parse_args()

    email_from = email_password = email_to = ""
    if args.email:
        email_from     = os.environ.get("GMAIL_ADDRESS", "")
        email_password = os.environ.get("GMAIL_APP_PASSWORD", "")
        email_to       = os.environ.get("EMAIL_TO", "")
        missing = [k for k, v in {"GMAIL_ADDRESS": email_from,
                                   "GMAIL_APP_PASSWORD": email_password,
                                   "EMAIL_TO": email_to}.items() if not v]
        if missing:
            print(f"[!] --email requires: {', '.join(missing)}")
            sys.exit(1)

    output_note = f"{args.output}.csv" + (f"  +  {args.output}.html" if not args.no_html else "")
    banner = f"\n{'═'*68}\n  UK Price Error Hunter\n  Threshold : under £{args.threshold:.2f}\n  Retailers : {', '.join(args.retailers)}\n  Output    : {output_note}\n{'═'*68}"

    run_count = 0
    known_urls: set[str] = set()

    while True:
        run_count += 1
        if args.watch:
            print(f"\n{'─'*68}\n  Scan #{run_count}  —  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'─'*68}")
        else:
            print(banner)

        errors = run_scan(args.threshold, args.retailers)

        if args.watch:
            new_errors = [e for e in errors if (e.url or f"{e.retailer}:{e.product_name}") not in known_urls]
            for e in new_errors:
                known_urls.add(e.url or f"{e.retailer}:{e.product_name}")
            display_errors = new_errors
            if not new_errors:
                print(f"\n  No NEW errors since last scan. Total known: {len(known_urls)}")
        else:
            display_errors = errors

        print_results(display_errors)

        if display_errors:
            save_csv(display_errors, f"{args.output}.csv")
            if not args.no_html:
                save_html(display_errors, f"{args.output}.html")
            if args.notify:
                notify_macos(len(display_errors), display_errors[0])
            if args.email:
                send_email_report(display_errors, email_to, email_from, email_password,
                                  html_mode=not args.no_html)

        print(f"\n  Total unique errors found: {len(errors)}")
        if not args.watch:
            break
        print(f"\n  Next scan in {args.watch} minute(s)... (Ctrl-C to stop)\n")
        time.sleep(args.watch * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n  Stopped by user.\n")
        sys.exit(0)