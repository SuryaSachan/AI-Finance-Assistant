"""Generate sleek, high-contrast Dark Mode High Level Design architecture diagram."""
from PIL import Image, ImageDraw, ImageFont

def draw_dashed_rounded_rect(draw, bbox, radius, outline, width=2, dash_len=8, space_len=6):
    x0, y0, x1, y1 = bbox
    # Top edge
    x = x0 + radius
    while x < x1 - radius:
        draw.line([(x, y0), (min(x + dash_len, x1 - radius), y0)], fill=outline, width=width)
        x += dash_len + space_len
    # Bottom edge
    x = x0 + radius
    while x < x1 - radius:
        draw.line([(x, y1), (min(x + dash_len, x1 - radius), y1)], fill=outline, width=width)
        x += dash_len + space_len
    # Left edge
    y = y0 + radius
    while y < y1 - radius:
        draw.line([(x0, y), (x0, min(y + dash_len, y1 - radius))], fill=outline, width=width)
        y += dash_len + space_len
    # Right edge
    y = y0 + radius
    while y < y1 - radius:
        draw.line([(x1, y), (x1, min(y + dash_len, y1 - radius))], fill=outline, width=width)
        y += dash_len + space_len
    
    # Corners
    draw.arc([x0, y0, x0 + 2*radius, y0 + 2*radius], 180, 270, fill=outline, width=width)
    draw.arc([x1 - 2*radius, y0, x1, y0 + 2*radius], 270, 360, fill=outline, width=width)
    draw.arc([x0, y1 - 2*radius, x0 + 2*radius, y1], 90, 180, fill=outline, width=width)
    draw.arc([x1 - 2*radius, y1 - 2*radius, x1, y1], 0, 90, fill=outline, width=width)

def render_high_level_design_dark(output_path="architecture_high_level_design.png"):
    W, H = 2400, 1400
    # Deep Dark Slate background (#0F172A)
    img = Image.new("RGBA", (W, H), (15, 23, 42, 255))
    draw = ImageDraw.Draw(img)

    # Subtle background dot grid
    for x in range(0, W, 40):
        for y in range(0, H, 40):
            draw.point((x, y), fill=(30, 41, 59, 140))

    # Fonts
    font_main_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 46)
    font_section = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 20)
    font_card_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 19)
    font_card_sub = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)
    font_card_sub_bold = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 15)
    font_user_label = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18)
    font_tech_label = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 17)
    font_tech_sub = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 14)

    # Dark Mode Palette
    C_TITLE = (248, 250, 252, 255)       # Slate 50
    C_TEXT = (241, 245, 249, 255)        # Slate 100
    C_MUTED = (148, 163, 184, 255)       # Slate 400
    C_BORDER_CONTAINER = (51, 65, 85, 255)# Slate 700
    C_BORDER_DASH = (71, 85, 105, 255)   # Slate 600
    C_ARROW = (148, 163, 184, 255)       # Light Slate Arrow

    # Top Title
    title_text = "AI Finance Assistant – High Level Design"
    bbox = font_main_title.getbbox(title_text)
    tw = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, 45), title_text, font=font_main_title, fill=C_TITLE)

    # Helper function for drawing dark mode cards
    def draw_card(x, y, w, h, title, subtitle_lines, bg_col, border_col, title_col, icon_fn=None):
        draw.rounded_rectangle([x, y, x + w, y + h], radius=14, fill=bg_col, outline=border_col, width=2)
        
        if icon_fn:
            icon_fn(draw, x + w // 2, y + 65)

        t_lines = title.split("\n")
        curr_y = y + 25 if not icon_fn else y + 105
        for tl in t_lines:
            t_box = font_card_title.getbbox(tl)
            t_w = t_box[2] - t_box[0]
            draw.text((x + (w - t_w) // 2, curr_y), tl, font=font_card_title, fill=title_col)
            curr_y += 24

        curr_y += 10
        for sl in subtitle_lines:
            s_box = font_card_sub.getbbox(sl)
            s_w = s_box[2] - s_box[0]
            draw.text((x + (w - s_w) // 2, curr_y), sl, font=font_card_sub, fill=C_MUTED)
            curr_y += 22

    def draw_arrow_h(x1, y, x2, color=C_ARROW, width=2):
        draw.line([(x1, y), (x2, y)], fill=color, width=width)
        if x2 > x1:
            draw.polygon([(x2, y), (x2 - 10, y - 6), (x2 - 10, y + 6)], fill=color)
        else:
            draw.polygon([(x2, y), (x2 + 10, y - 6), (x2 + 10, y + 6)], fill=color)

    def draw_arrow_v(x, y1, y2, color=C_ARROW, width=2):
        draw.line([(x, y1), (x, y2)], fill=color, width=width)
        if y2 > y1:
            draw.polygon([(x, y2), (x - 6, y2 - 10), (x + 6, y2 - 10)], fill=color)
        else:
            draw.polygon([(x, y2), (x - 6, y2 + 10), (x + 6, y2 + 10)], fill=color)

    def draw_bi_arrow_h(x1, y, x2, color=C_ARROW, width=2):
        draw.line([(x1, y), (x2, y)], fill=color, width=width)
        draw.polygon([(x1, y), (x1 + 10, y - 6), (x1 + 10, y + 6)], fill=color)
        draw.polygon([(x2, y), (x2 - 10, y - 6), (x2 - 10, y + 6)], fill=color)

    # ------------------ TOP ROW ------------------

    # 0. User Node on far left
    user_cx = 120
    user_cy = 340
    draw.ellipse([user_cx - 45, user_cy - 45, user_cx + 45, user_cy + 45], fill=(30, 41, 59, 255), outline=(96, 165, 250, 255), width=2)
    # Head
    draw.ellipse([user_cx - 16, user_cy - 30, user_cx + 16, user_cy + 2], fill=(226, 232, 240, 255))
    # Body arc
    draw.chord([user_cx - 30, user_cy + 8, user_cx + 30, user_cy + 45], 180, 360, fill=(226, 232, 240, 255))
    draw.text((user_cx - 18, user_cy + 55), "User", font=font_user_label, fill=C_TEXT)

    # Arrow User <-> Chat Interface
    draw_bi_arrow_h(user_cx + 45, user_cy, 240)

    # 1. Chat Interface
    def icon_chat(d, cx, cy):
        d.rounded_rectangle([cx - 24, cy - 18, cx + 24, cy + 18], radius=6, fill=(56, 189, 248, 255))
        d.polygon([(cx - 10, cy + 18), (cx - 2, cy + 18), (cx - 14, cy + 28)], fill=(56, 189, 248, 255))
        for dx in (-10, 0, 10):
            d.ellipse([cx + dx - 2, cy - 2, cx + dx + 2, cy + 2], fill=(15, 23, 42, 255))

    draw_card(240, 200, 200, 280, "1. Chat\nInterface", ["FastAPI", "(Web / API)"],
              bg_col=(20, 35, 60, 255), border_col=(56, 189, 248, 255), title_col=(56, 189, 248, 255), icon_fn=icon_chat)

    draw_arrow_h(440, 340, 480)

    # CONTAINER: Query Processing Pipeline (Dashed Box)
    q_box_x = 480
    q_box_y = 150
    q_box_w = 1190
    q_box_h = 360
    draw_dashed_rounded_rect(draw, [q_box_x, q_box_y, q_box_x + q_box_w, q_box_y + q_box_h], radius=16, outline=C_BORDER_DASH, width=2)
    draw.text((q_box_x + 470, q_box_y - 28), "Query Processing Pipeline", font=font_section, fill=(203, 213, 225, 255))

    # 2. Query Understanding
    def icon_brain(d, cx, cy):
        d.ellipse([cx - 20, cy - 16, cx - 2, cy + 16], fill=(52, 211, 153, 255))
        d.ellipse([cx + 2, cy - 16, cx + 20, cy + 16], fill=(52, 211, 153, 255))
        d.ellipse([cx - 12, cy - 22, cx + 12, cy - 4], fill=(52, 211, 153, 255))

    draw_card(510, 190, 240, 290, "2. Query\nUnderstanding", ["LLM / Parser", "(Intent, Entities,", "Filters, Dates)"],
              bg_col=(20, 45, 38, 255), border_col=(52, 211, 153, 255), title_col=(52, 211, 153, 255), icon_fn=icon_brain)

    draw_arrow_h(750, 340, 790)

    # 3. Plan Validation
    def icon_shield_amber(d, cx, cy):
        d.polygon([(cx, cy - 24), (cx + 20, cy - 14), (cx + 20, cy + 10), (cx, cy + 24), (cx - 20, cy + 10), (cx - 20, cy - 14)], fill=(251, 191, 36, 255))
        d.line([(cx - 8, cy + 2), (cx - 2, cy + 8), (cx + 8, cy - 6)], fill=(15, 23, 42, 255), width=3)

    draw_card(790, 190, 240, 290, "3. Plan\nValidation", ["Validate entities,", "columns, filters,", "dates & business", "rules"],
              bg_col=(45, 36, 18, 255), border_col=(251, 191, 36, 255), title_col=(251, 191, 36, 255), icon_fn=icon_shield_amber)

    draw_arrow_h(1030, 340, 1070)

    # 4. SQL Generation
    def icon_sql(d, cx, cy):
        d.rounded_rectangle([cx - 18, cy - 22, cx + 18, cy + 22], radius=4, fill=(56, 189, 248, 255))
        f_sql = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 12)
        d.text((cx - 12, cy - 7), "SQL", font=f_sql, fill=(15, 23, 42, 255))

    draw_card(1070, 190, 240, 290, "4. SQL\nGeneration", ["Generate safe", "parameterized", "SQL"],
              bg_col=(18, 38, 58, 255), border_col=(56, 189, 248, 255), title_col=(56, 189, 248, 255), icon_fn=icon_sql)

    draw_arrow_h(1310, 340, 1350)

    # 5. Execution (DuckDB)
    def icon_db(d, cx, cy):
        d.ellipse([cx - 20, cy - 22, cx + 20, cy - 8], fill=(192, 132, 252, 255))
        d.rectangle([cx - 20, cy - 15, cx + 20, cy + 12], fill=(192, 132, 252, 255))
        d.ellipse([cx - 20, cy + 5, cx + 20, cy + 19], fill=(192, 132, 252, 255))
        d.ellipse([cx - 18, cy - 20, cx + 18, cy - 10], fill=(233, 213, 255, 255))

    draw_card(1350, 190, 240, 290, "5. Execution\n(DuckDB)", ["Execute SQL on", "analytical views", "(DuckDB)"],
              bg_col=(35, 22, 58, 255), border_col=(192, 132, 252, 255), title_col=(192, 132, 252, 255), icon_fn=icon_db)

    # ------------------ RIGHT: DATA LAYER ------------------
    dl_x = 1730
    dl_y = 150
    dl_w = 570
    dl_h = 670
    draw.rounded_rectangle([dl_x, dl_y, dl_x + dl_w, dl_y + dl_h], radius=16, fill=(24, 33, 53, 255), outline=C_BORDER_CONTAINER, width=2)
    draw.text((dl_x + 230, dl_y + 25), "Data Layer", font=font_section, fill=C_TITLE)

    # Sub-box 1: Raw Data
    r_x = dl_x + 35
    draw.rounded_rectangle([r_x, dl_y + 70, r_x + 500, dl_y + 210], radius=12, fill=(30, 41, 65, 255), outline=C_BORDER_CONTAINER, width=1)
    draw.text((r_x + 210, dl_y + 85), "Raw Data", font=font_card_sub_bold, fill=C_TITLE)
    
    # Bank icon
    bx1 = r_x + 70
    draw.polygon([(bx1, dl_y + 120), (bx1 + 25, dl_y + 135), (bx1 - 25, dl_y + 135)], fill=(52, 211, 153, 255))
    draw.rectangle([bx1 - 20, dl_y + 135, bx1 + 20, dl_y + 155], fill=(52, 211, 153, 255))
    draw.text((bx1 - 18, dl_y + 165), "Banks", font=font_tech_sub, fill=C_MUTED)

    # Account icon
    bx2 = r_x + 250
    draw.rounded_rectangle([bx2 - 25, dl_y + 122, bx2 + 25, dl_y + 152], radius=4, fill=(56, 189, 248, 255))
    draw.line([(bx2 - 25, dl_y + 132), (bx2 + 25, dl_y + 132)], fill=(15, 23, 42, 255), width=2)
    draw.text((bx2 - 26, dl_y + 165), "Accounts", font=font_tech_sub, fill=C_MUTED)

    # Transaction icon
    bx3 = r_x + 430
    draw.ellipse([bx3 - 20, dl_y + 120, bx3 + 20, dl_y + 160], fill=(192, 132, 252, 255))
    draw.text((bx3 - 35, dl_y + 165), "Transactions", font=font_tech_sub, fill=C_MUTED)

    # Arrow Down to Data Processing
    draw_arrow_v(r_x + 250, dl_y + 210, dl_y + 260)

    # Sub-box 2: Data Processing
    draw.rounded_rectangle([r_x, dl_y + 260, r_x + 500, dl_y + 380], radius=12, fill=(30, 41, 65, 255), outline=C_BORDER_CONTAINER, width=1)
    draw.text((r_x + 185, dl_y + 280), "Data Processing", font=font_card_sub_bold, fill=C_TITLE)
    draw.text((r_x + 175, dl_y + 325), "ETL / Processing\n& View Creation", font=font_card_sub, fill=C_MUTED)

    # Arrow Down to Analytical Views
    draw_arrow_v(r_x + 250, dl_y + 380, dl_y + 430)

    # Sub-box 3: Analytical Views (DuckDB)
    draw.rounded_rectangle([r_x, dl_y + 430, r_x + 500, dl_y + 610], radius=12, fill=(30, 41, 65, 255), outline=C_BORDER_CONTAINER, width=1)
    draw.text((r_x + 145, dl_y + 450), "Analytical Views (DuckDB)", font=font_card_sub_bold, fill=C_TITLE)
    
    vx1 = r_x + 140
    icon_db(draw, vx1, dl_y + 520)
    draw.text((vx1 - 42, dl_y + 550), "v_transactions", font=font_tech_sub, fill=(203, 213, 225, 255))

    vx2 = r_x + 360
    icon_db(draw, vx2, dl_y + 520)
    draw.text((vx2 - 35, dl_y + 550), "v_accounts", font=font_tech_sub, fill=(203, 213, 225, 255))

    # Arrow from Analytical Views (DuckDB) leftwards into Execution (DuckDB)
    draw.line([(dl_x, dl_y + 520), (1470, dl_y + 520)], fill=C_ARROW, width=2)
    draw.line([(1470, dl_y + 520), (1470, 480)], fill=C_ARROW, width=2)
    draw.polygon([(1470, 480), (1464, 490), (1476, 490)], fill=C_ARROW)

    # ------------------ BOTTOM ROW ------------------
    # Arrow from 5. Execution down to 6. Result Verifier
    draw_arrow_v(1470, 480, 600)

    # 6. Result Verifier
    def icon_shield_cyan(d, cx, cy):
        d.polygon([(cx, cy - 24), (cx + 20, cy - 14), (cx + 20, cy + 10), (cx, cy + 24), (cx - 20, cy + 10), (cx - 20, cy - 14)], fill=(45, 212, 191, 255))
        d.line([(cx - 8, cy + 2), (cx - 2, cy + 8), (cx + 8, cy - 6)], fill=(15, 23, 42, 255), width=3)

    draw_card(1350, 600, 240, 290, "6. Result\nVerifier", ["Verify numbers in", "response against", "SQL result"],
              bg_col=(18, 42, 45, 255), border_col=(45, 212, 191, 255), title_col=(45, 212, 191, 255), icon_fn=icon_shield_cyan)

    draw_arrow_h(1350, 745, 1310)

    # 7. LLM Narrator
    def icon_narrator(d, cx, cy):
        d.rounded_rectangle([cx - 22, cy - 16, cx + 22, cy + 16], radius=6, fill=(251, 146, 60, 255))
        d.line([(cx - 14, cy - 6), (cx + 14, cy - 6)], fill=(15, 23, 42, 255), width=2)
        d.line([(cx - 14, cy), (cx + 8, cy)], fill=(15, 23, 42, 255), width=2)
        d.line([(cx - 14, cy + 6), (cx + 12, cy + 6)], fill=(15, 23, 42, 255), width=2)

    draw_card(1070, 600, 240, 290, "7. LLM Narrator", ["Generate natural", "language explanation", "using results"],
              bg_col=(45, 28, 18, 255), border_col=(251, 146, 60, 255), title_col=(251, 146, 60, 255), icon_fn=icon_narrator)

    draw_arrow_h(1070, 745, 1030)

    # 8. Response
    def icon_chart(d, cx, cy):
        d.rectangle([cx - 18, cy + 6, cx - 10, cy + 20], fill=(74, 222, 128, 255))
        d.rectangle([cx - 6, cy - 4, cx + 2, cy + 20], fill=(74, 222, 128, 255))
        d.rectangle([cx + 6, cy - 18, cx + 14, cy + 20], fill=(74, 222, 128, 255))

    draw_card(790, 600, 240, 290, "8. Response", ["Answer + Numbers", "+ Breakdown", "+ Source Records", "+ SQL (for transparency)"],
              bg_col=(18, 44, 30, 255), border_col=(74, 222, 128, 255), title_col=(74, 222, 128, 255), icon_fn=icon_chart)

    draw_arrow_h(790, 745, 750)

    # 9. Final Answer to User
    def icon_user_check(d, cx, cy):
        d.ellipse([cx - 20, cy - 20, cx + 20, cy + 20], fill=(167, 139, 250, 255))
        d.line([(cx - 8, cy + 1), (cx - 2, cy + 7), (cx + 8, cy - 5)], fill=(15, 23, 42, 255), width=3)

    draw_card(510, 600, 240, 290, "9. Final Answer\nto User", ["Delivered to user", "chat interface with", "interactive table"],
              bg_col=(32, 22, 54, 255), border_col=(167, 139, 250, 255), title_col=(167, 139, 250, 255), icon_fn=icon_user_check)

    # Arrow from 9. Final Answer back to User
    draw.line([(510, 745), (user_cx, 745)], fill=C_ARROW, width=2)
    draw.line([(user_cx, 745), (user_cx, user_cy + 80)], fill=C_ARROW, width=2)
    draw.polygon([(user_cx, user_cy + 80), (user_cx - 6, user_cy + 90), (user_cx + 6, user_cy + 90)], fill=C_ARROW)

    # ------------------ BOTTOM: TECH STACK ------------------
    ts_y = 1200
    draw.rounded_rectangle([200, ts_y, W - 200, ts_y + 120], radius=14, fill=(24, 33, 53, 255), outline=C_BORDER_CONTAINER, width=2)
    
    draw.text(((W - 100) // 2, ts_y - 14), "Tech Stack", font=font_section, fill=C_TITLE)

    techs = [
        ("Python", (52, 211, 153, 255)),
        ("FastAPI", (56, 189, 248, 255)),
        ("OpenAI / LLM", (203, 213, 225, 255)),
        ("DuckDB", (251, 191, 36, 255)),
        ("CSV / Parquet", (129, 140, 248, 255))
    ]

    t_step = (W - 400) // len(techs)
    for idx, (t_name, t_col) in enumerate(techs):
        tx = 200 + idx * t_step + t_step // 2
        draw.ellipse([tx - 65, ts_y + 45, tx - 45, ts_y + 65], fill=t_col)
        draw.text((tx - 35, ts_y + 45), t_name, font=font_tech_label, fill=C_TEXT)

    img.save(output_path, "PNG", quality=95)
    print(f"Dark Mode High Level Design saved to {output_path}")

if __name__ == "__main__":
    render_high_level_design_dark()
