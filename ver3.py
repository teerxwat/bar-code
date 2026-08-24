"""
TSC TE310 — ป้ายสไตล์ตั๋ว (แนวนอน 50x30 mm): stub ซ้าย REF + เส้นปรุ + บาร์โค้ดใหญ่ขวา
render ด้วย Pillow -> ส่ง BITMAP + BARCODE ของเครื่อง ผ่าน USB บน macOS

ติดตั้งก่อน:
    brew install libusb
    pip install pyusb pillow

วิธีรัน:
    python tsc_te310_usb_direct.py
    # ถ้า Access denied: sudo python tsc_te310_usb_direct.py
"""
import os
import sys
import usb.core
import usb.util
from PIL import Image, ImageDraw, ImageFont

# ============== ข้อความบนป้าย (แก้ตรงนี้) ==============
REF_TOP      = "123"
REF_BOTTOM   = "456"
NUMBER       = "1623786213"          # เลขที่แสดงใต้บาร์โค้ด
BARCODE_DATA = "1623786213"          # ข้อมูลในบาร์โค้ด (Code128)
# ======================================================

# ============== ค่าเครื่อง / ขนาด ==============
VENDOR_ID  = None
PRODUCT_ID = None
DENSITY = 10
SPEED   = 3
W, H = 590, 354          # 50mm x 30mm @300dpi
INVERT_BITMAP = False

DASH_X = 185             # ตำแหน่งเส้นปรุแนวตั้ง (แบ่งซ้าย-ขวา)

# บาร์โค้ด (เน้นใหญ่) — วางในโซนขวา
BAR_X      = 235         # ขยับซ้าย-ขวาเพื่อจัดกึ่งกลางโซนขวา
BAR_Y      = 92
BAR_HEIGHT = 155         # ความสูง (เพิ่มให้ใหญ่ขึ้นได้)
BAR_NARROW = 3           # ความกว้างแท่ง: 2=เล็ก 3=กลาง 4=ใหญ่
# ===============================================

BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
]
SANS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def load_font(paths, size, index=0):
    for p in paths:
        try:
            return ImageFont.truetype(p, size, index=index,
                                      layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            try:
                return ImageFont.truetype(p, size, index=index)
            except Exception:
                continue
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


def render_label_bitmap() -> Image.Image:
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)

    ref_f = load_font(SANS, 15)
    big_f = load_font(BOLD, 56)
    num_f = load_font(BOLD, 34)

    # --- stub ซ้าย: REF + 123 / 456 ---
    lcx = 100
    draw_tracked(d, (lcx, 118), "REF", ref_f, tracking=4, fill=0, align="center")
    d.text((lcx, 146), REF_TOP, font=big_f, fill=0, anchor="ma")
    d.rectangle([lcx - 48, 214, lcx + 48, 218], fill=0)     # เส้นคั่นแบบเศษส่วน
    d.text((lcx, 224), REF_BOTTOM, font=big_f, fill=0, anchor="ma")

    # --- เส้นปรุแนวตั้ง + รูกลมบน/ล่าง ---
    y = 16
    while y < 339:
        d.rectangle([DASH_X - 1, y, DASH_X + 1, min(y + 10, 339)], fill=0)
        y += 18
    for cy in (28, 326):
        d.ellipse([DASH_X - 11, cy - 11, DASH_X + 11, cy + 11], outline=0, width=2)

    # --- เลขใต้บาร์โค้ด (กึ่งกลางโซนขวา) ---
    rcx = (DASH_X + W) // 2
    draw_tracked(d, (rcx, 288), NUMBER, num_f, tracking=6, fill=0, align="center")

    # (พื้นที่บาร์โค้ดเว้นไว้ ให้คำสั่ง BARCODE วาดทับ)
    return img


def build_tspl() -> bytes:
    img = render_label_bitmap()
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP 2 mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    # BARCODE x,y,"type",height,human,rotation,narrow,wide,"data"  (human=0 เพราะวาดเลขเองแล้ว)
    bc = (f'BARCODE {BAR_X},{BAR_Y},"128",{BAR_HEIGHT},0,0,'
          f'{BAR_NARROW},{BAR_NARROW},"{BARCODE_DATA}"\r\n').encode()
    tail = b"PRINT 1,1\r\n"
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


def main():
    dev = find_printer()
    if dev is None:
        print("หาเครื่อง TSC ไม่เจอ — ดู VID/PID: system_profiler SPUSBDataType | grep -A 12 -i tsc")
        sys.exit(1)
    print(f"เจอเครื่อง: VID={hex(dev.idVendor)} PID={hex(dev.idProduct)} — กำลังส่งคำสั่งปริ้น...")
    try:
        n = send(dev, build_tspl())
        print(f"ส่งคำสั่งปริ้นเรียบร้อย ({n} bytes)")
    except usb.core.USBError as e:
        print(f"ส่งไม่สำเร็จ (USBError): {e}  -> ลอง sudo หรือถอด-เสียบสาย USB ใหม่")
        sys.exit(1)


if __name__ == "__main__":
    main()