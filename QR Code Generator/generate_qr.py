import qrcode
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import os
from datetime import datetime


def generate_qr_code(url: str, filename: str = "qr_code"):
    """
    Generate QR Code from a URL and save it as PNG and PDF files.
    
    Args:
        url (str): The link you want to encode in the QR code
        filename (str): Base name for the output files (without extension)
    """
    
    # Create output directory if it doesn't exist
    output_dir = "qr_codes"
    os.makedirs(output_dir, exist_ok=True)
    
    # QR Code configuration
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_H,  # High error correction level
        box_size=10,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)

    # Create QR Code image
    img = qr.make_image(fill_color="black", back_color="white")
    
    # === Save as PNG ===
    png_path = os.path.join(output_dir, f"{filename}.png")
    img.save(png_path)
    print(f"✅ PNG file created: {png_path}")
    
    # === Save as PDF ===
    pdf_path = os.path.join(output_dir, f"{filename}.pdf")
    
    c = canvas.Canvas(pdf_path, pagesize=A4)
    width, height = A4
    
    # Title
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width/2, height - 100, "QR Code")
    
    c.setFont("Helvetica", 12)
    c.drawCentredString(width/2, height - 130, "Scan to open the link")
    
    # Insert QR Code into PDF
    img_reader = ImageReader(png_path)
    img_width = 300
    img_height = 300
    x = (width - img_width) / 2
    y = (height - img_height) / 2 - 50
    
    c.drawImage(img_reader, x, y, width=img_width, height=img_height, preserveAspectRatio=True)
    
    # URL below the QR Code
    c.setFont("Helvetica", 10)
    display_url = url[:80] + ("..." if len(url) > 80 else "")
    c.drawCentredString(width/2, y - 30, display_url)
    
    c.save()
    
    print(f"✅ PDF file created: {pdf_path}")
    print(f"📍 Both files saved in '{output_dir}' folder.")


# ==================== Usage Example ====================
if __name__ == "__main__":
    link = input("Enter the link: ").strip()
    
    if not link.startswith(("http://", "https://")):
        link = "https://" + link
    
    # Generate filename with timestamp
    filename = f"qr_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    generate_qr_code(link, filename)