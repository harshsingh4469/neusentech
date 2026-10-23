"""
Creates two FAKE practice PDFs so you can test the pipeline before using real documents:
  tests/sample_who_gmp.pdf  - looks like a CDSCO WHO-GMP list
  tests/sample_ec.pdf       - looks like an EC letter with a product table and raw-material table
All company names and numbers are invented ("Demo ..."). Never load these into your real data.

    python3 tests/make_sample_pdfs.py
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
ss = getSampleStyleSheet()
grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])


def who_gmp():
    rows = [["S. No.", "Sub Sr. No.", "Name of the firm", "Address of WHO-GMP certified manufacturer",
             "Category of Drugs permitted"],
            ["", "", "Gujarat", "", ""],
            ["1", "1", "M/s Demo Pharma Ltd", "Plot 12, GIDC Ankleshwar, Bharuch", "Analgesic, Antipyretic"],
            ["2", "2", "M/s Demo Formulations Pvt Ltd", "Survey 45, Changodar, Ahmedabad", "Tablets, Capsules"],
            ["", "", "Telangana", "", ""],
            ["3", "1", "M/s Demo Pharma Limited", "Sy No 10, Jeedimetla, Hyderabad", "Antidiabetic"]]
    t = Table(rows, colWidths=[30, 40, 150, 190, 110]); t.setStyle(grid)
    SimpleDocTemplate(str(HERE / "sample_who_gmp.pdf"), pagesize=A4).build(
        [Paragraph("WHO-GMP Certified Manufacturing Units (PRACTICE FILE)", ss["Title"]), t])


def ec():
    story = [Paragraph("Subject: Grant of Environmental Clearance (PRACTICE FILE - invented data)", ss["Heading2"]),
             Paragraph("Name of Company: M/s Demo Pharma Ltd", ss["Normal"]),
             Paragraph("Location of Project: Plot 12, GIDC Ankleshwar, Bharuch", ss["Normal"]),
             Paragraph("Date: 15/03/2024", ss["Normal"]), Spacer(1, 12),
             Paragraph("List of products", ss["Heading3"])]
    prod = Table([["Sr. No.", "Name of the Product", "Existing (MT/Month)", "Proposed (MT/Month)", "Total (MT/Month)"],
                  ["1", "Paracetamol", "100", "50", "150"],
                  ["2", "Metformin Hydrochloride", "20", "10", "30"],
                  ["", "Total", "120", "60", "180"]], colWidths=[40, 150, 100, 100, 100])
    prod.setStyle(grid)
    story += [prod, Spacer(1, 20), Paragraph("Raw material consumption for Paracetamol", ss["Heading3"])]
    rm = Table([["Sr. No.", "Name of Raw Material", "Consumption (Kg/Kg)"],
                ["1", "Para Amino Phenol", "0.75"],
                ["2", "Acetic Anhydride", "0.72"],
                ["3", "Activated Carbon", "0.01"]], colWidths=[40, 200, 120])
    rm.setStyle(grid)
    story += [rm, Spacer(1, 20), Paragraph("Raw material consumption for Metformin Hydrochloride", ss["Heading3"])]
    rm2 = Table([["Sr. No.", "Name of Raw Material", "Quantity (MT/Month)"],
                 ["1", "Dicyandiamide", "21"],
                 ["2", "Dimethylamine Hydrochloride", "21.6"]], colWidths=[40, 200, 120])
    rm2.setStyle(grid)
    story.append(rm2)
    SimpleDocTemplate(str(HERE / "sample_ec.pdf"), pagesize=A4).build(story)


if __name__ == "__main__":
    who_gmp(); ec()
    print("Created tests/sample_who_gmp.pdf and tests/sample_ec.pdf (invented practice data)")
