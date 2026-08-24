"""
TSC TE310 — ป้ายบัตร ID (แนวนอน 50x30 mm) หัวภาษาไทย + บาร์โค้ดใหญ่ จัดกึ่งกลาง
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
TITLE        = "เทศบาลตำบลแม่วาง"
SUBTITLE     = "เชียงใหม่"
KEY_VALUE    = "PK-1000482"
ID_TEXT      = "ID"
BARCODE_DATA = "PK-1000482"          # ข้อมูลในบาร์โค้ด (Code128)
# ======================================================

# ============== ค่าเครื่อง / ขนาด ==============
VENDOR_ID  = None        # ใส่ถ้าหาเครื่องไม่เจอ เช่น 0x1203
PRODUCT_ID = None
DENSITY = 10
SPEED   = 3
W, H = 590, 354          # 50mm x 30mm @300dpi
INVERT_BITMAP = False    # พิมพ์ออกมาพื้นดำตัวขาว -> True

# บาร์โค้ด
BAR_NARROW = 3           # ความกว้างแท่ง (ยิ่งมากยิ่งกว้าง: 2=เล็ก 3=กลาง 4=เต็ม)
BAR_Y      = 138
BAR_HEIGHT = 140         # ความสูงบาร์โค้ด (ปรับให้ใหญ่ขึ้นได้)

# ฟอนต์ไทย (macOS) — ถ้าต้องการตัวหนาให้เพิ่ม index ใน TITLE_INDEX
THAI_FONTS = [
    "/System/Library/Fonts/SukhumvitSet.ttc",
    "/System/Library/Fonts/Supplemental/Thonburi.ttc",
    os.path.expanduser("~/Library/Fonts/Sarabun-Bold.ttf"),
    os.path.expanduser("~/Library/Fonts/IBMPlexSansThai-Bold.ttf"),
    "/Library/Fonts/Sarabun-Bold.ttf",
]
TITLE_INDEX = 0          # SukhumvitSet: ลองเปลี่ยนเป็น 5 เพื่อให้หนาขึ้น
MONO_BOLD = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
]
SANS = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
# ===============================================


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


def render_label_bitmap() -> Image.Image:
    img = Image.new("1", (W, H), 1)
    d = ImageDraw.Draw(img)
    cx = W // 2

    title_f = load_font(THAI_FONTS, 48, index=TITLE_INDEX)
    sub_f   = load_font(THAI_FONTS, 19)
    pk_f    = load_font(MONO_BOLD, 34)
    id_f    = load_font(SANS, 13)

    # กรอบรอบป้าย
    d.rectangle([6, 6, W - 7, H - 7], outline=0, width=2)

    # หัว + บรรทัดรอง (จัดกึ่งกลาง; ไม่ใส่ letter-spacing เพื่อให้สระ/วรรณยุกต์ไทยไม่หลุด)
    d.text((cx, 30), TITLE, font=title_f, fill=0, anchor="ma")
    d.text((cx, 104), SUBTITLE, font=sub_f, fill=0, anchor="ma")

    # PK ด้านล่าง (กึ่งกลาง) + ID มุมขวาล่าง
    d.text((cx, 286), KEY_VALUE, font=pk_f, fill=0, anchor="ma")
    d.text((W - 22, 312), ID_TEXT, font=id_f, fill=0, anchor="ra")

    # (พื้นที่บาร์โค้ดเว้นไว้ ให้คำสั่ง BARCODE วาดทับ)
    return img


def build_tspl() -> bytes:
    img = render_label_bitmap()
    if INVERT_BITMAP:
        img = img.point(lambda v: 255 - v)

    wbytes = (W + 7) // 8
    data = img.tobytes()

    # คำนวณความกว้างบาร์โค้ด Code128 เพื่อจัดกึ่งกลาง
    modules = 11 + 11 * len(BARCODE_DATA) + 11 + 13
    bar_w = modules * BAR_NARROW
    bx = max(10, (W - bar_w) // 2)

    head = (
        f"SIZE 50 mm, 30 mm\r\nGAP 2 mm, 0 mm\r\nDIRECTION 1\r\n"
        f"REFERENCE 0,0\r\nDENSITY {DENSITY}\r\nSPEED {SPEED}\r\nCLS\r\n"
    ).encode()
    bmp = f"BITMAP 0,0,{wbytes},{H},0,".encode() + data + b"\r\n"
    bc = (f'BARCODE {bx},{BAR_Y},"128",{BAR_HEIGHT},0,0,'
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