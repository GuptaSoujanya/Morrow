"""Small valid PDFs generated entirely from synthetic text for regression tests."""


def pdf_bytes(text="Synthetic Person - Python engineer", pages=1):
    escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.splitlines()]
    content = ("BT /F1 12 Tf 14 TL 72 720 Td " + " ".join("(" + line + ") Tj T*" for line in escaped) + " ET").encode("ascii") if text else b""
    page_ids = [5 + index for index in range(pages)]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        ("<< /Type /Pages /Count %d /Kids [%s] >>" % (pages, " ".join("%d 0 R" % number for number in page_ids))).encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        *[b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents 4 0 R >>" for _ in page_ids],
    ]
    document = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(document))
        document += str(index).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(document)
    document += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)).encode()
    document += b"".join(("%010d 00000 n \n" % offset).encode() for offset in offsets[1:])
    document += ("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)).encode()
    return document
