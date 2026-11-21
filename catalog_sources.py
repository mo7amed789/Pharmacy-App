"""Visible notices for the open product-reference catalog. No network or DB writes."""
import webbrowser

SOURCES = (
    ("Open Beauty Facts", "https://world.openbeautyfacts.org/data"),
    ("Open Products Facts", "https://us.openproductsfacts.org/data"),
    ("ODbL 1.0", "https://opendatacommons.org/licenses/odbl/1-0/"),
)
ATTRIBUTION = (
    "Contains data from Open Beauty Facts and Open Products Facts, "
    "available under the Open Database License (ODbL 1.0)."
)
AR_NOTICE = (
    "مصادر الكتالوج المفتوح: Open Beauty Facts وOpen Products Facts. "
    "الترخيص ODbL 1.0 للبيانات وDbCL للمحتوى. عند توزيع كتالوج مشتق "
    "يجب الحفاظ على نسب المصدر ومتطلبات المشاركة بالمثل. "
    "صور المنتجات لها ترخيص مستقل؛ لا تُضمَّن في دفعات البيانات الحالية."
)
AR_LIMITS = (
    "المصادر مفتوحة وتعاونية، وليست اعتماداً من GS1 أو هيئة الدواء. "
    "السعر غير المعروف ليس سعراً رسمياً؛ راجع السعر وبيانات العبوة قبل البيع. "
    "مخزون الصيدلية والمبيعات والعملاء بيانات خاصة، وليست جزءاً من كتالوج المرجع الموزّع."
)


def open_source(url):
    """Only open one of the fixed source/license links on an explicit click."""
    if url not in {item[1] for item in SOURCES}:
        raise ValueError("Unknown catalog source URL")
    return webbrowser.open(url)


def build_notice(parent):
    """Scrollable settings owns layout; this section never starts a sync."""
    from tkinter import ttk
    frame = ttk.LabelFrame(parent, text="مصادر الكتالوج وترخيص البيانات", padding=10)
    frame.pack(fill="x", anchor="w", pady=8)
    ttk.Label(frame, text=AR_NOTICE, wraplength=620, justify="right").pack(anchor="w", fill="x")
    ttk.Label(frame, text=ATTRIBUTION, wraplength=620, justify="left").pack(anchor="w", fill="x", pady=5)
    ttk.Label(frame, text=AR_LIMITS, wraplength=620, justify="right").pack(anchor="w", fill="x", pady=4)
    links = ttk.Frame(frame)
    links.pack(anchor="w", pady=4)
    for title, url in SOURCES:
        ttk.Button(links, text=title, command=lambda u=url: open_source(u)).pack(side="left", padx=(0, 6))
    return frame
