"""Generate high-resolution, presentation-grade architecture diagram PNG."""
import os
from PIL import Image, ImageDraw, ImageFont

def render_diagram(output_path="architecture_diagram.png"):
    W, H = 2400, 1400
    img = Image.new("RGBA", (W, H), (11, 15, 25, 255)) # Dark slate background #0B0F19
    draw = ImageDraw.Draw(img)

    # Fonts
    font_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 46)
    font_subtitle = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 22)
    font_tag = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 15)
    
    font_col_header = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 20)
    font_card_title = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 18)
    font_card_file = ImageFont.truetype("C:/Windows/Fonts/consolab.ttf", 14)
    font_body = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)
    font_body_bold = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 15)
    font_badge = ImageFont.truetype("C:/Windows/Fonts/segoeuib.ttf", 12)
    font_footer = ImageFont.truetype("C:/Windows/Fonts/segoeui.ttf", 15)

    # Palette
    C_TEXT = (248, 250, 252, 255)
    C_MUTED = (148, 163, 184, 255)
    C_DIM = (100, 116, 139, 255)
    C_BORDER = (51, 65, 85, 255)
    
    # Accent colors
    C_BLUE = (56, 189, 248, 255)     # #38BDF8
    C_INDIGO = (129, 140, 248, 255)  # #818CF8
    C_AMBER = (251, 191, 36, 255)    # #FBBF24
    C_EMERALD = (52, 211, 153, 255)  # #34D399
    C_ROSE = (244, 63, 94, 255)      # #F43F5E
    C_PURPLE = (192, 132, 252, 255)  # #C084FC

    # Subtle background grid dots
    for x in range(0, W, 40):
        for y in range(0, H, 40):
            draw.point((x, y), fill=(30, 41, 59, 120))

    # --- Header Section ---
    # Tag Pill
    tag_text = "SYSTEM ARCHITECTURE & EXECUTION LIFECYCLE"
    draw.rounded_rectangle([100, 50, 540, 84], radius=17, fill=(30, 41, 59, 255), outline=C_BLUE, width=1)
    draw.text((125, 58), tag_text, font=font_tag, fill=C_BLUE)

    # Main Title
    draw.text((100, 100), "AI Finance Assistant — High-Level Architecture", font=font_title, fill=C_TEXT)
    # Subtitle
    draw.text((100, 160), "Deterministic Financial Analytics with AI Interpretation · Sub-50ms In-Memory Computation · Zero-Hallucination Guardrails",
              font=font_subtitle, fill=C_MUTED)

    # Decorative header divider
    draw.line([(100, 205), (W - 100, 205)], fill=(30, 41, 59, 255), width=2)

    # --- 5 Columns Layout ---
    cols = [
        {
            "num": "01",
            "title": "CLIENT & API",
            "color": C_BLUE,
            "cards": [
                {
                    "title": "User Query Input",
                    "file": "Natural Language",
                    "desc": "• Freeform finance queries\n• e.g. 'How much spent on UPI last month?'\n• Follow-ups: 'Compare to prior month'",
                    "badge": "Input Layer"
                },
                {
                    "title": "Web Chat Interface",
                    "file": "web/ (HTML/JS/CSS)",
                    "desc": "• Responsive chat client\n• Interactive breakdown tables\n• One-click CSV & XLSX export",
                    "badge": "Frontend"
                },
                {
                    "title": "FastAPI Gateway",
                    "file": "app/main.py",
                    "desc": "• Endpoints: /api/ask, /api/export\n• Schema & dataset inspection\n• CORS & health diagnostics",
                    "badge": "REST API"
                }
            ]
        },
        {
            "num": "02",
            "title": "ORCHESTRATION & AI",
            "color": C_INDIGO,
            "cards": [
                {
                    "title": "Orchestration Engine",
                    "file": "app/engine.py",
                    "desc": "• Thread-safe session store\n• 8-turn conversation memory\n• Multi-turn plan inheritance",
                    "badge": "Coordinator"
                },
                {
                    "title": "3-Tier Query Planner",
                    "file": "app/planner.py",
                    "desc": "• Tier 1: Small LLM JSON slot-filling\n• Tier 2: 1-shot repair on schema error\n• Tier 3: Deterministic regex parser\n• Entity fuzzy matching (rapidfuzz)",
                    "badge": "Plan Generator"
                },
                {
                    "title": "Compact LLM Client",
                    "file": "app/llm.py",
                    "desc": "• Qwen2.5-3B-Instruct (local Ollama)\n• Also supports OpenAI / Sarvam\n• Token budgeting (<600 tokens/req)\n• 100% offline-ready fallback",
                    "badge": "3B Local AI"
                }
            ]
        },
        {
            "num": "03",
            "title": "SAFE SQL BUILDER",
            "color": C_AMBER,
            "cards": [
                {
                    "title": "Strict QueryPlan Validation",
                    "file": "app/plan_models.py",
                    "desc": "• Pydantic typed schema validation\n• Dataset whitelist (transactions/balances)\n• Disallows unknown filters or metrics\n• Refuses out-of-scope predictions",
                    "badge": "Validation"
                },
                {
                    "title": "Whitelist SQL Generator",
                    "file": "app/sql_builder.py",
                    "desc": "• LLM NEVER writes raw SQL\n• Parameterized query assembly\n• Strict column & operator mapping\n• Complete SQL injection immunity",
                    "badge": "Code Safety"
                },
                {
                    "title": "PII Protection Layer",
                    "file": "app/schema_catalog.py",
                    "desc": "• Account numbers masked to last 4\n• UTRs hidden from catalog entirely\n• AES-256-SIV ledger encryption support",
                    "badge": "Data Privacy"
                }
            ]
        },
        {
            "num": "04",
            "title": "DATA & COMPUTE",
            "color": C_EMERALD,
            "cards": [
                {
                    "title": "DuckDB Columnar Core",
                    "file": "data/finance.duckdb",
                    "desc": "• Embedded vectorized analytical DB\n• Runs over 250k+ transaction rows\n• 3 ms to 65 ms ultra-low latency\n• Zero external DB server needed",
                    "badge": "In-Memory Engine"
                },
                {
                    "title": "Query Executor",
                    "file": "app/executor.py",
                    "desc": "• Executes aggregations & groupings\n• Period-over-period comparative metrics\n• Computes totals & row budget limits",
                    "badge": "Execution"
                },
                {
                    "title": "Anomaly Detector",
                    "file": "app/anomalies.py",
                    "desc": "• Statistical outlier discovery\n• Flags spends ≥ 2.5σ above 12mo baseline\n• Automated risk signaling",
                    "badge": "Risk Watchdog"
                }
            ]
        },
        {
            "num": "05",
            "title": "VERIFY & DELIVER",
            "color": C_ROSE,
            "cards": [
                {
                    "title": "Number Guardrail",
                    "file": "app/answer.py",
                    "desc": "• Scans every digit in LLM reply\n• Validates against computed SQL values\n• Discards LLM text if 1 digit mismatch\n• ZERO hallucination tolerance",
                    "badge": "Anti-Hallucination"
                },
                {
                    "title": "Confidence Scoring",
                    "file": "app/answer.py",
                    "desc": "• High / Med / Low confidence metrics\n• Evaluates row count, filters & ambiguity\n• Transparent explanation metadata",
                    "badge": "Auditability"
                },
                {
                    "title": "Final Output Delivery",
                    "file": "UI Response",
                    "desc": "• Natural language concise summary\n• Formatted INR (₹) breakdown table\n• Full SQL query & sample audit trail\n• CSV / Excel download link",
                    "badge": "Verified Answer"
                }
            ]
        }
    ]

    col_w = 405
    col_gap = 40
    start_x = 100
    start_y = 240

    for i, col in enumerate(cols):
        cx = start_x + i * (col_w + col_gap)
        
        # Column Header Pill
        draw.rounded_rectangle([cx, start_y, cx + col_w, start_y + 44], radius=8, fill=(20, 28, 45, 255), outline=col["color"], width=1)
        draw.text((cx + 14, start_y + 12), col["num"], font=font_col_header, fill=col["color"])
        draw.text((cx + 50, start_y + 12), col["title"], font=font_col_header, fill=C_TEXT)

        # Draw 3 Cards
        card_y = start_y + 60
        card_h = 300
        card_gap = 18

        for card in col["cards"]:
            # Card background
            draw.rounded_rectangle([cx, card_y, cx + col_w, card_y + card_h], radius=12, fill=(20, 28, 48, 255), outline=C_BORDER, width=1)
            
            # Card left accent strip
            draw.rounded_rectangle([cx, card_y, cx + 5, card_y + card_h], radius=2, fill=col["color"])

            # Badge
            badge_w = len(card["badge"]) * 8 + 16
            draw.rounded_rectangle([cx + col_w - badge_w - 14, card_y + 14, cx + col_w - 14, card_y + 36], radius=6, fill=(30, 41, 65, 255))
            draw.text((cx + col_w - badge_w - 6, card_y + 18), card["badge"], font=font_badge, fill=col["color"])

            # Title & File
            draw.text((cx + 18, card_y + 14), card["title"], font=font_card_title, fill=C_TEXT)
            draw.text((cx + 18, card_y + 40), card["file"], font=font_card_file, fill=col["color"])

            # Separator inside card
            draw.line([(cx + 18, card_y + 66), (cx + col_w - 18, card_y + 66)], fill=(35, 47, 70, 255), width=1)

            # Description lines
            desc_y = card_y + 78
            for line in card["desc"].split("\n"):
                if line.startswith("•"):
                    draw.text((cx + 18, desc_y), line, font=font_body, fill=C_TEXT)
                else:
                    draw.text((cx + 28, desc_y), line, font=font_body, fill=C_MUTED)
                desc_y += 24

            card_y += card_h + card_gap

        # Connecting arrow to next column (between cols 1-2, 2-3, 3-4, 4-5)
        if i < len(cols) - 1:
            arrow_x1 = cx + col_w + 6
            arrow_x2 = cx + col_w + col_gap - 6
            mid_y = start_y + 510
            # Draw dashed/styled arrow
            draw.line([(arrow_x1, mid_y), (arrow_x2, mid_y)], fill=col["color"], width=2)
            # Arrow head
            draw.polygon([(arrow_x2, mid_y), (arrow_x2 - 8, mid_y - 6), (arrow_x2 - 8, mid_y + 6)], fill=col["color"])

    # --- Bottom Feature Highlights Bar ---
    bar_y = 1270
    draw.rounded_rectangle([100, bar_y, W - 100, bar_y + 80], radius=12, fill=(15, 23, 42, 255), outline=C_BORDER, width=1)

    highlights = [
        ("ZERO HALLUCINATION", "Every digit verified against SQL facts", C_EMERALD),
        ("HIGH-SPEED ENGINE", "DuckDB in-memory analytics in 3-65ms", C_BLUE),
        ("DATA PRIVACY FIRST", "Zero ledger data sent to cloud frontier APIs", C_AMBER),
        ("100% OFFLINE CAPABLE", "Tier-3 rule engine scores 20/20 on benchmark", C_PURPLE)
    ]

    hw = (W - 200) // len(highlights)
    for j, (h_title, h_sub, h_col) in enumerate(highlights):
        hx = 100 + j * hw + 25
        # Draw small status dot
        draw.ellipse([hx, bar_y + 22, hx + 10, bar_y + 32], fill=h_col)
        draw.text((hx + 18, bar_y + 16), h_title, font=font_card_title, fill=h_col)
        draw.text((hx + 18, bar_y + 44), h_sub, font=font_body, fill=C_MUTED)

    # Save output
    img.save(output_path, "PNG", quality=95)
    print(f"Diagram saved successfully to {output_path} (Resolution: {W}x{H})")

if __name__ == "__main__":
    render_diagram()
