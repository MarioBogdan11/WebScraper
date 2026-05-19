#!/usr/bin/env python3
"""
Web Scraper for Individual Web Scraping project pages
Usage: python web_scraper.py <URL>
Example: python web_scraper.py "https://www.archipelag.pl/projekty-domow/moniczka-iii-energo-plus-reco"
"""

import sys
import json
import re
import time
from urllib.parse import urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "beautifulsoup4", "lxml"])
    import requests
    from bs4 import BeautifulSoup


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_page(url: str) -> BeautifulSoup:
    """Fetch URL and return BeautifulSoup object."""
    print(f"\n🌐 Fetching: {url}")
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    print(f"✅ Status: {resp.status_code} | Size: {len(resp.content) / 1024:.1f} KB")
    return BeautifulSoup(resp.text, "lxml")


def clean(text: str) -> str:
    """Strip and collapse whitespace."""
    return re.sub(r"\s+", " ", text).strip() if text else ""


# ── Extraction helpers ──────────────────────────────────────────────────────

def get_meta(soup: BeautifulSoup) -> dict:
    """Extract <meta> tags: title, description, keywords."""
    return {
        "title":       clean(soup.title.get_text() if soup.title else ""),
        "description": soup.find("meta", {"name": "Description"}) and
                       soup.find("meta", {"name": "Description"}).get("content", ""),
        "keywords":    soup.find("meta", {"name": "Keywords"}) and
                       soup.find("meta", {"name": "Keywords"}).get("content", ""),
        "og_title":    soup.find("meta", {"property": "og:title"}) and
                       soup.find("meta", {"property": "og:title"}).get("content", ""),
        "og_image":    soup.find("meta", {"property": "og:image"}) and
                       soup.find("meta", {"property": "og:image"}).get("content", ""),
    }


def get_project_name(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1", class_="project_title")
    if h1:
        return clean(h1.get_text())
    return ""


def get_price(soup: BeautifulSoup) -> dict:
    prices = {}
    price_box = soup.find("div", class_="project_price")
    if price_box:
        current = price_box.find("p", class_="price_number")
        if current and "promotion" not in current.get("class", []):
            prices["current_price"] = clean(current.get_text())
        promo = price_box.find("p", class_=lambda c: c and "promotion" in c)
        if promo:
            prices["promo_price"] = clean(promo.get_text())
        old = price_box.find("p", class_="price_number_promotion")
        if old:
            prices["original_price"] = clean(old.get_text())
    return prices


def get_basic_stats(soup: BeautifulSoup) -> dict:
    """Parse the key-value list (area, footprint, volume, dimensions, etc.)."""
    stats = {}
    for row in soup.select(".light_list_row"):
        label_el = row.find("span", class_="light_list_item")
        value_el = row.find("span", class_="right")
        if label_el and value_el:
            key = clean(label_el.get_text()).rstrip(":")
            val = clean(value_el.get_text())
            if key and val:
                stats[key] = val
    return stats


def get_floor_rooms(soup: BeautifulSoup) -> list:
    """Extract floor-by-floor room lists."""
    floors = []
    for section in soup.select(".project_specific_section"):
        floor_data = {}
        h2 = section.find("h2")
        if h2:
            floor_data["floor"] = clean(h2.get_text())
        rooms = []
        for row in section.select(".light_list_row"):
            label_el = row.find("span", class_="light_list_item")
            value_el = row.find("span", class_="right")
            if label_el and value_el:
                room = clean(label_el.get_text())
                area = clean(value_el.get_text())
                if room and area:
                    rooms.append({"room": room, "area": area})
        if rooms:
            floor_data["rooms"] = rooms
            floors.append(floor_data)
    return floors


def get_description(soup: BeautifulSoup) -> str:
    """Get the full project description text."""
    parts = []
    for block in soup.select(".richtext"):
        txt = clean(block.get_text())
        if txt and len(txt) > 30:
            parts.append(txt)
    return "\n\n".join(dict.fromkeys(parts))  # deduplicate while preserving order


def get_images(soup: BeautifulSoup, base_url: str) -> list:
    """Collect all project image URLs."""
    images = []
    seen = set()
    for img in soup.select(".project_slider img, .project_view img"):
        src = img.get("data-src") or img.get("src", "")
        if src and "data:image" not in src and src not in seen:
            full = src if src.startswith("http") else base_url.rstrip("/") + "/" + src.lstrip("/")
            images.append(full)
            seen.add(src)
    return images


def get_categories(soup: BeautifulSoup) -> list:
    cats = []
    for a in soup.select(".project_box_category_link"):
        t = clean(a.get_text())
        if t:
            cats.append(t)
    return list(dict.fromkeys(cats))


def get_versions(soup: BeautifulSoup) -> list:
    versions = []
    for li in soup.select(".versions_list .version"):
        label = li.get("title") or li.get("rel") or clean(li.get_text())
        link_el = li.find("a")
        href = link_el["href"] if link_el else None
        versions.append({"label": clean(label), "url": href, "active": "active" in li.get("class", [])})
    return versions


def get_energy(soup: BeautifulSoup) -> dict:
    energy = {}
    ep_div = soup.find("div", class_="EnergyEP")
    if ep_div:
        energy["EP_indicator"] = clean(ep_div.get_text())
    wt_div = soup.find("div", class_="EnergyWT")
    if wt_div:
        energy["WT_standard"] = clean(wt_div.get_text())
    return energy


def get_build_costs(soup: BeautifulSoup) -> dict:
    costs = {}
    cost_table = soup.find("div", class_="EstimateBuildPLEnabled")
    if cost_table:
        for row in cost_table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                label = clean(cells[0].get_text())
                value = clean(cells[1].get_text())
                if label and value:
                    costs[label] = value
    return costs


def get_downloadable_files(soup: BeautifulSoup) -> list:
    files = []
    for item in soup.select(".project_files_list li.file a"):
        href = item.get("href", "")
        label = clean(item.get_text())
        if label:
            files.append({"label": label, "href": href})
    return files


def get_expert_opinion(soup: BeautifulSoup) -> dict:
    expert = {}
    block = soup.find("div", class_="expert_comment")
    if block:
        name_el = block.find("span", class_="expert_name")
        company_el = block.find("span", class_="expert_company")
        quote_el = block.find("p")
        if name_el:
            expert["name"] = clean(name_el.get_text())
        if company_el:
            expert["company"] = clean(company_el.get_text())
        if quote_el:
            expert["quote"] = clean(quote_el.get_text())
    return expert


def get_contact(soup: BeautifulSoup) -> dict:
    contact = {}
    phone = soup.find("strong", string=re.compile(r"\d{2}\s\d{3}\s\d{2}\s\d{2}"))
    if phone:
        contact["phone"] = clean(phone.get_text())
    email = soup.find("a", href=re.compile(r"mailto:"))
    if email:
        contact["email"] = email["href"].replace("mailto:", "")
    address_div = soup.find("div", class_="office_info")
    if address_div:
        contact["address"] = clean(address_div.get_text())
    return contact


def get_breadcrumbs(soup: BeautifulSoup) -> list:
    crumbs = []
    for li in soup.select(".breadcrumbs li"):
        txt = clean(li.get_text())
        if txt:
            crumbs.append(txt)
    return crumbs


def get_json_ld(soup: BeautifulSoup) -> dict:
    """Extract structured JSON-LD product data if present."""
    script = soup.find("script", {"type": "application/ld+json"})
    if script:
        try:
            return json.loads(script.string)
        except Exception:
            pass
    return {}


# ── Main scraper ────────────────────────────────────────────────────────────

def scrape(url: str) -> dict:
    soup = fetch_page(url)
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    print("\n⚙️  Extracting data...")

    data = {
        "url": url,
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "meta": get_meta(soup),
        "project_name": get_project_name(soup),
        "categories": get_categories(soup),
        "price": get_price(soup),
        "basic_stats": get_basic_stats(soup),
        "floors_and_rooms": get_floor_rooms(soup),
        "energy_data": get_energy(soup),
        "build_costs": get_build_costs(soup),
        "versions": get_versions(soup),
        "description": get_description(soup),
        "images": get_images(soup, base_url),
        "downloadable_files": get_downloadable_files(soup),
        "expert_opinion": get_expert_opinion(soup),
        "contact": get_contact(soup),
        "breadcrumbs": get_breadcrumbs(soup),
        "json_ld": get_json_ld(soup),
    }
    return data


def print_results(data: dict):
    SEP = "=" * 65

    print(f"\n{SEP}")
    print("  WEB SCRAPER RESULTS")
    print(SEP)

    print(f"\n📌 PROJECT: {data['project_name']}")
    print(f"🔗 URL:     {data['url']}")
    print(f"⏱️  Scraped: {data['scraped_at']}")

    print(f"\n{'─'*40}")
    print("📄 META")
    for k, v in data["meta"].items():
        if v:
            print(f"  {k}: {v[:120]}")

    if data["categories"]:
        print(f"\n{'─'*40}")
        print("🏷️  CATEGORIES")
        for c in data["categories"]:
            print(f"  • {c}")

    if data["price"]:
        print(f"\n{'─'*40}")
        print("💰 PRICE")
        for k, v in data["price"].items():
            print(f"  {k}: {v}")

    if data["basic_stats"]:
        print(f"\n{'─'*40}")
        print("📐 BASIC STATS")
        for k, v in data["basic_stats"].items():
            print(f"  {k}: {v}")

    if data["floors_and_rooms"]:
        print(f"\n{'─'*40}")
        print("🏠 FLOOR PLANS")
        for floor in data["floors_and_rooms"]:
            print(f"\n  [{floor.get('floor', 'Floor')}]")
            for room in floor.get("rooms", []):
                print(f"    {room['room']}: {room['area']}")

    if data["energy_data"]:
        print(f"\n{'─'*40}")
        print("⚡ ENERGY DATA")
        for k, v in data["energy_data"].items():
            print(f"  {k}: {v}")

    if data["build_costs"]:
        print(f"\n{'─'*40}")
        print("🏗️  BUILD COSTS (estimated)")
        for k, v in data["build_costs"].items():
            print(f"  {k}: {v}")

    if data["versions"]:
        print(f"\n{'─'*40}")
        print("📋 VERSIONS")
        for v in data["versions"]:
            active = " ← CURRENT" if v["active"] else ""
            print(f"  • {v['label']}{active}")

    if data["expert_opinion"]:
        print(f"\n{'─'*40}")
        print("🎓 EXPERT OPINION")
        e = data["expert_opinion"]
        print(f"  {e.get('name', '')} – {e.get('company', '')}")
        quote = e.get("quote", "")
        if quote:
            print(f"  \"{quote[:300]}{'...' if len(quote) > 300 else ''}\"")

    if data["images"]:
        print(f"\n{'─'*40}")
        print(f"🖼️  IMAGES ({len(data['images'])} found)")
        for img in data["images"][:5]:
            print(f"  {img}")
        if len(data["images"]) > 5:
            print(f"  ... and {len(data['images']) - 5} more")

    if data["downloadable_files"]:
        print(f"\n{'─'*40}")
        print("📁 DOWNLOADABLE FILES")
        for f in data["downloadable_files"]:
            print(f"  • {f['label']}")

    if data["contact"]:
        print(f"\n{'─'*40}")
        print("📞 CONTACT")
        for k, v in data["contact"].items():
            print(f"  {k}: {v[:100]}")

    if data["breadcrumbs"]:
        print(f"\n{'─'*40}")
        print("🗂️  BREADCRUMBS")
        print("  " + " › ".join(data["breadcrumbs"]))

    if data["json_ld"]:
        print(f"\n{'─'*40}")
        print("🔍 JSON-LD STRUCTURED DATA")
        ld = data["json_ld"]
        print(f"  Type:  {ld.get('@type', '')}")
        print(f"  Name:  {ld.get('name', '')}")
        offer = ld.get("offers", {})
        if offer:
            print(f"  Price: {offer.get('price', '')} {offer.get('priceCurrency', '')}")

    print(f"\n{SEP}\n")


def save_json(data: dict, filename: str = "scraped_data.json"):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 Full data saved to: {filename}")


# ── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default demo URL
        url = "https://www.archipelag.pl/projekty-domow/moniczka-iii-energo-plus-reco"
        print(f"No URL provided. Using demo: {url}")
    else:
        url = sys.argv[1]

    try:
        result = scrape(url)
        print_results(result)
        save_json(result)
    except requests.exceptions.RequestException as e:
        print(f"\n❌ Network error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        raise
