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


def build_notice(parent_layout):
    """Build Fluent CardWidget source/license notice inside parent QLayout."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout
    from qfluentwidgets import BodyLabel, CaptionLabel, CardWidget, PushButton, StrongBodyLabel

    card = CardWidget()
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(6)

    lay.addWidget(StrongBodyLabel("مصادر الكتالوج وترخيص البيانات"))
    n_lbl = BodyLabel(AR_NOTICE)
    n_lbl.setWordWrap(True)
    lay.addWidget(n_lbl)

    a_lbl = CaptionLabel(ATTRIBUTION)
    a_lbl.setWordWrap(True)
    a_lbl.setAlignment(Qt.AlignLeft)
    lay.addWidget(a_lbl)

    l_lbl = CaptionLabel(AR_LIMITS)
    l_lbl.setWordWrap(True)
    lay.addWidget(l_lbl)

    links = QHBoxLayout()
    links.setSpacing(8)
    for title, url in SOURCES:
        b = PushButton(title)
        b.clicked.connect(lambda _c=False, u=url: open_source(u))
        links.addWidget(b)
    links.addStretch(1)
    lay.addLayout(links)

    parent_layout.addWidget(card)
    return card
