import os
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from app.utils.casing import to_title_case
from app.config import settings

def number_to_words(num: float) -> str:
    """
    Converts a number into Indian Rupee English words representation (Lakhs, Crores, etc.)
    """
    if num == 0:
        return "Rupees Zero Only"
    
    integer_part = int(num)
    decimal_part = int(round((num - integer_part) * 100))
    
    def convert_chunk(n):
        units = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten",
                 "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        if n < 20:
            return units[n]
        elif n < 100:
            return tens[n // 10] + (" " + units[n % 10] if n % 10 != 0 else "")
        elif n < 1000:
            return units[n // 100] + " Hundred" + (" and " + convert_chunk(n % 100) if n % 100 != 0 else "")
        return ""
 
    def get_indian_words(n):
        if n == 0:
            return ""
        
        crores = n // 10000000
        n %= 10000000
        
        lakhs = n // 100000
        n %= 100000
        
        thousands = n // 1000
        n %= 1000
        
        hundreds = n // 100
        n %= 100
        
        parts = []
        if crores > 0:
            parts.append(convert_chunk(crores) + " Crore")
        if lakhs > 0:
            parts.append(convert_chunk(lakhs) + " Lakh")
        if thousands > 0:
            parts.append(convert_chunk(thousands) + " Thousand")
        if hundreds > 0:
            parts.append(convert_chunk(hundreds) + " Hundred")
        if n > 0:
            if len(parts) > 0:
                parts.append("and " + convert_chunk(n))
            else:
                parts.append(convert_chunk(n))
                
        return " ".join(parts)
        
    rupee_words = get_indian_words(integer_part)
    words = f"Rupees {rupee_words}" if rupee_words else "Zero Rupees"
    
    if decimal_part > 0:
        paise_words = convert_chunk(decimal_part)
        words += f" and {paise_words} Paise"
        
    words += " Only"
    return words


class PDFGenerator:
    @staticmethod
    def generate_invoice(
        invoice_number: str,
        sale_date: date,
        customer_name: str,
        customer_phone: str,
        items: list,
        total_amount: float,
        output_dir: str = "invoices"
    ) -> str:
        """
        Generates a professional retail PDF invoice.
        items parameter format: List of dicts containing:
            {"product_name": str, "quantity": int, "price": float, "warranty_info": str}
        Returns the absolute filepath of the generated PDF.
        """
        os.makedirs(output_dir, exist_ok=True)
        filename = f"{invoice_number.replace('/', '_')}.pdf"
        filepath = os.path.join(output_dir, filename)
        
        # Proper page layout and 0.5 inch margins
        doc = SimpleDocTemplate(
            filepath,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )
        
        styles = getSampleStyleSheet()
        
        # Premium monochrome color palette (Artem Lebedev Style)
        primary_color = colors.HexColor("#000000")
        secondary_color = colors.HexColor("#000000")
        dark_neutral = colors.HexColor("#000000")
        light_neutral = colors.HexColor("#FFFFFF")
        border_color = colors.HexColor("#E5E7EB")
        accent_color = colors.HexColor("#6B7280") # Clean grey for helper labels
        
        # Custom Typography Styles
        title_style = ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=24,
            leading=28,
            textColor=primary_color,
            spaceAfter=2
        )
        
        subtitle_style = ParagraphStyle(
            'InvoiceSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=accent_color,
            spaceAfter=8
        )
        
        meta_label_style = ParagraphStyle(
            'MetaLabel',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=8,
            leading=11,
            textColor=accent_color
        )
        
        meta_value_style = ParagraphStyle(
            'MetaValue',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=dark_neutral
        )

        table_header_style = ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=11,
            textColor=dark_neutral,
            alignment=TA_LEFT
        )
        
        table_cell_style = ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            leading=12,
            textColor=dark_neutral
        )
        
        table_cell_bold_style = ParagraphStyle(
            'TableCellBold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=dark_neutral
        )
        
        amount_words_style = ParagraphStyle(
            'AmountWords',
            parent=styles['Normal'],
            fontName='Helvetica-Oblique',
            fontSize=9,
            leading=12,
            textColor=accent_color,
            spaceBefore=12
        )
        
        footer_style = ParagraphStyle(
            'InvoiceFooter',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9.5,
            leading=13,
            textColor=primary_color,
            alignment=TA_CENTER,
            spaceBefore=20
        )

        elements = []
        
        # 1. Header Branding Table (Clean Spacing, No Overlaps)
        right_title_style = ParagraphStyle('RightTitle', parent=title_style, alignment=TA_RIGHT, fontSize=28, textColor=primary_color, leading=32)
        right_subtitle_style = ParagraphStyle('RightSubtitle', parent=subtitle_style, alignment=TA_RIGHT, fontSize=12, textColor=dark_neutral)
        
        header_data = [
            [
                Paragraph("BizPilot", title_style),
                Paragraph("INVOICE", right_title_style)
            ],
            [
                Paragraph("Electronics & Retail Store", subtitle_style),
                Paragraph(f"#{invoice_number.replace('DRAFT-', '')}", right_subtitle_style)
            ]
        ]
        header_table = Table(header_data, colWidths=[4.3 * inch, 3.2 * inch])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ]))
        elements.append(header_table)
        elements.append(Spacer(1, 15))
        
        # 2. Metadata Section (Clean Borderless Two-Column Details)
        cust_name_formatted = to_title_case(customer_name or "Cash Customer")
        
        meta_data = [
            [
                Paragraph("Email", meta_label_style),
                Paragraph("Phone", meta_label_style)
            ],
            [
                Paragraph("support@bizpilot.com", meta_value_style),
                Paragraph(f"+91 {settings.PRIMARY_ADMIN_PHONE}", meta_value_style)
            ],
            [
                Paragraph("Address", meta_label_style),
                Paragraph("Billed To", meta_label_style)
            ],
            [
                Paragraph("Retail Store", meta_value_style),
                Paragraph(f"<b>{cust_name_formatted}</b> &nbsp;({customer_phone or 'N/A'})", meta_value_style)
            ]
        ]
        
        meta_table = Table(meta_data, colWidths=[3.75 * inch, 3.75 * inch])
        meta_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 0),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ]))
        elements.append(meta_table)
        elements.append(Spacer(1, 25))
        
        # 3. Description Header
        desc_title_style = ParagraphStyle('DescTitle', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=primary_color)
        desc_data = [[
            Paragraph("Description", desc_title_style)
        ]]
        desc_table = Table(desc_data, colWidths=[7.5 * inch])
        desc_table.setStyle(TableStyle([
            ('PADDING', (0,0), (-1,-1), 0),
            ('LINEBELOW', (0,0), (-1,-1), 1, primary_color),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
        ]))
        elements.append(desc_table)
        elements.append(Spacer(1, 10))

        # 4. Clean, Borderless Items Table
        table_header_price_style = ParagraphStyle('THRight', parent=table_header_style, alignment=TA_RIGHT)
        table_data = [[
            Paragraph("Particulars", table_header_style),
            Paragraph("Warranty Duration", table_header_style),
            Paragraph("Qty", table_header_price_style),
            Paragraph("Unit Price", table_header_price_style),
            Paragraph("Amount (Rs.)", table_header_price_style),
        ]]
        
        for idx, item in enumerate(items, 1):
            qty = item["quantity"]
            price = float(item["price"])
            amount = qty * price
            
            prod_name_formatted = to_title_case(item["product_name"])
            table_data.append([
                Paragraph(prod_name_formatted, table_cell_style),
                Paragraph(to_title_case(item.get("warranty_info", "No Warranty")), table_cell_style),
                Paragraph(str(qty), ParagraphStyle('RightCell', parent=table_cell_style, alignment=TA_RIGHT)),
                Paragraph(f"Rs. {price:,.2f}", ParagraphStyle('RightCell', parent=table_cell_style, alignment=TA_RIGHT)),
                Paragraph(f"Rs. {amount:,.2f}", ParagraphStyle('RightCellBold', parent=table_cell_bold_style, alignment=TA_RIGHT)),
            ])
            
        # Column widths summing up to 7.5 inches
        item_table = Table(table_data, colWidths=[3.2 * inch, 1.4 * inch, 0.5 * inch, 1.1 * inch, 1.3 * inch])
        item_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,0), 'LEFT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LINEBELOW', (0,0), (-1,0), 0.5, primary_color), # Thin line below header row
            ('LINEBELOW', (0,-1), (-1,-1), 0.5, primary_color), # Thin line below last row
            ('PADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 8),
            ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ]))
        elements.append(item_table)
        elements.append(Spacer(1, 10))

        # 5. Right Aligned Subtotal & Total Block
        right_label_style = ParagraphStyle('TotalLabel', parent=table_cell_style, alignment=TA_RIGHT, textColor=accent_color)
        right_val_style = ParagraphStyle('TotalVal', parent=table_cell_style, alignment=TA_RIGHT, textColor=dark_neutral)
        total_val_bold_style = ParagraphStyle('TotalValBold', parent=table_cell_bold_style, alignment=TA_RIGHT, textColor=dark_neutral)

        total_rows = [
            [Paragraph("Subtotal", right_label_style), Paragraph(f"Rs. {total_amount:,.2f}", right_val_style)],
            [Paragraph("Total", ParagraphStyle('TotalLabelBold', parent=table_cell_bold_style, alignment=TA_RIGHT)), Paragraph(f"Rs. {total_amount:,.2f}", total_val_bold_style)],
            [Paragraph("Due Date", right_label_style), Paragraph(sale_date.strftime("%B %d, %Y"), right_val_style)]
        ]
        total_table = Table(total_rows, colWidths=[5.9 * inch, 1.6 * inch])
        total_table.setStyle(TableStyle([
            ('PADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LINEBELOW', (0,1), (-1,1), 0.5, primary_color), # Line under Total
        ]))
        elements.append(total_table)
        elements.append(Spacer(1, 12))

        # 4. Total in words
        words_desc = number_to_words(total_amount)
        elements.append(Paragraph(f"<b>Amount in Words:</b> {words_desc}", amount_words_style))
        elements.append(Spacer(1, 20))
        
        # 5. Footer Block (grouped to avoid page breaks)
        footer_data = [
            [
                Paragraph("<b>Terms & Conditions:</b><br/>1. Goods once sold are not returnable.<br/>2. Subject to local jurisdiction.<br/>3. Warranty is handled by respective brands / service centers.", ParagraphStyle('Terms', parent=table_cell_style, fontSize=7.5, textColor=dark_neutral, leading=10))
            ]
        ]
        footer_table = Table(footer_data, colWidths=[7.5 * inch])
        footer_table.setStyle(TableStyle([
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('PADDING', (0,0), (-1,-1), 0),
            ('LINEABOVE', (0,0), (-1,-1), 0.5, border_color),
            ('TOPPADDING', (0,0), (-1,-1), 10),
        ]))
        
        elements.append(KeepTogether([
            footer_table,
            Spacer(1, 15),
            Paragraph("Thank you for shopping with us!", footer_style)
        ]))
        
        # Build PDF
        doc.build(elements)
        return os.path.abspath(filepath)

    @staticmethod
    def generate_catalogue(products: list, output_path: str = "invoices/catalogue.pdf") -> str:
        """
        Generates a premium product catalogue PDF.
        products parameter: List of product model objects.
        Returns the absolute filepath of the generated PDF.
        """
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        doc = SimpleDocTemplate(
            output_path,
            pagesize=letter,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36
        )
        
        styles = getSampleStyleSheet()
        
        # Theme colors
        primary_color = colors.HexColor("#1B365D") # Deep Navy Blue
        secondary_color = colors.HexColor("#64748B") # Slate Grey
        light_neutral = colors.HexColor("#F8FAFC")
        border_color = colors.HexColor("#E2E8F0")
        accent_color = colors.HexColor("#475569")
        
        title_style = ParagraphStyle(
            'CatalogueTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=28,
            textColor=primary_color,
            alignment=TA_CENTER,
            spaceAfter=4
        )
        
        subtitle_style = ParagraphStyle(
            'CatalogueSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=11,
            textColor=accent_color,
            alignment=TA_CENTER,
            spaceAfter=25
        )
        
        category_header_style = ParagraphStyle(
            'CategoryHeader',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=14,
            textColor=secondary_color,
            spaceBefore=14,
            spaceAfter=6
        )
        
        th_style = ParagraphStyle(
            'C_TH',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9.5,
            textColor=colors.white
        )
        
        th_right_style = ParagraphStyle(
            'C_TH_R',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9.5,
            textColor=colors.white,
            alignment=TA_RIGHT
        )
        
        td_style = ParagraphStyle(
            'C_TD',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=9,
            textColor=primary_color
        )
        
        td_right_style = ParagraphStyle(
            'C_TD_R',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            textColor=primary_color,
            alignment=TA_RIGHT
        )
        
        footer_style = ParagraphStyle(
            'CatalogueFooter',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=10,
            textColor=primary_color,
            alignment=TA_CENTER,
            spaceBefore=25
        )

        elements = []
        
        # 1. Branding Header
        elements.append(Paragraph("BIZPILOT", title_style))
        elements.append(Paragraph("<b>PRODUCT CATALOGUE</b>", subtitle_style))
        
        # Group products by category
        grouped_products = {}
        for p in products:
            if p.is_active:
                cat = to_title_case(p.category or "General")
                if cat not in grouped_products:
                    grouped_products[cat] = []
                grouped_products[cat].append(p)
        
        if not grouped_products:
            elements.append(Paragraph("Catalogue is empty at this moment. Please check back later.", subtitle_style))
        else:
            for category, items in sorted(grouped_products.items()):
                elements.append(Paragraph(category, category_header_style))
                
                # Create category table
                table_data = [[
                    Paragraph("Product Name", th_style),
                    Paragraph("Default Price (Rs.)", th_right_style)
                ]]
                
                for item in sorted(items, key=lambda x: x.name):
                    table_data.append([
                        Paragraph(to_title_case(item.name), td_style),
                        Paragraph(f"{float(item.default_price):,.2f}", td_right_style)
                    ])
                
                cat_table = Table(table_data, colWidths=[5.3 * inch, 2.2 * inch])
                cat_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,0), primary_color),
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('TOPPADDING', (0,0), (-1,0), 6),
                    ('BOTTOMPADDING', (0,0), (-1,0), 6),
                    ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, light_neutral]),
                    ('LINEBELOW', (0,0), (-1,0), 2, secondary_color),
                    ('BOX', (0,0), (-1,-1), 1, border_color),
                    ('INNERGRID', (0,0), (-1,-1), 0.5, border_color),
                    ('PADDING', (0,0), (-1,-1), 7),
                ]))
                
                elements.append(cat_table)
                elements.append(Spacer(1, 10))
                
        elements.append(Spacer(1, 15))
        elements.append(Paragraph("For purchases or queries, reply 'Talk to Owner' or contact store support.<br/>Thank you for your business!", footer_style))
        
        doc.build(elements)
        return os.path.abspath(output_path)
