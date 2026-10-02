"""
พรีวิวป้ายสติกเกอร์เป็นไฟล์ PNG (ไม่ต้องต่อเครื่องพิมพ์จริง)

ใช้โค้ดวาดป้ายชุดเดียวกับ tsc_te310_print_server.py (render_label_bitmap,
build_house_moo_text) เพื่อให้พรีวิวตรงกับของจริง แล้ววาดบาร์โค้ด Code128 ทับ
ในตำแหน่ง/ขนาดเดียวกับที่เครื่องพิมพ์จะวาด (BAR_X, BAR_Y, BAR_HEIGHT, BAR_NARROW)

วิธีรัน:
    pip install python-barcode
    python preview_label.py \
        --user-id "M-1042" --name "นาย สมชาย ใจดี" \
        --house "123/45" --moo "3" --tambon "บ้านกาด" \
        --out preview.png
"""
import argparse

from barcode import Code128
from PIL import Image, ImageDraw

from tsc_te310_print_server import (
    BAND_W, BAR_HEIGHT, BAR_NARROW, BAR_X, BAR_Y, H, W,
    build_house_moo_text, render_label_bitmap,
)


def draw_barcode(img: Image.Image, data: str) -> None:
    """วาดแท่งบาร์โค้ด Code128 ทับบน img ที่ตำแหน่ง/สเกลเดียวกับที่ปริ้นเตอร์จะวาดจริง
    (โมดูลกว้าง BAR_NARROW dots ต่อแท่ง — ตรงกับ narrow=wide ที่ส่งไปใน TSPL BARCODE)"""
    modules = Code128(data).build()[0]  # สตริง '1'/'0' ทีละโมดูล (1=แท่งดำ)
    d = ImageDraw.Draw(img)
    x = BAR_X
    for bit in modules:
        if bit == "1":
            d.rectangle([x, BAR_Y, x + BAR_NARROW - 1, BAR_Y + BAR_HEIGHT - 1], fill=0)
        x += BAR_NARROW


def build_preview(name: str, tambon: str, house_moo: str, number: str, barcode_data: str) -> Image.Image:
    img = render_label_bitmap(name, tambon, house_moo, number).convert("L")
    draw_barcode(img, barcode_data)
    return img


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--user-id", default="M-1042")
    ap.add_argument("--name", default="นาย สมชาย ใจดี")
    ap.add_argument("--house", default="123/45")
    ap.add_argument("--moo", default="3")
    ap.add_argument("--soi", default="")
    ap.add_argument("--tambon", default="บ้านกาด")
    ap.add_argument("--out", default="preview.png")
    ap.add_argument("--scale", type=int, default=2, help="ขยายภาพกี่เท่าตอน save (ดูง่ายขึ้น)")
    args = ap.parse_args()

    house_moo = build_house_moo_text(house=args.house, moo=args.moo, soi=args.soi)
    img = build_preview(name=args.name, tambon=args.tambon, house_moo=house_moo,
                         number=args.user_id, barcode_data=args.user_id)

    if args.scale != 1:
        img = img.resize((W * args.scale, H * args.scale), Image.NEAREST)

    img.save(args.out)
    print(f"บันทึกพรีวิวแล้ว: {args.out} ({img.width}x{img.height}px)")


if __name__ == "__main__":
    main()
