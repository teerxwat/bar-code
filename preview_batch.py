"""
พรีวิวป้ายแบบ "หลายรายการรวดเดียว" (batch) — เตรียมไว้ทดสอบก่อนทำฟีเจอร์จริง

รูปแบบที่จะปริ้นจริงบนม้วนเดียว ต่อ user_id หนึ่งคน:
  1) label "คั่น" — พื้นดำเต็มแผ่น เขียน user_id ตัวใหญ่สีขาวแนวนอนกึ่งกลางจอ (ไม่มีบาร์โค้ด)
  2) ตามด้วยป้ายบาร์โค้ดจริง (แถบดำซ้าย ชื่อ/ที่อยู่ + บาร์โค้ด Code128) ซ้ำตาม quantity ใบ
แล้วขึ้น user_id ถัดไปต่อทันที เช่น:
  [คั่น M-1042] [บาร์โค้ด M-1042] x5 [คั่น M-1043] [บาร์โค้ด M-1043] x5 ...

ยังเป็นแค่ mock preview เท่านั้น (ยังไม่ได้ผูกกับ /print หรือ endpoint จริงใดๆ)
ใช้ฟังก์ชันชุดเดียวกับ tsc_te310_print_server.py (render_label_bitmap, build_house_moo_text,
render_divider_label, build_mock_batch_sheet) พรีวิวเลยตรงกับดีไซน์จริงทุก pixel

วิธีรัน (default = ตัวอย่าง M-1042 x5 แล้ว M-1043 x5 ตามที่อธิบายไว้):
    pip install python-barcode
    python preview_batch.py --out batch_preview.png

หรือกำหนดรายการเอง:
    python preview_batch.py --out batch_preview.png --items-json '[
        {"user_id":"M-1042","name":"นาย สมชาย ใจดี","house":"123/45","moo":"3","tambon":"บ้านกาด","quantity":5},
        {"user_id":"M-1043","name":"นาง สมหญิง ดีใจ","house":"88","moo":"3","tambon":"บ้านกาด","quantity":5}
    ]'
"""
import argparse
import json

from PIL import Image

from tsc_te310_print_server import build_mock_batch_sheet

DEFAULT_ITEMS = [
    {"user_id": "M-1042", "name": "นาย สมชาย ใจดี", "house": "123/45", "moo": "3",
     "tambon": "บ้านกาด", "quantity": 5},
    {"user_id": "M-1043", "name": "นาง สมหญิง ดีใจ", "house": "88", "moo": "3",
     "tambon": "บ้านกาด", "quantity": 5},
]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--items-json", default=None,
                     help='JSON list ของรายการ เช่น [{"user_id":"M-1042","name":"...",'
                          '"house":"...","moo":"...","soi":"","tambon":"...","quantity":5}, ...]')
    ap.add_argument("--out", default="batch_preview.png")
    ap.add_argument("--scale", type=int, default=1, help="ขยายภาพกี่เท่าตอน save (ระวังไฟล์ใหญ่)")
    args = ap.parse_args()

    items = json.loads(args.items_json) if args.items_json else DEFAULT_ITEMS
    sheet, have_barcode = build_mock_batch_sheet(items)

    if args.scale != 1:
        sheet = sheet.resize((sheet.width * args.scale, sheet.height * args.scale), Image.NEAREST)

    sheet.save(args.out)
    if not have_barcode:
        print("*** ไม่มี python-barcode ติดตั้งอยู่ — บาร์โค้ดบางส่วน/ทั้งหมดจะไม่ถูกวาด "
              "(ติดตั้งด้วย `pip install python-barcode`)")
    print(f"บันทึกพรีวิว batch แล้ว: {args.out} ({sheet.width}x{sheet.height}px, "
          f"{len(items)} รายการ)")


if __name__ == "__main__":
    main()
