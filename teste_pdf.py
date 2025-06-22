from fpdf import FPDF

def gerar_pdf():
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, txt="Teste de PDF funcionando!", ln=True)
    pdf.output("teste.pdf")
    print("PDF gerado com sucesso!")

if __name__ == "__main__":
    gerar_pdf()
