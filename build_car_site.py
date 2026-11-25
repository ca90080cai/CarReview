#!/usr/bin/env python3
"""🐉 新車龍龍 — 極簡獨立雲端建置引擎 (build_car_site.py)

100% Python 3.11+ 標準函式庫、零 pip install、零付費 API Key、零私有伺服器相依。
專為 GitHub Actions 雲端自主重建設計：
  1. 即時抓取台灣現行全品牌官方新車目錄（U-CAR 公開新車資料庫 + Toyota 台灣去背圖 + 免費即時匯率）
  2. 內建「停售下架即刻過濾守門員」，絕不顯示已停產／下架車款
  3. 整合 23 款台灣總代理未引進之「全新未領牌貿易商限定新車 (PI)」統一台幣完稅參考價
  4. 內建 6 大台灣買家核心精算引擎：
     - 雙軌透明定價（官方牌價 vs. 實車議價成交區間）
     - 2026 台灣原廠分期 0 利率 & 智選尾款 & 「0 利率 vs. 拿滿現金折價＋銀行低利」PK 引擎
     - 台灣精算養車成本（法定排氣量牌照＋燃料稅、純電 0 稅、丙/乙/甲式車險、油電費、保修與過保大修預備金）
     - 3 年／5 年單調遞減保值折舊曲線 & 新車 vs. 認證中古策略
     - 台灣精準純電／插電充電規格（CCS2 / CCS1 / AC Type1-2、800V 快充、V2L）
     - 改款世代週期與改款前後逐項對照表（含 W206 C-Class / C 300 2026/08 小改款深度對照）
  5. 輸出 100% 純靜態 GitHub Pages 網站至 `--out dist`（含 `index.html`, `data/bootstrap.json`, `favicon.ico`, `.nojekyll`）

執行方式：
  python3 build_car_site.py --out dist
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import html as html_lib
import json
import math
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
UCAR_BASE = "https://newcar.u-car.com.tw"
TOYOTA_TW_SHOWROOM = "https://www.toyota.com.tw/showroom.aspx"
FX_API_URL = "https://open.er-api.com/v6/latest/USD"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
}

# =========================================================================
# 1. BRAND METADATA, OFFICIAL OEM URLS, DELIST GUARD & COLORS
# =========================================================================

BRAND_CANONICAL: dict[str, str] = {
    "alfa romeo": "Alfa Romeo", "aston martin": "Aston Martin", "audi": "Audi",
    "bentley": "Bentley", "bmw": "BMW", "caterham": "Caterham",
    "citroën": "Citroën", "citroen": "Citroën", "cmc": "CMC", "dfsk": "DFSK",
    "ferrari": "Ferrari", "ford": "Ford", "foxtron": "Foxtron", "honda": "Honda",
    "hyundai": "Hyundai", "ineos grenadier": "INEOS", "ineos": "INEOS",
    "infiniti": "Infiniti", "jaguar": "Jaguar", "jeep": "Jeep", "kia": "Kia",
    "lamborghini": "Lamborghini", "land rover": "Land Rover", "lexus": "Lexus",
    "lotus": "Lotus", "luxgen": "Luxgen", "mahindra": "Mahindra",
    "maserati": "Maserati", "mazda": "Mazda", "mclaren": "McLaren",
    "mercedes-benz": "Mercedes-Benz", "mg": "MG", "mini": "MINI",
    "mitsubishi": "Mitsubishi", "morgan": "Morgan", "nissan": "Nissan",
    "opel": "Opel", "pagani": "Pagani", "peugeot": "Peugeot", "porsche": "Porsche",
    "rolls-royce": "Rolls-Royce", "subaru": "Subaru", "suzuki": "Suzuki",
    "tesla": "Tesla", "toyota": "Toyota", "volkswagen": "Volkswagen",
    "volkswagen commercial vehicles": "Volkswagen Commercial", "volvo": "Volvo",
    "škoda": "Škoda", "skoda": "Škoda",
}

BRAND_ZH: dict[str, str] = {
    "Mercedes-Benz": "賓士", "BMW": "寶馬", "Audi": "奧迪", "Porsche": "保時捷",
    "Toyota": "豐田", "Lexus": "凌志", "Honda": "本田", "Mazda": "馬自達",
    "Nissan": "日產", "Subaru": "速霸陸", "Suzuki": "鈴木", "Mitsubishi": "三菱",
    "Hyundai": "現代", "Kia": "起亞", "Tesla": "特斯拉", "Volvo": "富豪",
    "Volkswagen": "福斯", "Volkswagen Commercial": "福斯商旅", "Škoda": "斯柯達",
    "Ford": "福特", "MG": "名爵", "Luxgen": "納智捷", "Foxtron": "鴻華先進",
    "CMC": "中華汽車", "Land Rover": "荒原路華", "MINI": "迷你", "Peugeot": "寶獅",
    "Citroën": "雪鐵龍", "Opel": "歐寶", "Jeep": "吉普", "Alfa Romeo": "愛快羅密歐",
    "Maserati": "瑪莎拉蒂", "Ferrari": "法拉利", "Lamborghini": "藍寶堅尼",
    "Aston Martin": "奧斯頓馬丁", "Bentley": "賓利", "Rolls-Royce": "勞斯萊斯",
    "McLaren": "麥拉倫", "Lotus": "蓮花", "Infiniti": "極致", "Chevrolet": "雪佛蘭",
    "Dodge": "道奇", "RAM": "公羊", "INEOS": "英力士", "DFSK": "穩發商用",
}

BRAND_OFFICIAL_URLS: dict[str, str] = {
    "Alfa Romeo": "https://www.alfaromeo-tw.com", "Aston Martin": "https://www.astonmartin.com",
    "Audi": "https://www.audi.com.tw", "Bentley": "https://www.bentleymotors.com",
    "BMW": "https://www.bmw.com.tw", "Caterham": "https://caterhamcars.com",
    "Citroën": "https://www.citroen.com.tw", "CMC": "https://www.china-motor.com.tw",
    "DFSK": "https://www.dfsk.com.tw", "Ferrari": "https://www.ferrari.com",
    "Ford": "https://www.ford.com.tw", "Foxtron": "https://www.foxtronev.com",
    "Honda": "https://www.honda-taiwan.com.tw", "Hyundai": "https://www.hyundai-motor.com.tw",
    "INEOS": "https://ineosgrenadiertw.com", "Infiniti": "https://www.infiniti.com.tw",
    "Jaguar": "https://www.jaguar.tw", "Jeep": "https://www.jeep.com",
    "Kia": "https://www.kia.com/tw", "Lamborghini": "https://www.lamborghini.com",
    "Land Rover": "https://www.landrover.tw", "Lexus": "https://www.lexus.com.tw",
    "Lotus": "https://www.lotuscars.com", "Luxgen": "https://www.luxgen-motor.com.tw",
    "Maserati": "https://www.maserati.com/tw", "Mazda": "https://www.mazda.com.tw",
    "McLaren": "https://cars.mclaren.com", "Mercedes-Benz": "https://www.mercedes-benz.com.tw",
    "MG": "https://www.mgmotor.com.tw", "MINI": "https://www.mini.com.tw",
    "Mitsubishi": "https://www.mitsubishi-motors.com.tw", "Morgan": "https://morgan-motor.com",
    "Nissan": "https://new.nissan.com.tw", "Opel": "https://www.opel.tw",
    "Pagani": "https://www.pagani.com", "Peugeot": "https://www.peugeot.com.tw",
    "Porsche": "https://www.porsche.com/taiwan", "Rolls-Royce": "https://www.rolls-roycemotorcars.com",
    "Subaru": "https://www.subaru.asia/tw", "Suzuki": "https://www.taiwansuzuki.com.tw",
    "Tesla": "https://www.tesla.com/zh_tw", "Toyota": "https://www.toyota.com.tw",
    "Volkswagen": "https://www.volkswagen.com.tw", "Volkswagen Commercial": "https://www.volkswagen-commercial.com.tw",
    "Volvo": "https://www.volvocars.com/tw", "Škoda": "https://www.skoda.com.tw",
}

# Discontinued / delisted Taiwan models: (brand_low, exact_or_prefix_model_low)
DELISTED_TW_RULES: list[tuple[str, str, bool]] = [
    # (brand_low, keyword_low, exact_match_only)
    ("ford", "focus", False), ("ford", "kuga", False), ("ford", "mustang mach-e", False),
    ("mitsubishi", "colt plus", False), ("luxgen", "u6 neo", False), ("mg", "mg4", False),
    ("toyota", "gr supra", False), ("infiniti", "qx55", False), ("jaguar", "", False),
    ("opel", "mokka electric", False), ("subaru", "outback", False),
    ("tesla", "model s", False), ("tesla", "model x", False),
    ("porsche", "718 boxster", False), ("porsche", "718 cayman", False),
    ("porsche", "macan", True),  # fuel Macan discontinued; keep Macan Electric
    ("mahindra", "", False), ("ferrari", "296 gtb", True), ("ferrari", "296 gts", True),
]

DIRECT_FIXED_BRANDS = {"Tesla", "Foxtron", "Luxgen", "MG"}
EXOTIC_BRANDS = {
    "Ferrari", "Lamborghini", "McLaren", "Rolls-Royce", "Bentley",
    "Aston Martin", "Pagani", "Lotus", "Caterham", "Morgan", "INEOS",
}
LUXURY_BRANDS = {
    "Mercedes-Benz", "BMW", "Audi", "Lexus", "Porsche", "Volvo",
    "Land Rover", "Jaguar", "Maserati", "Infiniti", "Alfa Romeo", "MINI",
}
TW_CCS2_BRANDS = {
    "Tesla", "Volkswagen", "Volkswagen Commercial", "Škoda", "MG",
    "Opel", "Peugeot", "Citroën", "MINI", "Maserati", "Rolls-Royce", "Lotus", "smart",
}
# Brands/models where IMAGIN 360 renders generic/wrong silhouettes -> use real studio photos instead
IMAGIN_BLOCK_BRANDS = {"CMC", "Luxgen", "Foxtron", "DFSK", "Mahindra", "Caterham", "Morgan", "INEOS", "Pagani"}
IMAGIN_BLOCK_TOKENS = ("town ace", "zinger", "veryca", "j space", "delica", "vios", "custin", "bria", "n7", "n⁷")

BRAND_COLORS: dict[str, list[dict[str, Any]]] = {
    "Mercedes-Benz": [
        {"id": "polar-white", "name": "Polar White 極地白", "hex": "#F4F5F2", "price": 0},
        {"id": "obsidian-black", "name": "Obsidian Black 曜石黑", "hex": "#131519", "price": 0},
        {"id": "hightech-silver", "name": "High-Tech Silver 科技銀", "hex": "#C8CCD1", "price": 0},
        {"id": "graphite-grey", "name": "Graphite Grey 石墨灰", "hex": "#4D5157", "price": 0},
        {"id": "spectral-blue", "name": "Spectral Blue 光譜藍", "hex": "#1D3B6C", "price": 0},
        {"id": "patagonia-red", "name": "MANUFAKTUR 巴塔哥尼亞紅", "hex": "#9E1B24", "price": 23000},
    ],
    "BMW": [
        {"id": "alpine-white", "name": "Alpine White 雪山白", "hex": "#F5F6F4", "price": 0},
        {"id": "black-sapphire", "name": "Black Sapphire 寶石黑", "hex": "#14161A", "price": 0},
        {"id": "skyscraper-grey", "name": "Skyscraper Grey 摩天灰", "hex": "#8A9096", "price": 0},
        {"id": "portimao-blue", "name": "M Portimao Blue 波爾蒂芒藍", "hex": "#1B468C", "price": 0},
        {"id": "brooklyn-grey", "name": "M Brooklyn Grey 布魯克林灰", "hex": "#9AA2A9", "price": 0},
        {"id": "fire-red", "name": "Fire Red 炙焰紅", "hex": "#B41923", "price": 25000},
    ],
    "Porsche": [
        {"id": "white", "name": "冰純白 White", "hex": "#F5F5F3", "price": 0},
        {"id": "jet-black", "name": "金屬墨玉黑", "hex": "#141618", "price": 0},
        {"id": "gt-silver", "name": "GT Silver 金屬銀", "hex": "#B6BBC0", "price": 76000},
        {"id": "gentian-blue", "name": "龍膽藍 Gentian Blue", "hex": "#173466", "price": 76000},
        {"id": "crayon", "name": "蠟灰 Crayon", "hex": "#C4C2BC", "price": 152000},
        {"id": "carmine-red", "name": "胭脂紅 Carmine Red", "hex": "#A91620", "price": 152000},
    ],
    "Toyota": [
        {"id": "pearl-white", "name": "雪貂白 / 鉑鑽白", "hex": "#F5F5F3", "price": 0},
        {"id": "attitude-black", "name": "檀木黑", "hex": "#181A1E", "price": 0},
        {"id": "silver-metallic", "name": "極光銀", "hex": "#C8CDD2", "price": 0},
        {"id": "ash-grey", "name": "雲河灰", "hex": "#666C73", "price": 0},
        {"id": "emotional-red", "name": "炫魅紅", "hex": "#B41F27", "price": 10000},
    ],
    "Lexus": [
        {"id": "sonic-quartz", "name": "極光白 Sonic Quartz", "hex": "#F4F5F2", "price": 0},
        {"id": "sonic-titanium", "name": "極光鈦 Sonic Titanium", "hex": "#A5A8AC", "price": 0},
        {"id": "graphite-black", "name": "星耀黑 Graphite Black", "hex": "#15171B", "price": 0},
        {"id": "sonic-chrome", "name": "星熠灰 Sonic Chrome", "hex": "#5E6369", "price": 0},
        {"id": "celestial-blue", "name": "爵色藍 Celestial Blue", "hex": "#1A3259", "price": 0},
    ],
}

DEFAULT_COLORS = [
    {"id": "pearl-white", "name": "珍珠白 Pearl White", "hex": "#F4F5F2", "price": 0},
    {"id": "obsidian-black", "name": "曜石黑 Obsidian Black", "hex": "#17191D", "price": 0},
    {"id": "metallic-silver", "name": "極光銀 Metallic Silver", "hex": "#C4C9CE", "price": 0},
    {"id": "graphite-grey", "name": "鈦金屬灰 Graphite Grey", "hex": "#5C626A", "price": 0},
    {"id": "deep-blue", "name": "深海藍 Deep Blue", "hex": "#1E3A66", "price": 0},
    {"id": "crimson-red", "name": "炙熱紅 Crimson Red", "hex": "#B31D28", "price": 15000},
]

# =========================================================================
# 2. CURATED 23 BRAND-NEW PARALLEL IMPORTS (PI — 台灣總代理未引進全新未領牌)
#    All photos verified `thumb.wikimedia.org` (0 HTTP 429 / 0 Chrome ORB)
# =========================================================================

WIKI_T = "https://thumb.wikimedia.org/wikipedia/commons/thumb/"

PI_CURATED_SPECS: list[dict[str, Any]] = [
    {"id": "pi-ford-f-150-2026", "brand": "Ford", "model": "F-150", "model_zh": "F-150 全尺寸皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5885, 2029, 1920, 3693, 5], "official_url": "https://www.ford.com/trucks/f150/", "photos": [WIKI_T + "4/48/2024_Ford_F-150_Lariat_front_view.jpg/1280px-2024_Ford_F-150_Lariat_front_view.jpg", WIKI_T + "0/08/2024_Ford_F-150_King_Ranch_front_view.jpg/1280px-2024_Ford_F-150_King_Ranch_front_view.jpg"], "trims": [["XL (2.7L EcoBoost)", 2370000, "ICE", "2.7L 雙渦輪 V6", "325 hp", "542 Nm", 6.4, "EPA 21 MPG", "RWD/4x4", "10速自排"], ["XLT", 2660000, "ICE", "2.7L 雙渦輪 V6", "325 hp", "542 Nm", 6.2, "EPA 21 MPG", "RWD/4x4", "10速自排"], ["Lariat 4x4", 3770000, "ICE", "5.0L Coyote V8", "400 hp", "556 Nm", 5.9, "EPA 20 MPG", "AWD 4x4", "10速自排"], ["Platinum 油電版", 4310000, "HEV", "3.5L PowerBoost 油電 V6", "430 hp", "773 Nm", 5.3, "EPA 23 MPG", "AWD 4x4", "10速自排"], ["Raptor 越野旗艦", 4900000, "ICE", "3.5L H.O. 雙渦輪 V6", "450 hp", "691 Nm", 5.3, "EPA 16 MPG", "AWD 前後差速鎖", "10速自排"]]},
    {"id": "pi-ford-bronco-2026", "brand": "Ford", "model": "Bronco", "model_zh": "烈馬硬派越野 SUV（全新貿易商限定）", "body_style": "suv", "dims": [4811, 1928, 1852, 2949, 5], "official_url": "https://www.ford.com/suvs/bronco/", "photos": [WIKI_T + "d/de/2024_Ford_Bronco_2.7_Outer_Banks_V6_with_Sasquatch_Package_in_Cactus_Gray%2C_front_right%2C_06-26-2024.jpg/1280px-2024_Ford_Bronco_2.7_Outer_Banks_V6_with_Sasquatch_Package_in_Cactus_Gray%2C_front_right%2C_06-26-2024.jpg", WIKI_T + "d/d9/FORD_BRONCO_SIXTH_GENERATION_China.jpg/1280px-FORD_BRONCO_SIXTH_GENERATION_China.jpg"], "trims": [["Base 4-Door 4x4", 2410000, "ICE", "2.3L 渦輪直四", "300 hp", "441 Nm", 6.8, "EPA 20 MPG", "4WD", "10速自排"], ["Outer Banks 4x4", 2830000, "ICE", "2.7L 雙渦輪 V6", "330 hp", "563 Nm", 6.2, "EPA 19 MPG", "4WD", "10速自排"], ["Badlands Sasquatch", 3590000, "ICE", "2.7L 雙渦輪 V6", "330 hp", "563 Nm", 6.4, "EPA 17 MPG", "4WD 前後鎖", "10速自排"], ["Bronco Raptor", 5540000, "ICE", "3.0L 雙渦輪 V6", "418 hp", "597 Nm", 5.6, "EPA 15 MPG", "4WD", "10速強化自排"]]},
    {"id": "pi-ford-maverick-2026", "brand": "Ford", "model": "Maverick", "model_zh": "獨行俠都會油電皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5072, 1844, 1745, 3076, 5], "official_url": "https://www.ford.com/trucks/maverick/", "photos": [WIKI_T + "8/87/2022_Ford_Maverick.jpg/1280px-2022_Ford_Maverick.jpg", WIKI_T + "1/11/2022_Ford_Maverick_Lariat_Pick-Up_%2852805918565%29.jpg/1280px-2022_Ford_Maverick_Lariat_Pick-Up_%2852805918565%29.jpg"], "trims": [["XL Hybrid FWD", 1720000, "HEV", "2.5L 油電複合", "191 hp", "235 Nm", 7.7, "EPA 38 MPG", "FWD", "eCVT"], ["XLT Hybrid AWD", 1970000, "HEV", "2.5L 油電複合", "191 hp", "235 Nm", 7.5, "EPA 37 MPG", "AWD", "eCVT"], ["Lobo Street AWD", 2110000, "ICE", "2.0L 渦輪直四", "250 hp", "376 Nm", 6.1, "EPA 24 MPG", "AWD", "7速快排"], ["Tremor Off-Road", 2340000, "ICE", "2.0L 渦輪直四", "250 hp", "376 Nm", 6.4, "EPA 21 MPG", "AWD 後差速鎖", "8速自排"]]},
    {"id": "pi-toyota-tundra-2026", "brand": "Toyota", "model": "Tundra", "model_zh": "坦途全尺寸雙渦輪皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5933, 2037, 1981, 3701, 5], "official_url": "https://www.toyota.com/tundra/", "photos": [WIKI_T + "8/85/2022_Toyota_Tundra_CrewMax_Limited%2C_front_6.30.22.jpg/1280px-2022_Toyota_Tundra_CrewMax_Limited%2C_front_6.30.22.jpg", WIKI_T + "8/82/2022_Toyota_Tundra_Double_Cab_SR5%2C_front_4.5.23.jpg/1280px-2022_Toyota_Tundra_Double_Cab_SR5%2C_front_4.5.23.jpg"], "trims": [["SR5 CrewMax", 2810000, "ICE", "3.4L 雙渦輪 V6", "389 hp", "649 Nm", 6.2, "EPA 20 MPG", "RWD/4WD", "10速自排"], ["Limited 4WD", 3680000, "ICE", "3.4L 雙渦輪 V6", "389 hp", "649 Nm", 6.1, "EPA 19 MPG", "4WD", "10速自排"], ["Platinum Hybrid 4WD", 4320000, "HEV", "3.4L i-FORCE MAX 油電", "437 hp", "790 Nm", 5.7, "EPA 20 MPG", "4WD", "10速自排"], ["TRD Pro 4WD", 4600000, "HEV", "3.4L i-FORCE MAX 油電", "437 hp", "790 Nm", 5.7, "EPA 19 MPG", "4WD 後差速鎖", "10速自排"]]},
    {"id": "pi-toyota-tacoma-2026", "brand": "Toyota", "model": "Tacoma", "model_zh": "塔科馬第4代美規皮卡霸主（全新貿易商限定）", "body_style": "pickup", "dims": [5410, 1953, 1879, 3350, 5], "official_url": "https://www.toyota.com/tacoma/", "photos": [WIKI_T + "3/3c/2024_Toyota_Tacoma_TRD_Off-Road.jpg/1280px-2024_Toyota_Tacoma_TRD_Off-Road.jpg", WIKI_T + "e/e6/2024_Toyota_Tacoma_TRD_Sport_front_view.jpg/1280px-2024_Toyota_Tacoma_TRD_Sport_front_view.jpg"], "trims": [["SR5 Double Cab", 2270000, "ICE", "2.4L 渦輪直四", "278 hp", "430 Nm", 7.0, "EPA 21 MPG", "RWD/4WD", "8速自排"], ["TRD Off-Road 4WD", 2570000, "ICE", "2.4L 渦輪直四", "278 hp", "430 Nm", 7.0, "EPA 20 MPG", "4WD 後差速鎖", "8速自排"], ["Limited Hybrid 4WD", 3550000, "HEV", "2.4L 渦輪油電", "326 hp", "630 Nm", 6.2, "EPA 23 MPG", "4WD", "8速自排"], ["TRD Pro Hybrid", 4010000, "HEV", "2.4L i-FORCE MAX", "326 hp", "630 Nm", 6.3, "EPA 23 MPG", "4WD 防傾桿斷開", "8速自排"]]},
    {"id": "pi-toyota-4runner-2026", "brand": "Toyota", "model": "4Runner", "model_zh": "超霸第6代大改款越野傳奇（全新貿易商限定）", "body_style": "suv", "dims": [4950, 1976, 1798, 2850, 5], "official_url": "https://www.toyota.com/4runner/", "photos": [WIKI_T + "5/55/%2725_Toyota_4Runner.jpg/1280px-%2725_Toyota_4Runner.jpg", WIKI_T + "0/0a/2025_Toyota_4Runner_TRD_Sport_in_Wind_Chill_Pearl%2C_front_right%2C_2025-05-18.jpg/1280px-2025_Toyota_4Runner_TRD_Sport_in_Wind_Chill_Pearl%2C_front_right%2C_2025-05-18.jpg"], "trims": [["SR5 2WD", 2450000, "ICE", "2.4L 渦輪直四", "278 hp", "430 Nm", 7.1, "EPA 22 MPG", "RWD/4WD", "8速自排"], ["TRD Off-Road 4WD", 2890000, "ICE", "2.4L 渦輪直四", "278 hp", "430 Nm", 7.1, "EPA 21 MPG", "4WD 後差速鎖", "8速自排"], ["Limited 4WD", 3640000, "ICE", "2.4L 渦輪直四", "278 hp", "430 Nm", 7.1, "EPA 21 MPG", "全時4WD", "8速自排"], ["TRD Pro Hybrid", 4190000, "HEV", "2.4L i-FORCE MAX", "326 hp", "630 Nm", 6.4, "EPA 23 MPG", "4WD", "8速自排"]]},
    {"id": "pi-toyota-sequoia-2026", "brand": "Toyota", "model": "Sequoia", "model_zh": "紅杉全尺寸油電大樑旗艦（全新貿易商限定）", "body_style": "suv", "dims": [5286, 2022, 1892, 3099, 7], "official_url": "https://www.toyota.com/sequoia/", "photos": [WIKI_T + "3/33/2023_Toyota_Sequoia.jpg/1280px-2023_Toyota_Sequoia.jpg", WIKI_T + "7/74/2023_Toyota_Sequoia_%28cropped%29.jpg/1280px-2023_Toyota_Sequoia_%28cropped%29.jpg"], "trims": [["SR5 Hybrid", 3930000, "HEV", "3.4L 雙渦輪 V6 油電", "437 hp", "790 Nm", 5.6, "EPA 22 MPG", "RWD/4WD", "10速自排"], ["Limited 4WD", 4480000, "HEV", "3.4L 雙渦輪 V6 油電", "437 hp", "790 Nm", 5.6, "EPA 20 MPG", "4WD", "10速自排"], ["Capstone Luxury 4WD", 5180000, "HEV", "3.4L 雙渦輪 V6 油電", "437 hp", "790 Nm", 5.6, "EPA 20 MPG", "4WD", "10速自排"]]},
    {"id": "pi-toyota-grand-highlander-2026", "brand": "Toyota", "model": "Grand Highlander", "model_zh": "大漢蘭達全成人三排家庭神車（全新貿易商限定）", "body_style": "suv", "dims": [5116, 1989, 1781, 2949, 7], "official_url": "https://www.toyota.com/grandhighlander/", "photos": [WIKI_T + "e/e3/2024_Toyota_Grand_Highlander_Limited%2C_front_11.22.23.jpg/1280px-2024_Toyota_Grand_Highlander_Limited%2C_front_11.22.23.jpg", WIKI_T + "6/66/2024_Toyota_Grand_Highlander_XLE_AWD_in_Blueprint%2C_Front_Right%2C_09-10-2023.jpg/1280px-2024_Toyota_Grand_Highlander_XLE_AWD_in_Blueprint%2C_Front_Right%2C_09-10-2023.jpg"], "trims": [["LE FWD", 2450000, "ICE", "2.4L 渦輪直四", "265 hp", "420 Nm", 7.5, "EPA 24 MPG", "FWD", "8速自排"], ["Hybrid XLE AWD", 2800000, "HEV", "2.5L 油電四驅", "245 hp", "239 Nm", 7.8, "EPA 36 MPG", "AWD", "eCVT"], ["Hybrid Limited AWD", 3110000, "HEV", "2.5L 油電四驅", "245 hp", "239 Nm", 7.8, "EPA 34 MPG", "AWD", "eCVT"], ["Hybrid MAX Platinum", 3740000, "HEV", "2.4L 渦輪油電", "362 hp", "542 Nm", 5.8, "EPA 27 MPG", "AWD", "6速手自排"]]},
    {"id": "pi-toyota-gr-corolla-2026", "brand": "Toyota", "model": "GR Corolla", "model_zh": "GR Corolla 300hp 四驅終極鋼砲（全新貿易商限定）", "body_style": "hatchback", "dims": [4410, 1850, 1480, 2640, 5], "official_url": "https://www.toyota.com/grcorolla/", "photos": [WIKI_T + "6/66/2023-2025_Toyota_GR_Corolla_RZ_rear.jpg/1280px-2023-2025_Toyota_GR_Corolla_RZ_rear.jpg", WIKI_T + "f/f7/Toyota_Corolla_GR_Sport_Hybrid_Genf_2019_1Y7A5579.jpg/1280px-Toyota_Corolla_GR_Sport_Hybrid_Genf_2019_1Y7A5579.jpg"], "trims": [["Core (6MT / 8AT DAT)", 2280000, "ICE", "1.6L G16E-GTS 三缸渦輪", "300 hp", "400 Nm", 4.9, "EPA 24 MPG (10.2 km/L)", "GR-FOUR AWD", "6MT / 8AT DAT"], ["Premium Plus 碳纖頂", 2600000, "ICE", "1.6L G16E-GTS 三缸渦輪", "300 hp", "400 Nm", 4.9, "EPA 24 MPG (10.2 km/L)", "GR-FOUR AWD", "6MT / 8AT DAT"]]},
    {"id": "pi-toyota-crown-signia-2026", "brand": "Toyota", "model": "Crown Signia", "model_zh": "皇冠 Signia 豪華跨界油電旅行車（全新貿易商限定）", "body_style": "suv", "dims": [4930, 1880, 1625, 2850, 5], "official_url": "https://www.toyota.com/crownsignia/", "photos": [WIKI_T + "a/a1/The_frontview_of_Toyota_CROWN%22ESTATE_Z%22_%286AA-AZSH38W-CNXGB%29.jpg/1280px-The_frontview_of_Toyota_CROWN%22ESTATE_Z%22_%286AA-AZSH38W-CNXGB%29.jpg", WIKI_T + "a/ae/The_frontview_of_Toyota_CROWN_ESTATE_Z_%286AA-AZSH38W-CNXGB%29.jpg/1280px-The_frontview_of_Toyota_CROWN_ESTATE_Z_%286AA-AZSH38W-CNXGB%29.jpg"], "trims": [["XLE Hybrid AWD", 2660000, "HEV", "2.5L 油電電子四驅", "240 hp", "241 Nm", 7.1, "EPA 38 MPG (16.2 km/L)", "AWD", "eCVT"], ["Limited Hybrid AWD", 2890000, "HEV", "2.5L 油電電子四驅", "240 hp", "241 Nm", 7.1, "EPA 38 MPG (16.2 km/L)", "AWD", "eCVT"]]},
    {"id": "pi-lexus-gx-2026", "brand": "Lexus", "model": "GX", "model_zh": "GX 550 硬派豪華方正越野休旅（全新貿易商限定）", "body_style": "suv", "dims": [5005, 2117, 1920, 2850, 7], "official_url": "https://www.lexus.com/models/GX", "photos": [WIKI_T + "1/1d/24_Lexus_GX_550_Luxury.jpg/1280px-24_Lexus_GX_550_Luxury.jpg", WIKI_T + "c/ca/2024_Lexus_GX_550_Overtrail_%28United_States%29_rear_view.jpg/1280px-2024_Lexus_GX_550_Overtrail_%28United_States%29_rear_view.jpg"], "trims": [["GX 550 Premium 七座", 4100000, "ICE", "3.4L V6 雙渦輪", "349 hp", "650 Nm", 6.5, "EPA 17 MPG (7.2 km/L)", "全時4WD", "10速手自排"], ["GX 550 Overtrail+ 越野", 4550000, "ICE", "3.4L V6 雙渦輪", "349 hp", "650 Nm", 6.5, "EPA 17 MPG (7.2 km/L)", "4WD 雙差速鎖", "10速手自排"], ["GX 550 Luxury+ 旗艦", 5060000, "ICE", "3.4L V6 雙渦輪", "349 hp", "650 Nm", 6.5, "EPA 17 MPG (7.2 km/L)", "全時4WD", "10速手自排"]]},
    {"id": "pi-lexus-lx-2026", "brand": "Lexus", "model": "LX", "model_zh": "LX 600 / 700h 旗艦陸地王者（全新貿易商限定）", "body_style": "suv", "dims": [5100, 1990, 1895, 2850, 7], "official_url": "https://www.lexus.com/models/LX", "photos": [WIKI_T + "c/c2/Lexus_LX_600_VJA310_Atomic_Silver_%282%29.jpg/1280px-Lexus_LX_600_VJA310_Atomic_Silver_%282%29.jpg", WIKI_T + "9/96/LEXUS_LX_600_F-SPORT_%28J310%29_China.jpg/1280px-LEXUS_LX_600_F-SPORT_%28J310%29_China.jpg"], "trims": [["LX 600 Premium", 6520000, "ICE", "3.4L V6 雙渦輪", "409 hp", "650 Nm", 6.8, "EPA 19 MPG", "全時4WD", "10速手自排"], ["LX 700h Overtrail 油電", 7010000, "HEV", "3.4L V6 雙渦輪油電", "457 hp", "790 Nm", 6.4, "EPA 20 MPG", "4WD 前中後三鎖", "10速手自排"], ["LX 700h Ultra Luxury", 8530000, "HEV", "3.4L V6 雙渦輪油電", "457 hp", "790 Nm", 6.4, "EPA 20 MPG", "全時4WD", "10速手自排"]]},
    {"id": "pi-lexus-tx-2026", "brand": "Lexus", "model": "TX", "model_zh": "TX 真三排大空間豪華旗艦休旅（全新貿易商限定）", "body_style": "suv", "dims": [5159, 1989, 1781, 2949, 7], "official_url": "https://www.lexus.com/models/TX", "photos": [WIKI_T + "c/c3/2024_Lexus_TX350_in_Wind_Chill_Pearl%2C_front_right.jpg/1280px-2024_Lexus_TX350_in_Wind_Chill_Pearl%2C_front_right.jpg", WIKI_T + "b/b6/2024_Lexus_TX_500h_F_Sport_%28United_States%29_front_view.png/1280px-2024_Lexus_TX_500h_F_Sport_%28United_States%29_front_view.png"], "trims": [["TX 350 FWD", 3590000, "ICE", "2.4L 渦輪直四", "275 hp", "430 Nm", 7.8, "EPA 23 MPG", "FWD", "8速手自排"], ["TX 500h F SPORT AWD", 4380000, "HEV", "2.4L 渦輪油電 + Direct4", "366 hp", "550 Nm", 6.1, "EPA 27 MPG", "AWD 後輪轉向", "6速手自排"], ["TX 550h+ V6 PHEV", 4870000, "PHEV", "3.5L V6 插電油電 18.1kWh", "404 hp", "540 Nm", 5.9, "純電53km / 29 MPG", "Direct4 AWD", "eCVT"]]},
    {"id": "pi-chevrolet-corvette-c8-2026", "brand": "Chevrolet", "model": "Corvette C8", "model_zh": "科爾維特 C8 中置 V8 超跑（全新貿易商限定）", "body_style": "coupe", "dims": [4630, 1933, 1234, 2723, 2], "official_url": "https://www.chevrolet.com/performance/corvette", "photos": [WIKI_T + "4/4b/Chevrolet_Corvette_C8_IAA_2021_1X7A0156.jpg/1280px-Chevrolet_Corvette_C8_IAA_2021_1X7A0156.jpg", WIKI_T + "6/63/Chevrolet_Corvette_C8_convertibles_IAA_2021_1X7A0184.jpg/1280px-Chevrolet_Corvette_C8_convertibles_IAA_2021_1X7A0184.jpg"], "trims": [["Stingray 1LT Coupe", 4380000, "ICE", "6.2L LT2 中置 V8", "490 hp", "630 Nm", 3.1, "EPA 20 MPG", "RWD", "8速雙離合"], ["Stingray 2LT Coupe", 4790000, "ICE", "6.2L LT2 中置 V8", "495 hp", "630 Nm", 3.1, "EPA 20 MPG", "RWD", "8速雙離合"], ["E-Ray 油電四驅", 6620000, "HEV", "6.2L V8 + 前軸電馬達", "655 hp", "807 Nm", 2.6, "EPA 19 MPG", "eAWD", "8速雙離合"], ["Z06 1LZ (8,600rpm)", 7150000, "ICE", "5.5L LT6 平曲軸 V8", "670 hp", "624 Nm", 2.7, "EPA 15 MPG", "RWD", "8速雙離合"]]},
    {"id": "pi-chevrolet-silverado-1500-2026", "brand": "Chevrolet", "model": "Silverado 1500", "model_zh": "索羅德美式全尺寸皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5885, 2063, 1918, 3745, 5], "official_url": "https://www.chevrolet.com/trucks/silverado/1500", "photos": [WIKI_T + "a/a4/2023_Chevrolet_Silverado_1500_RST_Las_Vegas_Fall_2025.jpg/1280px-2023_Chevrolet_Silverado_1500_RST_Las_Vegas_Fall_2025.jpg", WIKI_T + "6/65/2023_Chevrolet_Silverado_1500_au_S.I.A.M._2023.JPG/1280px-2023_Chevrolet_Silverado_1500_au_S.I.A.M._2023.JPG"], "trims": [["WT Crew Cab", 2650000, "ICE", "2.7L TurboMax 渦輪直四", "310 hp", "583 Nm", 6.9, "EPA 19 MPG", "RWD/4WD", "8速自排"], ["LT 4WD (5.3L V8)", 3490000, "ICE", "5.3L V8", "355 hp", "519 Nm", 6.4, "EPA 17 MPG", "4WD", "10速自排"], ["ZR2 Off-Road 6.2L", 4490000, "ICE", "6.2L V8", "420 hp", "624 Nm", 5.5, "EPA 15 MPG", "4WD 前後鎖", "10速自排"]]},
    {"id": "pi-chevrolet-tahoe-2026", "brand": "Chevrolet", "model": "Tahoe", "model_zh": "太浩全尺寸 V8 休旅霸主（全新貿易商限定）", "body_style": "suv", "dims": [5352, 2057, 1928, 3071, 7], "official_url": "https://www.chevrolet.com/suvs/tahoe", "photos": [WIKI_T + "5/54/2024_Chevrolet_Tahoe_5.3_High_Country_V8%2C_06-20-2024.jpg/1280px-2024_Chevrolet_Tahoe_5.3_High_Country_V8%2C_06-20-2024.jpg", WIKI_T + "d/db/2024_Chevrolet_Tahoe_5.3_Z71_V8%2C_front_right%2C_06-16-2024.jpg/1280px-2024_Chevrolet_Tahoe_5.3_Z71_V8%2C_front_right%2C_06-16-2024.jpg"], "trims": [["LS 2WD", 3740000, "ICE", "5.3L V8", "355 hp", "519 Nm", 7.1, "EPA 17 MPG", "RWD", "10速自排"], ["Z71 Off-Road 4WD", 4430000, "ICE", "5.3L V8", "355 hp", "519 Nm", 7.0, "EPA 16 MPG", "4WD 加力箱", "10速自排"], ["High Country 6.2L", 5060000, "ICE", "6.2L V8", "420 hp", "624 Nm", 5.9, "EPA 16 MPG", "4WD", "10速自排"]]},
    {"id": "pi-ram-1500-2026", "brand": "RAM", "model": "1500", "model_zh": "公羊 1500 螺旋彈簧豪華皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5916, 2085, 1971, 3672, 5], "official_url": "https://www.ramtrucks.com/ram-1500.html", "photos": [WIKI_T + "8/84/2025_RAM_1500%2C_front_7.1.25.jpg/1280px-2025_RAM_1500%2C_front_7.1.25.jpg", WIKI_T + "b/bb/2025_RAM_1500_Limited%2C_front_5.23.25.jpg/1280px-2025_RAM_1500_Limited%2C_front_5.23.25.jpg"], "trims": [["Tradesman 4x2", 2570000, "MHEV", "3.6L V6 + 48V", "305 hp", "365 Nm", 7.4, "EPA 22 MPG", "RWD", "8速自排"], ["Big Horn 4x4 Hurricane", 3070000, "ICE", "3.0L 雙渦輪直六", "420 hp", "636 Nm", 5.3, "EPA 19 MPG", "4WD", "8速自排"], ["RHO Off-Road 540hp", 4370000, "ICE", "3.0L H.O. 雙渦輪直六", "540 hp", "706 Nm", 4.6, "EPA 15 MPG", "4WD", "8速強化自排"]]},
    {"id": "pi-jeep-gladiator-2026", "brand": "Jeep", "model": "Gladiator", "model_zh": "角鬥士敞篷硬軸越野皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5537, 1875, 1905, 3487, 5], "official_url": "https://www.jeep.com/gladiator.html", "photos": [WIKI_T + "4/4e/2018_Jeep_Gladiator.jpg/1280px-2018_Jeep_Gladiator.jpg", WIKI_T + "9/93/2020_Jeep_Gladiator_%28JT%29%2C_front_6.6.20.jpg/1280px-2020_Jeep_Gladiator_%28JT%29%2C_front_6.6.20.jpg"], "trims": [["Sport 4x4", 2340000, "ICE", "3.6L V6", "285 hp", "353 Nm", 7.5, "EPA 19 MPG", "4WD", "8速自排"], ["Rubicon Rock-Trac 4x4", 3090000, "ICE", "3.6L V6", "285 hp", "353 Nm", 7.8, "EPA 19 MPG", "4WD 前後差速鎖", "8速自排"]]},
    {"id": "pi-jeep-grand-cherokee-2026", "brand": "Jeep", "model": "Grand Cherokee", "model_zh": "大切諾基美式豪華 SUV（全新貿易商限定）", "body_style": "suv", "dims": [4915, 1968, 1798, 2964, 5], "official_url": "https://www.jeep.com/grand-cherokee.html", "photos": [WIKI_T + "0/07/Auto_Jeep_Grand_Cherokee_Elektrostal_Karla_Marksa_Street_30A%2C_Elektrostal_%D0%9D476%D0%A3%D0%A1197_2024-10_1728831464.jpg/1280px-Auto_Jeep_Grand_Cherokee_Elektrostal_Karla_Marksa_Street_30A%2C_Elektrostal_%D0%9D476%D0%A3%D0%A1197_2024-10_1728831464.jpg", WIKI_T + "3/3f/CC_Grand_Cherokee_1.jpg/1280px-CC_Grand_Cherokee_1.jpg"], "trims": [["Laredo 4x2", 2250000, "ICE", "3.6L V6", "293 hp", "353 Nm", 7.4, "EPA 22 MPG", "RWD", "8速自排"], ["Limited 4x4", 2670000, "ICE", "3.6L V6", "293 hp", "353 Nm", 7.4, "EPA 22 MPG", "4WD", "8速自排"], ["Summit Reserve 4xe PHEV", 4470000, "PHEV", "2.0T 插電油電", "375 hp", "637 Nm", 5.6, "純電40km / 56 MPGe", "4WD", "8速自排"]]},
    {"id": "pi-dodge-charger-daytona-2026", "brand": "Dodge", "model": "Charger Daytona", "model_zh": "戰馬第8代純電美式肌肉轎跑（全新貿易商限定）", "body_style": "coupe", "dims": [5248, 2028, 1497, 3074, 5], "official_url": "https://www.dodge.com/charger.html", "photos": [WIKI_T + "0/06/2024_Dodge_Charger_Daytona_RT%2C_front_4.14.25.jpg/1280px-2024_Dodge_Charger_Daytona_RT%2C_front_4.14.25.jpg", WIKI_T + "6/60/2024_Dodge_Charger_Daytona_Scat_Pack_in_Redeye%2C_front_left%2C_2026-08-30.jpg/1280px-2024_Dodge_Charger_Daytona_Scat_Pack_in_Redeye%2C_front_left%2C_2026-08-30.jpg"], "trims": [["Daytona R/T AWD", 2850000, "BEV", "雙馬達四驅 100.5kWh", "496 hp", "548 Nm", 4.7, "純電續航 496 km", "AWD", "單速直驅"], ["Scat Pack AWD 670hp", 3810000, "BEV", "雙馬達四驅 100.5kWh", "670 hp", "850 Nm", 3.3, "純電續航 388 km", "AWD 甩尾模式", "單速直驅"]]},
    {"id": "pi-dodge-durango-2026", "brand": "Dodge", "model": "Durango", "model_zh": "杜蘭戈 V8 肌肉三排性能 SUV（全新貿易商限定）", "body_style": "suv", "dims": [5100, 1925, 1801, 3043, 7], "official_url": "https://www.dodge.com/durango.html", "photos": [WIKI_T + "b/bf/2022_Dodge_Durango_RT_%28facelift%29%2C_front_6.21.22.jpg/1280px-2022_Dodge_Durango_RT_%28facelift%29%2C_front_6.21.22.jpg", WIKI_T + "f/fb/%2721_Dodge_Durango_SRT.png/1280px-%2721_Dodge_Durango_SRT.png"], "trims": [["GT AWD", 2430000, "ICE", "3.6L V6", "295 hp", "353 Nm", 7.4, "EPA 21 MPG", "AWD", "8速自排"], ["R/T 5.7L HEMI V8", 3090000, "ICE", "5.7L HEMI V8", "360 hp", "529 Nm", 6.2, "EPA 17 MPG", "AWD", "8速自排"], ["SRT Hellcat 710hp", 6190000, "ICE", "6.2L 機械增壓 V8", "710 hp", "875 Nm", 3.5, "EPA 13 MPG", "AWD", "8速強化自排"]]},
    {"id": "pi-tesla-cybertruck-2026", "brand": "Tesla", "model": "Cybertruck", "model_zh": "賽博皮卡不鏽鋼線傳純電皮卡（全新貿易商限定）", "body_style": "pickup", "dims": [5683, 2201, 1791, 3635, 5], "official_url": "https://www.tesla.com/cybertruck", "photos": [WIKI_T + "2/26/2024_Tesla_Cybertruck%2C_Moab_02.jpg/1280px-2024_Tesla_Cybertruck%2C_Moab_02.jpg", WIKI_T + "9/95/2024_Tesla_Cybertruck_Foundation_Series%2C_front_left_%28Greenwich%29.jpg/1280px-2024_Tesla_Cybertruck_Foundation_Series%2C_front_left_%28Greenwich%29.jpg"], "trims": [["All-Wheel Drive 雙馬達", 4160000, "BEV", "800V 雙馬達 123kWh", "600 hp", "1,008 Nm", 4.1, "純電續航 523 km", "AWD 線傳轉向", "單速直驅"], ["Cyberbeast 三馬達 845hp", 5190000, "BEV", "800V 三馬達 123kWh", "845 hp", "1,396 Nm", 2.7, "純電續航 515 km", "AWD 扭力向量", "單速直驅"]]},
    {"id": "pi-mercedes-benz-sprinter-passenger-van-2026", "brand": "Mercedes-Benz", "model": "Sprinter Passenger Van", "model_zh": "美製 12/15 人座豪華高頂商旅旗艦（全新貿易商限定）", "body_style": "mpv", "dims": [5932, 2020, 2460, 3665, 12], "official_url": "https://www.mbvans.com/en/sprinter/passenger-van", "photos": [WIKI_T + "c/c0/Benz_VS30_Sprinter.png/1280px-Benz_VS30_Sprinter.png", WIKI_T + "6/6c/MB_Sprinter_VS30_Maqsim_Pro.jpg/1280px-MB_Sprinter_VS30_Maqsim_Pro.jpg"], "trims": [["2500 Standard Roof 12座", 3120000, "ICE", "2.0L 柴油渦輪", "170 hp", "400 Nm", 11.2, "高速約 23 MPG", "RWD", "9G-TRONIC"], ["2500 High Roof 15座", 3930000, "ICE", "2.0L 雙渦輪柴油", "211 hp", "450 Nm", 9.8, "長途約 21 MPG", "RWD", "9G-TRONIC"], ["2500 High Roof AWD VIP", 4140000, "ICE", "2.0L 雙渦輪柴油", "211 hp", "450 Nm", 10.1, "綜合約 20 MPG", "AWD 電子四驅", "9G-TRONIC"]]},
]

# =========================================================================
# 3. BUYER INTELLIGENCE ENGINES (FINANCING, OWNERSHIP, RESALE, EV, LIFECYCLE)
# =========================================================================

NO_ZERO_APR_TOKENS = (
    "alphard", "lm ", "lm350", "lm500", "g-class", "g class", "maybach", "amg gt",
    "sl ", "jimny", "type r", "gr yaris", "gr86", "gr corolla", "mx-5", "m3",
    "m4", "m5", "m8", "xm", "z4", "rs 6", "rs6", "rs 3", "rs3", "gt3", "gt4",
    "cybertruck", "corvette", "mustang", "ranger raptor", "bronco",
)

# Brand -> (distributor, has_zero_apr, [(min_msrp, cap, months, title)], subsidy_rate, bank_aprs, balloon_or_None, note)
TW_FINANCING_PROFILES: dict[str, tuple] = {
    "Toyota": ("和泰汽車／和潤企業", True, [(1_600_000, 800_000, 40, "和泰高額 0 利率"), (1_000_000, 600_000, 30, "和泰分期 0 利率"), (0, 600_000, 40, "國產主力 0 利率")], 0.032, (2.38, 2.68, 3.28), None, "和泰常態推 60–80 萬 0 利率，可併用舊換新 5 萬；純現金購車通常可將補貼息轉回折價。"),
    "Lexus": ("和泰／L-finesse 智選", True, [(2_500_000, 1_200_000, 40, "Lexus 高額 0 利率"), (0, 1_000_000, 40, "Lexus 百萬 40 期 0 利率")], 0.034, (2.28, 2.58, 3.18), ("L-finesse 智選（48 期尾款型）", 20, 48, 48, 2.68), "UX／LBX／ES／NX／RX 適用 L-finesse 智選與指定月份百萬 0 利率。"),
    "Mercedes-Benz": ("台灣賓士資融", True, [(4_000_000, 2_400_000, 40, "星級旗艦高額 0 利率"), (2_600_000, 1_600_000, 40, "星耀版 160 萬 40 期 0 利率"), (0, 1_200_000, 40, "三芒星 120 萬 40 期 0 利率")], 0.038, (2.28, 2.58, 3.18), ("Agility 星自選（36 期尾款型）", 20, 36, 52, 2.68), "台灣賓士資融主力車系常態提供 120–240 萬 40 期 0 利率與 Agility 星自選（期滿 3 選 1）。"),
    "BMW": ("汎德 BMW Financial", True, [(4_000_000, 2_000_000, 48, "BMW 旗艦 200 萬 48 期 0 利率"), (2_400_000, 1_500_000, 48, "BMW 主力 150 萬 48 期 0 利率"), (0, 1_200_000, 48, "BMW 120 萬 48 期 0 利率")], 0.040, (2.28, 2.58, 3.18), ("BMW 智選專案（36 期低月付）", 20, 36, 50, 2.68), "汎德常態提供 120–200 萬 48 期 0 利率及智選低月付方案。"),
    "Audi": ("台灣奧迪財務", True, [(3_200_000, 2_000_000, 48, "Audi 200 萬 48 期 0 利率"), (2_000_000, 1_500_000, 48, "Audi 150 萬 48 期 0 利率"), (0, 1_200_000, 48, "Audi 120 萬 48 期 0 利率")], 0.040, (2.35, 2.65, 3.25), ("Audi 智選低月付（36 期）", 20, 36, 48, 2.68), "台灣奧迪全車系享 5 年保固，0 利率額度高且現金折讓彈性大。"),
    "Volvo": ("國際富豪 Volvo 財富方案", True, [(2_500_000, 1_500_000, 40, "Volvo 150 萬 40 期 0 利率"), (0, 1_200_000, 40, "Volvo 120 萬 40 期 0 利率")], 0.036, (2.38, 2.68, 3.28), ("Volvo 智慧分期（36 期）", 15, 36, 46, 2.75), "主打 120–150 萬 40 期 0 利率，跨年式現車折讓更甜。"),
    "Volkswagen": ("台灣福斯財務 VWFS", True, [(1_600_000, 1_000_000, 40, "福斯百萬 40 期 0 利率"), (0, 800_000, 36, "福斯 80 萬 36 期 0 利率")], 0.036, (2.45, 2.75, 3.35), None, "常態提供 80–100 萬 0 利率或大額現金折價二選一。"),
    "Volkswagen Commercial": ("台灣福斯商旅財務", True, [(1_800_000, 1_200_000, 40, "福斯商旅 120 萬 40 期 0 利率"), (0, 800_000, 36, "福斯商旅 80 萬 36 期 0 利率")], 0.035, (2.48, 2.78, 3.38), None, "商旅車系提供高額 0 利率或公司戶節稅租賃。"),
    "Škoda": ("Škoda 聰明購專案", True, [(1_400_000, 1_000_000, 36, "Škoda 百萬 36 期 0 利率"), (0, 800_000, 36, "Škoda 80 萬 36 期 0 利率")], 0.034, (2.45, 2.75, 3.35), None, "全車系標配 All 4 You（4 年不限里程保固＋3 次免費基礎保養）搭 0 利率。"),
    "Honda": ("台灣本田汽車", True, [(1_200_000, 800_000, 36, "Honda 80 萬 36 期 0 利率"), (0, 600_000, 36, "Honda 60 萬 36 期 0 利率")], 0.032, (2.45, 2.75, 3.35), None, "常以高額 0 利率＋5 年延保促銷，純現金空車折讓亦透明。"),
    "Ford": ("福特六和汽車", True, [(1_300_000, 1_000_000, 40, "福特百萬 40 期 0 利率"), (0, 800_000, 40, "福特 80 萬 40 期 0 利率")], 0.035, (2.48, 2.78, 3.38), None, "80–100 萬 40 期 0 利率，現金折讓在國產品牌中具優勢。"),
    "Mazda": ("台灣馬自達汽車", True, [(1_300_000, 1_000_000, 36, "Mazda 百萬 36 期 0 利率"), (0, 800_000, 30, "Mazda 80 萬 30 期 0 利率")], 0.033, (2.45, 2.75, 3.35), None, "主力車系常推高額 0 利率與 5 年原廠延保。"),
    "Hyundai": ("南陽實業現代汽車", True, [(1_400_000, 1_000_000, 40, "現代百萬 40 期 0 利率"), (0, 800_000, 36, "現代 80 萬 36 期 0 利率")], 0.034, (2.48, 2.78, 3.38), None, "國產主力及 IONIQ 純電均常態搭配 60–100 萬 0 利率。"),
    "Kia": ("台灣森那美起亞", True, [(1_500_000, 1_000_000, 40, "Kia 百萬 40 期 0 利率"), (0, 600_000, 36, "Kia 60 萬 36 期 0 利率")], 0.033, (2.48, 2.78, 3.38), None, "全車系 5 年不限里程保固，搭配 60–100 萬 0 利率。"),
    "Nissan": ("裕隆日產／裕融企業", True, [(1_200_000, 800_000, 40, "Nissan 80 萬 40 期 0 利率"), (0, 600_000, 40, "Nissan 60 萬 40 期 0 利率")], 0.034, (2.48, 2.78, 3.38), None, "裕融配合度高，提供 60–80 萬 40 期 0 利率。"),
    "Mitsubishi": ("中華三菱／匯豐", True, [(900_000, 600_000, 40, "中華三菱 60 萬 40 期 0 利率"), (0, 500_000, 36, "中華三菱 50 萬 36 期 0 利率")], 0.032, (2.55, 2.85, 3.45), None, "低頭款與 50–60 萬 0 利率方案，適用舊換新 5 萬。"),
    "CMC": ("中華汽車 CMC", True, [(800_000, 500_000, 36, "中華商用 50 萬 36 期 0 利率"), (0, 400_000, 30, "頭家 40 萬 30 期 0 利率")], 0.030, (2.58, 2.88, 3.48), None, "商用頭家低頭款與 0 利率減壓專案。"),
    "Subaru": ("台灣意美汽車", True, [(1_300_000, 1_000_000, 40, "Subaru 百萬 40 期 0 利率"), (0, 800_000, 36, "Subaru 80 萬 36 期 0 利率")], 0.036, (2.48, 2.78, 3.38), None, "提供 80–100 萬 0 利率與 5 年原廠保固。"),
    "Suzuki": ("台灣金鈴汽車", True, [(800_000, 600_000, 36, "Suzuki 60 萬 36 期 0 利率"), (0, 500_000, 36, "Suzuki 50 萬 36 期 0 利率")], 0.030, (2.48, 2.78, 3.38), None, "Swift／Vitara／S-Cross 適用 0 利率；Jimny 以現金或銀行低利為主。"),
    "MINI": ("汎德 MINI Financial", True, [(0, 1_000_000, 48, "MINI 百萬 48 期 0 利率")], 0.038, (2.35, 2.65, 3.25), ("MINI 智選專案（36 期）", 20, 36, 50, 2.68), "全新世代 MINI 提供百萬 48 期 0 利率或智選低月付。"),
    "Land Rover": ("JLR Financial", True, [(3_500_000, 2_000_000, 48, "JLR 200 萬 48 期 0 利率"), (0, 1_500_000, 48, "JLR 150 萬 48 期 0 利率")], 0.040, (2.38, 2.68, 3.28), None, "提供 150–200 萬 48 期 0 利率與 5 年保養禮遇。"),
    "Tesla": ("台灣特斯拉合作銀行", False, [], 0.0, (2.18, 2.48, 2.88), None, "Tesla 官網直營不二價，無原廠 0 利率補貼息落差；合作銀行利率最低 2.18% 起、最長 84 期。"),
    "MG": ("台灣 MG（透明不二價）", False, [], 0.0, (2.48, 2.78, 3.28), None, "MG 採透明不二價政策，以高 CP 值定價搭配銀行低利分期。"),
    "Porsche": ("台灣保時捷財務 PFS", False, [], 0.0, (2.35, 2.68, 3.18), ("PFS 保時捷彈性尾款／租賃（36 期）", 25, 36, 52, 2.68), "台灣保時捷高度客製選配，超過半數車主選用 PFS 36 期企業節稅租賃或銀行專貸。"),
}

# Brand -> (reliability_score, parts_mult, ins_mult, warranty_yrs, base_3y_resale, base_5y_resale)
BRAND_ACTUARIAL: dict[str, tuple[float, float, float, int, float, float]] = {
    "Lexus": (95, 1.45, 1.08, 4, 63.5, 51.0), "Toyota": (94, 0.95, 0.92, 4, 64.5, 52.5),
    "Honda": (91, 1.00, 0.95, 3, 61.5, 49.5), "Suzuki": (91, 0.90, 0.90, 3, 61.5, 49.5),
    "Mazda": (90, 1.05, 0.96, 3, 59.0, 46.5), "Subaru": (88, 1.20, 1.02, 3, 60.0, 47.5),
    "Porsche": (88, 3.10, 1.32, 4, 62.5, 50.5), "Mitsubishi": (86, 0.98, 0.94, 3, 55.5, 43.0),
    "Kia": (85, 1.15, 1.00, 5, 57.5, 45.0), "Hyundai": (85, 1.15, 1.00, 5, 57.5, 45.0),
    "MINI": (85, 1.85, 1.16, 3, 57.5, 44.5), "CMC": (85, 0.85, 0.88, 3, 57.5, 45.5),
    "BMW": (84, 2.35, 1.24, 3, 56.0, 42.5), "Infiniti": (84, 1.60, 1.12, 4, 49.0, 35.5),
    "Nissan": (82, 1.05, 0.96, 3, 54.5, 41.5), "Chevrolet": (82, 1.25, 1.04, 3, 57.5, 45.0),
    "Škoda": (81, 1.55, 1.10, 4, 56.0, 43.0), "Volkswagen Commercial": (81, 1.65, 1.10, 4, 59.5, 47.0),
    "Audi": (80, 2.30, 1.24, 5, 53.0, 39.5), "Volvo": (80, 2.25, 1.22, 3, 53.5, 40.0),
    "Tesla": (80, 1.65, 1.32, 4, 58.5, 45.5), "Ford": (80, 1.25, 1.04, 3, 55.0, 42.0),
    "MG": (80, 1.12, 1.02, 4, 55.0, 42.0), "RAM": (80, 1.45, 1.10, 3, 58.0, 45.5),
    "Mercedes-Benz": (79, 2.55, 1.28, 3, 57.0, 43.5), "Volkswagen": (79, 1.65, 1.12, 4, 56.0, 43.0),
    "Rolls-Royce": (79, 5.80, 1.45, 4, 59.0, 47.0), "Dodge": (78, 1.55, 1.18, 3, 52.0, 39.0),
    "INEOS": (78, 2.10, 1.18, 5, 61.5, 49.5), "Ferrari": (77, 5.50, 1.55, 3, 74.0, 65.0),
    "Foxtron": (77, 1.18, 1.12, 4, 51.5, 38.0), "Peugeot": (76, 1.75, 1.12, 3, 51.5, 38.5),
    "Opel": (76, 1.70, 1.12, 3, 50.0, 37.0), "DFSK": (76, 0.90, 0.92, 3, 52.5, 40.0),
    "Lamborghini": (76, 5.60, 1.55, 3, 70.0, 60.5), "Citroën": (75, 1.75, 1.12, 3, 51.0, 38.0),
    "Luxgen": (75, 1.12, 1.06, 4, 48.5, 35.5), "Bentley": (75, 4.90, 1.45, 3, 52.0, 39.0),
    "Jeep": (72, 1.75, 1.16, 3, 58.5, 46.0), "Aston Martin": (72, 4.60, 1.48, 3, 52.5, 39.5),
    "Lotus": (71, 3.60, 1.42, 3, 54.0, 41.0), "Alfa Romeo": (70, 2.45, 1.28, 3, 49.0, 35.5),
    "McLaren": (68, 5.20, 1.55, 3, 53.0, 40.0), "Land Rover": (67, 3.15, 1.34, 3, 54.0, 40.5),
    "Maserati": (66, 3.85, 1.42, 3, 46.0, 32.5),
}

ULTRA_800V_RULES: list[tuple[str, str, int, int, bool]] = [
    ("porsche", r"taycan|macan", 320, 18, False), ("audi", r"e-tron gt|q6|a6.*e-tron", 270, 21, False),
    ("hyundai", r"ioniq", 240, 18, True), ("kia", r"\bev[69]\b|\bev[35]\b", 235, 18, True),
    ("lotus", r"eletre|emeya", 350, 20, True), ("maserati", r"folgore", 270, 22, False),
    ("mercedes-benz", r"cla|glc.*electric", 320, 20, False), ("volvo", r"ex90|es90", 250, 24, True),
    ("tesla", r"cybertruck", 350, 24, True),
]

CURATED_FACELIFT_DB: list[tuple[str, str, dict[str, Any]]] = [
    ("mercedes-benz", "c-class", {
        "stage": "MID_CYCLE", "stage_label": "小改款交接期",
        "gen": "W206 / S206 世代（2026/08 德國已發表大改幅小改款；台灣正值 26 年式星耀版交接期）",
        "est_fl": "2026/08 德國已發表小改款（三芒星燈組＋MB.OS＋實體方向盤按鍵；台灣預計 2027 導入）",
        "est_rd": "預估 2029～2030 年下一世代大改款",
        "title": "W206 C-Class（含 C 300）改款前星耀版 vs. 2026/08 正式小改款深度對照",
        "before_label": "改款前｜2021–2026 星耀版（台灣現車）",
        "after_label": "小改款｜2026/08 發表 W206 Facelift（預計 2027 抵台）",
        "verdict": "要大馬力與滿配操控（258hp C 300＋2.5°後軸轉向＋可變阻尼＋現金折價），現在抄底 26 年式星耀版超值；若極度在意「實體方向盤按鍵、MB.OS AI 車機與三芒星發光車頭」，可等小改款！",
        "rows": [
            {"c": "台灣車型編成（C 300 動向）", "b": "房車 C 180（225萬）、C 200（261萬）、C 300（305萬）；旅行車 C 200／C 300 Estate。", "a": "傳出 C 180 停售、台灣改由 C 200／C 250 房車與單一 C 250 Estate 接棒；美歐規仍保留 258hp C 300。", "t": "tradeoff"},
            {"c": "引擎動力與 48V 輕油電", "b": "C 300 搭 M254 2.0T 258hp（+23hp 48V）／6.0 秒破百；C 200 1.5T 204hp。", "a": "升級 M254 Evo＋二代 ISG 2.0；台灣傳出 C 200（177+23hp）與 C 250（218+23hp）馬力較舊款 C 300 下修。", "t": "tradeoff"},
            {"c": "車頭水箱罩與頭尾燈", "b": "星芒點陣水箱護罩、單眉 LED 日行燈、三角幾何尾燈。", "a": "加大六邊形「發光水箱護罩」＋頭尾燈全面植入「三芒星光條識別燈語」與迎賓投影。", "t": "major"},
            {"c": "方向盤按鍵手感", "b": "全電容觸控滑動按鍵，行駛中易誤觸（改款前最大負評）。", "a": "聽取車主回饋！正式取消電容滑控、改回「實體撥片按鍵＋滾輪」，盲操作大躍進。", "t": "major"},
            {"c": "車機系統與 AI 導航", "b": "二代 MBUX（12.3+11.9 吋螢幕）、原廠圖資＋AR 導航。", "a": "全面升級賓士自研「MB.OS 第四代 MBUX」，整合 Gemini／ChatGPT AI 語音與 Google Maps 導航。", "t": "major"},
            {"c": "操控與底盤配備", "b": "台灣 26 年式 C 300 星耀版標配 2.5°後軸轉向＋可變阻尼懸吊＋全景天窗＋DIGITAL LIGHT。", "a": "標配雙前座通風椅與 AMG Line，但傳出部分入門車型將數位頭燈／隔音玻璃改列選配。", "t": "tradeoff"},
            {"c": "音響與座艙質感", "b": "星耀版標配 Burmester 3D 環場音響與 64 色氣氛燈。", "a": "Burmester 3D 音響升級支援 Dolby Atmos 杜比全景聲，新增櫻桃紅／山毛櫸棕內裝色。", "t": "upgrade"},
            {"c": "成交價與購車時機", "b": "26 年式處交接清倉期，空車折讓約 8–16 萬，入手總代理 258hp C 300 最後機會。", "a": "2026/08 德國先交車、台灣預計 2027 導入，初期幾乎無折讓且定價看漲。", "t": "upgrade"},
        ],
    }),
    ("toyota", "rav4", {
        "stage": "NEW_GEN", "stage_label": "全新世代剛上市",
        "gen": "第 6 代全新大改款（2026 導入台灣）", "est_fl": "預估 2029 年中期小改款", "est_rd": "預估 2032 年第 7 代",
        "title": "Toyota RAV4 第 5 代（XA50） vs. 第 6 代全新大改款對照",
        "before_label": "改款前｜第 5 代（2019–2025）", "after_label": "大改款｜第 6 代現行款",
        "verdict": "第 6 代從油電系統、Arene OS 到 TSS 4.0 全面跨世代領先，定價極具誠意，直接買第 6 代！",
        "rows": [
            {"c": "動力編成", "b": "2.0L 自然進氣為主力＋第 4 代 2.5L 油電。", "a": "全面電氣化升級第 5 代 THS 油電與長續航 PHEV，油耗與加速全面領先。", "t": "gen"},
            {"c": "外觀設計", "b": "傳統梯形大嘴水箱罩。", "a": "新世代 Hammerhead 雙髻鯊車頭與貫穿式燈語。", "t": "major"},
            {"c": "座艙軟體", "b": "舊世代車美仕主機。", "a": "雙 12.3 吋數位座艙＋豐田自研 Arene OS 支援 OTA。", "t": "gen"},
            {"c": "主動安全", "b": "TSS 2.0 / 2.5 輔助系統。", "a": "升級最新 TSS 4.0，強化路口行人與機車主動煞停防護。", "t": "major"},
        ],
    }),
    ("toyota", "corolla cross", {
        "stage": "FACELIFT_FRESH", "stage_label": "小改款成熟期",
        "gen": "XG10 小改款（2024 升級 EPB＋鋰電池）", "est_fl": "已完成中期小改款", "est_rd": "預估 2027–2028 年第 2 代",
        "title": "Corolla Cross 改款前 vs. 小改款（現行款）對照",
        "before_label": "改款前｜2020–2024", "after_label": "小改款｜現行款",
        "verdict": "小改款一次補齊「EPB 電子手煞車＋Auto Hold＋鋰電池 23.5 km/L」，完勝改款前！",
        "rows": [
            {"c": "手煞車與 Auto Hold", "b": "傳統足踏式駐車煞車、無 Auto Hold。", "a": "全系標配 EPB 電子手煞車＋Auto Hold，塞車解放雙腳！", "t": "major"},
            {"c": "油電電池與油耗", "b": "鎳氫電池，平均油耗約 21.9 km/L。", "a": "升級輕量高效率鋰電池組，平均油耗躍升至 23.5 km/L。", "t": "major"},
            {"c": "外觀與數位儀表", "b": "黑梯形水箱罩＋7 吋儀表。", "a": "無邊界漸層水箱罩＋尊爵以上 12.3 吋全數位儀表。", "t": "upgrade"},
        ],
    }),
    ("tesla", "model y", {
        "stage": "NEW_GEN", "stage_label": "全新煥新版",
        "gen": "煥新版 Project Juniper（2025–2026 全面交車）", "est_fl": "持續 OTA 進化", "est_rd": "預估 2030 年後",
        "title": "Tesla Model Y 舊款 vs. 全新煥新版 Juniper 對照",
        "before_label": "改款前｜2020–2024 舊款", "after_label": "煥新版｜Juniper 現行款",
        "verdict": "煥新版徹底解決「彈跳避震、隔音差、無通風椅」三大痛點並貼心保留實體方向燈撥桿！",
        "rows": [
            {"c": "懸吊與隔音", "b": "避震偏硬彈跳、高速胎噪明顯。", "a": "新阻尼懸吊＋全車雙層隔音玻璃，行路噪訊降逾 20%！", "t": "major"},
            {"c": "舒適科技", "b": "無通風椅、無後座螢幕、無氣氛燈。", "a": "標配雙前座通風椅、後座 8 吋螢幕、電動傾倒與環艙氣氛燈。", "t": "major"},
            {"c": "操作撥桿", "b": "傳統雙側撥桿。", "a": "螢幕滑動換檔，但保留「實體方向燈撥桿」超好上手。", "t": "upgrade"},
        ],
    }),
    ("bmw", "3 series", {
        "stage": "LATE_CYCLE", "stage_label": "世代末期・折價最甜",
        "gen": "G20 / G21 LCI 2 二度小改款", "est_fl": "已完成 LCI 2（OS 8.5＋平底方向盤）", "est_rd": "預估 2026–2027 年 Neue Klasse G50 大改款",
        "title": "BMW 3 Series 改款前 vs. 現行 LCI 2（＆G50 大改款展望）",
        "before_label": "改款前｜G20 前期型", "after_label": "現行 LCI 2（下一步 G50 大改款）",
        "verdict": "G20 LCI 2 成熟度滿分且末期折讓最甜；若期待 Panoramic Vision 全景投影可等 G50 大改款。",
        "rows": [
            {"c": "座艙螢幕", "b": "12.3+10.25 吋分離螢幕＋實體冷氣鍵。", "a": "12.3+14.9 吋懸浮曲面雙螢幕＋OS 8.5 QuickSelect。", "t": "tradeoff"},
            {"c": "方向盤與底盤", "b": "圓形方向盤與雞腿排檔。", "a": "平底運動方向盤、撥片排檔與優化後避震器上座。", "t": "major"},
            {"c": "大改款展望", "b": "現行成熟 CLAR 平台。", "a": "下代 G50 導入 Neue Klasse 設計語彙與 800V 純電 i3。", "t": "gen"},
        ],
    }),
    ("mercedes-benz", "glc", {
        "stage": "MID_CYCLE", "stage_label": "世代中期熱銷",
        "gen": "X254 / C254 世代（2022 問世）", "est_fl": "預估 2026–2027 小改款（三芒星燈組＋MB.OS）", "est_rd": "預估 2030 年大改款",
        "title": "X254 GLC 現行 48V 燃油 vs. 2027 小改款＆純電 GLC 比較",
        "before_label": "現行款｜X254 燃油 48V", "after_label": "預告｜小改款 ＆ GLC Electric",
        "verdict": "現行 X254 折讓與配備已相當甜；想體驗 MB.OS＋三芒星車頭或 800V 純電可關注新改款。",
        "rows": [
            {"c": "外觀與燈語", "b": "星芒水箱護罩＋單眉 LED 頭燈。", "a": "比照 W206 小改款換裝發光水箱罩與三芒星頭尾燈。", "t": "major"},
            {"c": "車機與方向盤", "b": "二代 MBUX＋電容觸控方向盤。", "a": "升級 MB.OS AI 車機並回歸實體方向盤滾輪按鍵。", "t": "major"},
        ],
    }),
    ("mazda", "cx-5", {
        "stage": "LATE_CYCLE", "stage_label": "世代末期・折價最甜",
        "gen": "第 2 代 KF 成熟末期（第 3 代油電大改款交接期）", "est_fl": "現行配備滿載且現金折讓最甜", "est_rd": "2026–2027 年第 3 代全新自研 Hybrid 大改款",
        "title": "Mazda CX-5 現行 KF 末期滿配 vs. 預計第 3 代油電大改款",
        "before_label": "現行款｜第 2 代 KF 成熟版", "after_label": "下一代｜第 3 代油電大改款",
        "verdict": "重視 100 萬級純日製零通病＋高折讓就買現行滿配；重視省油油電與更大後座值得等第 3 代。",
        "rows": [
            {"c": "動力系統", "b": "2.0L / 2.5T Skyactiv-G＋6AT（高妥善）。", "a": "首度導入馬自達自研 Hybrid 油電系統，油耗大躍進。", "t": "gen"},
            {"c": "空間與折價", "b": "後座略緊湊但現金折讓與通風椅滿配極超值。", "a": "尺碼與後座膝部空間放大，但初期售價看漲無折讓。", "t": "tradeoff"},
        ],
    }),
    ("volkswagen", "golf", {
        "stage": "FACELIFT_FRESH", "stage_label": "小改款成熟期",
        "gen": "Mk8.5 小改款（修正電容按鍵與 MIB4 螢幕）", "est_fl": "已完成 8.5 代小改款", "est_rd": "預估 2029 年 Mk9 純電世代",
        "title": "VW Golf 8 vs. Golf 8.5 小改款（痛點全面修正）",
        "before_label": "改款前｜Golf 8", "after_label": "現行｜Golf 8.5 小改款",
        "verdict": "Golf 8.5 一次修掉方向盤誤觸、滑條無背光與車機卡頓三大痛點，必選 8.5 代！",
        "rows": [
            {"c": "方向盤與背光滑條", "b": "電容方向盤易誤觸＋夜間空調滑條無背光。", "a": "回歸實體多功能按鍵＋12.9 吋 MIB4 螢幕與背光滑條！", "t": "major"},
            {"c": "外觀與性能", "b": "GTI 245ps / R 320ps。", "a": "發光 VW 廠徽＋GTI 漲至 265ps、R 漲至 333ps。", "t": "major"},
        ],
    }),
]

# =========================================================================
# 4. LIVE U-CAR HARVESTER & PARSER
# =========================================================================

class UCarTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._in_tr = self._in_cell = False
        self._cur_row: list[dict[str, Any]] = []
        self._cur_row_cls = ""
        self._txt: list[str] = []
        self._alts: list[str] = []
        self._colspan = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        am = dict(attrs)
        if tag == "tr":
            self._in_tr, self._cur_row, self._cur_row_cls = True, [], am.get("class") or ""
        elif tag in ("td", "th") and self._in_tr:
            self._in_cell, self._txt, self._alts = True, [], []
            try:
                self._colspan = max(1, int(am.get("colspan") or 1))
            except ValueError:
                self._colspan = 1
        elif tag == "img" and self._in_cell:
            alt = (am.get("alt") or "").strip()
            if alt:
                self._alts.append(alt)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._in_cell:
            text = re.sub(r"\s+", " ", " ".join(self._txt)).strip()
            cell = {"text": text, "alts": list(self._alts), "row_class": self._cur_row_cls}
            for _ in range(self._colspan):
                self._cur_row.append(cell)
            self._in_cell = False
        elif tag == "tr" and self._in_tr:
            if self._cur_row:
                self.rows.append(self._cur_row)
            self._in_tr = False

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._txt.append(data)


def _fetch_text(url: str, timeout: int = 16, retries: int = 2) -> str:
    last: Exception | None = None
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", errors="ignore")
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(0.35 * (i + 1))
    raise RuntimeError(f"Fetch failed {url}: {last}")


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "car"


def _pint(s: str) -> int | None:
    m = re.search(r"([\d,]+)", s or "")
    return int(m.group(1).replace(",", "")) if m else None


def _pfloat(s: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", s or "")
    return float(m.group(1)) if m else None


def _parse_wan_twd(cell_text: str) -> tuple[str, int | None]:
    clean = re.sub(r"\s+", " ", cell_text).strip()
    if any(w in clean for w in ("美元", "歐元", "英鎊")):
        return clean, None
    m = re.search(r"(?:預售價\s*)?([\d,]+(?:\.\d+)?)(?:\s*[~～-]\s*[\d,]+(?:\.\d+)?)?\s*萬(?:元)?(?:\s*起)?\s*$", clean)
    if not m:
        return clean, None
    wan = float(m.group(1).replace(",", ""))
    if wan <= 0:
        return clean, None
    return (clean[: m.start()].strip() or clean), int(round(wan * 10000))


def _is_delisted(brand: str, model: str) -> bool:
    bl, ml = brand.lower().strip(), model.lower().strip()
    for rb, rm, exact in DELISTED_TW_RULES:
        if bl == rb:
            if not rm:
                return True
            if exact and ml == rm:
                return True
            if not exact and rm in ml:
                return True
    return False


def _map_body(raw: str, model: str) -> str:
    b = f"{raw} {model}".lower()
    if any(k in b for k in ("皮卡", "貨卡", "pickup", "貨車", "發財", "hilux", "ranger", "amarok", "town ace", "a180", "a190", "j space")):
        if any(k in b for k in ("廂", "mpv", "商旅", "multivan", "caravelle", "v-class", "alphard", "sienna", "carnival", "staria", "custin", "berlingo", "caddy", "zinger", "id. buzz")):
            return "mpv"
        return "pickup"
    if any(k in b for k in ("mpv", "商旅", "廂型", "露營", "multivan", "caravelle", "california", "v-class", "alphard", "sienna", "carnival", "staria", "custin", "berlingo", "touran", "caddy", "lm", "granvia", "id. buzz")):
        return "mpv"
    if any(k in b for k in ("旅行車", "wagon", "estate", "touring", "avant", "shooting brake", "variant", "combi", "cross turismo")):
        return "wagon"
    if any(k in b for k in ("雙門", "跑車", "敞篷", "coupe", "coupé", "cabriolet", "roadster", "spider", "spyder", "911", "mx-5", "gr86", "mustang", "cle", "sl", "z4", "emira", "vantage", "db12", "revuelto", "temerario", "artura", "750s")):
        if any(k in b for k in ("suv", "休旅", "urus", "purosangue", "dbx", "cayenne", "macan", "glc", "gle", "x4", "x6", "q3 sportback", "q5 sportback", "q8", "grecale")):
            return "suv"
        return "coupe"
    if any(k in b for k in ("休旅", "suv", "跨界", "越野", "crossover", "g-class", "defender", "wrangler", "jimny", "grenadier", "gla", "glb", "glc", "gle", "gls", "eqa", "eqb", "eqe suv", "eqs suv", "x1", "x2", "x3", "x5", "x6", "x7", "xm", "ix", "q2", "q3", "q4", "q5", "q6", "q7", "q8", "ux", "nx", "rx", "rz", "lbx", "rav4", "corolla cross", "yaris cross", "bz4x", "crown", "cr-v", "hr-v", "forester", "crosstrek", "cx-", "xc40", "xc60", "xc90", "ex30", "ex40", "macan", "cayenne", "tiguan", "t-roc", "t-cross", "id.4", "id.5", "kodiaq", "karoq", "kamiq", "enyaq", "model y", "n7", "n⁷", "hs", "zs", "tucson", "santa fe", "kona", "venue", "sportage", "sorento", "ev6", "ev9", "niro", "2008", "3008", "408", "5008", "countryman", "range rover", "discovery", "grecale", "bentayga", "cullinan", "dbx", "urus", "purosangue")):
        return "suv"
    if any(k in b for k in ("掀背", "hatch", "a-class", "1 series", "a1", "a3 sportback", "golf", "polo", "fabia", "scala", "swift", "fit", "cooper", "208", "astra", "bria", "ioniq 5")):
        return "sedan" if ("sedan" in b or "四門" in b) else "hatchback"
    if any(k in b for k in ("房車", "轎車", "sedan", "四門", "saloon", "limousine")):
        return "sedan"
    return "suv"


def _map_pt(ps: str, energy: str, tech: str, name: str, batt: str) -> str:
    b = f"{ps} {energy} {tech} {name}".lower()
    if any(k in b for k in ("純電", "電動", "electric", "bev", "eqa", "eqb", "eqe", "eqs", "taycan", "e-tron", "ioniq", "ev6", "ev9", "ex30", "ex40", "bz4x", "model 3", "model y", "n7", "bria", "enyaq", "id.4", "id.5", "id. buzz", "ix", "i4", "i5", "i7", "ix1", "ix2", "spectre", "eletre", "macan electric")):
        if "phev" not in b and "插電" not in b and "油電" not in b and "汽油" not in energy:
            return "BEV"
    if any(k in b for k in ("插電", "phev", "plug-in", "e performance", "e-hybrid", "t8", "sf90", "revuelto", "artura", "temerario")):
        return "PHEV"
    if any(k in b for k in ("48v", "輕油電", "mhev", "mild")):
        return "MHEV"
    if any(k in b for k in ("油電", "hybrid", "e:hev", "e-power", "hev")):
        return "HEV"
    if batt and not re.search(r"0\.\d+|1\.\d+", batt) and "汽油" not in energy and "柴油" not in energy:
        return "BEV"
    return "ICE"


def _build_tx_price(brand: str, model: str, trim_name: str, msrp: int, is_pi: bool = False) -> dict[str, Any]:
    blob = f"{brand} {model} {trim_name}".lower()
    if is_pi:
        step = 10000
        low = int(round(msrp * 0.965 / step) * step)
        high = int(round(msrp * 1.03 / step) * step)
        return {"low": low, "typical": msrp, "high": high, "pricing_mode": "PARALLEL_IMPORT", "typical_delta_pct": 0.0, "note": "含美國/海外新車車價＋海運保險＋進口關稅/貨物稅/營業稅＋ARTC 驗車領牌預估完稅總價（實際依匯率與選配報價）。"}
    if brand in DIRECT_FIXED_BRANDS:
        return {"low": msrp, "typical": msrp, "high": msrp, "pricing_mode": "DIRECT_FIXED", "typical_delta_pct": 0.0, "note": f"{brand} 台灣採透明不二價定價，成交價與官方建議售價一致。"}
    is_hot = (
        brand in EXOTIC_BRANDS
        or (brand == "Porsche" and any(k in blob for k in ("911", "gt3", "gt4", "turbo s")))
        or (brand == "Mercedes-Benz" and any(k in blob for k in ("g 63", "g63", "maybach", "amg gt")))
        or (brand == "Toyota" and any(k in blob for k in ("alphard", "gr yaris", "land cruiser")))
        or (brand == "Lexus" and "lm " in blob)
        or msrp >= 9_000_000
    )
    if is_hot:
        return {"low": msrp, "typical": msrp, "high": int(round(msrp * 1.04 / 10000) * 10000), "pricing_mode": "HIGH_DEMAND_MARKUP", "typical_delta_pct": 0.0, "note": "熱門限量／配額接單車型，空車幾乎無折讓且常含選配。"}
    if brand in LUXURY_BRANDS:
        lp, tp, hp_ = 0.935, 0.960, 0.980
    elif brand in ("Toyota", "Honda", "Lexus", "Subaru", "Mazda", "Suzuki"):
        lp, tp, hp_ = 0.945, 0.968, 0.985
    else:
        lp, tp, hp_ = 0.935, 0.962, 0.982
    step = 5000 if msrp >= 500000 else 1000
    low = max(step, int(round(msrp * lp / step) * step))
    typ = max(low, min(msrp, int(round(msrp * tp / step) * step)))
    hi = max(typ, min(msrp, int(round(msrp * hp_ / step) * step)))
    return {"low": low, "typical": typ, "high": hi, "pricing_mode": "DEALER_DISCOUNT", "typical_delta_pct": round((typ - msrp) / msrp * 100, 1), "note": "台灣經銷商一般現金空車議價參考區間（不含舊換新 5 萬與加購選配）。"}


def _build_imagin(brand: str, model: str) -> dict[str, Any] | None:
    if brand in IMAGIN_BLOCK_BRANDS or any(tok in model.lower() for tok in IMAGIN_BLOCK_TOKENS):
        return None
    mk = brand.lower().replace("škoda", "skoda").replace("citroën", "citroen").replace("volkswagen commercial", "volkswagen")
    fam = re.sub(r"^(mercedes-amg|mercedes-maybach)\s+", "", model.lower())
    fam = re.sub(r"\s+(sedan|estate|coupe|coupé|cabriolet|suv|with eq technology|electric|shooting brake|sportback|avant|touring|gran coupe|gran coupé|passenger van)$", "", fam)
    fam = re.sub(r"[^a-z0-9-]+", "-", fam).strip("-") or "car"
    return {"make": mk, "modelFamily": fam, "year": 2025}


def _calc_monthly(principal: float, apr: float, months: int) -> tuple[int, int]:
    if principal <= 0 or months <= 0:
        return 0, 0
    if apr <= 0:
        return int(round(principal / months)), 0
    r = (apr / 100.0) / 12.0
    f = math.pow(1.0 + r, months)
    m = int(round(principal * r * f / (f - 1.0)))
    return m, max(0, m * months - int(round(principal)))


def _calc_balloon(principal: float, residual: float, apr: float, months: int) -> tuple[int, int]:
    if principal <= 0 or months <= 0:
        return 0, 0
    r = (apr / 100.0) / 12.0
    pv = residual / math.pow(1.0 + r, months)
    eff = max(0.0, principal - pv)
    f = math.pow(1.0 + r, months)
    m = int(round(eff * r * f / (f - 1.0)))
    return m, max(0, m * months + int(round(residual)) - int(round(principal)))


def _enrich_vehicle(v: dict[str, Any]) -> dict[str, Any]:
    """Attaches all 6 buyer engines: financing, ownership, resale, charging, lifecycle, scores."""
    market = v["market_code"]
    is_pi = market == "PI"
    brand, model = v["brand"], v["model"]
    ml = model.lower()
    trims = v["trims"]
    trims.sort(key=lambda t: t["msrp"])
    v["min_msrp"] = trims[0]["msrp"]
    v["max_msrp"] = trims[-1]["msrp"]
    v["min_tx"] = min(t["tx"]["typical"] for t in trims)
    v["max_tx"] = max(t["tx"]["typical"] for t in trims)
    v["powertrains"] = sorted({t["specs"]["pt"] for t in trims})
    best_idx = 1 if len(trims) >= 3 else (len(trims) - 1 if len(trims) == 2 and trims[1]["msrp"] <= trims[0]["msrp"] * 1.25 else 0)
    rep = trims[best_idx]
    v["best_trim_id"] = rep["id"]
    sp = rep["specs"]
    pt = sp["pt"]
    msrp = rep["msrp"]
    tx_typ = rep["tx"]["typical"]

    # 1. FINANCING & 0% APR ENGINE
    if is_pi:
        dist, allow_z, tiers, sub_r, aprs, bal_cfg, note = ("台灣外匯貿易商合作銀行（國泰／中信／富邦／和潤）", False, [], 0.0, (2.88, 3.28, 3.88), None, "本車屬全新貿易商限定導入，無總代理原廠 0 利率補貼；外匯新車專貸利率約 2.88%–3.68%（最高 75 成 / 72 期），亦可比較低利信貸全額買斷。")
    elif brand in EXOTIC_BRANDS:
        dist, allow_z, tiers, sub_r, aprs, bal_cfg, note = (f"{brand} 企業租賃／私人銀行專案", False, [], 0.0, (2.48, 2.88, 3.48), ("36 期企業節稅租賃專案（參考）", 30, 36, 50, 2.75), "超跑／層峰品牌不推 0 利率促銷，多採 36 期企業節稅租賃。")
    else:
        dist, allow_z, tiers, sub_r, aprs, bal_cfg, note = TW_FINANCING_PROFILES.get(
            brand, (f"{brand} 台灣總代理合作銀行", True, [(0, 800_000, 36, f"{brand} 80 萬 36 期 0 利率")], 0.034, (2.48, 2.78, 3.38), None, "展間可同時索取「原廠 0 利率」與「現金空車折讓」雙報價比對。")
        )
        if any(tok in ml for tok in NO_ZERO_APR_TOKENS) or (brand == "Maserati" and any(k in ml for k in ("mc20", "granturismo", "grancabrio"))):
            allow_z = False

    apr_min, apr_typ, apr_max = aprs
    setup_fee = 5000 if is_pi else 3500
    max_ltv = 75 if (is_pi or brand in EXOTIC_BRANDS) else 80
    max_mo = 72 if is_pi else 84
    fin_by_trim: dict[str, Any] = {}
    for t in trims:
        tm, ttx = t["msrp"], t["tx"]["typical"]
        c_disc = max(0, tm - ttx)
        zo = vsc = bo = None
        if allow_z and tiers and tm >= 350_000:
            cap, mo, zt = tiers[-1][1], tiers[-1][2], tiers[-1][3]
            for min_p, c, m_, ttl in tiers:
                if tm >= min_p:
                    cap, mo, zt = c, m_, ttl
                    break
            safe_cap = min(cap, max(100_000, int((tm * 0.80) // 100_000) * 100_000))
            down = max(0, tm - safe_cap)
            mz, _ = _calc_monthly(safe_cap, 0.0, mo)
            wan = safe_cap // 10_000
            raw_sub = int(round((safe_cap * (sub_r * 0.88) * (mo / 24.0)) / 1000.0) * 1000)
            est_sub = 0 if t["tx"]["pricing_mode"] == "DIRECT_FIXED" else (min(raw_sub, max(12_000, int(round(c_disc * 0.78 / 1000.0) * 1000))) if c_disc > 0 else min(raw_sub, int(round(safe_cap * 0.025 / 1000.0) * 1000)))
            zo = {"title": zt, "headline": f"{wan} 萬 {mo} 期 0 利率", "badge": f"0利率 {wan}萬{mo}期", "loan": safe_cap, "wan": wan, "months": mo, "down": down, "monthly": mz, "subsidy": est_sub}
            bm, bi = _calc_monthly(safe_cap, apr_typ, mo)
            btot = bi + setup_fee
            diff = btot - est_sub
            if est_sub == 0 or diff >= 4000:
                win, vs_txt = "zero_apr", f"選「原廠 {wan} 萬 {mo} 期 0 利率」更省！銀行 {apr_typ:.2f}% 利息＋設定費約 NT${btot:,}，高於預估少折現金約 NT${est_sub:,}，實省約 NT${abs(diff):,}。"
            elif diff <= -4000:
                win, vs_txt = "cash_plus_bank", f"內行建議「拿滿現金折價＋銀行 {apr_typ:.2f}% 低利」！選 0 利率預估少折約 NT${est_sub:,}，但同額度銀行總利息＋設定費僅約 NT${btot:,}，自貸反而省約 NT${abs(diff):,}。"
            else:
                win, vs_txt = "tie", f"兩方案總成本幾乎打平（差額僅約 NT${abs(diff):,}），請向業務同時索取「現金空車價」與「0 利率專案價」書面單比對。"
            vsc = {"winner": win, "apr": apr_typ, "bank_m": bm, "bank_cost": btot, "forfeit": est_sub, "save": abs(diff), "summary": vs_txt}
        if bal_cfg and not is_pi and tm >= 1_200_000:
            bn, dp, bmo, rp_, bapr = bal_cfg
            bd, bp, bres = int(round(tm * dp / 100)), int(round(tm * (100 - dp) / 100)), int(round(tm * rp_ / 100))
            bmonthly, bint = _calc_balloon(bp, bres, bapr, bmo)
            bo = {"name": bn, "down_pct": dp, "down": bd, "loan": bp, "months": bmo, "res_pct": rp_, "residual": bres, "apr": bapr, "monthly": bmonthly, "interest": bint}
        bp60 = int(round(ttx * max_ltv / 100))
        m60, i60 = _calc_monthly(bp60, apr_typ, 60)
        fin_by_trim[t["id"]] = {
            "has_zero_apr": bool(zo), "zero": zo, "vs_cash": vsc, "balloon": bo,
            "bank": {"apr_min": apr_min, "apr_typ": apr_typ, "apr_max": apr_max, "ltv": max_ltv, "max_mo": max_mo, "fee": setup_fee, "p60": bp60, "m60": m60, "i60": i60},
        }
    rep_fin = fin_by_trim[rep["id"]]
    zrep = rep_fin["zero"]
    v["financing"] = {
        "distributor": dist, "has_zero_apr": bool(zrep),
        "zero_max": zrep["loan"] if zrep else 0, "zero_months": zrep["months"] if zrep else 0,
        "badge": zrep["badge"] if zrep else (f"外匯專貸 {apr_min:.2f}%起" if is_pi else f"低利 {apr_min:.2f}%起"),
        "note": note, "by_trim": fin_by_trim,
    }

    # 2. ACTUARIAL TAIWAN OWNERSHIP COST & RELIABILITY
    rel, p_mult, i_mult, w_yrs, r3, r5 = BRAND_ACTUARIAL.get(brand, (80.0, 1.35, 1.06, 3, 54.0, 41.0))
    if pt == "HEV":
        rel, r3, r5 = min(97, rel + 1.5), min(76, r3 + 2.5), min(66, r5 + 2.5)
    elif pt == "BEV":
        r3, r5 = max(36, r3 - 3.5), max(25, r5 - 4.0)
    elif pt == "PHEV":
        rel, r3, r5 = max(62, rel - 1.5), max(38, r3 - 1.5), max(27, r5 - 2.0)
    rel_grade = "S" if rel >= 90 else ("A+" if rel >= 85 else ("A" if rel >= 80 else ("B+" if rel >= 75 else "B")))

    cc = sp.get("cc") or 0
    is_diesel = "柴" in sp.get("eng", "") or "diesel" in sp.get("eng", "").lower()
    if pt == "BEV":
        tax, tax_note = 0, "純電車免牌照稅（至 2030/12/31）且免燃料費"
    else:
        tw_b = [(500, 1620, 2160, 1296), (600, 2160, 2160, 1296), (1200, 4320, 4320, 2592), (1800, 7120, 4800, 2880), (2400, 11230, 6180, 3708), (3000, 15210, 7200, 4320), (3600, 28220, 8640, 5184), (4200, 28220, 9810, 5886), (4800, 46170, 11220, 6732), (5400, 46170, 12180, 7308), (6000, 69690, 13080, 7848), (6600, 69690, 13950, 8370), (99999, 117000, 15720, 9432)]
        use_cc = cc if cc > 0 else (1998 if msrp >= 1_500_000 else 1498)
        lic, pf, df = next((l, p, d) for lim, l, p, d in tw_b if use_cc <= lim)
        f_fee = df if is_diesel else pf
        tax, tax_note = lic + f_fee, f"{use_cc:,} cc 法定級距（牌照稅 NT${lic:,}＋燃料費 NT${f_fee:,}）"

    # Energy cost per 15,000 km/yr (Taiwan petrol 31.5/L, home/DC blended electricity 4.8/kWh)
    eff = sp.get("eff", "")
    if pt == "BEV":
        m_kmk = re.search(r"(\d+(?:\.\d+)?)\s*km\s*/\s*kwh", eff, re.I)
        kwh100 = round(100 / float(m_kmk.group(1)), 1) if m_kmk else 17.5
        energy_15k = int(round((15000 / 100.0) * kwh100 * 4.8))
    else:
        m_kml = re.search(r"(\d+(?:\.\d+)?)\s*km\s*/\s*l", eff, re.I)
        m_mpg = re.search(r"(\d+(?:\.\d+)?)\s*mpg", eff, re.I)
        kml = float(m_kml.group(1)) if m_kml else (round(float(m_mpg.group(1)) * 0.425, 1) if m_mpg else (19.5 if pt == "HEV" else 13.0))
        kml = max(5.0, min(35.0, kml))
        energy_15k = int(round((15000 / kml) * (29.5 if is_diesel else 31.5) * (0.65 if pt == "PHEV" else 1.0)))

    ins_b = int(round(max(12000, (11500 + msrp * 0.0085) * i_mult * (1.15 if pt == "BEV" else 1.0)) / 500) * 500)
    ins_e = int(round(max(22000, (16000 + msrp * 0.0175) * i_mult * (1.18 if pt == "BEV" else 1.0)) / 500) * 500)
    ins_a = int(round(ins_e * 1.48 / 500) * 500)
    maint = int(round((12500 if pt != "BEV" else 6500) * p_mult / 500) * 500)
    late_rep = int(round(max(6000, (100 - rel) * 750 * p_mult) / 500) * 500)
    annual_cash = tax + ins_e + energy_15k + maint

    # 3. RESALE CURVE (strictly monotonic Y0 > Y1 > Y2 > Y3 > Y4 > Y5)
    r3, r5 = round(r3, 1), round(min(r3 - 7.0, r5), 1)
    r1 = round(min(92.0, 100.0 - (100.0 - r3) * 0.44), 1)
    r2 = round(min(r1 - 3.0, 100.0 - (100.0 - r3) * 0.75), 1)
    r4 = round((r3 + r5) / 2.0, 1)
    y3_val, y5_val = int(round(tx_typ * r3 / 100)), int(round(tx_typ * r5 / 100))
    dep_5y_yr = int(round((tx_typ - y5_val) / 5))
    v["ownership"] = {
        "rel_score": round(rel, 1), "rel_grade": rel_grade, "warranty": w_yrs,
        "tax": tax, "tax_note": tax_note, "energy_15k": energy_15k, "maint": maint,
        "late_rep": late_rep, "ins": {"basic": ins_b, "standard": ins_e, "full": ins_a},
        "annual_cash": annual_cash, "annual_tco": annual_cash + dep_5y_yr,
    }
    v["resale"] = {
        "y1": r1, "y2": r2, "y3": r3, "y4": r4, "y5": r5,
        "y3_val": y3_val, "y5_val": y5_val, "dep_3y": tx_typ - y3_val, "dep_5y": tx_typ - y5_val,
        "cpo_tip": "保值率極高（3 年仍留 60%+），新車折舊損失小，買新車享完整保固最划算！" if r3 >= 60 else ("豪華／純電車頭 3 年折舊較快，重視高 CP 值可同時評估 1–2 年認證中古車，重視最新配備與 0 利率則選新車。" if r3 < 54 else "保值表現穩健，搭配經銷空車折讓或原廠 0 利率，持有 5 年攤提成本合理。"),
    }

    # 4. TAIWAN EV CHARGING PROFILE
    if any(p in ("BEV", "PHEV") for p in v["powertrains"]):
        is_bev = "BEV" in v["powertrains"]
        conn = ("CCS2" if brand in TW_CCS2_BRANDS else "CCS1") if is_bev else ("AC Type2" if brand in TW_CCS2_BRANDS else "AC Type1")
        arch, dc_kw, t10_80, v2l = ("400V", 150 if is_bev else 0, 32 if is_bev else 0, brand in ("Hyundai", "Kia", "MG", "Foxtron", "Luxgen"))
        for rb, pat, kw, mins, has_v2l in ULTRA_800V_RULES:
            if brand.lower() == rb and re.search(pat, ml):
                arch, dc_kw, t10_80, v2l = "800V", kw, mins, has_v2l
                break
        if brand == "Tesla" and is_bev and arch != "800V":
            dc_kw, t10_80 = 250, 27
        v["charging"] = {"has_plug": True, "conn": conn, "arch": arch, "dc_kw": dc_kw, "t10_80": t10_80, "v2l": v2l}
    else:
        v["charging"] = {"has_plug": False, "conn": "NONE", "arch": "", "dc_kw": 0, "t10_80": 0, "v2l": False}

    # 5. LIFECYCLE & BEFORE-VS-AFTER FACELIFT COMPARISON
    lc = None
    for rb, rm, cfg in CURATED_FACELIFT_DB:
        if brand.lower() == rb and rm in ml:
            lc = dict(cfg)
            break
    if lc is None:
        lc = {
            "stage": "MID_CYCLE", "stage_label": "現行主力世代",
            "gen": f"{brand} {model} 台灣現行在售最新年式",
            "est_fl": "預計 1～2 年內依原廠節奏進行年式配備升級或中期小改款",
            "est_rd": "預估 3～5 年後依品牌平台週期推出下一世代大改款",
            "title": f"{brand} {model} 現行在售款 vs. 預期小改款升級對照",
            "before_label": "現行在售款（交車快・折讓透明）",
            "after_label": "預期中期小改款展望",
            "verdict": "現行款供應穩定且可立即享受經銷折讓或原廠 0 利率方案；若不急用車可持續追蹤原廠改款動態。",
            "rows": [
                {"c": "外觀與燈組", "b": "現行成熟家族設計，台灣實車現貨選擇完整。", "a": "預期導入新式 LED 光條燈語與空氣力學新輪圈。", "t": "upgrade"},
                {"c": "座艙與車機", "b": "現行穩定版本車載主機與完整主動安全配備。", "a": "預期升級高算力車機晶片、無線連線與 AI 語音。", "t": "major"},
                {"c": "購車折讓與時機", "b": "已有合理空車折讓或原廠分期 0 利率專案。", "a": "改款初期定價易微調且折讓空間收斂。", "t": "tradeoff"},
            ],
        }
    v["lifecycle"] = lc

    # 6. 7-DIM REVIEW SCORES
    max_hp = max((_pint(t["specs"].get("hp", "")) or 150 for t in trims), default=150)
    best_acc = min((t["specs"]["acc"] for t in trims if t["specs"].get("acc")), default=None)
    v["best_acc"] = best_acc
    v["max_hp"] = max_hp
    v["scores"] = {
        "power": round(min(9.8, max(7.2, 7.4 + min(max_hp, 700) / 300.0 + (0.4 if pt in ("BEV", "PHEV") else 0))), 1),
        "handling": 8.9 if (v["body_style"] == "coupe" or brand in ("Porsche", "BMW", "Ferrari", "Lamborghini", "McLaren", "Alfa Romeo", "MINI", "Lotus")) else (8.3 if brand in LUXURY_BRANDS else 7.9),
        "space": 8.9 if v["body_style"] in ("mpv", "suv", "wagon") else (8.4 if v["body_style"] == "sedan" else 7.5),
        "safety": 9.1 if any("Level 2" in t["equip"].get("adas", "") for t in trims) else 8.4,
        "tech": 9.0 if (brand in LUXURY_BRANDS or brand in DIRECT_FIXED_BRANDS or pt == "BEV") else 8.2,
        "reliability": round(min(9.8, rel / 10.0), 1),
        "value": 8.9 if v["min_msrp"] <= 1_200_000 else (8.4 if v["min_msrp"] <= 2_400_000 else 7.8),
    }
    return v


def _fetch_toyota_cutouts() -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        page = _fetch_text(TOYOTA_TW_SHOWROOM, timeout=12, retries=1)
        pat = re.compile(r'href="/showroom/([^/"]+)/?".*?src="(//hotaicdn\.azureedge\.net/toyotaweb/CAR_[^"]+\.png)".*?<h4>(.*?)</h4>', re.S | re.I)
        for m in pat.finditer(page):
            url = "https:" + m.group(2).strip()
            for key in (m.group(1), re.sub(r"<[^>]+>", "", html_lib.unescape(m.group(3)))):
                nk = re.sub(r"[^a-z0-9]+", "", key.lower())
                if nk:
                    out[nk] = url
    except Exception:
        pass
    return out


def _fetch_live_fx() -> dict[str, float]:
    fallback = {"USD": 1.0, "TWD": 32.3, "JPY": 154.0, "EUR": 0.94, "CNY": 7.24}
    try:
        data = json.loads(_fetch_text(FX_API_URL, timeout=10, retries=1))
        rates = data.get("rates") or {}
        if rates.get("TWD"):
            return {k: round(float(rates.get(k, fallback[k])), 4) for k in fallback}
    except Exception:
        pass
    return fallback


def _discover_ucar_tw() -> list[dict[str, str]]:
    html_txt = html_lib.unescape(_fetch_text(f"{UCAR_BASE}/newcar/search", timeout=20, retries=2))
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for m in re.finditer(r'href="(/[^/"]+/[^/"]+/(\d+)/overall)"', html_txt):
        path, mid = m.group(1), m.group(2)
        if mid in seen:
            continue
        seen.add(mid)
        p = path.lstrip("/").split("/")
        out.append({"id": mid, "raw_brand": p[0].lower(), "raw_model": p[1], "overall": path, "spec": f"/{p[0]}/{p[1]}/{mid}/spec", "equip": f"/{p[0]}/{p[1]}/{mid}/equip"})
    return out


def _build_one_tw_car(entry: dict[str, str], toy_cutouts: dict[str, str]) -> dict[str, Any] | None:
    brand = BRAND_CANONICAL.get(entry["raw_brand"], entry["raw_brand"].title())
    enc = lambda path: "/" + "/".join(urllib.parse.quote(x, safe="") for x in path.lstrip("/").split("/"))
    try:
        ov_html = _fetch_text(UCAR_BASE + enc(entry["overall"]), timeout=15, retries=1)
        sp_html = _fetch_text(UCAR_BASE + enc(entry["spec"]), timeout=15, retries=1)
    except Exception:
        return None
    try:
        eq_html = _fetch_text(UCAR_BASE + enc(entry["equip"]), timeout=12, retries=0)
    except Exception:
        eq_html = ""

    # Display model name
    model = entry["raw_model"].title()
    mt = re.search(r"<title>(.*?)</title>", ov_html, re.S)
    if mt:
        tc = re.sub(r"\s*車款介紹.*$", "", html_lib.unescape(mt.group(1)).strip()).strip()
        for pref in (brand, entry["raw_brand"], "Mercedes-Benz", "Volkswagen Commercial Vehicles"):
            if tc.lower().startswith(pref.lower()) and tc[len(pref):].strip():
                model = tc[len(pref):].strip()
                break

    if _is_delisted(brand, model):
        return None

    # Parse spec & equip tables
    sp = UCarTableParser()
    sp.feed(sp_html)
    if not sp.rows:
        return None
    hdr = sp.rows[0]
    th_list = []
    for ci in range(1, len(hdr)):
        tn, msrp = _parse_wan_twd(hdr[ci]["text"])
        th_list.append((tn, msrp))
    n = len(th_list)
    spec_map: dict[str, list[str]] = {}
    for row in sp.rows[1:]:
        if not row:
            continue
        k = row[0]["text"].rstrip("：:").strip()
        if not k:
            continue
        vals = [row[i + 1]["text"] if i + 1 < len(row) else "" for i in range(n)]
        spec_map[k] = vals

    eq_map: dict[str, list[str]] = {}
    diff_keys: list[str] = []
    if eq_html:
        ep = UCarTableParser()
        ep.feed(eq_html)
        for row in ep.rows[1:]:
            if not row:
                continue
            k = row[0]["text"].rstrip("：:").strip()
            if not k:
                continue
            if "differentequip" in row[0].get("row_class", ""):
                diff_keys.append(k)
            vals = []
            for i in range(n):
                if i + 1 < len(row):
                    c = row[i + 1]
                    alts = " ".join(c["alts"])
                    if "標準配備" in alts:
                        vals.append(f"標配 {c['text']}".strip() if c["text"] else "標配")
                    elif "選用配備" in alts:
                        vals.append(f"選配 {c['text']}".strip() if c["text"] else "選配")
                    elif "無此配備" in alts:
                        vals.append("")
                    else:
                        vals.append(c["text"])
                else:
                    vals.append("")
            eq_map[k] = vals

    sv = lambda k, i, d="": (spec_map[k][i] if k in spec_map and i < len(spec_map[k]) and spec_map[k][i] else d)
    ev = lambda k, i: (eq_map[k][i] if k in eq_map and i < len(eq_map[k]) else "")

    body = _map_body(sv("車身型式", 0), model)
    trims: list[dict[str, Any]] = []
    seen_tids: set[str] = set()
    for i, (tn, msrp) in enumerate(th_list):
        if not msrp or msrp <= 0:
            continue
        tid = _slug(tn)
        k_s = 2
        while tid in seen_tids:
            tid = f"{_slug(tn)}-{k_s}"
            k_s += 1
        seen_tids.add(tid)

        ps, en, tech, batt = sv("動力系統", i), sv("能源", i), sv("引擎技術", i), sv("電池總容量", i) or sv("可用電池容量", i)
        pt = _map_pt(ps, en, tech, f"{model} {tn}", batt)
        disp = sv("排氣量", i)
        cc = _pint(disp) or 0
        eng = " / ".join(x for x in [ps or "純電動馬達", f"電池 {batt}" if batt else ""] if x) if pt == "BEV" else (" ".join(x for x in [disp, sv("汽缸設計", i), tech, ps] if x) or f"{en or '汽油'} 引擎")
        hp = sv("最大綜效馬力", i) or sv("引擎最大馬力", i) or sv("馬達最大功率", i) or "原廠公布"
        tq = sv("最大綜效扭力", i) or sv("引擎最大扭力", i) or sv("馬達最大扭力", i) or "原廠公布"
        trans = sv("變速系統", i) or ("單速電動減速齒輪" if pt == "BEV" else "自排變速系統")
        drive = sv("傳動方式", i) or "原廠配置"
        acc = _pfloat(sv("加速", i))
        if acc is not None and (acc < 1.5 or acc > 30.0):
            acc = None
        af, evr, efv = sv("平均油耗", i), sv("純電池里程", i) or sv("純電行程", i), sv("能效測試值", i)
        eff = (" / ".join(x for x in [f"續航 {evr}" if evr else "", f"能效 {efv}" if efv else ""] if x) or "依能源署純電標準") if pt == "BEV" else (" / ".join(x for x in [f"平均油耗 {af}" if af else "", f"純電 {evr}" if evr else ""] if x) or "依能源署測試標準")

        dims = [_pint(sv("車長", i)) or 4500, _pint(sv("車寬", i)) or 1820, _pint(sv("車高", i)) or 1550, _pint(sv("軸距", i)) or 2700, _pint(sv("乘客數", i)) or 5]
        airbags = _pint(ev("氣囊總數", i)) or 6
        adas_bits = [lbl for k_, lbl in [("車距維持巡航系統", "ACC 全速域"), ("車道維持輔助系統", "車道維持"), ("盲點偵測系統", "盲點偵測"), ("AEB自動緊急煞車系統", "AEB 主動煞停")] if ev(k_, i).startswith("標配")]
        adas = ("Level 2（" + "、".join(adas_bits) + "）") if adas_bits else "原廠主被動安全輔助"
        cam = "＋".join(x for x in ["360° 環景" if ev("環景影像系統", i).startswith("標配") else "", "倒車顯影" if ev("倒車攝影系統", i).startswith("標配") else ""] if x) or "停車輔助雷達"
        disp_str = "＋".join(x for x in ["數位儀錶" if ev("數位儀錶", i).startswith("標配") else "", "HUD 抬頭顯示" if ev("擡頭顯示器", i).startswith("標配") else "", "CarPlay/AA" if (ev("Apple CarPlay", i).startswith("標配") or ev("Android Auto", i).startswith("標配")) else ""] if x) or "原廠多媒體系統"

        # ALWAYS strictly list[str] for trim_diff_highlights!
        hl: list[str] = [f"{hp}・{trans}・{drive}"]
        for dk in diff_keys:
            if ev(dk, i).startswith("標配") and len(hl) < 5:
                hl.append(f"標配 {dk}")

        trims.append({
            "id": tid, "name": tn, "msrp": msrp, "tx": _build_tx_price(brand, model, tn, msrp),
            "specs": {"pt": pt, "eng": eng, "cc": cc, "hp": hp, "tq": tq, "trans": trans, "drive": drive, "acc": acc, "eff": eff, "dims": dims, "tire": sv("輪胎尺寸", i) or "原廠配胎"},
            "equip": {"airbags": airbags, "adas": adas, "cam": cam, "disp": disp_str, "sunroof": ev("天窗", i) or "依等級配置", "audio": ev("音響喇叭數", i) or "原廠音響"},
            "diff": hl,
        })

    if not trims:
        return None

    # Photos: Toyota studio PNG cutout (if match) + U-CAR real official photos (skip articleimage_)
    photos: list[str] = []
    if brand == "Toyota":
        nm = re.sub(r"[^a-z0-9]+", "", model.lower())
        if nm in toy_cutouts:
            photos.append(toy_cutouts[nm])
        else:
            for k_, u_ in toy_cutouts.items():
                if nm and (nm in k_ or k_ in nm):
                    photos.append(u_)
                    break
    mog = re.search(r'property="og:image"\s+content="([^"]+)"', ov_html)
    if mog:
        u = ("https:" + mog.group(1)) if mog.group(1).startswith("//") else mog.group(1)
        if "image.u-car.com.tw/" in u and "articleimage_" not in u and u not in photos:
            photos.append(u)
    for gid, pid in re.findall(r'data-gallery="(\d+)"\s+data-photo="(\d+)"', ov_html):
        u = f"https://image.u-car.com.tw/{gid}/photo_{pid}.jpg"
        if u not in photos:
            photos.append(u)
        if len(photos) >= 6:
            break
    if not photos:
        photos.append(f"https://image.u-car.com.tw/newcar_{entry['id']}.jpg")

    return _enrich_vehicle({
        "id": f"tw-{_slug(brand)}-{_slug(model)}-u{entry['id']}",
        "market_code": "TW",
        "brand": brand,
        "brand_zh": BRAND_ZH.get(brand, ""),
        "model": model,
        "model_zh": f"{BRAND_ZH.get(brand, brand)} {model}".strip(),
        "body_style": body,
        "official_url": BRAND_OFFICIAL_URLS.get(brand, "https://www.google.com/search?q=" + urllib.parse.quote(f"{brand} {model} 台灣官網")),
        "photos": photos[:6],
        "colors": BRAND_COLORS.get(brand, DEFAULT_COLORS),
        "imagin": _build_imagin(brand, model),
        "trims": trims,
    })


def _build_pi_vehicles() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in PI_CURATED_SPECS:
        trims = []
        for idx, tr in enumerate(p["trims"]):
            tn, msrp, pt, eng, hp, tq, acc, eff, drv, trans = tr
            m_l = re.search(r"(\d+(?:\.\d+)?)\s*L\b", eng)
            cc = int(round(float(m_l.group(1)) * 1000)) if (m_l and pt != "BEV") else 0
            trims.append({
                "id": f"pi-t{idx + 1}", "name": tn, "msrp": msrp,
                "tx": _build_tx_price(p["brand"], p["model"], tn, msrp, is_pi=True),
                "specs": {"pt": pt, "eng": eng, "cc": cc, "hp": hp, "tq": tq, "trans": trans, "drive": drv, "acc": acc, "eff": eff, "dims": p["dims"], "tire": "原廠規格配胎"},
                "equip": {"airbags": 8, "adas": "Level 2 智駕輔助（美規原廠全套安全系統）", "cam": "360° 環景＋倒車顯影", "disp": "大尺寸數位儀錶＋CarPlay/AA", "sunroof": "全景天窗（視等級）", "audio": "美規原廠高階音響"},
                "diff": [f"{hp}・{trans}・{drv}", f"全新未領牌完稅價約 NT${msrp / 10000:.0f} 萬"],
            })
        out.append(_enrich_vehicle({
            "id": p["id"], "market_code": "PI", "brand": p["brand"], "brand_zh": BRAND_ZH.get(p["brand"], ""),
            "model": p["model"], "model_zh": p["model_zh"], "body_style": p["body_style"],
            "official_url": p["official_url"], "photos": p["photos"],
            "colors": BRAND_COLORS.get(p["brand"], DEFAULT_COLORS),
            "imagin": _build_imagin(p["brand"], p["model"]),
            "trims": trims,
        }))
    return out


FAVICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0%" stop-color="#0f172a"/><stop offset="100%" stop-color="#2563eb"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#g)"/><text x="32" y="45" font-size="38" text-anchor="middle">🐉</text></svg>"""


def build_site(out_dir: Path, workers: int = 16) -> dict[str, Any]:
    t0 = time.perf_counter()
    print("🐉 [1/4] 正在連線台灣公開新車目錄與免費即時匯率...", flush=True)
    fx = _fetch_live_fx()
    toy_cutouts = _fetch_toyota_cutouts()
    ucar_list = _discover_ucar_tw()
    print(f"    -> 探索到 {len(ucar_list)} 款公開車系、{len(toy_cutouts)} 張 Toyota 棚拍去背圖、USD/TWD={fx['TWD']}", flush=True)

    print(f"🚗 [2/4] 平行解析全台灣現行新車規格、配備與實車圖資 ({workers} 執行緒)...", flush=True)
    tw_vehicles: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        for res in ex.map(lambda e: _build_one_tw_car(e, toy_cutouts), ucar_list):
            if res:
                tw_vehicles.append(res)

    # Deduplicate by (brand_low, model_low) keeping richer trim count
    dedup: dict[tuple[str, str], dict[str, Any]] = {}
    for v in tw_vehicles:
        key = (v["brand"].lower(), v["model"].lower())
        if key not in dedup or len(v["trims"]) > len(dedup[key]["trims"]):
            dedup[key] = v
    tw_clean = sorted(dedup.values(), key=lambda x: (x["brand"].lower(), x["min_msrp"]))
    pi_clean = _build_pi_vehicles()
    all_vehicles = tw_clean + pi_clean

    print(f"📦 [3/4] 產出靜態網站至 {out_dir}（台灣總代理 {len(tw_clean)} 款 ＋ 貿易商限定 {len(pi_clean)} 款 ＝ {len(all_vehicles)} 款）...", flush=True)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    (out_dir / "data").mkdir(parents=True, exist_ok=True)

    now_iso = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M CST")
    brands_tw = sorted({v["brand"] for v in tw_clean})
    brands_pi = sorted({v["brand"] for v in pi_clean})
    zero_apr_cnt = sum(1 for v in all_vehicles if v["financing"]["has_zero_apr"])

    bootstrap = {
        "generated_at": now_iso,
        "fx": fx,
        "stats": {
            "total": len(all_vehicles), "tw": len(tw_clean), "pi": len(pi_clean),
            "tw_brands": len(brands_tw), "pi_brands": len(brands_pi), "zero_apr_models": zero_apr_cnt,
        },
        "vehicles": all_vehicles,
    }
    (out_dir / "data" / "bootstrap.json").write_text(json.dumps(bootstrap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    src_html = ROOT_DIR / "web_app.html"
    if not src_html.is_file():
        raise FileNotFoundError(f"Missing {src_html}")
    shutil.copy2(src_html, out_dir / "index.html")
    (out_dir / "favicon.ico").write_text(FAVICON_SVG, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    kb = (out_dir / "data" / "bootstrap.json").stat().st_size / 1024.0
    print(f"✅ [4/4] 雲端建置完成！共 {len(all_vehicles)} 款新車（{zero_apr_cnt} 款享原廠 0 利率），bootstrap.json 僅 {kb:.1f} KB，耗時 {time.perf_counter() - t0:.1f}s。", flush=True)
    return bootstrap["stats"]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="🐉 新車龍龍雲端靜態建置器")
    ap.add_argument("--out", default="dist", help="靜態網站輸出資料夾")
    ap.add_argument("--workers", type=int, default=16, help="平行下載執行緒數")
    args = ap.parse_args()
    build_site(Path(args.out), workers=args.workers)
