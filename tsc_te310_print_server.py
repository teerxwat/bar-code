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
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont

# หาฟอนต์ไทยจาก path ของสคริปต์เอง (ไม่ใช่ cwd ที่รันคำสั่ง) — รองรับทั้งกรณี
# ไฟล์ฟอนต์อยู่ข้างสคริปต์โดยตรง และอยู่ในโฟลเดอร์ fonts/
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(SCRIPT_DIR, "fonts")

# ============== ค่าเครื่อง / ขนาด ==============
VENDOR_ID = None
PRODUCT_ID = None
DENSITY = 10
SPEED = 3
W, H = 590, 354  # 50mm x 30mm @300dpi
INVERT_BITMAP = False

BAND_W = 150  # ความกว้างแถบดำซ้าย

# บาร์โค้ด (เน้นใหญ่) — วางในโซนขวา
BAR_X = 250  # ขยับซ้าย-ขวาให้อยู่กึ่งกลางโซนขวา
BAR_Y = 92
BAR_HEIGHT = 158
BAR_NARROW = 3  # 2=เล็ก 3=กลาง 4=ใหญ่

PRINT_SERVER_PORT = 9100
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
            f = ImageFont.truetype(p, size, index=index,
                                    layout_engine=ImageFont.Layout.RAQM)
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


def fit_side_text_font(text: str, max_width: int, max_size: int = 46, min_size: int = 20, step: int = 2):
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


def build_address_text(house: str, moo: str = "", soi: str = "", tambon: str = "") -> str:
    """
    ประกอบข้อความที่อยู่ (บรรทัด 2 ของแถบดำ): "{house} หมู่ {moo} ซอย {soi} ต.{tambon}"
    - หมู่/ซอย/ตำบล ใส่เฉพาะตอนมีข้อมูล ไม่มีก็ไม่แสดงคำนำหน้านั้นเลย
    """
    parts = [f"{house}"]
    if moo:
        parts.append(f"หมู่ {moo}")
    if soi:
        parts.append(f"ซอย {soi}")
    if tambon:
        parts.append(f"{tambon}")
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
    max_size = 46
    while True:
        fonts = [fit_side_text_font(t, max_text_width, max_size=max_size)[0] for t in lines]
        bboxes = [tmp.textbbox((0, 0), t, font=f) for t, f in zip(lines, fonts)]
        heights = [b[3] - b[1] for b in bboxes]
        total_h = sum(heights) + gap * (len(lines) - 1) + 10
        if total_h <= max_total_height or max_size <= 20:
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


def render_label_bitmap(name: str, address: str, number: str) -> Image.Image:
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)

    # --- แถบดำซ้าย ---
    d.rectangle([0, 0, BAND_W - 1, H - 1], fill=0)  # 0 = ดำ

    # --- ข้อความแนวตั้งในแถบดำ (ขาวบนดำ) 2 บรรทัด: ชื่อ / ที่อยู่ ---
    # ถ้าไม่มีชื่อ (name ว่าง) จะเหลือบรรทัดเดียวคือที่อยู่ — ยังพิมพ์ได้ปกติ
    lines = [t for t in (name, address) if t]
    max_text_width = H - 30      # เผื่อขอบบน-ล่างของแถบดำข้างละ ~15px
    max_total_height = BAND_W - 16  # ทุกบรรทัดรวมกันต้องไม่ล้นความกว้างแถบดำ
    tile = render_band_tile(lines, max_text_width, max_total_height)
    img.paste(tile, ((BAND_W - tile.width) // 2, (H - tile.height) // 2))

    # --- เลขใต้บาร์โค้ด (กึ่งกลางโซนขวา) ---
    num_f = load_font(BOLD, 34)
    rcx = (BAND_W + W) // 2
    draw_tracked(d, (rcx, 292), number, num_f, tracking=6, fill=0, align="center")

    # (พื้นที่บาร์โค้ดเว้นไว้ ให้คำสั่ง BARCODE วาดทับ)
    return img


def build_tspl(name: str, address: str, number: str, barcode_data: str, quantity: int = 1) -> bytes:
    img = render_label_bitmap(name, address, number)
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP 2 mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    bc = (f'BARCODE {BAR_X},{BAR_Y},"128",{BAR_HEIGHT},0,0,'
          f'{BAR_NARROW},{BAR_NARROW},"{barcode_data}"\r\n').encode()
    tail = f"PRINT 1,{quantity}\r\n".encode()
    return head + bmp + bc + tail


# ============== ส่วนเชื่อมต่อ USB ==============
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


def dump_devices(devs):
    print("USB devices ที่เห็น:")
    for d in devs:
        manu = _safe_string(d, d.iManufacturer)
        prod = _safe_string(d, d.iProduct)
        tag = " [printer]" if _is_printer(d) else ""
        print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)} {manu} {prod}{tag}")


def find_printer():
    if VENDOR_ID and PRODUCT_ID:
        dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
        if dev:
            return dev
    candidates = list(usb.core.find(find_all=True))
    for dev in candidates:
        manu = _safe_string(dev, dev.iManufacturer)
        prod = _safe_string(dev, dev.iProduct)
        if "TSC" in manu or "TSC" in prod or "TE310" in prod:
            return dev
    printers = [d for d in candidates if _is_printer(d)]
    if len(printers) == 1:
        return printers[0]
    if len(printers) > 1:
        print("เจออุปกรณ์คลาส printer มากกว่า 1 ตัว — เลือกด้วย VID/PID:")
        for d in printers:
            print(f"  VID={hex(d.idVendor)} PID={hex(d.idProduct)}")
        return None
    dump_devices(candidates)
    return None


def send(dev, data: bytes):
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
    except (NotImplementedError, usb.core.USBError):
        pass
    dev.set_configuration()
    cfg = dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep_out = usb.util.find_descriptor(
        intf,
        custom_match=lambda e:
            usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
    )
    if ep_out is None:
        raise RuntimeError("ไม่เจอ bulk OUT endpoint")
    written = ep_out.write(data, timeout=10000)
    usb.util.dispose_resources(dev)
    return written


def print_label(user_id: str, house: str, moo: str, soi: str = "", name: str = "",
                tambon: str = "", quantity: int = 1):
    """ประกอบป้ายจาก user_id/name/house/moo/soi/tambon แล้วส่งไปเครื่องพิมพ์ผ่าน USB จริง"""
    address = build_address_text(house=house, moo=moo, soi=soi, tambon=tambon)
    tspl = build_tspl(name=name, address=address, number=user_id,
                      barcode_data=user_id, quantity=quantity)

    dev = find_printer()
    if dev is None:
        raise RuntimeError("หาเครื่อง TSC ไม่เจอ — เช็คสาย USB / system_profiler SPUSBDataType | grep -A 12 -i tsc")
    return send(dev, tspl)


# ============== HTTP Server (รับคำสั่งพิมพ์จากเว็บแอป) ==============
class PrintRequestHandler(BaseHTTPRequestHandler):
    def _set_cors_headers(self):
        # เว็บแอป SmartPay รันอยู่คนละ origin (เว็บไซต์จริง) แต่เครื่องนี้ต้องรับ
        # คำขอจาก origin นั้นได้ — เปิดกว้างไว้เพราะ server นี้ฟังแค่ localhost/LAN
        # ภายในสำนักงานเท่านั้น ไม่ได้เปิดออกอินเทอร์เน็ต
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

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

    def do_POST(self):
        if self.path != "/print":
            self._send_json(404, {"error": "not found"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
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

        if not user_id or not house:
            self._send_json(400, {"error": "user_id and house are required"})
            return
        if not isinstance(quantity, int) or quantity < 1 or quantity > 50:
            self._send_json(400, {"error": "quantity must be an integer between 1 and 50"})
            return

        try:
            n = print_label(user_id=user_id, house=house, moo=moo, soi=soi,
                            name=name, tambon=tambon, quantity=quantity)
        except RuntimeError as e:
            self._send_json(503, {"error": str(e)})
            return
        except usb.core.USBError as e:
            self._send_json(502, {"error": f"USB error: {e}"})
            return

        print(f"พิมพ์ให้ {user_id} ({name or '-'} | {house} หมู่ {moo or '-'} {tambon or '-'}) x{quantity} — ส่งไป {n} bytes")
        self._send_json(200, {"success": True, "bytes_sent": n})


def main():
    # ต้องผูกกับ 127.0.0.1 เท่านั้น — เว็บแอป SmartPay รันเป็น HTTPS ซึ่งเบราว์เซอร์จะบล็อก3
    # การเรียก http:// ไปยัง IP อื่นที่ไม่ใช่ localhost (mixed content policy) ดังนั้น
    # print server ตัวนี้ต้องรันบนเครื่องเดียวกับที่เปิดเว็บแอปอยู่เท่านั้น เรียกผ่าน
    # http://localhost:9100 หรือ http://127.0.0.1:9100 — เปิดที่ 0.0.0.0/IP สาธารณะแล้ว
    # เว็บแอปจะเรียกไม่ได้เลย (ถูกเบราว์เซอร์บล็อกตั้งแต่ต้น)
    check_thai_font()
    httpd = HTTPServer(("127.0.0.1", PRINT_SERVER_PORT), PrintRequestHandler)
    print(f"Print server กำลังทำงานที่ http://localhost:{PRINT_SERVER_PORT}")
    print("รอรับคำสั่งพิมพ์จากเว็บแอป SmartPay (POST /print) — กด Ctrl+C เพื่อหยุด")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nปิด print server แล้ว")


if __name__ == "__main__":
    main()