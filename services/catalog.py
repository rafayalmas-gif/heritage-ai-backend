import re, time, requests
from bs4 import BeautifulSoup
from config import HERITAGE_SITE, CATALOG_FILE, CATALOG_REFRESH_SECONDS, MAX_CATALOG_PRODUCTS
from services.utils import clean_text, load_json, save_json, now_iso
from services.media import cache_public_image

COLLECTION_PATHS = [
    "/collections/rings",
    "/collections/tops",
    "/collections/earrings",
    "/collections/pendants",
    "/collections/pendant-sets",
    "/collections/sets-necklace-sets",
    "/collections/necklace-sets",
    "/collections/bangles",
    "/collections/bracelets",
    "/collections/bangles-bracelets",
]

VISUAL_DNA_KEYWORDS = [
    "leaf", "vine", "floral", "flower", "paisley", "mughal", "jaali", "filigree", "jadau", "kundan", "meenakari",
    "halo", "cluster", "geometric", "chevron", "zigzag", "rope", "twisted", "pearl", "drop", "bunch",
    "zircon", "ganga jamni", "yellow gold", "white polish", "rose gold", "broad", "thin", "medium", "bridal"
]

def img_url(src):
    if not src:
        return ""
    if src.startswith("//"):
        return "https:" + src
    if src.startswith("/"):
        return HERITAGE_SITE + src
    return src.replace("http://", "https://")

def parse_price(text):
    m = re.search(r"Rs\.?\s*([0-9][0-9,]*)", text or "", re.I)
    return "Rs." + m.group(1) if m else ""

def extract_code(title, url=""):
    text = f"{title} {url}".upper()
    m = re.search(r"\b[A-Z]{1,5}[-\s]?\d{2,5}\b", text)
    if m:
        return m.group(0).replace(" ", "-")
    return url.rstrip("/").split("/")[-1].upper()[:30] if url else title[:30]

def infer_category(url, title):
    t = f"{url} {title}".lower()
    if "bangle" in t or "kada" in t:
        return "bangle"
    if "bracelet" in t:
        return "bracelet"
    if "ring" in t:
        return "ring"
    if "earring" in t or "tops" in t or "stud" in t:
        return "earrings"
    if "pendant-set" in t or "locket-set" in t:
        return "pendant set"
    if "pendant" in t or "locket" in t:
        return "pendant"
    if "necklace" in t or "set" in t:
        return "necklace set"
    return "unknown"

def tags_from_text(title, url, category):
    blob = f"{title} {url}".lower()
    tags = [category] if category else []
    for kw in VISUAL_DNA_KEYWORDS:
        if kw in blob:
            tags.append(kw)
    return sorted(set(tags))

def fetch_collection(path, limit=80):
    products, seen = [], set()
    for page in ["", "?page=1", "?page=2", "?page=3"]:
        try:
            r = requests.get(HERITAGE_SITE + path + page, headers={"User-Agent": "Mozilla/5.0 HeritageAI"}, timeout=30)
            if r.status_code != 200:
                continue
            soup = BeautifulSoup(r.text, "lxml")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if "/products/" not in href:
                    continue
                url = (href if href.startswith("http") else HERITAGE_SITE + href).split("?")[0]
                if url in seen:
                    continue
                seen.add(url)
                title = clean_text(a.get_text(" ", strip=True)) or url.split("/")[-1]
                card = a
                image = ""
                for _ in range(4):
                    if card and getattr(card, "find", None):
                        im = card.find("img")
                        if im:
                            image = img_url(im.get("src") or im.get("data-src") or "")
                            break
                    card = card.parent
                parent_text = a.parent.get_text(" ", strip=True) if a.parent else title
                price = parse_price(parent_text)
                cat = infer_category(path + " " + url, title)
                products.append({
                    "title": title, "url": url, "code": extract_code(title, url), "price": price,
                    "image_url": image, "category": cat, "tags": tags_from_text(title, url, cat)
                })
                if len(products) >= limit:
                    break
        except Exception as e:
            print("CATALOG_FETCH_ERROR", path, e, flush=True)
    return products[:limit]

def fetch_details(p):
    try:
        r = requests.get(p["url"], headers={"User-Agent": "Mozilla/5.0 HeritageAI"}, timeout=30)
        if r.status_code != 200:
            return p
        soup = BeautifulSoup(r.text, "lxml")
        text = soup.get_text(" ", strip=True)
        p["price"] = p.get("price") or parse_price(text)
        imgs = []
        for im in soup.find_all("img"):
            u = img_url(im.get("src") or im.get("data-src") or "")
            if u and u not in imgs:
                imgs.append(u)
        if not p.get("image_url") and imgs:
            p["image_url"] = imgs[0]
        p["image_urls"] = imgs[:5]
    except Exception:
        pass
    return p

def build_catalog(force=False):
    current = load_json(CATALOG_FILE, {})
    if not force and current.get("built_ts") and time.time() - current.get("built_ts", 0) < CATALOG_REFRESH_SECONDS:
        return current
    products, seen = [], set()
    for path in COLLECTION_PATHS:
        for p in fetch_collection(path):
            if p["url"] in seen:
                continue
            seen.add(p["url"])
            p = fetch_details(p)
            if p.get("image_url"):
                try:
                    p["cached_image_url"] = cache_public_image(p["image_url"])
                except Exception:
                    pass
            products.append(p)
            if len(products) >= MAX_CATALOG_PRODUCTS:
                break
        if len(products) >= MAX_CATALOG_PRODUCTS:
            break
    data = {"built_at": now_iso(), "built_ts": time.time(), "count": len(products), "products": products}
    save_json(CATALOG_FILE, data)
    return data

def get_catalog():
    return build_catalog(False)
