# -*- coding: utf-8 -*-
"""
Seed data for Pharmacy Enterprise v1.
~60 common Egyptian drugs. Prices are SAMPLE prices for testing only
— they are NOT official prices. Update them from supplier invoices
or the official printed price on the pack.
Barcodes are plausible SAMPLE EAN-13 numbers (622... = Egypt prefix),
generated for testing with a scanner / keyboard. They are NOT real
GTINs. Link a real barcode to a drug once, in the app, and every
later scan will find it.
"""
# (trade_en, trade_ar, scientific, company, form, strength,
#  category, strips_per_box, tablets_per_strip, buy_price, sell_price, min_stock)
SAMPLE_DRUGS = [
    ("Panadol", "بانادول", "Paracetamol", "GSK", "Tablets", "500 mg", "Analgesic", 2, 12, 18.00, 25.00, 10),
    ("Panadol Extra", "بانادول إكسترا", "Paracetamol + Caffeine", "GSK", "Tablets", "500 mg", "Analgesic", 2, 12, 45.00, 68.00, 10),
    ("Panadol Cold & Flu", "بانادول كولد آند فلو", "Paracetamol + Pseudoephedrine", "GSK", "Tablets", "500 mg", "Cold", 2, 12, 38.00, 55.00, 8),
    ("Augmentin", "أوجمنتين", "Amoxicillin + Clavulanic Acid", "GSK", "Tablets", "1 g", "Antibiotic", 2, 7, 135.00, 186.00, 5),
    ("Augmentin", "أوجمنتين", "Amoxicillin + Clavulanic Acid", "GSK", "Syrup", "457 mg/5ml", "Antibiotic", 1, 1, 85.00, 115.00, 5),
    ("Hibiotic", "هاي بيوتك", "Amoxicillin + Clavulanic Acid", "Amoun", "Tablets", "1 g", "Antibiotic", 2, 7, 95.00, 135.00, 5),
    ("Megamox", "ميجاموكس", "Amoxicillin + Clavulanic Acid", "Pharco", "Tablets", "1 g", "Antibiotic", 2, 7, 88.00, 125.00, 5),
    ("Amoxil", "أموكسيل", "Amoxicillin", "GSK", "Capsules", "500 mg", "Antibiotic", 2, 8, 42.00, 60.00, 5),
    ("Zithromax", "زيثروماكس", "Azithromycin", "Pfizer", "Tablets", "500 mg", "Antibiotic", 1, 3, 95.00, 135.00, 5),
    ("Xithrone", "زيثروين", "Azithromycin", "Amoun", "Tablets", "500 mg", "Antibiotic", 1, 3, 55.00, 78.00, 5),
    ("Cipro", "سيبرو", "Ciprofloxacin", "Amoun", "Tablets", "500 mg", "Antibiotic", 2, 10, 48.00, 68.00, 5),
    ("Flagyl", "فلاجيل", "Metronidazole", "Sanofi", "Tablets", "500 mg", "Antibiotic", 2, 10, 28.00, 40.00, 8),
    ("Antinal", "أنتينال", "Nifuroxazide", "Amoun", "Capsules", "200 mg", "Antidiarrheal", 2, 12, 30.00, 45.00, 8),
    ("Cataflam", "كاتافلام", "Diclofenac Potassium", "Novartis", "Tablets", "50 mg", "Anti-inflammatory", 2, 10, 55.00, 80.00, 8),
    ("Voltaren", "فولتارين", "Diclofenac Sodium", "Novartis", "Tablets", "50 mg", "Anti-inflammatory", 2, 10, 48.00, 70.00, 8),
    ("Brufen", "بروفين", "Ibuprofen", "Abbott", "Tablets", "400 mg", "Anti-inflammatory", 2, 10, 35.00, 50.00, 8),
    ("Celebrex", "سيليبريكس", "Celecoxib", "Pfizer", "Capsules", "200 mg", "Anti-inflammatory", 2, 10, 180.00, 250.00, 3),
    ("Aspirin", "أسبرين", "Acetylsalicylic Acid", "Bayer", "Tablets", "100 mg", "Antiplatelet", 2, 10, 15.00, 22.00, 10),
    ("Plavix", "بلافيكس", "Clopidogrel", "Sanofi", "Tablets", "75 mg", "Antiplatelet", 2, 14, 210.00, 290.00, 3),
    ("Concor", "كونكور", "Bisoprolol", "Merck", "Tablets", "5 mg", "Cardiac", 2, 15, 65.00, 92.00, 5),
    ("Norvasc", "نورفاسك", "Amlodipine", "Pfizer", "Tablets", "5 mg", "Cardiac", 2, 15, 75.00, 105.00, 5),
    ("Zestril", "زيستريل", "Lisinopril", "AstraZeneca", "Tablets", "10 mg", "Cardiac", 2, 14, 58.00, 82.00, 5),
    ("Lasix", "لازكس", "Furosemide", "Sanofi", "Tablets", "40 mg", "Diuretic", 2, 10, 22.00, 32.00, 5),
    ("Glucophage", "جلوكوفاج", "Metformin", "Merck", "Tablets", "500 mg", "Diabetes", 2, 15, 28.00, 40.00, 8),
    ("Glucophage XR", "جلوكوفاج إكس آر", "Metformin", "Merck", "Tablets", "1000 mg", "Diabetes", 2, 15, 55.00, 78.00, 8),
    ("Diamicron", "دياميكرون", "Gliclazide", "Servier", "Tablets", "60 mg", "Diabetes", 2, 15, 95.00, 135.00, 5),
    ("Januvia", "جانوفيا", "Sitagliptin", "MSD", "Tablets", "100 mg", "Diabetes", 2, 14, 420.00, 580.00, 3),
    ("Lipitor", "ليبيتور", "Atorvastatin", "Pfizer", "Tablets", "20 mg", "Cholesterol", 2, 15, 110.00, 155.00, 5),
    ("Atorvastatin", "أتورفاستاتين", "Atorvastatin", "Amoun", "Tablets", "20 mg", "Cholesterol", 2, 15, 55.00, 78.00, 5),
    ("Nexium", "نيكسيوم", "Esomeprazole", "AstraZeneca", "Tablets", "40 mg", "Gastric", 2, 7, 165.00, 230.00, 5),
    ("Omeprazole", "أوميبرازول", "Omeprazole", "Amoun", "Capsules", "20 mg", "Gastric", 2, 7, 38.00, 55.00, 5),
    ("Controloc", "كونترولوك", "Pantoprazole", "Takeda", "Tablets", "40 mg", "Gastric", 2, 7, 95.00, 135.00, 5),
    ("Ventolin", "فنتولين", "Salbutamol", "GSK", "Inhaler", "100 mcg", "Respiratory", 1, 1, 65.00, 92.00, 5),
    ("Singulair", "سينجولير", "Montelukast", "MSD", "Tablets", "10 mg", "Respiratory", 2, 7, 195.00, 270.00, 3),
    ("Zyrtec", "زيرتك", "Cetirizine", "UCB", "Tablets", "10 mg", "Antihistamine", 2, 10, 45.00, 65.00, 8),
    ("Claritin", "كلاريتين", "Loratadine", "Bayer", "Tablets", "10 mg", "Antihistamine", 2, 10, 48.00, 68.00, 8),
    ("Telfast", "تلفاست", "Fexofenadine", "Sanofi", "Tablets", "120 mg", "Antihistamine", 2, 10, 65.00, 92.00, 8),
    ("Otrivin", "أوتريفين", "Xylometazoline", "GSK", "Nasal Drops", "0.1%", "Cold", 1, 1, 28.00, 40.00, 8),
    ("Rhinostop", "رينوستوب", "Pseudoephedrine + Chlorpheniramine", "Amoun", "Syrup", "120 ml", "Cold", 1, 1, 22.00, 32.00, 8),
    ("Congestal", "كونجستال", "Paracetamol + Pseudoephedrine", "Sigma", "Tablets", "500 mg", "Cold", 2, 10, 25.00, 36.00, 8),
    ("123", "وان تو ثري", "Paracetamol + Pseudoephedrine", "Pharco", "Tablets", "500 mg", "Cold", 2, 10, 22.00, 32.00, 8),
    ("Strepsils", "ستربسلز", "Amylmetacresol + Dichlorobenzyl", "Reckitt", "Lozenges", "24", "Throat", 1, 24, 38.00, 55.00, 8),
    ("Betadine", "بيتادين", "Povidone Iodine", "Mundipharma", "Solution", "120 ml", "Antiseptic", 1, 1, 32.00, 46.00, 5),
    ("Fucidin", "فيوسيدين", "Fusidic Acid", "Leo", "Cream", "15 g", "Dermatology", 1, 1, 55.00, 78.00, 5),
    ("Kenacomb", "كيناكومب", "Triamcinolone + Neomycin", "GSK", "Cream", "15 g", "Dermatology", 1, 1, 28.00, 40.00, 5),
    ("Panthenol", "بانثينول", "Dexpanthenol", "Amoun", "Cream", "30 g", "Dermatology", 1, 1, 22.00, 32.00, 8),
    ("Bepanthen", "بيبانثين", "Dexpanthenol", "Bayer", "Cream", "30 g", "Dermatology", 1, 1, 48.00, 68.00, 5),
    ("Vitamin C", "فيتامين سي", "Ascorbic Acid", "Amoun", "Tablets", "1000 mg", "Vitamins", 1, 10, 30.00, 45.00, 8),
    ("Centrum", "سينتروم", "Multivitamins", "Pfizer", "Tablets", "30", "Vitamins", 1, 30, 220.00, 310.00, 3),
    ("Neurobion", "نيوروبيون", "Vitamin B Complex", "Merck", "Tablets", "10", "Vitamins", 2, 10, 55.00, 78.00, 5),
    ("Milga", "ميلجا", "Benfotiamine + B12", "Eva Pharma", "Tablets", "30", "Vitamins", 1, 30, 75.00, 105.00, 5),
    ("Depovit", "ديبوفيت", "Vitamin B12", "Amoun", "Ampoules", "3", "Vitamins", 1, 3, 35.00, 50.00, 5),
    ("Calcimax", "كالسي ماكس", "Calcium + Vitamin D", "Amoun", "Tablets", "30", "Vitamins", 1, 30, 65.00, 92.00, 5),
    ("Lyrica", "ليريكا", "Pregabalin", "Pfizer", "Capsules", "75 mg", "Neurology", 2, 14, 240.00, 335.00, 3),
    ("Neurontin", "نيورونتين", "Gabapentin", "Pfizer", "Capsules", "300 mg", "Neurology", 2, 15, 180.00, 250.00, 3),
    ("Cipralex", "سيبرالكس", "Escitalopram", "Lundbeck", "Tablets", "10 mg", "Psychiatry", 2, 14, 260.00, 360.00, 3),
    ("Arcoxia", "أركوكسيا", "Etoricoxib", "MSD", "Tablets", "90 mg", "Anti-inflammatory", 2, 7, 145.00, 200.00, 3),
    ("Fosamax", "فوساماكس", "Alendronate", "MSD", "Tablets", "70 mg", "Bone", 1, 4, 195.00, 270.00, 3),
    ("One Alpha", "وان ألفا", "Alfacalcidol", "Leo", "Capsules", "0.5 mcg", "Bone", 2, 15, 85.00, 120.00, 3),
    ("Decancit", "ديكانست", "Vitamin D3", "Amoun", "Tablets", "50000 IU", "Vitamins", 1, 4, 45.00, 65.00, 5),
]

def sample_barcode(index):
    """Deterministic plausible SAMPLE EAN-13, 622 + zero-padded index."""
    return "622%010d" % (100000 + index * 7)
