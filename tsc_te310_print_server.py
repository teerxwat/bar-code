"""
TSC TE310 — เซิร์ฟเวอร์พิมพ์ป้ายสติกเกอร์ผ่าน USB บนเครื่องที่ต่อกับเครื่องพิมพ์ (macOS)

เดิมสคริปต์นี้เป็นแบบแก้ตัวแปร SIDE_TEXT/NUMBER/BARCODE_DATA เองแล้วรันทีละครั้ง
ตอนนี้ปรับให้เป็น HTTP server แทน — เว็บแอป SmartPay เรียก POST /print มาที่เครื่องนี้
ได้โดยตรง (แทนที่จะเปิด browser print dialog แบบเดิม) ส่ง user_id, name, house, moo,
tambon มา สร้างป้ายให้พร้อมสั่งพิมพ์ทันที ดูสเปก API เต็มๆ ที่ README.md ในโฟลเดอร์เดียวกัน

ป้าย: แถบดำซ้าย (แนวนอน 50x30 mm) แสดง 2 บรรทัดแนวตั้งสีขาว —
บรรทัด 1: ชื่อ (name), บรรทัด 2: ที่อยู่ "{house} หมู่ {moo} ต.{tambon}"
+ บาร์โค้ด Code128 ของ user_id ใหญ่ทางขวา พร้อมเลข user_id กำกับใต้บาร์โค้ด

ติดตั้งก่อน:
    brew install libusb
    pip install pyusb pillow

วิธีรัน (server จะทำงานค้างไว้ รอรับคำสั่งพิมพ์จากเว็บแอป):
    python tsc_te310_print_server.py
    # ถ้า Access denied ตอนคุย USB: sudo python tsc_te310_print_server.py

ทดสอบด้วยมือ (ไม่ผ่านเว็บแอป):
    curl -X POST http://localhost:9100/print \
      -H "Content-Type: application/json" \
      -d '{"user_id":"M-1042","name":"นาย สมชาย ใจดี","house":"123/45","moo":"3","tambon":"บ้านกาด","quantity":1}'

ทดสอบตอนยังไม่มีเครื่องพิมพ์ต่ออยู่ (MOCK MODE):
    เปิด server ด้วย --mock (หรือตั้ง env TSC_MOCK=1) — /print จะไม่แตะ USB เลย
    แค่ประกอบป้ายเหมือนเดิมแล้ว "เสมือนพิมพ์สำเร็จ" พร้อมเซฟภาพ PNG ของป้าย
    (รวมบาร์โค้ดจริง ถ้าลง `pip install python-barcode` ไว้) ไปที่โฟลเดอร์ previews/
    ให้เปิดดูว่าถ้าพิมพ์จริงจะออกมาหน้าตาแบบไหน โดยยังทดสอบ flow ของเว็บแอป
    (POST /print, validation, JSON response) ได้ครบเหมือนมีเครื่องจริงต่ออยู่
        python tsc_te310_print_server.py --mock
        curl -X POST http://localhost:9100/print -H "Content-Type: application/json" \
          -d '{"user_id":"M-1042","name":"นาย สมชาย ใจดี","house":"123/45","moo":"3","tambon":"บ้านกาด"}'

พิมพ์หลายบ้านรวดเดียว จาก SmartPay API โดยตรง (ไม่ต้องพึ่งเบราว์เซอร์ไล่ยิง /print ทีละบ้าน):
    ตั้งค่า X-Print-Key ก่อน (ขอจากผู้ดูแลระบบ — คีย์เดียวกับที่ GET /print/sticker-by-key/{user_id}
    ใช้อยู่แล้ว) ผ่าน env SMARTPAY_PRINT_KEY แล้วยิง POST /print-batch-by-key มาที่ server
    ตัวนี้ด้วยเงื่อนไขแบบเดียวกับที่ POST /print/sticker-batch-by-key ของ SmartPay รับ
    (from_user_id, to_user_id, moo, tambon, user_ids, paid_only, quantity — ดู
    README-sticker-batch-api.md) — server จะไปดึงรายชื่อเอง แล้วพิมพ์ทั้งชุด (label คั่น
    พื้นดำ+ลูกศร ก่อนบาร์โค้ดของแต่ละบ้าน) รวดเดียวจนจบหรือจนพิมพ์ไม่ผ่านบ้านใดบ้านหนึ่ง
    (หยุดทั้งชุดทันทีถ้าพิมพ์บ้านไหนไม่ผ่าน) ถ้าตั้ง env SMARTPAY_ADMIN_JWT ไว้ด้วย จะเรียก
    บันทึกประวัติพิมพ์ (POST /print/sticker-batch/log) ให้อัตโนมัติหลังพิมพ์เสร็จ
        SMARTPAY_PRINT_KEY=xxxxx python tsc_te310_print_server.py
        curl -X POST http://localhost:9100/print-batch-by-key -H "Content-Type: application/json" \
          -d '{"from_user_id":"M-1001","to_user_id":"M-1010","quantity":2}'
    ทดสอบแบบ mock (ไม่ต้องมีเครื่องพิมพ์ ยังต้องมี SMARTPAY_PRINT_KEY ที่ใช้ดึงรายชื่อได้จริง):
        SMARTPAY_PRINT_KEY=xxxxx python tsc_te310_print_server.py --mock
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont, features

# RAQM (libraqm) จำเป็นสำหรับจัดวางสระ/วรรณยุกต์ภาษาไทยให้ถูกตำแหน่ง
# บน macOS ที่ลง libusb ผ่าน brew มักมีให้; บน Windows มักไม่มี (ต้องลง DLL เพิ่ม)
# ถ้าไม่มีจะ fallback เป็น BASIC layout — ไทยพิมพ์ออกแต่สระ/วรรณยุกต์อาจเพี้ยน
_HAVE_RAQM = features.check("raqm")
_LAYOUT = ImageFont.Layout.RAQM if _HAVE_RAQM else ImageFont.Layout.BASIC

# หาฟอนต์ไทยจาก path ของสคริปต์เอง (ไม่ใช่ cwd ที่รันคำสั่ง) — รองรับทั้งกรณี
# ไฟล์ฟอนต์อยู่ข้างสคริปต์โดยตรง และอยู่ในโฟลเดอร์ fonts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")


# โหลดไฟล์ .env (ถ้ามี) ข้างสคริปต์ — เก็บค่าที่ไม่อยากพิมพ์ซ้ำทุกครั้งตอนรัน server
# เช่น SMARTPAY_PRINT_KEY, SMARTPAY_ADMIN_JWT ไว้ในไฟล์นี้แทน (ดู .env.example)
# ไม่พึ่ง python-dotenv เพราะไม่อยากเพิ่ม dependency แค่นี้ — parse เองแบบง่ายๆ พอ
# ตั้งด้วย os.environ.setdefault() เท่านั้น: ถ้ามี env var จริงตั้งไว้อยู่แล้ว (เช่น
# ตอนรันแบบ `SMARTPAY_PRINT_KEY=xxx python ...`) ค่านั้นจะชนะเสมอ ไม่ถูกไฟล์ .env ทับ
def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


_load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

# ============== ค่าเครื่อง / ขนาด ==============
# Pin เครื่องบาร์โค้ดด้วย VID/PID ได้ผ่าน env var (เลขฐาน 16 เช่น 0x1203)
# ตั้งเมื่อ: มีเครื่อง TSC หลายตัว หรือชื่อ USB ไม่มีคำว่า "TSC"
#   หา VID/PID ได้ด้วย:  python tsc_te310_print_server.py --list
#   แล้วรันแบบ:  TSC_VID=0x1203 TSC_PID=0x0230 python tsc_te310_print_server.py
def _env_hex(name):
    v = os.environ.get(name)
    if not v:
        return None
    try:
        return int(v, 16)
    except ValueError:
        try:
            return int(v)
        except ValueError:
            print(f"*** ค่า {name}={v!r} ไม่ใช่เลขฐาน 16 ที่ถูกต้อง — ข้าม")
            return None


VENDOR_ID = _env_hex("TSC_VID")
PRODUCT_ID = _env_hex("TSC_PID")

# Vendor ID ของ TSC Auto ID Technology — เครื่อง TSC บางรุ่น (เช่น TE310) รายงาน
# ชื่อ USB (manufacturer/product) มาเป็นค่าว่าง เลยจับด้วยชื่อ "TSC" ไม่ได้
# ต้องรู้จัก VID ไว้ด้วยถึงจะแยกออกจากเครื่องปริ้นเอกสาร (เช่น Brother=0x04f9)
TSC_VENDOR_IDS = {0x1203}

DENSITY = 10
SPEED = 3
W, H = 590, 354  # 50mm x 30mm @300dpi
GAP_MM = 3  # ระยะ gap ระหว่างป้ายบนม้วนสติกเกอร์ (ต้องตรงกับ "GAP {GAP_MM} mm, 0 mm" ใน build_tspl)
INVERT_BITMAP = False

BAND_W = 150  # ความกว้างแถบดำซ้าย

# บาร์โค้ด (เน้นใหญ่) — วางในโซนขวา
BAR_X = 250  # ขยับซ้าย-ขวาให้อยู่กึ่งกลางโซนขวา
BAR_Y = 92
BAR_HEIGHT = 158
BAR_NARROW = 3  # 2=เล็ก 3=กลาง 4=ใหญ่

PRINT_SERVER_PORT = 9100

# MOCK MODE — ทดสอบ /print ได้โดยไม่ต้องมีเครื่องพิมพ์ต่ออยู่จริง เปิดด้วย
# --mock ตอนรัน หรือ env TSC_MOCK=1 — จะข้ามขั้นตอนหา/ส่งข้อมูลไป USB ทั้งหมด
# แล้วเซฟรูปตัวอย่างป้าย (PNG) ไว้ดูแทน พร้อมตอบ success กลับไปเหมือนพิมพ์จริง
MOCK_PRINT = bool(os.environ.get("TSC_MOCK")) or "--mock" in sys.argv
PREVIEW_DIR = os.path.join(SCRIPT_DIR, "previews")

# SmartPay API — ให้ print server ดึงรายชื่อบ้านทั้งชุด + พิมพ์ + บันทึกประวัติเองได้
# โดยไม่ต้องพึ่งเบราว์เซอร์เปิดค้าง (ดู README-sticker-batch-api.md ที่ backend ส่งมา)
#   SMARTPAY_API_BASE  = URL ฐานของ API (ปกติไม่ต้องตั้งเอง มีค่า default อยู่แล้ว)
#   SMARTPAY_PRINT_KEY = X-Print-Key ของฮาร์ดแวร์ (ขอจากผู้ดูแลระบบ) — จำเป็นสำหรับ
#                        POST /print-batch-by-key ถ้าไม่ตั้งไว้จะตอบ 503
#   SMARTPAY_ADMIN_JWT = ไม่บังคับ — ถ้าตั้งไว้ พิมพ์เสร็จแล้วจะเรียกบันทึกประวัติ
#                        (POST /print/sticker-batch/log) ให้อัตโนมัติ ถ้าไม่ตั้งจะข้าม
#                        ขั้นตอนนี้ไป (ต้องไปกดบันทึกที่หน้าเว็บแอดมินเอง)
SMARTPAY_API_BASE = os.environ.get("SMARTPAY_API_BASE",
                                    "https://www.maewang-smartpay.donaus-dev.net/api")
SMARTPAY_PRINT_KEY = os.environ.get("SMARTPAY_PRINT_KEY")
SMARTPAY_ADMIN_JWT = os.environ.get("SMARTPAY_ADMIN_JWT")
# ===============================================

BOLD = [
    # ฟอนต์หลัก: Noto Sans Thai รองรับภาษาไทยครบ (สระ/วรรณยุกต์/เลข)
    # เช็คทั้ง 2 ตำแหน่ง: ข้างสคริปต์โดยตรง และในโฟลเดอร์ fonts/
    os.path.join(SCRIPT_DIR, "NotoSansThai-Variable.ttf"),
    os.path.join(FONT_DIR, "NotoSansThai-Variable.ttf"),
    # ฟอนต์สำรอง (ใช้ได้แค่ภาษาอังกฤษ/ตัวเลข — ภาษาไทยจะหายทั้งบรรทัด!
    # ถ้าตกมาถึงตรงนี้แปลว่าหาไฟล์ Noto Sans Thai ไม่เจอ ดู warning ตอนเปิด server)
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
]


def check_thai_font():
    """เตือนตั้งแต่ตอนเปิด server ถ้าหาฟอนต์ไทยไม่เจอ — ไม่งั้นชื่อ/ที่อยู่ภาษาไทยจะพิมพ์ไม่ออก"""
    for p in BOLD[:2]:
        if os.path.exists(p):
            print(f"ฟอนต์ไทย OK: {p}")
            return True
    print("*** คำเตือน: หา NotoSansThai-Variable.ttf ไม่เจอ — ข้อความภาษาไทยจะพิมพ์ไม่ออก!")
    print(f"*** วางไฟล์ฟอนต์ไว้ที่ {SCRIPT_DIR}/ หรือ {FONT_DIR}/")
    return False


def load_font(paths, size, index=0):
    for p in paths:
        try:
            f = ImageFont.truetype(p, size, index=index, layout_engine=_LAYOUT)
        except Exception:
            try:
                f = ImageFont.truetype(p, size, index=index)
            except Exception:
                continue
        # Noto Sans Thai เป็น variable font (มีหลายน้ำหนักในไฟล์เดียว) ต้องสั่งตั้ง
        # แกนน้ำหนัก (wght) เป็น 700 (bold) เอง ไม่งั้นจะได้ค่า default คือ 400 (regular)
        # — ฟอนต์ระบบทั่วไปที่ไม่ใช่ variable font จะ error ตรงนี้ ปล่อยผ่านไปเฉยๆ ได้เลย
        try:
            f.set_variation_by_axes([700])
        except Exception:
            pass
        return f
    return ImageFont.load_default()


def draw_tracked(draw, xy, text, font, tracking=0, fill=0, align="left"):
    widths = [draw.textlength(c, font=font) for c in text]
    total = sum(widths) + tracking * max(0, len(text) - 1)
    x, y = xy
    if align == "right":
        x -= total
    elif align == "center":
        x -= total / 2
    for c, w in zip(text, widths):
        draw.text((x, y), c, font=font, fill=fill)
        x += w + tracking
    return total


def fit_side_text_font(text: str, max_width: int, max_size: int = 46, min_size: int = 10, step: int = 2):
    """
    ลดขนาดฟอนต์ลงเรื่อยๆ จนกว่าความกว้างของข้อความ (แนวนอน ก่อนหมุน 90°) จะพอดี
    กับพื้นที่ที่มี (max_width) — จำเป็นเพราะข้อความแถบดำยาวไม่คงที่ตามข้อมูล
    (ชื่อ/บ้านเลขที่/หมู่/ตำบล)
    """
    tmp = ImageDraw.Draw(Image.new("1", (4, 4), 0))
    size = max_size
    while size > min_size:
        f = load_font(BOLD, size)
        bbox = tmp.textbbox((0, 0), text, font=f)
        if (bbox[2] - bbox[0]) <= max_width:
            return f, size
        size -= step
    return load_font(BOLD, min_size), min_size


def build_house_moo_text(house: str, moo: str = "", soi: str = "") -> str:
    """
    ประกอบข้อความ "{house} หมู่ {moo} ซอย {soi}" — บรรทัดล่างของแถบดำ
    (ไม่มีคำนำหน้า "บ้านเลขที่" ใส่เลขบ้านเลย / ตำบลแยกไปอยู่บรรทัดบนต่างหาก ดู render_label_bitmap)
    - หมู่/ซอย ใส่เฉพาะตอนมีข้อมูล ไม่มีก็ไม่แสดงคำนำหน้านั้นเลย
    """
    parts = [house] if house else []
    if moo:
        parts.append(f"หมู่ {moo}")
    if soi:
        parts.append(f"ซอย {soi}")
    return " ".join(parts)


def render_band_tile(lines, max_text_width: int, max_total_height: int) -> Image.Image:
    """
    วาดข้อความหลายบรรทัด (ตัวขาวบนพื้นดำ) เป็น tile แนวนอน แล้วหมุน 90°
    ให้อ่านจากล่างขึ้นบน — แต่ละบรรทัดลดขนาดฟอนต์อัตโนมัติให้กว้างไม่เกิน
    max_text_width และถ้าความสูงรวมทุกบรรทัด (= ความกว้างแถบดำหลังหมุน)
    เกิน max_total_height จะบีบ max_size ลงแล้ววาดใหม่ทั้งชุด
    """
    tmp = ImageDraw.Draw(Image.new("1", (4, 4), 0))
    gap = 14  # ระยะห่างระหว่างบรรทัด
    max_size = 36  # ขนาดปกติของข้อความสั้น (ข้อความยาวจะหดลงจากนี้)
    while True:
        fonts = [fit_side_text_font(t, max_text_width, max_size=max_size)[0] for t in lines]
        bboxes = [tmp.textbbox((0, 0), t, font=f) for t, f in zip(lines, fonts)]
        heights = [b[3] - b[1] for b in bboxes]
        total_h = sum(heights) + gap * (len(lines) - 1) + 10
        if total_h <= max_total_height or max_size <= 10:
            break
        max_size -= 2

    tile_w = max(b[2] - b[0] for b in bboxes) + 10
    tile = Image.new("1", (tile_w, total_h), 0)  # พื้นดำ
    td = ImageDraw.Draw(tile)
    y = 5
    for t, f, b, h in zip(lines, fonts, bboxes, heights):
        w = b[2] - b[0]
        td.text(((tile_w - w) // 2 - b[0], y - b[1]), t, font=f, fill=1)  # ตัวขาว
        y += h + gap
    return tile.rotate(90, expand=True)  # หมุนให้อ่านจากล่างขึ้นบน


def render_label_bitmap(name: str, tambon: str, house_moo: str, number: str) -> Image.Image:
    """
    ป้าย: แถบดำซ้ายแสดงบ้านเลขที่-หมู่ ต่อด้วยตำบล (เช่น "123/45 หมู่ 3 บ้านกาด")
    ไม่แสดงชื่อเจ้าของบ้านแล้ว — ยกเว้นชื่อที่มีคำว่า "แพมเพิส" (จุดเก็บแพมเพิส)
    จะแสดงเป็นบรรทัดบนเหนือที่อยู่
    โซนขวา: บาร์โค้ด + เลข number
    """
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)

    # --- แถบดำซ้าย ---
    d.rectangle([0, 0, BAND_W - 1, H - 1], fill=0)  # 0 = ดำ

    # --- ข้อความแนวตั้งในแถบดำ (ขาวบนดำ): [ชื่อ เฉพาะแพมเพิส] / บ้านเลขที่-หมู่-ตำบล ---
    # ถ้าบรรทัดไหนว่าง (เช่น ป้าย sticker_text พิเศษ) จะเหลือแค่บรรทัดที่มีข้อมูล
    # ข้อความยาวเกินความยาวแถบ ฟอนต์จะหดเองเฉพาะบรรทัดนั้น (ดู render_band_tile)
    if "แพมเพิส" not in name:
        name = ""
    address = " ".join(t for t in (house_moo, tambon) if t)
    lines = [t for t in (name, address) if t]
    max_text_width = H - 20      # เผื่อขอบบน-ล่างของแถบดำข้างละ ~10px
    max_total_height = BAND_W - 16  # ทุกบรรทัดรวมกันต้องไม่ล้นความกว้างแถบดำ
    tile = render_band_tile(lines, max_text_width, max_total_height)
    img.paste(tile, ((BAND_W - tile.width) // 2, (H - tile.height) // 2))

    # --- เลขใต้บาร์โค้ด (กึ่งกลางโซนขวา) ---
    num_f = load_font(BOLD, 34)
    rcx = (BAND_W + W) // 2
    draw_tracked(d, (rcx, 292), number, num_f, tracking=6, fill=0, align="center")

    # (พื้นที่บาร์โค้ดเว้นไว้ ให้คำสั่ง BARCODE วาดทับ)
    return img


def build_tspl(name: str, tambon: str, house_moo: str, number: str, barcode_data: str, quantity: int = 1) -> bytes:
    img = render_label_bitmap(name, tambon, house_moo, number)
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP {GAP_MM} mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    bc = (f'BARCODE {BAR_X},{BAR_Y},"128",{BAR_HEIGHT},0,0,'
          f'{BAR_NARROW},{BAR_NARROW},"{barcode_data}"\r\n').encode()
    tail = f"PRINT 1,{quantity}\r\n".encode()
    return head + bmp + bc + tail


def build_divider_tspl(number: str) -> bytes:
    """TSPL job ของ label "คั่น" (พื้นดำ+เลข+ลูกศรชี้ลง) 1 ใบ — ใช้แทรกก่อนป้ายบาร์โค้ด
    ของแต่ละ user_id ตอนพิมพ์หลายรายการรวดเดียว (ดู render_divider_label / print_sticker_batch)
    ใช้ mode "1" ตรงจาก render_divider_label เลย ไม่ต้องแปลง — โครงสร้างเหมือน build_tspl
    ทุกอย่าง ต่างแค่ไม่มี BARCODE command และพิมพ์แค่ 1 ใบเสมอ (ไม่รับ quantity)"""
    img = render_divider_label(number)
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP {GAP_MM} mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    tail = b"PRINT 1,1\r\n"
    return head + bmp + tail


# ============== MOCK MODE (ไม่มีเครื่องพิมพ์จริง) ==============
def _draw_mock_barcode(img: Image.Image, data: str) -> bool:
    """วาดแท่งบาร์โค้ด Code128 ทับ img ที่ตำแหน่ง/สเกลเดียวกับที่เครื่องพิมพ์จะวาดจริง
    (ต้องมี python-barcode — `pip install python-barcode`) คืน True ถ้าวาดสำเร็จ"""
    try:
        from barcode import Code128
    except ImportError:
        return False
    modules = Code128(data).build()[0]  # สตริง '1'/'0' ทีละโมดูล (1=แท่งดำ)
    d = ImageDraw.Draw(img)
    x = BAR_X
    for bit in modules:
        if bit == "1":
            d.rectangle([x, BAR_Y, x + BAR_NARROW - 1, BAR_Y + BAR_HEIGHT - 1], fill=0)
        x += BAR_NARROW
    return True


def _draw_arrow_down(d: ImageDraw.ImageDraw, cx: int, y0: int, y1: int,
                      shaft_w: int = 6, head_w: int = 26, head_h: int = 20, fill=1):
    """วาดลูกศรชี้ลงแนวตั้ง (เส้น + หัวลูกศรสามเหลี่ยม) จาก y0 ถึง y1 กึ่งกลางที่ x=cx
    วาดเป็นเวกเตอร์เอง ไม่พึ่ง glyph ลูกศรของฟอนต์ (NotoSansThai ไม่มีตัวอักษร ↓/▼)"""
    d.line([cx, y0, cx, y1 - head_h], fill=fill, width=shaft_w)
    d.polygon([(cx - head_w // 2, y1 - head_h), (cx + head_w // 2, y1 - head_h), (cx, y1)], fill=fill)


def _draw_dashed_line(d: ImageDraw.ImageDraw, y: int, x0: int, x1: int,
                       dash: int = 20, gap: int = 12, width: int = 3, fill=1):
    """เส้นประแนวนอนยาวๆ จาก x0 ถึง x1 ที่ความสูง y"""
    x = x0
    while x < x1:
        d.line([x, y, min(x + dash, x1), y], fill=fill, width=width)
        x += dash + gap


def render_divider_label(number: str, quantity: int = 1) -> Image.Image:
    """label "คั่น" ที่จะแทรกก่อนป้ายบาร์โค้ดของ user_id แต่ละคน ตอนปริ้นหลายรายการ
    รวดเดียว — พื้นดำเต็มแผ่น มีเส้นประยาวด้านบน แล้วตัวเลข/รหัสสีขาวตัวใหญ่กึ่งกลาง
    ตามด้วยลูกศรชี้ลงเปล่าๆ (ไม่มีคำอธิบาย) บอกว่าบาร์โค้ดของคนนี้อยู่ "ด้านล่าง" ป้ายนี้
    (ตามลำดับที่ม้วนจะพิมพ์ออกมาจริง) ไว้ให้มองปราดเดียวรู้ว่าจากตรงนี้ไปคือของใคร

    ใช้ mode "1" (1-bit) แบบเดียวกับ render_label_bitmap เป๊ะ (bg fill=0, ลาย/ตัวอักษร
    fill=1) เพื่อให้เอาไปสร้าง TSPL BITMAP สำหรับพิมพ์จริงได้ตรงๆ ไม่ต้องแปลงโหมดเพิ่ม
    (ใช้พรีวิว mock ก็ได้เหมือนกัน แค่ .convert("L") ตอนเอาไปต่อภาพ)"""
    img = Image.new("1", (W, H), 0)  # พื้นดำเต็มแผ่น (0 = ดำ ตามธรรมเนียมเดียวกับแถบดำใน render_band_tile)
    d = ImageDraw.Draw(img)

    _draw_dashed_line(d, 26, 40, W - 40, fill=1)

    # เน้นตัวเลขให้ใหญ่สุดเท่าที่พื้นที่จะให้ — ลูกศรด้านล่างแค่ไอคอนเล็กๆ ไม่แย่งซีน
    f_id, _ = fit_side_text_font(number, max_width=W - 50, max_size=170, min_size=40, step=4)
    bbox = d.textbbox((0, 0), number, font=f_id)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    arrow_h = 40

    # จัดกึ่งกลางทั้งก้อน (เลข + ลูกศร) ในพื้นที่ใต้เส้นประ ไม่ให้ค้างโล่งด้านล่าง
    zone_top, zone_bottom = 55, H - 16
    content_h = th + 20 + arrow_h
    id_top = zone_top + max(0, (zone_bottom - zone_top - content_h) // 2)
    d.text(((W - tw) / 2 - bbox[0], id_top - bbox[1]), number, font=f_id, fill=1)
    id_bottom = id_top + th

    arrow_top = id_bottom + 20
    arrow_bottom = arrow_top + arrow_h
    if arrow_bottom <= H - 10:
        _draw_arrow_down(d, W // 2, arrow_top, arrow_bottom, shaft_w=4, head_w=16, head_h=12, fill=1)
    return img


def _stack_label_tiles(tiles: list, boundary_gaps: set | None = None,
                        boundary_captions: dict | None = None) -> Image.Image:
    """เรียง tile (Image mode 'L' กว้าง W เท่ากัน) ต่อกันแนวตั้งเหมือนม้วนสติกเกอร์จริง
    คั่นแต่ละใบด้วยแถบเทา + เส้นประแทนรอย gap/ตัดของม้วน ระยะห่างเท่ากับ GAP_MM
    ที่ส่งให้เครื่องพิมพ์จริง (ใช้ได้ทั้งกรณี label เดียวกันซ้ำ quantity รอบ และกรณี
    label คนละแบบ/คนละ user_id เรียงต่อกันแบบ batch)

    boundary_gaps: set ของ index ช่อง gap (ช่องหลัง tile ตำแหน่ง i) ที่เป็น "รอยต่อ
    ระหว่างคนละคน" — ช่องพวกนี้จะวาดเด่นกว่าปกติ (แถบสูง/เข้มกว่า + เส้นประหนา +
    ข้อความ "ตัดตรงนี้") ไว้บอกจุดตัดที่สำคัญจริงๆ เวลาต้องแยกกองของแต่ละคน ส่วนช่อง gap
    อื่นๆ (ระหว่างป้ายซ้ำใบเดิม/ระหว่างป้ายคั่นกับบาร์โค้ดใบแรกของคนเดียวกัน) จะวาด
    เป็นเส้นบางๆ ตามปกติ — ไม่เน้น เพราะไม่ใช่จุดที่ต้องแยกกอง
    boundary_captions: dict {gap_index: ข้อความ} ใส่ข้อความกำกับเพิ่มใต้ "ตัดตรงนี้"
    เช่น ชื่อ user_id คนถัดไป (ไม่บังคับ)"""
    if len(tiles) == 1:
        return tiles[0]
    boundary_gaps = boundary_gaps or set()
    boundary_captions = boundary_captions or {}
    gap_px = round(GAP_MM / 25.4 * 300)  # 300 dpi เท่ากับที่ป้ายจริงใช้
    big_gap_px = 70  # ช่อง gap ที่จุดตัดสำคัญ วาดใหญ่ขึ้นเพื่อให้เห็นชัด (ของตกแต่งพรีวิว
    # เท่านั้น ไม่ใช่ระยะจริงที่ส่งเครื่องพิมพ์ — เครื่องพิมพ์จริงยังใช้ gap 2mm เท่ากันหมด)

    heights = [t.height for t in tiles]
    gaps = [big_gap_px if i in boundary_gaps else gap_px for i in range(len(tiles) - 1)]
    total_h = sum(heights) + sum(gaps)
    sheet = Image.new("L", (W, total_h), 255)
    d = ImageDraw.Draw(sheet)
    f_cut = load_font(BOLD, 26)

    y = 0
    for i, t in enumerate(tiles):
        sheet.paste(t, (0, y))
        y += t.height
        if i < len(tiles) - 1:
            gh = gaps[i]
            gy0, gy1 = y, y + gh
            if i in boundary_gaps:
                d.rectangle([0, gy0, W, gy1], fill=225)
                dash_y = (gy0 + gy1) // 2
                x = 0
                while x < W:  # เส้นประหนา = จุดตัดสำคัญ แยกกองคนละคน
                    d.line([x, dash_y, min(x + 18, W), dash_y], fill=20, width=4)
                    x += 28
                label = boundary_captions.get(i, "ตัดตรงนี้ — เริ่มคนถัดไป")
                lb = d.textbbox((0, 0), label, font=f_cut)
                lw = lb[2] - lb[0]
                d.text(((W - lw) / 2 - lb[0], gy0 + 6 - lb[1]), label, font=f_cut, fill=20)
            else:
                d.rectangle([0, gy0, W, gy1], fill=210)  # แถบเทาอ่อน = ช่อง gap ของม้วน
                dash_y = (gy0 + gy1) // 2
                x = 0
                while x < W:  # เส้นประบาง = รอยตัด/perforation ปกติ
                    d.line([x, dash_y, min(x + 14, W), dash_y], fill=130, width=2)
                    x += 22
            y = gy1
    return sheet


def build_mock_sheet(name: str, tambon: str, house_moo: str, number: str, barcode_data: str,
                      quantity: int = 1):
    """ต่อป้าย quantity ใบเรียงต่อกันแนวตั้งเหมือนม้วนสติกเกอร์จริง (แต่ละใบหน้าตา
    เหมือนกันเป๊ะ เพราะเครื่องพิมพ์จริงก็พิมพ์จากบิตแมปเดียวกันซ้ำ quantity รอบจาก
    คำสั่ง TSPL เดียว "PRINT 1,{quantity}")
    คืนค่า (Image ของทั้งม้วน, มีบาร์โค้ดวาดสำเร็จไหม)"""
    label = render_label_bitmap(name, tambon, house_moo, number).convert("L")
    have_barcode = _draw_mock_barcode(label, barcode_data)
    sheet = _stack_label_tiles([label] * max(1, quantity))
    return sheet, have_barcode


def _resolve_item_fields(item: dict):
    """แปลง item dict ให้เป็น (id_text, name, tambon, house_moo, quantity) แบบเดียวกัน
    ไม่ว่าจะมาจาก 2 รูปแบบที่ต่างกัน:
      1) แบบทดสอบเอง (preview_batch.py เดิม): {user_id, name, house, moo, soi, tambon, quantity}
      2) แบบที่ได้จริงจาก SmartPay API POST /print/sticker-batch-by-key:
         {code_value, user_id, name, house_no, moo, tambon, label_house, sticker_text?, quantity}
         — ถ้ามี sticker_text ให้พิมพ์แค่ข้อความนั้นบรรทัดเดียว ห้ามพิมพ์ชื่อ/ที่อยู่/header
         (ใช้กับจุดเก็บแพมเพิส ตามที่ backend ระบุไว้ใน API ตอบกลับ)"""
    id_text = str(item.get("code_value") or item.get("user_id"))
    qty = max(1, int(item.get("quantity", 1)))

    sticker_text = item.get("sticker_text")
    if sticker_text:
        # name="" -> ไม่มี header, tambon ช่องเดียวโชว์ข้อความพิเศษ, ไม่มีบรรทัดบ้านเลขที่
        return id_text, "", sticker_text, "", qty

    if "label_house" in item:  # มาจาก API จริง — มีฟิลด์แยกให้ครบ ไม่ต้องประกอบเอง
        house_no = item.get("house_no", "")
        moo = item.get("moo", "")
        tambon = item.get("tambon", "")
        # บั๊กที่เจอจากข้อมูลจริง: บ้านที่ไม่มีเลขที่จริง backend จะเอารหัสสมาชิก
        # (code_value/user_id) มาใส่แทนเลขบ้านใน house_no/label_house เช่น
        # house_no="M-1007" ทั้งที่ไม่มีเลขบ้านจริง — เจอรหัสตัวเองแทน ให้ถือว่า
        # "ไม่มี" แทน (ไม่ใช่บั๊กฝั่งนี้ แต่แก้ที่ backend ไม่ได้ เลยกันไว้ที่ป้ายแทน)
        if house_no and house_no == id_text:
            house_no = "ไม่มี"
        house_moo = build_house_moo_text(house=house_no, moo=moo) if (house_no or moo) else ""
        return id_text, item.get("name", ""), tambon, house_moo, qty

    house_moo = build_house_moo_text(house=item.get("house", ""), moo=item.get("moo", ""),
                                      soi=item.get("soi", ""))
    return id_text, item.get("name", ""), item.get("tambon", ""), house_moo, qty


def build_mock_batch_sheet(items: list):
    """จำลองการปริ้นหลายรายการรวดเดียวบนม้วนเดียว: ต่อ 1 รายการใน items จะมี
    label คั่น (พื้นดำ+id+ลูกศรชี้ลง) 1 ใบ ตามด้วยป้ายบาร์โค้ดจริง quantity ใบ
    แล้วขึ้นรายการถัดไปต่อทันที (คั่น -> บาร์โค้ด x quantity -> คั่น -> บาร์โค้ด x quantity)
    จุดต่อระหว่างรายการ (ก่อนป้ายคั่นของคนถัดไป) จะถูกวาดเป็นจุดตัดเด่น พร้อมข้อความ
    "ตัดตรงนี้" กำกับ id ที่กำลังจะเริ่ม ไว้ให้แยกกองแต่ละคนได้ง่าย
    items: list ของ dict รูปแบบใดรูปแบบหนึ่งที่ _resolve_item_fields() รองรับ
    คืนค่า (Image ของทั้งม้วน, บาร์โค้ดวาดสำเร็จครบทุกรายการไหม)"""
    tiles = []
    boundary_gaps = set()
    boundary_captions = {}
    have_barcode_all = True
    for item in items:
        id_text, name, tambon, house_moo, qty = _resolve_item_fields(item)

        if tiles:  # ไม่ใช่รายการแรก -> gap ก่อนป้ายคั่นนี้คือจุดตัดสำคัญ (เริ่มคนใหม่)
            boundary_gaps.add(len(tiles) - 1)
            boundary_captions[len(tiles) - 1] = f"ตัดตรงนี้ — เริ่ม {id_text}"

        tiles.append(render_divider_label(id_text, quantity=qty).convert("L"))
        label = render_label_bitmap(name, tambon, house_moo, id_text).convert("L")
        have_barcode_all = _draw_mock_barcode(label, id_text) and have_barcode_all
        tiles.extend([label] * qty)

    sheet = _stack_label_tiles(tiles, boundary_gaps=boundary_gaps,
                                boundary_captions=boundary_captions)
    return sheet, have_barcode_all


def save_mock_preview(name: str, tambon: str, house_moo: str, number: str, barcode_data: str,
                       quantity: int = 1) -> str:
    """สร้างภาพป้าย quantity ใบเรียงกันแบบม้วนจริง แล้วเซฟเป็น PNG ไว้ดู — ใช้ตอน
    MOCK_PRINT เท่านั้น เซฟทั้งไฟล์ล่าสุด (latest.png) และไฟล์แยกตาม user_id/เวลา"""
    import time

    sheet, have_barcode = build_mock_sheet(name, tambon, house_moo, number, barcode_data, quantity)
    scale = 2 if quantity <= 6 else 1  # quantity เยอะแล้วขยาย 2x จะได้ไฟล์ใหญ่เกินจำเป็น
    if scale != 1:
        sheet = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)

    os.makedirs(PREVIEW_DIR, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(number))
    qty_suffix = f"_x{quantity}" if quantity > 1 else ""
    out_path = os.path.join(PREVIEW_DIR, f"{stamp}_{safe_id}{qty_suffix}.png")
    sheet.save(out_path)
    sheet.save(os.path.join(PREVIEW_DIR, "latest.png"))  # เผื่อจะเปิดดูอันล่าสุดไวๆ

    if not have_barcode:
        print("*** MOCK: ไม่มี python-barcode — พรีวิวจะไม่มีแท่งบาร์โค้ดให้ดู "
              "(ติดตั้งด้วย `pip install python-barcode` ถ้าอยากเห็นบาร์โค้ดจริงด้วย)")
    return out_path


# ============== ส่วนเชื่อมต่อ USB ==============
# บน Windows pyusb ต้องมี libusb-1.0.dll เป็น backend — ใช้ DLL ที่มากับแพ็กเกจ
# libusb-package (pip install libusb-package) จะได้ไม่ต้องก๊อป dll เข้า System32 เอง
# บน macOS/Linux ที่ลง libusb ผ่าน brew/apt แล้ว จะคืน None แล้วใช้ backend default
def _get_backend():
    try:
        import libusb_package
        return libusb_package.get_libusb1_backend()
    except Exception:
        return None


_USB_BACKEND = _get_backend()


def _usb_find(**kwargs):
    """ครอบ usb.core.find ให้แนบ backend ของ libusb-package อัตโนมัติ (ถ้ามี)"""
    return usb.core.find(backend=_USB_BACKEND, **kwargs)


def _safe_string(dev, index):
    try:
        return (usb.util.get_string(dev, index) or "").upper()
    except Exception:
        return ""


def _is_printer(dev):
    try:
        if dev.bDeviceClass == 7:
            return True
        for cfg in dev:
            for intf in cfg:
                if intf.bInterfaceClass == 7:
                    return True
    except Exception:
        pass
    return False


def _describe(dev):
    manu = _safe_string(dev, dev.iManufacturer)
    prod = _safe_string(dev, dev.iProduct)
    tag = " [printer]" if _is_printer(dev) else ""
    return f"VID={hex(dev.idVendor)} PID={hex(dev.idProduct)} {manu} {prod}{tag}".strip()


def dump_devices(devs):
    print("USB devices ที่เห็น:")
    for d in devs:
        print(f"  {_describe(d)}")


def find_printer():
    """
    เลือกเครื่องบาร์โค้ด TSC ในเครื่องที่ต่อปริ้นหลายตัว (เอกสาร + บาร์โค้ด) โดย:
      1) ถ้า pin VID/PID ไว้ (env TSC_VID/TSC_PID) → ใช้ตัวนั้นเป๊ะ แม่นสุด
      2) ไม่งั้นหาเครื่องที่ชื่อ USB มี "TSC"/"TE310" → ข้ามเครื่องปริ้นเอกสารทิ้ง
         เจอตัวเดียวใช้เลย, เจอหลายตัวให้ pin VID/PID (ไม่เดามั่ว)
      3) fallback สุดท้าย: อุปกรณ์คลาส printer ตัวเดียวในเครื่องเท่านั้น
    ทุกกรณีจะ log ว่าเลือกตัวไหน เพื่อให้ยืนยันได้ว่าไม่ได้ไปคว้าเครื่องเอกสาร
    """
    # 1) pin ด้วย VID/PID — แม่นที่สุด ไม่มีทางหยิบผิดตัว
    if VENDOR_ID and PRODUCT_ID:
        dev = _usb_find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev:
            print(f"[print-server] ใช้เครื่องที่ pin ไว้: {_describe(dev)}")
            return dev
        print(f"*** pin ไว้ที่ VID={hex(VENDOR_ID)} PID={hex(PRODUCT_ID)} "
              f"แต่หาไม่เจอ — เช็คสาย USB / ค่าที่ตั้ง TSC_VID,TSC_PID")
        return None

    candidates = list(_usb_find(find_all=True))

    # 2) หาเครื่อง TSC จาก Vendor ID หรือชื่อ — เครื่องปริ้นเอกสาร (Brother ฯลฯ)
    #    VID/ชื่อไม่ตรง เลยถูกข้ามอัตโนมัติ
    tsc = [d for d in candidates
           if d.idVendor in TSC_VENDOR_IDS
           or "TSC" in _safe_string(d, d.iManufacturer)
           or "TSC" in _safe_string(d, d.iProduct)
           or "TE310" in _safe_string(d, d.iProduct)]
    if len(tsc) == 1:
        print(f"[print-server] เจอเครื่องบาร์โค้ด: {_describe(tsc[0])}")
        return tsc[0]
    if len(tsc) > 1:
        print("*** เจอเครื่อง TSC มากกว่า 1 ตัว — ต้อง pin ด้วย env TSC_VID/TSC_PID:")
        for d in tsc:
            print(f"    {_describe(d)}")
        return None

    # 3) fallback: printer ตัวเดียวในเครื่องเท่านั้น (มีหลายตัว = ไม่เดา ให้ pin เอา)
    printers = [d for d in candidates if _is_printer(d)]
    if len(printers) == 1:
        print(f"[print-server] เจอเครื่องปริ้นตัวเดียว ใช้ตัวนี้: {_describe(printers[0])}")
        return printers[0]
    if len(printers) > 1:
        print("*** เจออุปกรณ์คลาส printer หลายตัว แต่ไม่มีตัวไหนชื่อ TSC —")
        print("*** ให้ดู VID/PID ของเครื่องบาร์โค้ดด้วย `--list` แล้ว pin ผ่าน TSC_VID/TSC_PID:")
        for d in printers:
            print(f"    {_describe(d)}")
        return None
    dump_devices(candidates)
    return None


def send(dev, data: bytes):
    # (Windows) detach kernel driver ไม่รองรับ — จับ error ทิ้งได้เลย
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass

    try:
        dev.set_configuration()
    except usb.core.USBError as e:
        # บางครั้งอุปกรณ์ถูกตั้ง config ไว้แล้ว การตั้งซ้ำจะเตือน — ไปต่อได้
        print(f"[print-server] set_configuration เตือน (ข้ามได้): {e}")

    # หา bulk OUT endpoint จาก "ทุก" interface/config ไม่ยึดแค่ (0,0)
    # เพราะบางเครื่อง/บนไดรเวอร์ WinUSB endpoint อาจไม่ได้อยู่ interface แรก
    ep_out = None
    for cfg in dev:
        for intf in cfg:
            ep = usb.util.find_descriptor(
                intf,
                custom_match=lambda e:
                    usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
            )
            if ep is not None:
                ep_out = ep
                break
        if ep_out is not None:
            break

    if ep_out is None:
        seen = []
        for cfg in dev:
            for intf in cfg:
                for e in intf:
                    direction = "OUT" if usb.util.endpoint_direction(
                        e.bEndpointAddress) == usb.util.ENDPOINT_OUT else "IN"
                    seen.append(f"{hex(e.bEndpointAddress)}({direction})")
        raise RuntimeError(f"ไม่เจอ bulk OUT endpoint — endpoints ที่เห็น: {seen or 'ไม่มีเลย'}")

    written = ep_out.write(data, timeout=10000)
    usb.util.dispose_resources(dev)
    return written


def print_label(user_id: str, house: str, moo: str, soi: str = "", name: str = "",
                tambon: str = "", quantity: int = 1):
    """ประกอบป้ายจาก user_id/name/house/moo/soi/tambon แล้วส่งไปเครื่องพิมพ์ผ่าน USB จริง
    (หรือถ้า MOCK_PRINT เปิดอยู่ — ข้าม USB ทั้งหมด เซฟรูปพรีวิวแทน)
    คืนค่า (จำนวน bytes ที่ "ส่ง"/จำลองว่าส่ง, path ไฟล์พรีวิว หรือ None ถ้าพิมพ์จริง)"""
    house_moo = build_house_moo_text(house=house, moo=moo, soi=soi)
    tspl = build_tspl(name=name, tambon=tambon, house_moo=house_moo, number=user_id,
                      barcode_data=user_id, quantity=quantity)

    if MOCK_PRINT:
        preview_path = save_mock_preview(name=name, tambon=tambon, house_moo=house_moo,
                                          number=user_id, barcode_data=user_id, quantity=quantity)
        print(f"[print-server] *** MOCK MODE — ไม่ได้ส่งไปเครื่องพิมพ์จริง (ไม่มีเครื่องต่ออยู่) "
              f"— จะออก {quantity} ใบเหมือนกันหมด (ใบเดียวกัน ซ้ำ {quantity} รอบในคำสั่งพิมพ์เดียว)")
        print(f"[print-server] เซฟพรีวิวไว้ที่: {preview_path}")
        return len(tspl), preview_path

    dev = find_printer()
    if dev is None:
        raise RuntimeError("หาเครื่อง TSC ไม่เจอ — เช็คสาย USB / system_profiler SPUSBDataType | grep -A 12 -i tsc")
    return send(dev, tspl), None


# ============== SmartPay API (ดึงรายชื่อบ้านทั้งชุด + บันทึกประวัติพิมพ์) ==============
# ตาม README-sticker-batch-api.md ที่ทีม backend ส่งมา — print server ฝั่งนี้เป็น
# "ทีมฮาร์ดแวร์" ที่เอกสารพูดถึง ใช้ X-Print-Key ดึงรายชื่อเอง แทนที่จะให้เบราว์เซอร์
# ยิง POST /print ทีละบ้าน (แบบที่หน้าเว็บทำอยู่ตอนนี้) — เร็วกว่าและไม่ต้องพึ่งเบราว์เซอร์เปิดค้าง
class RemoteAPIError(Exception):
    """error จากการเรียก SmartPay API — status ตรงกับ HTTP status ที่ API ตอบกลับมาจริง
    (หรือ 0 ถ้าต่อเน็ตไม่ได้เลย ยังไปไม่ถึง server)"""
    def __init__(self, status: int, message: str):
        super().__init__(f"[{status}] {message}")
        self.status = status
        self.message = message


def _call_smartpay_api(path: str, body: dict, headers: dict, timeout: int = 30) -> dict:
    url = f"{SMARTPAY_API_BASE}{path}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode("utf-8"))
            # backend เป็น FastAPI ตอบ error เป็น {"detail": "..."} เป็นหลัก แต่เผื่อ
            # รูปแบบอื่นไว้ด้วย ({"error":...} / {"message":...}) กันเหนียว
            msg = payload.get("detail") or payload.get("error") or payload.get("message") or str(payload)
        except Exception:
            msg = e.reason
        raise RemoteAPIError(e.code, msg) from e
    except urllib.error.URLError as e:
        raise RemoteAPIError(0, f"เชื่อมต่อ SmartPay API ไม่ได้: {e.reason}") from e


def fetch_sticker_batch(filters: dict) -> dict:
    """ดึงรายชื่อบ้านที่จะพิมพ์ทั้งชุด — POST /print/sticker-batch-by-key (ยืนยันตัวตนด้วย
    X-Print-Key) filters รองรับ field เดียวกับที่เอกสารระบุ: from_user_id, to_user_id,
    moo, tambon, user_ids, paid_only, quantity — ทุกช่องไม่บังคับ"""
    if not SMARTPAY_PRINT_KEY:
        raise RemoteAPIError(503, "ยังไม่ได้ตั้งค่า SMARTPAY_PRINT_KEY (env var) บนเครื่องนี้ — ขอคีย์จากผู้ดูแลระบบ")
    return _call_smartpay_api("/print/sticker-batch-by-key", filters,
                               {"X-Print-Key": SMARTPAY_PRINT_KEY})


def log_sticker_batch(printed_items: list):
    """บันทึกว่าพิมพ์บ้านไหนไปแล้วกี่ใบ — POST /print/sticker-batch/log (ยังผูกกับ JWT
    ของแอดมินอยู่ตามเอกสาร) ส่งเฉพาะบ้านที่พิมพ์ออกมาจริงเท่านั้น
    ถ้าไม่ได้ตั้งค่า SMARTPAY_ADMIN_JWT ไว้บนเครื่องนี้ จะข้ามขั้นตอนนี้ไปเฉยๆ (คืน None)
    — ต้องไปกดบันทึกที่หน้าเว็บแอดมินเองแทน"""
    if not SMARTPAY_ADMIN_JWT or not printed_items:
        return None
    return _call_smartpay_api("/print/sticker-batch/log", {"items": printed_items},
                               {"Authorization": f"Bearer {SMARTPAY_ADMIN_JWT}"})


def print_sticker_batch(filters: dict) -> dict:
    """ดึงรายชื่อบ้านจาก SmartPay API ตามเงื่อนไขใน filters แล้วพิมพ์ทั้งชุดรวดเดียว —
    ต่อ 1 บ้าน: label คั่น (พื้นดำ+id+ลูกศร) 1 ใบ ตามด้วยบาร์โค้ดจริง quantity ใบ แล้ว
    ขึ้นบ้านถัดไปต่อทันที (เหมือน build_mock_batch_sheet แต่พิมพ์ USB จริง)

    ถ้า MOCK_PRINT เปิดอยู่ จะจำลองว่าพิมพ์สำเร็จทั้งหมด แล้วเซฟรูปพรีวิวทั้งชุดไว้ดูแทน
    ถ้าพิมพ์จริงแล้วบ้านไหน "พิมพ์ไม่สำเร็จ" (USB error) จะหยุดทั้งชุดทันที ไม่ไล่พิมพ์ต่อ
    (พฤติกรรมเดียวกับที่หน้าเว็บทำอยู่ตอนนี้ ตามข้อ 3 ในเอกสาร) แล้วรายงานว่าพิมพ์ไปถึง
    บ้านไหนแล้วบ้าง — พิมพ์เสร็จ (บ้านไหนก็ตามที่สำเร็จจริง) จะเรียกบันทึกประวัติให้อัตโนมัติ
    ถ้ามีการตั้งค่า SMARTPAY_ADMIN_JWT ไว้"""
    fetched = fetch_sticker_batch(filters)
    items = fetched.get("items", [])

    printed = []
    failed_user_id = None
    preview_path = None

    if MOCK_PRINT:
        import time

        sheet, have_barcode = build_mock_batch_sheet(items)
        os.makedirs(PREVIEW_DIR, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        preview_path = os.path.join(PREVIEW_DIR, f"{stamp}_batch_{len(items)}houses.png")
        sheet.save(preview_path)
        sheet.save(os.path.join(PREVIEW_DIR, "latest.png"))
        if not have_barcode:
            print("*** MOCK: ไม่มี python-barcode — พรีวิวจะไม่มีแท่งบาร์โค้ดให้ดู "
                  "(ติดตั้งด้วย `pip install python-barcode`)")
        printed = [{"user_id": _resolve_item_fields(it)[0], "quantity": _resolve_item_fields(it)[4]}
                   for it in items]
        print(f"[print-server] *** MOCK MODE — จำลองพิมพ์ {len(items)} บ้านสำเร็จทั้งหมด "
              f"เซฟพรีวิวไว้ที่: {preview_path}")
    else:
        dev = find_printer()
        if dev is None:
            raise RuntimeError("หาเครื่อง TSC ไม่เจอ — เช็คสาย USB / system_profiler SPUSBDataType | grep -A 12 -i tsc")
        for item in items:
            id_text, name, tambon, house_moo, qty = _resolve_item_fields(item)
            # หมายเหตุลำดับ: ส่ง TSPL "คั่น" ก่อนแล้ว "บาร์โค้ด" ตามหลัง (ในโค้ด) ควร
            # จะให้ label คั่นพิมพ์ออกมาก่อนตามลำดับ แต่ทดสอบพิมพ์จริงกับเครื่อง TSC
            # แล้วพบว่าเครื่องพิมพ์ออกมา "สลับ" กัน (สองบล็อก PRINT ที่ส่งต่อกันในสตรีม
            # เดียว พิมพ์ออกมากลับด้าน) ยืนยันซ้ำ 2 รอบด้วยรูปถ่ายจริง — เลย "สลับลำดับ
            # การส่ง" ในโค้ดเพื่อชดเชย: ส่งบาร์โค้ดก่อน แล้วค่อยส่งคั่นตามหลัง ผลลัพธ์
            # ที่ออกมาจริงบนกระดาษถึงจะได้ คั่น -> บาร์โค้ด ตามที่ต้องการ
            tspl = build_tspl(name=name, tambon=tambon, house_moo=house_moo, number=id_text,
                               barcode_data=id_text, quantity=qty) + build_divider_tspl(id_text)
            try:
                send(dev, tspl)
            except (usb.core.USBError, RuntimeError) as e:
                print(f"[print-server] *** พิมพ์ {id_text} ไม่สำเร็จ: {e} — หยุดทั้งชุดทันที "
                      f"(พิมพ์ไปแล้ว {len(printed)}/{len(items)} บ้านก่อนหน้านี้)")
                failed_user_id = id_text
                break
            printed.append({"user_id": id_text, "quantity": qty})
            print(f"[print-server] พิมพ์ {id_text} x{qty} สำเร็จ ({len(printed)}/{len(items)})")

    log_result = None
    if printed:
        try:
            log_result = log_sticker_batch(printed)
        except RemoteAPIError as e:
            print(f"*** บันทึกประวัติพิมพ์ไม่สำเร็จ [{e.status}] {e.message} — พิมพ์ไปแล้วตามปกติ "
                  f"แค่บันทึกไม่ผ่าน ต้องไปกดบันทึกที่หน้าเว็บแอดมินเองสำหรับบ้านที่พิมพ์ไปแล้ว")
            log_result = {"error": e.message, "status": e.status}

    return {
        "fetched": len(items),
        "printed": printed,
        "failed_user_id": failed_user_id,
        "total_labels_printed": sum(p["quantity"] for p in printed),
        "mock": MOCK_PRINT,
        "preview_file": preview_path,
        "log_result": log_result,
    }


# ============== HTTP Server (รับคำสั่งพิมพ์จากเว็บแอป) ==============
class PrintRequestHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        # เว็บแอป SmartPay รันอยู่คนละ origin (เว็บไซต์จริง) แต่เครื่องนี้ต้องรับ
        # คำขอจาก origin นั้นได้ — เปิดกว้างไว้เพราะ server นี้ฟังแค่ localhost/LAN
        # ภายในสำนักงานเท่านั้น ไม่ได้เปิดออกอินเทอร์เน็ต
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome/Edge รุ่นใหม่ (Private Network Access) จะยิง preflight OPTIONS
        # แนบ header "Access-Control-Request-Private-Network: true" มาด้วยทุกครั้ง
        # ที่หน้าเว็บ HTTPS (โดเมนจริง) พยายามเรียก http://localhost หรือ IP วง LAN
        # ถ้า server ไม่ตอบ header นี้กลับไป เบราว์เซอร์จะบล็อก request เงียบๆ (fetch
        # ล้มเหลวแบบไม่มี error ชัดเจน) ตรงกับอาการ "เชื่อมต่อโปรแกรมเครื่องพิมพ์ไม่ได้"
        # ที่เว็บแอปเจอ ทั้งที่ server รันอยู่จริงและ /health เข้าถึงได้ปกติจาก curl
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[print-server] {self.address_string()} - {fmt % args}")

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        self._send_json(404, {"error": "not found"})

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self):
        if self.path == "/print":
            self._handle_print()
        elif self.path == "/print-batch-by-key":
            self._handle_print_batch_by_key()
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_print_batch_by_key(self):
        """POST /print-batch-by-key — เวอร์ชันฝั่งฮาร์ดแวร์ของ workflow ในเอกสาร
        README-sticker-batch-api.md: รับเงื่อนไข (from_user_id/to_user_id/moo/tambon/
        user_ids/paid_only/quantity) เดียวกับที่ POST /print/sticker-batch-by-key ของ
        SmartPay รับ แล้วให้ print server เป็นคนไปดึงรายชื่อ (ด้วย X-Print-Key ที่ตั้งไว้
        ในเครื่อง) + พิมพ์ทั้งชุดเองเลย ไม่ต้องให้เบราว์เซอร์ไล่ยิง /print ทีละบ้าน"""
        try:
            filters = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        print(f"[print-server] /print-batch-by-key เงื่อนไขที่รับมา: {filters}")

        try:
            result = print_sticker_batch(filters)
        except RemoteAPIError as e:
            print(f"[print-server] *** ดึงรายชื่อจาก SmartPay API ไม่สำเร็จ [{e.status}] {e.message}")
            self._send_json(e.status or 502, {"error": e.message})
            return
        except RuntimeError as e:
            print(f"[print-server] *** พิมพ์ไม่สำเร็จ (RuntimeError): {e}")
            self._send_json(503, {"error": str(e)})
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"error": f"{type(e).__name__}: {e}"})
            return

        ok = result["failed_user_id"] is None
        tag = "[MOCK] " if result["mock"] else ""
        print(f"{tag}พิมพ์ batch: {len(result['printed'])}/{result['fetched']} บ้านสำเร็จ "
              f"({result['total_labels_printed']} ใบ)"
              + (f" — หยุดที่ {result['failed_user_id']}" if not ok else ""))
        self._send_json(200 if ok else 502, {"success": ok, **result})

    def _handle_print(self):
        try:
            body = self._read_json_body()
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid JSON body"})
            return

        # log body ดิบไว้ debug — เห็นทันทีว่าเว็บแอปส่ง key อะไรมาจริงๆ
        print(f"[print-server] body ที่รับมา: {body}")

        user_id = body.get("user_id")
        # เว็บแอป/backend แต่ละที่ใช้ key ชื่อไม่เหมือนกัน — รองรับ variant ที่เจอบ่อยไว้หมด
        name = (body.get("name") or body.get("full_name") or body.get("fullname")
                or " ".join(x for x in (body.get("first_name"), body.get("last_name")) if x)
                or "")
        house = body.get("house")
        moo = body.get("moo") or ""
        soi = body.get("soi") or ""
        tambon = body.get("tambon") or ""
        quantity = body.get("quantity", 1)
        # ป้ายจุดเก็บแพมเพิส — backend ส่ง sticker_text มา ให้พิมพ์แค่ข้อความนั้น
        # แทนที่อยู่ (เหมือน _resolve_item_fields ฝั่ง batch)
        sticker_text = body.get("sticker_text") or ""

        # บั๊กที่เจอจากเว็บแอปจริง: บ้านที่ไม่มีเลขที่จริง จะส่ง house มาเป็นรหัส
        # สมาชิก (user_id) เอง เช่น {"user_id":"M-1005","house":"M-1005",...} แทนที่จะ
        # เป็นค่าว่าง — เอาไปพิมพ์ตรงๆ จะได้ป้ายที่อยู่ "M-1005 หมู่ 3 ..." ทั้งที่ไม่มี
        # เลขบ้านจริง เจอ house ตรงกับ user_id เป๊ะแบบนี้ ให้ถือว่า "ไม่มี" แทน
        if house and user_id and house == user_id:
            house = "ไม่มี"

        if not user_id or not (house or sticker_text):
            self._send_json(400, {"error": "user_id and house are required"})
            return
        if sticker_text:
            name, tambon, house, moo, soi = "", sticker_text, "", "", ""
        if not isinstance(quantity, int) or quantity < 1 or quantity > 50:
            self._send_json(400, {"error": "quantity must be an integer between 1 and 50"})
            return

        try:
            n, preview_path = print_label(user_id=user_id, house=house, moo=moo, soi=soi,
                                           name=name, tambon=tambon, quantity=quantity)
        except RuntimeError as e:
            print(f"[print-server] *** พิมพ์ไม่สำเร็จ (RuntimeError): {e}")
            self._send_json(503, {"error": str(e)})
            return
        except usb.core.USBError as e:
            print(f"[print-server] *** พิมพ์ไม่สำเร็จ (USBError): {e}")
            self._send_json(502, {"error": f"USB error: {e}"})
            return
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"error": f"{type(e).__name__}: {e}"})
            return

        tag = "[MOCK] " if preview_path else ""
        print(f"{tag}พิมพ์ให้ {user_id} ({name or '-'} | {house} หมู่ {moo or '-'} {tambon or '-'}) x{quantity} — ส่งไป {n} bytes")
        resp = {"success": True, "bytes_sent": n, "quantity": quantity, "mock": bool(preview_path)}
        if preview_path:
            resp["preview_file"] = preview_path
        self._send_json(200, resp)


def main():
    # ต้องผูกกับ 127.0.0.1 เท่านั้น — เว็บแอป SmartPay รันเป็น HTTPS ซึ่งเบราว์เซอร์จะบล็อก3
    # การเรียก http:// ไปยัง IP อื่นที่ไม่ใช่ localhost (mixed content policy) ดังนั้น
    # print server ตัวนี้ต้องรันบนเครื่องเดียวกับที่เปิดเว็บแอปอยู่เท่านั้น เรียกผ่าน
    # http://localhost:9100 หรือ http://127.0.0.1:9100 — เปิดที่ 0.0.0.0/IP สาธารณะแล้ว
    # เว็บแอปจะเรียกไม่ได้เลย (ถูกเบราว์เซอร์บล็อกตั้งแต่ต้น)
    check_thai_font()
    if not _HAVE_RAQM:
        print("*** คำเตือน: ไม่มี RAQM (libraqm) — สระ/วรรณยุกต์ภาษาไทยอาจวางผิดตำแหน่ง")
        print("*** ถ้าป้ายภาษาไทยเพี้ยน ดูวิธีลง raqm ใน README-Windows.txt ข้อ 'ภาษาไทยเพี้ยน'")
    if MOCK_PRINT:
        print("=" * 60)
        print("*** MOCK MODE เปิดอยู่ — ไม่ต้องมีเครื่องพิมพ์ต่อ USB ก็ทดสอบได้")
        print(f"*** /print จะเซฟรูปพรีวิวไว้ที่ {PREVIEW_DIR}/ แทนการพิมพ์จริง")
        print("=" * 60)
    httpd = HTTPServer(("127.0.0.1", PRINT_SERVER_PORT), PrintRequestHandler)
    print(f"Print server กำลังทำงานที่ http://localhost:{PRINT_SERVER_PORT}")
    print("รอรับคำสั่งพิมพ์จากเว็บแอป SmartPay (POST /print) — กด Ctrl+C เพื่อหยุด")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nปิด print server แล้ว")


if __name__ == "__main__":
    # `--list` = โชว์ USB ทุกตัวพร้อม VID/PID เพื่อหา VID/PID ของเครื่องบาร์โค้ด
    # แล้วเอาไปตั้ง env TSC_VID/TSC_PID (ดูคอมเมนต์ส่วนหัวไฟล์)
    if "--list" in sys.argv:
        dump_devices(list(_usb_find(find_all=True)))
    else:
        main()