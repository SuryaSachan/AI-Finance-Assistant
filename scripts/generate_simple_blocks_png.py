"""Generate clean, minimalist, high-level block architecture diagram PNG."""
from PIL import Image, ImageDraw, ImageFont

def render_simple_blocks(output_path="architecture_high_level.png"):
    W, H = 2200, 1200
    img = Image.new("RGBA", (W, H), (15, 23, 42, 255)) # Slate 900
    draw = ImageDraw.Draw(img)

    # Fonts
    font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 44)
    font_subtitle = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 20)
    font_step = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 14)
    font_block_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 22)
    font_block_sub = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)
    font_badge = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 13)
    font_arrow_lbl = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 13)

    # Palette
    C_TEXT = (248, 250, 252, 255)
    C_MUTED = (148, 163, 184, 255)
    C_BORDER = (51, 65, 85, 255)
    
    C_BLUE = (56, 189, 248, 255)     # Sky
    C_INDIGO = (129, 140, 248, 255)  # Indigo
    C_AMBER = (251, 191, 36, 255)    # Amber
    C_EMERALD = (52, 211, 153, 255)  # Emerald
    C_ROSE = (244, 63, 94, 255)      # Rose
    C_CYAN = (34, 211, 238, 255)     # Cyan

    # Background subtle grid pattern
    for x in range(0, W, 50):
        for y in range(0, H, 50):
            draw.point((x, y), fill=(30, 41, 59, 160))

    # --- Header ---
    draw.text((100, 70), "AI Finance Assistant — High-Level Architecture", font=font_title, fill=C_TEXT)
    draw.text((100, 130), "Core system blocks and data flow: from question to verified answer", font=font_subtitle, fill=C_MUTED)

    # Divider line
    draw.line([(100, 175), (W - 100, 175)], fill=(33, 45, 68, 255), width=2)

    # --- 6 Big Flow Blocks (2 Rows of 3 Blocks) ---
    # Row 1: Left to Right (1 -> 2 -> 3)
    # Row 2: Right to Left (4 -> 5 -> 6) or Left to Right (4 -> 5 -> 6)
    
    blocks = [
        # ROW 1 (Ingestion & Planning)
        {
            "step": "STEP 01",
            "title": "Web Chat Interface",
            "sub": "User asks question in natural English",
            "tag": "Frontend (web/)",
            "color": C_BLUE,
            "x": 100, "y": 240, "w": 560, "h": 220
        },
        {
            "step": "STEP 02",
            "title": "API Gateway & Engine",
            "sub": "Routes request & retains conversation memory",
            "tag": "FastAPI + engine.py",
            "color": C_INDIGO,
            "x": 820, "y": 240, "w": 560, "h": 220
        },
        {
            "step": "STEP 03",
            "title": "3-Tier Query Planner",
            "sub": "Converts question into structured JSON plan",
            "tag": "Qwen2.5-3B / Rule Engine",
            "color": C_AMBER,
            "x": 1540, "y": 240, "w": 560, "h": 220
        },
        
        # ROW 2 (Execution & Delivery)
        {
            "step": "STEP 04",
            "title": "Safe SQL Compiler",
            "sub": "Translates JSON plan into whitelist SQL",
            "tag": "sql_builder.py",
            "color": C_CYAN,
            "x": 1540, "y": 620, "w": 560, "h": 220
        },
        {
            "step": "STEP 05",
            "title": "DuckDB Analytics Core",
            "sub": "Executes aggregation & anomaly check in <50ms",
            "tag": "finance.duckdb + executor.py",
            "color": C_EMERALD,
            "x": 820, "y": 620, "w": 560, "h": 220
        },
        {
            "step": "STEP 06",
            "title": "Number Guardrail & Delivery",
            "sub": "Verifies all digits against SQL & renders answer",
            "tag": "Anti-Hallucination (answer.py)",
            "color": C_ROSE,
            "x": 100, "y": 620, "w": 560, "h": 220
        }
    ]

    def draw_arrow(x1, y1, x2, y2, color, label=""):
        draw.line([(x1, y1), (x2, y2)], fill=color, width=3)
        # Arrowhead
        if x2 > x1: # Right
            draw.polygon([(x2, y2), (x2 - 14, y2 - 8), (x2 - 14, y2 + 8)], fill=color)
        elif x2 < x1: # Left
            draw.polygon([(x2, y2), (x2 + 14, y2 - 8), (x2 + 14, y2 + 8)], fill=color)
        elif y2 > y1: # Down
            draw.polygon([(x2, y2), (x2 - 8, y2 - 14), (x2 + 8, y2 - 14)], fill=color)
        elif y2 < y1: # Up
            draw.polygon([(x2, y2), (x2 - 8, y2 + 14), (x2 + 8, y2 + 14)], fill=color)

        if label:
            lx = (x1 + x2) // 2
            ly = (y1 + y2) // 2 - 20
            draw.text((lx - 30, ly), label, font=font_arrow_lbl, fill=C_MUTED)

    # Draw all blocks
    for b in blocks:
        bx, by, bw, bh = b["x"], b["y"], b["w"], b["h"]

        # Main Card Box
        draw.rounded_rectangle([bx, by, bx + bw, by + bh], radius=16, fill=(24, 33, 53, 255), outline=C_BORDER, width=2)
        
        # Top Color Accent Strip
        draw.rounded_rectangle([bx, by, bx + bw, by + 8], radius=4, fill=b["color"])

        # Step Label + Tag
        draw.text((bx + 28, by + 26), b["step"], font=font_step, fill=b["color"])
        
        # Tag pill on right
        tag_w = len(b["tag"]) * 8 + 20
        draw.rounded_rectangle([bx + bw - tag_w - 24, by + 22, bx + bw - 24, by + 46], radius=6, fill=(33, 46, 74, 255))
        draw.text((bx + bw - tag_w - 14, by + 26), b["tag"], font=font_badge, fill=C_TEXT)

        # Title
        draw.text((bx + 28, by + 74), b["title"], font=font_block_title, fill=C_TEXT)

        # Subtitle / description (single concise line)
        draw.text((bx + 28, by + 120), b["sub"], font=font_block_sub, fill=C_MUTED)

    # --- Draw Connecting Arrows ---
    # 1 -> 2 (Horizontal Right)
    draw_arrow(660, 350, 820, 350, C_BLUE)
    # 2 -> 3 (Horizontal Right)
    draw_arrow(1380, 350, 1540, 350, C_INDIGO)
    
    # 3 -> 4 (Vertical Down)
    draw_arrow(1820, 460, 1820, 620, C_AMBER)

    # 4 -> 5 (Horizontal Left)
    draw_arrow(1540, 730, 1380, 730, C_CYAN)
    # 5 -> 6 (Horizontal Left)
    draw_arrow(820, 730, 660, 730, C_EMERALD)

    # Final Loop-back from 6 to 1 (Return Answer)
    # Upwards arrow showing answer rendered in UI
    draw_arrow(380, 620, 380, 460, C_ROSE)
    draw.text((395, 530), "Verified Answer Returned", font=font_arrow_lbl, fill=C_ROSE)

    # --- Bottom Summary Banner ---
    b_y = 930
    draw.rounded_rectangle([100, b_y, W - 100, b_y + 160], radius=14, fill=(20, 28, 48, 255), outline=C_BORDER, width=1)

    draw.text((140, b_y + 24), "CORE ARCHITECTURAL PRINCIPLES", font=font_step, fill=C_BLUE)
    
    principles = [
        ("• LLM translates language", "The AI model interprets user queries into a JSON plan; it never computes math."),
        ("• SQL does arithmetic", "DuckDB executes all calculations over columnar data in milliseconds."),
        ("• Guardrail verifies every digit", "If any number in the output isn't backed by database facts, it is discarded.")
    ]

    for idx, (p_head, p_body) in enumerate(principles):
        px = 140 + idx * 640
        draw.text((px, b_y + 64), p_head, font=font_block_title, fill=C_TEXT)
        draw.text((px, b_y + 104), p_body, font=font_block_sub, fill=C_MUTED)

    # Save
    img.save(output_path, "PNG", quality=95)
    print(f"Simple block diagram saved to {output_path}")

if __name__ == "__main__":
    render_simple_blocks()
