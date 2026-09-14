# -*- coding: utf-8 -*-
import os
import sqlite3
from functools import wraps
from io import BytesIO
from flask import Flask, render_template, request, redirect, url_for, jsonify, Response, session

from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from werkzeug.security import generate_password_hash, check_password_hash

def init_db():
    conn = sqlite3.connect('muhasebe.db') # Projede kullandığınız db dosya adı neyse
    cursor = conn.cursor()
    # cariler tablosunu yoksa oluşturan komut
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cariler (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unvan TEXT,
            telefon TEXT
            -- diğer sütunlarınızı buraya ekleyin
        )
    ''')
    conn.commit()
    conn.close()

# Uygulama başlarken tabloyu oluşturan fonksiyonu çalıştır
init_db()

app = Flask(__name__)

# Oturum (session) çerezlerini imzalamak için gizli anahtar.
# PythonAnywhere'de canlıya alırken bunu rastgele/uzun bir değerle değiştirin
# ve mümkünse ortam değişkeninden okuyun.
app.secret_key = os.environ.get('SECRET_KEY', 'NAZAKS-cok-gizli-anahtar-degistir-2026')

# Giriş Bilgileriniz
USERS = {
    "sumuas": generate_password_hash("786827")  # Kullanıcı Adı: sumuas | Şifre: 786827
}


def login_required(f):
    """Oturum açılmamışsa kullanıcıyı login sayfasına yönlendiren dekoratör."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        stored_hash = USERS.get(username)
        if stored_hash and check_password_hash(stored_hash, password):
            session['logged_in'] = True
            session['username'] = username
            next_url = request.form.get('next') or request.args.get('next') or url_for('index')
            return redirect(next_url)
        error = "Kullanıcı adı veya şifre hatalı."
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- TÜRKÇE FONT KAYDI (Windows + Linux / PythonAnywhere Uyumlu) ---
DEFAULT_FONT = 'Helvetica'
DEFAULT_FONT_BOLD = 'Helvetica-Bold'

font_candidates = [
    ('C:/Windows/Fonts/arial.ttf', 'C:/Windows/Fonts/arialbd.ttf'),
    ('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'),
    ('/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf')
]

for font_path, bold_path in font_candidates:
    if os.path.exists(font_path) and os.path.exists(bold_path):
        try:
            pdfmetrics.registerFont(TTFont('CustomFont', font_path))
            pdfmetrics.registerFont(TTFont('CustomFont-Bold', bold_path))
            DEFAULT_FONT = 'CustomFont'
            DEFAULT_FONT_BOLD = 'CustomFont-Bold'
            break
        except Exception:
            pass


def get_db():
    db_path = os.path.join(os.path.dirname(__file__), 'muhasebe.db')
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
@login_required
def index():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM cariler")
    cariler_raw = cursor.fetchall()
    
    cariler = []
    toplam_alacak = 0
    toplam_borc = 0
    
    for c in cariler_raw:
        c_id = c['id']
        cursor.execute("SELECT islem_turu, tutar FROM hareketler WHERE cari_id = ?", (c_id,))
        hareketler = cursor.fetchall()
        
        bakiye = 0
        for h in hareketler:
            tur = h['islem_turu']
            tutar = h['tutar'] or 0
            if tur in ['Alacak Yaz', 'Ödeme Yapıldı']:
                bakiye += tutar
            elif tur in ['Borç Yaz', 'Ödeme Alındı']:
                bakiye -= tutar
        
        if bakiye > 0:
            toplam_alacak += bakiye
        elif bakiye < 0:
            toplam_borc += abs(bakiye)
            
        telefon = c['telefon'] if 'telefon' in c.keys() else ''
        detay = c['detay'] if 'detay' in c.keys() else ''
        
        cariler.append((c['id'], c['unvan'], c['tip'], telefon, bakiye, detay))

    cursor.execute("""
        SELECT 
            h.id, 
            COALESCE(c.unvan, 'Bilinmeyen Cari') as unvan, 
            h.islem_turu, 
            h.tutar, 
            h.aciklama, 
            COALESCE(h.tarih, '-') as tarih, 
            h.cari_id 
        FROM hareketler h 
        LEFT JOIN cariler c ON h.cari_id = c.id 
        ORDER BY h.id DESC
    """)
    son_islemler_raw = cursor.fetchall()
    
    son_islemler = []
    toplam_ciro = 0
    
    for h in son_islemler_raw:
        son_islemler.append((
            h['id'], 
            h['unvan'], 
            h['islem_turu'], 
            h['tutar'], 
            h['aciklama'], 
            h['tarih'], 
            h['cari_id']
        ))
        if h['islem_turu'] == 'Alacak Yaz':
            toplam_ciro += h['tutar'] or 0

    cursor.execute("SELECT * FROM urunler")
    urunler_raw = cursor.fetchall()
    
    cursor.execute("SELECT * FROM receteler")
    recete_kalemleri_raw = cursor.fetchall()
    
    recete_kalemleri = [(r['id'], r['urun_id'], r['malzeme_adi'], r['maliyet']) for r in recete_kalemleri_raw]
    
    urunler = []
    for u in urunler_raw:
        u_id = u['id']
        maliyet = sum(r['maliyet'] for r in recete_kalemleri_raw if r['urun_id'] == u_id)
        urunler.append((u['id'], u['urun_adi'], u['satis_fiyati'], maliyet))

    conn.close()
    
    return render_template('index.html', 
                           cariler=cariler, 
                           son_islemler=son_islemler, 
                           urunler=urunler, 
                           recete_kalemleri=recete_kalemleri,
                           toplam_ciro=toplam_ciro,
                           toplam_alacak=toplam_alacak,
                           toplam_borc=toplam_borc)

@app.route('/cari_ekle', methods=['POST'])
@login_required
def cari_ekle():
    unvan = request.form.get('unvan')
    tip = request.form.get('tip')
    telefon = request.form.get('telefon')
    detay = request.form.get('detay')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO cariler (unvan, tip, telefon, detay) VALUES (?, ?, ?, ?)", 
                   (unvan, tip, telefon, detay))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/cari_guncelle', methods=['POST'])
@login_required
def cari_guncelle():
    cari_id = request.form.get('cari_id')
    unvan = request.form.get('unvan')
    tip = request.form.get('tip')
    telefon = request.form.get('telefon')
    detay = request.form.get('detay')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE cariler SET unvan=?, tip=?, telefon=?, detay=? WHERE id=?", 
                   (unvan, tip, telefon, detay, cari_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/cari_sil/<int:id>')
@login_required
def cari_sil(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cariler WHERE id = ?", (id,))
    cursor.execute("DELETE FROM hareketler WHERE cari_id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/islem_ekle', methods=['POST'])
@login_required
def islem_ekle():
    cari_id = request.form.get('cari_id')
    islem_turu = request.form.get('islem_turu')
    tutar = float(request.form.get('tutar', 0))
    aciklama = request.form.get('aciklama')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO hareketler (cari_id, islem_turu, tutar, aciklama, tarih) VALUES (?, ?, ?, ?, datetime('now', 'localtime'))", 
                   (cari_id, islem_turu, tutar, aciklama))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/islem_sil/<int:id>')
@login_required
def islem_sil(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM hareketler WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/islem_duzenle', methods=['POST'])
@login_required
def islem_duzenle():
    islem_id = request.form.get('islem_id')
    islem_turu = request.form.get('islem_turu')
    tutar = float(request.form.get('tutar', 0))
    aciklama = request.form.get('aciklama')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE hareketler SET islem_turu = ?, tutar = ?, aciklama = ? WHERE id = ?", 
                   (islem_turu, tutar, aciklama, islem_id))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))
@app.route('/urunlu_fis_kes', methods=['POST'])
@login_required
def urunlu_fis_kes():
    cari_id = request.form.get('cari_id')
    urun_id_list = request.form.getlist('urun_id[]')
    adet_list = request.form.getlist('adet[]')
    
    iskonto_oran = float(request.form.get('iskonto_oran', 0) or 0)
    kdv_oran = float(request.form.get('kdv_oran', 0) or 0)
    
    conn = get_db()
    cursor = conn.cursor()
    
    ara_toplam = 0.0
    urun_detaylari = []
    
    # Seçilen ürünlerin fiyatlarını veritabanından çekip ara toplamı hesaplama
    for i in range(len(urun_id_list)):
        u_id = urun_id_list[i]
        if not u_id:
            continue
        adt = float(adet_list[i]) if i < len(adet_list) and adet_list[i] else 1.0
        
        cursor.execute("SELECT urun_adi, satis_fiyati FROM urunler WHERE id = ?", (u_id,))
        urun = cursor.fetchone()
        if urun:
            fiyat = urun['satis_fiyati'] or 0.0
            tutar = fiyat * adt
            ara_toplam += tutar
            urun_detaylari.append(f"{urun['urun_adi']} x{int(adt) if adt.is_integer() else adt}")
    
    # İskonto ve KDV Hesabı
    iskonto_tutar = ara_toplam * (iskonto_oran / 100.0)
    matrah = ara_toplam - iskonto_tutar
    kdv_tutar = matrah * (kdv_oran / 100.0)
    net_toplam = matrah + kdv_tutar
    
    # Hareket açıklaması oluşturma
    aciklama = f"Satış Fişi ({', '.join(urun_detaylari)})"
    if iskonto_oran > 0:
        aciklama += f" [İsk: %{iskonto_oran:.0f}]"
    if kdv_oran > 0:
        aciklama += f" [KDV: %{kdv_oran:.0f}]"
        
    # Bakiyeye işlemek üzere harekete kaydetme
    cursor.execute(
        "INSERT INTO hareketler (cari_id, islem_turu, tutar, aciklama, tarih) VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
        (cari_id, 'Alacak Yaz', net_toplam, aciklama)
    )
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))
    cari_id = request.form.get('cari_id')
    urun_id = request.form.get('urun_id')
    adet = int(request.form.get('adet', 1))
    islem_tipi = request.form.get('islem_tipi')

    cari = Cari.query.get(cari_id)
    urun = Urun.query.get(urun_id)

    if islem_tipi == 'satis_fisi':
        toplam_tutar = urun.fiyat * adet
        cari.bakiye -= toplam_tutar
    else:
        toplam_tutar = 0  # Sevk fişi: bakiye değişmez

    yeni_fis = Fis(
        cari_id=cari_id,
        urun_id=urun_id,
        adet=adet,
        toplam_tutar=toplam_tutar,
        is_sevk=(islem_tipi == 'sevk_fisi')
    )
    
    db.session.add(yeni_fis)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/fis-olustur', methods=['POST']) # veya uygulamanızdaki fiş oluşturma route'u
def fis_olustur():
    cari_id = request.form.get('cari_id')
    urun_id = request.form.get('urun_id')
    adet = int(request.form.get('adet', 1))
    
    # Hangi butona basıldığını yakalıyoruz: 'satis_fisi' mi 'sevk_fisi' mi?
    islem_tipi = request.form.get('islem_tipi')

    urun = Urun.query.get(urun_id)
    cari = Cari.query.get(cari_id)

    if islem_tipi == 'satis_fisi':
        # Normal Fiş: Fiyat hesaplanır ve bakiyeden düşülür
        toplam_tutar = urun.fiyat * adet
        cari.bakiye -= toplam_tutar
        is_sevk_fisi = False
    else:
        # Sevk Fişi: Tutar 0 kabul edilir, CARİ BAKİYE DEĞİŞMEZ
        toplam_tutar = 0
        is_sevk_fisi = True

    # Veritabanına kaydetme
    yeni_fis = Fis(
        cari_id=cari_id,
        urun_id=urun_id,
        adet=adet,
        toplam_tutar=toplam_tutar,
        is_sevk=is_sevk_fisi
    )
    
    db.session.add(yeni_fis)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/cari_ekstre/<int:cari_id>')
@login_required
def cari_ekstre(cari_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM cariler WHERE id = ?", (cari_id,))
    cari = cursor.fetchone()
    
    cursor.execute("SELECT id, islem_turu, tutar, aciklama, COALESCE(tarih, '-') as tarih FROM hareketler WHERE cari_id = ? ORDER BY id ASC", (cari_id,))
    islemler = cursor.fetchall()
    
    hareketler = []
    running_balance = 0
    
    for h in islemler:
        h_id = h['id']
        tur = h['islem_turu']
        tutar = h['tutar'] or 0
        aciklama = h['aciklama'] or '-'
        tarih = h['tarih']
        
        borc = 0
        alacak = 0
        
        if tur in ['Alacak Yaz', 'Ödeme Yapıldı']:
            alacak = tutar
            running_balance += tutar
        elif tur in ['Borç Yaz', 'Ödeme Alındı']:
            borc = tutar
            running_balance -= tutar
            
        hareketler.append({
            'id': h_id,
            'tarih': tarih,
            'islem_turu': tur,
            'aciklama': aciklama,
            'tutar': tutar,
            'borc': borc,
            'alacak': alacak,
            'bakiye': running_balance
        })
        
    conn.close()
    
    unvan = cari['unvan'] if cari else 'Bilinmeyen Cari'
    tip = cari['tip'] if cari else '-'
    telefon = (cari['telefon'] if cari and 'telefon' in cari.keys() else '') or '-'
    detay = (cari['detay'] if cari and 'detay' in cari.keys() else '')
    
    return jsonify({
        'cari': {
            'id': cari_id,
            'unvan': unvan,
            'tip': tip,
            'telefon': telefon,
            'detay': detay,
            'net_bakiye': running_balance
        },
        'hareketler': hareketler
    })

@app.route('/urun_ekle', methods=['POST'])
@login_required
def urun_ekle():
    urun_adi = request.form.get('urun_adi')
    satis_fiyati = float(request.form.get('satis_fiyati', 0))
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO urunler (urun_adi, satis_fiyati) VALUES (?, ?)", (urun_adi, satis_fiyati))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/urun_sil/<int:id>')
@login_required
def urun_sil(id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM urunler WHERE id = ?", (id,))
    cursor.execute("DELETE FROM receteler WHERE urun_id = ?", (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

@app.route('/recete_kalem_ekle', methods=['POST'])
@login_required
def recete_kalem_ekle():
    urun_id = request.form.get('urun_id')
    malzeme_adi = request.form.get('malzeme_adi')
    maliyet = float(request.form.get('maliyet', 0))
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO receteler (urun_id, malzeme_adi, maliyet) VALUES (?, ?, ?)", 
                   (urun_id, malzeme_adi, maliyet))
    conn.commit()
    conn.close()
    return redirect(url_for('index'))

# 📑 TEKLİF PDF OLUŞTURMA ROTASI
@app.route('/teklif_pdf', methods=['POST'])
@login_required
def teklif_pdf():
    cari_id = request.form.get('cari_id')
    sevk_yeri = request.form.get('sevk_yeri', '')
    teklif_no = request.form.get('teklif_no', 'DO001')
    para_birimi = request.form.get('para_birimi', 'USD')
    iskonto_oran = float(request.form.get('iskonto_oran', 0))
    kdv_oran = float(request.form.get('kdv_oran', 0))
    ozel_not = request.form.get('ozel_not', '')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cariler WHERE id = ?", (cari_id,))
    cari = cursor.fetchone()
    conn.close()

    musteri_unvan = cari['unvan'] if cari else 'ALICI FIRMA'

    aciklamalar_raw = request.form.getlist('aciklama[]')
    aciklamalar_manuel = request.form.getlist('aciklama_manuel[]')
    
    aciklamalar = []
    for idx, val in enumerate(aciklamalar_raw):
        if val == 'SERBEST_METIN' and idx < len(aciklamalar_manuel):
            aciklamalar.append(aciklamalar_manuel[idx])
        else:
            aciklamalar.append(val)
    adetler = request.form.getlist('adet[]')
    birimler = request.form.getlist('birim[]')
    fiyatlar = request.form.getlist('fiyat[]')
    notlar = request.form.getlist('not[]')

    symbol = '$' if para_birimi == 'USD' else ('€' if para_birimi == 'EUR' else 'TL ')

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=18, textColor=colors.HexColor('#1a365d'))
    right_title = ParagraphStyle('RightTitle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=16, alignment=2, textColor=colors.HexColor('#2b6cb0'))
    small_info = ParagraphStyle('SmallInfo', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=8, textColor=colors.HexColor('#555555'), leading=10)
    meta_label = ParagraphStyle('MetaLabel', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=8, textColor=colors.HexColor('#4a5568'))
    meta_val = ParagraphStyle('MetaVal', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=9, textColor=colors.HexColor('#1a202c'))

    # HEADER
    header_data = [
        [
            Paragraph("NAZ-AKS<br/><font size=8 color='#555555'>Aydınlatma ve Elektronik <br/>INEGOL/BURSA</font>", title_style),
            Paragraph("QUOTE / TEKLİF<br/><font size=9 color='#718096'>Tarih: <b>15/08/2026</b></font>", right_title)
        ]
    ]
    header_table = Table(header_data, colWidths=[300, 220])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    # META TABLE
    meta_data = [
        [Paragraph("BILL TO / ALICI", meta_label), Paragraph("SHIP TO / SEVK YERİ", meta_label), Paragraph("QUOTE / TEKLİF #", meta_label)],
        [Paragraph(musteri_unvan, meta_val), Paragraph(sevk_yeri, meta_val), Paragraph(teklif_no, meta_val)]
    ]
    meta_table = Table(meta_data, colWidths=[200, 170, 150])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # ITEMS TABLE STİLLERİ
    item_header_style = ParagraphStyle('IH', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=8, textColor=colors.white)
    item_body_style = ParagraphStyle('IB', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=8.5, textColor=colors.HexColor('#2d3748'))
    item_right_style = ParagraphStyle('IR', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=8.5, alignment=2, textColor=colors.HexColor('#2d3748'))

    items_data = [[
        Paragraph("QTY/ADET", item_header_style),
        Paragraph("UNIT/BİRİM", item_header_style),
        Paragraph("DESCRIPTION/AÇIKLAMA", item_header_style),
        Paragraph("PRICE/FİYAT", item_header_style),
        Paragraph("AMOUNT/TUTAR ", item_header_style)
    ]]

    sub_total = 0.0
    for i in range(len(aciklamalar)):
        if not aciklamalar[i].strip():
            continue
        adt = float(adetler[i]) if adetler[i] else 1.0
        brm = birimler[i]
        fyt = float(fiyatlar[i]) if fiyatlar[i] else 0.0
        amt = adt * fyt
        sub_total += amt

        desc_text = aciklamalar[i]
        if i < len(notlar) and notlar[i].strip():
            desc_text += f" <font color='#718096'>({notlar[i]})</font>"

        items_data.append([
            Paragraph(str(int(adt) if adt.is_integer() else adt), item_body_style),
            Paragraph(brm, item_body_style),
            Paragraph(desc_text, item_body_style),
            Paragraph(f"{symbol}{fyt:,.2f}", item_right_style),
            Paragraph(f"{symbol}{amt:,.2f}", item_right_style)
        ])

    items_table = Table(items_data, colWidths=[40, 45, 255, 90, 90])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2b6cb0')),
        ('ALIGN', (0,0), (-1,0), 'LEFT'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 15))

    iskonto_tutar = sub_total * (iskonto_oran / 100.0)
    ara_toplam = sub_total - iskonto_tutar
    kdv_tutar = ara_toplam * (kdv_oran / 100.0)
    genel_toplam = ara_toplam + kdv_tutar

    summary_data = [
        [Paragraph("Sub Total / Toplam", meta_label), Paragraph(f"{symbol}{sub_total:,.2f}", item_right_style)],
        [Paragraph(f"Dis. / İskonto ({iskonto_oran:.0f}%)", meta_label), Paragraph(f"-{symbol}{iskonto_tutar:,.2f}", item_right_style)],
        [Paragraph(f"Tax / KDV ({kdv_oran:.0f}%)", meta_label), Paragraph(f"{symbol}{kdv_tutar:,.2f}", item_right_style)],
        [Paragraph("<b>TOTAL / TOPLAM</b>", meta_label), Paragraph(f"<b>{symbol}{genel_toplam:,.2f}</b>", item_right_style)]
    ]

    summary_table = Table(summary_data, colWidths=[150, 100])
    summary_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('BACKGROUND', (0,-1), (-1,-1), colors.HexColor('#2b6cb0')),
        ('TEXTCOLOR', (0,-1), (-1,-1), colors.white),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))

    notes_p = Paragraph(f"<b>Notlar / Notes:</b><br/>{ozel_not}", small_info) if ozel_not else Paragraph("", small_info)

    bottom_wrapper = Table([[notes_p, summary_table]], colWidths=[270, 250])
    bottom_wrapper.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(bottom_wrapper)
    story.append(Spacer(1, 15))

    terms_html = """
    <b>TERMS & CONDITIONS / ÖN ŞARTLAR</b><br/>
    <b>Teslimat Yeri:</b> Fabrika Depomuz | <b>Ödeme Şekli:</b> Nakit<br/>
    <b>MOQ & İskonto:</b> MOQ&lt;10 iskonto uygulanmaz. 10&lt;MOQ&lt;50 %25 / 50&lt;MOQ&lt;100 %35 / 100&lt;MOQ&lt;500 %45<br/>
    <b>İskonto Kuralları:</b> Nakit iskontosu listeden maks. %45'dir. Vadeli ödemelerde aylık %1.67 oranında azalır. Maksimum vade 92 gündür.<br/>
    <b>İade & Değişim:</b> Sevki yapılmış olan ürün kalitesizlik nedeni dışında iade alınmaz, değiştirilmez.
    """
    terms_table = Table([[Paragraph(terms_html, small_info)]], colWidths=[520])
    terms_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 8),
    ]))
    story.append(terms_table)

    doc.build(story)
    buffer.seek(0)

    response = Response(buffer.getvalue(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'inline; filename=NAZAKS_Teklif_{teklif_no}.pdf'
    return response
# 📑 SEVK FİŞİ PDF OLUŞTURMA ROTASI
@app.route('/sevk_fisi_pdf', methods=['POST'])
@login_required
def sevk_fisi_pdf():
    cari_id = request.form.get('cari_id')
    sevk_no = request.form.get('sevk_no', 'SEVK001')
    teslim_tarihi = request.form.get('teslim_tarihi', '')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cariler WHERE id = ?", (cari_id,))
    cari = cursor.fetchone()
    conn.close()

    musteri_unvan = cari['unvan'] if cari else 'ALICI FIRMA'
    telefon = (cari['telefon'] if cari and 'telefon' in cari.keys() else '') or '-'
    detay = (cari['detay'] if cari and 'detay' in cari.keys() else '') or '-'

    urun_adlari = request.form.getlist('urun_adi[]')
    adetler = request.form.getlist('adet[]')

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=18, textColor=colors.HexColor('#1a365d'))
    right_title = ParagraphStyle('RightTitle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=16, alignment=2, textColor=colors.HexColor('#2b6cb0'))
    meta_label = ParagraphStyle('MetaLabel', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=8, textColor=colors.HexColor('#4a5568'))
    meta_val = ParagraphStyle('MetaVal', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=9, textColor=colors.HexColor('#1a202c'))

    # HEADER
    header_data = [
        [
            Paragraph("NAZAKS<br/><font size=8 color='#555555'>Aydınlatma ve Elektronik<br/>INEGOL/BURSA</font>", title_style),
            Paragraph("SEVK FİŞİ / DELIVERY NOTE", right_title)
        ]
    ]
    header_table = Table(header_data, colWidths=[300, 220])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    # CARİ VE FİŞ BİLGİLERİ
    meta_data = [
        [Paragraph("CARİ BİLGİLERİ", meta_label), Paragraph("SEVK / TESLİM BİLGİSİ", meta_label)],
        [
            Paragraph(f"<b>Ünvan:</b> {musteri_unvan}<br/><b>Tel:</b> {telefon}<br/><b>Adres:</b> {detay}", meta_val),
            Paragraph(f"<b>Sevk Fiş No:</b> {sevk_no}<br/><b>Teslim Tarihi:</b> {teslim_tarihi}", meta_val)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[260, 260])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # ÜRÜN LİSTESİ
    item_header_style = ParagraphStyle('IH', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=9, textColor=colors.white)
    item_body_style = ParagraphStyle('IB', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=9, textColor=colors.HexColor('#2d3748'))

    items_data = [[
        Paragraph("S.NO", item_header_style),
        Paragraph("ÜRÜN / MALZEME AÇIKLAMASI", item_header_style),
        Paragraph("MİKTAR / ADET", item_header_style)
    ]]

    for i in range(len(urun_adlari)):
        if not urun_adlari[i].strip():
            continue
        adt = adetler[i] if i < len(adetler) else "1"
        items_data.append([
            Paragraph(str(i + 1), item_body_style),
            Paragraph(urun_adlari[i], item_body_style),
            Paragraph(str(adt), item_body_style)
        ])

    items_table = Table(items_data, colWidths=[50, 370, 100])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#2b6cb0')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 40))

    # KARŞILIKLI İMZA SATIRI
    imza_data = [
        [Paragraph("<b>TESLİM EDEN (NAZAKS)</b>", meta_label), Paragraph("<b>TESLİM ALAN (MÜŞTERİ)</b>", meta_label)],
        [Paragraph("Adı Soyadı:<br/>İmza / Tarih:", meta_val), Paragraph("Adı Soyadı:<br/>İmza / Tarih:", meta_val)]
    ]
    imza_table = Table(imza_data, colWidths=[260, 260])
    imza_table.setStyle(TableStyle([
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 12),
    ]))
    story.append(imza_table)

    doc.build(story)
    buffer.seek(0)

    # Mobil görünüm için inline yerine attachment parametresi eklendi
    response = Response(buffer.getvalue(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=Sevk_Fisi_{sevk_no}.pdf'
    return response

# 📑 CARİ EKSTRE PDF OLUŞTURMA ROTASI
@app.route('/cari_ekstre_pdf/<int:cari_id>')
@login_required
def cari_ekstre_pdf(cari_id):
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM cariler WHERE id = ?", (cari_id,))
    cari = cursor.fetchone()
    
    cursor.execute("SELECT islem_turu, tutar, aciklama, COALESCE(tarih, '-') as tarih FROM hareketler WHERE cari_id = ? ORDER BY id ASC", (cari_id,))
    islemler = cursor.fetchall()
    conn.close()

    unvan = cari['unvan'] if cari else 'Bilinmeyen Cari'
    tip = cari['tip'] if cari else '-'
    telefon = (cari['telefon'] if cari and 'telefon' in cari.keys() else '') or '-'
    detay = (cari['detay'] if cari and 'detay' in cari.keys() else '') or '-'

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('TitleStyle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=18, textColor=colors.HexColor('#1a365d'))
    right_title = ParagraphStyle('RightTitle', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=16, alignment=2, textColor=colors.HexColor('#2b6cb0'))
    meta_label = ParagraphStyle('MetaLabel', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=8, textColor=colors.HexColor('#4a5568'))
    meta_val = ParagraphStyle('MetaVal', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=9, textColor=colors.HexColor('#1a202c'))

    header_data = [
        [
            Paragraph("NAZAKS<br/><font size=8 color='#555555'>Aydınlatma ve Elektronik <br/>INEGOL/BURSA</font>", title_style),
            Paragraph("CARİ HESAP EKSTRESİ<br/><font size=9 color='#718096'>Tarih: <b>15/08/2026</b></font>", right_title)
        ]
    ]
    header_table = Table(header_data, colWidths=[300, 220])
    header_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'TOP')]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    meta_data = [
        [Paragraph("CARİ UNVAN", meta_label), Paragraph("MÜŞTERİ TİPİ / TEL", meta_label), Paragraph("ADRES / DETAY", meta_label)],
        [Paragraph(unvan, meta_val), Paragraph(f"{tip} / {telefon}", meta_val), Paragraph(detay, meta_val)]
    ]
    meta_table = Table(meta_data, colWidths=[220, 150, 150])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('INNERGRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 6),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    item_header_style = ParagraphStyle('IH', parent=styles['Normal'], fontName=DEFAULT_FONT_BOLD, fontSize=8, textColor=colors.white)
    item_body_style = ParagraphStyle('IB', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=8.5, textColor=colors.HexColor('#2d3748'))
    item_right_style = ParagraphStyle('IR', parent=styles['Normal'], fontName=DEFAULT_FONT, fontSize=8.5, alignment=2, textColor=colors.HexColor('#2d3748'))

    table_data = [[
        Paragraph("TARİH", item_header_style),
        Paragraph("İŞLEM TÜRÜ", item_header_style),
        Paragraph("AÇIKLAMA", item_header_style),
        Paragraph("BORÇ", item_header_style),
        Paragraph("ALACAK", item_header_style),
        Paragraph("BAKİYE", item_header_style)
    ]]

    running_balance = 0.0
    for h in islemler:
        tur = h['islem_turu']
        tutar = h['tutar'] or 0.0
        aciklama = h['aciklama'] or '-'
        tarih = h['tarih']

        borc = 0.0
        alacak = 0.0

        if tur in ['Alacak Yaz', 'Ödeme Yapıldı']:
            alacak = tutar
            running_balance += tutar
        elif tur in ['Borç Yaz', 'Ödeme Alındı']:
            borc = tutar
            running_balance -= tutar

        borc_str = f"{borc:,.2f} TL" if borc > 0 else "-"
        alacak_str = f"{alacak:,.2f} TL" if alacak > 0 else "-"

        table_data.append([
            Paragraph(tarih, item_body_style),
            Paragraph(tur, item_body_style),
            Paragraph(aciklama, item_body_style),
            Paragraph(borc_str, item_right_style),
            Paragraph(alacak_str, item_right_style),
            Paragraph(f"{running_balance:,.2f} TL", item_right_style)
        ])

    ekstre_table = Table(table_data, colWidths=[90, 80, 160, 65, 65, 60])
    ekstre_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1a365d')),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e0')),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(ekstre_table)

    doc.build(story)
    buffer.seek(0)

    response = Response(buffer.getvalue(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=Cari_Ekstre_{unvan}.pdf'
    return response

if __name__ == '__main__':
    app.run(debug=True, port=5000)
