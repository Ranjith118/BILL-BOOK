from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                 Paragraph, Spacer, Image)
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
import io, os

BLACK     = colors.HexColor('#000000')
WHITE     = colors.white
BORDER    = colors.HexColor('#999999')
HEADER_BG = colors.HexColor('#EFEFEF')
TOTAL_BG  = colors.HexColor('#E4E4E4')
DARK_GRAY = colors.HexColor('#555555')

def _s(size=9, bold=False, italic=False, color=BLACK, align=TA_LEFT):
    font = ('Helvetica-BoldOblique' if bold and italic else
            'Helvetica-Bold'        if bold           else
            'Helvetica-Oblique'     if italic         else 'Helvetica')
    return ParagraphStyle('_', fontName=font, fontSize=size,
                          textColor=color, alignment=align,
                          leading=max(size * 1.35, 11), spaceAfter=0)

def _p(text, size=9, bold=False, italic=False, color=BLACK, align=TA_LEFT):
    return Paragraph(str(text), _s(size, bold, italic, color, align))

def _blank():
    return _p('')

def _amount_in_words(amount):
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven',
            'Eight', 'Nine', 'Ten', 'Eleven', 'Twelve', 'Thirteen',
            'Fourteen', 'Fifteen', 'Sixteen', 'Seventeen', 'Eighteen', 'Nineteen']
    tens_w = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty',
              'Sixty', 'Seventy', 'Eighty', 'Ninety']

    def below_hundred(n):
        if n < 20: return ones[n]
        return tens_w[n // 10] + ((' ' + ones[n % 10]) if n % 10 else '')

    def below_thousand(n):
        if n < 100: return below_hundred(n)
        return ones[n // 100] + ' Hundred' + ((' ' + below_hundred(n % 100)) if n % 100 else '')

    n = int(round(amount))
    if n == 0: return 'Zero Rupees'
    parts = []
    for div, label in [(10_000_000, 'Crore'), (100_000, 'Lakh'), (1_000, 'Thousand')]:
        if n >= div:
            parts.append(below_thousand(n // div) + ' ' + label)
            n %= div
    if n:
        parts.append(below_thousand(n))
    return ' '.join(parts) + ' Rupees'

BASE = [
    ('FONTNAME',      (0,0),(-1,-1), 'Helvetica'),
    ('FONTSIZE',      (0,0),(-1,-1), 9),
    ('TOPPADDING',    (0,0),(-1,-1), 4),
    ('BOTTOMPADDING', (0,0),(-1,-1), 4),
    ('LEFTPADDING',   (0,0),(-1,-1), 5),
    ('RIGHTPADDING',  (0,0),(-1,-1), 5),
    ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
]

def generate_invoice_pdf(bill, business):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            rightMargin=12*mm, leftMargin=12*mm,
                            topMargin=10*mm, bottomMargin=10*mm)

    def _biz(attr, default=''):
        return (getattr(business, attr, None) or default) if business else default

    biz_name  = _biz('name',       'Business Name')
    biz_phone = _biz('phone')
    biz_email = _biz('email')
    biz_addr  = _biz('address')
    biz_gst   = _biz('gst_number')
    biz_terms = _biz('terms')
    logo_path = _biz('logo')
    sig_path  = _biz('signature')
    logo_size = _biz('logo_size', 'medium')

    inv_no   = str(getattr(bill, 'bill_id', ''))
    inv_date = bill.date.strftime('%d/%m/%Y') if hasattr(bill.date, 'strftime') else str(bill.date)
    due_raw  = getattr(bill, 'due_date', None)
    due_date = due_raw.strftime('%d/%m/%Y') if hasattr(due_raw, 'strftime') else (str(due_raw) if due_raw else '-')

    cust  = bill.customer
    items = bill.items or []
    W     = 186 * mm
    elements = []

    # ── TOP LABEL ─────────────────────────────────────────────────────────────
    tag_para = Paragraph('ORIGINAL FOR RECIPIENT',
                         ParagraphStyle('tag', fontName='Helvetica', fontSize=7,
                                        textColor=DARK_GRAY, borderPadding=(2,5,2,5),
                                        borderColor=BORDER, borderWidth=0.6,
                                        alignment=TA_CENTER, leading=10))
    top_lbl = Table([[_p('TAX INVOICE', size=10, bold=True), tag_para, _blank()]],
                    colWidths=[30*mm, 52*mm, W - 82*mm])
    top_lbl.setStyle(TableStyle([
        ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ('TOPPADDING',    (0,0),(-1,-1), 0),
        ('BOTTOMPADDING', (0,0),(-1,-1), 2),
    ]))
    elements.append(top_lbl)

    # ── HEADER BOX ────────────────────────────────────────────────────────────
    LEFT_W  = W * 0.50
    RIGHT_W = W - LEFT_W

    # Logo height based on user preference
    LOGO_H_MAP = {'small': 10*mm, 'medium': 16*mm, 'large': 24*mm}
    LOGO_H = LOGO_H_MAP.get(logo_size, 16*mm)
    STATIC_IMG = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'static', 'images')

    def _load_image(filename, height=14*mm, data=None, mimetype=None):
        """Load image constrained to fit within column — never overflows."""
        PADDING = 4 * mm  # padding inside the cell on each side

        def _make_image(source, is_bytes=False):
            try:
                from PIL import Image as PILImage
                if is_bytes:
                    pil_img = PILImage.open(io.BytesIO(source))
                else:
                    pil_img = PILImage.open(source)
                orig_w, orig_h = pil_img.size

                # Max dimensions: height = LOGO_H, width = LOGO_COL_W - 2*PADDING
                max_h = height
                max_w = height * 1.5 - PADDING * 2  # column width minus padding

                # Scale to fit within both constraints
                scale_by_h = max_h / orig_h
                scale_by_w = max_w / orig_w
                scale = min(scale_by_h, scale_by_w)

                final_w = orig_w * scale
                final_h = orig_h * scale

                if is_bytes:
                    return Image(io.BytesIO(source), width=final_w, height=final_h)
                else:
                    return Image(source, width=final_w, height=final_h)
            except Exception:
                return None

        if data:
            img = _make_image(data, is_bytes=True)
            if img:
                return img

        if not filename:
            return None
        path = os.path.join(STATIC_IMG, filename)
        if not os.path.isfile(path):
            return None
        return _make_image(path, is_bytes=False)

    logo_img = _load_image(logo_path, LOGO_H,
                           data=_biz('logo_data'), mimetype=_biz('logo_mimetype'))

    # ── Build business info rows (no logo here — logo gets its own column) ───
    biz_rows = []
    biz_rows.append([_p(biz_name, size=11, bold=True)])
    if biz_phone: biz_rows.append([_p(f"Mobile:  {biz_phone}", size=8)])
    if biz_email: biz_rows.append([_p(f"Email:   {biz_email}", size=8)])
    if biz_addr:  biz_rows.append([_p(biz_addr, size=8)])
    if biz_gst:   biz_rows.append([_p(f"GSTIN: {biz_gst}", size=8)])

    # ── Meta table (Invoice No / Date / Due Date) ─────────────────────────────
    COL3 = RIGHT_W / 3
    meta_tbl = Table([
        [_p('Invoice No.',  size=8, bold=True, align=TA_CENTER),
         _p('Invoice Date', size=8, bold=True, align=TA_CENTER),
         _p('Due Date',     size=8, bold=True, align=TA_CENTER)],
        [_p(inv_no,   size=9, align=TA_CENTER),
         _p(inv_date, size=9, align=TA_CENTER),
         _p(due_date, size=9, align=TA_CENTER)],
    ], colWidths=[COL3, COL3, COL3])
    meta_tbl.setStyle(TableStyle(BASE + [
        ('FONTNAME',  (0,0),(-1,0),  'Helvetica-Bold'),
        ('ALIGN',     (0,0),(-1,-1), 'CENTER'),
        ('LINEBELOW', (0,0),(-1,0),  0.5, BORDER),
        ('GRID',      (0,0),(-1,-1), 0.4, BORDER),
    ]))

    # ── Dynamic header: 3 cols if logo, 2 cols if no logo ────────────────────
    if logo_img:
        # Fixed logo column — width based on LOGO_H with padding
        LOGO_COL_W = LOGO_H * 1.5
        BIZ_COL_W  = LEFT_W - LOGO_COL_W
        logo_img.hAlign = 'CENTER'

        logo_cell = Table([[logo_img]], colWidths=[LOGO_COL_W])
        logo_cell.setStyle(TableStyle([
            ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
            ('TOPPADDING',    (0,0),(-1,-1), 4),
            ('BOTTOMPADDING', (0,0),(-1,-1), 4),
            ('LEFTPADDING',   (0,0),(-1,-1), 4),
            ('RIGHTPADDING',  (0,0),(-1,-1), 4),
            ('OVERFLOW',      (0,0),(-1,-1), 'HIDDEN'),
        ]))

        biz_inner = Table(biz_rows, colWidths=[BIZ_COL_W - 6*mm])
        biz_inner.setStyle(TableStyle([
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('TOPPADDING',    (0,0),(-1,-1), 2),
            ('BOTTOMPADDING', (0,0),(-1,-1), 2),
        ]))

        hdr_outer = Table([[logo_cell, biz_inner, meta_tbl]],
                          colWidths=[LOGO_COL_W, BIZ_COL_W, RIGHT_W])
        hdr_outer.setStyle(TableStyle([
            ('BOX',           (0,0),(-1,-1), 0.8, BORDER),
            ('LINEBEFORE',    (1,0),(1,-1),  0.8, BORDER),
            ('LINEBEFORE',    (2,0),(2,-1),  0.8, BORDER),
            ('TOPPADDING',    (1,0),(1,-1),  5),
            ('BOTTOMPADDING', (1,0),(1,-1),  5),
            ('LEFTPADDING',   (1,0),(1,-1),  6),
            ('RIGHTPADDING',  (1,0),(1,-1),  4),
            ('LEFTPADDING',   (2,0),(2,-1),  0),
            ('RIGHTPADDING',  (2,0),(2,-1),  0),
            ('TOPPADDING',    (2,0),(2,-1),  0),
            ('BOTTOMPADDING', (2,0),(2,-1),  0),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))
    else:
        # No logo — standard 2-column layout
        biz_inner = Table(biz_rows, colWidths=[LEFT_W - 6*mm])
        biz_inner.setStyle(TableStyle([
            ('LEFTPADDING',   (0,0),(-1,-1), 0),
            ('RIGHTPADDING',  (0,0),(-1,-1), 0),
            ('TOPPADDING',    (0,0),(-1,-1), 2),
            ('BOTTOMPADDING', (0,0),(-1,-1), 2),
        ]))

        hdr_outer = Table([[biz_inner, meta_tbl]], colWidths=[LEFT_W, RIGHT_W])
        hdr_outer.setStyle(TableStyle([
            ('BOX',           (0,0),(-1,-1), 0.8, BORDER),
            ('LINEBEFORE',    (1,0),(1,-1),  0.8, BORDER),
            ('TOPPADDING',    (0,0),(0,-1),  5),
            ('BOTTOMPADDING', (0,0),(0,-1),  5),
            ('LEFTPADDING',   (0,0),(0,-1),  6),
            ('RIGHTPADDING',  (0,0),(0,-1),  4),
            ('LEFTPADDING',   (1,0),(1,-1),  0),
            ('RIGHTPADDING',  (1,0),(1,-1),  0),
            ('TOPPADDING',    (1,0),(1,-1),  0),
            ('BOTTOMPADDING', (1,0),(1,-1),  0),
            ('VALIGN',        (0,0),(-1,-1), 'MIDDLE'),
        ]))

    elements.append(hdr_outer)

    # ── BILL TO ───────────────────────────────────────────────────────────────
    bt_rows = [[_p('BILL TO', size=8, color=DARK_GRAY)],
               [_p(str(cust.name), size=10, bold=True)]]
    if getattr(cust, 'phone',   None): bt_rows.append([_p(f"Mobile:  {cust.phone}", size=8)])
    if getattr(cust, 'email',   None): bt_rows.append([_p(f"Email:   {cust.email}", size=8)])
    if getattr(cust, 'address', None): bt_rows.append([_p(str(cust.address), size=8)])

    bt_tbl = Table(bt_rows, colWidths=[W])
    bt_tbl.setStyle(TableStyle([
        ('BOX',           (0,0),(-1,-1), 0.8, BORDER),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
    ]))
    elements.append(bt_tbl)

    # ── ITEMS TABLE ───────────────────────────────────────────────────────────
    SNO_W  = 14 * mm
    QTY_W  = 24 * mm
    RATE_W = 30 * mm
    AMT_W  = 36 * mm
    SVC_W  = W - SNO_W - QTY_W - RATE_W - AMT_W

    item_rows = [[
        _p('S.NO.',    size=8, bold=True, align=TA_CENTER),
        _p('SERVICES', size=8, bold=True, align=TA_CENTER),
        _p('QTY.',     size=8, bold=True, align=TA_CENTER),
        _p('RATE',     size=8, bold=True, align=TA_CENTER),
        _p('AMOUNT',   size=8, bold=True, align=TA_CENTER),
    ]]

    for idx, item in enumerate(items, 1):
        amt = item.quantity * item.price
        item_rows.append([
            _p(str(idx),                   size=9, align=TA_CENTER),
            _p(item.product.name,          size=9, align=TA_LEFT),
            _p(str(item.quantity),         size=9, align=TA_CENTER),
            _p(f"Rs.{item.price:,.2f}",    size=9, align=TA_RIGHT),
            _p(f"Rs.{amt:,.2f}",           size=9, align=TA_RIGHT),
        ])

    MIN_DATA = 12
    while len(item_rows) <= MIN_DATA:
        item_rows.append([_blank(), _blank(), _blank(), _blank(), _blank()])

    item_rows.append([
        _blank(),
        _blank(),
        _p('TOTAL', size=9, bold=True, align=TA_RIGHT),
        _p('-',     size=9, align=TA_CENTER),
        _p(f"Rs.{bill.total_amount:,.0f}", size=9, bold=True, align=TA_RIGHT),
    ])

    n = len(item_rows)
    item_style = TableStyle(BASE + [
        ('BACKGROUND',    (0,0),(-1,0),     HEADER_BG),
        ('FONTNAME',      (0,0),(-1,0),     'Helvetica-Bold'),
        ('ALIGN',         (0,0),(-1,0),     'CENTER'),
        ('BACKGROUND',    (0,n-1),(-1,n-1), TOTAL_BG),
        ('FONTNAME',      (2,n-1),(2,n-1),  'Helvetica-Bold'),
        ('FONTNAME',      (4,n-1),(4,n-1),  'Helvetica-Bold'),
        ('BOX',           (0,0),(-1,-1),    0.8, BORDER),
        ('INNERGRID',     (0,0),(-1,-1),    0.4, BORDER),
        ('ALIGN',         (0,1),(0,n-2),    'CENTER'),
        ('ALIGN',         (1,1),(1,n-2),    'LEFT'),
        ('ALIGN',         (2,1),(2,n-2),    'CENTER'),
        ('ALIGN',         (3,1),(3,n-2),    'RIGHT'),
        ('ALIGN',         (4,1),(4,n-2),    'RIGHT'),
        ('TOPPADDING',    (0,1),(-1,n-2),   8),
        ('BOTTOMPADDING', (0,1),(-1,n-2),   8),
    ])
    items_tbl = Table(item_rows, colWidths=[SNO_W, SVC_W, QTY_W, RATE_W, AMT_W],
                      repeatRows=1)
    items_tbl.setStyle(item_style)
    elements.append(items_tbl)

    # ── TAX SUMMARY ───────────────────────────────────────────────────────────
    tax_map = {}
    for item in items:
        hsn     = str(getattr(item, 'hsn', '') or '')
        gst     = float(item.gst)
        key     = (hsn, gst)
        taxable = item.quantity * item.price
        if key not in tax_map:
            tax_map[key] = {'taxable': 0, 'cgst_r': gst/2,
                            'sgst_r': gst/2, 'cgst': 0, 'sgst': 0}
        tax_map[key]['taxable'] += taxable
        tax_map[key]['cgst']    += taxable * gst / 200
        tax_map[key]['sgst']    += taxable * gst / 200

    HN_W = 18*mm; TV_W = 30*mm; CR_W = 14*mm
    CA_W = 20*mm; SR_W = 14*mm; SA_W = 20*mm
    TT_W = W - HN_W - TV_W - CR_W - CA_W - SR_W - SA_W

    tax_hdr1 = [_p('HSN/SAC',         size=7, bold=True, align=TA_CENTER),
                _p('Taxable Value',   size=7, bold=True, align=TA_CENTER),
                _p('CGST',            size=7, bold=True, align=TA_CENTER),
                _blank(),
                _p('SGST',            size=7, bold=True, align=TA_CENTER),
                _blank(),
                _p('Total Tax Amount',size=7, bold=True, align=TA_CENTER)]
    tax_hdr2 = [_blank(), _blank(),
                _p('Rate',   size=7, bold=True, align=TA_CENTER),
                _p('Amount', size=7, bold=True, align=TA_CENTER),
                _p('Rate',   size=7, bold=True, align=TA_CENTER),
                _p('Amount', size=7, bold=True, align=TA_CENTER),
                _blank()]

    tax_data = []
    total_taxable = total_cgst = total_sgst = 0.0
    for (hsn, gst), d in tax_map.items():
        total_taxable += d['taxable']
        total_cgst    += d['cgst']
        total_sgst    += d['sgst']
        tax_data.append([
            _p(hsn,                                    size=8, align=TA_CENTER),
            _p(f"Rs.{d['taxable']:,.2f}",              size=8, align=TA_RIGHT),
            _p(f"{d['cgst_r']:.1f}%",                 size=8, align=TA_CENTER),
            _p(f"Rs.{d['cgst']:,.2f}",                 size=8, align=TA_RIGHT),
            _p(f"{d['sgst_r']:.1f}%",                 size=8, align=TA_CENTER),
            _p(f"Rs.{d['sgst']:,.2f}",                 size=8, align=TA_RIGHT),
            _p(f"Rs.{d['cgst']+d['sgst']:,.2f}",       size=8, align=TA_RIGHT),
        ])

    total_tax = total_cgst + total_sgst
    tax_total = [
        _p('Total', size=8, bold=True, align=TA_RIGHT),
        _p(f"{total_taxable:,.0f}",  size=8, align=TA_RIGHT),
        _blank(),
        _p(f"{total_cgst:,.0f}",     size=8, align=TA_RIGHT),
        _blank(),
        _p(f"{total_sgst:,.0f}",     size=8, align=TA_RIGHT),
        _p(f"Rs.{total_tax:,.0f}", size=8, bold=True, align=TA_RIGHT),
    ]

    all_tax = [tax_hdr1, tax_hdr2] + tax_data + [tax_total]
    nt = len(all_tax)
    tax_tbl = Table(all_tax, colWidths=[HN_W, TV_W, CR_W, CA_W, SR_W, SA_W, TT_W])
    tax_tbl.setStyle(TableStyle(BASE + [
        ('BACKGROUND',    (0,0),(-1,1),      HEADER_BG),
        ('FONTNAME',      (0,0),(-1,1),      'Helvetica-Bold'),
        ('BACKGROUND',    (0,nt-1),(-1,nt-1),TOTAL_BG),
        ('FONTNAME',      (0,nt-1),(0,nt-1), 'Helvetica-Bold'),
        ('FONTNAME',      (6,nt-1),(6,nt-1), 'Helvetica-Bold'),
        ('BOX',           (0,0),(-1,-1),     0.8, BORDER),
        ('INNERGRID',     (0,0),(-1,-1),     0.4, BORDER),
        ('ALIGN',         (0,0),(-1,-1),     'CENTER'),
        ('ALIGN',         (1,2),(1,nt-1),    'RIGHT'),
        ('ALIGN',         (3,2),(3,nt-1),    'RIGHT'),
        ('ALIGN',         (5,2),(5,nt-1),    'RIGHT'),
        ('ALIGN',         (6,2),(6,nt-1),    'RIGHT'),
        ('SPAN',          (2,0),(3,0)),
        ('SPAN',          (4,0),(5,0)),
        ('TOPPADDING',    (0,0),(-1,-1),     3),
        ('BOTTOMPADDING', (0,0),(-1,-1),     3),
        ('FONTSIZE',      (0,0),(-1,-1),     7),
    ]))
    elements.append(tax_tbl)

    # ── AMOUNT IN WORDS ───────────────────────────────────────────────────────
    words_tbl = Table([
        [_p('Total Amount (in words)', size=8, bold=True)],
        [_p(_amount_in_words(bill.total_amount), size=9)],
    ], colWidths=[W])
    words_tbl.setStyle(TableStyle([
        ('BOX',           (0,0),(-1,-1), 0.8, BORDER),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
    ]))
    elements.append(words_tbl)

    # ── TERMS & CONDITIONS | AUTHORISED SIGNATORY ─────────────────────────────
    TC_W  = W * 0.55
    SIG_W = W - TC_W

    terms_text = biz_terms
    has_terms  = bool(terms_text and terms_text.strip())
    sig_img = _load_image(sig_path, 12*mm,
                          data=_biz('signature_data'), mimetype=_biz('signature_mimetype'))

    # Left: terms (if set) or empty
    if has_terms:
        tc_rows = [[_p('Terms and Conditions', size=8, bold=True)]]
        for i, line in enumerate(terms_text.split('\n'), 1):
            line = line.strip()
            if line:
                prefix = '' if (line and line[0].isdigit()) else f"{i}. "
                tc_rows.append([_p(prefix + line, size=8)])
    else:
        tc_rows = [[_p('Terms and Conditions', size=8, bold=True)],
                   [_p('No terms specified.', size=8, color=DARK_GRAY)]]

    tc_inner = Table(tc_rows, colWidths=[TC_W - 8*mm])
    tc_inner.setStyle(TableStyle([
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ('TOPPADDING',    (0,0),(-1,-1), 2),
        ('BOTTOMPADDING', (0,0),(-1,-1), 2),
    ]))

    # Right: signature image (if uploaded) + space to sign + label
    sig_rows = []
    if sig_img:
        sig_img.hAlign = 'CENTER'
        sig_rows.append([sig_img])
    else:
        # Empty space for manual signature
        sig_rows.append([Spacer(1, 18*mm)])

    sig_rows.append([_p('Authorised Signatory For', size=8, color=DARK_GRAY, align=TA_CENTER)])
    sig_rows.append([_p(biz_name, size=8, bold=True, align=TA_CENTER)])

    sig_inner = Table(sig_rows, colWidths=[SIG_W - 8*mm])
    sig_inner.setStyle(TableStyle([
        ('LEFTPADDING',   (0,0),(-1,-1), 0),
        ('RIGHTPADDING',  (0,0),(-1,-1), 0),
        ('TOPPADDING',    (0,0),(-1,-1), 3),
        ('BOTTOMPADDING', (0,0),(-1,-1), 3),
        ('ALIGN',         (0,0),(-1,-1), 'CENTER'),
        # Line above the label row
        ('LINEABOVE',     (0,-2),(0,-2), 0.5, BORDER),
    ]))

    bottom_tbl = Table([[tc_inner, sig_inner]], colWidths=[TC_W, SIG_W])
    bottom_tbl.setStyle(TableStyle([
        ('BOX',           (0,0),(-1,-1), 0.8, BORDER),
        ('LINEBEFORE',    (1,0),(1,-1),  0.8, BORDER),
        ('TOPPADDING',    (0,0),(-1,-1), 5),
        ('BOTTOMPADDING', (0,0),(-1,-1), 5),
        ('LEFTPADDING',   (0,0),(-1,-1), 6),
        ('RIGHTPADDING',  (0,0),(-1,-1), 6),
        ('VALIGN',        (0,0),(-1,-1), 'TOP'),
    ]))
    elements.append(bottom_tbl)

    doc.build(elements)
    buffer.seek(0)
    return buffer
